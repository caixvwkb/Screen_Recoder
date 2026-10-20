# This Python file uses the following encoding: utf-8
"""屏幕捕获与导出：视频录制 / 散图捕获 / PDF 导出。

截图后端说明（为什么有两种后端）：
  - 散图(ImageCapture) 与 PDF(PDFExporter) 在 GUI 线程内截图，统一使用
    Qt 的 grab_region()（即 grabWindow）——坐标系统与 Qt 一致，避免 mss
    在多显示器 / 高分屏缩放下出现区域偏移。
  - 视频录制(ScreenRecorder) 跑在独立后台线程，而 Qt 的截图 API 不允许在
    非 GUI 线程调用，因此继续使用 mss（线程安全）。这是二者后端不同的原因。
"""
import system.tracelog as tracelog
import ctypes
import os
import threading
import time
from ctypes import wintypes

import cv2
import mss
import numpy as np

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication





# ---------------- 应用窗口捕获（Win32 PrintWindow） ----------------
# 方案：PrintWindow(hwnd, memDC, PW_RENDERFULLCONTENT=2) 向目标窗口发 WM_PRINT，
# 由窗口/DWM 自绘到内存 DC —— 即使窗口被其他画面完全遮挡，也能取到其真实内容。
# 限制：极少数纯 DirectX 全屏独占渲染窗口可能返回黑屏（超出 PW_RENDERFULLCONTENT
# 覆盖范围），此时 UI 会给出提示。


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


# Win32 函数类型声明：ctypes 未声明 argtypes 时 64 位指针会被截断为 32 位，
# 传 byref/指针参数会导致硬崩溃（STATUS_STACK_BUFFER_OVERRUN）。
_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32

_user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetClientRect.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.ReleaseDC.restype = ctypes.c_int
_user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
_user32.PrintWindow.restype = wintypes.BOOL
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL

_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
_gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteObject.restype = wintypes.BOOL
_gdi32.DeleteDC.argtypes = [wintypes.HDC]
_gdi32.DeleteDC.restype = wintypes.BOOL
_gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT]
_gdi32.GetDIBits.restype = ctypes.c_int


def is_window_valid(hwnd):
    """窗口句柄是否仍有效（未销毁）。"""
    if not hwnd:
        return False
    try:
        return bool(_user32.IsWindow(hwnd))
    except Exception:
        return False


def capture_window_by_hwnd(hwnd):
    """抓取指定窗口客户区内容（被遮挡也能取到），返回 QPixmap；失败返回 None。

    仅供 GUI 线程调用（返回 Qt 对象）。尺寸 = 窗口客户区当前实际大小。
    """
    arr = _print_window_bgra(hwnd)
    if arr is None:
        return None
    h, w = arr.shape[:2]
    from PySide6.QtGui import QImage, QPixmap
    img = QImage(arr.data, w, h, arr.strides[0], QImage.Format_ARGB32)
    return QPixmap.fromImage(img.copy())


def capture_window_by_hwnd_np(hwnd):
    """线程安全版窗口捕获，返回 BGR numpy 数组（OpenCV 可直接写入）；失败返回 None。"""
    arr = _print_window_bgra(hwnd)
    if arr is None:
        return None
    return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)


def _print_window_bgra(hwnd):
    """核心：PrintWindow 到内存 DC，GetDIBits 读回 BGRA 像素（纯 Win32，线程安全）。"""
    try:
        user32 = _user32
        gdi32 = _gdi32

        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        w, h = int(rect.right), int(rect.bottom)
        if w <= 0 or h <= 0:
            return None

        hwnd_dc = user32.GetDC(hwnd)
        if not hwnd_dc:
            return None
        try:
            mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
            bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
            if not mem_dc or not bmp:
                return None
            old_bmp = gdi32.SelectObject(mem_dc, bmp)

            # PW_RENDERFULLCONTENT：由 DWM 合成窗口内容（含被遮挡部分）
            user32.PrintWindow(hwnd, mem_dc, 2)

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = w
            bmi.biHeight = -h          # 负值 = top-down，直接得到正向行序
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0      # BI_RGB
            buf = ctypes.create_string_buffer(w * h * 4)
            got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf,
                                  ctypes.byref(bmi), 0)
            if got == 0:
                return None
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
            return arr.copy()
        finally:
            try:
                gdi32.SelectObject(mem_dc, old_bmp)
                gdi32.DeleteObject(bmp)
                gdi32.DeleteDC(mem_dc)
            except Exception:
                pass
            user32.ReleaseDC(hwnd, hwnd_dc)
    except Exception:
        return None


