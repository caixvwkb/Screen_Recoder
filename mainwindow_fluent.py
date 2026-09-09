# -*- coding: utf-8 -*-
"""ScreenRecorder UI 重构版（2.3.13）：基于 PySide6-Fluent-Widgets 的 Fluent 风格界面。

重构原则（见 需求和开发记录文档.md · UI 重构选型）：
- 功能逻辑不动：ocr.py / asr.py / export_worker.py / capture.py / folder_ocr.py 全保留，
  仅重做表现层；
- 5 个功能页（视频 / 散图 / PDF / OCR / ASR）+ 底部设置页；
- 每个大功能分块 = 可点击折叠的 ExpandGroupSettingCard（点击标题栏展开/收起）；
- 设置页承载旧版全局设置（保持置顶 / 输出目录 / 快捷键 / 目录工具）；
- 旧版 mainwindow.py 不删除、不使用，仅作功能参考；
- 本文件逐步迁移验证后，再切换为正式入口。

当前进度：主界面框架 + 设置页全局选项，功能页逐页迁移中。
"""
import tracelog
import os
import sys

from PySide6.QtCore import (Qt, QStandardPaths, Signal, QEvent, QPoint, QRect,
                            QTimer, QUrl, QVariantAnimation, QEasingCurve)
from PySide6.QtGui import QDesktopServices, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QFileDialog, QDialog, QMenu, QInputDialog, QSpinBox,
                               QDoubleSpinBox, QProgressBar)

from ui.debug_console import DebugConsole, install as install_log_bridge

from qfluentwidgets import (
    FluentWindow,
    FluentIcon,
    NavigationItemPosition,
    NavigationToolButton,
    setTheme,
    setThemeColor,
    Theme,
    isDarkTheme,
    ScrollArea,
    HeaderCardWidget,
    ExpandGroupSettingCard,
    SettingCard,
    SettingCardGroup,
    PushSettingCard,
    PushButton,
    PrimaryPushButton,
    SwitchSettingCard,
    SwitchButton,
    LineEdit,
    ComboBox,
    SpinBox,
    DoubleSpinBox,
    BodyLabel,
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    CardWidget,
    HorizontalSeparator,
)
from qfluentwidgets.components.settings.setting_card import SettingIconWidget

from datetime import datetime

from settings_manager import SettingsManager
from shortcut_manager import ShortcutManager, ShortcutEditDialog
from capture import ScreenRecorder, ImageCapture, PDFExporter
from region_selector import SelectionWindow
from global_hotkey import GlobalHotkeyManager
from export_worker import SidecarWorker, PDFExportWorker
from ui.widgets import FeaturePage, TwoRowCard, DirPickerCard, OutFolderCard
from ui.pages.video_page import VideoPageMixin
from ui.pages.image_page import ImagePageMixin
from ui.pages.pdf_page import PdfPageMixin
from ui.pages.ocr_page import OcrPageMixin
from ui.pages.asr_page import AsrPageMixin
import sound_feedback

APP_THEME_COLOR = "#0078D4"  # Windows 11 蓝
DEFAULT_SHORTCUTS = ShortcutManager.DEFAULT_SHORTCUTS

# 页面注册表：名称 / 图标 / 副标题 / 大功能分块（icon, 标题, 副标题, 占位说明）
PAGE_DEFS = [
    ("散图录制", FluentIcon.PHOTO, "散图 / 手动截图录制", [
        (FluentIcon.CAMERA, "截图区域", "全屏 / 框选区域", None),
        (FluentIcon.FOLDER, "保存设置", "散图命名与保存目录", None),
        (FluentIcon.PLAY, "截图控制", "手动批量 / 自动连拍", None),
    ]),
    ("PDF 输出", FluentIcon.DOCUMENT, "PDF 打包输出录制", [
        (FluentIcon.CAMERA, "页面设置", "截图区域与页面参数", None),
        (FluentIcon.FOLDER, "输出设置", "输出目录与命名", None),
        (FluentIcon.PLAY, "录制控制", "手动批量 / 自动连拍", None),
    ]),
    ("OCR 识别", FluentIcon.SEARCH, "图片 / PDF 批量 OCR 文字识别", [
        (FluentIcon.FOLDER, "识别源", "文件夹与扫描范围", None),
        (FluentIcon.SETTING, "识别设置", "并发数与合并输出", None),
        (FluentIcon.PLAY, "识别控制", "批量识别与进度", None),
    ]),
    ("视频录制", FluentIcon.VIDEO, "屏幕 / 区域视频录制", [
        (FluentIcon.CAMERA, "录制区域", "全屏 / 自定义窗口", None),
        (FluentIcon.SETTING, "视频参数", "帧率、码率、编码", None),
        (FluentIcon.VOLUME, "音频设置", "内录 / 麦克风 / MP3 纯音频", None),
        (FluentIcon.PLAY, "录制控制", "开始 / 暂停 / 停止", None),
    ]),
    ("ASR 识别", FluentIcon.MICROPHONE, "音频 / 视频语音转写", [
        (FluentIcon.FOLDER, "识别源", "文件夹与扫描范围", None),
        (FluentIcon.SETTING, "识别设置", "并发与处理格式", None),
        (FluentIcon.PLAY, "识别控制", "批量转写与进度", None),
    ]),
]

# 快捷键动作 → 各功能页对应方法（蓝色高亮页 = 快捷键目标页，通用语意按当前页路由）
_PAGE_ACTION_MAP = {
    "video": {
        "select_region": "_select_video_region",
        "start_recording": "_start_video_recording",
        "stop_recording": "_stop_video_recording",
    },
    "image": {
        "select_region": "_select_image_region",
        "start_recording": "_start_batch_capture",
        "stop_recording": "_stop_batch_capture",
        "capture_image": "_capture_image",
    },
    "pdf": {
        "select_region": "_select_pdf_region",
        "start_recording": "_start_pdf_batch_capture",
        "stop_recording": "_stop_pdf_batch_capture",
        "capture_image": "_pdf_capture_image",
    },
}
_ACTION_NAMES = {
    "select_region": "框选录制范围",
    "start_recording": "开始",
    "stop_recording": "结束",
    "capture_image": "截取",
}






def _enable_content_two_line(card) -> None:
    """开启说明文字自动折行；实际高度由 SettingsPage.resizeEvent 按行数修正。

    SettingCard 的 hBoxLayout 里 vBox 会被 stretch 空项挤到很窄（~200px），
    文字挤在左边；这里强制说明区最小宽度，让布局把剩余宽度分给文字区。
    """
    try:
        lbl = card.contentLabel
        lbl.setWordWrap(True)
        lbl.setMinimumWidth(380)
    except Exception:
        pass


