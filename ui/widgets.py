# -*- coding: utf-8 -*-
"""UI 通用组件层：折叠卡收起修复 + 功能页容器 + 两行卡 + 目录/输出目录卡。

- FeaturePage：功能页容器（标题卡 + 可折叠大功能分块 + 底部信息栏）
- TwoRowCard：两行排版设置卡（第一行图标+标题+说明，第二行控件独占一行）
- DirPickerCard / OutFolderCard：设置页目录选择卡
- 折叠卡补丁：修复 qfluentwidgets ExpandGroupSettingCard 收起动画终点缺陷
"""
import os
from PySide6.QtCore import Qt, QVariantAnimation, QEasingCurve, Signal
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QFileDialog, QDialog, QListWidget)
from qfluentwidgets import (FluentIcon, ScrollArea, HeaderCardWidget, ExpandGroupSettingCard,
                            SettingCard, SettingCardGroup, PushSettingCard,
                            PushButton, PrimaryPushButton, BodyLabel, CaptionLabel,
                            CardWidget, HorizontalSeparator, SwitchButton, LineEdit)
from qfluentwidgets.components.settings.setting_card import SettingIconWidget

# ---- 折叠卡收起修复（qfluentwidgets ExpandGroupSettingCard 动画终点计算缺陷） ----
# 原实现收起动画终点取 scrollbar.maximum()（= 内容高 - 卡高），高度收敛在 2×卡高
# 收不拢。改为：收起/展开都直接用 QVariantAnimation 动画卡片自身高度，
# 从当前高度平滑过渡到目标高度（收起=卡头高，展开=卡头+内容高）。
# 内容高度用 self.widgets 累加（与库 _adjustViewSize 同口径，addGroupWidget 维护）。
_ORIG_SET_EXPAND = ExpandGroupSettingCard.setExpand


def _fixed_measure(self):
    """临时撑开卡片高度，让布局给出非受限的 viewLayout.sizeHint()（稳定可靠）。"""
    saved = self.height()
    self.setFixedHeight(10000)
    h = self.viewLayout.sizeHint().height()
    self.setFixedHeight(saved)
    return h


def _fixed_set_expand(self, isExpand: bool):
    if self.isExpand == isExpand:
        return
    self._adjustViewSize()
    self.isExpand = isExpand
    self.setProperty('isExpand', isExpand)
    self.setStyle(QApplication.style())
    self.expandAni.stop()
    end = self.card.height() + (_fixed_measure(self) if isExpand else 0)
    ani = QVariantAnimation(self)
    ani.setDuration(200)
    ani.setEasingCurve(QEasingCurve.OutQuad)
    ani.setStartValue(self.height())
    ani.setEndValue(end)
    ani.valueChanged.connect(lambda v: self.setFixedHeight(int(v)))
    ani.start()
    self._expand_ani = ani  # 保持引用，防止动画中途被回收
    self.card.expandButton.setExpand(isExpand)


ExpandGroupSettingCard.setExpand = _fixed_set_expand


