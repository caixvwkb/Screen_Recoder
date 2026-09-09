"""ASR 语音识别模块：sherpa-onnx + SenseVoice（外置模型目录热加载）。

对标 ocr.py 的结构设计：
- 模型目录默认 `models/asr/`（model.int8.onnx + tokens.txt），可显式指定任意目录；
- thread-local 缓存识别器，目录变化自动重建（换模型文件即生效）；
- 日志打印模型来源（控制台 + asr.log），每个来源只打一次；
- 音频解码：soundfile 直读 wav/flac/ogg/opus/mp3；其他格式或视频用
  imageio-ffmpeg 自带的 ffmpeg 转成 16k 单声道 wav（无需系统安装 ffmpeg）。
"""
import os
import re
import subprocess
import sys
import tempfile
import threading
import tracelog
from datetime import datetime

import numpy as np

SAMPLE_RATE = 16000  # SenseVoice 固定输入采样率

# SenseVoice 长音频必须分段识别：整段一次喂给 encoder 时，self-attention
# 矩阵 L×L 随音频时长平方增长（几分钟课堂录音 → 数十 GB 中间 buffer 直接 OOM）。
# 单段不超过 30s（SenseVoice 训练窗口上限），段间重叠 1s 避免切在词中间丢字。
CHUNK_SECONDS = 30.0
CHUNK_OVERLAP_SECONDS = 1.0

# SenseVoice 模型目录需要的文件（缺一视为模型目录不完整）
# 默认值；若目录内存在 config.json 则以配置为准（见 _load_asr_config）
ASR_FILES = ["model.int8.onnx", "tokens.txt"]

# 模型来源日志去重（多线程加载只打一次避免刷屏；输出统一走 tracelog → trace.log）
_logged_sources = set()
_log_lock = threading.Lock()

_recognizer_local = threading.local()
_punctuator_local = threading.local()


def _load_asr_config(model_dir: str) -> dict:
    """读取 models/<dir>/config.json（相对路径配置模型组成）。

    文件不存在/解析失败返回空 dict（调用方回退默认硬编码）。
    支持的键（均为相对 model_dir 的路径/文件名）：
      model_file / tokens_file —— ASR 主模型与词表；
      punct_dir / punct_file   —— 标点模型子目录与文件名。
    """
    if not model_dir:
        return {}
    p = os.path.join(model_dir, "config.json")
    if not os.path.isfile(p):
        return {}
    try:
        import json
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError("config.json 顶层必须是 JSON 对象")
        return cfg
    except Exception as e:
        tracelog.warn(f"[ASR] config.json 读取失败（使用默认配置）: {e}")
        return {}


def _cfg_source_label(model_dir: str) -> str:
    """配置来源标注：config.json（外置） vs 内置默认（无 config.json）。"""
    if model_dir and os.path.isfile(os.path.join(model_dir, "config.json")):
        return "config.json（外置）"
    return "内置默认（无 config.json）"


def _cfg_required_files(cfg: dict) -> list:
    """目录完整性校验清单：config.json 指定 > 默认 ASR_FILES。"""
    mf = (cfg.get("model_file") or "").strip()
    tf = (cfg.get("tokens_file") or "").strip()
    if mf and tf:
        return [mf, tf]
    return list(ASR_FILES)


def _log_engine_source(source: str):
    """每个模型来源只打印一次详细日志（多线程并发加载去重防刷屏）。"""
    with _log_lock:
        if source in _logged_sources:
            return
        _logged_sources.add(source)
    tracelog.info(source)


def models_complete(model_dir: str) -> bool:
    """模型目录是否包含 SenseVoice 全部必需文件（config.json 指定 > 默认清单）。"""
    if not model_dir or not os.path.isdir(model_dir):
        return False
    required = _cfg_required_files(_load_asr_config(model_dir))
    return all(os.path.isfile(os.path.join(model_dir, n)) for n in required)


