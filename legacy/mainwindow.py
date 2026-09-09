# This Python file uses the following encoding: utf-8
"""主窗口（MainWindow）：UI 的“接线员”。

只负责三件事：
  1. 组装界面（ui_form 自动生成的 Ui_MainWindow）
  2. 把按钮 / 菜单 / 快捷键信号连接到对应动作
  3. 维护三种录制模式（视频 / 散图 / PDF）的状态切换与状态栏提示

具体的录制、截图、PDF 导出逻辑都在 capture.py；
选区遮罩在 region_selector.py；设置读写与快捷键管理在
settings_manager.py / shortcut_manager.py。这里不写业务细节。
"""
import os
import sys
from datetime import datetime

from PySide6.QtCore import Qt, QStandardPaths, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QProgressBar, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget, QWidgetAction)

from capture import ImageCapture, PDFExporter, ScreenRecorder
from export_worker import ASRWorker, FolderOcrWorker, PDFExportWorker, SidecarWorker
from folder_ocr import scan_folder
from global_hotkey import GlobalHotkeyManager
from region_selector import SelectionWindow
from settings_manager import SettingsManager
from shortcut_manager import ShortcutEditDialog, ShortcutManager
from ui_form import Ui_MainWindow


class MainWindow(QMainWindow):
    """主窗口：UI 接线员，负责信号连接、状态切换与调用各子模块。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # 初始化变量
        self.selected_region = None
        self.image_selected_region = None
        self.pdf_selected_region = None
        self.is_recording = False
        self.is_image_recording = False
        self.is_pdf_recording = False
        self.selection_window = None
        self.recording_start_time = None
        self.recording_timer = QTimer()
        self.image_capture_count = 0
        self.image_captured_files = []  # 本次批量会话截取的图片文件列表（用于生成说明.md）
        self.pdf_capture_count = 0
        self.screen_recorder = None
        self.image_capture = None
        self.image_output_folder = None
        self.pdf_exporter = None
        self.pdf_temp_folder = None
        self.batch_mode = False  # 批量截图模式
        self.batch_folder = None  # 批量截图的输出文件夹
        self.pdf_batch_mode = False  # PDF 批量截图模式
        self.pdf_temp_images = []  # 存储批量截图的临时图片
        # 后台任务状态锁（防止处理中重复触发）
        self._pdf_exporting = False   # PDF 导出（含 OCR）进行中
        self._sidecar_processing = False  # 散图批量 OCR + 说明.md 生成中
        self._folder_ocr_processing = False  # 「OCR 识别」页批量识别进行中
        self._folder_asr_processing = False  # 「ASR 识别」页批量转写进行中
        self._pdf_export_worker = None
        self._sidecar_worker = None
        self._folder_ocr_worker = None
        self._folder_asr_worker = None

        # 获取应用数据目录
        self.app_data_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        self.app_data_dir = os.path.join(self.app_data_dir, "ScreenRecorder")
        os.makedirs(self.app_data_dir, exist_ok=True)

        # 设置文件路径
        self.settings_file = os.path.join(self.app_data_dir, "settings.json")
        self.output_dir = os.path.join(self.app_data_dir, "Recordings")
        os.makedirs(self.output_dir, exist_ok=True)

        # 设置 / 快捷键管理（负责文件的读写与数据，不接触界面控件）
        self.settings_manager = SettingsManager(self.app_data_dir)
        self.shortcut_manager = ShortcutManager(self.settings_file)

        # OCR 输出开关：控制是否生成 AI 可读的说明/隐形文字层。
        # 文案说明：勾选后，输出的截图/PDF 会自动运行 OCR 识别文字并附带说明文件。
        # 2026-09-07 起该开关与「OCR 并发数」「OCR 模型路径」一起移入「OCR 识别」页内部
        #（与 ASR 页保持一致），此处保留 QAction 对象供散图/PDF 导出逻辑统一判断。
        self.ui.actionOcrEnabled = QAction("OCR 文字识别（勾选后，输出截图/PDF 时自动识别文字并附带说明）", self)
        self.ui.actionOcrEnabled.setCheckable(True)
        self.ui.actionOcrEnabled.setChecked(True)  # 默认开启（rapidocr 未装时静默降级）
        # 用户点击时立即持久化（setChecked 不触发 triggered，load_settings 恢复时不会误保存）
        self.ui.actionOcrEnabled.triggered.connect(self.save_settings)

        # OCR/ASR 输出到独立文件夹（选项菜单）：勾选后批量生成的 md 汇总到源文件夹下指定目录
        self._create_ocr_asr_output_option()

        # 「OCR 识别」功能页（第 4 个 Tab）：选文件夹批量识别图片/PDF，每个文件生成一个说明.md
        self._create_folder_ocr_tab()

        # 「ASR 识别」功能页（第 5 个 Tab）：音频/视频 → 语音转文字（界面骨架，识别功能后续接入）
        self._create_asr_tab()

        # 连接定时器信号
        self.recording_timer.timeout.connect(self.update_recording_duration)

        # 加载设置
        self.load_settings()

        # 连接信号
        self.ui.selectRegionBtn.clicked.connect(self.select_region)
        self.ui.startBtn.clicked.connect(self.start_recording)
        self.ui.stopBtn.clicked.connect(self.stop_recording)
        self.ui.browsePathBtn.clicked.connect(self.browse_output_path)
        self.ui.formatComboBox.currentTextChanged.connect(self.update_video_extension)

        # 散图录制信号
        self.ui.imageSelectRegionBtn.clicked.connect(self.select_image_region)
        self.ui.captureBtn.clicked.connect(self.capture_image)
        self.ui.autoStartBtn.clicked.connect(self.start_image_recording)
        self.ui.autoStopBtn.clicked.connect(self.stop_image_recording)
        self.ui.manualStartBtn.clicked.connect(self.start_batch_capture)
        self.ui.manualStopBtn.clicked.connect(self.stop_batch_capture)
        self.ui.imageBrowsePathBtn.clicked.connect(self.browse_image_path)

        # PDF 输出信号
        self.ui.pdfSelectRegionBtn.clicked.connect(self.select_pdf_region)
        self.ui.pdfCaptureBtn.clicked.connect(self.pdf_capture_image)
        self.ui.pdfManualStartBtn.clicked.connect(self.start_pdf_batch_capture)
        self.ui.pdfManualStopBtn.clicked.connect(self.stop_pdf_batch_capture)
        self.ui.pdfAutoStartBtn.clicked.connect(self.start_pdf_recording)
        self.ui.pdfAutoStopBtn.clicked.connect(self.stop_pdf_recording)
        self.ui.pdfBrowsePathBtn.clicked.connect(self.browse_pdf_path)

        # 连接菜单
        self.ui.actionExit.triggered.connect(self.close)
        self.ui.actionAlwaysOnTop.triggered.connect(self.toggle_always_on_top)
        self.ui.actionSelectRegion.triggered.connect(self.select_current_region)

        # 添加文件菜单子项
        self.add_file_menu_items()

        # 注册快捷键
        self.register_shortcuts()

        # 初始化快捷键设置
        self.init_shortcut_settings()

        # 全局热键（后台待命）：手动批量截取会话期间注册 Enter 全局截图
        self.global_hotkeys = GlobalHotkeyManager(self)
        self.global_hotkeys.activated.connect(self._on_global_hotkey)
        self.global_hotkeys.install(QApplication.instance())

        # 初始化扩展名显示
        self.update_video_extension(self.ui.formatComboBox.currentText())

    def add_file_menu_items(self):
        # 清空现有菜单
        self.ui.menu_File.clear()

        # 添加打开设置目录
        open_settings_action = QAction("打开设置目录", self)
        open_settings_action.triggered.connect(self.open_settings_directory)
        self.ui.menu_File.addAction(open_settings_action)

        # 添加打开输出默认目录
        open_output_action = QAction("打开输出默认目录", self)
        open_output_action.triggered.connect(self.open_output_directory)
        self.ui.menu_File.addAction(open_output_action)

        # 添加分隔线
        self.ui.menu_File.addSeparator()

        # 添加退出
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        self.ui.menu_File.addAction(exit_action)

    def _create_ocr_asr_output_option(self):
        """选项菜单加「OCR/ASR 输出到独立文件夹」：批量生成 md 时是否汇总到源文件夹下指定目录。

        QWidgetAction 把「勾选框 + 目录名输入框」塞进菜单，不改 ui_form.py。
        勾选：OCR 页/ASR 页批量处理时，所有 md 生成到 <源文件夹>/<目录名>（默认「输出」）；
        不勾选：每个 md 散在源文件旁边（默认行为）。
        """
        w = QWidget(self)
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 2, 12, 2)
        h.setSpacing(6)
        self.ocrAsrOutCheck = QCheckBox("OCR/ASR 输出到独立文件夹", w)
        self.ocrAsrOutCheck.setChecked(False)
        self.ocrAsrOutCheck.setToolTip(
            "勾选后：OCR/ASR 批量生成 md 时，所有文档汇总输出到源文件夹下指定目录（默认「输出」）。\n"
            "不勾选：每个 md 生成在源文件旁边（默认行为）。")
        h.addWidget(self.ocrAsrOutCheck)
        h.addWidget(QLabel("目录名:", w))
        self.ocrAsrOutDirEdit = QLineEdit(w)
        self.ocrAsrOutDirEdit.setText("输出")
        self.ocrAsrOutDirEdit.setMaximumWidth(120)
        h.addWidget(self.ocrAsrOutDirEdit)
        h.addStretch(1)
        act = QWidgetAction(self)
        act.setDefaultWidget(w)
        self.ui.menu_Options.addAction(act)
        self.ocrAsrOutCheck.toggled.connect(self.save_settings)
        self.ocrAsrOutDirEdit.editingFinished.connect(self.save_settings)

    def _ocr_asr_out_dir(self, src_folder: str) -> str:
        """勾选「输出到独立文件夹」时返回目标目录路径（并创建）；否则返回空串（散在源文件旁）。"""
        if not hasattr(self, 'ocrAsrOutCheck') or not self.ocrAsrOutCheck.isChecked():
            return ""
        name = (self.ocrAsrOutDirEdit.text() or "").strip() or "输出"
        out_dir = os.path.join(src_folder, name)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError:
            return ""
        return out_dir

    def _create_ocr_tab_settings(self, parent_layout):
        """在「OCR 识别」页内创建 OCR 设置区：开关 / 并发数 / 模型路径。

        2026-09-07：从选项菜单搬入页面内部（与 ASR 识别页保持一致的交互位置），
        纯代码构建不改 ui_form.py。控件名不变（ocrConcurrencySpin/ocrModelDirEdit），
        散图/PDF 导出与文件夹 OCR 的引用代码无需改动。
        """
        box = QGroupBox("OCR 设置")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(8, 8, 8, 8)
        bv.setSpacing(6)

        # ① OCR 开关：与 ui.actionOcrEnabled 双向同步（散图/PDF 导出逻辑仍读 action）
        self.ocrEnabledCheck = QCheckBox("OCR 文字识别（勾选后，输出截图/PDF 时自动识别文字并附带说明）")
        self.ocrEnabledCheck.setChecked(self.ui.actionOcrEnabled.isChecked())
        self.ocrEnabledCheck.toggled.connect(self.ui.actionOcrEnabled.setChecked)
        self.ui.actionOcrEnabled.toggled.connect(self.ocrEnabledCheck.setChecked)
        bv.addWidget(self.ocrEnabledCheck)

        # ② OCR 并发数：多线程并行识别，加速批量 OCR。每线程独立引擎，>1 时显著提速
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("OCR 并发数:"))
        self.ocrConcurrencySpin = QSpinBox()
        self.ocrConcurrencySpin.setRange(1, 8)
        # 默认取 CPU 核数一半（上限 4）：太快会占满 CPU 造成桌面卡顿、且并行引擎内存翻倍
        default = min(4, max(1, (os.cpu_count() or 4) // 2))
        self.ocrConcurrencySpin.setValue(default)
        self.ocrConcurrencySpin.setToolTip(
            "同时运行几个 OCR 引擎（并行识别）。\n"
            "每引擎占用 1 个 CPU 核，并行数越大越快、但越占 CPU/内存。\n"
            "建议不超过 CPU 核数一半；识别大文件夹时若发现电脑卡顿请调小。")
        row1.addWidget(self.ocrConcurrencySpin)
        row1.addStretch(1)
        bv.addLayout(row1)

        # ③ OCR 模型路径：外置模型目录热加载（可选，留空自动检测 exe/源码旁 models/ocr/）
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("OCR 模型路径:"))
        self.ocrModelDirEdit = QLineEdit()
        self.ocrModelDirEdit.setPlaceholderText("留空=自动检测（exe 旁 models/ocr/），可自定义外置模型目录")
        self.ocrModelDirEdit.setToolTip(
            "外置 OCR 模型目录（需含 ch_PP-OCRv4_det/rec、cls 三个 onnx 模型）。\n"
            "留空自动检测：打包后找 exe 同级 models/ocr/；源码运行找项目根 models/ocr/。\n"
            "指定路径后换模型文件即生效（热加载），无需重新打包。")
        row2.addWidget(self.ocrModelDirEdit, 1)
        self.ocrModelBtn = QPushButton("浏览…")
        row2.addWidget(self.ocrModelBtn)
        bv.addLayout(row2)

        parent_layout.addWidget(box)

        # 信号
        self.ocrModelBtn.clicked.connect(self._choose_ocr_model_dir)
        self.ocrModelDirEdit.editingFinished.connect(self.save_settings)
        self.ocrConcurrencySpin.valueChanged.connect(self.save_settings)
        self.ocrEnabledCheck.toggled.connect(self.save_settings)

    def _ocr_model_dir(self):
        """当前设置的 OCR 外置模型路径（可空，空=自动检测）"""
        return (self.ocrModelDirEdit.text() or "").strip() if hasattr(self, 'ocrModelDirEdit') else ""

    def _check_ocr_model(self):
        """OCR 模型可用性检查：显式指定路径缺失/不完整时弹窗提示。

        返回 True=可用（继续）；False=不可用（调用方应中止 OCR 相关动作）。
        只做文件存在性检查（轻量），不加载引擎。
        """
        model_dir = self._ocr_model_dir()
        if model_dir:
            from ocr import models_complete
            if not models_complete(model_dir):
                QMessageBox.warning(
                    self, "OCR 模型路径无效",
                    f"指定路径不包含完整 OCR 模型：\n{model_dir}\n\n"
                    "需要以下 3 个文件：\n"
                    "· ch_PP-OCRv4_det_infer.onnx\n"
                    "· ch_PP-OCRv4_rec_infer.onnx\n"
                    "· ch_ppocr_mobile_v2.0_cls_infer.onnx\n\n"
                    "请重新选择正确的模型目录，或清空该选项使用自动检测。")
                return False
        return True

    def _choose_ocr_model_dir(self):
        """选择外置 OCR 模型目录（含 3 个 onnx 模型）"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择 OCR 模型目录（含 3 个 onnx 模型）",
            self.ocrModelDirEdit.text() or os.path.dirname(os.path.abspath(__file__)))
        if folder:
            self.ocrModelDirEdit.setText(folder)
            self.save_settings()

    def _create_ocr_concurrency_option(self):
        """选项菜单加「OCR 并发数」：多线程并行识别，加速批量 OCR。

        用 QWidgetAction 把「标签 + 数字框」塞进菜单，不改 ui_form.py。
        并发数全局生效：散图说明.md / PDF 文字层 / 文件夹 OCR 三处共用。
        """
        w = QWidget(self)
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 2, 12, 2)
        h.setSpacing(6)
        h.addWidget(QLabel("OCR 并发数:"))
        self.ocrConcurrencySpin = QSpinBox(w)
        self.ocrConcurrencySpin.setRange(1, 8)
        # 默认取 CPU 核数一半（上限 4）：太快会占满 CPU 造成桌面卡顿、且并行引擎内存翻倍
        default = min(4, max(1, (os.cpu_count() or 4) // 2))
        self.ocrConcurrencySpin.setValue(default)
        self.ocrConcurrencySpin.setToolTip(
            "同时运行几个 OCR 引擎（并行识别）。\n"
            "每引擎占用 1 个 CPU 核，并行数越大越快、但越占 CPU/内存。\n"
            "建议不超过 CPU 核数一半；识别大文件夹时若发现电脑卡顿请调小。")
        h.addWidget(self.ocrConcurrencySpin)
        h.addStretch(1)
        act = QWidgetAction(self)
        act.setDefaultWidget(w)
        self.ui.menu_Options.addAction(act)
        self.ocrConcurrencySpin.valueChanged.connect(self.save_settings)

    def _create_folder_ocr_tab(self):
        """动态创建「OCR 识别」Tab（第 4 页）：选择文件夹 -> 批量识别图片/PDF -> 每文件一个说明.md。

        用纯代码构建而非改 ui_form.py（自动生成文件，避免被 .ui 重新生成覆盖）。
        """
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        # 文件夹选择行
        row = QHBoxLayout()
        self.ocrFolderEdit = QLineEdit()
        self.ocrFolderEdit.setPlaceholderText("选择要识别的文件夹（内含图片或 PDF）")
        row.addWidget(self.ocrFolderEdit, 1)
        self.ocrBrowseBtn = QPushButton("选择文件夹")
        self.ocrBrowseBtn.clicked.connect(self._choose_ocr_folder)
        row.addWidget(self.ocrBrowseBtn)
        v.addLayout(row)

        # OCR 设置区（开关 / 并发数 / 模型路径——2026-09-07 从选项菜单搬入，与 ASR 页一致）
        self._create_ocr_tab_settings(v)

        # 选项
        opt_row = QHBoxLayout()
        self.ocrRecursiveCheck = QCheckBox("包含子文件夹")
        self.ocrRecursiveCheck.setChecked(True)
        self.ocrPdfCheck = QCheckBox("包含 PDF 文件")
        self.ocrPdfCheck.setChecked(True)
        opt_row.addWidget(self.ocrRecursiveCheck)
        opt_row.addWidget(self.ocrPdfCheck)
        opt_row.addStretch(1)
        v.addLayout(opt_row)

        # 合并选项
        self.ocrMergeCheck = QCheckBox("合并图片为一个 md 文件（PDF 仍各自生成）")
        self.ocrMergeCheck.setChecked(True)
        v.addWidget(self.ocrMergeCheck)

        # 开始按钮
        self.ocrStartBtn = QPushButton("开始识别")
        self.ocrStartBtn.clicked.connect(self.start_folder_ocr)
        v.addWidget(self.ocrStartBtn)

        # 进度
        self.ocrProgressBar = QProgressBar()
        self.ocrProgressBar.setRange(0, 1)
        self.ocrProgressBar.setValue(0)
        v.addWidget(self.ocrProgressBar)
        self.ocrStatusLabel = QLabel("状态: 就绪")
        v.addWidget(self.ocrStatusLabel)

        v.addStretch(1)
        # 使用说明
        tip = QLabel(
            "说明：\n"
            "1. 选择一个文件夹，程序会扫描其中的图片（png/jpg/jpeg/bmp/webp 等）和 PDF 文件；\n"
            "2. 勾选「合并图片为一个 md 文件」：所有图片识别结果汇总成 1 个 <文件夹名>_图片说明.md（PDF 仍各自生成）；\n"
            "3. 不勾选：每个文件单独生成对应的「<文件名>_说明.md」；\n"
            "4. 图片直接 OCR；PDF 优先提取内置文字层，扫描件（无文字）会自动逐页渲染后再识别。\n"
            "5. 识别在后台进行，可随时切到其它标签页操作，不卡界面。"
        )
        tip.setWordWrap(True)
        v.addWidget(tip)

        # 作为第 4 个 Tab 加入
        self.ui.modeTabWidget.addTab(tab, "OCR 识别")

    def _create_asr_tab(self):
        """动态创建「ASR 识别」Tab（第 5 页）：音频/视频 -> 语音转写 -> md 文本。

        当前为界面骨架：语音模型路径（自动检测 models/asr/）+ 输入源选择 + 进度占位。
        转写功能（sherpa-onnx + SenseVoice）后续接入；模型与 OCR 分目录存放（models/ocr/ vs models/asr/）。
        """
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        # 语音模型路径行
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("语音模型路径:"))
        self.asrModelDirEdit = QLineEdit()
        self.asrModelDirEdit.setPlaceholderText("留空=自动检测（exe 旁 models/asr/）")
        self.asrModelDirEdit.setToolTip(
            "sherpa-onnx 语音识别模型目录（SenseVoice 等，含 model.onnx / tokens.txt）\n"
            "与 OCR 模型分目录：OCR 用 models/ocr/，语音用 models/asr/")
        model_row.addWidget(self.asrModelDirEdit, 1)
        self.asrModelBtn = QPushButton("浏览…")
        self.asrModelBtn.clicked.connect(self._choose_asr_model_dir)
        model_row.addWidget(self.asrModelBtn)
        v.addLayout(model_row)

        # 输入源：文件夹（音频/视频）
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("识别文件夹:"))
        self.asrFolderEdit = QLineEdit()
        self.asrFolderEdit.setPlaceholderText("选择包含音频/视频文件的文件夹（wav/mp3/m4a/flac/mp4/mkv 等）")
        src_row.addWidget(self.asrFolderEdit, 1)
        self.asrBrowseBtn = QPushButton("选择文件夹")
        self.asrBrowseBtn.clicked.connect(self._choose_asr_folder)
        src_row.addWidget(self.asrBrowseBtn)
        v.addLayout(src_row)

        # ASR 设置区：并发数 / 一站式自动化 / 子文件夹 / 忽略文件（与 OCR 页设置区风格一致）
        box = QGroupBox("ASR 设置")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(8, 8, 8, 8)
        bv.setSpacing(6)

        # ① 并发数：并行转写几个音频（每路占用 1 个 CPU 核）
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("ASR 并发数:"))
        self.asrConcurrencySpin = QSpinBox()
        self.asrConcurrencySpin.setRange(1, 8)
        default = min(4, max(1, (os.cpu_count() or 4) // 2))
        self.asrConcurrencySpin.setValue(default)
        self.asrConcurrencySpin.setToolTip(
            "同时转写几个文件（并行）。\n"
            "每路占用 1 个 CPU 核，并行数越大越快、但越占 CPU/内存。\n"
            "建议不超过 CPU 核数一半。")
        row1.addWidget(self.asrConcurrencySpin)
        row1.addStretch(1)
        bv.addLayout(row1)

        # ② 视频自动语音转写：对标「OCR 文字识别」开关——勾选后录制的视频
        #    自动一站式处理：提取语音 → 转录为文字（而非"流程描述"式的选项）
        self.asrVideoAutoCheck = QCheckBox("视频自动语音转写（勾选后，录制的视频自动提取语音并转录为文字）")
        self.asrVideoAutoCheck.setChecked(True)
        self.asrVideoAutoCheck.setToolTip(
            "对标「OCR 文字识别」：勾选后，录制完成的视频会自动提取音轨并转写为文字。\n"
            "不勾选则只录制视频，不做语音转写。")
        bv.addWidget(self.asrVideoAutoCheck)

        # ③ 扫描子文件夹
        self.asrRecursiveCheck = QCheckBox("包含子文件夹")
        self.asrRecursiveCheck.setChecked(True)
        bv.addWidget(self.asrRecursiveCheck)

        # ④ 处理格式：正向白名单——只处理列出的音频/视频格式，其余文件自动跳过
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("处理格式:"))
        self.asrFormatsEdit = QLineEdit()
        self.asrFormatsEdit.setText("wav,mp3,m4a,flac,ogg,mp4,mkv,avi,mov,webm")
        self.asrFormatsEdit.setToolTip(
            "只处理列出的音频/视频格式，其余文件自动跳过（正向白名单）。\n"
            "逗号分隔，不带点。例如：wav,mp3,m4a,mp4")
        row2.addWidget(self.asrFormatsEdit, 1)
        bv.addLayout(row2)

        v.addWidget(box)

        # 开始按钮：后台转写（不阻塞界面）
        self.asrStartBtn = QPushButton("开始识别")
        self.asrStartBtn.clicked.connect(self.start_folder_asr)
        v.addWidget(self.asrStartBtn)

        # 进度
        self.asrProgressBar = QProgressBar()
        self.asrProgressBar.setRange(0, 1)
        self.asrProgressBar.setValue(0)
        v.addWidget(self.asrProgressBar)
        self.asrStatusLabel = QLabel("状态: 待命")
        v.addWidget(self.asrStatusLabel)

        v.addStretch(1)
        # 使用说明
        tip = QLabel(
            "说明：\n"
            "1. 选择一个含音频/视频的文件夹，程序将逐文件转写为文字并生成 <文件名>_语音转写.md；\n"
            "2. 语音模型默认放 models/asr/（SenseVoice，中英日韩粤），留空自动检测；\n"
            "3. 「处理格式」为白名单：只转写列出的格式，其余文件自动跳过；\n"
            "4. 模型与 OCR 分开管理：OCR 模型在 models/ocr/，互不影响；\n"
            "5. wav/flac/ogg/mp3 直接解码；m4a/视频等格式自动用内置 ffmpeg 转码后转写。"
        )
        tip.setWordWrap(True)
        v.addWidget(tip)

        # 作为第 5 个 Tab 加入
        self.ui.modeTabWidget.addTab(tab, "ASR 识别")

        # 输入框记忆持久化
        self.asrModelDirEdit.editingFinished.connect(self.save_settings)
        self.asrFolderEdit.editingFinished.connect(self.save_settings)
        self.asrFormatsEdit.editingFinished.connect(self.save_settings)
        self.asrConcurrencySpin.valueChanged.connect(self.save_settings)
        self.asrVideoAutoCheck.toggled.connect(self.save_settings)
        self.asrRecursiveCheck.toggled.connect(self.save_settings)

    def _choose_asr_model_dir(self):
        """选择外置语音模型目录（含 model.onnx / tokens.txt 等）"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择语音识别模型目录",
            self.asrModelDirEdit.text() or os.path.dirname(os.path.abspath(__file__)))
        if folder:
            self.asrModelDirEdit.setText(folder)
            self.save_settings()

    def _choose_asr_folder(self):
        """选择含音频/视频的文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择包含音频/视频的文件夹", self.asrFolderEdit.text() or self.app_data_dir)
        if folder:
            self.asrFolderEdit.setText(folder)
            self.save_settings()

    def _asr_model_dir(self):
        """当前设置的 ASR 外置模型路径（可空，空=自动检测 models/asr/）"""
        return (self.asrModelDirEdit.text() or "").strip() if hasattr(self, 'asrModelDirEdit') else ""

    def _check_asr_model(self):
        """ASR 模型可用性检查：显式指定路径缺失/不完整时弹窗提示。

        返回 True=可用（继续）；False=不可用（调用方应中止）。
        """
        model_dir = self._asr_model_dir()
        if model_dir:
            from asr import models_complete
            if not models_complete(model_dir):
                QMessageBox.warning(
                    self, "ASR 模型路径无效",
                    f"指定路径不包含完整 SenseVoice 模型：\n{model_dir}\n\n"
                    "需要以下 2 个文件：\n"
                    "· model.int8.onnx\n"
                    "· tokens.txt\n\n"
                    "请重新选择正确的模型目录，或清空该选项使用自动检测（models/asr/）。")
                return False
        return True

    def start_folder_asr(self):
        """开始批量 ASR：扫描文件夹（处理格式白名单）-> 后台逐文件转写 -> 生成语音转写.md"""
        try:
            if self._folder_asr_processing:
                return
            folder = self.asrFolderEdit.text().strip()
            if not folder or not os.path.isdir(folder):
                QMessageBox.warning(self, "警告", "请先选择有效文件夹！")
                return

            # 处理格式白名单（正向过滤）
            formats = [x.strip().lower().lstrip(".") for x in self.asrFormatsEdit.text().split(",") if x.strip()]
            if not formats:
                QMessageBox.warning(self, "警告", "请填写要处理的格式（如 wav,mp3,mp4）！")
                return

            from asr import scan_asr_files
            files = scan_asr_files(folder, formats, recursive=self.asrRecursiveCheck.isChecked())
            if not files:
                QMessageBox.information(self, "提示", "该文件夹内没有可处理的音频/视频文件。")
                return

            # ASR 模型检查：显式指定路径无效时明确提示
            if not self._check_asr_model():
                return

            # 后台转写，不阻塞界面
            self._folder_asr_processing = True
            self.asrStartBtn.setEnabled(False)
            self.asrProgressBar.setRange(0, len(files))
            self.asrProgressBar.setValue(0)
            self.asrStatusLabel.setText(f"状态: 正在转写 0/{len(files)} …")
            self._folder_asr_worker = ASRWorker(
                files,
                max_workers=self.asrConcurrencySpin.value(),
                model_dir=self._asr_model_dir(),
                out_dir=self._ocr_asr_out_dir(folder))
            self._folder_asr_worker.progress.connect(self._on_asr_progress)
            self._folder_asr_worker.finished.connect(self._on_asr_done)
            self._folder_asr_worker.failed.connect(self._on_asr_failed)
            self._folder_asr_worker.start()
        except Exception as e:
            print(f"开始 ASR 转写出错: {e}")
            QMessageBox.critical(self, "错误", f"开始 ASR 转写失败: {str(e)}")

    def _on_asr_progress(self, done, total, name):
        """ASR 转写进度更新"""
        self.asrProgressBar.setValue(done)
        self.asrStatusLabel.setText(f"状态: 正在转写 {done}/{total} — {name}")

    def _on_asr_done(self, md_count, fail_count):
        """ASR 转写完成"""
        self._folder_asr_processing = False
        self.asrStartBtn.setEnabled(True)
        self.asrStatusLabel.setText(f"状态: 完成，生成 {md_count} 份转写文档" + (f"，失败 {fail_count} 个" if fail_count else ""))
        self.show_status_message(f"ASR 转写完成！生成 {md_count} 份文档", 10000)
        if fail_count:
            QMessageBox.warning(self, "完成", f"ASR 转写完成：成功 {md_count} 份，失败 {fail_count} 个。\n详见 asr.log")

    def _on_asr_failed(self, msg):
        """ASR 转写线程异常"""
        self._folder_asr_processing = False
        self.asrStartBtn.setEnabled(True)
        self.asrStatusLabel.setText("状态: 转写出错")
        QMessageBox.critical(self, "错误", f"ASR 转写出错: {msg}")

    def _choose_ocr_folder(self):
        """选择要识别的文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择要识别的文件夹", self.ocrFolderEdit.text() or self.app_data_dir)
        if folder:
            self.ocrFolderEdit.setText(folder)
            self.save_settings()  # 记住上次选择的文件夹

    def start_folder_ocr(self):
        """开始批量 OCR：扫描文件夹 -> 后台逐文件识别 -> 每文件生成说明.md"""
        try:
            if self._folder_ocr_processing:
                return
            folder = self.ocrFolderEdit.text().strip()
            if not folder or not os.path.isdir(folder):
                QMessageBox.warning(self, "警告", "请先选择有效文件夹！")
                return

            files = scan_folder(
                folder,
                recursive=self.ocrRecursiveCheck.isChecked(),
                include_pdf=self.ocrPdfCheck.isChecked(),
            )
            if not files:
                QMessageBox.information(self, "提示", "该文件夹内没有可识别的图片或 PDF 文件。")
                return

            # OCR 模型检查：显式指定路径无效时明确提示，而不是识别出空白
            if not self._check_ocr_model():
                return

            # 后台处理，不阻塞界面
            self._folder_ocr_processing = True
            self.ocrStartBtn.setEnabled(False)
            self.ocrProgressBar.setRange(0, len(files))
            self.ocrProgressBar.setValue(0)
            self.ocrStatusLabel.setText(f"状态: 识别中… 0/{len(files)}")
            self._folder_ocr_worker = FolderOcrWorker(
                files, folder,
                merge_images=self.ocrMergeCheck.isChecked(),
                max_workers=self.ocrConcurrencySpin.value(),
                model_dir=self._ocr_model_dir(),
                out_dir=self._ocr_asr_out_dir(folder))
            self._folder_ocr_worker.progress.connect(self._on_folder_ocr_progress)
            self._folder_ocr_worker.finished.connect(self._on_folder_ocr_done)
            self._folder_ocr_worker.failed.connect(self._on_folder_ocr_failed)
            self._folder_ocr_worker.start()
            self.show_status_message(f"开始识别文件夹：{folder}（共 {len(files)} 个文件）", 10000)
        except Exception as e:
            print(f"开始文件夹 OCR 出错: {e}")
            QMessageBox.critical(self, "错误", f"开始识别失败: {str(e)}")
            self._folder_ocr_processing = False
            self.ocrStartBtn.setEnabled(True)

    def _on_folder_ocr_progress(self, cur, total, name):
        self.ocrProgressBar.setValue(cur)
        self.ocrStatusLabel.setText(f"状态: 识别中… {cur}/{total}（{name}）")
        self.show_status_message(f"正在识别 {cur}/{total}: {name}", 0)

    def _on_folder_ocr_done(self, md_count, fail_count):
        self._folder_ocr_processing = False
        self.ocrStartBtn.setEnabled(True)
        self.ocrProgressBar.setValue(self.ocrProgressBar.maximum())
        self.ocrStatusLabel.setText(f"状态: 完成（生成 {md_count} 个说明文件，失败 {fail_count} 个）")
        self.show_status_message(
            f"文件夹 OCR 完成！生成 {md_count} 个说明文件，失败 {fail_count} 个", 10000)

    def _on_folder_ocr_failed(self, msg):
        self._folder_ocr_processing = False
        self.ocrStartBtn.setEnabled(True)
        self.ocrStatusLabel.setText("状态: 识别出错")
        print(f"文件夹 OCR 出错: {msg}")

    def register_shortcuts(self):
        """注册快捷键"""
        # 快捷键已经在 update_shortcut_menu 方法中通过 QAction 设置
        # 这里不再重复注册，避免冲突
        pass

    def handle_enter_key(self):
        """处理 Enter 键按下"""
        current_tab = self.ui.modeTabWidget.currentIndex()
        if current_tab == 1:  # 散图录制
            self.capture_image()
        elif current_tab == 2:  # PDF 输出
            self.pdf_capture_image()

    def _on_global_hotkey(self, name):
        """全局热键触发回调（程序后台/失焦时由 Windows 转发进来）。"""
        if name == "capture_image":
            self.handle_enter_key()

    def _update_global_capture_hotkey(self):
        """批量截取会话进行中 → 注册全局 Enter 截图；结束 → 注销。

        只在手动批量截取期间启用全局 Enter，避免后台常驻时抢走
        其它程序的 Enter 键（如浏览器里按回车确认）。
        """
        session_active = self.batch_mode or self.pdf_batch_mode
        if session_active:
            # 必须传真实窗口句柄：Qt6 收不到 NULL 句柄的 WM_HOTKEY 线程消息，
            # 用 winId() 注册后消息走窗口过程才能被 native filter 捕获
            hwnd = int(self.winId())  # winId() 会按需创建原生窗口，句柄生命周期内稳定
            self.global_hotkeys.register(
                "capture_image", self.shortcut_settings["capture_image"], hwnd=hwnd)
        else:
            self.global_hotkeys.unregister("capture_image")

    def show_status_message(self, message, timeout=5000):
        """显示状态栏提示消息"""
        self.statusBar().showMessage(message, timeout)

    def init_shortcut_settings(self):
        """初始化快捷键设置：由 ShortcutManager 统一加载并同步到界面"""
        settings = self.settings_manager.load()
        self.shortcut_manager.load(settings)
        self.shortcut_settings = self.shortcut_manager.to_dict()
        # 更新快捷键菜单项
        self.update_shortcut_menu()

    def update_shortcut_menu(self):
        """更新快捷键菜单项"""
        # 清空现有快捷键菜单
        self.ui.menu_Shortcuts.clear()
        
        # 添加选择录制区域菜单项
        select_region_action = QAction(f"选择录制区域 ({self.shortcut_settings['select_region']})", self)
        select_region_action.triggered.connect(self.select_current_region)
        select_region_action.setShortcut(QKeySequence(self.shortcut_settings['select_region']))
        # 为菜单项添加右键菜单
        select_region_menu = QMenu(self)
        edit_select_region_action = QAction("修改快捷键", self)
        edit_select_region_action.triggered.connect(lambda: self.edit_shortcut('select_region', select_region_action))
        select_region_menu.addAction(edit_select_region_action)
        select_region_action.setMenu(select_region_menu)
        self.ui.menu_Shortcuts.addAction(select_region_action)
        
        # 添加开始录制菜单项
        start_recording_action = QAction(f"开始录制 ({self.shortcut_settings['start_recording']})", self)
        start_recording_action.triggered.connect(self.start_recording)
        start_recording_action.setShortcut(QKeySequence(self.shortcut_settings['start_recording']))
        # 为菜单项添加右键菜单
        start_recording_menu = QMenu(self)
        edit_start_recording_action = QAction("修改快捷键", self)
        edit_start_recording_action.triggered.connect(lambda: self.edit_shortcut('start_recording', start_recording_action))
        start_recording_menu.addAction(edit_start_recording_action)
        start_recording_action.setMenu(start_recording_menu)
        self.ui.menu_Shortcuts.addAction(start_recording_action)
        
        # 添加停止录制菜单项
        stop_recording_action = QAction(f"停止录制 ({self.shortcut_settings['stop_recording']})", self)
        stop_recording_action.triggered.connect(self.stop_recording)
        stop_recording_action.setShortcut(QKeySequence(self.shortcut_settings['stop_recording']))
        # 为菜单项添加右键菜单
        stop_recording_menu = QMenu(self)
        edit_stop_recording_action = QAction("修改快捷键", self)
        edit_stop_recording_action.triggered.connect(lambda: self.edit_shortcut('stop_recording', stop_recording_action))
        stop_recording_menu.addAction(edit_stop_recording_action)
        stop_recording_action.setMenu(stop_recording_menu)
        self.ui.menu_Shortcuts.addAction(stop_recording_action)
        
        # 添加截取图片菜单项
        capture_image_action = QAction(f"截取图片 ({self.shortcut_settings['capture_image']})", self)
        capture_image_action.triggered.connect(self.handle_enter_key)
        capture_image_action.setShortcut(QKeySequence(self.shortcut_settings['capture_image']))
        # 为菜单项添加右键菜单
        capture_image_menu = QMenu(self)
        edit_capture_image_action = QAction("修改快捷键", self)
        edit_capture_image_action.triggered.connect(lambda: self.edit_shortcut('capture_image', capture_image_action))
        capture_image_menu.addAction(edit_capture_image_action)
        capture_image_action.setMenu(capture_image_menu)
        self.ui.menu_Shortcuts.addAction(capture_image_action)



    def edit_shortcut(self, shortcut_key, action):
        """编辑快捷键：弹出 ShortcutEditDialog，确定后更新并保存"""
        dialog = ShortcutEditDialog(
            current_shortcut=self.shortcut_settings[shortcut_key],
            shortcut_manager=self.shortcut_manager,
            shortcut_key=shortcut_key,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.shortcut_manager.update(shortcut_key, dialog.get_shortcut())
            self.shortcut_settings = self.shortcut_manager.to_dict()
            self.save_settings()
            self.update_shortcut_menu()
            # 若批量截取会话进行中，同步更新全局热键
            self._update_global_capture_hotkey()

    def open_settings_directory(self):
        """打开设置文件目录"""
        if os.path.exists(self.app_data_dir):
            os.startfile(self.app_data_dir)
        else:
            QMessageBox.warning(self, "警告", "设置目录不存在！")

    def open_output_directory(self):
        """打开输出默认目录"""
        if os.path.exists(self.output_dir):
            os.startfile(self.output_dir)
        else:
            QMessageBox.warning(self, "警告", "输出目录不存在！")

    def toggle_always_on_top(self):
        """切换保持置顶"""
        if self.ui.actionAlwaysOnTop.isChecked():
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        else:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        self.show()

    def select_current_region(self):
        """根据当前标签页选择对应的区域"""
        current_tab = self.ui.modeTabWidget.currentIndex()
        if current_tab == 0:  # 视频录制
            self.select_region()
        elif current_tab == 1:  # 散图录制
            self.select_image_region()
        elif current_tab == 2:  # PDF 输出
            self.select_pdf_region()

    def select_region(self):
        """选择视频录制区域"""
        self.hide()

        self.selection_window = SelectionWindow()
        self.selection_window.selection_completed.connect(self.on_region_selection_completed)
        self.selection_window.selection_canceled.connect(self.on_region_selection_canceled)
        self.selection_window.show()

    def on_region_selection_completed(self, region):
        """视频区域选择完成回调"""
        x, y, width, height = region
        self.selected_region = (x, y, width, height)
        self.ui.regionLabel.setText(f"当前区域: ({x}, {y}) {width}x{height}")
        self.show()

    def on_region_selection_canceled(self):
        """视频区域选择取消回调"""
        self.show()
        if not self.selected_region:
            self.ui.regionLabel.setText("当前区域: 未选择")

    def select_image_region(self):
        """选择散图录制区域"""
        self.hide()

        self.selection_window = SelectionWindow()
        self.selection_window.selection_completed.connect(self.on_image_region_selection_completed)
        self.selection_window.selection_canceled.connect(self.on_image_region_selection_canceled)
        self.selection_window.show()

    def on_image_region_selection_completed(self, region):
        """散图区域选择完成回调"""
        x, y, width, height = region
        self.image_selected_region = (x, y, width, height)
        self.ui.imageRegionLabel.setText(f"当前区域: ({x}, {y}) {width}x{height}")
        self.show()

    def on_image_region_selection_canceled(self):
        """散图区域选择取消回调"""
        self.show()
        if not self.image_selected_region:
            self.ui.imageRegionLabel.setText("当前区域: 未选择")

    def select_pdf_region(self):
        """选择 PDF 输出区域"""
        self.hide()

        self.selection_window = SelectionWindow()
        self.selection_window.selection_completed.connect(self.on_pdf_region_selection_completed)
        self.selection_window.selection_canceled.connect(self.on_pdf_region_selection_canceled)
        self.selection_window.show()

    def on_pdf_region_selection_completed(self, region):
        """PDF 区域选择完成回调"""
        x, y, width, height = region
        self.pdf_selected_region = (x, y, width, height)
        self.ui.pdfRegionLabel.setText(f"当前区域: ({x}, {y}) {width}x{height}")
        self.show()

    def on_pdf_region_selection_canceled(self):
        """PDF 区域选择取消回调"""
        self.show()
        if not self.pdf_selected_region:
            self.ui.pdfRegionLabel.setText("当前区域: 未选择")

    def update_video_extension(self, format):
        """更新视频文件扩展名"""
        self.ui.extensionLabel.setText(f".{format}")

    def get_video_output_path(self):
        """获取视频输出路径"""
        path = self.ui.outputPathLineEdit.text()
        if not os.path.isabs(path):
            path = os.path.join(self.app_data_dir, path)
        os.makedirs(path, exist_ok=True)
        filename = self.ui.outputFileNameLineEdit.text()
        format = self.ui.formatComboBox.currentText()
        return os.path.join(path, f"{filename}.{format}")

    def get_image_output_path(self):
        """获取图片输出路径"""
        path = self.ui.imagePathLineEdit.text()
        if not os.path.isabs(path):
            path = os.path.join(self.app_data_dir, path)
        os.makedirs(path, exist_ok=True)
        return path

    def get_pdf_output_path(self):
        """获取 PDF 输出路径"""
        path = self.ui.pdfPathLineEdit.text()
        if not os.path.isabs(path):
            path = os.path.join(self.app_data_dir, path)
        os.makedirs(path, exist_ok=True)
        filename = self.ui.pdfFileNameLineEdit.text()
        return os.path.join(path, f"{filename}.pdf")

    def start_recording(self):
        try:
            current_tab = self.ui.modeTabWidget.currentIndex()
            if current_tab == 0:  # 视频录制
                if not self.selected_region:
                    QMessageBox.warning(self, "警告", "请先选择录制区域！")
                    return

                output_file = self.get_video_output_path()
                fps = self.ui.fpsSpinBox.value()

                # 验证输出路径
                output_dir = os.path.dirname(output_file)
                if not os.access(os.path.dirname(output_dir), os.W_OK):
                    QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                    return

                # 创建 ScreenRecorder 实例
                self.screen_recorder = ScreenRecorder(self.selected_region, output_file, fps)
                self.screen_recorder.finished.connect(self.on_recording_finished)

                self.is_recording = True
                self.recording_start_time = datetime.now()

                # 更新 UI 状态
                self.ui.startBtn.setEnabled(False)
                self.ui.stopBtn.setEnabled(True)
                self.ui.selectRegionBtn.setEnabled(False)
                self.ui.statusLabel.setText("状态: 录制中...")
                self.ui.durationLabel.setText("已录制: 00:00:00")

                # 启动定时器，每秒更新一次录制时长
                self.recording_timer.start(1000)

                # 开始录制
                self.screen_recorder.start()

                self.show_status_message(f"开始录制！输出文件: {output_file}", 10000)
            elif current_tab == 1:  # 散图录制
                self.start_image_recording()
            elif current_tab == 2:  # PDF 输出
                self.start_pdf_recording()
        except Exception as e:
            print(f"开始录制出错: {e}")
            QMessageBox.critical(self, "错误", f"开始录制失败: {str(e)}")
            # 恢复 UI 状态
            current_tab = self.ui.modeTabWidget.currentIndex()
            if current_tab == 0:
                self.ui.startBtn.setEnabled(True)
                self.ui.stopBtn.setEnabled(False)
                self.ui.selectRegionBtn.setEnabled(True)
                self.ui.statusLabel.setText("状态: 就绪")
            elif current_tab == 1:
                self.ui.autoStartBtn.setEnabled(True)
                self.ui.autoStopBtn.setEnabled(False)
                self.ui.imageStatusLabel.setText("状态: 就绪")
            elif current_tab == 2:
                self.ui.pdfAutoStartBtn.setEnabled(True)
                self.ui.pdfAutoStopBtn.setEnabled(False)
                self.ui.pdfStatusLabel.setText("状态: 就绪")

    def stop_recording(self):
        try:
            current_tab = self.ui.modeTabWidget.currentIndex()
            if current_tab == 0:  # 视频录制
                if not self.is_recording:
                    return

                # 停止录制
                if self.screen_recorder:
                    self.screen_recorder.stop()

                self.is_recording = False
                self.recording_start_time = None

                # 停止定时器
                self.recording_timer.stop()

                # 更新 UI 状态
                self.ui.startBtn.setEnabled(True)
                self.ui.stopBtn.setEnabled(False)
                self.ui.selectRegionBtn.setEnabled(True)
                self.ui.statusLabel.setText("状态: 已停止")
            elif current_tab == 1:  # 散图录制
                self.stop_image_recording()
            elif current_tab == 2:  # PDF 输出
                self.stop_pdf_recording()
        except Exception as e:
            print(f"停止录制出错: {e}")
            QMessageBox.critical(self, "错误", f"停止录制失败: {str(e)}")
            # 恢复 UI 状态
            current_tab = self.ui.modeTabWidget.currentIndex()
            if current_tab == 0:
                self.is_recording = False
                if hasattr(self, 'recording_timer') and self.recording_timer:
                    self.recording_timer.stop()
                self.ui.startBtn.setEnabled(True)
                self.ui.stopBtn.setEnabled(False)
                self.ui.selectRegionBtn.setEnabled(True)
                self.ui.statusLabel.setText("状态: 已停止")
            elif current_tab == 1:
                self.is_image_recording = False
                if hasattr(self, 'image_timer') and self.image_timer:
                    self.image_timer.stop()
                self.ui.autoStartBtn.setEnabled(True)
                self.ui.autoStopBtn.setEnabled(False)
                self.ui.imageStatusLabel.setText("状态: 已停止")
            elif current_tab == 2:
                self.is_pdf_recording = False
                if hasattr(self, 'pdf_timer') and self.pdf_timer:
                    self.pdf_timer.stop()
                self.ui.pdfAutoStartBtn.setEnabled(True)
                self.ui.pdfAutoStopBtn.setEnabled(False)
                self.ui.pdfStatusLabel.setText("状态: 已停止")

    def on_recording_finished(self):
        """录制完成回调"""
        try:
            output_file = self.get_video_output_path()
            if os.path.exists(output_file):
                self.show_status_message(f"录制已停止！保存到: {output_file}", 10000)
            else:
                self.show_status_message(f"录制已停止，但文件可能未保存成功！预期路径: {output_file}", 10000)
        except Exception as e:
            print(f"录制完成回调出错: {e}")
            QMessageBox.critical(self, "错误", f"处理录制完成事件时出错: {str(e)}")

    def capture_image(self):
        """手动截取图片"""
        try:
            if not self.image_selected_region:
                QMessageBox.warning(self, "警告", "请先选择截图区域！")
                return

            # 获取输出路径
            base_path = self.get_image_output_path()
            
            # 验证输出路径
            if not os.access(os.path.dirname(base_path), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 获取图片格式
            image_format = self.ui.imageFormatComboBox.currentText()

            # 如果处于批量模式，使用批量文件夹
            if self.batch_mode and self.batch_folder:
                output_folder = self.batch_folder
                # 创建 ImageCapture 实例
                image_capture = ImageCapture(self.image_selected_region, output_folder, image_format)
                image_capture.captured.connect(self.on_image_captured)
                
                # 捕获图片
                self.image_capture_count += 1
                output_file = image_capture.capture(self.image_capture_count)

                if output_file:
                    # 更新状态
                    self.ui.imageStatusLabel.setText(f"状态: 批量模式已截取 {self.image_capture_count} 张图片")
                else:
                    # 截图失败
                    self.image_capture_count -= 1
                    self.ui.imageStatusLabel.setText("状态: 截图失败")
                    QMessageBox.warning(self, "警告", "截图失败，请检查权限或空间！")
            else:
                # 单次截图模式
                # 创建时间戳文件夹
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                folder_name = self.ui.imageFileNameLineEdit.text()
                output_folder = os.path.join(base_path, f"{folder_name}_{timestamp}")
                os.makedirs(output_folder, exist_ok=True)
                
                # 创建 ImageCapture 实例
                image_capture = ImageCapture(self.image_selected_region, output_folder, image_format)
                image_capture.captured.connect(self.on_image_captured)

                # 捕获图片
                self.image_capture_count += 1
                output_file = image_capture.capture(self.image_capture_count)

                if output_file:
                    # 更新状态
                    self.ui.imageStatusLabel.setText(f"状态: 已截取 {self.image_capture_count} 张图片")
                else:
                    # 截图失败，重置计数器
                    self.image_capture_count -= 1
                    self.ui.imageStatusLabel.setText("状态: 截图失败")
                    QMessageBox.warning(self, "警告", "截图失败，请检查权限或空间！")
        except Exception as e:
            print(f"截图过程出错: {e}")
            QMessageBox.critical(self, "错误", f"截图失败: {str(e)}")
            # 重置计数器
            if self.batch_mode and self.batch_folder:
                # 批量模式下不重置计数器
                pass
            elif self.image_capture_count > 0:
                self.image_capture_count -= 1
            self.ui.imageStatusLabel.setText("状态: 截图失败")

    def on_image_captured(self, output_file):
        """图片捕获完成回调"""
        try:
            if output_file and os.path.exists(output_file):
                # 记录本次会话截取的图片（用于生成说明.md）
                if self.batch_mode:
                    self.image_captured_files.append(output_file)
                self.show_status_message(f"已截取图片！保存到: {output_file}", 10000)
            else:
                self.show_status_message("图片可能未保存成功！", 10000)
        except Exception as e:
            print(f"图片捕获回调出错: {e}")
            QMessageBox.critical(self, "错误", f"处理图片捕获事件时出错: {str(e)}")

    def start_batch_capture(self):
        """开始批量截图"""
        try:
            if not self.image_selected_region:
                QMessageBox.warning(self, "警告", "请先选择截图区域！")
                return

            # 获取输出路径
            base_path = self.get_image_output_path()
            
            # 验证输出路径
            if not os.access(os.path.dirname(base_path), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 创建时间戳文件夹
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_name = self.ui.imageFileNameLineEdit.text()
            self.batch_folder = os.path.join(base_path, f"{folder_name}_{timestamp}")
            os.makedirs(self.batch_folder, exist_ok=True)

            # 重置计数器
            self.image_capture_count = 0
            self.image_captured_files = []
            self.batch_mode = True
            self._update_global_capture_hotkey()  # 注册全局 Enter 截图

            # 更新 UI 状态
            self.ui.manualStartBtn.setEnabled(False)
            self.ui.manualStopBtn.setEnabled(True)
            self.ui.imageStatusLabel.setText("状态: 批量模式已开始，请截取图片")
        except Exception as e:
            print(f"开始批量截图失败: {e}")
            QMessageBox.critical(self, "错误", f"开始批量截图失败: {str(e)}")

    def stop_batch_capture(self):
        """停止批量截图"""
        try:
            if not self.batch_mode:
                return

            # 保存截图数量
            capture_count = self.image_capture_count

            # 重置状态
            self.batch_mode = False
            batch_folder = self.batch_folder
            self.batch_folder = None
            self._update_global_capture_hotkey()  # 注销全局 Enter 截图

            # 更新 UI 状态
            self.ui.manualStartBtn.setEnabled(True)
            self.ui.manualStopBtn.setEnabled(False)

            # 显示结果
            if capture_count > 0:
                self.ui.imageStatusLabel.setText(f"状态: 批量截图已完成，共截取 {capture_count} 张图片")
                self.show_status_message(f"批量截图已完成！共截取 {capture_count} 张图片。保存到: {batch_folder}", 10000)

                # AI 友好：后台 OCR 识别 + 生成配套说明.md（不阻塞界面）
                files = list(self.image_captured_files)
                self.image_captured_files = []
                if files and not self._sidecar_processing:
                    if self.ui.actionOcrEnabled.isChecked() and not self._check_ocr_model():
                        # OCR 开关打开但模型不可用：跳过识别，仅提示
                        self.show_status_message("OCR 模型不可用，本次截图未生成说明文件", 8000)
                    elif self.ui.actionOcrEnabled.isChecked():
                        self._sidecar_processing = True
                        self._sidecar_worker = SidecarWorker(
                            files, batch_folder,
                            max_workers=self.ocrConcurrencySpin.value(),
                            model_dir=self._ocr_model_dir())
                        self._sidecar_worker.progress.connect(self._on_sidecar_progress)
                        self._sidecar_worker.finished.connect(self._on_sidecar_done)
                        self._sidecar_worker.failed.connect(self._on_sidecar_failed)
                        self.show_status_message(f"正在识别截图文字（OCR）… 0/{len(files)}", 0)
                        self._sidecar_worker.start()
                    # OCR 关闭：跳过识别，直接提示完成（不生成说明.md）
                    else:
                        self.show_status_message(
                            f"批量截图已完成！共截取 {capture_count} 张图片。保存到: {batch_folder}", 10000)
            else:
                self.ui.imageStatusLabel.setText("状态: 批量截图已取消")
                self.show_status_message("批量截图已取消，未截取任何图片", 10000)
                # 删除空文件夹
                if os.path.exists(batch_folder):
                    try:
                        os.rmdir(batch_folder)
                        print(f"已删除空文件夹: {batch_folder}")
                    except:
                        pass
        except Exception as e:
            print(f"停止批量截图失败: {e}")
            QMessageBox.critical(self, "错误", f"停止批量截图失败: {str(e)}")
            # 确保状态被重置
            self.batch_mode = False
            self.batch_folder = None
            self._update_global_capture_hotkey()  # 注销全局 Enter 截图
            self.ui.manualStartBtn.setEnabled(True)
            self.ui.manualStopBtn.setEnabled(False)

    def start_image_recording(self):
        """开始自动截图录制"""
        try:
            if not self.image_selected_region:
                QMessageBox.warning(self, "警告", "请先选择截图区域！")
                return

            # 获取输出路径
            base_path = self.get_image_output_path()
            
            # 验证输出路径
            if not os.access(os.path.dirname(base_path), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 创建时间戳文件夹
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_name = self.ui.imageFileNameLineEdit.text()
            self.image_output_folder = os.path.join(base_path, f"{folder_name}_{timestamp}")
            os.makedirs(self.image_output_folder, exist_ok=True)

            # 重置计数器
            self.image_capture_count = 0

            # 获取图片格式
            image_format = self.ui.imageFormatComboBox.currentText()
            
            # 创建 ImageCapture 实例
            self.image_capture = ImageCapture(self.image_selected_region, self.image_output_folder, image_format)
            self.image_capture.captured.connect(self.on_image_captured)

            # 获取时间间隔（秒）
            interval_seconds = max(0.1, self.ui.frameIntervalSpinBox.value())  # 确保时间间隔至少为0.1秒
            interval = interval_seconds * 1000  # 转换为毫秒

            # 更新 UI 状态
            self.is_image_recording = True
            self.ui.autoStartBtn.setEnabled(False)
            self.ui.autoStopBtn.setEnabled(True)
            self.ui.imageStatusLabel.setText("状态: 自动录制中...")

            # 启动定时器
            self.image_timer = QTimer()
            self.image_timer.timeout.connect(self.auto_capture_image)
            self.image_timer.start(int(interval))

            self.show_status_message(f"开始自动截图录制！保存到: {self.image_output_folder}", 10000)
        except Exception as e:
            print(f"开始自动截图录制出错: {e}")
            QMessageBox.critical(self, "错误", f"开始自动截图录制失败: {str(e)}")
            # 恢复 UI 状态
            self.ui.autoStartBtn.setEnabled(True)
            self.ui.autoStopBtn.setEnabled(False)
            self.ui.imageStatusLabel.setText("状态: 就绪")

    def auto_capture_image(self):
        """自动截取图片"""
        try:
            if not self.is_image_recording:
                return

            # 捕获图片
            self.image_capture_count += 1
            output_file = self.image_capture.capture(self.image_capture_count)

            if output_file:
                # 更新状态
                self.ui.imageStatusLabel.setText(f"状态: 已截取 {self.image_capture_count} 张图片")
            else:
                # 截图失败，重置计数器
                self.image_capture_count -= 1
                self.ui.imageStatusLabel.setText(f"状态: 已截取 {self.image_capture_count} 张图片 (部分失败)")
        except Exception as e:
            print(f"自动截图出错: {e}")
            # 重置计数器
            if self.image_capture_count > 0:
                self.image_capture_count -= 1
            self.ui.imageStatusLabel.setText(f"状态: 已截取 {self.image_capture_count} 张图片 (错误)")

    def stop_image_recording(self):
        """停止自动截图录制"""
        try:
            if not self.is_image_recording:
                return

            # 停止定时器
            self.image_timer.stop()

            # 更新 UI 状态
            self.is_image_recording = False
            self.ui.autoStartBtn.setEnabled(True)
            self.ui.autoStopBtn.setEnabled(False)
            self.ui.imageStatusLabel.setText(f"状态: 已停止，共截取 {self.image_capture_count} 张图片")

            self.show_status_message(f"自动截图录制已停止！共截取 {self.image_capture_count} 张图片", 10000)
        except Exception as e:
            print(f"停止自动截图录制出错: {e}")
            QMessageBox.critical(self, "错误", f"停止自动截图录制失败: {str(e)}")
            # 恢复 UI 状态
            self.is_image_recording = False
            if hasattr(self, 'image_timer') and self.image_timer:
                self.image_timer.stop()
            self.ui.autoStartBtn.setEnabled(True)
            self.ui.autoStopBtn.setEnabled(False)
            self.ui.imageStatusLabel.setText(f"状态: 已停止，共截取 {self.image_capture_count} 张图片")

    def pdf_capture_image(self):
        """PDF 手动截取图片"""
        try:
            if not self.pdf_selected_region:
                QMessageBox.warning(self, "警告", "请先选择 PDF 区域！")
                return

            # 验证输出路径
            output_file = self.get_pdf_output_path()
            output_dir = os.path.dirname(output_file)
            if not os.access(os.path.dirname(output_dir), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 如果处于批量模式
            if self.pdf_batch_mode and hasattr(self, 'pdf_exporter'):
                # 捕获图片
                self.pdf_capture_count += 1
                temp_file = self.pdf_exporter.capture(self.pdf_capture_count)

                if temp_file:
                    # 更新状态
                    self.ui.pdfStatusLabel.setText(f"状态: 批量模式已截取 {self.pdf_capture_count} 张图片")
                else:
                    # 截图失败
                    self.pdf_capture_count -= 1
                    self.ui.pdfStatusLabel.setText("状态: 截图失败")
                    QMessageBox.warning(self, "警告", "截图失败，请检查权限或空间！")
            else:
                # 单次截图模式
                if self._pdf_exporting:
                    self.show_status_message("正在导出 PDF，请稍候…", 5000)
                    return
                # 创建时间戳文件夹（中间文件）
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                temp_folder = os.path.join(self.output_dir, f"temp_{timestamp}")
                os.makedirs(temp_folder, exist_ok=True)

                # 创建 PDFExporter 实例
                self.pdf_exporter = PDFExporter(self.pdf_selected_region, output_file, temp_folder)
                self.pdf_exporter.exported.connect(self.on_pdf_exported)

                # 重置计数器
                self.pdf_capture_count = 0

                # 捕获图片
                self.pdf_capture_count += 1
                temp_file = self.pdf_exporter.capture(self.pdf_capture_count)

                if not temp_file:
                    QMessageBox.warning(self, "警告", "截图失败，请检查权限或空间！")
                    self.ui.pdfStatusLabel.setText("状态: 截图失败")
                    return

                # 更新状态
                self.ui.pdfStatusLabel.setText("状态: 处理中...")

                # 后台生成 PDF（含 OCR，不阻塞界面）
                self._start_pdf_export(self.pdf_exporter)
        except Exception as e:
            print(f"PDF 截取过程出错: {e}")
            QMessageBox.critical(self, "错误", f"PDF 截取失败: {str(e)}")
            self.ui.pdfStatusLabel.setText("状态: PDF 截取失败")

    def on_pdf_exported(self, output_file):
        """PDF 导出完成回调"""
        try:
            if output_file and os.path.exists(output_file):
                self.show_status_message(f"PDF 生成完成！保存到: {output_file}", 10000)
                self.ui.pdfStatusLabel.setText("状态: 已完成")
            else:
                QMessageBox.warning(self, "警告", "PDF 可能未生成成功！")
                self.ui.pdfStatusLabel.setText("状态: 生成失败")
        except Exception as e:
            print(f"PDF 导出回调出错: {e}")
            QMessageBox.critical(self, "错误", f"处理 PDF 导出事件时出错: {str(e)}")
            self.ui.pdfStatusLabel.setText("状态: 生成失败")

    # ---------- 后台导出（多线程，避免阻塞界面） ----------
    def _start_pdf_export(self, exporter):
        """后台启动 PDF 导出（OCR 按开关可选），带状态锁与进度回传。"""
        if self._pdf_exporting:
            self.show_status_message("正在导出 PDF，请稍候…", 5000)
            return
        ocr_enabled = self.ui.actionOcrEnabled.isChecked()
        if ocr_enabled and not self._check_ocr_model():
            self.show_status_message("OCR 模型不可用，本次导出不包含文字层", 8000)
            ocr_enabled = False
        self._pdf_exporting = True
        self._pdf_export_worker = PDFExportWorker(
            exporter, ocr_enabled=ocr_enabled,
            max_workers=self.ocrConcurrencySpin.value(),
            model_dir=self._ocr_model_dir())
        self._pdf_export_worker.progress.connect(self._on_pdf_progress)
        self._pdf_export_worker.finished.connect(self._on_pdf_export_done)
        self._pdf_export_worker.failed.connect(self._on_pdf_failed)
        label = "正在导出 PDF（含 OCR）…" if ocr_enabled else "正在导出 PDF…"
        self.ui.pdfStatusLabel.setText(f"状态: {label}")
        self.show_status_message("正在导出 PDF… 0 页", 0)
        self._pdf_export_worker.start()

    def _on_pdf_progress(self, cur, total):
        self.ui.pdfStatusLabel.setText(f"状态: 正在导出 PDF… 第 {cur}/{total} 页")
        self.show_status_message(f"正在导出 PDF… 第 {cur}/{total} 页", 0)

    def _on_pdf_export_done(self, pdf_path, ok):
        self._pdf_exporting = False
        if ok and pdf_path and os.path.exists(pdf_path):
            self.ui.pdfStatusLabel.setText("状态: 已完成")
            self.show_status_message(f"PDF 生成完成！保存到: {pdf_path}", 10000)
        else:
            self.ui.pdfStatusLabel.setText("状态: PDF 生成失败")
            self.show_status_message("PDF 生成失败，请检查权限或空间！", 10000)
        # 恢复按钮（批量结束/自动录制结束导出的场景由 stop 方法禁用过）
        self.ui.pdfManualStartBtn.setEnabled(True)
        self.ui.pdfManualStopBtn.setEnabled(False)
        self.ui.pdfAutoStartBtn.setEnabled(True)
        self.ui.pdfAutoStopBtn.setEnabled(False)

    def _on_pdf_failed(self, msg):
        print(f"PDF 导出失败: {msg}")

    def _on_sidecar_progress(self, cur, total):
        self.show_status_message(f"正在识别截图文字（OCR）… {cur}/{total}", 0)

    def _on_sidecar_done(self, md_path, ok):
        self._sidecar_processing = False
        if ok and md_path:
            self.show_status_message(f"已生成 AI 配套说明: {md_path}", 10000)
        else:
            self.show_status_message("生成说明.md 失败（OCR 可能不可用）", 10000)

    def _on_sidecar_failed(self, msg):
        self._sidecar_processing = False
        print(f"生成说明.md 失败: {msg}")

    def start_pdf_recording(self):
        """开始 PDF 自动录制"""
        try:
            if not self.pdf_selected_region:
                QMessageBox.warning(self, "警告", "请先选择 PDF 区域！")
                return

            # 验证输出路径
            output_file = self.get_pdf_output_path()
            output_dir = os.path.dirname(output_file)
            if not os.access(os.path.dirname(output_dir), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 创建时间戳文件夹（中间文件）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.pdf_temp_folder = os.path.join(self.output_dir, f"temp_{timestamp}")
            os.makedirs(self.pdf_temp_folder, exist_ok=True)

            # 创建 PDFExporter 实例
            self.pdf_exporter = PDFExporter(self.pdf_selected_region, output_file, self.pdf_temp_folder)
            self.pdf_exporter.exported.connect(self.on_pdf_exported)

            # 重置计数器
            self.pdf_capture_count = 0

            # 获取时间间隔（秒）
            interval_seconds = max(0.1, self.ui.pdfFrameIntervalSpinBox.value())  # 确保时间间隔至少为0.1秒
            interval = interval_seconds * 1000  # 转换为毫秒

            # 更新 UI 状态
            self.is_pdf_recording = True
            self.ui.pdfAutoStartBtn.setEnabled(False)
            self.ui.pdfAutoStopBtn.setEnabled(True)
            self.ui.pdfStatusLabel.setText("状态: 自动录制中...")

            # 启动定时器
            self.pdf_timer = QTimer()
            self.pdf_timer.timeout.connect(self.auto_pdf_capture)
            self.pdf_timer.start(int(interval))

            self.show_status_message(f"开始 PDF 自动录制！保存到: {output_file}", 10000)
        except Exception as e:
            print(f"开始 PDF 自动录制出错: {e}")
            QMessageBox.critical(self, "错误", f"开始 PDF 自动录制失败: {str(e)}")
            # 恢复 UI 状态
            self.ui.pdfAutoStartBtn.setEnabled(True)
            self.ui.pdfAutoStopBtn.setEnabled(False)
            self.ui.pdfStatusLabel.setText("状态: 就绪")

    def auto_pdf_capture(self):
        """自动截取 PDF 图片"""
        try:
            if not self.is_pdf_recording:
                return

            # 捕获图片
            self.pdf_capture_count += 1
            temp_file = self.pdf_exporter.capture(self.pdf_capture_count)

            if temp_file:
                # 更新状态
                self.ui.pdfStatusLabel.setText(f"状态: 自动录制中... ({self.pdf_capture_count})")
            else:
                # 截图失败，重置计数器
                self.pdf_capture_count -= 1
                self.ui.pdfStatusLabel.setText(f"状态: 自动录制中... ({self.pdf_capture_count}) (部分失败)")
        except Exception as e:
            print(f"自动 PDF 截图出错: {e}")
            # 重置计数器
            if self.pdf_capture_count > 0:
                self.pdf_capture_count -= 1
            self.ui.pdfStatusLabel.setText(f"状态: 自动录制中... ({self.pdf_capture_count}) (错误)")

    def stop_pdf_recording(self):
        """停止 PDF 自动录制并生成 PDF"""
        try:
            if not self.is_pdf_recording:
                return

            # 停止定时器
            self.pdf_timer.stop()

            # 更新状态
            self.is_pdf_recording = False
            self.ui.pdfAutoStartBtn.setEnabled(False)  # 导出中禁用
            self.ui.pdfAutoStopBtn.setEnabled(False)
            self.ui.pdfStatusLabel.setText("状态: 生成 PDF 中...")

            # 后台生成 PDF（含 OCR，不阻塞界面）
            if self.pdf_exporter:
                self._start_pdf_export(self.pdf_exporter)
        except Exception as e:
            print(f"停止 PDF 自动录制出错: {e}")
            QMessageBox.critical(self, "错误", f"停止 PDF 自动录制失败: {str(e)}")
            # 恢复 UI 状态
            self.is_pdf_recording = False
            if hasattr(self, 'pdf_timer') and self.pdf_timer:
                self.pdf_timer.stop()
            self.ui.pdfAutoStartBtn.setEnabled(True)
            self.ui.pdfAutoStopBtn.setEnabled(False)
            self.ui.pdfStatusLabel.setText("状态: 已停止")

    def start_pdf_batch_capture(self):
        """开始 PDF 批量截图"""
        try:
            if self._pdf_exporting:
                QMessageBox.information(self, "提示", "正在导出上一份 PDF，请稍候再开始！")
                return
            if not self.pdf_selected_region:
                QMessageBox.warning(self, "警告", "请先选择 PDF 区域！")
                return

            # 验证输出路径
            output_file = self.get_pdf_output_path()
            output_dir = os.path.dirname(output_file)
            if not os.access(os.path.dirname(output_dir), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 创建时间戳文件夹（中间文件）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_folder = os.path.join(self.output_dir, f"temp_{timestamp}")
            os.makedirs(temp_folder, exist_ok=True)

            # 创建 PDFExporter 实例
            self.pdf_exporter = PDFExporter(self.pdf_selected_region, output_file, temp_folder)
            self.pdf_exporter.exported.connect(self.on_pdf_exported)

            # 重置状态
            self.pdf_capture_count = 0
            self.pdf_batch_mode = True
            self._update_global_capture_hotkey()  # 注册全局 Enter 截图

            # 更新 UI 状态
            self.ui.pdfManualStartBtn.setEnabled(False)
            self.ui.pdfManualStopBtn.setEnabled(True)
            self.ui.pdfStatusLabel.setText("状态: 批量模式已开始，请截取图片")
        except Exception as e:
            print(f"开始 PDF 批量截图失败: {e}")
            QMessageBox.critical(self, "错误", f"开始 PDF 批量截图失败: {str(e)}")

    def stop_pdf_batch_capture(self):
        """停止 PDF 批量截图并生成 PDF"""
        try:
            if not self.pdf_batch_mode:
                return

            # 保存截图数量
            capture_count = self.pdf_capture_count

            # 重置状态
            self.pdf_batch_mode = False
            self._update_global_capture_hotkey()  # 注销全局 Enter 截图

            # 显示结果
            if capture_count > 0:
                self.ui.pdfStatusLabel.setText("状态: 生成 PDF 中...")

                # 后台生成 PDF（含 OCR，不阻塞界面）；导出中禁用开始/停止
                self.ui.pdfManualStartBtn.setEnabled(False)
                self.ui.pdfManualStopBtn.setEnabled(False)
                if self.pdf_exporter:
                    self._start_pdf_export(self.pdf_exporter)
            else:
                self.ui.pdfStatusLabel.setText("状态: 批量截图已取消")
                self.show_status_message("PDF 批量截图已取消，未截取任何图片", 10000)
                self.ui.pdfManualStartBtn.setEnabled(True)
                self.ui.pdfManualStopBtn.setEnabled(False)

                # 清理 PDFExporter
                if hasattr(self, 'pdf_exporter') and self.pdf_exporter:
                    self.pdf_exporter.cleanup()
        except Exception as e:
            print(f"停止 PDF 批量截图失败: {e}")
            QMessageBox.critical(self, "错误", f"停止 PDF 批量截图失败: {str(e)}")
            # 确保状态被重置
            self.pdf_batch_mode = False
            self._update_global_capture_hotkey()  # 注销全局 Enter 截图
            self.ui.pdfManualStartBtn.setEnabled(True)
            self.ui.pdfManualStopBtn.setEnabled(False)

    def update_recording_duration(self):
        """更新录制时长显示"""
        if self.is_recording and self.recording_start_time:
            elapsed = datetime.now() - self.recording_start_time
            hours = elapsed.seconds // 3600
            minutes = (elapsed.seconds % 3600) // 60
            seconds = elapsed.seconds % 60
            duration_str = f"已录制: {hours:02d}:{minutes:02d}:{seconds:02d}"
            self.ui.durationLabel.setText(duration_str)

    def browse_output_path(self):
        default_path = self.ui.outputPathLineEdit.text()
        if not os.path.isabs(default_path):
            default_path = os.path.join(self.app_data_dir, default_path)

        folder_path = QFileDialog.getExistingDirectory(
            self,
            "选择输出路径",
            default_path
        )

        if folder_path:
            # 转换为相对路径（如果在 app_data_dir 内）
            if folder_path.startswith(self.app_data_dir):
                relative_path = os.path.relpath(folder_path, self.app_data_dir)
                if relative_path == '.':
                    relative_path = ''
                self.ui.outputPathLineEdit.setText(relative_path)
            else:
                self.ui.outputPathLineEdit.setText(folder_path)

    def browse_image_path(self):
        default_path = self.ui.imagePathLineEdit.text()
        if not os.path.isabs(default_path):
            default_path = os.path.join(self.app_data_dir, default_path)

        folder_path = QFileDialog.getExistingDirectory(
            self,
            "选择输出路径",
            default_path
        )

        if folder_path:
            # 转换为相对路径（如果在 app_data_dir 内）
            if folder_path.startswith(self.app_data_dir):
                relative_path = os.path.relpath(folder_path, self.app_data_dir)
                if relative_path == '.':
                    relative_path = ''
                self.ui.imagePathLineEdit.setText(relative_path)
            else:
                self.ui.imagePathLineEdit.setText(folder_path)

    def browse_pdf_path(self):
        default_path = self.ui.pdfPathLineEdit.text()
        if not os.path.isabs(default_path):
            default_path = os.path.join(self.app_data_dir, default_path)

        folder_path = QFileDialog.getExistingDirectory(
            self,
            "选择输出路径",
            default_path
        )

        if folder_path:
            # 转换为相对路径（如果在 app_data_dir 内）
            if folder_path.startswith(self.app_data_dir):
                relative_path = os.path.relpath(folder_path, self.app_data_dir)
                if relative_path == '.':
                    relative_path = ''
                self.ui.pdfPathLineEdit.setText(relative_path)
            else:
                self.ui.pdfPathLineEdit.setText(folder_path)

    def load_settings(self):
        """加载设置：从 SettingsManager 读取并应用到界面控件"""
        settings = self.settings_manager.load()

        if not settings:
            # 默认设置
            self.ui.outputPathLineEdit.setText("Recordings")
            self.ui.outputFileNameLineEdit.setText("录制结果")
            self.ui.imagePathLineEdit.setText("Recordings")
            self.ui.imageFileNameLineEdit.setText("截图")
            self.ui.pdfPathLineEdit.setText("Recordings")
            self.ui.pdfFileNameLineEdit.setText("输出")
            return

        # 恢复设置
        if 'output_format' in settings:
            index = self.ui.formatComboBox.findText(settings['output_format'])
            if index != -1:
                self.ui.formatComboBox.setCurrentIndex(index)

        if 'fps' in settings:
            self.ui.fpsSpinBox.setValue(settings['fps'])

        if 'output_path' in settings:
            self.ui.outputPathLineEdit.setText(settings['output_path'])
        else:
            self.ui.outputPathLineEdit.setText("Recordings")

        if 'output_file_name' in settings:
            self.ui.outputFileNameLineEdit.setText(settings['output_file_name'])
        else:
            self.ui.outputFileNameLineEdit.setText("录制结果")

        if 'image_format' in settings:
            index = self.ui.imageFormatComboBox.findText(settings['image_format'])
            if index != -1:
                self.ui.imageFormatComboBox.setCurrentIndex(index)

        if 'image_path' in settings:
            self.ui.imagePathLineEdit.setText(settings['image_path'])
        else:
            self.ui.imagePathLineEdit.setText("Recordings")

        if 'image_file_name' in settings:
            self.ui.imageFileNameLineEdit.setText(settings['image_file_name'])
        else:
            self.ui.imageFileNameLineEdit.setText("截图")

        if 'pdf_path' in settings:
            self.ui.pdfPathLineEdit.setText(settings['pdf_path'])
        else:
            self.ui.pdfPathLineEdit.setText("Recordings")

        if 'pdf_file_name' in settings:
            self.ui.pdfFileNameLineEdit.setText(settings['pdf_file_name'])
        else:
            self.ui.pdfFileNameLineEdit.setText("输出")

        if 'frame_interval' in settings:
            self.ui.frameIntervalSpinBox.setValue(settings['frame_interval'])

        if 'pdf_frame_interval' in settings:
            self.ui.pdfFrameIntervalSpinBox.setValue(settings['pdf_frame_interval'])

        if 'always_on_top' in settings:
            self.ui.actionAlwaysOnTop.setChecked(settings['always_on_top'])
            self.toggle_always_on_top()

        if 'ocr_enabled' in settings:
            self.ui.actionOcrEnabled.setChecked(settings['ocr_enabled'])

        # 「OCR 识别」页设置恢复
        if hasattr(self, 'ocrFolderEdit'):
            if 'ocr_folder_path' in settings:
                self.ocrFolderEdit.setText(settings['ocr_folder_path'])
            if 'ocr_recursive' in settings:
                self.ocrRecursiveCheck.setChecked(settings['ocr_recursive'])
            if 'ocr_include_pdf' in settings:
                self.ocrPdfCheck.setChecked(settings['ocr_include_pdf'])
            if 'ocr_merge_images' in settings:
                self.ocrMergeCheck.setChecked(settings['ocr_merge_images'])
            if 'ocr_concurrency' in settings:
                self.ocrConcurrencySpin.setValue(settings['ocr_concurrency'])
            if 'ocr_model_dir' in settings:
                self.ocrModelDirEdit.setText(settings['ocr_model_dir'])

        # 「ASR 识别」页设置恢复（与 OCR 分目录；骨架选项先行就位）
        if hasattr(self, 'asrFolderEdit'):
            if 'asr_model_dir' in settings:
                self.asrModelDirEdit.setText(settings['asr_model_dir'])
            if 'asr_folder_path' in settings:
                self.asrFolderEdit.setText(settings['asr_folder_path'])
            if 'asr_concurrency' in settings:
                self.asrConcurrencySpin.setValue(settings['asr_concurrency'])
            if 'asr_video_auto' in settings:
                self.asrVideoAutoCheck.setChecked(settings['asr_video_auto'])
            if 'asr_recursive' in settings:
                self.asrRecursiveCheck.setChecked(settings['asr_recursive'])
            if 'asr_formats' in settings:
                self.asrFormatsEdit.setText(settings['asr_formats'])

        # OCR/ASR 输出目录选项恢复
        if hasattr(self, 'ocrAsrOutCheck'):
            if 'ocr_asr_out_enabled' in settings:
                self.ocrAsrOutCheck.setChecked(settings['ocr_asr_out_enabled'])
            if 'ocr_asr_out_dir' in settings:
                self.ocrAsrOutDirEdit.setText(settings['ocr_asr_out_dir'])

    def save_settings(self):
        """保存设置：汇总界面状态并交给 SettingsManager 写文件"""
        settings = {
            'output_format': self.ui.formatComboBox.currentText(),
            'fps': self.ui.fpsSpinBox.value(),
            'output_path': self.ui.outputPathLineEdit.text(),
            'output_file_name': self.ui.outputFileNameLineEdit.text(),
            'image_format': self.ui.imageFormatComboBox.currentText(),
            'image_path': self.ui.imagePathLineEdit.text(),
            'image_file_name': self.ui.imageFileNameLineEdit.text(),
            'pdf_path': self.ui.pdfPathLineEdit.text(),
            'pdf_file_name': self.ui.pdfFileNameLineEdit.text(),
            'frame_interval': self.ui.frameIntervalSpinBox.value(),
            'pdf_frame_interval': self.ui.pdfFrameIntervalSpinBox.value(),
            'always_on_top': self.ui.actionAlwaysOnTop.isChecked(),
            'ocr_enabled': self.ui.actionOcrEnabled.isChecked(),
            'ocr_folder_path': self.ocrFolderEdit.text() if hasattr(self, 'ocrFolderEdit') else "",
            'ocr_recursive': self.ocrRecursiveCheck.isChecked() if hasattr(self, 'ocrRecursiveCheck') else True,
            'ocr_include_pdf': self.ocrPdfCheck.isChecked() if hasattr(self, 'ocrPdfCheck') else True,
            'ocr_merge_images': self.ocrMergeCheck.isChecked() if hasattr(self, 'ocrMergeCheck') else True,
            'ocr_concurrency': self.ocrConcurrencySpin.value() if hasattr(self, 'ocrConcurrencySpin') else 4,
            'ocr_model_dir': self.ocrModelDirEdit.text() if hasattr(self, 'ocrModelDirEdit') else "",
            'asr_model_dir': self.asrModelDirEdit.text() if hasattr(self, 'asrModelDirEdit') else "",
            'asr_folder_path': self.asrFolderEdit.text() if hasattr(self, 'asrFolderEdit') else "",
            'asr_concurrency': self.asrConcurrencySpin.value() if hasattr(self, 'asrConcurrencySpin') else 4,
            'asr_video_auto': self.asrVideoAutoCheck.isChecked() if hasattr(self, 'asrVideoAutoCheck') else True,
            'asr_recursive': self.asrRecursiveCheck.isChecked() if hasattr(self, 'asrRecursiveCheck') else True,
            'asr_formats': self.asrFormatsEdit.text() if hasattr(self, 'asrFormatsEdit') else "wav,mp3,m4a,flac,ogg,mp4,mkv,avi,mov,webm",
            'ocr_asr_out_enabled': self.ocrAsrOutCheck.isChecked() if hasattr(self, 'ocrAsrOutCheck') else False,
            'ocr_asr_out_dir': self.ocrAsrOutDirEdit.text() if hasattr(self, 'ocrAsrOutDirEdit') else "输出",
            'shortcuts': self.shortcut_manager.to_dict(),
        }
        self.settings_manager.save(settings)

    def closeEvent(self, event):
        """关闭窗口时保存设置并注销全局热键"""
        self.save_settings()
        self.global_hotkeys.unregister_all()
        # 等待后台导出线程结束（短暂等待，避免写一半的 PDF 损坏）
        for w in (self._pdf_export_worker, self._sidecar_worker, self._folder_ocr_worker):
            if w is not None and getattr(w, '_thread', None) is not None:
                try:
                    w._thread.join(timeout=5)
                except Exception:
                    pass
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = MainWindow()
    widget.show()
    sys.exit(app.exec())