class FeaturePage(QWidget):
    """功能页：标题卡 + 若干可折叠大功能分块（ExpandGroupSettingCard）。"""

    def __init__(self, title: str, subtitle: str, blocks, parent=None):
        super().__init__(parent)
        self.setObjectName(f"page_{title}")  # addSubInterface 要求 objectName 非空（导航键）

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName(f"scroll_{title}")

        container = QWidget()
        container.setObjectName(f"container_{title}")
        v = QVBoxLayout(container)
        v.setContentsMargins(48, 32, 48, 32)
        v.setSpacing(12)

        # 页面标题卡
        header = HeaderCardWidget(container)
        header.setTitle(title)
        header.viewLayout.addWidget(BodyLabel(subtitle, header))
        header.viewLayout.addStretch(1)
        v.addWidget(header)

        # 大功能分块：可点击折叠
        self.block_cards = {}
        for icon, block_title, block_sub, placeholder in blocks:
            card = self._make_block(icon, block_title, block_sub, placeholder, container)
            self.block_cards[block_title] = card
            v.addWidget(card)

        # 底部伸展：内容顶对齐，留白在页面底部
        v.addStretch(1)

        # 底部信息栏：页面级输出/进度状态（默认空，页面构建时按需填充）
        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(8, 6, 8, 4)
        self.footer.setSpacing(12)
        v.addLayout(self.footer)

        self.scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)

    @staticmethod
    def _make_block(icon, block_title: str, block_sub: str, placeholder, parent):
        """单个可折叠功能块：点击标题栏展开/收起。

        placeholder 为空/None 表示该块已迁移（不再显示"待迁移"占位卡），
        由页面构建代码直接向 group.viewLayout 填充 SettingCard。
        """
        group = ExpandGroupSettingCard(icon, block_title, block_sub, parent)
        group.setExpand(True)  # 初始展开，保持信息可见
        if placeholder:
            setting_group = SettingCardGroup("功能占位", group)
            group.addGroupWidget(setting_group)
            setting_group.addSettingCard(
                PushSettingCard("（占位）", FluentIcon.EMBED,
                                "待迁移", placeholder, setting_group)
            )
        return group

    def _sync_expand_height(self, card):
        """按真实内容高度修正折叠卡展开高度（撑开测量，不依赖卡 sizeHint 激活时机）。

        构建期逐卡 addGroupWidget 时，末张卡 sizeHint 可能尚未激活（为 0），
        自动触发的 _adjustViewSize 会少算一卡；此处临时撑开卡片高度，
        让布局给出非受限的 viewLayout.sizeHint()，再据此设置正确高度。
        """
        if not getattr(card, "isExpand", False):
            return
        saved = card.height()
        card.setFixedHeight(10000)
        h = card.viewLayout.sizeHint().height()
        card.setFixedHeight(saved)
        card.setFixedHeight(card.card.height() + h)

    def showEvent(self, e):
        """页面真正显示时，折叠块内容已布局完成 → 同步展开高度。"""
        super().showEvent(e)
        for card in self.block_cards.values():
            self._sync_expand_height(card)



class TwoRowCard(CardWidget):
    """两行布局设置卡（子选项卡）：第一行 图标+标题+说明文字；第二行 操作控件独占一行。

    解决单行 SettingCard 右侧控件被说明文字换行挤压/拉伸的问题。
    """

    def __init__(self, icon, title, content, parent=None):
        super().__init__(parent)
        self.icon_widget = SettingIconWidget(icon, self)
        self.title_label = BodyLabel(title, self)
        self.content_label = CaptionLabel(content, self)
        self.content_label.setWordWrap(True)

        self.vBox = QVBoxLayout(self)
        self.vBox.setContentsMargins(16, 10, 16, 10)
        self.vBox.setSpacing(6)

        # 第一行：图标 + 标题/说明（竖排）
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(self.icon_widget, 0, Qt.AlignTop)
        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        text_box.addWidget(self.title_label)
        text_box.addWidget(self.content_label)
        top.addLayout(text_box, 1)
        self.vBox.addLayout(top)

        # 分隔线
        self.separator = HorizontalSeparator(self)
        self.vBox.addWidget(self.separator)

        # 第二行：操作控件（独占一行，不会被文字挤压）
        self.controls = QHBoxLayout()
        self.controls.setSpacing(8)
        self.vBox.addLayout(self.controls)

    def add_control(self, widget, stretch=0, alignment=Qt.AlignLeft, height=32):
        if height is not None:
            widget.setFixedHeight(height)
        self.controls.addWidget(widget, stretch, alignment)



