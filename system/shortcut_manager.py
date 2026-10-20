# This Python file uses the following encoding: utf-8
"""快捷键配置。

包含两部分：
  - ShortcutManager     ：快捷键数据的默认值、加载、保存、冲突校验
  - ShortcutEditDialog  ：修改快捷键的对话框（修饰键下拉框 + 基本键输入）
"""
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout)


class ShortcutManager:
    """快捷键数据管理：默认值、加载、保存、冲突校验。"""

    DEFAULT_SHORTCUTS = {
        "select_region": "Ctrl+Alt+1", # 选择录制区域
        "start_recording": "Ctrl+Alt+2",# 开始录制
        "stop_recording": "Ctrl+Alt+3", # 停止录制
        "capture_image": "Return",       # 手动截取图片
    }

    def __init__(self, settings_file: str):
        self.settings_file = settings_file
        self.shortcuts = dict(self.DEFAULT_SHORTCUTS)

    def load(self, settings: dict) -> None:
        """从设置字典合并快捷键（保留默认值，仅覆盖用户改过的项）。"""
        if "shortcuts" in settings:
            self.shortcuts.update(settings["shortcuts"])

    def to_dict(self) -> dict:
        return dict(self.shortcuts)

    def update(self, key: str, value: str) -> None:
        self.shortcuts[key] = value

    def is_conflict(self, new_shortcut: str, except_key: str) -> bool:
        """判断 new_shortcut 是否已被其它功能占用（except_key 自身除外）。"""
        for k, v in self.shortcuts.items():
            if k != except_key and v == new_shortcut:
                return True
        return False


class ShortcutEditDialog(QDialog):
    """修改快捷键对话框：修饰键 + 基本键，实时预览，确定时做冲突校验。"""

    MODIFIERS = ["空", "Ctrl", "Alt", "Shift",
                 "Ctrl+Shift", "Ctrl+Alt", "Alt+Shift"]

    def __init__(self, current_shortcut: str, shortcut_manager: ShortcutManager,
                 shortcut_key: str, parent=None):
        super().__init__(parent)
        self.manager = shortcut_manager
        self.shortcut_key = shortcut_key
        self.result_shortcut = None
        self.setWindowTitle("修改快捷键")
        self.resize(300, 150)
        self._build_ui(current_shortcut)

    def _build_ui(self, current_shortcut: str):
        layout = QVBoxLayout(self)

        # 修饰键选择
        modifier_layout = QHBoxLayout()
        modifier_label = QLabel("修饰键:")
        self.modifier_combo = QComboBox()
        self.modifier_combo.addItems(self.MODIFIERS)
        modifier_layout.addWidget(modifier_label)
        modifier_layout.addWidget(self.modifier_combo)
        layout.addLayout(modifier_layout)

        # 基本键输入
        key_layout = QHBoxLayout()
        key_label = QLabel("基本键:")
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("请输入键")
        key_layout.addWidget(key_label)
        key_layout.addWidget(self.key_edit)
        layout.addLayout(key_layout)

        # 预览
        self.preview_label = QLabel("预览:")
        layout.addWidget(self.preview_label)

        # 按钮
        button_layout = QHBoxLayout()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")
        button_layout.addStretch()
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        # 实时更新预览
        self.modifier_combo.currentTextChanged.connect(self._update_preview)
        self.key_edit.textChanged.connect(self._update_preview)

        # 载入当前快捷键（拆成「修饰键 + 基本键」）
        if "+" in current_shortcut:
            parts = current_shortcut.split("+")
            modifier = "+".join(parts[:-1])
            key = parts[-1]
            if modifier in self.MODIFIERS:
                self.modifier_combo.setCurrentText(modifier)
            self.key_edit.setText(key)
        else:
            self.modifier_combo.setCurrentText("空")
            self.key_edit.setText(current_shortcut)

        self._update_preview()

        ok_button.clicked.connect(self._on_ok)
        cancel_button.clicked.connect(self.reject)

    def _update_preview(self):
        modifier = self.modifier_combo.currentText()
        key = self.key_edit.text()
        preview = key if modifier == "空" else f"{modifier}+{key}"
        self.preview_label.setText(f"预览: {preview}")

    def _on_ok(self):
        modifier = self.modifier_combo.currentText()
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "警告", "请输入基本键")
            return
        new_shortcut = key if modifier == "空" else f"{modifier}+{key}"
        # 冲突校验：已被其它功能占用则不让确定
        if self.manager.is_conflict(new_shortcut, self.shortcut_key):
            QMessageBox.warning(self, "警告", "该快捷键已被使用")
            return
        self.result_shortcut = new_shortcut
        self.accept()

    def get_shortcut(self) -> str:
        """确定后返回新的快捷键字符串。"""
        return self.result_shortcut
