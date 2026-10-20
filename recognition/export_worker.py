# This Python file uses the following encoding: utf-8
"""后台导出工作线程：PDF 导出 / OCR 说明生成，避免阻塞 GUI 线程。

为什么这样能安全回传进度：
  - Qt 信号是线程安全的，工作线程里 emit 的信号会自动（AutoConnection）
    排队到接收者所在线程（主线程）的槽函数执行；
  - 所以这里用 Python threading.Thread + Qt 信号即可：重活在线程里跑，
    进度/结果通过信号回到主线程更新 UI，主线程不卡顿。
"""
import system.tracelog as tracelog
import os
import sys
import threading

from PySide6.QtCore import QObject, Signal


class PDFExportWorker(QObject):
    """后台执行 PDFExporter.export()（含逐页 OCR），并回报进度。

    start() 启动线程，完成后发 finished(输出PDF路径, 是否成功)。
    """
    progress = Signal(int, int)   # 当前页, 总页数
    finished = Signal(str, bool)  # 输出 PDF 路径, 是否成功
    failed = Signal(str)          # 错误信息（失败时）

    def __init__(self, exporter, ocr_enabled=True, max_workers=1, model_dir=""):
        super().__init__()
        self._exporter = exporter
        self._ocr_enabled = ocr_enabled
        self._max_workers = max_workers
        self._model_dir = model_dir
        self._thread = None
        self._stop_event = threading.Event()  # 中断标志（stop() 置位，_run 预留接入取消）

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """请求中断：置位取消标志（当前 _run 尚未接入，保留语义）。"""
        self._stop_event.set()

    def _run(self):
        try:
            result = self._exporter.export(
                progress_cb=lambda cur, total: self.progress.emit(cur, total),
                ocr_enabled=self._ocr_enabled,
                ocr_max_workers=self._max_workers,
                ocr_model_dir=self._model_dir)
            ok = bool(result)
            self.finished.emit(result or "", ok)
        except Exception as e:
            tracelog.error(f"[导出线程] PDF 导出出错: {e}")
            self.failed.emit(str(e))
            self.finished.emit("", False)


class SidecarWorker(QObject):
    """后台执行"散图批量结束"的 OCR 识别 + 说明.md 生成。

    start() 启动线程，完成后发 finished(说明.md路径, 是否成功)。
    """
    progress = Signal(int, int)   # 当前图, 总图数
    finished = Signal(str, bool)  # 说明.md 路径, 是否成功
    failed = Signal(str)

    def __init__(self, files, folder, max_workers=4, model_dir=""):
        super().__init__()
        self._files = list(files)
        self._folder = folder
        self._max_workers = max_workers
        self._model_dir = model_dir
        self._thread = None
        self._stop_event = threading.Event()  # 中断标志（stop() 置位，_run 预留接入取消）

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """请求中断：置位取消标志（当前 _run 尚未接入，保留语义）。"""
        self._stop_event.set()

    def _run(self):
        try:
            from recognition.ocr import ocr_images_parallel, write_sidecar_md
            results = ocr_images_parallel(
                self._files,
                max_workers=self._max_workers,
                progress_cb=lambda c, t, n: self.progress.emit(c, t),
                model_dir=self._model_dir)
            items = [{"file": f, "ocr_text": results.get(f, "")} for f in self._files]
            md = write_sidecar_md(self._folder, items)
            self.finished.emit(md or "", bool(md))
        except Exception as e:
            tracelog.error(f"[导出线程] 生成说明.md 出错: {e}")
            self.failed.emit(str(e))
            self.finished.emit("", False)


class FolderOcrWorker(QObject):
    """后台对一批文件做 OCR，为「OCR 识别」页服务。

    - merge_images=False：每个文件生成一个 <文件名>_说明.md；
    - merge_images=True ：图片全部 OCR 后合并成一个 <根文件夹名>_图片说明.md
                          （放在 root_folder 下），PDF 仍各自生成。
    start() 启动线程，完成后发 finished(生成md数, 失败文件数)。
    """
    progress = Signal(int, int, str)   # 当前文件序号, 总文件数, 当前文件名
    finished = Signal(int, int)        # 成功生成 md 数, 失败文件数
    failed = Signal(str)

    def __init__(self, files, root_folder, merge_images=False, max_workers=4, model_dir="", out_dir=""):
        super().__init__()
        self._files = list(files)
        self._root_folder = root_folder
        self._merge_images = merge_images
        self._max_workers = max_workers
        self._model_dir = model_dir
        self._out_dir = out_dir
        self._thread = None
        self._stop_event = threading.Event()  # 中断标志（stop() 置位，_run 接入取消）
        self.last_remaining = 0  # 被打断时未处理文件数（供 UI 提示继续识别）

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """请求中断：置位取消标志，未开始任务取消，已完成文件保留输出。"""
        self._stop_event.set()

    def _run(self):
        # 按文件为单位即时输出：每文件识别完成立即写 md（merge 图片收齐后合并），
        # 停止（cancel_event）只影响未开始文件，已完成文件不丢。
        from recognition.folder_ocr import (IMAGE_EXTS, ocr_files_parallel, write_file_sidecar,
                                write_merged_image_md)
        total = len(self._files)
        md_count, fail_count, done = [0], [0], [0]
        image_items = []
        lock = threading.Lock()
        try:
            def on_file_done(f, text):
                with lock:
                    done[0] += 1
                    self.progress.emit(done[0], total, os.path.basename(f))
                    ext = os.path.splitext(f)[1].lower()
                    if self._merge_images and ext in IMAGE_EXTS:
                        image_items.append({"file": f, "ocr_text": text})
                        return  # 图片等合并统一最后写
                    md = write_file_sidecar(f, text, self._out_dir or None)
                    if md:
                        md_count[0] += 1
                    else:
                        fail_count[0] += 1

            ocr_files_parallel(
                self._files,
                max_workers=self._max_workers,
                model_dir=self._model_dir,
                cancel_event=self._stop_event,
                on_file_done=on_file_done)
            # 合并图片为一个 md（需全部图片收齐后写，放根文件夹下）
            if image_items:
                md = write_merged_image_md(self._out_dir or self._root_folder, image_items)
                if md:
                    md_count[0] += 1
                else:
                    fail_count[0] += len(image_items)
            remaining = total - done[0]
            self.last_remaining = remaining
            self.finished.emit(md_count[0], fail_count[0])
        except Exception as e:
            tracelog.error(f"[导出线程] 文件夹 OCR 出错: {e}")
            self.failed.emit(str(e))
            self.finished.emit(md_count[0], fail_count[0] + (total - done[0]))


