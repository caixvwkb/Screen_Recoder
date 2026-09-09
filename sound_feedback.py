"""操作提示音：后台/最小化运行时反馈操作结果。

三档音效（models/sounds 外置，随 models 分发；缺失时静音并记日志）：
- ok.wav    实质性成功（如截取/截图完成）——由截取类操作播放
- click.wav 普通按钮点击成功（开始/停止/框选/全屏等，避免用"成功音"显得怪异）
- fail.wav  任何操作失败（统一播放）

播放：winsound.PlaySound 异步，不阻塞 UI。开关：设置页「通用」->「操作提示音」
（持久化键 sound_feedback，默认开启）。触发写 tracelog（DEBUG），开调试浮窗可确认。
"""
import os
import threading
import winsound

import paths
import tracelog

_global_enabled = True


def set_enabled(on: bool) -> None:
    """全局开关（由设置页/启动加载调用）。"""
    global _global_enabled
    _global_enabled = bool(on)


def is_enabled() -> bool:
    return _global_enabled


def _sound_path(fname: str) -> str:
    """在 models/sounds 下定位音效文件（源码=项目根，打包版=exe 同级）。"""
    try:
        p = os.path.join(paths.app_root(), "models", "sounds", fname)
        return p if os.path.isfile(p) else ""
    except Exception:
        return ""


def _play(fname: str) -> None:
    """子线程播放音效文件；文件缺失时静音并记日志。"""
    def run():
        path = _sound_path(fname)
        if not path:
            tracelog.debug(f"[提示音] 音效文件缺失（静音）: models/sounds/{fname}")
            return
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            tracelog.warn(f"[提示音] 播放 {fname} 失败: {e}")
    threading.Thread(target=run, daemon=True).start()


def play_ok() -> None:
    """实质性成功提示音（models/sounds/ok.wav；缺失静音）。"""
    if not _global_enabled:
        return
    tracelog.debug("[提示音] 操作成功")
    _play("ok.wav")


def play_click() -> None:
    """普通按钮点击提示音（models/sounds/click.wav；缺失静音）。"""
    if not _global_enabled:
        return
    tracelog.debug("[提示音] 按钮点击")
    _play("click.wav")


def play_fail() -> None:
    """操作失败提示音（models/sounds/fail.wav；缺失静音）。"""
    if not _global_enabled:
        return
    tracelog.debug("[提示音] 操作失败")
    _play("fail.wav")
