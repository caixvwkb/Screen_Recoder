# This Python file uses the following encoding: utf-8
"""Windows 全局热键支持（后台待命）。

解决痛点：ScreenRecorder 失焦时，应用内 QShortcut 快捷键全部失效，
导致"手动批量截图时必须在别的程序和 ScreenRecorder 之间来回点击"。

本模块基于 Windows RegisterHotKey + QAbstractNativeEventFilter 实现，
无第三方依赖，仅支持 Windows（本项目的目标平台）。

设计约定：
  - 全局热键只用于"批量截取会话进行中"的 Enter 截图（capture_image）；
    会话开始注册、结束注销，避免后台常驻时干扰其他程序的 Enter。
  - Ctrl+A / Ctrl+P / Ctrl+B 等保持应用内快捷键（它们是系统通用快捷键，
    注册为全局会破坏其它程序的全选/打印/加粗）。
"""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

# Windows 常量
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000  # 按住不放时不自动重复触发

_user32 = ctypes.windll.user32

# Qt 快捷键键名 -> Windows 虚拟键码（VK）
_QT_KEY_TO_VK = {
    "Return": 0x0D, "Enter": 0x0D,
    "Space": 0x20, "Tab": 0x09, "Escape": 0x1B, "Backspace": 0x08,
    "Delete": 0x2E, "Insert": 0x2D, "Home": 0x24, "End": 0x23,
    "PageUp": 0x21, "PageDown": 0x22, "Up": 0x26, "Down": 0x28,
    "Left": 0x25, "Right": 0x27,
    "Pause": 0x13, "ScrollLock": 0x91, "Print": 0x2C, "Menu": 0x5D,
    "CapsLock": 0x14, "NumLock": 0x90,
}
# 字母 A-Z、数字 0-9、F1-F24
_QT_KEY_TO_VK.update({chr(c): c for c in range(ord("A"), ord("Z") + 1)})
_QT_KEY_TO_VK.update({str(d): ord(str(d)) for d in range(10)})
_QT_KEY_TO_VK.update({f"F{n}": 0x70 + n for n in range(1, 25)})

_MOD_MAP = {
    "Ctrl": MOD_CONTROL, "Control": MOD_CONTROL,
    "Alt": MOD_ALT, "Shift": MOD_SHIFT,
}


def is_global_safe(shortcut: str) -> bool:
    """判断快捷键是否适合注册为「全局」热键。

    纯 Ctrl+字母/数字（Ctrl+A 全选、Ctrl+S 保存、Ctrl+P 打印、Ctrl+1 切标签）
    是系统通用组合，全局注册会抢走其它程序的对应功能——此类只应保留
    应用内快捷键（窗口聚焦时生效），不注册全局。允许全局的：
      - 含 Alt 或 Shift 的组合（Ctrl+Alt+1、Alt+A、Ctrl+Shift+X）；
      - F 功能键（F1-F24）；
      - Enter/Return（由调用方决定是否临时注册）。
    """
    parts = shortcut.split("+")
    mods = {p.strip() for p in parts[:-1]}
    key = parts[-1].strip()
    if key in ("Return", "Enter"):
        return True
    if key.startswith("F") and key[1:].isdigit():
        return True
    return bool(mods & {"Alt", "Shift"})


class GlobalHotkeyManager(QObject):
    """注册/注销全局热键，并把 WM_HOTKEY 消息转成 Qt 信号。"""

    activated = Signal(str)  # 触发时发出功能名，如 "capture_image"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._next_id = 1
        self._id_to_name = {}   # hotkey_id -> 功能名
        self._name_to_id = {}   # 功能名 -> hotkey_id
        self._name_to_hwnd = {} # 功能名 -> 注册时使用的窗口句柄
        self._filter = None     # 原生事件过滤器（install 时创建）

    # ---------- 快捷键字符串解析 ----------
    def parse(self, shortcut: str):
        """把 "Ctrl+A" / "Return" 解析为 (modifiers, vk)；键名不识别返回 None。"""
        parts = shortcut.split("+")
        mod = 0
        for p in parts[:-1]:
            m = _MOD_MAP.get(p.strip())
            if m is None:
                return None
            mod |= m
        vk = _QT_KEY_TO_VK.get(parts[-1].strip())
        if vk is None:
            return None
        return mod, vk

    # ---------- 注册 / 注销 ----------
    def register(self, name: str, shortcut: str, hwnd=None) -> bool:
        """注册一个全局热键。已注册返回 True；冲突或键名不识别返回 False。

        hwnd: 注册到的窗口句柄（主窗口 winId()）。**必须传真实窗口句柄**——
        Qt 6 不会把 NULL 句柄的线程消息（WM_HOTKEY）转发给 native event filter，
        传 None 注册会"注册成功但永远收不到"。用窗口句柄注册后，
        WM_HOTKEY 走窗口过程，Qt 才能捕获并触发信号。
        """
        if name in self._name_to_id:
            return True
        parsed = self.parse(shortcut)
        if parsed is None:
            return False
        mod, vk = parsed
        hid = self._next_id
        self._next_id += 1
        ok = _user32.RegisterHotKey(hwnd, hid, mod | MOD_NOREPEAT, vk)
        if not ok:
            return False
        self._id_to_name[hid] = name
        self._name_to_id[name] = hid
        self._name_to_hwnd[name] = hwnd
        return True

    def unregister(self, name: str) -> None:
        hid = self._name_to_id.pop(name, None)
        hwnd = self._name_to_hwnd.pop(name, None)
        if hid is not None:
            _user32.UnregisterHotKey(hwnd, hid)
            self._id_to_name.pop(hid, None)

    def unregister_all(self) -> None:
        for name in list(self._name_to_id):
            self.unregister(name)

    def is_registered(self, name: str) -> bool:
        return name in self._name_to_id

    # ---------- 事件过滤 ----------
    def install(self, app) -> None:
        """把原生事件过滤器挂到 QApplication 上（幂等，可重复调用）。"""
        if self._filter is None:
            self._filter = _HotKeyEventFilter(self)
            app.installNativeEventFilter(self._filter)

    def _on_hotkey(self, hid: int) -> None:
        name = self._id_to_name.get(hid)
        if name:
            self.activated.emit(name)


class _HotKeyEventFilter(QAbstractNativeEventFilter):
    """捕获 WM_HOTKEY 消息并转给 GlobalHotkeyManager。"""

    def __init__(self, manager: GlobalHotkeyManager):
        super().__init__()
        self._manager = manager

    def nativeEventFilter(self, eventType, message):
        try:
            et = bytes(eventType) if not isinstance(eventType, bytes) else eventType
            if et == b"windows_generic_MSG":
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == WM_HOTKEY:
                    self._manager._on_hotkey(int(msg.wParam))
                    return True, 0  # 已处理，不再往下传
        except Exception:
            pass
        return False, 0