class ASRWorker(QObject):
    """后台对一批音频/视频文件做语音转写（SenseVoice），为「ASR 识别」页服务。

    - 转写运行在**独立子进程**（--asr-worker 模式）：OCR 的 pip onnxruntime
      与 sherpa onnxruntime 同进程共存会导致 GPU 推理段错误崩溃，
      子进程隔离后 GPU/OCR 互不干扰；
    - 进度/结果经子进程 stdout 的 JSON 行回传，父进程转发为 Qt 信号；
    - 每个文件转写后立即写 <文件名>_语音转写.txt（输出目录或源文件旁）。
    start() 启动子进程，完成后发 finished(生成txt数, 失败文件数)。
    """
    progress = Signal(int, int, str, int, int)  # 文件done, 文件total, 文件名, 段done, 段total
    finished = Signal(int, int)        # 成功生成 txt 数, 失败文件数
    failed = Signal(str)

    def __init__(self, files, max_workers=4, model_dir="", out_dir="",
                 cpu_workers=None, gpu_workers=None,
                 cpu_model_dir=None, gpu_model_dir=None,
                 _entry=None):
        super().__init__()
        self._files = list(files)
        self._max_workers = max_workers
        self._model_dir = model_dir
        self._out_dir = out_dir
        self._cpu_workers = cpu_workers
        self._gpu_workers = gpu_workers
        self._cpu_model_dir = cpu_model_dir
        self._gpu_model_dir = gpu_model_dir
        self._entry = _entry
        self._thread = None
        self._stop_event = threading.Event()
        self._proc = None
        self.last_remaining = 0  # 被打断时未处理文件数（供 UI 提示继续转写）

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """请求中断批量转写：终止子进程（已写出的 txt 保留，可续传）。"""
        self._stop_event.set()
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def _run(self):
        import json
        import subprocess
        total = len(self._files)
        if total == 0:
            self.finished.emit(0, 0)
            return
        if self._entry:
            cmd = list(self._entry)
        elif getattr(sys, "frozen", False):
            cmd = [sys.executable, "--asr-worker"]  # 打包版：exe 自身支持 worker 模式
        else:
            main = os.path.abspath(sys.modules["__main__"].__file__)
            cmd = [sys.executable, main, "--asr-worker"]
        cfg = {
            "files": self._files,
            "out_dir": self._out_dir or "",
            "max_workers": self._max_workers,
            "model_dir": self._model_dir or "",
            "cpu_workers": self._cpu_workers or 0,
            "gpu_workers": self._gpu_workers or 0,
            "cpu_model_dir": self._cpu_model_dir or "",
            "gpu_model_dir": self._gpu_model_dir or "",
        }
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        CREATE_NO_WINDOW = 0x08000000
        done = 0
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env, creationflags=CREATE_NO_WINDOW,
                text=True, encoding="utf-8", errors="replace", bufsize=1)
            self._proc.stdin.write(json.dumps(cfg, ensure_ascii=False))
            self._proc.stdin.close()
        except Exception as e:
            tracelog.error(f"[ASR] 启动转写子进程失败: {e}")
            self.failed.emit(str(e))
            self.finished.emit(0, total)
            return
        for line in self._proc.stdout:
            if self._stop_event.is_set():
                try:
                    self._proc.terminate()
                except Exception:
                    pass
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            t = msg.get("t")
            if t == "seg":
                self.progress.emit(done, total, msg.get("name", ""),
                                   msg.get("seg_done", 0), msg.get("seg_total", 0))
            elif t == "file":
                done = int(msg.get("done", done))
                self.progress.emit(done, total, msg.get("name", ""), 0, 0)
            elif t == "done":
                self.last_remaining = int(msg.get("remaining", 0))
                self.finished.emit(int(msg.get("txt", 0)), int(msg.get("fail", 0)))
                return
            elif t == "err":
                self.failed.emit(msg.get("msg", "转写子进程出错"))
        # 子进程非正常结束（取消/崩溃）且未发 done
        self.last_remaining = total - done
        self.finished.emit(done, total - done)
