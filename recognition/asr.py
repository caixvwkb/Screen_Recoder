"""ASR 语音识别模块：sherpa-onnx + SenseVoice（外置模型目录热加载）。

对标 ocr.py 的结构设计：
- 模型目录默认 `models/asr/`（model.int8.onnx + tokens.txt），可显式指定任意目录；
- thread-local 缓存识别器，目录变化自动重建（换模型文件即生效）；
- 日志打印模型来源（控制台 + asr.log），每个来源只打一次；
- 音频解码：soundfile 直读 wav/flac/ogg/opus/mp3；其他格式或视频用
  imageio-ffmpeg 自带的 ffmpeg 转成 16k 单声道 wav（无需系统安装 ffmpeg）。
"""
import glob
import os
import re
import subprocess
import sys
import tempfile
import threading
import system.tracelog as tracelog
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
    from system.paths import app_base_candidates
    candidates = []
    for root in app_base_candidates():
        candidates.append(os.path.join(root, "models", "asr"))
    for c in candidates:
        if models_complete(c):
            tracelog.info(f"[ASR] 模型目录选定: {c}")
            return c
    tracelog.warn(f"[ASR] 未找到外置模型目录（已探测 {len(candidates)} 个候选，均不完整）: {candidates}")
    return None


_cuda_dll_ready = False


def _ensure_cuda_dlls() -> bool:
    """把 pip 安装的 NVIDIA CUDA 运行库 DLL 目录注入 PATH。

    sherpa-onnx 的 CUDA provider（onnxruntime_providers_cuda.dll）依赖系统
    cublasLt/cublas/cudart/cudnn/cufft/curand 等 DLL。用 pip 的
    nvidia-*-cu12 包可免装数 GB 的完整 CUDA Toolkit：DLL 在
    site-packages\nvidia\<pkg>\bin，注入 PATH 即可被 LoadLibrary 解析。
    返回是否成功注册（失败不影响 CPU 推理）。
    """
    global _cuda_dll_ready
    if _cuda_dll_ready:
        return True
    try:
        import site as _site
        dirs = []
        # 源码运行：pip 安装的 nvidia-*-cu12 包（site-packages\nvidia\<pkg>\bin）
        for sp in _site.getsitepackages():
            base = os.path.join(sp, "nvidia")
            if os.path.isdir(base):
                for d in glob.glob(os.path.join(base, "*", "bin")):
                    if os.path.isdir(d):
                        dirs.append(d)
        # 打包运行：exe 同级的 nvidia 目录（分发时随包携带即可免装 CUDA）
        try:
            from system.paths import app_base_candidates
            for root in app_base_candidates():
                base = os.path.join(root, "nvidia")
                if os.path.isdir(base):
                    for d in glob.glob(os.path.join(base, "*", "bin")):
                        if os.path.isdir(d) and d not in dirs:
                            dirs.append(d)
        except Exception:
            pass
        if dirs:
            os.environ["PATH"] = ";".join(dirs) + ";" + os.environ.get("PATH", "")
            _cuda_dll_ready = True
            tracelog.info(f"[ASR] CUDA 运行库目录已注入 PATH（{len(dirs)} 个）")
            return True
        tracelog.warn("[ASR] 未找到 NVIDIA CUDA 运行库（源码: pip nvidia-*-cu12；打包: exe 同级 nvidia/ 目录），GPU 推理不可用，将回退 CPU")
    except Exception as e:
        tracelog.warn(f"[ASR] CUDA DLL 目录探测失败: {e}")
    return False