def resolve_model_dir(explicit_dir: str = "") -> str:
    """解析外置 ASR 模型目录：显式指定 > 自动探测 > None。

    自动探测顺序（按用途分目录的结构）：
      1. 打包后 exe 同级 models/asr/；
      2. 源码运行则项目根 models/asr/。
    返回目录路径；None 表示没有可用外置目录（ASR 不可用）。
    """
    if explicit_dir and models_complete(explicit_dir):
        return explicit_dir
    # 自动探测：多候选根（exe 同级 / 项目根 / 各自父级），兼容 Nuitka/PyInstaller
    from paths import app_base_candidates
    candidates = []
    for root in app_base_candidates():
        candidates.append(os.path.join(root, "models", "asr"))
    for c in candidates:
        if models_complete(c):
            tracelog.info(f"[ASR] 模型目录选定: {c}")
            return c
    tracelog.warn(f"[ASR] 未找到外置模型目录（已探测 {len(candidates)} 个候选，均不完整）: {candidates}")
    return None


def get_recognizer(model_dir: str = "") -> object:
    """获取（缓存的）SenseVoice 离线识别器；失败返回 None。

    thread-local 缓存 key 为模型目录——切换目录/替换模型文件后自动重建。
    """
    key = explicit_dir = (model_dir or "").strip()
    rec = getattr(_recognizer_local, "rec", None)
    rec_key = getattr(_recognizer_local, "rec_key", None)
    if rec is not None and rec_key == key:
        return rec if rec is not False else None
    try:
        import sherpa_onnx
    except ImportError:
        tracelog.error("[ASR] sherpa-onnx 未安装，ASR 功能不可用（pip install sherpa-onnx）")
        _recognizer_local.rec = False
        _recognizer_local.rec_key = key
        return None

    resolved = resolve_model_dir(explicit_dir)
    if not resolved:
        tracelog.warn("[ASR] 未找到外置模型目录 models/asr/，ASR 功能不可用")
        _recognizer_local.rec = False
        _recognizer_local.rec_key = key
        return None

    try:
        cfg = _load_asr_config(resolved)
        kwargs = dict(
            model=os.path.join(resolved, cfg.get("model_file") or "model.int8.onnx"),
            tokens=os.path.join(resolved, cfg.get("tokens_file") or "tokens.txt"),
            num_threads=1,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            use_itn=True,
            debug=False,
        )
        try:  # 新版支持 language 参数
            _recognizer_local.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                language="auto", **kwargs)
        except TypeError:
            _recognizer_local.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(**kwargs)
        _recognizer_local.rec_key = key
        _log_engine_source(
            f"[ASR] ASR 引擎加载成功：本地外置模型 {os.path.normpath(resolved)}\n"
            f"      模型: {cfg.get('model_file') or 'model.int8.onnx'}（SenseVoice int8，中英日韩粤）\n"
            f"      配置来源: {_cfg_source_label(resolved)}")
    except Exception as e:
        tracelog.error(f"[ASR] ASR 引擎加载失败: {e}")
        _recognizer_local.rec = False
        _recognizer_local.rec_key = key
    return _recognizer_local.rec if _recognizer_local.rec is not False else None


def get_punctuator(model_dir: str = "") -> object:
    """获取（缓存的）CT-Transformer 标点恢复模型；模型缺失/加载失败返回 None。

    标点模型为后处理（只加标点、不改识别文字），放在 ASR 模型目录的
    `punct/` 子目录：`<asr_dir>/punct/model.int8.onnx`（sherpa-onnx 官方
    punct-ct-transformer zh-en int8，72MB）。缺失时 ASR 照常工作，
    仅输出无标点文本（回退 60 字硬切）。thread-local 缓存，按目录自动重建。
    """
    key = explicit_dir = (model_dir or "").strip()
    punc = getattr(_punctuator_local, "punc", None)
    punc_key = getattr(_punctuator_local, "punc_key", None)
    if punc is not None and punc_key == key:
        return punc if punc is not False else None
    resolved = resolve_model_dir(explicit_dir)
    if not resolved:
        return None
    cfg = _load_asr_config(resolved)
    punct_dir = cfg.get("punct_dir") or "punct"
    punct_file = cfg.get("punct_file") or "model.int8.onnx"
    model_path = os.path.join(resolved, punct_dir, punct_file)
    if not os.path.isfile(model_path):
        tracelog.info(f"[ASR] 标点模型未找到（{model_path}），跳过标点恢复（无标点输出）")
        _punctuator_local.punc = False
        _punctuator_local.punc_key = key
        return None
    try:
        import sherpa_onnx
        cfg = sherpa_onnx.OfflinePunctuationConfig(
            model=sherpa_onnx.OfflinePunctuationModelConfig(
                ct_transformer=model_path, num_threads=1))
        _punctuator_local.punc = sherpa_onnx.OfflinePunctuation(cfg)
        _punctuator_local.punc_key = key
        tracelog.info(
            f"[ASR] 标点模型加载成功: {model_path}（配置来源: {_cfg_source_label(resolved)}）")
    except Exception as e:
        tracelog.error(f"[ASR] 标点模型加载失败: {e}")
        _punctuator_local.punc = False
        _punctuator_local.punc_key = key
    return _punctuator_local.punc if _punctuator_local.punc is not False else None