def enum_visible_windows(exclude_hwnd=None):
    """枚举当前可见顶层窗口，返回 [(hwnd, 标题, 宽, 高), ...]（排除系统外壳）。"""
    result = []
    user32 = _user32

    @WNDENUMPROC
    def _cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        if exclude_hwnd and int(hwnd) == int(exclude_hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in ('Shell_TrayWnd', 'Progman', 'WorkerW',
                         'Windows.UI.Core.CoreWindow'):
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = int(rect.right - rect.left)
        h = int(rect.bottom - rect.top)
        if w <= 0 or h <= 0:
            return True
        result.append((int(hwnd), title.value, w, h))
        return True

    user32.EnumWindows(_cb, 0)
    return result


def grab_region(x: int, y: int, width: int, height: int):
    """用 Qt grabWindow 抓取屏幕指定区域，返回 QPixmap；失败返回 None。"""
    screen = QGuiApplication.primaryScreen()
    if not screen:
        return None
    return screen.grabWindow(0, x, y, width, height)


def _rename_if_exists(src: str, dst: str):
    """把临时文件改名为最终文件（src 不存在时静默）。"""
    try:
        if os.path.exists(src):
            if os.path.exists(dst):
                os.unlink(dst)
            os.rename(src, dst)
    except Exception as e:
        tracelog.warn(f"[录制] 临时文件改名失败 {src} -> {dst}: {e}")


def _create_dxcam_camera():
    """创建 dxcam 抓屏相机（优先主屏输出，BGR 直出）。

    返回 None 表示 dxcam 不可用（未安装/远程桌面/虚拟机/显卡驱动不支持
    DXGI Desktop Duplication），调用方自动回退 mss。
    """
    try:
        import dxcam
        try:
            info = dxcam.output_info() or {}
            for device_idx, outputs in info.items():
                for out in outputs:
                    if out.get("is_primary"):
                        return dxcam.create(
                            device_idx=device_idx,
                            output_idx=out["output"],
                            output_color="BGR")
        except Exception:
            pass
        return dxcam.create(output_color="BGR")
    except Exception as e:
        tracelog.warn(f"[录制] dxcam 不可用，自动回退 mss 抓屏: {e}")
        return None


class ScreenRecorder(QObject):
    """视频录制：在独立后台线程连续抓帧并写 MP4/AVI/MKV/MOV。

    抓屏双引擎：dxcam（DXGI，快、能抓全屏游戏）优先，不可用时回退 mss；
    窗口模式用 PrintWindow（被遮挡也取真实内容）。散图/截图走 Qt grabWindow。
    start() 开线程、stop() 停线程并发出 finished 信号。

    音频支持（audio_capture）：
    - audio_sources: 非空时同时采集音频（内录/麦克风/外部输入，可多源混音），
      视频帧先写临时文件，停止后与音频 wav 经 ffmpeg mux 成带声视频；
    - audio_only: True 时只录音频，输出 MP3（此时不抓视频帧）。
    """
    finished = Signal()

    def __init__(self, region, output_file, fps, window_hwnd=None,
                 audio_sources=None, audio_only=False, guard=True):
        super().__init__()
        self.region = region          # 屏幕区域模式：region 非空
        self.window_hwnd = window_hwnd  # 窗口模式：抓取指定应用窗口（不被遮挡）
        self.output_file = output_file
        self.fps = fps
        self.audio_sources = audio_sources or []  # [{'kind':.., 'device_id':..}, ...]
        self.audio_only = audio_only
        self.guard = guard            # 录制守护：抓帧瞬时异常自动重试，全屏切换不中断
        self.is_recording = False
        self.recording_thread = None

    def start(self):
        self.is_recording = True
        self.recording_thread = threading.Thread(target=self._record)
        self.recording_thread.daemon = True
        self.recording_thread.start()

    def stop(self):
        self.is_recording = False
        if self.recording_thread:
            self.recording_thread.join()
        self.finished.emit()

    def _record(self):
        try:
            if self.audio_only:
                self._record_audio_only()
                return

            # 窗口模式：尺寸以窗口客户区首帧为准（后续窗口缩放时按比例缩放适配）
            window_size = None
            if self.window_hwnd:
                probe = capture_window_by_hwnd_np(self.window_hwnd)
                if probe is None:
                    tracelog.error(
                        f"[录制] 窗口捕获失败: hwnd={self.window_hwnd} "
                        f"（窗口可能已关闭，或为独占全屏/硬件加速渲染，PrintWindow 取不到内容）")
                    return
                height, width = probe.shape[:2]
                window_size = (width, height)
                out_w, out_h = window_size
            else:
                # 屏幕区域模式：region 来自 Qt（逻辑坐标），mss 用物理像素，
                # 必须按 devicePixelRatio 换算，否则 Windows DPI 缩放（如 200%）下
                # 只录到左上角一小块（如 1/4）。
                x, y, width, height = self.region
                screen = QGuiApplication.primaryScreen()
                dpr = screen.devicePixelRatio() if screen else 1.0
                px_x, px_y = int(x * dpr), int(y * dpr)
                px_w, px_h = int(width * dpr), int(height * dpr)
                out_w, out_h = px_w, px_h

            # 确保输出目录存在
            output_dir = os.path.dirname(self.output_file)
            os.makedirs(output_dir, exist_ok=True)

            # 根据文件扩展名选择编码器
            ext = os.path.splitext(self.output_file)[1].lower()
            if ext == '.mp4':
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            elif ext == '.avi':
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
            elif ext == '.mkv':
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
            elif ext == '.mov':
                fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            else:
                fourcc = cv2.VideoWriter_fourcc(*'XVID')

            # 有音频时视频先写临时文件（后续与音频 mux），无音频直接写最终文件
            # 临时文件放缓存目录（输出目录只出成品），避免 _tmp_audio_*.mp4 残留在输出目录
            need_mux = bool(self.audio_sources)
            video_target = self.output_file
            if need_mux:
                from system.paths import cache_dir
                video_target = os.path.join(
                    cache_dir(), f"_tmp_audio_{os.getpid()}_{int(time.time())}.mp4")

            # 创建视频写入器（物理像素尺寸）
            out = cv2.VideoWriter(video_target, fourcc, self.fps, (out_w, out_h))

            if not out.isOpened():
                tracelog.error(f"[录制] 无法打开视频文件: {video_target}")
                return

            monitor = None
            if not self.window_hwnd:
                monitor = {'top': px_y, 'left': px_x, 'width': px_w, 'height': px_h}

            # 预热 dxcam：DXGI 设备冷初始化约 300ms，必须在音频启动/计录基准之前
            # 完成，否则首帧延迟 = 启动延迟，造成"声音超前画面"。窗口模式用
            # PrintWindow 不依赖 dxcam，跳过预热。
            camera = None
            use_dxcam = False
            if not self.window_hwnd:
                camera = _create_dxcam_camera()
                use_dxcam = camera is not None

            # 音频采集（与视频并行）
            audio_rec = None
            if need_mux:
                from capture.audio_capture import AudioRecorder
                audio_rec = AudioRecorder(self.audio_sources)
                audio_rec.start()

            # 帧率控制：按录制时钟对齐时间戳。
            # 旧实现「抓帧+固定 sleep(1/fps)」在抓帧/编码耗时较长时，实际帧率
            # 明显低于设定值（如 30fps 设定实际只有 ~12fps），而视频文件仍标记
            # 帧率控制：固定间隔抓帧（抓一帧 → 写 → sleep(1/fps)）。
            # 不做时间戳追赶对齐——性能不足时追帧会让 CPU 满载、系统卡顿。
            # 实际帧率 = 总帧数/总耗时，录制结束后统一把视频时长对齐真实时间
            # （见下方 fix_video_fps），画面速度永远等于真实时间，音画同步。
            # 帧队列分离：抓帧线程只抓屏入队（快），编码线程从队列取帧写文件（慢），
            # 编码耗时不再拖累抓帧节奏，实际帧率贴近设定；队列满则**等待**编码消费
            # （反压，不丢帧）——保证帧序列完整，时长对齐后局部也音画同步。
            import queue as _queue
            frame_queue = _queue.Queue(maxsize=8)
            backpressure_waits = 0
            encoded_count = [0]
            encoder_error = []

            def _encoder_worker():
                try:
                    while True:
                        item = frame_queue.get()
                        if item is None:
                            break
                        out.write(item)
                        encoded_count[0] += 1
                except Exception as e:
                    encoder_error.append(e)
                    tracelog.error(f"[录制] 编码线程异常: {e}")

            encoder_thread = threading.Thread(target=_encoder_worker, daemon=True)
            encoder_thread.start()

            fail_streak = 0
            record_start = time.monotonic()
            frame_interval = 1.0 / max(self.fps, 1)
            # 目标时刻对齐：每帧应在 record_start + n×interval 时刻抓取。
            # 只 sleep 到目标时刻、落后不追不重置（自然降速），避免抓帧耗时与
            # 固定 sleep 叠加导致间隔偏大；也不产生追帧卡顿。队列反压兜底丢帧。
            next_ts = record_start
            # 双引擎抓屏：dxcam（DXGI，快、能抓全屏游戏）优先，不可用时回退 mss。
            # 窗口模式（PrintWindow）不受影响。camera 已在上方预热（创建耗时已扣除）。
            if use_dxcam:
                # DXGI Desktop Duplication 是画面变化驱动的：静态桌面时单帧 grab()
                # 会因无新帧返回 None。start() 后台线程持续抓帧 + video_mode=True
                # （画面无新帧时复用上一帧，避免静态桌面阻塞等新帧），录制循环
                # get_latest_frame() 即时消费（静态画面返回上一帧，重复帧写文件，
                # 时长仍正确）。
                cam_region = (px_x, px_y, px_x + px_w, px_y + px_h)
                # 后台抓帧目标 ≥ 录制帧率即可（消费是即时读 latest_frame）
                camera.start(target_fps=max(60, self.fps), region=cam_region,
                             video_mode=True)
            sct = None if use_dxcam else mss.mss()
            # 同步诊断统计（Welford 在线均差，不占内存）：首帧延迟 = 视频相对音频的
            # 起始偏移；帧间隔均值/标准差 = 帧序列均匀度（音画同步的前提）。
            _first_ts = None
            _ts_prev = None
            _gap_n = 0
            _gap_mean = 0.0
            _gap_m2 = 0.0
            _gap_max = 0.0
            try:
                while self.is_recording:
                    try:
                        if self.window_hwnd:
                            # 窗口模式：PrintWindow 实时抓取（被遮挡也取真实内容）
                            frame = capture_window_by_hwnd_np(self.window_hwnd)
                            if frame is None:
                                raise OSError("窗口抓取返回空（窗口可能已关闭）")
                            if window_size and frame.shape[:2][::-1] != window_size:
                                frame = cv2.resize(frame, window_size)
                            img = frame
                        elif use_dxcam:
                            # dxcam 后台线程持续抓帧，这里即时取最新帧（BGR 直出）
                            img = camera.get_latest_frame()
                            if img is None:
                                raise OSError("dxcam 尚未抓到首帧（画面切换/设备失效）")
                        else:
                            # mss 回退：抓屏（frombuffer 复用内存，少一次拷贝）
                            screenshot = sct.grab(monitor)
                            arr = np.frombuffer(
                                screenshot.bgra, dtype=np.uint8
                            ).reshape(screenshot.height, screenshot.width, 4)
                            img = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)

                        # 记录该帧真实抓取时刻（put 之前，入队等待不算抓帧耗时）
                        _now = time.monotonic()
                        if _first_ts is None:
                            _first_ts = _now
                        if _ts_prev is not None:
                            _gap = _now - _ts_prev
                            _gap_n += 1
                            _d = _gap - _gap_mean
                            _gap_mean += _d / _gap_n
                            _gap_m2 += _d * (_gap - _gap_mean)
                            if _gap > _gap_max:
                                _gap_max = _gap
                        _ts_prev = _now

                        try:
                            frame_queue.put_nowait(img)
                        except _queue.Full:
                            # 反压：编码跟不上时**等待**编码消费而非丢帧。
                            # 丢帧在时间轴上不均匀（集中在编码重负载段），整体时长
                            # 对齐（-itsscale）无法修复局部帧密度跳变，音频是匀速的
                            # → 高帧率档会出现音画不同步。等待则帧序列完整，时长对齐
                            # 后局部也同步；代价是实际帧率降到编码能力上限（如 120
                            # 档实际约 70fps），但不会加速/跳变。
                            backpressure_waits += 1
                            frame_queue.put(img, timeout=0.5)
                        next_ts += frame_interval
                        delay = next_ts - time.monotonic()
                        if delay > 0:
                            time.sleep(delay)
                    except Exception as e:
                        # 录制守护：全屏应用切换瞬间（独占全屏/DWM 重建）抓帧常报
                        # 瞬时异常，重试即可恢复；守护开启时最多重试 15 次
                        # （约 4.5s），持续失败（窗口关闭/设备失效）才放弃
                        fail_streak += 1
                        tracelog.warn(f"[录制] 抓帧失败(第{fail_streak}次): {e}")
                        if not self.guard or fail_streak >= 15:
                            raise
                        time.sleep(0.3)
                        continue
                    fail_streak = 0
            finally:
                if use_dxcam:
                    try:
                        camera.stop()
                    except Exception:
                        pass
                if sct is not None:
                    try:
                        sct.close()
                    except Exception:
                        pass

            # 结束编码线程并释放资源
            frame_queue.put(None)
            encoder_thread.join(timeout=15)
            out.release()
            total_frames = encoded_count[0]
            if backpressure_waits:
                _elapsed = max(time.monotonic() - record_start, 1e-6)
                tracelog.info(
                    f"[录制] 编码反压等待 {backpressure_waits} 次"
                    f"（实际帧率 {total_frames / _elapsed:.1f}fps，"
                    f"帧序列完整，时长对齐后音画同步）")
            if encoder_error:
                tracelog.warn(f"[录制] 编码异常，部分帧未写入: {encoder_error[0]}")

            # 时长对齐：固定间隔抓帧的实际帧率可能略低于设定（抓帧+编码耗时叠加），
            # 视频时长 = 帧数/设定fps 会短于真实录制时间 → 播放加速、音画不同步。
            # 无条件按实际平均帧率缩放时间戳（-itsscale 纯时间戳缩放，不重编码），
            # 视频时长 = 帧数/实际fps = 真实录制时间，画面速度正确。
            elapsed = time.monotonic() - record_start
            tracelog.info(
                f"[录制] 时长诊断: 编码帧 {total_frames} / 循环耗时 {elapsed:.2f}s"
                f" / 实际帧率 {total_frames / elapsed if elapsed else 0:.1f}fps"
                f" / 设定 {self.fps}fps")
            if total_frames > 10 and elapsed > 0.5:
                actual_fps = total_frames / elapsed
                if abs(actual_fps - self.fps) / self.fps > 0.05:
                    tracelog.info(
                        f"[录制] 实际帧率 {actual_fps:.1f}fps，"
                        f"视频时长对齐真实时间（避免播放加速）")
                    from capture.audio_capture import fix_video_fps
                    fix_video_fps(video_target, self.fps / actual_fps)

            # 音频合成：写 wav → ffmpeg mux 到最终文件
            # 同步诊断输出（在 mux 之前，反映原始偏移）：
            # 首帧延迟 = 视频第一帧相对 record_start 的延迟；音频起点延迟 = 音频
            # 首个样本相对 start 的延迟。净偏移 = 视频晚开始量 - 音频晚开始量，
            # 才是真正需要补偿的差值（两者都晚时部分抵消）。
            if _first_ts is not None:
                _first_delay_ms = (_first_ts - record_start) * 1000
                _gap_std = (_gap_m2 / _gap_n) ** 0.5 if _gap_n else 0.0
                _verdict = ("帧序列均匀（音画同步前提成立）"
                            if _gap_std < frame_interval * 0.5
                            else "帧间隔抖动明显（反压等待/系统负载，局部可能偏移）")
                tracelog.info(
                    f"[录制] 同步诊断: 首帧延迟 {_first_delay_ms:.0f}ms"
                    f"（视频相对基准晚开始量）")
                tracelog.info(
                    f"[录制] 同步诊断: 帧间隔均值 {_gap_mean * 1000:.1f}ms / "
                    f"标准差 {_gap_std * 1000:.1f}ms / 最大 {_gap_max * 1000:.1f}ms，"
                    f"目标 {frame_interval * 1000:.1f}ms → {_verdict}")
            if need_mux and audio_rec is not None:
                samples, sr = audio_rec.stop()
                _audio_delay_s = audio_rec.audio_start_delay()
                tracelog.info(
                    f"[录制] 同步诊断: 音频起点延迟 {_audio_delay_s * 1000:.0f}ms"
                    f"（音频相对基准晚开始量）")
                if samples is not None and len(samples):
                    wav_tmp = os.path.join(
                        os.path.dirname(video_target),
                        f"_tmp_audio_{os.getpid()}_{int(time.time())}.wav")
                    try:
                        from capture.audio_capture import write_wav, mux_video_audio
                        if write_wav(samples, sr, wav_tmp):
                            if mux_video_audio(video_target, wav_tmp, self.output_file):
                                tracelog.info(f"[录制] 音视频合成完成: {self.output_file}")
                                # 合成成功后删除缓存里的临时视频（成品已含视频轨）
                                try:
                                    if os.path.exists(video_target):
                                        os.unlink(video_target)
                                except OSError as e:
                                    tracelog.warn(f"[录制] 临时视频删除失败: {e}")
                            else:
                                tracelog.warn(f"[录制] mux 失败，回退无声视频: {self.output_file}")
                                _rename_if_exists(video_target, self.output_file)
                        else:
                            tracelog.warn(f"[录制] wav 写入失败，回退无声视频: {self.output_file}")
                            _rename_if_exists(video_target, self.output_file)
                    finally:
                        for p in (wav_tmp,):
                            try:
                                if os.path.exists(p):
                                    os.unlink(p)
                            except OSError:
                                pass
                else:
                    tracelog.warn("[录制] 未采集到音频，输出无声视频")
                    _rename_if_exists(video_target, self.output_file)
            elif need_mux:
                _rename_if_exists(video_target, self.output_file)
        except Exception as e:
            tracelog.error(f"[录制] 录制过程出错: {e}")

    def _record_audio_only(self):
        """MP3 纯音频录制：只采集音频，lameenc 编码输出。"""
        from capture.audio_capture import AudioRecorder, encode_mp3
        output_dir = os.path.dirname(self.output_file)
        os.makedirs(output_dir, exist_ok=True)
        rec = AudioRecorder(self.audio_sources)
        rec.start()
        # 空转等待：采集线程持续到 is_recording=False
        while self.is_recording:
            time.sleep(0.05)
        samples, sr = rec.stop()
        if samples is None or not len(samples):
            tracelog.warn("[录制] MP3 模式未采集到音频")
            return
        if encode_mp3(samples, sr, self.output_file):
            tracelog.info(f"[录制] MP3 录制完成: {self.output_file}")
        else:
            tracelog.error(f"[录制] MP3 编码失败: {self.output_file}")

