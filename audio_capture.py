# -*- coding: utf-8 -*-
"""视频录制音频支持：多来源采集（系统内录 / 麦克风 / 外部输入）与输出合成。

后端选型：
- 采集：soundcard（PortAudio/WASAPI）——支持枚举 loopback（内录）与 mic（麦克风/外部输入），
  多流并行采集，numpy 输出；与 PyAudio 相比原生支持 WASAPI loopback。
- MP3 编码：lameenc（LAME 封装，纯 C 扩展 wheel，无外部 ffmpeg 依赖）。
- 音视频合成：imageio-ffmpeg 自带 ffmpeg mux（OpenCV VideoWriter 只写视频流，
  无法写音轨，故视频/音频分别产出后 mux）。

约定：统一目标采样率 48000、双声道；多源同时选中时按帧对齐后混音（相加裁剪）。
"""
import os
import threading
import time
import tracelog

import numpy as np

TARGET_SR = 48000  # 统一采集/混音采样率
TARGET_CH = 2      # 统一声道数


# ---------------- 设备枚举 ----------------

def list_audio_sources():
    """枚举音频输入来源，返回 {'loopback': [...], 'mic': [...]}。

    每项 {'id': str, 'name': str}；库缺失/无设备时返回空结构（调用方禁用选项）。
    """
    out = {"loopback": [], "mic": []}
    try:
        import soundcard as sc
    except Exception as e:
        # 覆盖 ImportError / FileNotFoundError（打包版缺 mediafoundation.py.h 等数据文件）
        # 等一切加载失败：音频枚举降级为空，绝不阻塞程序启动
        tracelog.warn(f"[音频] soundcard 加载失败，音频录制不可用: {e}")
        return out
    try:
        for m in sc.all_microphones(include_loopback=True):
            item = {"id": m.id, "name": m.name}
            if getattr(m, "isloopback", False):
                out["loopback"].append(item)
            else:
                out["mic"].append(item)
    except Exception as e:
        tracelog.error(f"[音频] 枚举音频设备失败: {e}")
    return out


# ---------------- 单源采集线程 ----------------

class _SourceRecorder(threading.Thread):
    """单个音频源的后台采集线程：持续 record 到 chunks。"""

    def __init__(self, device_id: str, is_loopback: bool, samplerate: int):
        super().__init__(daemon=True)
        self.device_id = device_id
        self.is_loopback = is_loopback
        self.samplerate = samplerate
        self._stop_evt = threading.Event()
        self.chunks = []
        self.error = ""
        self._rec = None
        self.first_sample_ts = None  # 首个样本的真实时刻（monotonic，启动延迟测量）

    def run(self):
        import soundcard as sc
        try:
            mic = sc.get_microphone(self.device_id, include_loopback=True)
            if mic is None:
                self.error = f"找不到设备: {self.device_id}"
                return
            with mic.recorder(samplerate=self.samplerate, channels=TARGET_CH) as rec:
                self._rec = rec
                while not self._stop_evt.is_set():
                    data = rec.record(numframes=1024)
                    if data is not None and len(data):
                        if self.first_sample_ts is None:
                            self.first_sample_ts = time.monotonic()
                        self.chunks.append(np.asarray(data, dtype=np.float32))
        except Exception as e:
            self.error = str(e)

    def stop(self):
        self._stop_evt.set()
        self.join(timeout=3)


# ---------------- 多源采集与混音 ----------------

class AudioRecorder:
    """多来源音频录制（loopback / mic 可同时）。

    用法：
        rec = AudioRecorder([{'kind': 'loopback', 'device_id': ...}, ...])
        rec.start(); ...; data = rec.stop()
    stop() 返回 (samples: np.ndarray (N,2) float32 或 None, sr: int)。
    """

    def __init__(self, sources: list, samplerate: int = TARGET_SR):
        self.sources = [s for s in sources if s and s.get("device_id")]
        self.samplerate = samplerate
        self._threads = []

    def start(self):
        self._start_ts = time.monotonic()
        for s in self.sources:
            t = _SourceRecorder(s["device_id"], s.get("kind") == "loopback", self.samplerate)
            t.start()
            self._threads.append(t)
        tracelog.debug(f"[音频] 采集线程已启动: {len(self._threads)} 个来源")

    def audio_start_delay(self) -> float:
        """音频起点相对 start() 的延迟秒数（首个样本真实时刻 - start 时刻）。"""
        if not self._threads:
            return 0.0
        firsts = [t.first_sample_ts for t in self._threads if t.first_sample_ts]
        if not firsts:
            return 0.0
        return min(firsts) - self._start_ts

    def stop(self):
        """停止采集并返回 (samples, sr)；无有效音频返回 (None, sr)。"""
        for t in self._threads:
            t.stop()
        if not self._threads:
            return None, self.samplerate

        # 每个来源拼接为 (N, 2) 数组；失败来源记录日志
        arrays = []
        for t in self._threads:
            if t.error:
                tracelog.warn(f"[音频] 来源采集失败: {t.error}")
                continue
            if not t.chunks:
                continue
            arr = np.concatenate(t.chunks, axis=0).astype(np.float32)
            if arr.ndim == 1:  # 单声道 → 双声道
                arr = np.column_stack([arr, arr])
            if arr.ndim > 2:
                arr = arr.reshape(arr.shape[0], -1)[:, :TARGET_CH]
            arrays.append(arr)

        if not arrays:
            tracelog.warn("[音频] 未采集到任何有效音频（全部来源静默或失败）")
            return None, self.samplerate

        # 多来源混音：对齐到最短帧数，相加后裁剪到 [-1, 1]
        n = min(a.shape[0] for a in arrays)
        mixed = np.zeros((n, TARGET_CH), dtype=np.float32)
        for a in arrays:
            mixed += a[:n]
        mixed = np.clip(mixed, -1.0, 1.0)
        total_s = n / self.samplerate
        tracelog.debug(f"[音频] 采集完成: {len(arrays)} 源, {total_s:.1f}s（已混音）")
        return mixed, self.samplerate


