# -*- coding: utf-8 -*-
import tracelog
import os
"""ScreenRecorder 2.2 ASR 识别页控制器（页面构建 + 页面业务逻辑）。

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
from export_worker import ASRWorker


class AsrPageMixin(object):
    def _build_asr_page(self, page):
        """ASR 识别页（第 5 页）：选择文件夹 → 批量语音转写音频/视频 → 每文件一个转写.txt。

        迁移自旧版 mainwindow.py _create_asr_tab：
        - 识别源（文件夹选择 + 扫描范围：子文件夹 / 处理格式白名单）
        - 识别设置（并发数 / 模型与自动化说明——语音模型路径与视频自动转写开关集中在设置页）
        - 识别控制（开始识别 + 状态行）
        """
        self.asr_page = page
        self._folder_asr_processing = False
        self._folder_asr_worker = None

        # —— 块① 识别源 ——
        src_card = page.block_cards["识别源"]

        # 识别文件夹：输入框 + 选择… + 打开
        self.asr_folder_edit = LineEdit()
        self.asr_folder_edit.setPlaceholderText("选择包含音频/视频的文件夹（wav/mp3/m4a/flac/mp4 等）")
        self.asr_folder_edit.setClearButtonEnabled(True)
        self.asr_folder_edit.editingFinished.connect(self._save_settings)
        self.asr_folder_btn = PushButton("选择…")
        self.asr_folder_btn.setMinimumWidth(72)
        self.asr_folder_btn.clicked.connect(self._choose_asr_folder)
        self.asr_folder_open_btn = PushButton("打开")
        self.asr_folder_open_btn.setMinimumWidth(72)
        self.asr_folder_open_btn.clicked.connect(self._open_asr_folder)
        folder_card = TwoRowCard(
            FluentIcon.FOLDER, "识别文件夹",
            "选择包含音频或视频的文件夹；逐文件转写为文字并生成 <文件名>_语音转写.txt")
        folder_card.add_control(self.asr_folder_edit, 1)
        folder_card.add_control(self.asr_folder_btn)
        folder_card.add_control(self.asr_folder_open_btn)
        folder_card.controls.addSpacing(16)
        src_card.addGroupWidget(folder_card)

        # 扫描范围：子文件夹 / 处理格式白名单
        self.asr_recursive_switch = SwitchButton("包含子文件夹")
        self.asr_recursive_switch.setChecked(True)
        self.asr_recursive_switch.checkedChanged.connect(self._save_settings)
        self.asr_formats_edit = LineEdit()
        self.asr_formats_edit.setText("wav,mp3,m4a,flac,ogg,mp4,mkv,avi,mov,webm")
        self.asr_formats_edit.setMinimumWidth(220)
        self.asr_formats_edit.setToolTip(
            "只处理列出的音频/视频格式，其余文件自动跳过（正向白名单）。\n"
            "逗号分隔，不带点。例如：wav,mp3,m4a,mp4")
        self.asr_formats_edit.editingFinished.connect(self._save_settings)
        scan_card = TwoRowCard(
            FluentIcon.EMBED, "扫描范围",
            "「包含子文件夹」递归扫描子目录；「处理格式」为白名单：只转写列出的格式，其余自动跳过")
        scan_card.add_control(self.asr_recursive_switch)
        scan_card.controls.addSpacing(12)
        scan_card.add_control(BodyLabel("处理格式:"))
        scan_card.add_control(self.asr_formats_edit)
        scan_card.controls.addStretch(1)
        src_card.addGroupWidget(scan_card)

        # 任务清单：展示每个文件状态（待处理/处理中/已完成），已完成自动跳过
        list_wrap = QWidget()
        list_v = QVBoxLayout(list_wrap)
        list_v.setContentsMargins(8, 8, 8, 8)
        list_v.setSpacing(4)
        list_v.addWidget(BodyLabel("任务清单（已完成自动跳过 · 可随时取消）"))
        self.asr_file_list = QListWidget()
        self.asr_file_list.setMaximumHeight(150)
        list_v.addWidget(self.asr_file_list)
        src_card.addGroupWidget(list_wrap)
        self._asr_list_items = {}

        # —— 块② 识别设置 ——
        set_card = page.block_cards["识别设置"]

        # 并发数
        self.asr_concurrency_spin = QSpinBox()
        self.asr_concurrency_spin.setRange(1, 8)
        self.asr_concurrency_spin.setValue(min(4, max(1, (os.cpu_count() or 4) // 2)))
        self.asr_concurrency_spin.setToolTip(
            "同时转写几个文件（并行）。\n"
            "每路占用 1 个 CPU 核，并行数越大越快、但越占 CPU/内存。\n"
            "建议不超过 CPU 核数一半。")
        self.asr_concurrency_spin.valueChanged.connect(self._save_settings)
        self._apply_num_qss(self.asr_concurrency_spin)
        conc_card = TwoRowCard(
            FluentIcon.SETTING, "并发数", "同时转写几个文件（每路独立识别器）；越大越快但越占 CPU/内存（建议≤CPU 核数一半）")
        conc_card.add_control(BodyLabel("并发数:"))
        conc_card.add_control(self.asr_concurrency_spin)
        conc_card.controls.addStretch(1)
        set_card.addGroupWidget(conc_card)

        # 模型与自动化说明卡（模型路径/视频自动转写开关集中在设置页）
        info_card = TwoRowCard(
            FluentIcon.INFO, "模型与自动化",
            "语音模型路径（SenseVoice，models/asr/）与「视频自动语音转写」开关在左下「设置」页统一配置")
        set_card.addGroupWidget(info_card)

        # —— 块③ 识别控制 ——
        ctrl_card = page.block_cards["识别控制"]

        self.asr_start_btn = PrimaryPushButton("开始识别")
        self.asr_start_btn.setMinimumWidth(120)
        self.asr_start_btn.clicked.connect(lambda: self._run_with_sound(self._start_folder_asr))
        start_card = TwoRowCard(
            FluentIcon.PLAY, "批量转写",
            "后台扫描并逐文件转写音频/视频为文字；wav/flac/ogg/mp3 直接解码，m4a/视频自动用内置 ffmpeg 转码")
        start_card.add_control(self.asr_start_btn)
        self.asr_stop_btn = PushButton("取消")
        self.asr_stop_btn.setMinimumWidth(72)
        self.asr_stop_btn.setEnabled(False)
        self.asr_stop_btn.clicked.connect(self._stop_folder_asr)
        start_card.add_control(self.asr_stop_btn)
        start_card.controls.addStretch(1)
        ctrl_card.addGroupWidget(start_card)

        # 状态行（与其它页同构：第三块内最后一行）
        status_row = QHBoxLayout()
        status_row.setContentsMargins(8, 4, 8, 4)
        self.asr_status_label = CaptionLabel("状态: 待命")
        status_row.addWidget(self.asr_status_label)
        status_row.addStretch(1)
        self.asr_progress_bar = QProgressBar()
        self.asr_progress_bar.setRange(0, 1)
        self.asr_progress_bar.setValue(0)
        self.asr_progress_bar.setFixedSize(160, 12)
        self._apply_progress_qss()
        status_row.addWidget(self.asr_progress_bar)
        ctrl_status_widget = QWidget()
        ctrl_status_widget.setLayout(status_row)
        ctrl_card.addGroupWidget(ctrl_status_widget)

        # 恢复持久化设置
        self._load_asr_page_settings()
    def _load_asr_page_settings(self):
        settings = self.settings_manager.load()
        if "asr_folder" in settings:
            self.asr_folder_edit.setText(str(settings["asr_folder"]))
        if "asr_recursive" in settings:
            self.asr_recursive_switch.setChecked(bool(settings["asr_recursive"]))
        if "asr_formats" in settings:
            self.asr_formats_edit.setText(str(settings["asr_formats"]))
        if "asr_concurrency" in settings:
            try:
                self.asr_concurrency_spin.setValue(int(settings["asr_concurrency"]))
            except (TypeError, ValueError):
                pass
    def _choose_asr_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择包含音频/视频的文件夹",
            self.asr_folder_edit.text() or self.app_data_dir)
        if folder:
            self.asr_folder_edit.setText(folder)
            self._save_settings()
    def _open_asr_folder(self):
        path = (self.asr_folder_edit.text() or "").strip()
        if not path or not os.path.isdir(path):
            self._show_tip("打开文件夹", "先选择有效文件夹，再点「打开」在资源管理器显示")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    def _start_folder_asr(self):
        """开始批量 ASR：扫描文件夹（处理格式白名单）→ 后台逐文件转写 → 生成转写.md"""
        try:
            if self._folder_asr_processing:
                return False
            folder = self.asr_folder_edit.text().strip()
            if not folder or not os.path.isdir(folder):
                self._show_tip("警告", "请先选择有效文件夹！")
                return False

            # 处理格式白名单（正向过滤）
            formats = [x.strip().lower().lstrip(".")
                       for x in self.asr_formats_edit.text().split(",") if x.strip()]
            if not formats:
                self._show_tip("警告", "请填写要处理的格式（如 wav,mp3,mp4）！")
                return False

            from asr import scan_asr_files, is_transcribed
            files = scan_asr_files(folder, formats, recursive=self.asr_recursive_switch.isChecked())
            if not files:
                self._show_tip("提示", "该文件夹内没有可处理的音频/视频文件。")
                return False

            # ASR 模型检查：显式指定路径无效时明确提示
            if not self._check_asr_model():
                return False

            # 未完成重传：时间标签识别已完成的文件（输出 txt 存在且新于源文件），自动跳过
            out_dir = self._ocr_asr_out_dir(folder)
            pending = [f for f in files if not is_transcribed(f, out_dir)]
            self._populate_asr_list(files, pending, out_dir)
            if not pending:
                self._show_tip("提示", f"全部 {len(files)} 个文件已完成转写，无需处理")
                return False
            skipped = len(files) - len(pending)

            # 后台转写，不阻塞界面
            self._folder_asr_processing = True
            self.asr_start_btn.setEnabled(False)
            self.asr_stop_btn.setEnabled(True)
            self.asr_progress_bar.setRange(0, len(pending))
            self.asr_progress_bar.setValue(0)
            self.asr_status_label.setText(
                f"状态: 正在转写 {len(pending)} 个文件"
                + (f"（已完成 {skipped} 个不重复）" if skipped else "") + " …")
            self._folder_asr_worker = ASRWorker(
                pending,
                max_workers=self.asr_concurrency_spin.value(),
                model_dir=self._asr_model_dir(),
                out_dir=out_dir)
            self._folder_asr_worker.progress.connect(self._on_asr_progress)
            self._folder_asr_worker.finished.connect(self._on_asr_done)
            self._folder_asr_worker.failed.connect(self._on_asr_failed)
            self._folder_asr_worker.start()
            self._show_tip("开始转写",
                           f"处理 {len(pending)} 个文件"
                           + (f"，已完成 {skipped} 个不重复" if skipped else ""))
            return True
        except Exception as e:
            tracelog.error(f"[ASR页] 开始 ASR 转写出错: {e}")
            self._folder_asr_processing = False
            self.asr_start_btn.setEnabled(True)
            self._show_tip("错误", f"开始 ASR 转写失败: {e}")
            return False
    def _on_asr_progress(self, done, total, name, seg_done, seg_total):
        """双进度：进度条=文件进度；状态文字=全局段进度（自增）+ 当前文件。"""
        self.asr_progress_bar.setRange(0, total)
        self.asr_progress_bar.setValue(done)
        if seg_done > 0 and seg_total > 0:
            self.asr_status_label.setText(
                f"状态: 段 {seg_done}/{seg_total} · {name}")
            self._update_asr_list_status(name, "处理中", "#4a90d9")
        else:
            self.asr_status_label.setText(f"状态: {name} 完成")
            self._update_asr_list_status(name, "已完成", "#3fb950")
            self._show_tip("转写完成", f"{name} 完成")
    def _on_asr_done(self, md_count, fail_count):
        self._folder_asr_processing = False
        self.asr_start_btn.setEnabled(True)
        self.asr_stop_btn.setEnabled(False)
        remaining = 0
        if self._folder_asr_worker:
            remaining = getattr(self._folder_asr_worker, "last_remaining", 0) or 0
        msg = f"状态: 完成，生成 {md_count} 份转写文档"
        if fail_count:
            msg += f"，失败 {fail_count} 个"
        if remaining:
            msg += f"，未处理 {remaining} 个（重新开始重新处理）"
        self.asr_status_label.setText(msg)
        tip = f"生成 {md_count} 份转写文档"
        if fail_count:
            tip += f"，失败 {fail_count} 个"
        if remaining:
            tip += f"，未处理 {remaining} 个可重新处理"
        self._show_tip("转写完成", tip)
    def _on_asr_failed(self, msg):
        self._folder_asr_processing = False
        self.asr_start_btn.setEnabled(True)
        self.asr_stop_btn.setEnabled(False)
        self.asr_status_label.setText("状态: 转写出错")
        tracelog.error(f"[ASR页] ASR 转写出错: {msg}")
        self._show_tip("错误", f"ASR 转写出错: {msg}")
    def _populate_asr_list(self, files, pending, out_dir):
        """填充任务清单：已完成（时间标签识别）灰绿标注，待处理默认色。"""
        from asr import is_transcribed
        pending_names = {os.path.basename(f) for f in pending}
        self.asr_file_list.clear()
        self._asr_list_items = {}
        for f in files:
            name = os.path.basename(f)
            done = name not in pending_names
            item = QListWidgetItem(f"{name} —— {'已完成' if done else '待处理'}")
            item.setForeground(QColor("#3fb950" if done else "#808080"))
            self.asr_file_list.addItem(item)
            self._asr_list_items[name] = item

    def _update_asr_list_status(self, name, status, color):
        """更新清单中某文件状态（处理中/已完成）。"""
        item = self._asr_list_items.get(name)
        if item is None:
            return
        item.setText(f"{name} —— {status}")
        item.setForeground(QColor(color))

    def _stop_folder_asr(self):
        """停止批量转写：当前段识别完成后退出，已完成文件保留输出。"""
        if not self._folder_asr_worker:
            return
        self._folder_asr_worker.stop()
        self.asr_stop_btn.setEnabled(False)
        self.asr_status_label.setText("状态: 正在取消…（当前段完成后退出，已完成文件保留）")
