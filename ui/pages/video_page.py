# -*- coding: utf-8 -*-
"""ScreenRecorder 2.2 视频录制页控制器（页面构建 + 页面业务逻辑）。

迁移自 mainwindow_fluent.py：页面方法按功能页拆分到 ui/pages/，
MainWindow 通过多继承装配各 Mixin；跨页公共能力（模型检查 / 设置持久化 /
提示 / 数值输入框 QSS）仍在 MainWindow 中提供，此处经 self 调用。
"""
import json
import os
import tracelog
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QUrl, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QWidget, QFileDialog,
                               QSpinBox, QDoubleSpinBox, QProgressBar)
from PySide6.QtGui import QDesktopServices, QGuiApplication
from qfluentwidgets import (FluentIcon, PushButton, PrimaryPushButton,
                            SwitchButton, ComboBox, LineEdit, BodyLabel,
                            CaptionLabel, HorizontalSeparator)
from ui.widgets import TwoRowCard
from capture import ScreenRecorder
from region_selector import SelectionWindow


class VideoPageMixin(object):
    def _build_video_page(self, page):

        """视频录制页：迁移旧版 region/output/control 三块（mainwindow.py 113-117 信号段）。

        层级：每块内使用标准 SettingCard（图标 + 标题 + 副标题 + 右侧控件）。
        """
        # 状态
        self.video_region = None
        self.video_window_hwnd = None   # 应用窗口捕获：目标窗口句柄（None=屏幕区域模式）
        self.is_video_recording = False
        self.video_recorder = None
        self.video_recording_start = None
        self.video_recording_timer = QTimer(self)
        self.video_recording_timer.timeout.connect(self._update_video_duration)
        self.video_page = page

        # —— 块① 录制区域（三个子功能：全屏 / 框选 / 应用窗口[占位]） ——
        region_card = page.block_cards["录制区域"]

        # ① 全屏录制：一键选整个主屏
        self.video_fullscreen_btn = PrimaryPushButton("选择全屏")
        self.video_fullscreen_btn.setMinimumWidth(96)
        self.video_fullscreen_btn.clicked.connect(lambda: self._run_with_sound(self._select_fullscreen_region))
        fullscreen_card = TwoRowCard(
            FluentIcon.FULL_SCREEN, "全屏录制", "捕获整个屏幕画面，无需框选")
        fullscreen_card.add_control(self.video_fullscreen_btn, 0, Qt.AlignLeft)
        region_card.addGroupWidget(fullscreen_card)

        # ② 框选录制：手动框选任意区域（现有功能）
        self.video_box_btn = PrimaryPushButton("框选范围")
        self.video_box_btn.setMinimumWidth(96)
        self.video_box_btn.clicked.connect(lambda: self._run_with_sound(self._select_video_region))
        box_card = TwoRowCard(
            FluentIcon.CUT, "框选录制", "手动框选屏幕上的任意区域")
        box_card.add_control(self.video_box_btn, 0, Qt.AlignLeft)
        region_card.addGroupWidget(box_card)

        # ③ 应用窗口捕获：选择运行中的应用窗口，捕获其真实画面（不被遮挡）
        self.video_window_btn = PrimaryPushButton("选择窗口")
        self.video_window_btn.setMinimumWidth(96)
        self.video_window_btn.clicked.connect(lambda: self._run_with_sound(self._pick_video_window))
        window_card = TwoRowCard(
            FluentIcon.APPLICATION, "应用窗口捕获",
            "捕获指定应用窗口画面，即使被其他画面遮挡也取窗口真实内容")
        window_card.add_control(self.video_window_btn, 0, Qt.AlignLeft)
        region_card.addGroupWidget(window_card)

        # 当前区域状态行
        region_status = QHBoxLayout()
        region_status.setContentsMargins(8, 4, 8, 4)
        self.video_region_status = CaptionLabel("当前区域: 未选择")
        region_status.addWidget(self.video_region_status)
        region_status.addStretch(1)
        status_widget = QWidget()
        status_widget.setLayout(region_status)
        region_card.addGroupWidget(status_widget)

        # —— 块② 视频参数 ——
        param_card = page.block_cards["视频参数"]

        # 视频格式：第二行 帧率 + 格式
        self.video_format_combo = ComboBox()
        for fmt in ("mp4", "avi", "mkv", "mov", "webm"):
            self.video_format_combo.addItem(fmt)
        self.video_format_combo.addItem("mp3（仅音频）", None, "mp3")
        self.video_format_combo.setFixedWidth(128)
        self.video_format_combo.currentTextChanged.connect(
            lambda _: self._save_settings())
        self.video_format_combo.currentIndexChanged.connect(
            lambda _: self._update_fps_visibility(animate=True))
        # 画质档位：24/30/60/120/144/240，语义档位代替帧率数字。
        # 超过显示器物理刷新率的档位自动禁用并标注（如 60Hz 屏禁 120/144/240，
        # 144Hz 屏禁 240）——高过屏幕上限的帧率只是重复帧，无意义。
        from PySide6.QtGui import QGuiApplication
        self.video_fps_combo = ComboBox()
        # 录制档位最高 60fps：60 以上档位（120/144/240）编码/抓帧瓶颈下
        # 音画同步难保证，且办公录屏用不到，已移除。
        self._video_fps_levels = [
            ("流畅（24fps）", 24), ("均衡（30fps）", 30), ("高清（60fps）", 60),
        ]
        for _i, (_label, _fps) in enumerate(self._video_fps_levels):
            self.video_fps_combo.addItem(_label, None, _fps)
        self.video_fps_combo.setCurrentIndex(1)  # 默认均衡 30fps
        self.video_fps_combo.setFixedWidth(128)
        self.video_fps_combo.currentIndexChanged.connect(lambda _: self._save_settings())

        # 画质控件组（「mp3（仅音频）」纯音频模式时无需帧率，做小动画隐藏）
        self.fps_label = BodyLabel("画质:")
        fps_widget = QWidget()
        fps_row = QHBoxLayout(fps_widget)
        fps_row.setContentsMargins(0, 0, 0, 0)
        fps_row.setSpacing(6)
        fps_row.addWidget(self.fps_label)
        fps_row.addWidget(self.video_fps_combo)
        self.fps_widget = fps_widget
        self.fps_anim = QPropertyAnimation(fps_widget, b"maximumHeight", self)
        self.fps_anim.setDuration(180)
        self.fps_anim.setEasingCurve(QEasingCurve.OutCubic)

        fmt_card = TwoRowCard(
            FluentIcon.VIDEO, "视频格式", "输出容器格式，自动决定文件扩展名")
        # 帧率组不固定高度（height=None），动画收起/展开才有效
        fmt_card.add_control(self.fps_widget, height=None)
        fmt_card.add_control(BodyLabel("格式:"))
        fmt_card.add_control(self.video_format_combo)
        fmt_card.controls.addStretch(1)
        param_card.addGroupWidget(fmt_card)

        # 输出目录：第二行 输入框 + 选择… + 打开
        self.video_path_edit = LineEdit()
        self.video_path_edit.setPlaceholderText("留空=默认输出目录")
        self.video_path_edit.setClearButtonEnabled(True)
        self.video_path_edit.setMinimumWidth(160)
        self.video_path_edit.editingFinished.connect(self._save_settings)
        self.video_path_btn = PushButton("选择…")
        self.video_path_btn.setMinimumWidth(72)
        self.video_path_btn.clicked.connect(self._browse_video_path)
        self.video_path_open_btn = PushButton("打开")
        self.video_path_open_btn.setMinimumWidth(72)
        self.video_path_open_btn.clicked.connect(self._open_video_path)

        dir_card = TwoRowCard(
            FluentIcon.FOLDER, "输出目录", "视频保存位置；「选择…」更换目录，「打开」在资源管理器显示")
        dir_card.add_control(self.video_path_edit, 1)
        dir_card.add_control(self.video_path_btn)
        dir_card.add_control(self.video_path_open_btn)
        dir_card.controls.addSpacing(16)  # 右侧安全间距
        param_card.addGroupWidget(dir_card)

        # 文件名
        self.video_name_edit = LineEdit()
        self.video_name_edit.setText("录制_视频")
        self.video_name_edit.setClearButtonEnabled(True)
        self.video_name_edit.setMinimumWidth(200)
        self.video_name_edit.editingFinished.connect(self._save_settings)
        name_card = TwoRowCard(
            FluentIcon.EDIT, "文件名", "输出文件名，自动补上扩展名")
        name_card.add_control(self.video_name_edit, 1)
        name_card.controls.addSpacing(16)
        param_card.addGroupWidget(name_card)

        # —— 音频设置（视频参数之后）：内录 / 麦克风 / MP3 纯音频 ——
        audio_card = page.block_cards["音频设置"]

        # ① 录制音频总开关
        self.video_audio_switch = SwitchButton()
        self.video_audio_switch.setChecked(False)
        self.video_audio_switch.checkedChanged.connect(self._on_video_audio_toggled)
        audio_switch_card = TwoRowCard(
            FluentIcon.VOLUME, "录制音频", "把系统声音 / 麦克风录进视频；「MP3（仅音频）」格式时自动只录音")
        audio_switch_card.add_control(self.video_audio_switch, 0, Qt.AlignLeft)
        audio_card.addGroupWidget(audio_switch_card)

        # ② 系统声音（内录）：按「正在发声的应用」选择（WASAPI 会话枚举）
        self.video_loopback_combo = ComboBox()
        self.video_loopback_combo.setMinimumWidth(280)
        self.video_loopback_combo.currentIndexChanged.connect(
            lambda _: self._save_settings())
        self.video_loopback_refresh_btn = PushButton(FluentIcon.SYNC, "刷新")
        self.video_loopback_refresh_btn.setMinimumWidth(80)
        self.video_loopback_refresh_btn.setToolTip("重新检测正在发声的应用")
        self.video_loopback_refresh_btn.clicked.connect(
            lambda: self._run_with_sound(self._refresh_loopback_sessions))
        loopback_row = QHBoxLayout()
        loopback_row.setContentsMargins(0, 0, 0, 0)
        loopback_row.setSpacing(8)
        loopback_row.addWidget(self.video_loopback_combo, 1)
        loopback_row.addWidget(self.video_loopback_refresh_btn)
        loopback_widget = QWidget()
        loopback_widget.setLayout(loopback_row)
        loopback_card = TwoRowCard(
            FluentIcon.VOLUME, "系统声音（内录）", "选择正在发声的应用，自动捕获它所在输出设备的声音；找不到应用时点「刷新」重新检测")
        loopback_card.add_control(loopback_widget, 1)
        audio_card.addGroupWidget(loopback_card)

        # ③ 麦克风 / 外部输入
        self.video_mic_combo = ComboBox()
        self.video_mic_combo.setFixedWidth(280)
        self.video_mic_combo.currentIndexChanged.connect(
            lambda _: self._save_settings())
        mic_card = TwoRowCard(
            FluentIcon.MICROPHONE, "麦克风 / 外部输入", "麦克风或线路输入（如立体声混音）；与内录同时选 = 混音录制")
        mic_card.add_control(self.video_mic_combo, 1)
        audio_card.addGroupWidget(mic_card)


        # 设备/会话枚举（启动时读取；未安装 soundcard / 无设备时给出提示并禁用）
        self._video_audio_sources = self._enumerate_audio_devices()
        self._refresh_loopback_sessions()
        self._fill_audio_combo(self.video_mic_combo, "mic")
        self._on_video_audio_toggled(self.video_audio_switch.isChecked())

        # —— 块③ 录制控制 ——
        ctrl_card = page.block_cards["录制控制"]
        self.video_start_btn = PrimaryPushButton("开始录制")
        self.video_start_btn.setMinimumWidth(104)
        self.video_start_btn.clicked.connect(lambda: self._run_with_sound(self._start_video_recording))
        self.video_stop_btn = PushButton("停止录制")
        self.video_stop_btn.setMinimumWidth(104)
        self.video_stop_btn.setEnabled(False)
        self.video_stop_btn.clicked.connect(lambda: self._run_with_sound(self._stop_video_recording))
        self.video_control_card = TwoRowCard(
            FluentIcon.PLAY, "录制控制", "开始录制到所选区域，可随时停止")
        self.video_control_card.add_control(self.video_stop_btn)
        self.video_control_card.add_control(self.video_start_btn)
        self.video_control_card.controls.addStretch(1)
        ctrl_card.addGroupWidget(self.video_control_card)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 4, 0, 0)
        self.video_status_label = CaptionLabel("状态: 就绪")
        status_row.addWidget(self.video_status_label)
        status_row.addStretch(1)
        self.video_duration_label = CaptionLabel("已录制: 00:00:00")
        status_row.addWidget(self.video_duration_label)
        ctrl_status_widget = QWidget()
        ctrl_status_widget.setLayout(status_row)
        ctrl_card.addGroupWidget(ctrl_status_widget)

    # ---- 视频录制逻辑（迁移自 mainwindow.py select_region / start/stop_recording） ----
    def _select_fullscreen_region(self):
        """一键选择整个主屏作为录制区域（同时退出窗口捕获模式）。"""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self._show_tip("无法获取屏幕", "未检测到主屏幕")
            return False
        geo = screen.geometry()
        self.video_region = (geo.x(), geo.y(), geo.width(), geo.height())
        self._clear_window_capture_mode()
        self.video_region_status.setText(
            f"当前区域: 全屏 {geo.width()}x{geo.height()}")
        self._show_tip("已选择全屏", f"录制区域: {geo.width()}x{geo.height()}")
        return True
    def _clear_window_capture_mode(self):
        """退出窗口捕获模式：清空窗口句柄/标题，恢复窗口按钮文字。
        否则残留的 window_hwnd 会让开始录制时仍走窗口预检而失败。"""
        self.video_window_hwnd = None
        self.video_window_title = ""
        self.video_window_btn.setText("选择窗口")
    def _select_video_region(self):
        self.hide()
        self._selection_window = SelectionWindow()
        self._selection_window.selection_completed.connect(self._on_video_region_done)
        self._selection_window.selection_canceled.connect(self._on_video_region_cancel)
        self._selection_window.show()
        return True
    def _on_video_region_done(self, region):
        x, y, width, height = region
        self.video_region = (x, y, width, height)
        self._clear_window_capture_mode()
        self.video_region_status.setText(f"当前区域: ({x}, {y}) {width}x{height}")
        self.show()
    def _on_video_region_cancel(self):
        self.show()
        if not self.video_region:
            self.video_region_status.setText("当前区域: 未选择")
    def _video_output_path(self):
        """拼接视频输出完整路径（相对路径基于默认输出目录）。"""
        path = self.video_path_edit.text().strip()
        if not path:
            path = self.output_dir
        elif not os.path.isabs(path):
            path = os.path.join(self.output_dir, path)
        os.makedirs(path, exist_ok=True)
        name = self.video_name_edit.text().strip() or "录制_视频"
        fmt = self.video_format_combo.currentData() or self.video_format_combo.currentText()
        return os.path.join(path, f"{name}.{fmt}")

    # ---------------- 帧率可见性（mp3 纯音频模式隐藏） ----------------

    def _update_fps_visibility(self, animate: bool = True):
        """「mp3（仅音频）」时收起帧率控件组（小动画）；否则展开。

        用 maximumHeight 动画控制：收起时高度压到 0（布局中不占空间即视觉隐藏），
        展开时恢复到控件自然高度。不调用 hide()/show()，避免动画完成信号重复连接。
        """
        if not hasattr(self, "fps_widget"):
            return
        is_mp3 = (self.video_format_combo.currentData() == "mp3")
        target_h = 0 if is_mp3 else self.fps_widget.sizeHint().height()
        if animate:
            self.fps_anim.stop()
            self.fps_anim.setStartValue(self.fps_widget.height())
            self.fps_anim.setEndValue(target_h)
            self.fps_anim.start()
        else:
            self.fps_anim.stop()
            self.fps_widget.setMaximumHeight(target_h)

    # ---------------- 音频设置（内录 / 麦克风 / MP3 纯音频） ----------------

    def _enumerate_audio_devices(self):
        """枚举音频来源；返回 {'loopback': [...], 'mic': [...]}，失败为空结构。"""
        from audio_capture import list_audio_sources
        return list_audio_sources()

    def _fill_audio_combo(self, combo, kind: str):
        """按设备列表填充下拉（麦克风/外部输入用）：空项「无（不录）」+ 各设备（id 作 data）。"""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("无（不录）", "")
        devices = self._video_audio_sources.get(kind, [])
        for dev in devices:
            combo.addItem(dev["name"], None, dev["id"])
        if not devices:
            combo.setEnabled(False)
            combo.setToolTip("未检测到设备（soundcard 未安装或无可用设备）")
        combo.blockSignals(False)

    def _refresh_loopback_sessions(self):
        """重新检测正在发声的应用并填充内录下拉（保留当前选择）。

        data 为 JSON：{"pid":…, "proc":进程名, "dev":输出设备名}；
        录制时按设备名匹配 soundcard loopback（get_microphone 支持按名匹配）。
        """
        from audio_sessions import list_active_sessions
        sessions = list_active_sessions()
        cur = self.video_loopback_combo.currentData()
        self.video_loopback_combo.blockSignals(True)
        self.video_loopback_combo.clear()
        self.video_loopback_combo.addItem("无（不录）", "")
        for s in sessions:
            proc = s["process_name"]
            dev = s["device_name"]
            label = (s.get("display_name") or "").strip() or proc
            data = json.dumps(
                {"pid": s["pid"], "proc": proc, "dev": dev}, ensure_ascii=False)
            self.video_loopback_combo.addItem(f"{label} · {dev}", None, data)
        if not sessions:
            self.video_loopback_combo.setToolTip(
                "当前没有检测到正在发声的应用：打开播放声音的程序后点「刷新」")
        else:
            self.video_loopback_combo.setToolTip(
                "列表只显示正在发声的应用；新程序发声后点「刷新」更新")
        if cur:
            idx = self.video_loopback_combo.findData(cur)
            if idx >= 0:
                self.video_loopback_combo.setCurrentIndex(idx)
        self.video_loopback_combo.setEnabled(self.video_audio_switch.isChecked())
        self.video_loopback_combo.blockSignals(False)
        return True

    def _on_video_audio_toggled(self, checked: bool):
        """录制音频开关：控制来源下拉可用性并保存。"""
        self.video_loopback_combo.setEnabled(checked)
        self.video_mic_combo.setEnabled(checked)
        self._save_settings()

    def _collect_audio_sources(self) -> list:
        """收集当前选中的音频来源，返回 [] 表示不录音。

        内录项为会话 JSON → 输出设备名（soundcard 按名匹配 loopback）；
        麦克风项为设备 id。两者可同时选中 = 混音录制。
        """
        sources = []
        lb = self.video_loopback_combo.currentData()
        if lb:
            try:
                info = json.loads(lb)
                dev = info.get("dev")
                if dev:
                    sources.append({"kind": "loopback", "device_id": dev})
            except Exception:
                pass
        mic = self.video_mic_combo.currentData()
        if mic:
            sources.append({"kind": "mic", "device_id": mic})
        return sources

    def _current_video_format(self) -> str:
        """实际输出格式值（mp3（仅音频）→ mp3）。"""
        return self.video_format_combo.currentData() or self.video_format_combo.currentText()
    def _browse_video_path(self):
        default_path = self.video_path_edit.text().strip()
        if default_path and not os.path.isabs(default_path):
            default_path = os.path.join(self.output_dir, default_path)
        folder = QFileDialog.getExistingDirectory(
            self, "选择输出路径", default_path or self.output_dir)
        if folder:
            if folder.startswith(self.output_dir):
                rel = os.path.relpath(folder, self.output_dir)
                self.video_path_edit.setText("" if rel == "." else rel)
            else:
                self.video_path_edit.setText(folder)
            self._save_settings()
    def _open_video_path(self):
        """在资源管理器中打开当前输出目录。"""
        path = self.video_path_edit.text().strip()
        if not path:
            path = self.output_dir
        elif not os.path.isabs(path):
            path = os.path.join(self.output_dir, path)
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    def _recorder_guard(self) -> bool:
        """录制守护开关（默认开；设置页存在时读开关状态）。"""
        try:
            return bool(getattr(self.settings_page, "recorder_guard_switch", None)
                        and self.settings_page.recorder_guard_switch.isChecked())
        except Exception:
            return True

    def _start_video_recording(self):
        from capture import is_window_valid
        fmt = self._current_video_format()
        is_mp3 = (fmt == "mp3")
        if not is_mp3 and not self.video_region and not self.video_window_hwnd:
            self._show_tip("请先选择录制区域", "框选屏幕范围，或「选择窗口」指定应用窗口")
            return False
        if self.video_window_hwnd and not is_window_valid(self.video_window_hwnd):
            self._show_tip("所选窗口已关闭", "请重新选择应用窗口")
            return False
        if self.video_window_hwnd:
            # 预检：PrintWindow 取不到内容的窗口（独占全屏/硬件加速渲染）直接提示，
            # 避免"开始录制"后才因抓帧失败中断；并给「改用全屏录制」一键折中入口
            from capture import capture_window_by_hwnd_np
            if capture_window_by_hwnd_np(self.video_window_hwnd) is None:
                self._show_window_capture_fallback()
                return False
        try:
            audio_sources = [] if not is_mp3 and not self.video_audio_switch.isChecked() \
                else self._collect_audio_sources()
            if is_mp3 and not audio_sources:
                self._show_tip("请选择音频来源", "MP3 仅音频模式需要至少选择一个音频来源")
                return False
            output_file = self._video_output_path()
            fps = self.video_fps_combo.currentData() or 20
            if not os.access(os.path.dirname(os.path.dirname(output_file)), os.W_OK):
                self._show_tip("输出路径没有写入权限", output_file)
                return False
            self.video_recorder = ScreenRecorder(
                self.video_region, output_file, fps,
                window_hwnd=self.video_window_hwnd,
                audio_sources=audio_sources,
                audio_only=is_mp3,
                guard=self._recorder_guard())
            self.video_recorder.finished.connect(self._on_video_finished)
            self._video_finish_handled = False
            self.is_video_recording = True
            self.video_recording_start = datetime.now()
            self.video_start_btn.setEnabled(False)
            self.video_stop_btn.setEnabled(True)
            self.video_fullscreen_btn.setEnabled(False)
            self.video_box_btn.setEnabled(False)
            self.video_window_btn.setEnabled(False)
            self.video_status_label.setText("状态: 录音中..." if is_mp3 else "状态: 录制中...")
            self.video_duration_label.setText("已录制: 00:00:00")
            self.video_recording_timer.start(1000)
            self.video_recorder.start()
            self._show_tip("开始录制", f"输出: {output_file}")
            return True
        except Exception as e:
            self._show_tip("开始录制失败", str(e))
            self.is_video_recording = False
            self.video_start_btn.setEnabled(True)
            self.video_stop_btn.setEnabled(False)
            self.video_fullscreen_btn.setEnabled(True)
            self.video_box_btn.setEnabled(True)
            self.video_status_label.setText("状态: 就绪")
            return False
    def _stop_video_recording(self):
        if not self.is_video_recording:
            return False
        try:
            if self.video_recorder:
                self.video_recorder.stop()
            self.is_video_recording = False
            self.video_recording_start = None
            self.video_recording_timer.stop()
            self.video_start_btn.setEnabled(True)
            self.video_stop_btn.setEnabled(False)
            self.video_fullscreen_btn.setEnabled(True)
            self.video_box_btn.setEnabled(True)
            self.video_window_btn.setEnabled(True)
            self.video_status_label.setText("状态: 已停止")
            self.setFocus()  # 归还焦点，避免焦点残留按钮导致 Enter 误触发
            return True
        except Exception as e:
            self._show_tip("停止录制失败", str(e))
            return False
    def _update_video_duration(self):
        if self.is_video_recording and self.video_recording_start:
            elapsed = datetime.now() - self.video_recording_start
            h, rem = divmod(int(elapsed.total_seconds()), 3600)
            m, s = divmod(rem, 60)
            self.video_duration_label.setText(f"已录制: {h:02d}:{m:02d}:{s:02d}")
            # 录制守护：录制线程意外死亡（异常/被系统回收）但标志未复位 → 自动复位
            rec = self.video_recorder
            if rec and rec.recording_thread and not rec.recording_thread.is_alive() \
                    and not getattr(self, "_video_finish_handled", False):
                self._video_finish_handled = True
                try:
                    tracelog.error("[守护] 录制线程意外终止，已自动复位状态（可重新开始录制）")
                except Exception:
                    pass
                self._on_video_finished()
    def _on_video_finished(self):
        """录制自然结束/异常退出：完整复位状态，保证可再次开始（否则按钮全灰卡死）。"""
        try:
            self._video_finish_handled = True
            self.is_video_recording = False
            self.video_recording_start = None
            try:
                self.video_recording_timer.stop()
            except Exception:
                pass
            self.video_start_btn.setEnabled(True)
            self.video_stop_btn.setEnabled(False)
            self.video_fullscreen_btn.setEnabled(True)
            self.video_box_btn.setEnabled(True)
            self.video_window_btn.setEnabled(True)
            self.setFocus()  # 归还焦点，避免焦点残留按钮导致 Enter 误触发
            output_file = self._video_output_path()
            if os.path.exists(output_file):
                self.video_status_label.setText("状态: 已停止")
                self._show_tip("录制完成", f"已保存: {output_file}")
            else:
                self.video_status_label.setText("状态: 就绪")
                self._show_tip("录制已停止", f"文件未保存成功？预期路径: {output_file}")
        except Exception as e:
            self._show_tip("录制完成回调出错", str(e))

    # ---------------- 散图录制页 ----------------

    def _pick_video_window(self):
        """选择要捕获的应用窗口（PrintWindow 抓取，被遮挡也取真实内容）。"""
        from ui.widgets import WindowPickerDialog
        from capture import is_window_valid
        res = WindowPickerDialog.pick(self)
        if not res:
            return False
        hwnd, title, w, h = res
        if not is_window_valid(hwnd):
            self._show_tip("窗口无效", "所选窗口已关闭，请重新选择")
            return False
        self.video_window_hwnd = int(hwnd)
        self.video_window_title = title
        self.video_region = None
        self.video_region_status.setText("当前区域: 窗口「%s」 %dx%d" % (title, w, h))
        self._show_tip("已选择窗口", "%s (%dx%d)" % (title, w, h))
        return True

    # ---------------- 窗口捕获失败 → 改用全屏录制（折中入口） ----------------

    def _show_window_capture_fallback(self):
        """窗口（如 osu 显卡渲染/独占全屏）取不到内容时，提示并提供一键改全屏。"""
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition, PushButton
            from PySide6.QtCore import Qt
            bar = InfoBar.warning(
                "窗口无法捕获",
                "所选窗口可能是显卡渲染或独占全屏（如 osu），取不到画面内容；"
                "可改用「全屏录制」继续",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=6000, parent=self)
            btn = PushButton("改用全屏录制")
            btn.clicked.connect(self._fallback_fullscreen_recording)
            bar.addAction(btn)
            bar.show()
        except Exception:
            # 提示组件异常时退回普通提示，保证入口不丢失
            self._show_tip("窗口无法捕获",
                           "所选窗口可能已关闭，或是独占全屏/硬件加速渲染（取不到内容），请重新选择")

    def _fallback_fullscreen_recording(self):
        """放弃窗口模式，切换为全屏录制并直接开始。"""
        try:
            self.video_window_hwnd = None
            self.video_window_title = ""
            self.video_window_btn.setText("选择窗口")
            self._select_fullscreen_region()
            # 窗口模式残留的状态文字立即更新
            self.video_region_status.setText(
                f"当前区域: 全屏 {self.video_region[2]}x{self.video_region[3]}")
            self._start_video_recording()
        except Exception as e:
            tracelog.error(f"[录制] 改用全屏失败: {e}")
            self._show_tip("切换全屏失败", str(e))
