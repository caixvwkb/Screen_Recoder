# -*- coding: utf-8 -*-
"""统一日志模块（tracelog）：所有模块的日志统一走这里。

- 输出：控制台 + 缓存目录 cache/trace.log（打包版=exe 同级 cache/，源码=项目根 cache/）
- 分级：DEBUG < INFO < WARN < ERROR，默认 INFO
  - INFO：关键事件（环境判定 / 路径解析 / 模型加载 / 扫描目录 / 批量结果）
  - DEBUG：细节（逐帧 / 逐文件 / 中间量），调试终端显示时自动开启
- 线程安全（OCR/ASR 多线程并发写日志）
- 被 paths.py 依赖：tracelog 内部延迟导入 paths，paths 打日志时的重入有保护
"""
import os
import threading
from datetime import datetime

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
_level = _LEVELS["INFO"]
_lock = threading.Lock()
_log_file = None
_initializing = False

# 可选输出通道（调试浮窗等 UI 订阅）：任意可调用 fn(line)，线程安全广播，
# 不依赖 Qt——被 paths.py 依赖时保持纯 Python
_sinks = []
_sinks_lock = threading.Lock()


def add_sink(fn):
    """注册一个日志行接收器：fn(line)，任意线程调用（接收方自行处理线程）。"""
    with _sinks_lock:
        if fn not in _sinks:
            _sinks.append(fn)


def remove_sink(fn):
    with _sinks_lock:
        if fn in _sinks:
            _sinks.remove(fn)


def _notify_sinks(line: str):
    with _sinks_lock:
        sinks = list(_sinks)
    for fn in sinks:
        try:
            fn(line)
        except Exception:
            pass


def set_level(name: str):
    """全局日志级别："DEBUG" / "INFO" / "WARN" / "ERROR"。"""
    global _level
    _level = _LEVELS.get(str(name).upper(), _LEVELS["INFO"])


def get_level() -> str:
    return next(k for k, v in _LEVELS.items() if v == _level)


def _ensure_file() -> str:
    """日志文件路径（程序根/cache/trace.log），首次调用时解析并缓存。

    与缓存目录统一（paths.cache_dir，随程序走）：源码=项目根/cache，
    打包版=exe 同级/cache。
    """
    global _log_file, _initializing
    if _log_file is not None:
        return _log_file
    if _initializing:  # paths 解析中打日志的重入保护 → 用模块旁 cache/ 兜底
        return _fallback_file()
    _initializing = True
    try:
        from paths import cache_dir
        _log_file = os.path.join(cache_dir(), "trace.log")
    except Exception:
        _log_file = _fallback_file()
    finally:
        _initializing = False
    return _log_file


def _fallback_file() -> str:
    """重入/异常兜底：本模块旁 cache/trace.log（源码项目根，打包版=解包目录）。"""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, "trace.log")


def log(level: str, msg: str):
    lv = _LEVELS.get(str(level).upper(), _LEVELS["INFO"])
    if lv < _level:
        return
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [{level.upper()}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        # 先无锁解析文件路径：首次调用可能触发 paths.app_root() 打日志
        # （同线程重入），若此时已持锁会死锁，故 _ensure_file 必须在加锁前
        fpath = _ensure_file()
        with _lock:
            with open(fpath, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass
    # 广播给 UI 订阅者（调试浮窗），顺序在文件写入后，异常不干扰主流程
    _notify_sinks(line)


def debug(msg: str):
    log("DEBUG", msg)


def info(msg: str):
    log("INFO", msg)


def warn(msg: str):
    log("WARN", msg)


def error(msg: str):
    log("ERROR", msg)