class SettingsPage(QWidget):
    """设置页：外观 / 通用 / 全局快捷键 / 存储与目录（对照旧版全局设置迁移）。"""

    def __init__(self, app_data_dir: str, output_dir: str, parent=None):
        super().__init__(parent)
        self.setObjectName("page_设置")
        self._app_data_dir = app_data_dir
        self._output_dir = output_dir

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("scroll_设置")

        container = QWidget()
        container.setObjectName("container_设置")
        v = QVBoxLayout(container)
        v.setContentsMargins(48, 32, 48, 32)
        v.setSpacing(12)

        header = HeaderCardWidget(container)
        header.setTitle("设置")
        header.viewLayout.addWidget(BodyLabel("全局偏好设置", header))
        header.viewLayout.addStretch(1)
        v.addWidget(header)

        # ---------- 外观 ----------
        appearance = SettingCardGroup("外观", container)
        self.dark_switch = SwitchSettingCard(
            FluentIcon.VIEW, "深色模式", "开启深色主题，关闭为浅色主题", parent=appearance
        )
        # 注意：SwitchSettingCard.setChecked 只写配置不改 UI，必须用 switchButton.setChecked
        # 默认深色主题（用户偏好；有配置文件时由 _load_settings 覆盖）
        self.dark_switch.switchButton.setChecked(True)
        appearance.addSettingCard(self.dark_switch)
        v.addWidget(appearance)

        # ---------- 通用 ----------
        general = SettingCardGroup("通用", container)
        self.auto_ocr_switch = SwitchSettingCard(
            FluentIcon.SEARCH, "自动 OCR 识别",
            "勾选后，录屏 / 截图 / PDF 输出时自动识别文字并附带说明", parent=general
        )
        general.addSettingCard(self.auto_ocr_switch)

        self.auto_asr_switch = SwitchSettingCard(
            FluentIcon.MICROPHONE, "视频自动转写",
            "勾选后，录制的视频自动转写语音（ASR）", parent=general
        )
        general.addSettingCard(self.auto_asr_switch)

        self.always_on_top_switch = SwitchSettingCard(
            FluentIcon.UP, "保持置顶", "窗口始终显示在其他应用之上", parent=general
        )
        general.addSettingCard(self.always_on_top_switch)

        self.debug_console_switch = SwitchSettingCard(
            FluentIcon.CODE, "隐藏调试浮窗",
            "默认勾选=隐藏；取消勾选即时弹出独立文本浮窗，像终端一样实时滚动输出日志（无需重启）",
            parent=general
        )
        # 默认勾选（隐藏终端）；有配置文件时由 _load_settings 覆盖
        self.debug_console_switch.switchButton.setChecked(True)
        _enable_content_two_line(self.debug_console_switch)
        general.addSettingCard(self.debug_console_switch)

        self.sound_feedback_switch = SwitchSettingCard(
            FluentIcon.VOLUME, "操作提示音",
            "快捷键/截图操作成功或失败时播放系统提示音，便于最小化或后台运行时感知操作结果",
            parent=general
        )
        # 默认开启；有配置文件时由 _load_settings 覆盖
        self.sound_feedback_switch.switchButton.setChecked(True)
        _enable_content_two_line(self.sound_feedback_switch)
        general.addSettingCard(self.sound_feedback_switch)

        self.recorder_guard_switch = SwitchSettingCard(
            FluentIcon.POWER_BUTTON, "录制守护（后台常驻）",
            "其他应用全屏（游戏/视频）时保持录制后台进行：抓帧瞬时异常自动重试，"
            "录制线程异常不中断、进程不崩溃；关闭后维持旧行为（一次异常即中断）",
            parent=general
        )
        # 默认开启；有配置文件时由 _load_settings 覆盖
        self.recorder_guard_switch.switchButton.setChecked(True)
        _enable_content_two_line(self.recorder_guard_switch)
        general.addSettingCard(self.recorder_guard_switch)

        self.out_folder_card = OutFolderCard(FluentIcon.FOLDER, parent=general)
        general.addSettingCard(self.out_folder_card)
        v.addWidget(general)

        # ---------- 全局快捷键 ----------
        shortcut_group = SettingCardGroup("全局快捷键", container)
        self.shortcut_cards = {}
        for name, key in DEFAULT_SHORTCUTS.items():
            card = PushSettingCard(
                key, FluentIcon.CODE, self._shortcut_label(name),
                "点击按钮修改快捷键", shortcut_group)
            shortcut_group.addSettingCard(card)
            self.shortcut_cards[name] = card
        shortcut_hint = CaptionLabel(
            "快捷键作用于当前停留的功能页（导航栏蓝色高亮页）：框选/开始/结束/截取"
            "会路由到该页对应操作；页面不支持的动作会弹出提示。")
        shortcut_hint.setWordWrap(True)
        shortcut_hint.setContentsMargins(16, 2, 16, 8)
        shortcut_group.vBoxLayout.addWidget(shortcut_hint)
        v.addWidget(shortcut_group)

        # ---------- 模型（OCR / ASR 集中管理） ----------
        model_group = SettingCardGroup("模型", container)
        self.ocr_model_dir = ""
        self.ocr_model_card = DirPickerCard(
            FluentIcon.SEARCH, "OCR 模型路径", "自动探测（默认）", model_group)
        model_group.addSettingCard(self.ocr_model_card)
        self.asr_model_dir = ""
        self.asr_model_card = DirPickerCard(
            FluentIcon.MICROPHONE, "ASR 模型路径", "自动探测（默认）", model_group)
        model_group.addSettingCard(self.asr_model_card)
        self.reset_model_card = PushSettingCard(
            "恢复自动探测", FluentIcon.SYNC, "模型自动探测",
            "清空 OCR / ASR 自定义路径，恢复默认探测程序旁的 models/ocr、models/asr",
            model_group)
        model_group.addSettingCard(self.reset_model_card)
        model_hint = CaptionLabel(
            "留空 = 自动探测程序旁的 models/ocr、models/asr 目录；"
            "模型不打包进 exe，随程序文件夹分发。", model_group)
        model_hint.setWordWrap(True)
        v.addWidget(model_group)
        v.addWidget(model_hint)

        # ---------- 存储与目录 ----------
        storage = SettingCardGroup("存储与目录", container)
        self.open_settings_card = PushSettingCard(
            "打开", FluentIcon.SETTING, "设置文件目录",
            self._app_data_dir, storage)
        storage.addSettingCard(self.open_settings_card)
        self.open_output_card = PushSettingCard(
            "打开", FluentIcon.DOWNLOAD, "输出默认目录",
            self._output_dir, storage)
        storage.addSettingCard(self.open_output_card)
        v.addWidget(storage)
        v.addStretch(1)

        self.scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)

        # 长说明卡片（自动折行）集合：resize 时按实际宽度重算高度
        self._wrap_cards = [c for c in (
            getattr(self, "debug_console_switch", None),
            getattr(self, "sound_feedback_switch", None),
            getattr(self, "recorder_guard_switch", None),
        ) if c is not None]
        self._wrap_cards_lines = {}   # id(card) -> 上次行数（行数变化才改高度，防递归）

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fix_wrap_card_heights()

    def _fix_wrap_card_heights(self):
        """长说明卡片：按当前内容区实际宽度计算折行数，把卡片高度调到
        (基础 70 + 额外行数×行高)，避免多行文字被 70px 固定高裁剪（上下遮挡）。"""
        for card in self._wrap_cards:
            try:
                lbl = card.contentLabel
                fm = lbl.fontMetrics()
                avail = lbl.width()
                if avail <= 0:
                    continue
                txt = lbl.text()
                lines = 1
                cur = ""
                for ch in txt:
                    if fm.horizontalAdvance(cur + ch) > avail:
                        lines += 1
                        cur = ch
                    else:
                        cur += ch
                key = id(card)
                if self._wrap_cards_lines.get(key) == lines:
                    continue
                self._wrap_cards_lines[key] = lines
                line_h = fm.height()
                lbl.setMinimumHeight(lines * line_h + 2)
                card.setFixedHeight(70 + (lines - 1) * line_h)
            except Exception:
                pass

    @staticmethod
    def _shortcut_label(key: str) -> str:
        return {
            "select_region": "选择录制区域",
            "start_recording": "开始录制",
            "stop_recording": "停止录制",
            "capture_image": "截取图片",
        }.get(key, key)