def get_gpu_info():
    """查询第一张 NVIDIA 显卡显存。

    返回 (总显存MB, 当前可用MB)，无 NVIDIA 显卡 / 驱动未装 / 探测失败返回 None。
    用驱动自带的 nvml.dll（System32），无需额外安装。
    """
    import ctypes
    try:
        nvml = ctypes.WinDLL("nvml.dll")
        nvml.nvmlInit()
        handle = ctypes.c_void_p()
        if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
            nvml.nvmlShutdown()
            return None

        class MemInfo(ctypes.Structure):
            _fields_ = [("total", ctypes.c_ulonglong),
                        ("free", ctypes.c_ulonglong),
                        ("used", ctypes.c_ulonglong)]

        mem = MemInfo()
        if nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) != 0:
            nvml.nvmlShutdown()
            return None
        nvml.nvmlShutdown()
        return int(mem.total // (1024 * 1024)), int(mem.free // (1024 * 1024))
    except Exception:
        return None


def suggest_gpu_workers(reserve_mb: int = 1536, per_instance_mb: int = 950) -> int:
    """按当前可用显存推荐 GPU 并发数（并行的 GPU 推理实例数）。

    GPU 没有『核数』概念：并行的推理实例数受显存限制（每个 SenseVoice
    int8 推理 session 实测约 0.9GB：本机 2/4/6 路峰值显存 1913/3613/5313MB）。
    公式 = (可用显存 - 桌面/其他程序预留 1.5GB) / 单实例占用，向下取整，最少 1。
    推荐值本身已含显存预留（本机推荐 6，实测 6 路峰值 5.3GB 安全）；
    探测失败给保守默认 4。
    """
    info = get_gpu_info()
    if not info:
        return 4
    total_mb, free_mb = info
    return max(1, (free_mb - reserve_mb) // per_instance_mb)


def list_asr_models(root_dir: str = "") -> list:
    """扫描 ASR 模型根目录，返回可用模型列表。

    每个可用模型 = 一个子目录（含 config.json 且主模型文件存在）；
    根目录本身也算一个（兼容旧扁平结构，无 config.json 时按默认
    model.int8.onnx 判断）。返回 [{name, path, label}]；name 为
    config.json 的 name（显示名），label 为子目录名（"" = 根默认）。
    """
    from system.paths import app_base_candidates
    root = (root_dir or "").strip()
    if not root:
        root = resolve_model_dir("")
    if not root or not os.path.isdir(root):
        return []

    def _probe(d):
        cfg = _load_asr_config(d)
        mtype = str(cfg.get("model_type") or "sense_voice").strip().lower()
        if mtype == "whisper":
            f = cfg.get("whisper_encoder") or "encoder.onnx"
        else:
            f = cfg.get("model_file") or "model.int8.onnx"
        if os.path.isfile(os.path.join(d, f)):
            return cfg, mtype, f
        return None, mtype, f

    items = []
    cfg, mtype, f = _probe(root)
    if cfg is not None:
        items.append({
            "name": (cfg.get("name") or "").strip() or "默认（根目录）",
            "path": root,
            "label": "",
            "mtype": mtype,
        })
    for sub in sorted(os.listdir(root)):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        # 标点模型目录（punct/）不是独立 ASR 模型，跳过
        if sub.strip().lower() in ("punct", "punctuation"):
            continue
        cfg, mtype, f = _probe(d)
        if cfg is None:
            continue
        items.append({
            "name": (cfg.get("name") or "").strip() or sub,
            "path": d,
            "label": sub,
            "mtype": mtype,
        })
    return items


_cuda_probe_result = None   # None=未探测；True/False 缓存结果（只探测一次）


def _cuda_usable(model_dir: str = "") -> bool:
    """探测当前环境 GPU（CUDA）推理是否可用，模块级缓存只探测一次。

    轻量代价：首次调用会构建并丢弃一个识别器（约 1s）；批量转写开始时
    有 GPU 并发才调用，避免每个 GPU worker 线程各自失败重试/告警。
    """
    global _cuda_probe_result
    if _cuda_probe_result is not None:
        return _cuda_probe_result
    try:
        import sherpa_onnx
        _ensure_cuda_dlls()
        resolved = resolve_model_dir((model_dir or "").strip())
        if not resolved:
            _cuda_probe_result = False
            return False
        cfg = _load_asr_config(resolved)
        mtype = str(cfg.get("model_type") or "sense_voice").strip().lower()
        if mtype == "whisper":
            sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=os.path.join(resolved, cfg.get("whisper_encoder") or "encoder.onnx"),
                decoder=os.path.join(resolved, cfg.get("whisper_decoder") or "decoder.onnx"),
                tokens=os.path.join(resolved, cfg.get("tokens_file") or "tokens.txt"),
                language=str(cfg.get("whisper_language") or "zh"),
                task="transcribe", num_threads=1, provider="cuda")
        else:
            k = dict(
                model=os.path.join(resolved, cfg.get("model_file") or "model.int8.onnx"),
                tokens=os.path.join(resolved, cfg.get("tokens_file") or "tokens.txt"),
                num_threads=1, sample_rate=SAMPLE_RATE, feature_dim=80,
                use_itn=True, debug=False, provider="cuda")
            try:
                sherpa_onnx.OfflineRecognizer.from_sense_voice(language="auto", **k)
            except TypeError:
                sherpa_onnx.OfflineRecognizer.from_sense_voice(**k)
        _cuda_probe_result = True
    except Exception:
        _cuda_probe_result = False
    return _cuda_probe_result


def get_recognizer(model_dir: str = "", provider: str = "cpu") -> object:
    """获取（缓存的）SenseVoice 离线识别器；失败返回 None。

    thread-local 缓存 key 为模型目录——切换目录/替换模型文件后自动重建。
    """
    key = f"{(model_dir or '').strip()}|{provider}"
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

    resolved = resolve_model_dir((model_dir or "").strip())
    if not resolved:
        tracelog.warn("[ASR] 未找到外置模型目录 models/asr/，ASR 功能不可用")
        _recognizer_local.rec = False
        _recognizer_local.rec_key = key
        return None

    if provider == "cuda":
        _ensure_cuda_dlls()

    def _build(prov):
        mtype = str(cfg.get("model_type") or "sense_voice").strip().lower()
        if mtype == "whisper":
            # Whisper 模型：encoder/decoder/tokens + language（sherpa-onnx 官方格式）
            enc = os.path.join(resolved, cfg.get("whisper_encoder") or "encoder.onnx")
            dec = os.path.join(resolved, cfg.get("whisper_decoder") or "decoder.onnx")
            tok = os.path.join(resolved, cfg.get("tokens_file") or "tokens.txt")
            if not (os.path.isfile(enc) and os.path.isfile(dec)):
                raise FileNotFoundError(f"Whisper 模型不完整: {os.path.normpath(resolved)}")
            return sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=enc, decoder=dec, tokens=tok,
                language=str(cfg.get("whisper_language") or "zh"),
                task="transcribe", num_threads=1,
                provider=("cuda" if prov == "cuda" else "cpu"))
        # SenseVoice（默认）：单模型文件 + tokens
        k = dict(
            model=os.path.join(resolved, cfg.get("model_file") or "model.int8.onnx"),
            tokens=os.path.join(resolved, cfg.get("tokens_file") or "tokens.txt"),
            num_threads=1,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            use_itn=True,
            debug=False,
        )
        if prov == "cuda":
            k["provider"] = "cuda"
        try:  # 新版支持 language 参数
            return sherpa_onnx.OfflineRecognizer.from_sense_voice(language="auto", **k)
        except TypeError:
            return sherpa_onnx.OfflineRecognizer.from_sense_voice(**k)

    try:
        cfg = _load_asr_config(resolved)
        _recognizer_local.rec = _build(provider)
        _recognizer_local.rec_key = key
        _mtype = str(cfg.get("model_type") or "sense_voice").strip().lower()
        _mname = (cfg.get("name") or "").strip()
        if _mtype == "whisper":
            _mdesc = f"Whisper（{cfg.get('whisper_encoder') or 'encoder.onnx'} + {cfg.get('whisper_decoder') or 'decoder.onnx'}）"
        else:
            _mdesc = f"{_mname or 'SenseVoice'}（{cfg.get('model_file') or 'model.int8.onnx'}）"
        _log_engine_source(
            f"[ASR] ASR 引擎加载成功：本地外置模型 {os.path.normpath(resolved)}\n"
            f"      模型: {_mdesc}\n"
            f"      推理: {'GPU（CUDA）' if provider == 'cuda' else 'CPU'}\n"
            f"      配置来源: {_cfg_source_label(resolved)}")
    except Exception as e:
        if provider == "cuda":
            # GPU 不可用（缺库/驱动/不支持）→ 记录缓存（只告警一次）+ 回退 CPU 重建
            global _cuda_probe_result
            if _cuda_probe_result is None:
                _cuda_probe_result = False
                tracelog.warn(f"[ASR] GPU 推理不可用（{e}），自动回退 CPU")
            try:
                _recognizer_local.rec = _build("cpu")
                _recognizer_local.rec_key = f"{(model_dir or '').strip()}|cpu"
                _log_engine_source(
                    f"[ASR] ASR 引擎加载成功（GPU 回退）：本地外置模型 {os.path.normpath(resolved)}\n"
                    f"      推理: CPU（GPU 回退）")
            except Exception as e2:
                tracelog.error(f"[ASR] ASR 引擎加载失败: {e2}")
                _recognizer_local.rec = False
                _recognizer_local.rec_key = key
        else:
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
    from system.paths import cache_dir
    fd, tmp = tempfile.mkstemp(dir=cache_dir(), suffix=".wav")
    os.close(fd)
    try:
        _flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        r = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", audio_path,
             "-ar", str(SAMPLE_RATE), "-ac", "1", "-f", "wav", tmp],
            capture_output=True, timeout=600, creationflags=_flags)
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