def _clean_special_tokens(text: str) -> str:
    """清理 SenseVoice 输出的特殊标记（<|zh|>、<|NEUTRAL|>、<|Speech|> 等）。"""
    return re.sub(r"<\|[^|]+\|>", "", text or "").strip()


def _read_wav_16k(audio_path: str):
    """用 soundfile 读音频为 16k 单声道 float32（支持 wav/flac/ogg/opus/mp3）。"""
    import soundfile as sf
    samples, sr = sf.read(audio_path, dtype="float32", always_2d=False)
    if samples.ndim > 1:  # 立体声 → 单声道（取均值）
        samples = samples.mean(axis=1)
    if sr != SAMPLE_RATE:  # 重采样到 16k（线性插值，轻量够用）
        n_out = max(1, int(round(len(samples) * SAMPLE_RATE / sr)))
        x_old = np.linspace(0.0, 1.0, len(samples), endpoint=False)
        x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
        samples = np.interp(x_new, x_old, samples).astype(np.float32)
    return samples


def _decode_with_ffmpeg(audio_path: str):
    """用 imageio-ffmpeg 自带的 ffmpeg 把任意音频/视频转成 16k 单声道 wav。

    返回临时 wav 路径（调用方负责删除）；失败返回 None。
    """
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    from paths import cache_dir
    fd, tmp = tempfile.mkstemp(dir=cache_dir(), suffix=".wav")
    os.close(fd)
    try:
        r = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", audio_path,
             "-ar", str(SAMPLE_RATE), "-ac", "1", "-f", "wav", tmp],
            capture_output=True, timeout=600)
        if r.returncode != 0 or not os.path.getsize(tmp):
            os.unlink(tmp)
            return None
        return tmp
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        return None


import re

_SENT_SPLIT = re.compile(r"(?<=[。！？；…])(?![…])")  # 按句末标点切句（保留标点；连续省略号不切）
# 英文句点/问号/感叹号也参与切句（课堂录音以中文为主，英文标点作补充）
_SENT_SPLIT_EN = re.compile(r"(?<=[.!?])\s+")
# 当前 SenseVoice int8 模型不输出句读标点，超长句按此长度硬切（字幕行感）
_SENT_MAX_LEN = 60


def _split_sentences(text: str) -> list:
    """把一段文本切成句子列表：先按标点切，超长句再按 _SENT_MAX_LEN 硬切。

    保留句末标点，去空句；模型无标点输出时退化为定长分段。
    """
    parts = _SENT_SPLIT.split(text or "")
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # 英文句点切分（如 "Hello. World."）
        if re.search(r"[A-Za-z0-9]\.", p):
            sub = [x.strip() for x in _SENT_SPLIT_EN.split(p) if x.strip()]
            for s in sub:
                out.extend(_chunk_long(s))
        else:
            out.extend(_chunk_long(p))
    return out


def _chunk_long(s: str) -> list:
    """超长句按 _SENT_MAX_LEN 硬切（SenseVoice 无标点时保证行不超长）。"""
    if len(s) <= _SENT_MAX_LEN:
        return [s]
    return [s[i:i + _SENT_MAX_LEN] for i in range(0, len(s), _SENT_MAX_LEN)]