# ---------------- 输出合成 ----------------

def _audio_to_int16(samples: np.ndarray) -> np.ndarray:
    """float32 [-1,1] → int16（用于 WAV/MP3 编码）。"""
    return np.clip(samples, -1.0, 1.0) * 32767.0


def write_wav(samples, samplerate: int, path: str) -> bool:
    """写 WAV（soundfile）。samples 为 float32 (N, ch)。"""
    try:
        import soundfile as sf
        sf.write(path, samples, samplerate, format="WAV")
        return True
    except Exception as e:
        tracelog.error(f"[音频] 写 WAV 失败 {path}: {e}")
        return False


def encode_mp3(samples, samplerate: int, path: str, bitrate: int = 192) -> bool:
    """int16/float32 音频 → MP3（lameenc）。"""
    try:
        import lameenc
    except ImportError:
        tracelog.error("[音频] lameenc 未安装，无法输出 MP3（pip install lameenc）")
        return False
    try:
        if samples.dtype != np.int16:
            samples = _audio_to_int16(samples).astype(np.int16)
        if samples.ndim == 1:
            samples = samples[:, None]
        enc = lameenc.Encoder()
        enc.set_bit_rate(bitrate)
        enc.set_in_sample_rate(samplerate)
        enc.set_channels(samples.shape[1])
        enc.set_quality(2)
        data = samples.tobytes()
        out = enc.encode(data)
        out += enc.flush()
        with open(path, "wb") as f:
            f.write(out)
        return True
    except Exception as e:
        tracelog.error(f"[音频] MP3 编码失败 {path}: {e}")
        return False


def fix_video_fps(video_path: str, scale: float) -> bool:
    """缩放视频时间戳使时长对齐真实时间（-itsscale 纯时间戳缩放，不重编码）。

    scale = 设定fps / 实际fps（>1 表示跟不上帧率，把每帧时长放大）：
    视频时长 = 帧数×单帧时长 = 帧数×scale/设定fps = 帧数/实际fps = 真实录制时间，
    播放器按真实时长播放，画面不加速、与音频同步。
    """
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        tracelog.error(f"[音频] 找不到 ffmpeg: {e}")
        return False
    import subprocess
    tmp = video_path + ".fpsfix.mp4"
    try:
        r = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error",
             "-itsscale", f"{scale:.4f}", "-i", video_path,
             "-c", "copy", tmp],
            capture_output=True, timeout=600)
        if r.returncode != 0 or not os.path.exists(tmp) or not os.path.getsize(tmp):
            tracelog.error(f"[录制] 帧率重封装失败: {r.stderr.decode('utf-8', 'ignore')[:300]}")
            return False
        os.replace(tmp, video_path)
        tracelog.info(f"[录制] 视频时长已对齐实际帧率（缩放 {scale:.2f}×）")
        return True
    except Exception as e:
        tracelog.error(f"[录制] 帧率重封装异常: {e}")
        return False


def mux_video_audio(video_path: str, audio_path: str, output_path: str) -> bool:
    """用 imageio-ffmpeg 自带 ffmpeg 把无声视频 + 音频 mux 成带声视频。

    不加 -shortest：视频比音频短时（首帧晚开始/编码掉帧）输出取两流最大时长，
    尾部自然保留"只有声音"的部分（视频结束定格/黑屏、声音继续）；
    -shortest 会把音频裁到视频长度导致尾部声音丢失。
    """
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        tracelog.error(f"[音频] 找不到 ffmpeg: {e}")
        return False
    import subprocess
    try:
        cmd = [ffmpeg, "-y", "-loglevel", "error",
               "-i", video_path, "-i", audio_path,
               "-c:v", "copy", "-c:a", "aac", output_path]
        r = subprocess.run(cmd, capture_output=True, timeout=600)
        if r.returncode != 0 or not os.path.exists(output_path) or not os.path.getsize(output_path):
            tracelog.error(f"[音频] ffmpeg mux 失败: {r.stderr.decode(errors='ignore')[-500:]}")
            return False
        return True
    except Exception as e:
        tracelog.error(f"[音频] ffmpeg mux 异常: {e}")
        return False