def _segment_ranges(n: int, seg_seconds: float = CHUNK_SECONDS) -> list:
    """把 n 个采样点切成 (start, end) 段列表（段长 seg_seconds、步进 段长-1s，末段不足 1s 跳过）。

    seg_seconds 可调：CPU / GPU 流水线可各自用不同切分块大小
    （GPU 推理快，用大块段可减少调度开销；段长不影响识别内容）。
    """
    chunk_len = int(seg_seconds * SAMPLE_RATE)
    hop = int((seg_seconds - CHUNK_OVERLAP_SECONDS) * SAMPLE_RATE)
    ranges = []
    start = 0
    while start < n:
        end = min(n, start + chunk_len)
        if start > 0 and end - start < SAMPLE_RATE:
            break
        ranges.append((start, end))
        start += hop
    return ranges


def transcribe(audio_path: str, model_dir: str = "", provider: str = "cpu") -> str:
    """转写单个音频/视频文件，返回文字；失败返回空串并记日志。

    长音频按 CHUNK_SECONDS 分段识别后拼接（段间重叠 CHUNK_OVERLAP_SECONDS），
    避免 SenseVoice attention 矩阵随时间平方爆炸（OOM / 空结果）。
    单文件内部串行分段——批量场景请用 transcribe_parallel_segments（段级并行）。
    """
    recognizer = get_recognizer(model_dir, provider)
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
    """为单个音频/视频文件生成 <源文件名>.txt（纯文本，适配性最好）。

    out_dir: 指定输出目录（汇总输出用）；None/空 = 写在源文件同目录。
    内容为纯转写文字（无 Markdown 符号、无元信息头），任何编辑器/AI 直接可读。
    """
    text = (text or "").strip()
    if not text:
        return ""
    folder = out_dir or os.path.dirname(audio_file)
    os.makedirs(folder, exist_ok=True)
    base = os.path.splitext(os.path.basename(audio_file))[0]
    txt_name = f"{base}.txt"
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
    """时间标签识别：输出 <源文件名>.txt 存在且修改时间 >= 源文件 → 已转写。

    用于未完成重传：批量转写前扫描，跳过已完成的文件（软件重启/打断后
    也能准确识别哪些已完成）。
    """
    folder = out_dir or os.path.dirname(audio_file)
    base = os.path.splitext(os.path.basename(audio_file))[0]
    txt = os.path.join(folder, f"{base}.txt")
    if not os.path.isfile(txt):
        return False
    try:
        return os.path.getmtime(txt) >= os.path.getmtime(audio_file)
    except OSError:
        return False


