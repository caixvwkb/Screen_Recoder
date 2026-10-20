# -*- coding: utf-8 -*-
"""ScreenRecorder AI 工作站页控制器（页面构建 + 页面业务逻辑）。

工作站是主程序的一个子页面（导航项），与 video/image/pdf/ocr/asr 页同构：
- 本模块提供 AiPageMixin，MainWindow 多继承装配，_build_ai_page(page) 构建页面
- 业务逻辑在 workstation/core（模型客户端 / vLLM 管理 / 检索 / 会话）
- 能力在 workstation/capabilities（file_io / ocr / asr / terminal / search）
- OCR / ASR 能力直接复用本项目现有引擎（同项目 import，不跨项目）
"""
from PySide6.QtWidgets import (QVBoxLayout, QWidget, QHBoxLayout, QTextEdit,
                               QListWidget, QPushButton, QLineEdit)
from qfluentwidgets import (FluentIcon, PushButton, PrimaryPushButton,
                            BodyLabel, CaptionLabel, HorizontalSeparator)
from ui.widgets import TwoRowCard


class AiPageMixin(object):
    def _build_ai_page(self, page):
        """AI 工作站页：vLLM 对话 + 能力调用 + 检索 + 文件产出。

        迁移自「本地 AI 工作站」设计（vLLM 独立进程，OpenAI 兼容 SSE 流式，
        DeepSeek-R1-Distill-Qwen-7B-AWQ；识图/语音复用本项目 OCR/ASR 引擎）。
        """
        self.ai_page = page
        self._ai_processing = False

        # —— 块① 模型与状态 ——
        status_card = page.block_cards["模型状态"]
        self.ai_status_label = CaptionLabel("vLLM：未启动")
        status_card.add_control(self.ai_status_label)

        # —— 块② 对话 ——
        chat_card = page.block_cards["对话"]
        self.ai_output = QTextEdit()
        self.ai_output.setReadOnly(True)
        chat_card.add_control(self.ai_output)

        self.ai_input = QTextEdit()
        self.ai_input.setPlaceholderText("输入指令（可引用下方参考文件）…")
        self.ai_input.setMaximumHeight(80)
        chat_card.add_control(self.ai_input)

        send_row = QHBoxLayout()
        self.ai_send_btn = PrimaryPushButton("发送")
        self.ai_send_btn.clicked.connect(self._ai_send)
        send_row.addWidget(self.ai_send_btn)
        send_row.addStretch(1)
        chat_card.add_control(send_row)

        # —— 块③ 能力与文件（后续迭代） ——
        tool_card = page.block_cards["能力与文件"]
        tool_card.add_control(BodyLabel("识图 / 语音转写 / 终端 / 库检索：后续迭代实现"))

    # ---------- 业务 ----------
    def _ai_send(self):
        """发送对话请求（骨架占位，后续接入 workstation.core.ModelClient）。"""
        self.ai_status_label.setText("vLLM：对话发送（待实现 model_client）")