def _fmt_ts(sec: float) -> str:
    """秒 → HH:MM:SS.mmm（文件基准时间戳，SRT 风格）。"""
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        ms = 0
        s += 1
    if s >= 60:
        s = 0
        m += 1
    if m >= 60:
        m = 0
        h += 1
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _sentences_with_ts(text: str, seg_start_sec: float, seg_duration_sec: float) -> list:
    """段文本 → [(起始秒, 句子)]；句时间按字符占比在段内近似分配。

    当前 SenseVoice int8 模型不输出句级时间戳（segment_texts 为空），
    段起始时间精确（30s 粒度），句内时间按字符比例估算（误差数秒，用于定位）。
    """
    sents = _split_sentences(text)
    total = sum(len(s) for s in sents)
    if not sents or total == 0:
        return []
    out = []
    acc = 0
    for s in sents:
        ts = seg_start_sec + (acc / total) * seg_duration_sec
        out.append((ts, s))
        acc += len(s)
    return out


def _transcribe_one(recognizer, samples, seg_start_sec: float = 0.0,
                    seg_duration_sec: float = None, punctuator=None):
    """识别一段（≤30s）音频。

    返回 (text, [(起始秒, 句子), ...])；seg_duration_sec 缺省按采样数推算。
    punctuator 非空时对识别文本做标点恢复（只加标点不改字，失败自动跳过）。
    """
    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, samples)
    recognizer.decode_stream(stream)
    text = _clean_special_tokens(stream.result.text)
    if punctuator is not None and text:
        try:
            text = punctuator.add_punctuation(text)
        except Exception as e:
            tracelog.warn(f"[ASR] 标点恢复失败（跳过）: {e}")
    if seg_duration_sec is None:
        seg_duration_sec = len(samples) / SAMPLE_RATE
    return text, _sentences_with_ts(text, seg_start_sec, seg_duration_sec)


def _load_samples(audio_path: str):
    """解码音频/视频为 16k 单声道 float32；失败返回 None。

    返回 (samples, decode_via)，decode_via ∈ {"soundfile", "ffmpeg"}。
    """
    try:
        samples = _read_wav_16k(audio_path)
        return samples, "soundfile"
    except Exception:
        pass
    wav_path = _decode_with_ffmpeg(audio_path)
    if not wav_path:
        return None
    try:
        samples = _read_wav_16k(wav_path)
        return samples, "ffmpeg"
    finally:
        if os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except OSError:
                pass


def _segment_ranges(n: int) -> list:
    """把 n 个采样点切成 (start, end) 段列表（段长 30s、步进 29s，末段不足 1s 跳过）。"""
    chunk_len = int(CHUNK_SECONDS * SAMPLE_RATE)
    hop = int((CHUNK_SECONDS - CHUNK_OVERLAP_SECONDS) * SAMPLE_RATE)
    ranges = []
    start = 0
    while start < n:
        end = min(n, start + chunk_len)
        if start > 0 and end - start < SAMPLE_RATE:
            break
        ranges.append((start, end))
        start += hop
    return ranges