class ImageCapture(QObject):
    """散图捕获：在 GUI 线程内用 Qt grabWindow 截取单张图片并保存。

    由主窗口通过按钮 / 定时器触发 capture()，发出 captured 信号回传文件路径。
    """
    captured = Signal(str)  # 发送捕获的文件路径

    def __init__(self, region, output_folder, image_format, window_hwnd=None):
        super().__init__()
        self.region = region
        self.window_hwnd = window_hwnd
        self.output_folder = output_folder
        self.image_format = image_format

    def capture(self, count):
        """捕获屏幕并保存图片"""
        try:
            if not self.region and not self.window_hwnd:
                return None

            # 抓取来源：窗口模式（PrintWindow）或屏幕区域（grab_region）
            if self.window_hwnd:
                pixmap = capture_window_by_hwnd(self.window_hwnd)
                if pixmap is None:
                    tracelog.debug(f"[录制] 无法获取窗口: hwnd={self.window_hwnd}")
                    return None
            else:
                x, y, width, height = self.region
                pixmap = grab_region(x, y, width, height)
                if pixmap is None:
                    tracelog.debug("[录制] 无法获取屏幕")
                    return None

            # 确保输出目录存在
            os.makedirs(self.output_folder, exist_ok=True)

            # 生成文件名
            output_file = os.path.join(self.output_folder, f"{count}.{self.image_format}")

            # 保存图片
            pixmap.save(output_file)

            self.captured.emit(output_file)
            return output_file
        except Exception as e:
            tracelog.error(f"[截图] 截图过程出错: {e}")
            return None

