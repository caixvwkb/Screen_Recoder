# -*- coding: utf-8 -*-
import system.tracelog as tracelog
import os
from datetime import datetime
"""ScreenRecorder 2.2 PDF 输出页控制器（页面构建 + 页面业务逻辑）。

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
from capture.capture import PDFExporter
from recognition.export_worker import PDFExportWorker
from capture.region_selector import SelectionWindow


class PdfPageMixin(object):
    def _build_pdf_page(self, page):
        """PDF 输出页：迁移旧版 pdfTab（mainwindow.py 129-135 信号段）。

        设计意图：把"当前屏幕区域"逐帧抓成图片序列，再一次性打包成一个 PDF
        （图片按原尺寸排页，保证完整不裁剪）。与散图录制同构：
          - 手动批量：后台待命注册全局 Enter，切到任意程序按 Enter 抓一页，
            停止后自动合成 PDF（可选 OCR 文字层）。
          - 自动连拍：按间隔自动抓帧，停止后合成 PDF。
        中间临时图片存在 output_dir/temp_时间戳/，导出完成后自动清理。
        """
        # 状态
        self.pdf_region = None
        self.pdf_window_hwnd = None   # 应用窗口捕获：目标窗口句柄（None=屏幕区域模式）
        self.pdf_batch_mode = False
        self.pdf_capture_count = 0
        self.pdf_exporter = None
        self.is_pdf_recording = False
        self.pdf_timer = None
        self._pdf_exporting = False
        self._pdf_export_worker = None
        self.pdf_page = page

        # —— 块① 页面设置：截图区域（与视频/散图同构） ——
        region_card = page.block_cards["页面设置"]

        # 全屏
        self.pdf_fullscreen_btn = PrimaryPushButton("选择全屏")
        self.pdf_fullscreen_btn.setMinimumWidth(96)
        self.pdf_fullscreen_btn.clicked.connect(lambda: self._run_with_sound(self._select_pdf_fullscreen_region))
        fs_card = TwoRowCard(
            FluentIcon.FULL_SCREEN, "全屏页面", "一键框定整个主屏为 PDF 页面区域")
        fs_card.add_control(self.pdf_fullscreen_btn, 0, Qt.AlignLeft)
        region_card.addGroupWidget(fs_card)

        # 框选
        self.pdf_box_btn = PrimaryPushButton("框选范围")
        self.pdf_box_btn.setMinimumWidth(96)
        self.pdf_box_btn.clicked.connect(lambda: self._run_with_sound(self._select_pdf_region))
        box_card = TwoRowCard(
            FluentIcon.CUT, "框选页面", "手动框选屏幕区域作为 PDF 页面")
        box_card.add_control(self.pdf_box_btn, 0, Qt.AlignLeft)
        region_card.addGroupWidget(box_card)

        # 应用窗口捕获：选择运行中的应用窗口，捕获其真实画面（不被遮挡）
        self.pdf_window_btn = PrimaryPushButton("选择窗口")
        self.pdf_window_btn.setMinimumWidth(96)
        self.pdf_window_btn.clicked.connect(lambda: self._run_with_sound(self._pick_pdf_window))
        window_card = TwoRowCard(
            FluentIcon.APPLICATION, "应用窗口捕获",
            "捕获指定应用窗口画面，即使被其他画面遮挡也取窗口真实内容")
        window_card.add_control(self.pdf_window_btn, 0, Qt.AlignLeft)
        region_card.addGroupWidget(window_card)

        # 当前区域状态行
        region_status = QHBoxLayout()
        region_status.setContentsMargins(8, 4, 8, 4)
        self.pdf_region_status = CaptionLabel("当前区域: 未选择")
        region_status.addWidget(self.pdf_region_status)
        region_status.addStretch(1)
        region_status_widget = QWidget()
        region_status_widget.setLayout(region_status)
        region_card.addGroupWidget(region_status_widget)

        # —— 块② 输出设置 ——
        out_card = page.block_cards["输出设置"]

        # 输出目录
        self.pdf_path_edit = LineEdit()
        self.pdf_path_edit.setPlaceholderText("留空=默认输出目录")
        self.pdf_path_edit.setClearButtonEnabled(True)
        self.pdf_path_edit.setMinimumWidth(160)
        self.pdf_path_edit.editingFinished.connect(self._save_settings)
        self.pdf_path_btn = PushButton("选择…")
        self.pdf_path_btn.setMinimumWidth(72)
        self.pdf_path_btn.clicked.connect(self._browse_pdf_path)
        self.pdf_path_open_btn = PushButton("打开")
        self.pdf_path_open_btn.setMinimumWidth(72)
        self.pdf_path_open_btn.clicked.connect(self._open_pdf_path)
        dir_card = TwoRowCard(
            FluentIcon.FOLDER, "输出目录", "PDF 保存位置；「选择…」更换目录，「打开」在资源管理器显示")
        dir_card.add_control(self.pdf_path_edit, 1)
        dir_card.add_control(self.pdf_path_btn)
        dir_card.add_control(self.pdf_path_open_btn)
        dir_card.controls.addSpacing(16)
        out_card.addGroupWidget(dir_card)

        # 文件名
        self.pdf_name_edit = LineEdit()
        self.pdf_name_edit.setText("输出")
        self.pdf_name_edit.setClearButtonEnabled(True)
        self.pdf_name_edit.setMinimumWidth(180)
        self.pdf_name_edit.editingFinished.connect(self._save_settings)
        name_card = TwoRowCard(
            FluentIcon.EDIT, "文件名", "PDF 输出文件名，自动补 .pdf 扩展名")
        name_card.add_control(self.pdf_name_edit, 1)
        name_card.add_control(BodyLabel(".pdf"))
        name_card.controls.addSpacing(16)
        out_card.addGroupWidget(name_card)

        # —— 块③ 录制控制：手动批量 + 自动连拍 ——
        ctrl_card = page.block_cards["录制控制"]

        # 手动批量会话
        self.pdf_manual_start_btn = PrimaryPushButton("开始批量")
        self.pdf_manual_start_btn.setMinimumWidth(92)
        self.pdf_manual_start_btn.clicked.connect(lambda: self._run_with_sound(self._start_pdf_batch_capture))
        self.pdf_manual_stop_btn = PushButton("停止批量")
        self.pdf_manual_stop_btn.setMinimumWidth(92)
        self.pdf_manual_stop_btn.setEnabled(False)
        self.pdf_manual_stop_btn.clicked.connect(lambda: self._run_with_sound(self._stop_pdf_batch_capture))
        self.pdf_capture_btn = PushButton("截取页面 (Enter)")
        self.pdf_capture_btn.setMinimumWidth(120)
        self.pdf_capture_btn.clicked.connect(lambda: self._run_with_sound(self._pdf_capture_image))
        manual_card = TwoRowCard(
            FluentIcon.EMBED, "手动批量抓页",
            "点「开始批量」进入后台待命：切到任意程序操作，按 Enter 抓一页；停止后自动合成 PDF")
        manual_card.add_control(self.pdf_manual_start_btn)
        manual_card.add_control(self.pdf_manual_stop_btn)
        manual_card.add_control(self.pdf_capture_btn)
        manual_card.controls.addStretch(1)
        ctrl_card.addGroupWidget(manual_card)

        # 自动连拍
        self.pdf_auto_start_btn = PrimaryPushButton("开始连拍")
        self.pdf_auto_start_btn.setMinimumWidth(92)
        self.pdf_auto_start_btn.clicked.connect(lambda: self._run_with_sound(self._start_pdf_recording))
        self.pdf_auto_stop_btn = PushButton("停止连拍")
        self.pdf_auto_stop_btn.setMinimumWidth(92)
        self.pdf_auto_stop_btn.setEnabled(False)
        self.pdf_auto_stop_btn.clicked.connect(lambda: self._run_with_sound(self._stop_pdf_recording))
        self.pdf_interval_spin = QDoubleSpinBox()
        self.pdf_interval_spin.setRange(0.1, 100.0)
        self.pdf_interval_spin.setSingleStep(0.5)
        self.pdf_interval_spin.setValue(1.0)
        self.pdf_interval_spin.setDecimals(1)
        self.pdf_interval_spin.setFixedSize(88, 32)
        self._apply_num_qss(self.pdf_interval_spin)
        auto_card = TwoRowCard(
            FluentIcon.VIEW, "自动定时连拍",
            "按设定间隔自动抓取当前区域，停止后合成 PDF（适合监控画面变化）")
        auto_card.add_control(BodyLabel("间隔(秒):"))
        auto_card.add_control(self.pdf_interval_spin)
        auto_card.add_control(self.pdf_auto_stop_btn)
        auto_card.add_control(self.pdf_auto_start_btn)
        auto_card.controls.addStretch(1)
        ctrl_card.addGroupWidget(auto_card)

        # —— 状态行（与视频页/散图页同构：第三块内最后一行） ——
        status_row = QHBoxLayout()
        status_row.setContentsMargins(8, 4, 8, 4)
        self.pdf_status_label = CaptionLabel("状态: 就绪")
        status_row.addWidget(self.pdf_status_label)
        status_row.addStretch(1)
        self.pdf_progress_bar = QProgressBar()
        self.pdf_progress_bar.setRange(0, 100)
        self.pdf_progress_bar.setValue(0)
        self.pdf_progress_bar.setFixedSize(160, 12)
        self._apply_progress_qss()
        status_row.addWidget(self.pdf_progress_bar)
        ctrl_status_widget = QWidget()
        ctrl_status_widget.setLayout(status_row)
        ctrl_card.addGroupWidget(ctrl_status_widget)

        # 恢复持久化设置
        self._load_pdf_page_settings()
    def _load_pdf_page_settings(self):
        settings = self.settings_manager.load()
        if "pdf_path" in settings:
            self.pdf_path_edit.setText(str(settings["pdf_path"]))
        if "pdf_name" in settings:
            self.pdf_name_edit.setText(str(settings["pdf_name"]))
    def _select_pdf_fullscreen_region(self):
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self._show_tip("无法获取屏幕", "未检测到主屏幕")
            return False
        geo = screen.geometry()
        self.pdf_region = (geo.x(), geo.y(), geo.width(), geo.height())
        self.pdf_region_status.setText(
            f"当前区域: 全屏 {geo.width()}x{geo.height()}")
        self._show_tip("已选择全屏", f"PDF 页面区域: {geo.width()}x{geo.height()}")
        return True
    def _select_pdf_region(self):
        self.hide()
        self._selection_window = SelectionWindow()
        self._selection_window.selection_completed.connect(self._on_pdf_region_done)
        self._selection_window.selection_canceled.connect(self._on_pdf_region_cancel)
        self._selection_window.show()
        return True
    def _on_pdf_region_done(self, region):
        x, y, width, height = region
        self.pdf_region = (x, y, width, height)
        self.pdf_region_status.setText(f"当前区域: ({x}, {y}) {width}x{height}")
        self.show()
    def _on_pdf_region_cancel(self):
        self.show()
        if not self.pdf_region:
            self.pdf_region_status.setText("当前区域: 未选择")

    # ---- PDF 输出路径 ----
    def _pdf_output_file(self):
        """拼接 PDF 输出完整文件路径（相对路径基于默认输出目录）。"""
        path = self.pdf_path_edit.text().strip()
        if not path:
            path = self.output_dir
        elif not os.path.isabs(path):
            path = os.path.join(self.output_dir, path)
        os.makedirs(path, exist_ok=True)
        name = self.pdf_name_edit.text().strip() or "输出"
        return os.path.join(path, f"{name}.pdf")
    def _pdf_temp_folder(self):
        """PDF 临时目录：放缓存区（源码=项目根 cache，打包版=exe 同级 cache），
        不在输出目录创建；PDFExporter 为内存模式（帧不落盘），此目录仅作占位/兼容，
        导出完成或取消时由 cleanup() 删除。"""
        from system.paths import cache_dir
        cache = cache_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(cache, f"pdf_temp_{timestamp}")
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass
        return folder
    def _browse_pdf_path(self):
        default_path = self.pdf_path_edit.text().strip()
        if default_path and not os.path.isabs(default_path):
            default_path = os.path.join(self.output_dir, default_path)
        folder = QFileDialog.getExistingDirectory(
            self, "选择输出路径", default_path or self.output_dir)
        if folder:
            if folder.startswith(self.output_dir):
                rel = os.path.relpath(folder, self.output_dir)
                self.pdf_path_edit.setText("" if rel == "." else rel)
            else:
                self.pdf_path_edit.setText(folder)
            self._save_settings()
    def _open_pdf_path(self):
        """在资源管理器中打开当前 PDF 输出目录（留空=默认输出目录）。"""
        path = self.pdf_path_edit.text().strip()
        if not path:
            path = self.output_dir
        elif not os.path.isabs(path):
            path = os.path.join(self.output_dir, path)
        os.makedirs(path, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self._show_tip("无法打开目录", path)

    # ---- PDF 抓页与导出 ----
    def _pdf_capture_image(self):
        """抓取一页：批量会话中追加到当前 exporter，否则单页立即导出。

        返回 True/False 供快捷键路由判断成功与否（播放提示音）。
        """
        try:
            if not self.pdf_region and not self.pdf_window_hwnd:
                self._show_tip("请先选择截图区域", "点击「全屏页面」/「框选页面」，或「选择窗口」")
                return False
            from capture.capture import is_window_valid
            if self.pdf_window_hwnd and not is_window_valid(self.pdf_window_hwnd):
                self._show_tip("所选窗口已关闭", "请重新选择应用窗口")
                return False
            output_file = self._pdf_output_file()
            output_dir = os.path.dirname(output_file)
            if not os.access(os.path.dirname(output_dir), os.W_OK):
                self._show_tip("输出路径没有写入权限", output_file)
                return False
            if self.pdf_batch_mode and self.pdf_exporter:
                self.pdf_capture_count += 1
                temp_file = self.pdf_exporter.capture(self.pdf_capture_count)
                if temp_file:
                    self.pdf_status_label.setText(
                        f"状态: 批量模式已截取 {self.pdf_capture_count} 页")
                    return True
                else:
                    self.pdf_capture_count -= 1
                    self.pdf_status_label.setText("状态: 截图失败")
                    return False
            else:
                if self._pdf_exporting:
                    self._show_tip("正在导出 PDF", "请稍候…")
                    return False
                temp_folder = self._pdf_temp_folder()
                self.pdf_exporter = PDFExporter(self.pdf_region, output_file, temp_folder, window_hwnd=self.pdf_window_hwnd)
                self.pdf_exporter.exported.connect(self._on_pdf_exported)
                self.pdf_capture_count = 0
                self.pdf_capture_count += 1
                temp_file = self.pdf_exporter.capture(self.pdf_capture_count)
                if not temp_file:
                    self.pdf_status_label.setText("状态: 截图失败")
                    self._show_tip("截图失败", "请检查权限或空间")
                    return False
                self.pdf_status_label.setText("状态: 处理中...")
                self._start_pdf_export(self.pdf_exporter)
                return True
        except Exception as e:
            self.pdf_status_label.setText("状态: PDF 截取失败")
            self._show_tip("PDF 截取失败", str(e))
            return False
    def _on_pdf_exported(self, output_file):
        """PDFExporter.exported 信号（单页导出直接路径回传）。"""
        try:
            if output_file and os.path.exists(output_file):
                self.pdf_status_label.setText("状态: 已完成")
                self._show_tip("PDF 生成完成", output_file)
            else:
                self.pdf_status_label.setText("状态: 生成失败")
        except Exception as e:
            self._show_tip("PDF 导出回调出错", str(e))
    def _start_pdf_batch_capture(self):
        """开始 PDF 批量会话：注册全局 Enter，此后在任意程序按 Enter 抓页。"""
        try:
            if self._pdf_exporting:
                self._show_tip("正在导出上一份 PDF", "请稍候再开始")
                return False
            if not self.pdf_region and not self.pdf_window_hwnd:
                self._show_tip("请先选择截图区域", "点击「全屏页面」/「框选页面」，或「选择窗口」")
                return False
            from capture.capture import is_window_valid
            if self.pdf_window_hwnd and not is_window_valid(self.pdf_window_hwnd):
                self._show_tip("所选窗口已关闭", "请重新选择应用窗口")
                return False
            output_file = self._pdf_output_file()
            output_dir = os.path.dirname(output_file)
            if not os.access(os.path.dirname(output_dir), os.W_OK):
                self._show_tip("输出路径没有写入权限", output_file)
                return False
            temp_folder = self._pdf_temp_folder()
            self.pdf_exporter = PDFExporter(self.pdf_region, output_file, temp_folder, window_hwnd=self.pdf_window_hwnd)
            self.pdf_exporter.exported.connect(self._on_pdf_exported)
            self.pdf_capture_count = 0
            self.pdf_batch_mode = True
            self._update_global_capture_hotkey()  # 注册全局 Enter
            self.pdf_manual_start_btn.setEnabled(False)
            self.pdf_manual_stop_btn.setEnabled(True)
            self.pdf_status_label.setText("状态: 批量模式已开始，请截取页面")
            self._show_tip("批量模式已开始",
                           "切到任意程序按 Enter 抓一页；停止后自动合成 PDF")
            return True
        except Exception as e:
            self._show_tip("开始 PDF 批量失败", str(e))
            return False
    def _stop_pdf_batch_capture(self):
        """停止 PDF 批量会话：注销全局 Enter，合成 PDF。"""
        try:
            if not self.pdf_batch_mode:
                return False
            capture_count = self.pdf_capture_count
            self.pdf_batch_mode = False
            self._update_global_capture_hotkey()  # 注销全局 Enter
            if capture_count > 0:
                self.pdf_status_label.setText("状态: 生成 PDF 中...")
                self.pdf_manual_start_btn.setEnabled(False)
                self.pdf_manual_stop_btn.setEnabled(False)
                if self.pdf_exporter:
                    self._start_pdf_export(self.pdf_exporter)
            else:
                self.pdf_status_label.setText("状态: 批量截图已取消")
                self.pdf_manual_start_btn.setEnabled(True)
                self.pdf_manual_stop_btn.setEnabled(False)
                self.setFocus()  # 归还焦点，避免焦点残留按钮导致 Enter 误触发
                if self.pdf_exporter:
                    try:
                        self.pdf_exporter.cleanup()
                    except Exception:
                        pass
            return True
        except Exception as e:
            self._show_tip("停止 PDF 批量失败", str(e))
            self.pdf_batch_mode = False
            self._update_global_capture_hotkey()
            self.pdf_manual_start_btn.setEnabled(True)
            self.pdf_manual_stop_btn.setEnabled(False)
            return False
    def _start_pdf_recording(self):
        """开始 PDF 自动连拍。"""
        try:
            if self._pdf_exporting:
                self._show_tip("正在导出上一份 PDF", "请稍候再开始")
                return False
            if not self.pdf_region and not self.pdf_window_hwnd:
                self._show_tip("请先选择截图区域", "点击「全屏页面」/「框选页面」，或「选择窗口」")
                return False
            from capture.capture import is_window_valid
            if self.pdf_window_hwnd and not is_window_valid(self.pdf_window_hwnd):
                self._show_tip("所选窗口已关闭", "请重新选择应用窗口")
                return False
            output_file = self._pdf_output_file()
            output_dir = os.path.dirname(output_file)
            if not os.access(os.path.dirname(output_dir), os.W_OK):
                self._show_tip("输出路径没有写入权限", output_file)
                return False
            temp_folder = self._pdf_temp_folder()
            self.pdf_exporter = PDFExporter(self.pdf_region, output_file, temp_folder, window_hwnd=self.pdf_window_hwnd)
            self.pdf_exporter.exported.connect(self._on_pdf_exported)
            self.pdf_capture_count = 0
            interval_ms = int(max(0.1, self.pdf_interval_spin.value()) * 1000)
            self.is_pdf_recording = True
            self.pdf_auto_start_btn.setEnabled(False)
            self.pdf_auto_stop_btn.setEnabled(True)
            self.pdf_status_label.setText("状态: 自动连拍中...")
            self.pdf_timer = QTimer(self)
            self.pdf_timer.timeout.connect(self._auto_pdf_capture)
            self.pdf_timer.start(interval_ms)
            self._show_tip("开始自动连拍", f"每 {self.pdf_interval_spin.value():g} 秒抓一页")
            return True
        except Exception as e:
            self._show_tip("开始自动连拍失败", str(e))
            self.is_pdf_recording = False
            self.pdf_auto_start_btn.setEnabled(True)
            self.pdf_auto_stop_btn.setEnabled(False)
            self.pdf_status_label.setText("状态: 就绪")
            return False
    def _auto_pdf_capture(self):
        if not self.is_pdf_recording:
            return
        try:
            self.pdf_capture_count += 1
            temp_file = self.pdf_exporter.capture(self.pdf_capture_count)
            if temp_file:
                self.pdf_status_label.setText(
                    f"状态: 自动连拍中... ({self.pdf_capture_count})")
            else:
                self.pdf_capture_count -= 1
                self.pdf_status_label.setText(
                    f"状态: 自动连拍中... ({self.pdf_capture_count}) (部分失败)")
        except Exception as e:
            tracelog.error(f"[PDF页] 自动截图出错: {e}")
            self.pdf_capture_count = max(0, self.pdf_capture_count - 1)
            self.pdf_status_label.setText(
                f"状态: 自动连拍中... ({self.pdf_capture_count}) (错误)")
    def _stop_pdf_recording(self):
        if not self.is_pdf_recording:
            return False
        try:
            self.pdf_timer.stop()
            self.is_pdf_recording = False
            self.pdf_auto_start_btn.setEnabled(False)  # 导出中禁用
            self.pdf_auto_stop_btn.setEnabled(False)
            self.pdf_status_label.setText("状态: 生成 PDF 中...")
            if self.pdf_exporter:
                self._start_pdf_export(self.pdf_exporter)
            return True
        except Exception as e:
            self._show_tip("停止自动连拍失败", str(e))
            self.is_pdf_recording = False
            if self.pdf_timer:
                self.pdf_timer.stop()
            self.pdf_auto_start_btn.setEnabled(True)
            self.pdf_auto_stop_btn.setEnabled(False)
            self.pdf_status_label.setText("状态: 已停止")
            return False

    # ---- 后台导出（多线程，避免阻塞界面） ----
    def _start_pdf_export(self, exporter):
        """后台启动 PDF 导出（OCR 按开关可选），带状态锁与进度回传。"""
        if self._pdf_exporting:
            self._show_tip("正在导出 PDF", "请稍候…")
            return
        ocr_on = getattr(self.settings_page, "auto_ocr_switch", None)
        ocr_enabled = bool(ocr_on and ocr_on.isChecked())
        if ocr_enabled and not self._check_ocr_model():
            self._show_tip("OCR 模型不可用", "本次导出不包含文字层")
            ocr_enabled = False
        self._pdf_exporting = True
        default_workers = max(1, (os.cpu_count() or 4) // 2)
        self._pdf_export_worker = PDFExportWorker(
            exporter, ocr_enabled=ocr_enabled,
            max_workers=default_workers,
            model_dir=self._ocr_model_dir())
        self._pdf_export_worker.progress.connect(self._on_pdf_progress)
        self._pdf_export_worker.finished.connect(self._on_pdf_export_done)
        self._pdf_export_worker.failed.connect(self._on_pdf_failed)
        label = "正在导出 PDF（含 OCR）…" if ocr_enabled else "正在导出 PDF…"
        self.pdf_status_label.setText(f"状态: {label}")
        self.pdf_progress_bar.setValue(0)
        self._pdf_export_worker.start()
    def _on_pdf_progress(self, cur, total):
        self.pdf_status_label.setText(f"状态: 正在导出 PDF… 第 {cur}/{total} 页")
        if total > 0:
            self.pdf_progress_bar.setValue(int(cur * 100 / total))
    def _cleanup_legacy_temp_dirs(self):
        """清理输出目录下历史残留的空 temp_* 目录（旧版 PDF 临时文件夹遗留）。

        只删「temp_ 前缀 + 空目录」的我们自己的残留，不影响用户文件。
        """
        try:
            for name in os.listdir(self.output_dir):
                if name.startswith("temp_"):
                    p = os.path.join(self.output_dir, name)
                    if os.path.isdir(p):
                        try:
                            os.rmdir(p)  # 仅空目录可删；非空则跳过
                        except OSError:
                            pass
        except OSError:
            pass

    def _on_pdf_export_done(self, pdf_path, ok):
        self._cleanup_legacy_temp_dirs()  # 顺带清旧版残留的空 temp_* 目录
        self._pdf_exporting = False
        self.pdf_progress_bar.setValue(100 if ok else 0)
        if ok and pdf_path and os.path.exists(pdf_path):
            self.pdf_status_label.setText("状态: 已完成")
            self._show_tip("PDF 生成完成", pdf_path)
        else:
            self.pdf_status_label.setText("状态: PDF 生成失败")
            self._show_tip("PDF 生成失败", "请检查权限或空间")
        self.pdf_manual_start_btn.setEnabled(True)
        self.pdf_manual_stop_btn.setEnabled(False)
        self.pdf_auto_start_btn.setEnabled(True)
        self.pdf_auto_stop_btn.setEnabled(False)
        self.setFocus()  # 归还焦点，避免焦点残留按钮导致 Enter 误触发
    def _on_pdf_failed(self, msg):
        self._cleanup_legacy_temp_dirs()  # 顺带清旧版残留的空 temp_* 目录
        self._pdf_exporting = False
        self.pdf_status_label.setText("状态: PDF 导出出错")
        self._show_tip("PDF 导出出错", msg)
        # 复位全部控制按钮，保证失败后能再次开始（否则全禁用死锁）
        self.pdf_manual_start_btn.setEnabled(True)
        self.pdf_manual_stop_btn.setEnabled(False)
        self.pdf_auto_start_btn.setEnabled(True)
        self.pdf_auto_stop_btn.setEnabled(False)
        self.setFocus()

    # ---------------- 导航栏右键管理 ----------------

    def _pick_pdf_window(self):
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
        self.pdf_window_hwnd = int(hwnd)
        self.pdf_window_title = title
        self.pdf_region = None
        self.pdf_region_status.setText("当前区域: 窗口「%s」 %dx%d" % (title, w, h))
        self._show_tip("已选择窗口", "%s (%dx%d)" % (title, w, h))
        return True