def transcribe(audio_path: str, model_dir: str = "") -> str:
    """转写单个音频/视频文件，返回文字；失败返回空串并记日志。

    长音频按 CHUNK_SECONDS 分段识别后拼接（段间重叠 CHUNK_OVERLAP_SECONDS），
    避免 SenseVoice attention 矩阵随时间平方爆炸（OOM / 空结果）。
    单文件内部串行分段——批量场景请用 transcribe_parallel_segments（段级并行）。
    """
    recognizer = get_recognizer(model_dir)
    if recognizer is None:
        return ""
    try:
        tracelog.info(f"[ASR] 开始转写: {os.path.basename(audio_path)}（模型: {model_dir or '自动探测'}）")
        punctuator = get_punctuator(model_dir)
        loaded = _load_samples(audio_path)
        if loaded is None:
            raise RuntimeError("无法解码音频（格式不支持且无 ffmpeg 兜底）")
        samples, decode_via = loaded
        if len(samples) == 0:
            tracelog.warn(f"[ASR] 转写 {os.path.basename(audio_path)} 为空音频")
            return ""
        texts = []
        for start, end in _segment_ranges(len(samples)):
            try:
                t, _ = _transcribe_one(recognizer, samples[start:end],
                                       start / SAMPLE_RATE,
                                       (end - start) / SAMPLE_RATE,
                                       punctuator)
            except Exception as e:
                tracelog.error(f"[ASR] 分段识别失败（start={start}s）: {e}")
                t = ""
            if t:
                texts.append(t)
        text = "".join(texts)
        tracelog.info(f"[ASR] 完成: {os.path.basename(audio_path)}（{decode_via}，"
                      f"{len(texts)} 段，{len(text)} 字）")
        return text
    except Exception as e:
        tracelog.error(f"[ASR] 转写 {os.path.basename(audio_path)} 失败: {e}")
        return ""


def scan_asr_files(folder: str, formats, recursive: bool = True) -> list:
    """按「处理格式」白名单扫描文件夹中的音频/视频文件（正向过滤）。"""
    files = []
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        for name in sorted(names):
            ext = os.path.splitext(name)[1].lower().lstrip(".")
            if ext in formats:
                files.append(os.path.join(root, name))
        if not recursive:
            break
    return files


def write_asr_txt(audio_file: str, text: str, out_dir: str = None) -> str:
    """为单个音频/视频文件生成 <文件名>_语音转写.txt（纯文本，适配性最好）。

    out_dir: 指定输出目录（汇总输出用）；None/空 = 写在源文件同目录。
    内容为纯转写文字（无 Markdown 符号、无元信息头），任何编辑器/AI 直接可读。
    """
    text = (text or "").strip()
    if not text:
        return ""
    folder = out_dir or os.path.dirname(audio_file)
    os.makedirs(folder, exist_ok=True)
    base = os.path.splitext(os.path.basename(audio_file))[0]
    txt_name = f"{base}_语音转写.txt"
    txt_path = os.path.join(folder, txt_name)
    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        return txt_path
    except Exception as e:
        tracelog.error(f"[ASR] 写入 {txt_name} 失败: {e}")
        return ""


def _merge_file_sents(sents: list) -> str:
    """句子列表（乱序）→ 带时间戳文本（按起始时间排序）。"""
    sents = sorted(sents, key=lambda x: x[0])
    text = "".join(x[1] for x in sents)
    ts_text = "".join(f"[{_fmt_ts(ts)}] {sent}\n" for ts, sent in sents).strip()
    return ts_text or text


def is_transcribed(audio_file: str, out_dir: str = None) -> bool:
    """时间标签识别：输出 <名>_语音转写.txt 存在且修改时间 >= 源文件 → 已转写。

    用于未完成重传：批量转写前扫描，跳过已完成的文件（软件重启/打断后
    也能准确识别哪些已完成）。
    """
    folder = out_dir or os.path.dirname(audio_file)
    base = os.path.splitext(os.path.basename(audio_file))[0]
    txt = os.path.join(folder, f"{base}_语音转写.txt")
    if not os.path.isfile(txt):
        return False
    try:
        return os.path.getmtime(txt) >= os.path.getmtime(audio_file)
    except OSError:
        return False


