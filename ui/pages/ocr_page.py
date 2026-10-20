# -*- coding: utf-8 -*-
import tracelog
import os
"""ScreenRecorder 2.2 OCR 识别页控制器（页面构建 + 页面业务逻辑）。

迁移自 mainwindow_fluent.py：页面方法按功能页拆分到 ui/pages/，
MainWindow 通过多继承装配各 Mixin；跨页公共能力（模型检查 / 设置持久化 /
提示 / 数值输入框 QSS）仍在 MainWindow 中提供，此处经 self 调用。
"""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QVBoxLayout, QWidget,
                               QFileDialog, QSpinBox, QDoubleSpinBox, QProgressBar,
                               QListWidget, QListWidgetItem)
from PySide6.QtGui import QDesktopServices, QGuiApplication, QColor
from qfluentwidgets import (FluentIcon, PushButton, PrimaryPushButton,
                            SwitchButton, ComboBox, LineEdit, BodyLabel,
                            CaptionLabel, HorizontalSeparator)
from ui.widgets import TwoRowCard
from export_worker import FolderOcrWorker


class OcrPageMixin(object):
    def _build_ocr_page(self, page):
        """OCR 识别页（第 4 页）：选择文件夹 → 批量识别图片/PDF → 每文件一个说明.md。

        迁移自旧版 mainwindow.py _create_folder_ocr_tab：
        - 识别源（文件夹选择 + 扫描范围：子文件夹 / 含 PDF）
        - 识别设置（并发数 / 合并图片为一个 md）——模型路径集中在全局设置页
        - 识别控制（开始识别 + 状态行：状态 + 进度条）
        """
        self.ocr_page = page
        self._folder_ocr_processing = False
        self._folder_ocr_worker = None

        # —— 块① 识别源 ——
        src_card = page.block_cards["识别源"]

        # 识别文件夹：输入框 + 选择… + 打开（与散图/PDF 页目录卡同构）
        self.ocr_folder_edit = LineEdit()
        self.ocr_folder_edit.setPlaceholderText("选择要识别的文件夹（内含图片或 PDF）")
        self.ocr_folder_edit.setClearButtonEnabled(True)
        self.ocr_folder_edit.editingFinished.connect(self._save_settings)
        self.ocr_folder_btn = PushButton("选择…")
        self.ocr_folder_btn.setMinimumWidth(72)
        self.ocr_folder_btn.clicked.connect(self._choose_ocr_folder)
        self.ocr_folder_open_btn = PushButton("打开")
        self.ocr_folder_open_btn.setMinimumWidth(72)
        self.ocr_folder_open_btn.clicked.connect(self._open_ocr_folder)
        folder_card = TwoRowCard(
            FluentIcon.FOLDER, "识别文件夹",
            "选择包含图片（png/jpg/jpeg/bmp/webp）或 PDF 的文件夹；「打开」在资源管理器显示")
        folder_card.add_control(self.ocr_folder_edit, 1)
        folder_card.add_control(self.ocr_folder_btn)
        folder_card.add_control(self.ocr_folder_open_btn)
        folder_card.controls.addSpacing(16)
        src_card.addGroupWidget(folder_card)

        # 扫描范围：子文件夹 / 含 PDF
        self.ocr_recursive_switch = SwitchButton("包含子文件夹")
        self.ocr_recursive_switch.setChecked(True)
        self.ocr_recursive_switch.checkedChanged.connect(self._save_settings)
        self.ocr_pdf_switch = SwitchButton("包含 PDF 文件")
        self.ocr_pdf_switch.setChecked(True)
        self.ocr_pdf_switch.checkedChanged.connect(self._save_settings)
        scan_card = TwoRowCard(
            FluentIcon.EMBED, "扫描范围",
            "「包含子文件夹」递归扫描子目录；「包含 PDF 文件」同时识别 PDF（扫描件自动逐页渲染后识别）")
        scan_card.add_control(self.ocr_recursive_switch)
        scan_card.add_control(self.ocr_pdf_switch)
        scan_card.controls.addStretch(1)
        src_card.addGroupWidget(scan_card)

        # 任务清单：展示每个文件状态（待处理/处理中/已完成），已完成自动跳过
        list_wrap = QWidget()
        list_v = QVBoxLayout(list_wrap)
        list_v.setContentsMargins(8, 8, 8, 8)
        list_v.setSpacing(4)
        list_v.addWidget(BodyLabel("任务清单（已完成自动跳过 · 可随时取消）"))
        self.ocr_file_list = QListWidget()
        self.ocr_file_list.setMaximumHeight(150)
        list_v.addWidget(self.ocr_file_list)
        src_card.addGroupWidget(list_wrap)
        self._ocr_list_items = {}

        # —— 块② 识别设置 ——
        set_card = page.block_cards["识别设置"]

        # 并发数：多线程并行识别（每线程独立引擎）
        self.ocr_concurrency_spin = QSpinBox()
        self.ocr_concurrency_spin.setRange(1, 16)
        self.ocr_concurrency_spin.setValue(min(4, max(1, (os.cpu_count() or 4) // 2)))
        self.ocr_concurrency_spin.setToolTip(
            "同时运行几个 OCR 引擎（并行识别）。\n"
            "每引擎占用 1 个 CPU 核，并行数越大越快、但越占 CPU/内存。\n"
            "建议不超过 CPU 核数一半；识别大文件夹时若发现电脑卡顿请调小。")
        self.ocr_concurrency_spin.valueChanged.connect(self._save_settings)
        self._apply_num_qss(self.ocr_concurrency_spin)
        conc_card = TwoRowCard(
            FluentIcon.SETTING, "并发数", "同时运行几个 OCR 引擎并行识别；越大越快但越占 CPU/内存（建议≤CPU 核数一半）")
        conc_card.add_control(BodyLabel("并发数:"))
        conc_card.add_control(self.ocr_concurrency_spin)
        conc_card.controls.addStretch(1)
        set_card.addGroupWidget(conc_card)

        # 合并输出：图片合并为一个 md
        self.ocr_merge_switch = SwitchButton("合并图片为一个 md 文件")
        self.ocr_merge_switch.setChecked(True)
        self.ocr_merge_switch.checkedChanged.connect(self._save_settings)
        merge_card = TwoRowCard(
            FluentIcon.VIEW, "合并输出",
            "勾选：所有图片识别结果汇总成一个 <文件夹名>_图片说明.md（PDF 仍各自生成）；\n"
            "不勾选：每个文件单独生成一个 <文件名>_说明.md；\n"
            "注意：合并模式无单文件中间结果，取消/中断后重新开始会重新识别全部图片")
        merge_card.add_control(self.ocr_merge_switch)
        merge_card.controls.addStretch(1)
        set_card.addGroupWidget(merge_card)

        # —— 块③ 识别控制 ——
        ctrl_card = page.block_cards["识别控制"]

        self.ocr_start_btn = PrimaryPushButton("开始识别")
        self.ocr_start_btn.setMinimumWidth(120)
        self.ocr_start_btn.clicked.connect(lambda: self._run_with_sound(self._start_folder_ocr))
        start_card = TwoRowCard(
            FluentIcon.PLAY, "批量识别",
            "后台扫描并识别文件夹内的图片/PDF，逐文件生成说明文本；识别期间可切换页面操作")
        start_card.add_control(self.ocr_start_btn)
        self.ocr_stop_btn = PushButton("取消")
        self.ocr_stop_btn.setMinimumWidth(72)
        self.ocr_stop_btn.setEnabled(False)
        self.ocr_stop_btn.clicked.connect(self._stop_folder_ocr)
        start_card.add_control(self.ocr_stop_btn)
        start_card.controls.addStretch(1)
        ctrl_card.addGroupWidget(start_card)

        # 状态行（与视频/散图/PDF 页同构：第三块内最后一行）
        status_row = QHBoxLayout()
        status_row.setContentsMargins(8, 4, 8, 4)
        self.ocr_status_label = CaptionLabel("状态: 就绪")
        status_row.addWidget(self.ocr_status_label)
        status_row.addStretch(1)
        self.ocr_progress_bar = QProgressBar()
        self.ocr_progress_bar.setRange(0, 1)
        self.ocr_progress_bar.setValue(0)
        self.ocr_progress_bar.setFixedSize(160, 12)
        self._apply_progress_qss()
        status_row.addWidget(self.ocr_progress_bar)
        ctrl_status_widget = QWidget()
        ctrl_status_widget.setLayout(status_row)
        ctrl_card.addGroupWidget(ctrl_status_widget)

        # 恢复持久化设置
        self._load_ocr_page_settings()
    def _load_ocr_page_settings(self):
        settings = self.settings_manager.load()
        if "ocr_folder" in settings:
            self.ocr_folder_edit.setText(str(settings["ocr_folder"]))
        if "ocr_recursive" in settings:
            self.ocr_recursive_switch.setChecked(bool(settings["ocr_recursive"]))
        if "ocr_pdf" in settings:
            self.ocr_pdf_switch.setChecked(bool(settings["ocr_pdf"]))
        if "ocr_merge" in settings:
            self.ocr_merge_switch.setChecked(bool(settings["ocr_merge"]))
        if "ocr_concurrency" in settings:
            try:
                self.ocr_concurrency_spin.setValue(int(settings["ocr_concurrency"]))
            except (TypeError, ValueError):
                pass
    def _choose_ocr_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择要识别的文件夹",
            self.ocr_folder_edit.text() or self.app_data_dir)
        if folder:
            self.ocr_folder_edit.setText(folder)
            self._save_settings()
    def _open_ocr_folder(self):
        path = (self.ocr_folder_edit.text() or "").strip()
        if not path or not os.path.isdir(path):
            self._show_tip("打开文件夹", "先选择有效文件夹，再点「打开」在资源管理器显示")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    def _start_folder_ocr(self):
        """开始批量 OCR：扫描文件夹 → 后台逐文件识别 → 每文件生成说明.md"""
        try:
            if self._folder_ocr_processing:
                return False
            folder = self.ocr_folder_edit.text().strip()
            if not folder or not os.path.isdir(folder):
                self._show_tip("警告", "请先选择有效文件夹！")
                return False

            from folder_ocr import scan_folder, is_ocred
            files = scan_folder(
                folder,
                recursive=self.ocr_recursive_switch.isChecked(),
                include_pdf=self.ocr_pdf_switch.isChecked(),
            )
            if not files:
                self._show_tip("提示", "该文件夹内没有可识别的图片或 PDF 文件。")
                return False

            # OCR 模型检查：显式指定路径无效时明确提示
            if not self._check_ocr_model():
                return False

            # 未完成重传：时间标签识别已完成的文件（说明.md 存在且新于源文件），自动跳过
            out_dir = self._ocr_asr_out_dir(folder)
            pending = [f for f in files if not is_ocred(f, out_dir)]
            self._populate_ocr_list(files, pending, out_dir)
            if not pending:
                self._show_tip("提示", f"全部 {len(files)} 个文件已完成识别，无需处理")
                return False
            skipped = len(files) - len(pending)

            # 后台处理，不阻塞界面
            self._folder_ocr_processing = True
            self.ocr_start_btn.setEnabled(False)
            self.ocr_stop_btn.setEnabled(True)
            self.ocr_progress_bar.setRange(0, len(pending))
            self.ocr_progress_bar.setValue(0)
            self.ocr_status_label.setText(
                f"状态: 识别中… 0/{len(pending)}"
                + (f"（已完成 {skipped} 个不重复）" if skipped else ""))
            # 待处理全部标记为「处理中」，完成一个变绿
            self._mark_ocr_pending_processing()
            self._folder_ocr_worker = FolderOcrWorker(
                pending, folder,
                merge_images=self.ocr_merge_switch.isChecked(),
                max_workers=self.ocr_concurrency_spin.value(),
                model_dir=self._ocr_model_path("cpu"),
                out_dir=out_dir)
            self._folder_ocr_worker.progress.connect(self._on_folder_ocr_progress)
            self._folder_ocr_worker.finished.connect(self._on_folder_ocr_done)
            self._folder_ocr_worker.failed.connect(self._on_folder_ocr_failed)
            self._folder_ocr_worker.start()
            self._show_tip("开始识别",
                           f"处理 {len(pending)} 个文件"
                           + (f"，已完成 {skipped} 个不重复" if skipped else ""))
            return True
        except Exception as e:
            tracelog.error(f"[OCR页] 开始文件夹 OCR 出错: {e}")
            self._folder_ocr_processing = False
            self.ocr_start_btn.setEnabled(True)
            self._show_tip("错误", f"开始识别失败: {e}")
            return False
    def _on_folder_ocr_progress(self, cur, total, name):
        self.ocr_progress_bar.setValue(cur)
        self.ocr_status_label.setText(f"状态: 识别中… {cur}/{total}（{name}）")
        self._update_ocr_list_status(name, "已完成", "#3fb950")
    def _on_folder_ocr_done(self, md_count, fail_count):
        self._folder_ocr_processing = False
        self.ocr_start_btn.setEnabled(True)
        self.ocr_stop_btn.setEnabled(False)
        remaining = 0
        if self._folder_ocr_worker:
            remaining = getattr(self._folder_ocr_worker, "last_remaining", 0) or 0
        self.ocr_progress_bar.setValue(self.ocr_progress_bar.maximum())
        msg = f"状态: 完成（生成 {md_count} 个说明文件"
        if fail_count:
            msg += f"，失败 {fail_count} 个"
        if remaining:
            if self.ocr_merge_switch.isChecked():
                msg += f"，未处理 {remaining} 个；合并模式重新开始将全部重新识别"
            else:
                msg += f"，未处理 {remaining} 个（重新开始重新处理）"
        msg += "）"
        self.ocr_status_label.setText(msg)
        tip = f"生成 {md_count} 个说明文件"
        if fail_count:
            tip += f"，失败 {fail_count} 个"
        if remaining:
            if self.ocr_merge_switch.isChecked():
                tip += f"，合并模式重新开始将全部重新识别"
            else:
                tip += f"，未处理 {remaining} 个可重新处理"
        self._show_tip("识别完成", tip)
    def _on_folder_ocr_failed(self, msg):
        self._folder_ocr_processing = False
        self.ocr_start_btn.setEnabled(True)
        self.ocr_stop_btn.setEnabled(False)
        self.ocr_status_label.setText("状态: 识别出错")
        tracelog.error(f"[OCR页] 文件夹 OCR 出错: {msg}")
        self._show_tip("错误", f"OCR 识别出错: {msg}")
    def _populate_ocr_list(self, files, pending, out_dir):
        """填充任务清单：已完成（时间标签识别）绿色，待处理灰色。"""
        pending_names = {os.path.basename(f) for f in pending}
        self.ocr_file_list.clear()
        self._ocr_list_items = {}
        for f in files:
            name = os.path.basename(f)
            done = name not in pending_names
            item = QListWidgetItem(f"{name} —— {'已完成' if done else '待处理'}")
            item.setForeground(QColor("#3fb950" if done else "#808080"))
            self.ocr_file_list.addItem(item)
            self._ocr_list_items[name] = item

    def _mark_ocr_pending_processing(self):
        """开始识别后：清单中待处理项全部标记为「处理中」（蓝色）。"""
        for name, item in self._ocr_list_items.items():
            if "待处理" in item.text():
                item.setText(f"{name} —— 处理中")
                item.setForeground(QColor("#4a90d9"))

    def _update_ocr_list_status(self, name, status, color):
        item = self._ocr_list_items.get(name)
        if item is None:
            return
        item.setText(f"{name} —— {status}")
        item.setForeground(QColor(color))

    def _stop_folder_ocr(self):
        """取消批量识别：当前文件识别完退出，已完成文件保留输出。"""
        if not self._folder_ocr_worker:
            return
        self._folder_ocr_worker.stop()
        self.ocr_stop_btn.setEnabled(False)
        if self.ocr_merge_switch.isChecked():
            self.ocr_status_label.setText("状态: 正在取消…（合并模式：重新开始将全部重新识别）")
        else:
            self.ocr_status_label.setText("状态: 正在取消…（当前文件完成后退出，已完成保留）")