class DirPickerCard(SettingCard):
    """目录选择卡：右侧两个按钮 = 「选择…」（弹目录选择）+「打开」（资源管理器打开当前路径）。"""

    chooseClicked = Signal()
    openClicked = Signal()

    def __init__(self, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.choose_btn = PushButton("选择…", self)
        self.open_btn = PushButton("打开", self)
        self.choose_btn.clicked.connect(self.chooseClicked)
        self.open_btn.clicked.connect(self.openClicked)
        self.hBoxLayout.addWidget(self.choose_btn, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addWidget(self.open_btn, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)



class OutFolderCard(SettingCard):
    """「OCR/ASR 输出目录」一体卡：右侧开关 + 目录名输入框。

    勾选：批量 OCR/ASR 生成的 md 汇总到 <源文件夹>/<目录名>（默认「输出」）；
    不勾选：每份 md 直接写在源文件旁边。输入框仅勾选时可用。
    """

    checkedChanged = Signal(bool)

    def __init__(self, icon, parent=None):
        super().__init__(icon, "OCR/ASR 输出目录",
                         "勾选后：批量 OCR/ASR 生成的 md 汇总到\n源文件夹下新建的子目录，目录名可自定义；\n不勾选：每份 md 直接写在源文件旁边",
                         parent)
        self.dir_edit = LineEdit(self)
        self.dir_edit.setPlaceholderText("输出")
        self.dir_edit.setClearButtonEnabled(True)
        self.dir_edit.setFixedWidth(150)
        self.switch_button = SwitchButton(self)
        self.switch_button.checkedChanged.connect(self._on_checked)
        self.hBoxLayout.addWidget(self.dir_edit, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addWidget(self.switch_button, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)
        # 三行说明：默认卡高 70px 放不下，加高到 112px
        self.setFixedHeight(112)
        self._sync_edit_enabled()

    def _on_checked(self, checked: bool):
        self._sync_edit_enabled()
        self.checkedChanged.emit(checked)

    def _sync_edit_enabled(self):
        self.dir_edit.setEnabled(self.switch_button.isChecked())

    def isChecked(self):
        return self.switch_button.isChecked()

    def setChecked(self, checked: bool):
        self.switch_button.setChecked(checked)
        self._sync_edit_enabled()


class WindowPickerDialog(QDialog):
    """选择要捕获的应用窗口（列表对话框）。

    枚举当前可见顶层窗口，双击或点确定返回 (hwnd, 标题, 宽, 高)；
    目标窗口即使被其他画面遮挡，后续捕获也能取到其真实内容。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择应用窗口")
        self.resize(600, 440)
        self.selected = None
        self._items = []

        layout = QVBoxLayout(self)
        hint = CaptionLabel("选择要捕获的窗口（被遮挡也能取到其真实画面）：")
        layout.addWidget(hint)

        self.list_widget = QListWidget(self)
        self.list_widget.itemDoubleClicked.connect(self._accept)
        layout.addWidget(self.list_widget, 1)

        btns = QHBoxLayout()
        refresh_btn = PushButton("刷新列表")
        refresh_btn.clicked.connect(self._refresh)
        ok_btn = PrimaryPushButton("确定")
        ok_btn.clicked.connect(self._accept)
        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(refresh_btn)
        btns.addStretch(1)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        self._refresh()

    def _refresh(self):
        from capture.capture import enum_visible_windows
        self.list_widget.clear()
        self._items = []
        try:
            parent_hwnd = int(self.parent().winId()) if self.parent() else None
        except Exception:
            parent_hwnd = None
        for hwnd, title, w, h in enum_visible_windows(exclude_hwnd=parent_hwnd):
            self._items.append((hwnd, title, w, h))
            self.list_widget.addItem("%s    [%dx%d]" % (title, w, h))

    def _accept(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self.selected = self._items[row]
            self.accept()

    @staticmethod
    def pick(parent=None):
        """弹出选择对话框，返回 (hwnd, 标题, 宽, 高) 或 None（取消）。"""
        dlg = WindowPickerDialog(parent)
        if dlg.exec():
            return dlg.selected
        return None
