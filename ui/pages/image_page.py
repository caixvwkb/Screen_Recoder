# -*- coding: utf-8 -*-
import system.tracelog as tracelog
import os
from datetime import datetime
"""ScreenRecorder 2.2 散图录制页控制器（页面构建 + 页面业务逻辑）。

迁移自 mainwindow_fluent.py：页面方法按功能页拆分到 ui/pages/，
MainWindow 通过多继承装配各 Mixin；跨页公共能力（模型检查 / 设置持久化 /
提示 / 数值输入框 QSS）仍在 MainWindow 中提供，此处经 self 调用。
"""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QWidget, QFileDialog,
                               QSpinBox, QDoubleSpinBox, QProgressBar)
from PySide6.QtGui import QDesktopServices, QGuiApplication
from qfluentwidgets import (FluentIcon, PushButton, PrimaryPushButton,
                            SwitchButton, ComboBox, LineEdit, BodyLabel,
                            CaptionLabel, HorizontalSeparator)
from ui.widgets import TwoRowCard
from capture.capture import ImageCapture
from system.global_hotkey import GlobalHotkeyManager
from capture.region_selector import SelectionWindow
from recognition.export_worker import SidecarWorker


class ImagePageMixin(object):
    def _build_image_page(self, page):
        """散图录制页：迁移旧版 imageTab（mainwindow.py 119-126 信号段）。

        设计意图：不录视频文件，按需抓取静态帧（图片序列），
        可配合 OCR 自动生成"AI 可读说明.md"。
          - 手动批量模式：后台待命注册全局 Enter，切到任意程序按 Enter 抓帧，
            停止会话后自动 OCR 生成说明.md（全程无需回本软件）。
          - 自动定时模式：按设定间隔连拍，适合监控画面变化。
        """
        # 状态
        self.image_region = None
        self.image_window_hwnd = None   # 应用窗口捕获：目标窗口句柄（None=屏幕区域模式）
        self.batch_mode = False
        self.batch_folder = None
        self.image_capture_count = 0
        self.image_captured_files = []
        self.is_image_recording = False
        self.image_capture = None
        self.image_timer = None
        self._sidecar_processing = False
        self._sidecar_worker = None
        self.image_page = page

        # 全局热键（后台待命）：批量会话期间注册全局 Enter 截图
        if not hasattr(self, "global_hotkeys"):
            # MainWindow 已在导航构建前创建统一实例并连接 _route_action 路由；
            # 这里只复用（会话期 Enter 注册走统一实例），不重复连接避免双触发。
            self.global_hotkeys = GlobalHotkeyManager(self)
            self.global_hotkeys.activated.connect(self._on_global_hotkey)
            self.global_hotkeys.install(QApplication.instance())

        # —— 块① 截图区域：全屏 / 框选 + 状态行（与视频页"录制区域"同构） ——
        region_card = page.block_cards["截图区域"]

        # 全屏截图
        self.image_fullscreen_btn = PrimaryPushButton("选择全屏")
        self.image_fullscreen_btn.setMinimumWidth(96)
        self.image_fullscreen_btn.clicked.connect(lambda: self._run_with_sound(self._select_image_fullscreen_region))
        fs_card = TwoRowCard(
            FluentIcon.FULL_SCREEN, "全屏截图", "一键框定整个主屏为截图区域")
        fs_card.add_control(self.image_fullscreen_btn, 0, Qt.AlignLeft)
        region_card.addGroupWidget(fs_card)

        # 框选截图
        self.image_box_btn = PrimaryPushButton("框选范围")
        self.image_box_btn.setMinimumWidth(96)
        self.image_box_btn.clicked.connect(lambda: self._run_with_sound(self._select_image_region))
        box_card = TwoRowCard(
            FluentIcon.CUT, "框选截图", "手动框选屏幕上的任意区域")
        box_card.add_control(self.image_box_btn, 0, Qt.AlignLeft)
        region_card.addGroupWidget(box_card)

        # 应用窗口捕获：选择运行中的应用窗口，捕获其真实画面（不被遮挡）
        self.image_window_btn = PrimaryPushButton("选择窗口")
        self.image_window_btn.setMinimumWidth(96)
        self.image_window_btn.clicked.connect(lambda: self._run_with_sound(self._pick_image_window))
        window_card = TwoRowCard(
            FluentIcon.APPLICATION, "应用窗口捕获",
            "捕获指定应用窗口画面，即使被其他画面遮挡也取窗口真实内容")
        window_card.add_control(self.image_window_btn, 0, Qt.AlignLeft)
        region_card.addGroupWidget(window_card)

        # 当前区域状态行
        region_status = QHBoxLayout()
        region_status.setContentsMargins(8, 4, 8, 4)
        self.image_region_status = CaptionLabel("当前区域: 未选择")
        region_status.addWidget(self.image_region_status)
        region_status.addStretch(1)
        region_status_widget = QWidget()
        region_status_widget.setLayout(region_status)
        region_card.addGroupWidget(region_status_widget)

        # —— 块② 保存设置 ——
        save_card = page.block_cards["保存设置"]

        # 图片格式
        self.image_format_combo = ComboBox()
        self.image_format_combo.addItems(["png", "jpg", "bmp"])
        self.image_format_combo.setFixedWidth(110)
        self.image_format_combo.currentTextChanged.connect(
            lambda _: self._save_settings())
        fmt_card = TwoRowCard(
            FluentIcon.PHOTO, "图片格式", "输出图片格式，png 无损 / jpg 体积小 / bmp 原始位图")
        fmt_card.add_control(self.image_format_combo)
        fmt_card.controls.addStretch(1)
        save_card.addGroupWidget(fmt_card)

        # 输出目录
        self.image_path_edit = LineEdit()
        self.image_path_edit.setPlaceholderText("留空=默认输出目录")
        self.image_path_edit.setClearButtonEnabled(True)
        self.image_path_edit.setMinimumWidth(160)
        self.image_path_edit.editingFinished.connect(self._save_settings)
        self.image_path_btn = PushButton("选择…")
        self.image_path_btn.setMinimumWidth(72)
        self.image_path_btn.clicked.connect(self._browse_image_path)
        self.image_path_open_btn = PushButton("打开")
        self.image_path_open_btn.setMinimumWidth(72)
        self.image_path_open_btn.clicked.connect(self._open_image_path)
        dir_card = TwoRowCard(
            FluentIcon.FOLDER, "输出目录", "截图保存位置；「选择…」更换目录，「打开」在资源管理器显示")
        dir_card.add_control(self.image_path_edit, 1)
        dir_card.add_control(self.image_path_btn)
        dir_card.add_control(self.image_path_open_btn)
        dir_card.controls.addSpacing(16)
        save_card.addGroupWidget(dir_card)

        # 文件夹名
        self.image_name_edit = LineEdit()
        self.image_name_edit.setText("截图")
        self.image_name_edit.setClearButtonEnabled(True)
        self.image_name_edit.setMinimumWidth(200)
        self.image_name_edit.editingFinished.connect(self._save_settings)
        name_card = TwoRowCard(
            FluentIcon.EDIT, "文件夹名", "每次会话自动创建「文件夹名_时间戳」子文件夹，图片按 1、2、3… 序号命名")
        name_card.add_control(self.image_name_edit, 1)
        name_card.controls.addSpacing(16)
        save_card.addGroupWidget(name_card)

        # —— 块③ 截图控制：手动批量 + 自动连拍 两种模式放一起 ——
        ctrl_card = page.block_cards["截图控制"]

        # 手动批量会话：开始/停止 + 截取图片(Enter)
        self.manual_start_btn = PrimaryPushButton("开始批量")
        self.manual_start_btn.setMinimumWidth(92)
        self.manual_start_btn.clicked.connect(lambda: self._run_with_sound(self._start_batch_capture))
        self.manual_stop_btn = PushButton("停止批量")
        self.manual_stop_btn.setMinimumWidth(92)
        self.manual_stop_btn.setEnabled(False)
        self.manual_stop_btn.clicked.connect(lambda: self._run_with_sound(self._stop_batch_capture))
        self.capture_btn = PushButton("截取图片 (Enter)")
        self.capture_btn.setMinimumWidth(120)
        self.capture_btn.clicked.connect(lambda: self._run_with_sound(self._capture_image, ok_sound="ok"))
        manual_card = TwoRowCard(
            FluentIcon.EMBED, "手动批量截图",
            "点「开始批量」进入后台待命：切到任意程序操作，按 Enter 截取一帧；停止后自动 OCR 生成说明.md")
        manual_card.add_control(self.manual_start_btn)
        manual_card.add_control(self.manual_stop_btn)
        manual_card.add_control(self.capture_btn)
        manual_card.controls.addStretch(1)
        ctrl_card.addGroupWidget(manual_card)

        # 一次性截图：突发性单张截图（框选→立即截取→打开图片目录，无需批量会话）
        self.one_shot_btn = PrimaryPushButton("框选并截图")
        self.one_shot_btn.setMinimumWidth(96)
        self.one_shot_btn.clicked.connect(lambda: self._run_with_sound(self._start_one_shot_capture))
        one_card = TwoRowCard(
            FluentIcon.CAMERA, "一次性截图",
            "框选后立即截取一张图片并打开所在目录，适合快速单张截图（不进批量）")
        one_card.add_control(self.one_shot_btn)
        one_card.controls.addStretch(1)
        ctrl_card.addGroupWidget(one_card)

        # 自动定时连拍
        self.auto_start_btn = PrimaryPushButton("开始连拍")
        self.auto_start_btn.setMinimumWidth(92)
        self.auto_start_btn.clicked.connect(lambda: self._run_with_sound(self._start_image_recording))
        self.auto_stop_btn = PushButton("停止连拍")
        self.auto_stop_btn.setMinimumWidth(92)
        self.auto_stop_btn.setEnabled(False)
        self.auto_stop_btn.clicked.connect(lambda: self._run_with_sound(self._stop_image_recording))
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 100.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setValue(1.0)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setFixedSize(88, 32)
        self._apply_num_qss(self.interval_spin)
        self.interval_spin.valueChanged.connect(lambda _: self._save_settings())
        auto_card = TwoRowCard(
            FluentIcon.VIEW, "自动定时连拍",
            "按设定间隔自动截取当前区域，适合监控画面变化；停止后同样触发 OCR 说明.md")
        auto_card.add_control(BodyLabel("间隔(秒):"))
        auto_card.add_control(self.interval_spin)
        auto_card.add_control(self.auto_stop_btn)
        auto_card.add_control(self.auto_start_btn)
        auto_card.controls.addStretch(1)
        ctrl_card.addGroupWidget(auto_card)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 4, 0, 0)
        self.image_status_label = CaptionLabel("状态: 就绪")
        status_row.addWidget(self.image_status_label)
        status_row.addStretch(1)
        preview_status_widget = QWidget()
        preview_status_widget.setLayout(status_row)
        ctrl_card.addGroupWidget(preview_status_widget)

        # 恢复持久化设置
        self._load_image_page_settings()
    def _load_image_page_settings(self):
        settings = self.settings_manager.load()
        if "image_format" in settings:
            idx = self.image_format_combo.findText(str(settings["image_format"]))
            if idx >= 0:
                self.image_format_combo.setCurrentIndex(idx)
        if "image_path" in settings:
            self.image_path_edit.setText(str(settings["image_path"]))
        if "image_name" in settings:
            self.image_name_edit.setText(str(settings["image_name"]))
        if "image_interval" in settings:
            self.interval_spin.setValue(float(settings["image_interval"]))

    # ---- 散图区域选择 ----
    def _select_image_fullscreen_region(self):
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self._show_tip("无法获取屏幕", "未检测到主屏幕")
            return False
        geo = screen.geometry()
        self.image_region = (geo.x(), geo.y(), geo.width(), geo.height())
        self.image_region_status.setText(
            f"当前区域: 全屏 {geo.width()}x{geo.height()}")
        self._show_tip("已选择全屏", f"截图区域: {geo.width()}x{geo.height()}")
        return True
    def _select_image_region(self):
        self.hide()
        self._selection_window = SelectionWindow()
        self._selection_window.selection_completed.connect(self._on_image_region_done)
        self._selection_window.selection_canceled.connect(self._on_image_region_cancel)
        self._selection_window.show()
        return True
    def _on_image_region_done(self, region):
        x, y, width, height = region
        self.image_region = (x, y, width, height)
        self.image_region_status.setText(f"当前区域: ({x}, {y}) {width}x{height}")
        self.show()
    def _on_image_region_cancel(self):
        self.show()
        if not self.image_region:
            self.image_region_status.setText("当前区域: 未选择")

    # ---- 一次性截图（单发：框选 → 立即截取 → 打开目录） ----
    def _start_one_shot_capture(self):
        """进入框选模式；框选完成自动截图并打开目录（突发性单张场景）。"""
        try:
            self.hide()  # 隐藏本窗口，避免被截进画面
            self._one_shot_selection = SelectionWindow()
            self._one_shot_selection.selection_completed.connect(self._on_one_shot_region_done)
            self._one_shot_selection.selection_canceled.connect(self._on_one_shot_region_cancel)
            self._one_shot_selection.show()
            return True
        except Exception as e:
            self._show_tip("一次性截图启动失败", str(e))
            return False

    def _on_one_shot_region_cancel(self):
        self.show()

    def _on_one_shot_region_done(self, region):
        """框选完成：先收起框选窗口，保持主窗口隐藏，稍等画面刷新后再截图，
        避免红框/主窗口 UI 被截进画面；截图完成后再显示主窗口。"""
        x, y, width, height = region
        self.image_region = (x, y, width, height)
        self.image_region_status.setText(f"当前区域: ({x}, {y}) {width}x{height}")
        try:
            self._one_shot_selection.hide()  # 收起框选红框
        except Exception:
            pass
        QTimer.singleShot(120, self._capture_one_shot)  # 等 Windows 重绘桌面后抓屏

    def _capture_one_shot(self):
        """单发截图：存到散图输出根目录（不建会话子文件夹），完成后显示主窗口并打开目录。"""
        try:
            if not self.image_region:
                self._show_tip("请先框选范围", "一次性截图需要先框选屏幕区域")
                self.show()
                return
            base_path = self._image_output_base()
            if not os.access(base_path, os.W_OK):
                self._show_tip("输出路径没有写入权限", base_path)
                self.show()
                return
            fmt = self.image_format_combo.currentText()
            name = self.image_name_edit.text().strip() or "截图"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(base_path, f"{name}_单张_{timestamp}.{fmt}")
            x, y, w, h = self.image_region
            from capture.capture import grab_region
            pixmap = grab_region(x, y, w, h)
            if pixmap is None or pixmap.isNull():
                self._show_tip("截图失败", "无法获取屏幕区域")
                import system.sound_feedback as sound_feedback
                sound_feedback.play_fail()
                self.show()
                return
            if not pixmap.save(out_path):
                self._show_tip("保存失败", out_path)
                import system.sound_feedback as sound_feedback
                sound_feedback.play_fail()
                self.show()
                return
            self.show()  # 画面已抓取，恢复主窗口
            self.setFocus()  # 焦点归还主窗口（一次性截图后 Enter 仍可继续截图）
            import system.sound_feedback as sound_feedback
            sound_feedback.play_ok()  # 真正截取成功 → ok 音
            self.image_status_label.setText(
                f"状态: 已截取单张 -> {os.path.basename(out_path)}")
            self._show_tip("已截取", os.path.basename(out_path))
            # 自动 OCR 开启时：单文件单核识别，生成同名说明.md（不受并发设置影响）
            ocr_on = getattr(self.settings_page, "auto_ocr_switch", None)
            if ocr_on is not None and ocr_on.isChecked():
                if self._check_ocr_model():
                    self._start_one_shot_ocr(out_path, base_path)
            self._open_image_path()  # 打开图片所在目录
        except Exception as e:
            self._show_tip("一次性截图失败", str(e))
            self.show()

    def _start_one_shot_ocr(self, image_path, folder):
        """一次性截图的附带 OCR：单文件单核识别，生成同名 .md（异步，不阻塞）。"""
        def run():
            try:
                from recognition.ocr import ocr_image, write_sidecar_md
                text = ocr_image(image_path, self._ocr_model_dir())
                md_name = os.path.splitext(os.path.basename(image_path))[0] + ".md"
                md = write_sidecar_md(
                    folder, [{"file": image_path, "ocr_text": text}], md_name=md_name)
                if md:
                    tracelog.info(f"[一次性OCR] 已生成: {md}")
                    QTimer.singleShot(0, lambda m=md: self._show_tip(
                        "OCR 说明已生成", os.path.basename(m)))
            except Exception as e:
                tracelog.error(f"[一次性OCR] 生成失败: {e}")
        import threading
        threading.Thread(target=run, daemon=True).start()

    # ---- 散图输出路径 ----
    def _image_output_base(self):
        """拼接散图输出基础目录（相对路径基于默认输出目录）。"""
        path = self.image_path_edit.text().strip()
        if not path:
            path = self.output_dir
        elif not os.path.isabs(path):
            path = os.path.join(self.output_dir, path)
        os.makedirs(path, exist_ok=True)
        return path
    def _browse_image_path(self):
        default_path = self.image_path_edit.text().strip()
        if default_path and not os.path.isabs(default_path):
            default_path = os.path.join(self.output_dir, default_path)
        folder = QFileDialog.getExistingDirectory(
            self, "选择输出路径", default_path or self.output_dir)
        if folder:
            if folder.startswith(self.output_dir):
                rel = os.path.relpath(folder, self.output_dir)
                self.image_path_edit.setText("" if rel == "." else rel)
            else:
                self.image_path_edit.setText(folder)
            self._save_settings()
    def _open_image_path(self):
        """在资源管理器中打开当前截图输出目录（留空=默认输出目录）。"""
        path = self.image_path_edit.text().strip()
        if not path:
            path = self.output_dir
        elif not os.path.isabs(path):
            path = os.path.join(self.output_dir, path)
        os.makedirs(path, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self._show_tip("无法打开目录", path)

    # ---- 全局热键（手动批量会话） ----
    def _on_global_hotkey(self, name):
        """全局热键触发回调（程序后台/失焦时由 Windows 转发进来）。

        通用语意按「当前停留页」路由：当前页是散图 → 散图截取；PDF → PDF 截取；
        其它页 → 由 _route_action 提示。self 为 MainWindow（mixin）。
        """
        if name == "capture_image":
            self._route_action("capture_image")
    def _update_global_capture_hotkey(self):
        """批量截取会话进行中 → 注册全局 Enter 截图；结束 → 注销。

        只在散图/PDF 手动批量期间启用全局 Enter，避免后台常驻时抢走其它程序的 Enter。
        """
        session_active = getattr(self, "batch_mode", False) or getattr(self, "pdf_batch_mode", False)
        if session_active:
            hwnd = int(self.winId())  # Qt6 收不到 NULL 句柄的 WM_HOTKEY，必须真实句柄
            key = self.shortcut_manager.to_dict().get("capture_image", "Return")
            if not self.global_hotkeys.register("capture_image", key, hwnd=hwnd):
                self._show_tip("全局热键注册失败",
                               "Enter 可能被其它程序占用；可改用界面「截取」按钮")
        else:
            self.global_hotkeys.unregister("capture_image")

    # ---- 散图截取 ----
    def _capture_image(self):
        """手动截取一帧：批量会话中写入批量文件夹，否则新建时间戳文件夹。

        返回 True/False 供快捷键路由判断成功与否（播放提示音）。
        """
        try:
            if not self.image_region and not self.image_window_hwnd:
                self._show_tip("请先选择截图区域", "点击「全屏截图」/「框选范围」，或「选择窗口」")
                return False
            from capture.capture import is_window_valid
            if self.image_window_hwnd and not is_window_valid(self.image_window_hwnd):
                self._show_tip("所选窗口已关闭", "请重新选择应用窗口")
                return False
            base_path = self._image_output_base()
            if not os.access(os.path.dirname(base_path), os.W_OK):
                self._show_tip("输出路径没有写入权限", base_path)
                return False
            fmt = self.image_format_combo.currentText()
            if self.batch_mode and self.batch_folder:
                cap = ImageCapture(self.image_region, self.batch_folder, fmt, window_hwnd=self.image_window_hwnd)
                cap.captured.connect(self._on_image_captured)
                self.image_capture_count += 1
                output_file = cap.capture(self.image_capture_count)
                if output_file:
                    self.image_status_label.setText(
                        f"状态: 批量模式已截取 {self.image_capture_count} 张图片")
                    return True
                else:
                    self.image_capture_count -= 1
                    self.image_status_label.setText("状态: 截图失败")
                    return False
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                folder_name = self.image_name_edit.text().strip() or "截图"
                out_folder = os.path.join(base_path, f"{folder_name}_{timestamp}")
                os.makedirs(out_folder, exist_ok=True)
                cap = ImageCapture(self.image_region, out_folder, fmt, window_hwnd=self.image_window_hwnd)
                cap.captured.connect(self._on_image_captured)
                self.image_capture_count += 1
                output_file = cap.capture(self.image_capture_count)
                if output_file:
                    self.image_status_label.setText(
                        f"状态: 已截取 {self.image_capture_count} 张图片")
                    return True
                else:
                    self.image_capture_count -= 1
                    self.image_status_label.setText("状态: 截图失败")
                    return False
        except Exception as e:
            self._show_tip("截图失败", str(e))
            return False
    def _on_image_captured(self, output_file):
        """图片捕获完成回调：批量会话中记录文件供停止后 OCR。"""
        try:
            if output_file and os.path.exists(output_file):
                if self.batch_mode:
                    self.image_captured_files.append(output_file)
        except Exception as e:
            tracelog.error(f"[散图页] 图片捕获回调出错: {e}")
    def _start_batch_capture(self):
        """开始手动批量会话：注册全局 Enter，此后在任意程序按 Enter 抓帧。"""
        try:
            if not self.image_region and not self.image_window_hwnd:
                self._show_tip("请先选择截图区域", "点击「全屏截图」/「框选范围」，或「选择窗口」")
                return False
            from capture.capture import is_window_valid
            if self.image_window_hwnd and not is_window_valid(self.image_window_hwnd):
                self._show_tip("所选窗口已关闭", "请重新选择应用窗口")
                return False
            base_path = self._image_output_base()
            if not os.access(os.path.dirname(base_path), os.W_OK):
                self._show_tip("输出路径没有写入权限", base_path)
                return False
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_name = self.image_name_edit.text().strip() or "截图"
            self.batch_folder = os.path.join(base_path, f"{folder_name}_{timestamp}")
            os.makedirs(self.batch_folder, exist_ok=True)
            self.image_capture_count = 0
            self.image_captured_files = []
            self.batch_mode = True
            self._update_global_capture_hotkey()  # 注册全局 Enter
            self.manual_start_btn.setEnabled(False)
            self.manual_stop_btn.setEnabled(True)
            self.image_status_label.setText("状态: 批量模式已开始，请截取图片")
            self._show_tip("批量模式已开始",
                           "切到任意程序按 Enter 截取；停止后自动 OCR 生成说明.md")
            return True
        except Exception as e:
            self._show_tip("开始批量截图失败", str(e))
            return False
    def _stop_batch_capture(self):
        """停止手动批量会话：注销全局 Enter，触发 OCR 说明.md 生成。"""
        try:
            if not self.batch_mode:
                return False
            capture_count = self.image_capture_count
            self.batch_mode = False
            batch_folder = self.batch_folder
            self.batch_folder = None
            self._update_global_capture_hotkey()  # 注销全局 Enter
            self.manual_start_btn.setEnabled(True)
            self.manual_stop_btn.setEnabled(False)
            self.setFocus()  # 归还焦点，避免焦点残留按钮导致 Enter 误触发
            if capture_count > 0:
                self.image_status_label.setText(
                    f"状态: 批量截图已完成，共截取 {capture_count} 张图片")
                files = list(self.image_captured_files)
                self.image_captured_files = []
                ocr_on = getattr(self.settings_page, "auto_ocr_switch", None)
                if files and not self._sidecar_processing and ocr_on and ocr_on.isChecked():
                    if not self._check_ocr_model():
                        self._show_tip("OCR 模型不可用", "本次截图未生成说明文件")
                    else:
                        self._start_sidecar_ocr(files, batch_folder)
                else:
                    self._show_tip("批量截图已完成",
                                   f"共截取 {capture_count} 张图片。保存到: {batch_folder}")
            else:
                self.image_status_label.setText("状态: 批量截图已取消")
                if os.path.exists(batch_folder):
                    try:
                        os.rmdir(batch_folder)
                    except OSError:
                        pass
            return True
        except Exception as e:
            self._show_tip("停止批量截图失败", str(e))
            self.batch_mode = False
            self.batch_folder = None
            self._update_global_capture_hotkey()
            self.manual_start_btn.setEnabled(True)
            self.manual_stop_btn.setEnabled(False)
            return False

    # ---- 自动定时连拍 ----
    def _start_image_recording(self):
        """开始自动定时连拍。"""
        try:
            if not self.image_region:
                self._show_tip("请先选择截图区域", "点击「全屏截图」或「框选范围」")
                return False
            base_path = self._image_output_base()
            if not os.access(os.path.dirname(base_path), os.W_OK):
                self._show_tip("输出路径没有写入权限", base_path)
                return False
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_name = self.image_name_edit.text().strip() or "截图"
            self.image_output_folder = os.path.join(base_path, f"{folder_name}_{timestamp}")
            os.makedirs(self.image_output_folder, exist_ok=True)
            self.image_capture_count = 0
            fmt = self.image_format_combo.currentText()
            self.image_capture = ImageCapture(
                self.image_region, self.image_output_folder, fmt,
                window_hwnd=self.image_window_hwnd)
            self.image_capture.captured.connect(self._on_image_captured)
            interval_ms = int(max(0.1, self.interval_spin.value()) * 1000)
            self.is_image_recording = True
            self.auto_start_btn.setEnabled(False)
            self.auto_stop_btn.setEnabled(True)
            self.image_status_label.setText("状态: 自动连拍中...")
            self.image_timer = QTimer(self)
            self.image_timer.timeout.connect(self._auto_capture_image)
            self.image_timer.start(interval_ms)
            self._show_tip("开始自动连拍", f"每 {self.interval_spin.value():g} 秒一帧")
            return True
        except Exception as e:
            self._show_tip("开始自动连拍失败", str(e))
            self.is_image_recording = False
            self.auto_start_btn.setEnabled(True)
            self.auto_stop_btn.setEnabled(False)
            self.image_status_label.setText("状态: 就绪")
            return False
    def _auto_capture_image(self):
        if not self.is_image_recording:
            return
        try:
            self.image_capture_count += 1
            output_file = self.image_capture.capture(self.image_capture_count)
            if output_file:
                self.image_status_label.setText(
                    f"状态: 已截取 {self.image_capture_count} 张图片")
            else:
                self.image_capture_count -= 1
                self.image_status_label.setText(
                    f"状态: 已截取 {self.image_capture_count} 张图片 (部分失败)")
        except Exception as e:
            tracelog.error(f"[散图页] 自动截图出错: {e}")
            self.image_capture_count = max(0, self.image_capture_count - 1)
            self.image_status_label.setText(
                f"状态: 已截取 {self.image_capture_count} 张图片 (错误)")
    def _stop_image_recording(self):
        if not self.is_image_recording:
            return False
        try:
            self.image_timer.stop()
            self.is_image_recording = False
            self.auto_start_btn.setEnabled(True)
            self.auto_stop_btn.setEnabled(False)
            self.setFocus()  # 归还焦点，避免焦点残留按钮导致 Enter 误触发
            count = self.image_capture_count
            self.image_status_label.setText(
                f"状态: 已停止，共截取 {count} 张图片")
            files = list(self.image_captured_files)
            self.image_captured_files = []
            ocr_on = getattr(self.settings_page, "auto_ocr_switch", None)
            folder = self.image_output_folder
            if files and not self._sidecar_processing and ocr_on and ocr_on.isChecked():
                if self._check_ocr_model():
                    self._start_sidecar_ocr(files, folder)
            self._show_tip("自动连拍已停止", f"共截取 {count} 张图片")
            return True
        except Exception as e:
            self._show_tip("停止自动连拍失败", str(e))
            self.is_image_recording = False
            if self.image_timer:
                self.image_timer.stop()
            self.auto_start_btn.setEnabled(True)
            self.auto_stop_btn.setEnabled(False)
            return False

    # ---- OCR 说明.md 附带处理 ----
    def _start_sidecar_ocr(self, files, folder):
        """后台启动散图 OCR + 说明.md 生成（不阻塞界面）。"""
        self._sidecar_processing = True
        default_workers = max(1, (os.cpu_count() or 4) // 2)
        self._sidecar_worker = SidecarWorker(
            files, folder,
            max_workers=default_workers,
            model_dir=self._ocr_model_dir())
        self._sidecar_worker.progress.connect(self._on_sidecar_progress)
        self._sidecar_worker.finished.connect(self._on_sidecar_done)
        self._sidecar_worker.failed.connect(self._on_sidecar_failed)
        self.image_status_label.setText(
            f"状态: 正在识别截图文字（OCR）… 0/{len(files)}")
        self._sidecar_worker.start()
    def _on_sidecar_progress(self, cur, total):
        self.image_status_label.setText(
            f"状态: 正在识别截图文字（OCR）… {cur}/{total}")
    def _on_sidecar_done(self, md_path, ok):
        self._sidecar_processing = False
        if ok:
            self.image_status_label.setText("状态: 截图已完成，说明.md 已生成")
            self._show_tip("截图完成", f"说明文件: {md_path}")
        else:
            self.image_status_label.setText("状态: 截图完成（说明.md 生成失败）")
    def _on_sidecar_failed(self, msg):
        self._sidecar_processing = False
        self.image_status_label.setText("状态: 截图完成（OCR 出错）")
        self._show_tip("OCR 出错", msg)

    # ---------------- PDF 输出页 ----------------

    def _pick_image_window(self):
        """选择要捕获的应用窗口（PrintWindow 抓取，被遮挡也取真实内容）。"""
        from ui.widgets import WindowPickerDialog
        from capture.capture import is_window_valid
        res = WindowPickerDialog.pick(self)
        if not res:
            return False
        hwnd, title, w, h = res
        if not is_window_valid(hwnd):
            self._show_tip("窗口无效", "所选窗口已关闭，请重新选择")
            return False
        self.image_window_hwnd = int(hwnd)
        self.image_window_title = title
        self.image_region = None
        self.image_region_status.setText("当前区域: 窗口「%s」 %dx%d" % (title, w, h))
        self._show_tip("已选择窗口", "%s (%dx%d)" % (title, w, h))
        return True