def transcribe_parallel_segments(files, max_workers: int = 4, model_dir: str = "",
                                 on_file_done=None, on_segment_done=None,
                                 cancel_event=None) -> dict:
    """段级并行转写：文件 × 分段拍平成独立识别任务，统一线程池并行。

    - **两阶段**：全部文件先并行解码，解码全部就绪后才提交识别任务；
    - **交错提交**：按文件轮换提交段任务（f1s1, f2s1, f3s1, f1s2, …），
      多个文件的段同时进池、均匀推进，避免单个文件独占线程池；
    - **按文件即时完成**：某个文件的全部段完成 → 立即聚合并回调
      on_file_done（写文件/进度/提示按文件为单位，不等待全部文件）；
      中途失败只影响失败文件，已完成文件照常输出。

    返回 {文件路径: 转写文本}（解码失败/空音频 → 空串，不触发 on_file_done）。
    on_file_done(f, text)：每完成一个文件立即回调一次（文件进度/输出用）。
    on_segment_done(f, seg_done, seg_total)：每完成一段回调一次
    （seg_done/seg_total 为全局累计，一直自增）。
    cancel_event：threading.Event；置位时停止提交新段并取消未开始的段，
    已完成的文件照常触发 on_file_done（打断后已识别内容不丢）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
    results = {f: "" for f in files}
    if not files or max_workers < 1:
        return results
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            # ① 解码全部文件（并行；m4a/视频走 ffmpeg 转码也摊平），全部就绪后再切段
            load_futs = {pool.submit(_load_samples, f): f for f in files}
            loaded = {}
            for fut in as_completed(load_futs):
                f = load_futs[fut]
                try:
                    loaded[f] = fut.result()
                except Exception as e:
                    tracelog.error(f"[ASR] 解码失败 {os.path.basename(f)}: {e}")
                    loaded[f] = None

            # 每个文件的可识别段列表（解码成功且非空才参与）
            file_ranges = {}
            for f in files:
                data = loaded.get(f)
                if not data:
                    continue
                samples, via = data
                if len(samples) == 0:
                    continue
                file_ranges[f] = _segment_ranges(len(samples))
            seg_total = {f: len(r) for f, r in file_ranges.items()}
            g_total = sum(seg_total.values()) or 1

            def recognize_seg(samples, start, end):
                rec = get_recognizer(model_dir)  # 每线程独立实例，非线程安全
                if rec is None:
                    return "", []
                punc = get_punctuator(model_dir)
                try:
                    return _transcribe_one(rec, samples[start:end], start / SAMPLE_RATE,
                                           (end - start) / SAMPLE_RATE, punc)
                except Exception as e:
                    tracelog.error(f"[ASR] 分段识别失败: {e}")
                    return "", []

            # ② 按文件轮换交错提交段任务（多文件均匀进池，避免独占）
            seg_futs = {}
            if file_ranges:
                max_segs = max(len(r) for r in file_ranges.values())
                for i in range(max_segs):
                    if cancel_event and cancel_event.is_set():
                        break
                    for f in files:
                        r = file_ranges.get(f)
                        if r and i < len(r):
                            start, end = r[i]
                            fut = pool.submit(recognize_seg, loaded[f][0], start, end)
                            seg_futs[fut] = (f, start)

            # ③ 段完成：全局累计计数 + 回调；某文件全部段完成 → 立即聚合输出
            seg_done = {}
            g_done = [0]
            file_sents = {}
            for fut in as_completed(seg_futs):
                if cancel_event and cancel_event.is_set():
                    for f2 in list(seg_futs):
                        if not f2.done():
                            f2.cancel()
                    break
                f, start = seg_futs[fut]
                try:
                    t, sents = fut.result()
                except CancelledError:
                    break
                except Exception:
                    t, sents = "", []
                if sents:
                    file_sents.setdefault(f, []).extend(sents)
                n_done = seg_done.get(f, 0) + 1
                seg_done[f] = n_done
                g_done[0] += 1
                # 段落级进度日志（乱序为完成顺序；等待长音频时可感知在推进）
                tracelog.info(f"[ASR] 段 {g_done[0]}/{g_total}（{os.path.basename(f)} "
                              f"{n_done}/{seg_total.get(f, 1)}）")
                if on_segment_done:
                    try:
                        on_segment_done(f, g_done[0], g_total)
                    except Exception:
                        pass
                # 该文件全部段完成 → 立即聚合、回调（写文件/进度/提示按文件为单位）
                if n_done == seg_total.get(f) and f in file_ranges:
                    results[f] = _merge_file_sents(file_sents.get(f, []))
                    if on_file_done:
                        try:
                            on_file_done(f, results[f])
                        except Exception:
                            pass
    except Exception as e:
        tracelog.error(f"[ASR] 批量转写出错: {e}")
    return results