def transcribe_parallel_segments(files, max_workers: int = 4, model_dir: str = "",
                                 on_file_done=None, on_segment_done=None,
                                 cancel_event=None,
                                 cpu_workers: int = None, gpu_workers: int = None,
                                 cpu_model_dir: str = None, gpu_model_dir: str = None,
                                 cpu_seg_sec: float = CHUNK_SECONDS,
                                 gpu_seg_sec: float = CHUNK_SECONDS * 2) -> dict:
    """双流水线并行转写：源头文件池 → CPU / GPU 两条独立队列。

    架构（三队列）：
    - **源头队列**：全部待转写文件，作为分流的源头；
    - **CPU 队列 / GPU 队列**：各自独立的一条流水线（互不等待），
      每条流水线 = 本队列段 worker 池 + 预解码线程；
    - **每条流水线的节奏**：初始化从源头拿 2 个任务（当前 + 预解码都解码好），
      识别当前文件期间后台预解码下一个；当前文件跑完 → 从源头再拿一个接上，
      **始终有一个任务在预解码**；
    - **CPU / GPU 队列并行**：各看自己手头的任务，完成一个就从源头拿下一个，
      不等待对方；区别只是段切分块大小（cpu_seg_sec / gpu_seg_sec，GPU 用大块）。

    回调语义（与旧版兼容）：
    - on_segment_done(f, seg_done, seg_total)：seg_done 为跨队列全局自增段数；
      seg_total 为已提交段总数（两队列合计，处理中递增）；
    - on_file_done(f, text)：每完成一个文件立即回调一次（文件进度/输出用）。
    cancel_event：threading.Event；置位时停止拿新文件/提交新段并取消未开始的段，
    已完成的文件照常触发 on_file_done（打断后已识别内容不丢）。
    """
    import queue as _queue
    results = {f: "" for f in files}
    # 推理负载归一化：cpu_workers/gpu_workers 显式指定时按双池分配；
    # 均未指定时保持旧行为（全部走 CPU，池大小 = max_workers）。
    if cpu_workers is None and gpu_workers is None:
        cpu_workers = max_workers
        gpu_workers = 0
    cpu_workers = max(0, int(cpu_workers or 0))
    gpu_workers = max(0, int(gpu_workers or 0))
    # GPU 不可用时把 GPU 并发并入 CPU（避免回退后只剩 GPU 路数、比纯 CPU 更慢），
    # 且只告警一次（否则每个 GPU worker 线程各自失败告警刷屏）
    if gpu_workers > 0 and not _cuda_usable():
        tracelog.warn(f"[ASR] GPU 不可用，GPU 并发 {gpu_workers} 并入 CPU（总 {cpu_workers + gpu_workers} 路）")
        cpu_workers += gpu_workers
        gpu_workers = 0
    if cpu_workers + gpu_workers < 1:
        cpu_workers = max(1, max_workers)
        gpu_workers = 0
    if not files:
        return results

    workers = []   # 常驻 worker 池（循环外定义，finally 收尾用）
    try:
        import threading as _th
        import time as _time

        # ---------- 三队列架构：源头文件池 + CPU/GPU 两条独立流水线 ----------
        source_q = _queue.Queue()      # ① 源头队列（分流来源）
        for _f in files:
            source_q.put(_f)
        g_done = [0]            # 全局已完成段数（两条流水线共享自增）
        submitted_segs = [0]    # 已提交段总数（两流水线合计，段进度总数）
        state_lock = _th.Lock()
        sents_all = {}          # f -> 该文件已识别句列表（跨流水线锁保护）
        file_seg_done = {}      # f -> 该文件已完成段数

        def _make_pipeline(provider: str, n_workers: int, seg_sec: float, prov_model_dir: str):
            """构建一条流水线（CPU 或 GPU）：解码池 + 段 worker 池 + 文件循环。

            解码并行化：每流水线常驻 PD_N(=min(2,worker数)) 个解码线程，从源头
            连续取文件解码进有界队列（decoded_q，防积压占内存），推理端只等
            "已解码好"的文件——解码不再阻塞推理，多文件批量时解码瓶颈减半。
            两条流水线完全独立并行，各看自己手头任务，互不等待。
            """
            seg_q = _queue.Queue()          # ②③ 该队列自己的段任务队列

            def _seg_worker():
                mdir = prov_model_dir or model_dir
                rec = get_recognizer(mdir, provider)  # 线程本地缓存 → 每线程只加载一次
                punc = get_punctuator(model_dir)
                while True:
                    item = seg_q.get()
                    if item is None:        # 哨兵：结束线程
                        return
                    if cancel_event and cancel_event.is_set():
                        continue            # 取消：丢弃未开始的段
                    f, samples, start, end, seg_total = item
                    try:
                        t, sents = _transcribe_one(rec, samples[start:end],
                                                   start / SAMPLE_RATE,
                                                   (end - start) / SAMPLE_RATE, punc)
                    except Exception as e:
                        tracelog.error(f"[ASR] 分段识别失败: {e}")
                        t, sents = "", []
                    with state_lock:
                        sents_all.setdefault(f, []).extend(sents)
                        file_seg_done[f] = file_seg_done.get(f, 0) + 1
                        g_done[0] += 1
                        total_now = submitted_segs[0]
                        seg_done_f = file_seg_done[f]
                    # 段落级进度日志（全局自增；总数为两流水线已提交段之和）
                    tracelog.info(f"[ASR] 段 {g_done[0]}/{total_now} "
                                  f"（{os.path.basename(f)} {seg_done_f}/{seg_total}）")
                    if on_segment_done:
                        try:
                            on_segment_done(f, g_done[0], total_now)
                        except Exception:
                            pass

            workers = [_th.Thread(target=_seg_worker, daemon=True)
                       for _ in range(max(1, n_workers))]

            # 解码池：常驻 PD_N 个线程从源头连续解码，结果进有界队列。
            # maxsize=PD_N：解码快于推理时自动限流，避免积压多文件采样占内存。
            PD_N = max(1, min(2, n_workers))
            decoded_q = _queue.Queue(maxsize=PD_N)

            def _decoder():
                try:
                    while True:
                        if cancel_event and cancel_event.is_set():
                            return
                        try:
                            f = source_q.get(timeout=0.2)
                        except _queue.Empty:
                            return          # 源头已空：本解码线程退出
                        try:
                            d = _load_samples(f)
                        except Exception as e:
                            tracelog.error(f"[ASR] 解码失败 {os.path.basename(f)}: {e}")
                            d = None
                        decoded_q.put((f, d))   # 解码完成 → 推理端消费
                finally:
                    decoded_q.put((None, None))  # 哨兵：本解码线程结束

            decoders = [_th.Thread(target=_decoder, daemon=True)
                        for _ in range(PD_N)]
            for t in decoders:
                t.start()

            def _pipeline():
                for w in workers:
                    w.start()
                try:
                    sentinels = 0
                    while True:
                        if cancel_event and cancel_event.is_set():
                            break
                        f_cur, data_cur = decoded_q.get()
                        if f_cur is None:      # 解码线程哨兵
                            sentinels += 1
                            if sentinels >= PD_N:
                                break
                            continue
                        if data_cur is None or len(data_cur) == 0:
                            results[f_cur] = ""
                            continue          # 解码失败/空音频：跳过该文件
                        samples, via = data_cur
                        ranges = _segment_ranges(len(samples), seg_sec)
                        seg_total_file = len(ranges)
                        with state_lock:
                            submitted_segs[0] += seg_total_file
                            sents_all[f_cur] = []
                            file_seg_done[f_cur] = 0

                        # 当前文件段全部入本队列段队列
                        for start, end in ranges:
                            if cancel_event and cancel_event.is_set():
                                break
                            seg_q.put((f_cur, samples, start, end, seg_total_file))
                        # 等待当前文件全部段完成（取消则不等待，未完成文件不输出）
                        while file_seg_done.get(f_cur, 0) < seg_total_file:
                            if cancel_event and cancel_event.is_set():
                                break
                            _time.sleep(0.05)

                        # 聚合输出 + 释放内存
                        if file_seg_done.get(f_cur, 0) >= seg_total_file:
                            results[f_cur] = _merge_file_sents(sents_all.get(f_cur, []))
                            if on_file_done:
                                try:
                                    on_file_done(f_cur, results[f_cur])
                                except Exception:
                                    pass
                        with state_lock:
                            sents_all.pop(f_cur, None)
                            file_seg_done.pop(f_cur, None)
                        del samples, data_cur
                finally:
                    # 收尾：丢弃未开始段，放哨兵让 worker 退出
                    while True:
                        try:
                            seg_q.get_nowait()
                        except _queue.Empty:
                            break
                    for _ in workers:
                        seg_q.put(None)
                    for w in workers:
                        w.join()
                    # 丢弃解码队列残留（解码好的文件采样），退出解码线程
                    while True:
                        try:
                            decoded_q.get_nowait()
                        except _queue.Empty:
                            break
                    for t in decoders:
                        t.join()

            return _pipeline

        # 启动 CPU / GPU 两条流水线（各自独立并行，互不等待）
        pipelines = []
        if cpu_workers > 0:
            pipelines.append(_th.Thread(
                target=_make_pipeline("cpu", cpu_workers, cpu_seg_sec, cpu_model_dir),
                daemon=True))
        if gpu_workers > 0:
            pipelines.append(_th.Thread(
                target=_make_pipeline("cuda", gpu_workers, gpu_seg_sec, gpu_model_dir),
                daemon=True))
        for p in pipelines:
            p.start()
        for p in pipelines:
            p.join()
    except Exception as e:
        tracelog.error(f"[ASR] 批量转写出错: {e}")
    return results