class MainWindow(VideoPageMixin, ImagePageMixin, PdfPageMixin,
                 OcrPageMixin, AsrPageMixin, FluentWindow):
    """ScreenRecorder 2.3.13 主窗口（Fluent 风格）。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ScreenRecorder 2.3.13")
        # 录屏软件窗口不宜过大（避免录制时遮挡画面）：默认约 720×640
        self.resize(720, 640)
        self.setMinimumSize(600, 480)

        # 绿色化数据目录：随程序走（打包后=exe 同级；源码运行=项目根）
        from paths import app_root, cache_dir, default_output_dir, settings_file
        self.app_data_dir = app_root()
        self.cache_dir = cache_dir()
        self.output_dir = default_output_dir()
        self.settings_manager = SettingsManager(self.app_data_dir)
        self.shortcut_manager = ShortcutManager(settings_file())
        self._migrate_legacy_settings()

        # Fluent 主题：跟随系统 + 品牌色
        setTheme(Theme.AUTO)
        setThemeColor(APP_THEME_COLOR)

        # 调试浮窗：独立窗口实时滚动输出 tracelog（不依赖控制台，
        # 源码/打包版一致；显示与否由设置「隐藏调试终端」即时控制）
        self._debug_console = DebugConsole()
        self._log_bridge = install_log_bridge(self._debug_console)

        # 全局热键统一管理：启动即注册（含用户自定义）、退出才注销。
        # image_page 的批量 Enter 截图复用本实例（hasattr 检测），避免实例冲突。
        self.global_hotkeys = GlobalHotkeyManager(self)
        self.global_hotkeys.activated.connect(self._route_action)
        self.global_hotkeys.install(QApplication.instance())

        self._build_navigation()
        self._build_settings_page()
        self._nav_current = ""
        self._load_settings()
        # 快捷键按「当前停留页」路由：应用内快捷键绑定（框选/开始/结束/截取）
        self._bind_app_shortcuts()
        # 全局热键常驻注册（读用户自定义；Enter 截图除外——万能确认键，会话期临时）
        self._register_global_hotkeys()
        # 导航切换时记录最后停留页（持久化，启动恢复）
        # FluentWindow 内部用 stackedWidget.currentChanged 驱动导航高亮，直接复用该信号
        self.stackedWidget.currentChanged.connect(self._on_interface_changed)
        self._restore_last_page()
        # 首次运行（无配置文件）：立即落盘一份默认配置，
        # 保证 settings.json 存在、用户可见可预期（后续改动才保存）
        if not os.path.exists(settings_file()):
            self._save_settings()
        # 首次运行（无配置文件）：立即落盘一份默认配置，
        # 保证 settings.json 存在、用户可见可预期（后续改动才保存）
        if not os.path.exists(os.path.join(self.app_data_dir, "settings.json")):
            self._save_settings()
        # 导航栏右键菜单：等初始化全部完成后再挂事件过滤器，避免 __init__ 早期触发
        self.navigationInterface.panel.installEventFilter(self)
        # 首帧布局完全激活后再同步一次折叠块展开高度（showEvent 时可能仍有卡未布局）
        QTimer.singleShot(80, self._sync_all_expand_heights)

    def _migrate_legacy_settings(self):
        """旧版（%AppData%/python/ScreenRecorder/settings.json）配置一次性迁移。

        绿色化后配置改存程序目录：若新位置无配置而旧位置有，复制过去，
        保留用户快捷键/主题等设置。旧文件保留不删（安全回退）。

        注意：**打包版跳过迁移**（is_compiled）。打包版应首次运行生成全新默认配置
        （exe 同级），迁移会把源码开发期的测试路径/选项带进分发版本，造成
        "打包版设置和开发版一样"的困惑；迁移仅服务于源码开发环境。
        """
        from paths import is_compiled, settings_file
        if is_compiled():
            return
        target = settings_file()
        if os.path.exists(target):
            return
        legacy = os.path.join(
            QStandardPaths.writableLocation(QStandardPaths.AppDataLocation),
            "ScreenRecorder", "settings.json")
        try:
            if os.path.exists(legacy):
                import shutil
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(legacy, target)
                tracelog.info(f"[设置] 已迁移旧配置: {legacy} -> {target}")
        except Exception as e:
            tracelog.warn(f"[设置] 旧配置迁移失败: {e}")

    def _sync_all_expand_heights(self):
        for i in range(self.stackedWidget.count()):
            page = self.stackedWidget.widget(i)
            for card in getattr(page, "block_cards", {}).values():
                page._sync_expand_height(card)

    # ---------------- 页面构建 ----------------

    def _build_navigation(self):
        # 导航栏右键菜单（隐藏页面 / 添加页面 / 恢复）——安装时机见 __init__ 末尾
        self._nav_meta = {}
        self._nav_hidden = []
        self._nav_custom_pages = []
        self._page_builders = {}   # objectName -> (build_fn, page)（懒构建：剩余页延迟填充）
        self._page_built = set()   # 已构建完成的页面 objectName
        builders = {
            "视频录制": self._build_video_page,
            "散图录制": self._build_image_page,
            "PDF 输出": self._build_pdf_page,
            "OCR 识别": self._build_ocr_page,
            "ASR 识别": self._build_asr_page,
        }
        for title, icon, subtitle, blocks in PAGE_DEFS:
            page = FeaturePage(title, subtitle, blocks)
            self._nav_meta[page.objectName()] = (icon, title, NavigationItemPosition.TOP)
            self.addSubInterface(page, icon, title)
            fn = builders.get(title)
            if fn is None:
                continue
            if title == "视频录制":
                # 视频页立即构建：_load_settings 需要 self.video_page 恢复视频参数
                fn(page)
                self._page_built.add(page.objectName())
            else:
                self._page_builders[page.objectName()] = (fn, page)
        # 事件循环空闲时逐个预构建剩余页面（不阻塞首屏显示）
        QTimer.singleShot(0, self._build_lazy_pages)
        # 兜底：切到尚未构建的页面时立即同步构建，保证切换瞬间页面完整
        self.stackedWidget.currentChanged.connect(self._ensure_page_built)

        # 底部：关于软件按钮（打开「关于」对话框）
        self._about_btn = NavigationToolButton(FluentIcon.INFO)
        self._about_btn.setToolTip("关于软件")

    # ---------------- 页面懒构建 ----------------

    def _build_lazy_pages(self):
        """事件循环空闲时预构建页面：先同步构建当前显示页（保证首屏完整），
        其余页面每 10ms 逐个预构建（避免一次卡顿）。"""
        w = self.stackedWidget.currentWidget()
        if w is not None and w.objectName() in self._page_builders:
            self._build_page(w.objectName())
        for name in list(self._page_builders):
            QTimer.singleShot(10, lambda n=name: self._build_page(n))

    def _build_page(self, name):
        """构建指定页面（幂等）；构建完成后从待建表移除。"""
        if name in self._page_built:
            return
        item = self._page_builders.pop(name, None)
        if item is None:
            return
        fn, page = item
        try:
            fn(page)
        finally:
            self._page_built.add(name)

    def _ensure_page_built(self, index):
        """切换兜底：切到尚未构建的页面时立即同步构建。"""
        w = self.stackedWidget.currentWidget()
        if w is None:
            return
        name = w.objectName()
        if name not in self._page_built and name in self._page_builders:
            self._build_page(name)

    def _build_settings_page(self):
        self._about_btn.clicked.connect(self._show_about_dialog)
        self.navigationInterface.addWidget(
            "aboutButton", self._about_btn, self._show_about_dialog,
            NavigationItemPosition.BOTTOM,
        )

    # ---------------- 视频录制页 ----------------

    def _apply_spin_qss(self):
        """帧率/间隔数值输入框主题感知样式（qfluentwidgets SpinBox 渲染失效的替代方案）。"""
        for attr in ("interval_spin",):
            w = getattr(self, attr, None)
            if w is not None:
                self._apply_num_qss(w)

    def _apply_num_qss(self, w):
        """给标准 QSpinBox / QDoubleSpinBox 应用深/浅色主题样式。"""
        dark = isDarkTheme()
        bg = "#2b2b2b" if dark else "#ffffff"
        fg = "#ffffff" if dark else "#1f1f1f"
        border = "#5a5a5a" if dark else "#c8c8c8"
        sel = "#3d7eff" if dark else "#d0e0ff"
        cls = "QDoubleSpinBox" if isinstance(w, QDoubleSpinBox) else "QSpinBox"
        w.setStyleSheet(f"""
{cls} {{
    background-color: {bg}; color: {fg};
    border: 1px solid {border}; border-radius: 6px;
    padding: 2px 8px; selection-background-color: {sel};
}}
{cls}::up-button, {cls}::down-button {{
    width: 20px; border: none; background: transparent;
}}
{cls}::up-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 6px solid {fg};
}}
{cls}::down-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 6px solid {fg};
}}
""")
































    def _check_ocr_model(self):
        """OCR 模型可用性轻量检查（仅文件存在性，不加载引擎）。"""
        model_dir = self._ocr_model_dir()
        if model_dir:
            try:
                from ocr import models_complete
                return models_complete(model_dir)
            except Exception:
                return False
        return True  # 空=自动探测，交给引擎

    def _check_asr_model(self):
        """ASR 模型可用性轻量检查（SenseVoice：model*.onnx + tokens.txt，不加载引擎）。"""
        model_dir = self._asr_model_dir()
        if model_dir:
            try:
                from asr import models_complete
                return models_complete(model_dir)
            except Exception:
                return False
        return True  # 空=自动探测，交给引擎






















    def _apply_progress_qss(self):
        bar = getattr(self, "pdf_progress_bar", None)
        if bar is None:
            return
        dark = isDarkTheme()
        chunk = "#3d7eff"
        bg = "#2b2b2b" if dark else "#e8e8e8"
        border = "#5a5a5a" if dark else "#c0c0c0"
        bar.setStyleSheet(f"""