class PDFExporter(QObject):
    """PDF 导出：先抓取多张临时图片，再一次性合成 PDF。

    流程：capture() 把每张截图存到临时目录 -> export() 用 reportlab 把
    图片按原尺寸排进 PDF（页面尺寸反向适配图片，保证完整不裁剪）-> 
    cleanup() 无论成败都清理临时文件。
    """
    exported = Signal(str)  # 发送生成的 PDF 文件路径

    def __init__(self, region, output_pdf, temp_folder, window_hwnd=None):
        super().__init__()
        self.region = region
        self.window_hwnd = window_hwnd
        self.output_pdf = output_pdf
        self.temp_folder = temp_folder   # 保留参数兼容旧调用，内存模式不再使用
        self.captured_frames = []        # 内存帧（QImage 列表），零散图落盘

    def capture(self, count):
        """捕获屏幕并保存临时图片"""
        if not self.region and not self.window_hwnd:
            return None

        if self.window_hwnd:
            x, y, width, height = 0, 0, 0, 0
            mode_txt = f"窗口 hwnd={self.window_hwnd}"
        else:
            x, y, width, height = self.region
            mode_txt = f"区域 ({x}, {y}, {width}, {height})"

        # 调试信息
        tracelog.debug(f"[截图] 来源: {mode_txt}")

        # 内存存储：转 QImage 存入列表，不落盘（QImage 跨线程只读安全）
        if self.window_hwnd:
            pixmap = capture_window_by_hwnd(self.window_hwnd)
            if pixmap is None:
                tracelog.debug("[截图] 无法获取窗口内容")
                return None
        else:
            pixmap = grab_region(x, y, width, height)
            if pixmap is None:
                tracelog.debug("[截图] 无法获取屏幕")
                return None

        img = pixmap.toImage()
        self.captured_frames.append(img)
        tracelog.debug(f"[截图] 帧 {count} 已入内存 ({img.width()}x{img.height()})")
        return True

    def export(self, progress_cb=None, ocr_enabled=True, ocr_max_workers=1, ocr_model_dir=""):
        """生成 PDF 文件

        progress_cb: 可选进度回调，签名为 (当前页, 总页数)，每页处理完后调用。
                     传 None 时保持旧行为（同步、无进度）。
        ocr_enabled: 是否执行 OCR（隐形文字层 + 配套说明.md）。
                     关闭时只生成纯图片 PDF（元数据仍保留），OCR 相关步骤全部跳过。
        ocr_max_workers: OCR 并行数（>1 时多线程并行识别各页文字，显著加速）。
        ocr_model_dir: 可选，外置 OCR 模型目录。
        """
        try:
            if not self.captured_frames:
                return None
            total = len(self.captured_frames)

            # 确保输出目录存在
            output_dir = os.path.dirname(self.output_pdf)
            os.makedirs(output_dir, exist_ok=True)

            # 生成 PDF
            from reportlab.pdfgen import canvas

            # 读取第一帧来决定页面尺寸（内存）
            first_img = self.captured_frames[0]
            first_img_width, first_img_height = first_img.width(), first_img.height()

            # 关键改进：让PDF页面尺寸反向适配图片
            # 使用图片尺寸作为页面尺寸（转换为点：1英寸=72点，假设屏幕DPI=96）
            dpi = 96
            page_width = (first_img_width / dpi) * 72
            page_height = (first_img_height / dpi) * 72
            
            tracelog.debug(f"[PDF] 第一张图片尺寸: {first_img_width} x {first_img_height}")
            tracelog.debug(f"[PDF] 页面尺寸: {page_width:.2f} x {page_height:.2f} 点")

            # 创建canvas，使用适配图片的页面尺寸
            c = canvas.Canvas(self.output_pdf, pagesize=(page_width, page_height))
            # 元数据：方便 AI / 文档工具识别来源
            c.setTitle(os.path.basename(self.output_pdf))
            c.setAuthor("ScreenRecorder")
            c.setCreator("ScreenRecorder")

            # 预先并行识别所有页文字（OCR 并行，直接识别内存帧，无中间文件）
            ocr_texts = {}
            if ocr_enabled:
                from recognition.ocr import ocr_images_ndarray_parallel
                ocr_texts = ocr_images_ndarray_parallel(
                    self.captured_frames, max_workers=ocr_max_workers,
                    model_dir=ocr_model_dir)

            # 收集每页 OCR 文字（用于生成配套说明.md）
            ocr_items = []

            # 处理所有帧（内存）
            for idx, img in enumerate(self.captured_frames):
                img_w, img_h = img.width(), img.height()
                
                tracelog.debug(f"[PDF] 第 {idx+1} 张图片尺寸: {img_w} x {img_h}")

                # 转换图片尺寸为点
                img_w_points = (img_w / dpi) * 72
                img_h_points = (img_h / dpi) * 72
                
                tracelog.debug(f"[PDF] 图片尺寸（点）: {img_w_points:.2f} x {img_h_points:.2f}")

                # 计算缩放比例，确保图片完整适应页面
                scale_w = page_width / img_w_points
                scale_h = page_height / img_h_points
                scale = min(scale_w, scale_h)

                scaled_w = img_w_points * scale
                scaled_h = img_h_points * scale
                
                tracelog.debug(f"[PDF] 缩放比例: {scale:.4f}")
                tracelog.debug(f"[PDF] 缩放后尺寸: {scaled_w:.2f} x {scaled_h:.2f}")

                # 计算居中位置（reportlab坐标原点在左下角）
                pos_x = (page_width - scaled_w) / 2
                pos_y = (page_height - scaled_h) / 2
                
                tracelog.debug(f"[PDF] 绘制位置: ({pos_x:.2f}, {pos_y:.2f})")

                # 添加图片到 PDF（QImage -> 内存 PNG -> PIL -> ImageReader，
                # reportlab 直接消费，零落盘）
                from PySide6.QtCore import QBuffer
                from io import BytesIO
                from PIL import Image as PILImage
                from reportlab.lib.utils import ImageReader
                buf = QBuffer()
                buf.open(QBuffer.ReadWrite)
                img.save(buf, "PNG")
                pil_img = PILImage.open(BytesIO(bytes(buf.data())))
                buf.close()
                # reportlab 4.4 的 PDFImageXObject 用已废弃的 jpeg_fh 属性判断
                # PIL 对象（新版 Pillow 已无此属性）→ 必须包一层 ImageReader
                c.drawImage(ImageReader(pil_img), pos_x, pos_y,
                            width=scaled_w, height=scaled_h)

                # OCR 隐形文字层：视觉上透明，AI / PDF 工具可直接提取文字
                if ocr_enabled:
                    ocr_text = ocr_texts.get(idx, "")
                    ocr_items.append({"file": f"第{idx+1}页.png", "ocr_text": ocr_text})
                    if ocr_text:
                        c.saveState()
                        c.setFillAlpha(0)          # 文字完全透明（仅作文字层）
                        c.setFillColorRGB(0, 0, 0)
                        c.setFont("Helvetica", 4)
                        y = page_height - 5
                        for line in ocr_text.split("\n"):
                            if y < 5:
                                break
                            c.drawString(3, y, line[:200])
                            y -= 5
                        c.restoreState()

                c.showPage()  # 新建一页
                if progress_cb:
                    progress_cb(idx + 1, total)

            # 保存PDF
            c.save()
            tracelog.info("[PDF] 生成完成")

            # 生成配套说明.md（AI 可直接读取文本）
            if ocr_enabled:
                try:
                    from recognition.ocr import write_sidecar_md
                    side_dir = os.path.dirname(self.output_pdf)
                    side_name = os.path.splitext(os.path.basename(self.output_pdf))[0] + "_说明.md"
                    side_path = write_sidecar_md(side_dir, ocr_items, md_name=side_name)
                    tracelog.info(f"[PDF] 已生成配套说明: {side_path}")
                except Exception as e:
                    tracelog.error(f"[PDF] 生成配套说明失败: {e}")

            # 发送导出完成信号
            self.exported.emit(self.output_pdf)
            return self.output_pdf
        except Exception as e:
            tracelog.error(f"[PDF] 生成过程出错: {e}")
            return None
        finally:
            # 无论成功还是失败，都清理临时文件
            self.cleanup()

    def cleanup(self):
        """清空内存帧，并删除临时目录（PDFExporter 内存模式零散图落盘，
        temp_folder 仅占位；导出/取消后必须清理，避免残留空目录）。"""
        try:
            self.captured_frames = []
        except Exception:
            pass
        try:
            tf = getattr(self, "temp_folder", None)
            if tf and os.path.isdir(tf):
                import shutil
                shutil.rmtree(tf, ignore_errors=True)
        except Exception:
            pass

