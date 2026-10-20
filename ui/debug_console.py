# -*- coding: utf-8 -*-
"""调试浮窗：把 tracelog 日志一行行输出到独立窗口（像终端一样滚动）。

- 不依赖控制台（源码/打包版行为一致，打包版不再弹黑窗）
- 跨线程安全：tracelog 从任意工作线程打日志 → LogBridge 发 Qt 信号
  （QueuedConnection）→ 主线程追加到 QPlainTextEdit
- 主题跟随深浅色（由主窗口 _apply_theme 时调用 set_theme 同步）
"""
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

import system.tracelog as tracelog

_DARK_QSS = (
    "QPlainTextEdit{background:#1b1b1b;color:#d4d4d4;"
    "border:1px solid #3c3c3c;border-radius:6px;"
    "font-family:Consolas,'Microsoft YaHei UI';font-size:9pt;}"
)
_LIGHT_QSS = (
    "QPlainTextEdit{background:#ffffff;color:#1a1a1a;"
    "border:1px solid #d0d0d0;border-radius:6px;"
    "font-family:Consolas,'Microsoft YaHei UI';font-size:9pt;}"
)


class DebugConsole(QWidget):
    """独立调试输出浮窗：只读多行文本，滚动追加日志，防内存膨胀。"""

    MAX_BLOCKS = 3000  # 超过自动丢弃最旧行

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ScreenRecorder 调试输出")
        self.resize(820, 500)
        self.setWindowFlag(Qt.Window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(self.MAX_BLOCKS)
        self.view.setPlaceholderText("暂无调试输出……")
        layout.addWidget(self.view)
        self.set_theme(True)

    def set_theme(self, dark: bool):
        self.view.setStyleSheet(_DARK_QSS if dark else _LIGHT_QSS)

    def append(self, line: str):
        """主线程调用（经 LogBridge 信号队列）。"""
        self.view.appendPlainText(line)
        # 自动跟随到底部（最新行可见）
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())


class LogBridge(QObject):
    """tracelog sink 桥：任意线程调用 emit_line，信号转主线程后写入浮窗。"""

    _line = Signal(str)

    def __init__(self, console: DebugConsole):
        super().__init__()
        self._console = console
        self._line.connect(self._append)

    def emit_line(self, text: str):
        """注册给 tracelog.add_sink 的入口（可能来自工作线程）。"""
        self._line.emit(text)

    def _append(self, text: str):
        self._console.append(text)


def install(console: DebugConsole) -> LogBridge:
    """把浮窗挂到 tracelog，返回 bridge（用于注销）。"""
    bridge = LogBridge(console)
    tracelog.add_sink(bridge.emit_line)
    return bridge


def uninstall(bridge: LogBridge):
    tracelog.remove_sink(bridge.emit_line)