QProgressBar {{
    background-color: {bg}; border: 1px solid {border};
    border-radius: 7px; text-align: center;
}}
QProgressBar::chunk {{
    background-color: {chunk}; border-radius: 6px;
}}
""")

    # ---- PDF 区域选择 ----




















    def eventFilter(self, obj, event):
        if (hasattr(self, "navigationInterface")
                and obj is getattr(self.navigationInterface, "panel", None)
                and event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.RightButton):
            self._show_nav_context_menu(event.globalPosition().toPoint())
            return True
        return super().eventFilter(obj, event)

    def _nav_item_at(self, global_pos):
        """返回 global_pos 命中的导航项 routeKey；空白返回 None。"""
        panel = self.navigationInterface.panel
        for route_key, item in list(panel.items.items()):
            wid = item.widget
            g = wid.mapToGlobal(QPoint(0, 0))
            if QRect(g, wid.size()).contains(global_pos):
                return route_key
        return None

    def _show_nav_context_menu(self, global_pos):
        hit = self._nav_item_at(global_pos)
        menu = QMenu(self)
        if hit and hit in self._nav_meta:
            text = self._nav_meta[hit][1]
            menu.addAction(f"隐藏「{text}」", lambda: self._hide_nav_item(hit))
            # 自定义页支持彻底删除
            name = hit[len("page_"):] if hit.startswith("page_") else ""
            if name in self._nav_custom_pages:
                menu.addAction(f"删除「{text}」", lambda: self._delete_nav_page(hit))
        else:
            menu.addAction("添加导航页面", self._add_nav_page)
            menu.addAction("恢复被隐藏的页面", self._restore_nav_default)
        menu.exec(global_pos)

    def _delete_nav_page(self, route_key):
        """彻底删除自定义导航页面：导航栏、页面栈、持久化列表一并移除。"""
        if route_key not in self._nav_meta:
            return
        text = self._nav_meta[route_key][1]
        page = self.stackedWidget.findChild(QWidget, route_key)
        self.navigationInterface.removeWidget(route_key)
        if page is not None:
            self.stackedWidget.removeWidget(page)
            page.deleteLater()
        self._nav_meta.pop(route_key, None)
        self._nav_hidden = [k for k in self._nav_hidden if k != route_key]
        name = route_key[len("page_"):] if route_key.startswith("page_") else ""
        if name in self._nav_custom_pages:
            self._nav_custom_pages.remove(name)
        self._save_settings()
        self._show_tip("已删除", f"「{text}」页面已彻底删除")

    def _hide_nav_item(self, route_key):
        """隐藏导航页面：从导航栏移除图标，页面保留（可恢复）。"""
        self.navigationInterface.removeWidget(route_key)
        if route_key not in self._nav_hidden:
            self._nav_hidden.append(route_key)
        self._save_settings()
        self._show_tip("已隐藏",
                       f"「{self._nav_meta[route_key][1]}」已从导航栏移除（右键空白处可恢复）")

    def _add_nav_page(self):
        """添加自定义导航页面（占位功能页）。"""
        name, ok = QInputDialog.getText(self, "添加导航页面", "页面名称：")
        name = (name or "").strip()
        if not ok or not name:
            return
        route_key = f"page_{name}"
        if route_key in self.navigationInterface.panel.items:
            self._show_tip("页面已存在", f"「{name}」已存在，请换一个名称")
            return
        page = FeaturePage(name, "自定义页面（导航栏右键添加）",
                           [(FluentIcon.APPLICATION, "功能区", "自定义页面", "在此开发新功能")])
        self.addSubInterface(page, FluentIcon.APPLICATION, name)
        self._nav_meta[route_key] = (FluentIcon.APPLICATION, name, NavigationItemPosition.TOP)
        self._nav_custom_pages.append(name)
        self._save_settings()
        self.navigationInterface.setCurrentItem(route_key)

    def _restore_nav_default(self):
        """恢复所有被隐藏的导航页面。"""
        restored = 0
        for route_key in list(self._nav_hidden):
            icon, text, position = self._nav_meta.get(
                route_key, (FluentIcon.APPLICATION, route_key, NavigationItemPosition.TOP))
            page = self.stackedWidget.findChild(QWidget, route_key)
            if page is None:
                continue
            self.navigationInterface.addItem(
                route_key, icon, text,
                onClick=lambda p=page: self.switchTo(p),
                position=position, tooltip=text)
            self._nav_hidden.remove(route_key)
            restored += 1
        if restored:
            self._save_settings()
            self._show_tip("已恢复", f"恢复了 {restored} 个页面")
        else:
            self._show_tip("没有可恢复的页面", "右键导航栏空白处可添加新页面")

    def _build_settings_page(self):
        self.settings_page = SettingsPage(self.app_data_dir, self.output_dir, self)
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)
        self._nav_meta["page_设置"] = (FluentIcon.SETTING, "设置", NavigationItemPosition.BOTTOM)

        sp = self.settings_page
        sp.dark_switch.checkedChanged.connect(self._apply_theme)
        sp.always_on_top_switch.checkedChanged.connect(self._toggle_always_on_top)
        sp.auto_ocr_switch.checkedChanged.connect(self._save_settings)
        sp.auto_asr_switch.checkedChanged.connect(self._save_settings)
        sp.debug_console_switch.checkedChanged.connect(self._on_debug_console_changed)
        sp.sound_feedback_switch.checkedChanged.connect(self._on_sound_feedback_changed)
        sp.recorder_guard_switch.checkedChanged.connect(self._save_settings)
        sp.out_folder_card.checkedChanged.connect(self._save_settings)
        sp.out_folder_card.dir_edit.editingFinished.connect(self._save_settings)
        sp.open_settings_card.clicked.connect(lambda: self._open_dir(self.app_data_dir))
        sp.open_output_card.clicked.connect(lambda: self._open_dir(self.output_dir))
        sp.ocr_model_card.chooseClicked.connect(lambda: self._choose_model_dir("ocr"))
        sp.asr_model_card.chooseClicked.connect(lambda: self._choose_model_dir("asr"))
        sp.ocr_model_card.openClicked.connect(lambda: self._open_model_dir("ocr"))
        sp.asr_model_card.openClicked.connect(lambda: self._open_model_dir("asr"))
        sp.reset_model_card.clicked.connect(self._reset_model_dir)
        for name in sp.shortcut_cards:
            sp.shortcut_cards[name].clicked.connect(
                lambda _=False, n=name: self._edit_shortcut(n))

    # ---------------- 设置持久化 ----------------

    def _load_settings(self):
        settings = self.settings_manager.load()
        sp = self.settings_page
        if "always_on_top" in settings:
            sp.always_on_top_switch.switchButton.setChecked(bool(settings["always_on_top"]))
        # 深浅主题统一走 _apply_theme：同时应用 setTheme 与开关状态，
        # 避免"开关显示浅色、界面实际深色"的不一致（主题 bug 根因）
        # 默认深色（无配置时）；有配置按配置
        self._apply_theme(bool(settings.get("dark_mode", True)))
        if "ocr_enabled" in settings:
            sp.auto_ocr_switch.switchButton.setChecked(bool(settings["ocr_enabled"]))
        if "asr_video_auto" in settings:
            sp.auto_asr_switch.switchButton.setChecked(bool(settings["asr_video_auto"]))
        if "debug_console" in settings:
            sp.debug_console_switch.switchButton.setChecked(bool(settings["debug_console"]))
        if "sound_feedback" in settings:
            sp.sound_feedback_switch.switchButton.setChecked(bool(settings["sound_feedback"]))
        sound_feedback.set_enabled(sp.sound_feedback_switch.isChecked())
        if "recorder_guard" in settings:
            sp.recorder_guard_switch.switchButton.setChecked(bool(settings["recorder_guard"]))
        if "ocr_asr_out_enabled" in settings:
            sp.out_folder_card.setChecked(bool(settings["ocr_asr_out_enabled"]))
        if "ocr_asr_out_dir" in settings:
            sp.out_folder_card.dir_edit.setText(str(settings["ocr_asr_out_dir"]))
        if "ocr_model_dir" in settings:
            self._set_model_dir("ocr", str(settings["ocr_model_dir"]))
        if "asr_model_dir" in settings:
            self._set_model_dir("asr", str(settings["asr_model_dir"]))
        self.shortcut_manager.load(settings)
        self._nav_current = str(settings.get("nav_current", ""))
        self._refresh_shortcut_cards()
        # 视频页参数恢复
        vp = getattr(self, "video_page", None)
        if vp is not None:
            if "video_format" in settings:
                idx = self.video_format_combo.findText(str(settings["video_format"]))
                if idx >= 0:
                    self.video_format_combo.setCurrentIndex(idx)
            self._update_fps_visibility(animate=False)
            if "video_fps" in settings:
                target = int(settings["video_fps"])
                idx = self.video_fps_combo.findData(target)
                if idx >= 0:
                    self.video_fps_combo.setCurrentIndex(idx)
                else:
                    # 保存的档位不在当前档位表：回退默认均衡 30
                    self.video_fps_combo.setCurrentIndex(1)
            if "video_path" in settings:
                self.video_path_edit.setText(str(settings["video_path"]))
            if "video_name" in settings:
                self.video_name_edit.setText(str(settings["video_name"]))
            # 音频设置恢复（内录=发声应用会话 JSON / 麦克风=设备 id；无匹配保持「无」）
            audio_enabled = bool(settings.get("video_audio_enabled", False))
            self.video_audio_switch.setChecked(audio_enabled)
            if "video_audio_loopback" in settings:
                idx = self.video_loopback_combo.findData(str(settings["video_audio_loopback"]))
                if idx >= 0:
                    self.video_loopback_combo.setCurrentIndex(idx)
            if "video_audio_mic" in settings:
                idx = self.video_mic_combo.findData(str(settings["video_audio_mic"]))
                if idx >= 0:
                    self.video_mic_combo.setCurrentIndex(idx)
            self._on_video_audio_toggled(audio_enabled)
        # 恢复自定义导航页 + 应用隐藏状态
        panel = self.navigationInterface.panel
        for name in settings.get("nav_custom_pages", []):
            route_key = f"page_{name}"
            if route_key not in panel.items:
                page = FeaturePage(name, "自定义页面（导航栏右键添加）",
                                   [(FluentIcon.APPLICATION, "功能区", "自定义页面", "在此开发新功能")])
                self.addSubInterface(page, FluentIcon.APPLICATION, name)
                self._nav_meta[route_key] = (FluentIcon.APPLICATION, name, NavigationItemPosition.TOP)
        self._nav_custom_pages = list(settings.get("nav_custom_pages", []))
        for route_key in settings.get("nav_hidden", []):
            if route_key in self._nav_meta and route_key not in self._nav_hidden:
                self.navigationInterface.removeWidget(route_key)
                self._nav_hidden.append(route_key)

    def _on_debug_console_changed(self, checked: bool):
        """「隐藏调试终端」开关：勾选=隐藏调试浮窗（默认）；取消勾选=即时弹出浮窗。

        浮窗是 Qt 控件，运行中切换即时生效，无需重启（区别于旧控制台方案）。
        """
        self._save_settings()
        self._apply_debug_console(bool(checked))

    def _apply_debug_console(self, hidden: bool):
        if hidden:
            tracelog.set_level("INFO")
            self._debug_console.hide()
        else:
            tracelog.set_level("DEBUG")
            self._debug_console.show()
            self._debug_console.raise_()
            self._debug_console.activateWindow()

    def _on_sound_feedback_changed(self, checked: bool):
        """「操作提示音」开关：即时切换，无需重启。"""
        sound_feedback.set_enabled(bool(checked))
        self._save_settings()

    # ---------------- 快捷键路由（当前停留页） ----------------

    def _current_page_key(self):
        """当前导航停留页的 key（蓝色高亮页 = 快捷键目标页）。"""
        w = self.stackedWidget.currentWidget()
        if w is self.video_page:
            return "video"
        if w is self.image_page:
            return "image"
        if w is self.pdf_page:
            return "pdf"
        if w is self.ocr_page:
            return "ocr"
        if w is self.asr_page:
            return "asr"
        if w is self.settings_page:
            return "settings"
        return ""

    def _on_interface_changed(self, _index=None):
        """导航切换：记录最后停留页并持久化（启动时恢复）。"""
        key = self._current_page_key()
        if key and key != self._nav_current:
            self._nav_current = key
            self._save_settings()

    def _run_with_sound(self, func, ok_sound="click"):
        """执行一个操作按钮的处理函数，按返回值播放提示音。

        成功：ok_sound 指定（默认 click.wav 普通点击；截取类操作传 "ok" 播 ok.wav）；
        失败（返回 False 或异常）：统一播放 fail.wav。
        """
        try:
            result = func()
            if result is False:
                sound_feedback.play_fail()
            else:
                if ok_sound == "ok":
                    sound_feedback.play_ok()
                else:
                    sound_feedback.play_click()
        except Exception as e:
            tracelog.error(f"[提示音] 操作执行异常: {e}")
            sound_feedback.play_fail()

    def _route_action(self, name: str):
        """通用语意快捷键 → 路由到当前停留页的对应方法。

        name: select_region / start_recording / stop_recording / capture_image
        当前页不支持该动作时提示，不静默。
        路由方法返回 False 表示操作失败（播放失败音），其余视为成功（播放成功音），
        后台/最小化运行时通过提示音感知操作结果。
        """
        key = self._current_page_key()
        method_name = _PAGE_ACTION_MAP.get(key, {}).get(name)
        if method_name and hasattr(self, method_name):
            tracelog.debug(f"[快捷键] {_ACTION_NAMES.get(name, name)} → {key} 页")
            result = getattr(self, method_name)()
            if result is False:
                sound_feedback.play_fail()
            else:
                # 截取类（真正截图）成功播 ok；框选/开始/结束等普通操作播 click
                if name == "capture_image":
                    sound_feedback.play_ok()
                else:
                    sound_feedback.play_click()
        else:
            target = getattr(self, f"{key}_page", None) if key else None
            page_title = target.windowTitle() if target is not None else ""
            self._show_tip(
                f"当前页无「{_ACTION_NAMES.get(name, name)}」操作",
                f"此快捷键在「{page_title or key or '当前页'}」页不适用；请切换到对应功能页")
            sound_feedback.play_fail()

    def _register_global_hotkeys(self):
        """启动/修改快捷键后注册全部全局热键（读用户自定义值），带注册日志。

        Enter（capture_image）例外：它是万能确认键（所有程序回车），常驻全局会
        抢走其它程序的回车确认，保持「批量截图会话期间临时注册」的既有设计。
        Ctrl 系组合（框选/开始/结束）常驻——录屏软件后台待命的标准形态。
        """
        hwnd = int(self.winId())
        for name, default_key in ShortcutManager.DEFAULT_SHORTCUTS.items():
            if name == "capture_image":
                continue
            key = self.shortcut_manager.to_dict().get(name, default_key)
            if not key:
                continue
            if self.global_hotkeys.register(name, key, hwnd=hwnd):
                tracelog.info(f"[热键] 全局注册: {_ACTION_NAMES.get(name, name)} → {key}")
            else:
                tracelog.warn(
                    f"[热键] 全局注册失败: {_ACTION_NAMES.get(name, name)} → {key}"
                    f"（可能被其它程序占用，应用内快捷键仍可用）")

    def closeEvent(self, e):
        """程序退出：注销全部全局热键，避免残留占用系统组合键。"""
        try:
            self.global_hotkeys.unregister_all()
            tracelog.info("[热键] 程序退出，已注销全部全局热键")
        except Exception:
            pass
        super().closeEvent(e)

    def _bind_app_shortcuts(self):
        """绑定应用内快捷键（框选/开始/结束/截取），全部路由到当前停留页。"""
        for sc in getattr(self, "_app_shortcuts", {}).values():
            sc.setParent(None)
            sc.deleteLater()
        self._app_shortcuts = {}
        for name, default_key in ShortcutManager.DEFAULT_SHORTCUTS.items():
            key = self.shortcut_manager.to_dict().get(name, default_key)
            if not key:
                continue
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda n=name: self._route_action(n))
            self._app_shortcuts[name] = sc

    def _rebind_shortcuts(self):
        """快捷键修改后重绑应用内快捷键 + 重注册全局热键（含用户自定义）。"""
        self._bind_app_shortcuts()
        for name in ("select_region", "start_recording", "stop_recording"):
            self.global_hotkeys.unregister(name)
        self._register_global_hotkeys()

    def _restore_last_page(self):
        """启动时恢复上次停留的页面（蓝色高亮同步）。"""
        target = {
            "video": getattr(self, "video_page", None),
            "image": getattr(self, "image_page", None),
            "pdf": getattr(self, "pdf_page", None),
            "ocr": getattr(self, "ocr_page", None),
            "asr": getattr(self, "asr_page", None),
            "settings": getattr(self, "settings_page", None),
        }.get(self._nav_current)
        if target is not None:
            self.stackedWidget.setCurrentWidget(target)

    def _save_settings(self):
        sp = getattr(self, "settings_page", None)
        if sp is None:
            return  # 页面构建早期（settings_page 未建）触发的开关信号，跳过全局部分
        self.settings_manager.save({
            "always_on_top": sp.always_on_top_switch.isChecked(),
            "dark_mode": sp.dark_switch.isChecked(),
            "debug_console": sp.debug_console_switch.isChecked(),
            "sound_feedback": sp.sound_feedback_switch.isChecked(),
            "recorder_guard": sp.recorder_guard_switch.isChecked(),
            "ocr_enabled": sp.auto_ocr_switch.isChecked(),
            "asr_video_auto": sp.auto_asr_switch.isChecked(),
            "ocr_asr_out_enabled": sp.out_folder_card.isChecked(),
            "ocr_asr_out_dir": sp.out_folder_card.dir_edit.text() or "输出",
            "ocr_model_dir": getattr(sp, "ocr_model_dir", "") or "",
            "asr_model_dir": getattr(sp, "asr_model_dir", "") or "",
            "shortcuts": self.shortcut_manager.to_dict(),
            "nav_current": getattr(self, "_nav_current", ""),
            "nav_hidden": getattr(self, "_nav_hidden", []),
            "nav_custom_pages": getattr(self, "_nav_custom_pages", []),
            "video_format": getattr(self, "video_format_combo", None).currentText()
                if hasattr(self, "video_format_combo") else "mp4",
            "video_fps": self.video_fps_combo.currentData() if hasattr(self, "video_fps_combo") else 30,
            "video_path": self.video_path_edit.text() if hasattr(self, "video_path_edit") else "",
            "video_name": self.video_name_edit.text() if hasattr(self, "video_name_edit") else "录制_视频",
            "video_audio_enabled": self.video_audio_switch.isChecked()
                if hasattr(self, "video_audio_switch") else False,
            "video_audio_loopback": self.video_loopback_combo.currentData() or ""
                if hasattr(self, "video_loopback_combo") else "",
            "video_audio_mic": self.video_mic_combo.currentData() or ""
                if hasattr(self, "video_mic_combo") else "",
            "image_format": self.image_format_combo.currentText()
                if hasattr(self, "image_format_combo") else "png",
            "image_path": self.image_path_edit.text() if hasattr(self, "image_path_edit") else "",
            "image_name": self.image_name_edit.text() if hasattr(self, "image_name_edit") else "截图",
            "image_interval": self.interval_spin.value()
                if hasattr(self, "interval_spin") else 1.0,
            "pdf_path": self.pdf_path_edit.text() if hasattr(self, "pdf_path_edit") else "",
            "pdf_name": self.pdf_name_edit.text() if hasattr(self, "pdf_name_edit") else "输出",
            "ocr_folder": self.ocr_folder_edit.text() if hasattr(self, "ocr_folder_edit") else "",
            "ocr_recursive": self.ocr_recursive_switch.isChecked()
                if hasattr(self, "ocr_recursive_switch") else True,
            "ocr_pdf": self.ocr_pdf_switch.isChecked() if hasattr(self, "ocr_pdf_switch") else True,
            "ocr_merge": self.ocr_merge_switch.isChecked()
                if hasattr(self, "ocr_merge_switch") else True,
            "ocr_concurrency": self.ocr_concurrency_spin.value()
                if hasattr(self, "ocr_concurrency_spin") else 2,
            "asr_folder": self.asr_folder_edit.text() if hasattr(self, "asr_folder_edit") else "",
            "asr_recursive": self.asr_recursive_switch.isChecked()
                if hasattr(self, "asr_recursive_switch") else True,
            "asr_formats": self.asr_formats_edit.text()
                if hasattr(self, "asr_formats_edit") else "wav,mp3,m4a,flac,ogg,mp4,mkv,avi,mov,webm",
            "asr_concurrency": self.asr_concurrency_spin.value()
                if hasattr(self, "asr_concurrency_spin") else 2,
        })

    # ---------------- 全局行为 ----------------

    def _set_model_dir(self, kind: str, path: str):
        """更新模型路径并刷新卡片显示；空串 = 自动探测（默认）。"""
        sp = self.settings_page
        path = (path or "").strip()
        card = sp.ocr_model_card if kind == "ocr" else sp.asr_model_card
        if kind == "ocr":
            sp.ocr_model_dir = path
        else:
            sp.asr_model_dir = path
        card.setContent(path or "自动探测（默认）")

    def _ocr_model_dir(self) -> str:
        return getattr(self.settings_page, "ocr_model_dir", "") or ""

    def _asr_model_dir(self) -> str:
        return getattr(self.settings_page, "asr_model_dir", "") or ""

    def _choose_model_dir(self, kind: str):
        """弹目录选择框设置 OCR/ASR 模型路径，并保存。"""
        name = "OCR" if kind == "ocr" else "ASR"
        current = self._ocr_model_dir() if kind == "ocr" else self._asr_model_dir()
        start = current or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
        path = QFileDialog.getExistingDirectory(self, f"选择 {name} 模型目录", start)
        if path:
            self._set_model_dir(kind, path)
            self._save_settings()
            self._show_tip(f"{name} 模型路径已设置", path)

    def _refresh_shortcut_cards(self):
        """把 ShortcutManager 当前快捷键同步到设置页卡片按钮文字。"""
        sp = self.settings_page
        for name, key in self.shortcut_manager.to_dict().items():
            if name in sp.shortcut_cards:
                sp.shortcut_cards[name].button.setText(key)

    def _edit_shortcut(self, name: str):
        """弹快捷键编辑对话框，确定后更新 ShortcutManager 并持久化。"""
        dialog = ShortcutEditDialog(
            current_shortcut=self.shortcut_manager.to_dict().get(name, DEFAULT_SHORTCUTS[name]),
            shortcut_manager=self.shortcut_manager,
            shortcut_key=name,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.shortcut_manager.update(name, dialog.get_shortcut())
            self._refresh_shortcut_cards()
            self._rebind_shortcuts()  # 应用内快捷键重绑（路由当前页）
            self._save_settings()
            self._show_tip("快捷键已更新",
                           f"{self.settings_page._shortcut_label(name)}：{dialog.get_shortcut()}")

    def _reset_model_dir(self):
        """清空 OCR/ASR 自定义模型路径，恢复自动探测。"""
        self._set_model_dir("ocr", "")
        self._set_model_dir("asr", "")
        self._save_settings()
        self._show_tip("已恢复模型自动探测", "将自动查找程序旁的 models/ocr、models/asr")

    def _open_model_dir(self, kind: str):
        """资源管理器打开模型目录：优先当前设置路径，未设置时打开默认探测路径（程序旁 models）。"""
        name = "OCR" if kind == "ocr" else "ASR"
        path = self._ocr_model_dir() if kind == "ocr" else self._asr_model_dir()
        if not path:
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
            candidate = os.path.join(base, "ocr" if kind == "ocr" else "asr")
            path = candidate if os.path.isdir(candidate) else base
        if os.path.isdir(path):
            os.startfile(path)
        else:
            self._show_tip(f"{name} 模型目录不存在", path)

    def _ocr_asr_out_dir(self, src_folder: str) -> str:
        """勾选「输出到独立文件夹」时返回目标目录路径（并创建）；否则返回空串（散在源文件旁）。"""
        sp = self.settings_page
        if not sp.out_folder_card.isChecked():
            return ""
        name = (sp.out_folder_card.dir_edit.text() or "").strip() or "输出"
        out_dir = os.path.join(src_folder, name)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError:
            return ""
        return out_dir

    def _toggle_always_on_top(self, checked: bool):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()
        self._save_settings()

    @staticmethod
    def _open_dir(path: str):
        if os.path.exists(path):
            os.startfile(path)
        else:
            InfoBar.warning("目录不存在", path, duration=2500,
                            position=InfoBarPosition.TOP_RIGHT)

    # ---------------- 主题 ----------------

    def _apply_theme(self, dark: bool):
        """设置深浅色主题，并同步设置页开关状态。"""
        setTheme(Theme.DARK if dark else Theme.LIGHT)
        sw = getattr(self.settings_page, "dark_switch", None)
        if sw is not None:
            sw.switchButton.blockSignals(True)
            sw.switchButton.setChecked(dark)
            sw.switchButton.blockSignals(False)
        self._apply_spin_qss()  # 帧率输入框样式随主题切换
        self._apply_progress_qss()  # PDF 进度条样式随主题切换
        self._debug_console.set_theme(dark)  # 调试浮窗随主题
        self._save_settings()

    def _show_about_dialog(self):
        """关于软件对话框：软件信息 / 版本 / 作者 / 技术栈。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("关于 ScreenRecorder")
        dlg.setFixedWidth(400)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(10)

        # 头部：图标 + 软件名
        head = QHBoxLayout()
        head.setSpacing(12)
        icon = SettingIconWidget(FluentIcon.VIDEO, dlg)
        icon.setFixedSize(44, 44)
        head.addWidget(icon)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = BodyLabel("ScreenRecorder 2.3.13", dlg)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        title_box.addWidget(title)
        sub = CaptionLabel("屏幕录制 · 截图 · OCR/ASR 文字识别", dlg)
        title_box.addWidget(sub)
        head.addLayout(title_box, 1)
        v.addLayout(head)

        v.addWidget(HorizontalSeparator(dlg))

        # 信息行
        info = [
            ("版本", "2.3.13（启动优化与稳定性）"),
            ("作者", "Caixvwkb"),
            ("技术栈", "Python 3.11 · PySide6 · PySide6-Fluent-Widgets"),
            ("打包", "Nuitka（standalone / onefile）"),
            ("功能", "视频录制 / 散图录制 / PDF 打包 / OCR 识别 / ASR 转写"),
        ]
        for k, val in info:
            row = QHBoxLayout()
            row.addWidget(BodyLabel(k, dlg))
            row.addStretch(1)
            lab = CaptionLabel(val, dlg)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(lab)
            v.addLayout(row)

        v.addWidget(HorizontalSeparator(dlg))
        foot = CaptionLabel("仅用于个人学习与工具研究，请勿用于非法用途。", dlg)
        v.addWidget(foot)

        ok = PrimaryPushButton("确定", dlg)
        ok.setFixedWidth(96)
        ok.clicked.connect(dlg.accept)
        v.addWidget(ok, 0, Qt.AlignHCenter)
        dlg.exec()

    def _show_tip(self, title: str, content: str):
        InfoBar.success(title, content, parent=self, duration=1500,
                        position=InfoBarPosition.TOP_RIGHT)


def main():
    import traceback as _tb

    # 全局异常兜底（录制守护的一部分）：未捕获异常只记录日志、不使进程退出，
    # 避免全屏应用切换等场景下的偶发异常把整个软件带崩
    def _excepthook(etype, value, tb):
        try:
            import tracelog
            tracelog.error("[守护] 未捕获异常: " + "".join(_tb.format_exception(etype, value, tb)))
        except Exception:
            _tb.print_exception(etype, value, tb)

    sys.excepthook = _excepthook

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont
    app = QApplication(sys.argv)
    app.setApplicationName("ScreenRecorder")
    # 显式设置默认字体：避免打包版缺字体目录时 Qt 内部解析到无效磅值
    # （QFont::setPointSize(-1) 警告来源），界面文字统一使用系统雅黑
    app.setFont(QFont("Microsoft YaHei UI", 9))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
