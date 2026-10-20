# -*- coding: utf-8 -*-
"""ScreenRecorder AI 工作站页控制器（v2：多配置 / 多项目 / 会话化折叠对话）。

结构：
- 页面副标题中性：代码 / 文档 / 科学问题 / 研究资料问答
- 块① 模型配置：多 profile 列表（加号添加、radio 单选当前、可删除），
  下方三字段编辑区（base_url / api_key / model），每框一行说明，无联网纠错
- 块② 本地项目：多项目勾选列表（勾选才参与检索注入；不勾 = 纯对话），
  加号选文件夹添加，删除，建索引按钮，算法后续完善
- 块③ 对话：会话下拉切换 / 新建 / 删除；轮次折叠（旧轮收成标题，点开展开）；
  底部输入框 + 发送/停止
- 持久化：workstation/config.json（api_profiles / active_profile /
  local_projects / conversations）
"""
import json
import os
import uuid
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QRadioButton,
                               QScrollArea, QTextBrowser, QVBoxLayout, QWidget,
                               QComboBox)
from qfluentwidgets import (LineEdit, PushButton, PrimaryPushButton, SwitchButton,
                            CaptionLabel, BodyLabel, FluentIcon, ComboBox)

from ui.widgets import TwoRowCard
from workstation.core.model_client import ModelClient
from workstation.core.searcher import Searcher


def _cfg_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")


def _load_cfg() -> dict:
    try:
        with open(_cfg_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cfg(cfg: dict) -> None:
    with open(_cfg_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _normalize_cfg(cfg: dict) -> dict:
    """兼容旧配置：把旧的单 api 段迁移为 api_profiles[0]。"""
    if "api_profiles" not in cfg:
        old = cfg.get("api", {}) or {}
        cfg["api_profiles"] = [{
            "name": "默认配置",
            "base_url": old.get("base_url", "https://api.deepseek.com"),
            "api_key": old.get("api_key", ""),
            "model": old.get("model", "deepseek-flash"),
        }]
        cfg.pop("api", None)
    cfg.setdefault("active_profile", 0)
    if "local_projects" not in cfg:
        roots = (cfg.get("searcher", {}) or {}).get("roots", [])
        cfg["local_projects"] = [{"path": r, "enabled": True} for r in roots]
    cfg.setdefault("conversations", [])
    return cfg


# ============ 流式对话线程（沿用 v1） ============
class ChatWorker(QThread):
    chunk_ready = Signal(str, bool)
    stream_finished = Signal(str)
    stream_error = Signal(str)

    def __init__(self, client: ModelClient, messages: list, sampling: dict, parent=None):
        super().__init__(parent)
        self._client = client
        self._messages = messages
        self._sampling = sampling
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        full = []
        try:
            for kind, t in self._client.chat_stream(self._messages, **self._sampling):
                if self._stop:
                    break
                if kind == "text":
                    full.append(t)
                self.chunk_ready.emit(t, kind == "reasoning")
            self.stream_finished.emit("".join(full))
        except Exception as e:
            self.stream_error.emit(str(e))


class AiPageMixin(object):

    # ---------------- 页面构建 ----------------
    def _build_ai_page(self, page):
        self.ai_page = page
        self._ai_worker = None
        self._ai_busy = False
        self._ai_cfg = _normalize_cfg(_load_cfg())

        # 页面副标题改中性（HeaderCard subtitle）
        try:
            header = page.findChild(QWidget)
            for lab in page.findChildren(QLabel):
                if "服务器 AI 对话" in (lab.text() or ""):
                    lab.setText("AI 对话助手 · 代码 / 文档 / 科学问题 · 可挂接本地研究库检索")
                    break
        except Exception:
            pass

        self._build_ai_config_block(page)
        self._build_ai_tools_block(page)
        self._build_ai_projects_block(page)
        self._build_ai_chat_block(page)

    # ===== 块① 模型配置：多 profile =====
    def _build_ai_config_block(self, page):
        cfg_card = page.block_cards["模型配置"]

        # 列表卡
        list_card = TwoRowCard(
            FluentIcon.FOLDER, "配置列表",
            "保存多套 API 配置（官方云端 / 本地服务），点选一条即切换为当前使用；下面编辑区跟着切")
        self.ai_profile_list = QListWidget()
        self.ai_profile_list.setMaximumHeight(100)
        list_card.add_control(self.ai_profile_list, 1, height=None)
        self.ai_profile_list.currentRowChanged.connect(self._ai_on_profile_select)
        cfg_card.addGroupWidget(list_card)

        # 操作按钮卡
        op_card = TwoRowCard(FluentIcon.EDIT, "添加 / 删除", "新增一套空白配置，或删掉选中的那套")
        add_btn = PushButton("+ 添加配置")
        add_btn.clicked.connect(self._ai_add_profile)
        op_card.add_control(add_btn)
        del_btn = PushButton("删除当前配置")
        del_btn.clicked.connect(self._ai_del_profile)
        op_card.add_control(del_btn)
        op_card.controls.addStretch(1)
        cfg_card.addGroupWidget(op_card)

        # ① URL 卡
        url_card = TwoRowCard(
            FluentIcon.SETTING, "① 服务端点 URL",
            "填官方文档给的 base_url：DeepSeek 填 https://api.deepseek.com（不要加 /v1）；"
            "本地服务（Ollama/vLLM）填 http://127.0.0.1:8000/v1")
        self.ai_base_url_edit = LineEdit()
        self.ai_base_url_edit.setPlaceholderText("https://api.deepseek.com")
        url_card.add_control(self.ai_base_url_edit, 1)
        cfg_card.addGroupWidget(url_card)

        # ② 密钥卡
        key_card = TwoRowCard(
            FluentIcon.EMBED, "② API 密钥",
            "去官方平台申请的 sk- 开头密钥（DeepSeek 在 platform.deepseek.com 申请）；本地服务不需要，留空")
        self.ai_api_key_edit = LineEdit()
        self.ai_api_key_edit.setEchoMode(QLineEdit.Password)
        self.ai_api_key_edit.setPlaceholderText("sk-...（本地服务留空）")
        key_card.add_control(self.ai_api_key_edit, 1)
        cfg_card.addGroupWidget(key_card)

        # ③ 模型卡
        mdl_card = TwoRowCard(
            FluentIcon.ROBOT, "③ 模型名称（严格名）",
            "必须是官方文档列出的模型严格名，不是自己起的名字：DeepSeek 填 deepseek-flash 或 deepseek-v4-pro；"
            "填错会报 400 invalid model")
        self.ai_model_edit = LineEdit()
        self.ai_model_edit.setPlaceholderText("deepseek-flash")
        mdl_card.add_control(self.ai_model_edit, 1)
        save_btn = PrimaryPushButton("保存当前配置")
        save_btn.clicked.connect(self._ai_save_profile)
        mdl_card.add_control(save_btn)
        mdl_card.controls.addStretch(1)
        cfg_card.addGroupWidget(mdl_card)

        self._ai_reload_profile_list()

    def _ai_profiles(self) -> list:
        return self._ai_cfg.get("api_profiles", [])

    def _ai_reload_profile_list(self):
        self.ai_profile_list.blockSignals(True)
        self.ai_profile_list.clear()
        for i, p in enumerate(self._ai_profiles()):
            it = QListWidgetItem(f"{i + 1}. {p.get('name', '未命名')}")
            self.ai_profile_list.addItem(it)
        act = self._ai_cfg.get("active_profile", 0)
        self.ai_profile_list.setCurrentRow(act if act < len(self._ai_profiles()) else 0)
        self.ai_profile_list.blockSignals(False)
        self._ai_on_profile_select(self.ai_profile_list.currentRow())

    def _ai_on_profile_select(self, row: int):
        if row < 0 or row >= len(self._ai_profiles()):
            return
        p = self._ai_profiles()[row]
        self.ai_base_url_edit.setText(p.get("base_url", ""))
        self.ai_api_key_edit.setText(p.get("api_key", ""))
        self.ai_model_edit.setText(p.get("model", ""))
        self._ai_cfg["active_profile"] = row

    def _ai_add_profile(self):
        self._ai_profiles().append({
            "name": f"配置 {len(self._ai_profiles()) + 1}",
            "base_url": "", "api_key": "", "model": ""})
        self._ai_reload_profile_list()
        self.ai_profile_list.setCurrentRow(len(self._ai_profiles()) - 1)

    def _ai_del_profile(self):
        row = self.ai_profile_list.currentRow()
        if 0 <= row < len(self._ai_profiles()):
            self._ai_profiles().pop(row)
            self._ai_cfg["active_profile"] = 0
            _save_cfg(self._ai_cfg)
            self._ai_reload_profile_list()

    def _ai_save_profile(self):
        row = self.ai_profile_list.currentRow()
        if row < 0:
            return
        p = self._ai_profiles()[row]
        p["base_url"] = self.ai_base_url_edit.text().strip()
        p["api_key"] = self.ai_api_key_edit.text().strip()
        p["model"] = self.ai_model_edit.text().strip()
        self._ai_cfg["active_profile"] = row
        _save_cfg(self._ai_cfg)
        self.ai_status_label.setText(f"配置已保存：{p.get('name')}")

    # ===== 块② 工具箱：把外部内容写入 context.txt =====
    def _build_ai_tools_block(self, page):
        t_card = page.block_cards["工具箱"]
        op_card = TwoRowCard(
            FluentIcon.APPLICATION, "写入上下文",
            "把本地文件 / 剪贴板等内容写入当前会话的 context.txt，AI 下一轮就能看到")
        f_btn = PushButton("📄 读本地文件")
        f_btn.setToolTip("选一个文本文件，全文写入【功能写入: 文件: 路径】")
        f_btn.clicked.connect(self._ai_tool_read_file)
        op_card.add_control(f_btn)
        cb_btn = PushButton("📋 写入剪贴板")
        cb_btn.setToolTip("把当前剪贴板文本写入【功能写入: 剪贴板】")
        cb_btn.clicked.connect(self._ai_tool_clipboard)
        op_card.add_control(cb_btn)
        rf_btn = PushButton("🔄 刷新已写入的文件段")
        rf_btn.setToolTip("扫 context.txt 里所有【功能写入: 文件: ...】段，文件改过就全量替换")
        rf_btn.clicked.connect(self._ai_tool_refresh_files)
        op_card.add_control(rf_btn)
        op_card.controls.addStretch(1)
        t_card.addGroupWidget(op_card)

        # 角色设定：编辑框双向同步 context.txt 系统区的【系统设定】段
        from PySide6.QtWidgets import QPlainTextEdit
        role_card = TwoRowCard(
            FluentIcon.ROBOT, "角色设定",
            "编辑 AI 人设；失焦自动写入 context.txt 系统区，下次发送即生效")
        self.ai_role_edit = QPlainTextEdit()
        self.ai_role_edit.setPlaceholderText("你是严谨的嵌入式工程师与代码助手。")
        self.ai_role_edit.setMinimumHeight(70)
        self.ai_role_edit.setMaximumHeight(120)
        self.ai_role_edit.setPlainText(self._ai_load_role_from_context())
        self.ai_role_edit.focusOutEvent = lambda e: (
            QPlainTextEdit.focusOutEvent(self.ai_role_edit, e),
            self._ai_save_role_to_context())
        role_card.add_control(self.ai_role_edit, 1, height=None)
        t_card.addGroupWidget(role_card)

        # Tool-use 循环：启用后写入工具协议提示词，AI 可输出 ACTION 块让客户端执行命令
        tu_card = TwoRowCard(
            FluentIcon.CODE, "Tool-use 循环",
            '启用后 AI 可输出 [ACTION] 块让本地执行命令，形成"执行→回灌→再决策"循环')
        self.ai_tooluse_btn = PushButton("▶ 启用循环")
        self.ai_tooluse_btn.setCheckable(True)
        self.ai_tooluse_btn.toggled.connect(self._ai_on_tooluse_toggle)
        tu_card.add_control(self.ai_tooluse_btn)
        edit_tu_btn = PushButton("✏️ 编辑提示词")
        edit_tu_btn.setToolTip("打开 tool_use_prompt.txt 编辑工具协议提示词")
        edit_tu_btn.clicked.connect(self._ai_open_tooluse_prompt)
        tu_card.add_control(edit_tu_btn)
        open_tu_btn = PushButton("📂 配置文件")
        open_tu_btn.setToolTip("打开 workstation/tool_use_prompt.txt 所在目录")
        open_tu_btn.clicked.connect(self._ai_open_tooluse_dir)
        tu_card.add_control(open_tu_btn)
        tu_card.controls.addStretch(1)
        t_card.addGroupWidget(tu_card)

    def _ai_load_role_from_context(self) -> str:
        """从当前会话 context.txt 系统区读最新一段【系统设定】。"""
        conv = self._ai_active_conv()
        if not conv:
            return self._ai_cfg.get("system_prompt", "")
        p = self._ai_context_path(conv)
        if not os.path.exists(p):
            return self._ai_cfg.get("system_prompt", "")
        import re
        text = open(p, encoding="utf-8").read()
        parts = re.split(r"【([^】]+)】", text)
        last = ""
        i = 1
        while i + 1 < len(parts):
            if parts[i].strip().startswith("系统设定"):
                last = parts[i + 1].strip()
            i += 2
        return last or self._ai_cfg.get("system_prompt", "")

    def _ai_save_role_to_context(self):
        """把编辑框内容写入 context.txt 系统区（替换所有旧【系统设定】段）。"""
        conv = self._ai_active_conv()
        if not conv:
            return
        text = self.ai_role_edit.toPlainText().strip()
        if not text:
            return
        # 先把旧【系统设定】段全删掉，再写新的到系统区开头
        p = self._ai_context_path(conv)
        if os.path.exists(p):
            content = open(p, encoding="utf-8").read()
        else:
            content = "\n".join(self._AI_SECTIONS) + "\n"
        import re
        # 删除所有【系统设定】段
        content = re.sub(r"\n【系统设定】\n.*?(?=\n【|\n===|\Z)", "", content, flags=re.S)
        # 插入到系统区开头
        block = f"\n【系统设定】\n{text}\n"
        idx = content.find("=== 系统区 ===")
        if idx >= 0:
            end = content.find("\n", idx + len("=== 系统区 ==="))
            content = content[:end] + block + content[end:]
        else:
            content = block + content
        open(p, "w", encoding="utf-8").write(content)
        self._ai_cfg["system_prompt"] = text
        _save_cfg(self._ai_cfg)
        self.ai_status_label.setText("角色设定已写入上下文")

    def _ai_tool_read_file(self):
        conv = self._ai_active_conv()
        if not conv:
            self.ai_status_label.setText("请先新建会话")
            return
        path, _ = QFileDialog.getOpenFileName(
            self.ai_page, "选择要写入上下文的文件", "D:/",
            "文本文件 (*.txt *.md *.c *.h *.cpp *.hpp *.py *.s *.json *.csv *.log);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = self._ai_truncate(f.read())
        except Exception as e:
            self.ai_status_label.setText(f"读取失败: {e}")
            return
        # 标记文件路径 + 修改时间，刷新时用
        import os as _os
        mtime = _os.path.getmtime(path)
        self._ai_append_context(conv, f"功能写入: 文件: {path} (mtime={mtime:.0f})", f"```\n{content}\n```")
        self.ai_status_label.setText(f"已写入上下文：{_os.path.basename(path)}（{len(content)} 字符）")

    def _ai_tool_clipboard(self):
        conv = self._ai_active_conv()
        if not conv:
            self.ai_status_label.setText("请先新建会话")
            return
        text = QApplication.clipboard().text().strip()
        if not text:
            self.ai_status_label.setText("剪贴板为空")
            return
        self._ai_append_context(conv, "功能写入: 剪贴板", f"```\n{text}\n```")
        self.ai_status_label.setText(f"已写入剪贴板内容（{len(text)} 字符）")

    def _ai_tool_refresh_files(self):
        """扫 context.txt，把【功能写入: 文件: <path> (mtime=xxx)】段全量替换成最新文件内容。"""
        import re as _re
        conv = self._ai_active_conv()
        if not conv:
            return
        p = self._ai_context_path(conv)
        if not os.path.exists(p):
            self.ai_status_label.setText("本会话还没有 context.txt")
            return
        with open(p, "r", encoding="utf-8") as f:
            text = f.read()
        # 匹配所有文件段
        pat = _re.compile(r"【功能写入: 文件: (.+?) \(mtime=(\d+)\)】\n(.*?)(?=\n【|\Z)", _re.S)
        replaced = 0
        def _sub(m):
            nonlocal replaced
            fpath = m.group(1)
            old_mtime = int(m.group(2))
            if not os.path.exists(fpath):
                return m.group(0)
            new_mtime = int(os.path.getmtime(fpath))
            if new_mtime <= old_mtime:
                return m.group(0)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    new_content = self._ai_truncate(f.read())
                replaced += 1
                return f"【功能写入: 文件: {fpath} (mtime={new_mtime})】\n```\n{new_content}\n```"
            except Exception:
                return m.group(0)
        new_text = pat.sub(_sub, text)
        if replaced:
            with open(p, "w", encoding="utf-8") as f:
                f.write(new_text)
        self.ai_status_label.setText(f"刷新完成：更新了 {replaced} 个文件段")

    # ===== 块③ 本地项目：多项目勾选（自适应行高） =====
    def _build_ai_projects_block(self, page):
        r_card = page.block_cards["文件清单"]

        # 项目列表卡：每行一个勾选项，加几个文件夹就长几行，不滚动
        list_card = TwoRowCard(
            FluentIcon.FOLDER, "项目列表",
            "勾选的项目在每次提问时自动检索相关内容并注入 prompt；一个都不勾 = 纯对话，不做本地检索")
        self.ai_proj_container = QWidget()
        self.ai_proj_layout = QVBoxLayout(self.ai_proj_container)
        self.ai_proj_layout.setContentsMargins(4, 4, 4, 4)
        self.ai_proj_layout.setSpacing(4)
        list_card.add_control(self.ai_proj_container, 1, height=None)
        r_card.addGroupWidget(list_card)

        # 操作按钮卡
        op_card = TwoRowCard(FluentIcon.EDIT, "添加 / 建索引", "把项目文件夹加进来，或把文件清单写入上下文")
        add_btn = PushButton("+ 添加项目文件夹")
        add_btn.clicked.connect(self._ai_add_project)
        op_card.add_control(add_btn)
        idx_btn = PushButton("建立/刷新索引")
        idx_btn.clicked.connect(self._ai_build_index)
        op_card.add_control(idx_btn)
        dump_btn = PushButton("📥 写入文件索引")
        dump_btn.setToolTip("把扫描到的全部文件路径+摘要写入当前会话 context.txt")
        dump_btn.clicked.connect(self._ai_dump_file_index)
        op_card.add_control(dump_btn)
        ig_btn = PushButton("📂 打开忽略规则")
        ig_btn.setToolTip("打开 ai_ignore.js，配置要忽略的目录/后缀")
        ig_btn.clicked.connect(self._ai_open_ignore)
        op_card.add_control(ig_btn)
        op_card.controls.addStretch(1)
        r_card.addGroupWidget(op_card)

        # 单文件写入字数上限
        lim_row = QHBoxLayout()
        lim_row.addWidget(QLabel("单文件写入字数上限："))
        self.ai_limit_edit = QLineEdit()
        self.ai_limit_edit.setPlaceholderText("留空 = 全量写入（非常耗上下文，建议填 2000~5000）")
        self.ai_limit_edit.setMaximumWidth(320)
        lim_row.addWidget(self.ai_limit_edit, 1)
        lim_wrap = QWidget(); lim_wrap.setLayout(lim_row)
        r_card.addGroupWidget(lim_wrap)

        self.ai_index_label = CaptionLabel("未建立索引")
        r_card.addGroupWidget(self.ai_index_label)

        # 文件清单：扫描后列出文件摘要，点"写入"把全文塞进 context.txt
        self.ai_filelist_container = QWidget()
        self.ai_filelist_layout = QVBoxLayout(self.ai_filelist_container)
        self.ai_filelist_layout.setContentsMargins(4, 4, 4, 4)
        self.ai_filelist_layout.setSpacing(4)
        fl_card = TwoRowCard(FluentIcon.FOLDER, "文件清单",
                             "扫描结果预览；点「写入文件索引」把清单塞进上下文，AI 据此决定读哪个")
        fl_card.add_control(self.ai_filelist_container, 1, height=None)
        r_card.addGroupWidget(fl_card)

        self._ai_reload_project_list()

    def _ai_projects(self) -> list:
        return self._ai_cfg.get("local_projects", [])

    def _ai_reload_project_list(self):
        # 清空旧行
        while self.ai_proj_layout.count():
            item = self.ai_proj_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        projects = self._ai_projects()
        if not projects:
            empty = CaptionLabel("（还没有项目，点下面「+ 添加项目文件夹」）")
            self.ai_proj_layout.addWidget(empty)
            return

        for idx, p in enumerate(projects):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            cb = QCheckBox(p.get("path", ""))
            cb.setChecked(p.get("enabled", True))
            cb.setToolTip(p.get("path", ""))
            cb.stateChanged.connect(
                lambda state, i=idx: self._ai_on_project_toggle(i, state == Qt.Checked.value))
            rl.addWidget(cb, 1)
            rm = PushButton("移除")
            rm.setFixedWidth(60)
            rm.clicked.connect(lambda _, i=idx: self._ai_del_project(i))
            rl.addWidget(rm)
            self.ai_proj_layout.addWidget(row)

    def _ai_on_project_toggle(self, row: int, enabled: bool):
        if 0 <= row < len(self._ai_projects()):
            self._ai_projects()[row]["enabled"] = enabled
            _save_cfg(self._ai_cfg)

    def _ai_add_project(self):
        d = QFileDialog.getExistingDirectory(self.ai_page, "选择项目文件夹", "D:/")
        if d:
            self._ai_projects().append({"path": d.replace("/", "\\"), "enabled": True})
            _save_cfg(self._ai_cfg)
            self._ai_reload_project_list()

    def _ai_del_project(self, row: int = -1):
        if row < 0:
            return
        if 0 <= row < len(self._ai_projects()):
            self._ai_projects().pop(row)
            _save_cfg(self._ai_cfg)
            self._ai_reload_project_list()

    def _ai_ignore_file(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ai_ignore.js")

    def _ai_open_ignore(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        p = self._ai_ignore_file()
        if not os.path.exists(p):
            self.ai_status_label.setText("ai_ignore.js 不存在")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def _ai_load_ignore_rules(self) -> tuple:
        """从 ai_ignore.js 读 IGNORE_DIRS / IGNORE_EXTS，返回 (dirs_set, exts_set)。"""
        import re
        p = self._ai_ignore_file()
        dirs, exts = set(), set()
        if not os.path.exists(p):
            return dirs, exts
        try:
            text = open(p, encoding="utf-8").read()
        except Exception:
            return dirs, exts
        m = re.search(r"IGNORE_DIRS\s*=\s*\[([^\]]*)\]", text)
        if m:
            dirs = set(s.strip().strip('"').strip("'") for s in m.group(1).split(",") if s.strip())
        m = re.search(r"IGNORE_EXTS\s*=\s*\[([^\]]*)\]", text)
        if m:
            exts = set(s.strip().strip('"').strip("'").lower() for s in m.group(1).split(",") if s.strip())
        return dirs, exts

    def _ai_limit(self) -> int:
        """返回单文件写入字数上限；空 = 0 表示不截断。"""
        try:
            n = int(self.ai_limit_edit.text().strip())
            return n if n > 0 else 0
        except Exception:
            return 0

    def _ai_truncate(self, text: str) -> str:
        lim = self._ai_limit()
        if not lim or len(text) <= lim:
            return text
        return text[:lim] + f"\n……（已截断，共 {len(text)} 字符，上限 {lim}）"

    def _ai_index_db(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                            "cache", "search_index.db")

    def _ai_file_index_json(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                            "cache", "file_index.json")

    def _ai_summary_limit(self) -> int:
        """索引摘要字数上限：跟随用户设置，空 = 0 表示全量摘要。"""
        return self._ai_limit()

    def _ai_build_index(self):
        roots = [p["path"] for p in self._ai_projects() if p.get("enabled")]
        if not roots:
            self.ai_index_label.setText("没有勾选的项目")
            return
        self.ai_index_label.setText("正在扫描文件清单…")
        import threading, json as _json

        exts = (".txt", ".md", ".c", ".h", ".cpp", ".hpp", ".py", ".s", ".json", ".csv", ".log")
        ignore_dirs, ignore_exts = self._ai_load_ignore_rules()
        sum_lim = self._ai_summary_limit()

        def _run():
            items = []
            for root in roots:
                for dirpath, dirnames, filenames in os.walk(root):
                    # 按 ai_ignore.js 过滤目录
                    dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
                    for fn in filenames:
                        ext = os.path.splitext(fn)[1].lower()
                        if ext in ignore_exts:
                            continue
                        if not fn.lower().endswith(exts):
                            continue
                        fp = os.path.join(dirpath, fn)
                        try:
                            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                                if sum_lim > 0:
                                    summary = f.read(sum_lim).replace("\n", " ").strip()
                                else:
                                    summary = f.read().replace("\n", " ").strip()
                            items.append({
                                "path": fp,
                                "summary": summary,
                                "mtime": int(os.path.getmtime(fp)),
                            })
                        except Exception:
                            continue
            try:
                os.makedirs(os.path.dirname(self._ai_file_index_json()), exist_ok=True)
                with open(self._ai_file_index_json(), "w", encoding="utf-8") as f:
                    _json.dump(items, f, ensure_ascii=False, indent=2)
                scope = f"前 {sum_lim} 字摘要" if sum_lim > 0 else "全量摘要"
                msg = f"扫描完成：{len(items)} 个文本文件（{scope}）"
            except Exception as e:
                msg = f"扫描失败: {e}"
            self.ai_index_label.setText(msg)
            # 主线程刷新文件清单 UI
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._ai_refresh_filelist)

        threading.Thread(target=_run, daemon=True).start()

    def _ai_refresh_filelist(self):
        """从 file_index.json 重建文件清单 UI。"""
        import json as _json
        # 清空
        while self.ai_filelist_layout.count():
            it = self.ai_filelist_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        p = self._ai_file_index_json()
        if not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                items = _json.load(f)
        except Exception:
            return
        if not items:
            self.ai_filelist_layout.addWidget(CaptionLabel("（清单为空）"))
            return
        # 最多显示 200 条，避免界面过长
        for it in items[:200]:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            name = os.path.basename(it["path"])
            lab = QLabel(f"📄 {name}\n   {it['summary'][:60]}…")
            lab.setToolTip(it["path"])
            rl.addWidget(lab, 1)
            # 每行一个"写入"按钮：手动把该文件全文写入 context.txt
            btn = QPushButton("📥 写入")
            btn.setFixedWidth(70)
            btn.setFixedHeight(26)
            fp = it["path"]
            btn.clicked.connect(lambda _=False, p=fp: self._ai_write_filepath(p))
            rl.addWidget(btn)
            self.ai_filelist_layout.addWidget(row)

    def _ai_write_filepath(self, path: str):
        """把指定路径文件全文写入当前会话 context.txt。"""
        conv = self._ai_active_conv()
        if not conv:
            self.ai_status_label.setText("请先新建会话")
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = self._ai_truncate(f.read())
            mtime = int(os.path.getmtime(path))
            self._ai_append_context(conv, f"功能写入: 文件: {path} (mtime={mtime})", f"```\n{content}\n```")
            self.ai_status_label.setText(f"已写入：{os.path.basename(path)}（{len(content)} 字符）")
        except Exception as e:
            self.ai_status_label.setText(f"写入失败: {e}")

    def _ai_dump_file_index(self):
        """把 file_index.json 全部路径+摘要写入 context.txt【功能写入: 文件索引】。"""
        import json as _json
        conv = self._ai_active_conv()
        if not conv:
            self.ai_status_label.setText("请先新建会话")
            return
        p = self._ai_file_index_json()
        if not os.path.exists(p):
            self.ai_status_label.setText("还没建索引，先点「建立/刷新索引」")
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                items = _json.load(f)
        except Exception as e:
            self.ai_status_label.setText(f"读索引失败: {e}")
            return
        if not items:
            self.ai_status_label.setText("索引为空")
            return
        # 拼成树形清单：同级目录共用父路径，缩进列出文件
        # 按目录分组
        from collections import defaultdict
        groups = defaultdict(list)
        for it in items:
            dn = os.path.dirname(it["path"])
            fn = os.path.basename(it["path"])
            groups[dn].append((fn, it["summary"]))
        lines = [f"本项目共 {len(items)} 个文本文件，按目录分组（需要哪个全文告诉 AI 或用工具箱写入）："]
        for dn, files in sorted(groups.items()):
            lines.append(f"📁 {dn}/")
            for fn, summary in sorted(files):
                lines.append(f"   ├─ {fn} | {summary}")
        text = "\n".join(lines)
        self._ai_append_context(conv, "功能写入: 文件索引", text)
        self.ai_status_label.setText(f"已写入文件索引：{len(items)} 个文件摘要")

    # ===== 块③ 对话：会话切换 + 折叠轮次 =====
    def _build_ai_chat_block(self, page):
        chat_card = page.block_cards["对话"]

        # 会话栏：下拉切换 + 新建 + 删除当前
        bar = QHBoxLayout()
        bar.addWidget(QLabel("会话:"))
        self.ai_conv_combo = ComboBox()
        self.ai_conv_combo.setMinimumWidth(220)
        self.ai_conv_combo.currentIndexChanged.connect(self._ai_on_conv_switch)
        bar.addWidget(self.ai_conv_combo)
        new_btn = PushButton("新建会话")
        new_btn.clicked.connect(self._ai_new_conv)
        bar.addWidget(new_btn)
        del_btn = PushButton("删除当前会话")
        del_btn.clicked.connect(self._ai_del_conv)
        bar.addWidget(del_btn)
        open_btn = PushButton("打开工作目录")
        open_btn.setToolTip("打开本会话的工作文件夹（context.txt 记录完整上下文，可手动编辑）")
        open_btn.clicked.connect(self._ai_open_workdir)
        bar.addWidget(open_btn)
        rn_btn = PushButton("✏️ 重命名")
        rn_btn.setToolTip("修改当前会话显示名")
        rn_btn.clicked.connect(self._ai_rename_conv)
        bar.addWidget(rn_btn)
        bar.addWidget(QLabel("上下文格式:"))
        self.ai_ctx_ext_combo = ComboBox()
        self.ai_ctx_ext_combo.addItems(["txt", "md"])
        cur_ext = self._ai_cfg.get("context_ext", "txt").lower()
        self.ai_ctx_ext_combo.setCurrentText(cur_ext if cur_ext in ("txt", "md") else "txt")
        self.ai_ctx_ext_combo.currentTextChanged.connect(self._ai_on_ctx_ext_changed)
        bar.addWidget(self.ai_ctx_ext_combo)
        sync_btn = PushButton("⟳ 同步上下文")
        sync_btn.setToolTip("手动刷新：从 context 文件重新读取对话记录与角色设定，覆盖 UI 显示")
        sync_btn.clicked.connect(self._ai_sync_from_file)
        bar.addWidget(sync_btn)
        bar.addStretch(1)
        wrap = QWidget(); wrap.setLayout(bar)
        chat_card.addGroupWidget(wrap)

        # 轮次区：自适应高度，不套内部滚动（页面整体滚动承载）
        self.ai_chat_container = QWidget()
        self.ai_chat_layout = QVBoxLayout(self.ai_chat_container)
        self.ai_chat_layout.setContentsMargins(4, 4, 4, 4)
        self.ai_chat_layout.setSpacing(8)
        self.ai_chat_layout.addStretch(1)
        chat_card.addGroupWidget(self.ai_chat_container)

        # 输入 + 按钮（Enter 发送）
        self.ai_input = QLineEdit()
        self.ai_input.setPlaceholderText("提问：可问代码问题、科学原理、让 AI 基于本地项目整理文档…（Enter 发送）")
        self.ai_input.returnPressed.connect(self._ai_send)
        chat_card.addGroupWidget(self.ai_input)

        row = QHBoxLayout()
        self.ai_send_btn = PrimaryPushButton("发送")
        self.ai_send_btn.clicked.connect(self._ai_send)
        row.addWidget(self.ai_send_btn)
        self.ai_stop_btn = PushButton("停止")
        self.ai_stop_btn.setEnabled(False)
        self.ai_stop_btn.clicked.connect(self._ai_stop)
        row.addWidget(self.ai_stop_btn)
        row.addStretch(1)
        wrap = QWidget(); wrap.setLayout(row)
        chat_card.addGroupWidget(wrap)

        self.ai_status_label = CaptionLabel("就绪")
        chat_card.addGroupWidget(self.ai_status_label)

        self._ai_reload_conv_combo()

    # ---- 会话管理 ----
    def _ai_convs(self) -> list:
        return self._ai_cfg.setdefault("conversations", [])

    def _ai_active_conv(self):
        if not hasattr(self, "ai_conv_combo"):
            return None
        idx = self.ai_conv_combo.currentIndex()
        convs = self._ai_convs()
        return convs[idx] if 0 <= idx < len(convs) else None

    def _ai_reload_conv_combo(self):
        self.ai_conv_combo.blockSignals(True)
        self.ai_conv_combo.clear()
        for c in self._ai_convs():
            title = c.get("title", "新会话")
            # 显示最近一问摘要，方便识别
            last_user = ""
            for m in reversed(c.get("messages", [])):
                if m.get("role") == "user":
                    last_user = m.get("content", "")[:20].replace("\n", " ")
                    break
            label = f"{title} | {last_user}" if last_user else title
            self.ai_conv_combo.addItem(label)
        self.ai_conv_combo.blockSignals(False)
        if not self._ai_convs():
            self._ai_new_conv()
        else:
            self.ai_conv_combo.setCurrentIndex(len(self._ai_convs()) - 1)
        # 同步当前会话 messages（context 文件是真相源）
        conv = self._ai_active_conv()
        if conv and os.path.exists(self._ai_context_path(conv)):
            msgs = self._ai_build_messages(conv)
            conv["messages"] = [{"role": m["role"], "content": m["content"]} for m in msgs[1:]]
        self._ai_render_conv()

    # ---- AI 工作目录（每会话一个文件夹，context.txt 记录完整上下文） ----
    def _ai_workspace_root(self) -> str:
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ai_workspace")
        os.makedirs(root, exist_ok=True)
        return os.path.abspath(root)

    def _ai_conv_dir(self, conv: dict) -> str:
        d = conv.get("work_dir")
        if d and os.path.isdir(d):
            return d
        # work_dir 失效（文件夹被手动改名/移动）：新建时间戳目录，状态栏提示
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c for c in conv.get("title", "会话") if c not in r'\/:*?"<>|')[:30]
        d = os.path.join(self._ai_workspace_root(), f"{ts}_{safe_title}")
        os.makedirs(d, exist_ok=True)
        conv["work_dir"] = d
        _save_cfg(self._ai_cfg)
        if hasattr(self, "ai_status_label"):
            self.ai_status_label.setText("⚠ 原工作目录已失效，已新建空目录（旧存档在 ai_workspace 里手动找）")
        return d

    def _ai_context_path(self, conv: dict) -> str:
        ext = self._ai_cfg.get("context_ext", "txt").lower().lstrip(".")
        if ext not in ("txt", "md"):
            ext = "txt"
        return os.path.join(self._ai_conv_dir(conv), f"context.{ext}")

    # 分区定义：tag 前缀 → 分区头
    _AI_SECTIONS = ["=== 系统区 ===", "=== 资料区 ===", "=== 对话区 ==="]

    def _ai_section_for_tag(self, tag: str) -> str:
        if tag.startswith("系统设定") or tag.startswith("本地检索") or tag == "工具协议":
            return "=== 系统区 ==="
        if tag.startswith("功能写入"):
            return "=== 资料区 ==="
        return "=== 对话区 ==="

    def _ai_dedup_key(self, tag: str):
        """根据标签返回去重 key；返回 None 表示不去重（对话区每次都是新轮次）。"""
        if tag == "系统设定":
            return "系统设定"
        if tag == "工具协议":
            return "工具协议"
        if tag == "功能写入: 文件索引":
            return "功能写入: 文件索引"
        if tag.startswith("功能写入: 文件:"):
            # 提取文件路径（去掉后面的 mtime=xxx），同路径视为同一段
            head = tag.split("(", 1)[0].strip()
            return head
        return None

    def _ai_append_context(self, conv: dict, tag: str, text: str):
        """把一段带【标签】的文本按分区插入 context.txt（同 key 旧段先删除再插入）。"""
        from datetime import datetime
        p = self._ai_context_path(conv)
        section = self._ai_section_for_tag(tag)
        # 用户/助手/工具结果段：配对时间戳
        if tag == "用户":
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            conv["pending_ts"] = ts
            tag = f"用户 {ts}"
        elif tag == "助手":
            ts = conv.get("pending_ts", datetime.now().strftime("%Y%m%d_%H%M%S"))
            tag = f"助手 {ts}"
        elif tag in ("工具调用", "工具结果"):
            # 工具来回用独立递增序号，每次调用+结果成对共享 r{N}
            round_n = conv.get("tooluse_rounds", 0)
            tag = f"{tag} r{round_n}" if round_n else tag
        # 读现有内容，没有就建分区骨架
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = "\n".join(self._AI_SECTIONS) + "\n"
        # 确保三个分区头都在
        for h in self._AI_SECTIONS:
            if h not in content:
                content += f"\n{h}\n"
        # 找目标分区范围
        idx = content.find(section)
        if idx < 0:
            content += f"\n---\n【{tag}】\n{text}\n"
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return
        next_idx = len(content)
        for h in self._AI_SECTIONS:
            if h == section:
                continue
            j = content.find(h, idx + len(section))
            if j > idx:
                next_idx = min(next_idx, j)
        section_body = content[idx + len(section):next_idx]
        # 按 key 去重：删除目标分区内同 key 的旧段
        key = self._ai_dedup_key(tag)
        if key:
            section_body = self._ai_remove_sections_by_key(section_body, key)
        # 插入新段，对话段用 --- 分隔
        if tag.startswith(("用户", "助手", "工具调用", "工具结果")):
            block = f"\n---\n【{tag}】\n{text}\n"
        else:
            block = f"\n【{tag}】\n{text}\n"
        new_section_body = section_body.rstrip() + block
        content = content[:idx + len(section)] + new_section_body + content[next_idx:]
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _ai_remove_sections_by_key(body: str, key: str) -> str:
        """在分区正文里删除所有以【key】开头的段（段从【tag】行到下一个【tag】行或文末）。"""
        import re
        # 匹配 【xxx】 开头的段头
        pattern = re.compile(r"\n?【([^\n】]+)】\n")
        # 找出所有段头位置
        matches = list(pattern.finditer(body))
        if not matches:
            return body
        # 从后往前删，避免位置偏移
        keep_ranges = []
        i = 0
        while i < len(matches):
            m = matches[i]
            seg_tag = m.group(1)
            # 判断是否同 key
            same = False
            if key == "系统设定" and seg_tag == "系统设定":
                same = True
            elif key == "功能写入: 文件索引" and seg_tag == "功能写入: 文件索引":
                same = True
            elif key.startswith("功能写入: 文件:") and seg_tag.startswith("功能写入: 文件:"):
                # 比较路径部分（去掉 mtime）
                if seg_tag.split("(", 1)[0].strip() == key:
                    same = True
            if same:
                # 跳过这个段（不加入保留区）
                i += 1
                continue
            # 保留从这里到下一个段头（或文末）
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            keep_ranges.append((start, end))
            i += 1
        # 重组
        if not keep_ranges:
            return ""
        out = "".join(body[s:e] for s, e in keep_ranges)
        return out

    def _ai_on_ctx_ext_changed(self, ext: str):
        """切换上下文文件后缀（txt/md）：保存配置，已有文件不强制改名，下次写入用新后缀。"""
        self._ai_cfg["context_ext"] = ext.lower().lstrip(".")
        _save_cfg(self._ai_cfg)

    def _ai_sync_from_file(self):
        """全局同步：从 context 文件重新解析 messages + 角色设定，覆盖 UI 显示。"""
        conv = self._ai_active_conv()
        if not conv:
            return
        p = self._ai_context_path(conv)
        if not os.path.exists(p):
            self.ai_status_label.setText("context 文件不存在")
            return
        # 1. 从文件重建 messages
        msgs = self._ai_build_messages(conv)
        conv["messages"] = [{"role": m["role"], "content": m["content"]} for m in msgs[1:]]
        # 2. 从系统区提取角色设定，回填角色编辑框
        import re
        with open(p, "r", encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"【系统设定】\n(.+?)(?=\n【|\n===|\Z)", text, re.S)
        if m and hasattr(self, "ai_role_edit"):
            self.ai_role_edit.blockSignals(True)
            self.ai_role_edit.setPlainText(m.group(1).strip())
            self.ai_role_edit.blockSignals(False)
        # 3. 持久化 config
        _save_cfg(self._ai_cfg)
        # 4. 重渲染
        self._ai_reload_conv_combo()
        self.ai_status_label.setText(f"已从文件同步：{len(conv['messages'])} 条消息")

    def _ai_delete_turn(self, turn_index: int):
        """删除第 turn_index 轮对话（0 起）：从 context 文件对话区删对应【用户】/【助手】段，同步 conv messages。"""
        conv = self._ai_active_conv()
        if not conv:
            return
        import re
        p = self._ai_context_path(conv)
        if not os.path.exists(p):
            return
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()

        # 找对话区
        chat_header = "=== 对话区 ==="
        idx = content.find(chat_header)
        if idx < 0:
            return
        chat_body = content[idx + len(chat_header):]
        # 切分成段：[(tag, body), ...]
        parts = re.split(r"【([^】]+)】", chat_body)
        # parts[0] 是对话区头前的空白，之后成对出现
        segs = []  # list of (tag, body, start_pos, end_pos_in_chat_body)
        pos = 0
        # 重新算位置：用 finditer
        pattern = re.compile(r"【([^】]+)】\n")
        matches = list(pattern.finditer(chat_body))
        for i, m in enumerate(matches):
            tag = m.group(1).strip()
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(chat_body)
            segs.append((tag, start, end))

        # 找出所有【用户 ts】段的索引，第 turn_index 个就是要删的
        user_seg_indices = [i for i, (tag, _, _) in enumerate(segs) if tag.startswith("用户")]
        if turn_index < 0 or turn_index >= len(user_seg_indices):
            return
        target_seg_idx = user_seg_indices[turn_index]
        # 提取该用户段的 ts
        target_tag = segs[target_seg_idx][0]
        ts = target_tag.replace("用户", "").strip()
        # 要删的段：所有同 ts 的用户/助手/工具结果段
        del_indices = [i for i, (tag, _, _) in enumerate(segs)
                       if ts in tag and tag.startswith(("用户", "助手", "工具调用", "工具结果"))]
        # 范围：最前一个删除段的 start 到最后一个删除段的 end
        del_start = segs[del_indices[0]][1]
        del_end = segs[del_indices[-1]][2]
        # 重组对话区
        new_chat_body = chat_body[:del_start] + chat_body[del_end:]
        new_content = content[:idx + len(chat_header)] + new_chat_body
        with open(p, "w", encoding="utf-8") as f:
            f.write(new_content)

        # 同步 conv["messages"]：重新从 context.txt 解析
        msgs = self._ai_build_messages(conv)
        conv["messages"] = [{"role": m["role"], "content": m["content"]} for m in msgs[1:]]
        _save_cfg(self._ai_cfg)
        self._ai_render_conv()
        self.ai_status_label.setText(f"已删除第 {turn_index + 1} 轮对话")

    # ===== Tool-use 循环 =====
    def _ai_tooluse_prompt_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tool_use_prompt.txt")

    def _ai_on_tooluse_toggle(self, enabled: bool):
        import re
        conv = self._ai_active_conv()
        if not conv:
            return
        # 先读 context.txt，检测是否已有【工具协议】段
        p_ctx = self._ai_context_path(conv)
        has_section = False
        if os.path.exists(p_ctx):
            with open(p_ctx, "r", encoding="utf-8") as f:
                existing = f.read()
            has_section = bool(re.search(r"(?:^|\n)【工具协议】\n", existing))
        if enabled:
            if has_section:
                # 已有则跳过插入，只更新按钮状态
                self.ai_tooluse_btn.setText("⏸ 已启用，点击关闭")
                self.ai_status_label.setText("Tool-use 循环已启用（提示词已存在，跳过插入）")
            else:
                p = self._ai_tooluse_prompt_path()
                if not os.path.exists(p):
                    self.ai_status_label.setText("找不到 tool_use_prompt.txt")
                    self.ai_tooluse_btn.setChecked(False)
                    return
                with open(p, "r", encoding="utf-8") as f:
                    raw = f.read()
                # 过滤 # 注释行（写入 md 后 # 会被渲染成大标题）
                prompt = "\n".join(
                    line for line in raw.splitlines()
                    if not line.strip().startswith("#")
                ).strip()
                self._ai_append_context(conv, "工具协议", prompt)
                self.ai_tooluse_btn.setText("⏸ 已启用，点击关闭")
                self.ai_status_label.setText("Tool-use 循环已启用，AI 可输出 [ACTION] 块")
        else:
            if has_section:
                self._ai_remove_tag_section(conv, "工具协议")
            # 没有则不删，按钮复位
            self.ai_tooluse_btn.setText("▶ 启用循环")
            self.ai_status_label.setText("Tool-use 循环已关闭")
        conv["tooluse_enabled"] = enabled
        _save_cfg(self._ai_cfg)

    def _ai_remove_tag_section(self, conv: dict, tag: str):
        """从 context.txt 删除指定标签段。"""
        import re
        p = self._ai_context_path(conv)
        if not os.path.exists(p):
            return
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        # 删除【tag】...下一个【tag】或分区头之前的内容
        pattern = re.compile(r"\n?【" + re.escape(tag) + r"】\n.*?(?=\n【|\n===|\Z)", re.S)
        new_content = pattern.sub("", content)
        with open(p, "w", encoding="utf-8") as f:
            f.write(new_content)

    def _ai_open_tooluse_prompt(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._ai_tooluse_prompt_path()))

    def _ai_open_tooluse_dir(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        d = os.path.dirname(self._ai_tooluse_prompt_path())
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _ai_delete_turn_by_ts(self, ts: str):
        """按时间戳删除整轮对话（用户+助手，保留工具来回）。"""
        import re
        conv = self._ai_active_conv()
        if not conv or not ts:
            return
        p = self._ai_context_path(conv)
        if not os.path.exists(p):
            return
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        # 删除所有 tag 里包含该 ts 的用户/助手段
        pattern = re.compile(r"\n?【(用户|助手) " + re.escape(ts) + r"】\n.*?(?=\n【|\n===|\Z)", re.S)
        new_content = pattern.sub("", content)
        with open(p, "w", encoding="utf-8") as f:
            f.write(new_content)
        # 重新同步
        msgs = self._ai_build_messages(conv)
        conv["messages"] = [{"role": m["role"], "content": m["content"]} for m in msgs[1:]]
        _save_cfg(self._ai_cfg)
        self._ai_render_conv()

    def _ai_delete_turn_dict(self, t: dict):
        """按 turn dict 删除对应段。"""
        import re
        conv = self._ai_active_conv()
        if not conv:
            return
        p = self._ai_context_path(conv)
        if not os.path.exists(p):
            return
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        if t["type"] == "chat":
            # 删用户+助手（同 ts）
            ts = re.escape(t["ts"])
            pattern = re.compile(r"\n?【(用户|助手) " + ts + r"】\n.*?(?=\n【|\n===|\Z)", re.S)
            content = pattern.sub("", content)
        else:
            # 删工具调用+结果（同 r{N}）
            r = re.escape(t["ts"])
            pattern = re.compile(r"\n?【(工具调用|工具结果) " + r + r"】\n.*?(?=\n【|\n===|\Z)", re.S)
            content = pattern.sub("", content)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        # 重新同步
        msgs = self._ai_build_messages(conv)
        conv["messages"] = [{"role": m["role"], "content": m["content"]} for m in msgs[1:]]
        _save_cfg(self._ai_cfg)
        self._ai_render_conv()

    def _ai_open_workdir(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        conv = self._ai_active_conv()
        if not conv:
            return
        d = self._ai_conv_dir(conv)
        # 仅当 context 文件不存在时写初始化说明（不重复追加）
        ext = self._ai_cfg.get("context_ext", "txt").lower()
        p = os.path.join(d, f"context.{ext if ext in ('txt','md') else 'txt'}")
        if not os.path.exists(p):
            self._ai_append_context(conv, "会话开始",
                                    f"会话：{conv.get('title')}\n创建：{conv.get('created')}\n"
                                    f"工作目录：{d}\n\n"
                                    "本文件按分区组织：系统区（人设/背景）、资料区（文件/剪贴板）、对话区（问答）。\n"
                                    "你可以手动编辑任意分区内容；下次发送时 AI 会读取本文件全部内容作为上下文。")
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _ai_new_conv(self):
        conv = {
            "id": uuid.uuid4().hex[:8],
            "title": f"会话 {len(self._ai_convs()) + 1}",
            "created": datetime.now().isoformat(timespec="seconds"),
            "messages": [],
        }
        self._ai_convs().append(conv)
        # 预创建工作目录
        self._ai_conv_dir(conv)
        _save_cfg(self._ai_cfg)
        self._ai_reload_conv_combo()
        self.ai_conv_combo.setCurrentIndex(len(self._ai_convs()) - 1)

    def _ai_rename_conv(self):
        from PySide6.QtWidgets import QInputDialog
        conv = self._ai_active_conv()
        if not conv:
            return
        name, ok = QInputDialog.getText(self.ai_page, "重命名会话",
                                        "会话名称：", text=conv.get("title", ""))
        if not ok or not name.strip():
            return
        new_title = name.strip()
        old_dir = conv.get("work_dir", "")
        # 同步重命名本地文件夹：保留时间戳前缀，只替换后缀
        if old_dir and os.path.isdir(old_dir):
            parent = os.path.dirname(old_dir)
            base = os.path.basename(old_dir)
            # 文件夹格式：YYYYMMDD_HHMMSS_旧会话名
            parts = base.split("_", 2)
            if len(parts) >= 3:
                ts_prefix = f"{parts[0]}_{parts[1]}"
            else:
                ts_prefix = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(c for c in new_title if c not in r'\/:*?"<>|')[:30]
            new_dir = os.path.join(parent, f"{ts_prefix}_{safe_title}")
            try:
                os.rename(old_dir, new_dir)
                conv["work_dir"] = new_dir
            except Exception as e:
                self.ai_status_label.setText(f"⚠ 文件夹重命名失败：{e}（仅改会话标题）")
        conv["title"] = new_title
        _save_cfg(self._ai_cfg)
        self._ai_reload_conv_combo()
        self.ai_status_label.setText(f"已重命名为：{new_title}")

    def _ai_del_conv(self):
        idx = self.ai_conv_combo.currentIndex()
        if 0 <= idx < len(self._ai_convs()):
            conv = self._ai_convs().pop(idx)
            # 本地工作目录（context.txt）作为存档保留，不删除
            # 用户想彻底清理可手动到 ai_workspace 删文件夹
            _save_cfg(self._ai_cfg)
            self._ai_reload_conv_combo()

    def _ai_on_conv_switch(self, idx: int):
        # 切换会话时从 context.txt 重新同步 messages（用户手动改 context.txt 后切回即生效）
        conv = self._ai_active_conv()
        if conv and os.path.exists(self._ai_context_path(conv)):
            msgs = self._ai_build_messages(conv)
            conv["messages"] = [{"role": m["role"], "content": m["content"]} for m in msgs[1:]]
            _save_cfg(self._ai_cfg)
        self._ai_render_conv()

    # ---- 轮次渲染（折叠） ----
    def _ai_clear_chat_layout(self):
        while self.ai_chat_layout.count():
            item = self.ai_chat_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.ai_chat_layout.addStretch(1)

    def _ai_render_conv(self):
        self._ai_clear_chat_layout()
        conv = self._ai_active_conv()
        if not conv:
            return
        # 直接从 context 文件解析分组，按 ts 配对用户/助手，工具调用/结果附加
        import re
        p = self._ai_context_path(conv)
        if not os.path.exists(p):
            return
        with open(p, "r", encoding="utf-8") as f:
            text = f.read()
        # 切分对话区段
        chat_idx = text.find("=== 对话区 ===")
        if chat_idx < 0:
            return
        chat_text = text[chat_idx:]
        # 按段顺序渲染：用户/助手成对算一轮，工具调用+结果成对算一轮
        parts = re.split(r"(?:^|\n)【([^】]+)】\n", chat_text)
        # parts[0] 是对话区头，之后成对
        raw_segs = []
        i = 1
        while i + 1 < len(parts):
            tag = parts[i].strip()
            body = parts[i + 1].strip()
            i += 2
            if not body:
                continue
            raw_segs.append((tag, body))
        # 配对：用户+助手成对，工具调用+结果成对，孤立段单独成轮
        turns = []
        i = 0
        while i < len(raw_segs):
            tag, body = raw_segs[i]
            if tag.startswith("用户"):
                ts = tag.replace("用户", "").strip()
                assistant = None
                j = i + 1
                if j < len(raw_segs) and raw_segs[j][0].startswith("助手"):
                    assistant = raw_segs[j][1]
                    j += 1
                turns.append({"type": "chat", "ts": ts, "user": body, "assistant": assistant})
                i = j
            elif tag.startswith("助手"):
                # 孤立的助手段（AI 主动汇报，没有对应用户问题）
                ts = tag.replace("助手", "").strip()
                turns.append({"type": "chat", "ts": ts, "user": None, "assistant": body})
                i += 1
            elif tag.startswith("工具调用"):
                r = tag.replace("工具调用", "").strip()
                result = None
                j = i + 1
                if j < len(raw_segs) and raw_segs[j][0].startswith("工具结果"):
                    result = raw_segs[j][1]
                    j += 1
                turns.append({"type": "tool", "ts": r, "call": body, "result": result})
                i = j
            elif tag.startswith("工具结果"):
                # 孤立的工具结果（没有对应调用），单独成轮
                turns.append({"type": "tool", "ts": "?", "call": None, "result": body})
                i += 1
            else:
                i += 1
        # 渲染
        for idx, t in enumerate(turns):
            collapsed = (idx < len(turns) - 1)
            block = self._ai_make_turn_block(t, collapsed=collapsed)
            self.ai_chat_layout.insertWidget(self.ai_chat_layout.count() - 1, block)

        # 渲染完后撑开外部「对话」卡片高度（异步等布局完成）
        from PySide6.QtCore import QTimer
        def _fix():
            card = self.ai_page.block_cards.get("对话")
            if card is not None and hasattr(self.ai_page, "_sync_expand_height"):
                self.ai_page._sync_expand_height(card)
        QTimer.singleShot(50, _fix)

    @staticmethod
    def _fit_browser_height(browser: QTextBrowser):
        """让 QTextBrowser 高度跟随内容（不出现内部滚动条）。"""
        from PySide6.QtCore import QTimer
        def _apply():
            browser.document().setTextWidth(browser.viewport().width())
            h = int(browser.document().size().height()) + 8
            browser.setFixedHeight(max(h, 30))
        browser.document().documentLayout().documentSizeChanged.connect(lambda _: _apply())
        QTimer.singleShot(0, _apply)

    def _ai_make_turn_block(self, t: dict, collapsed: bool) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 6, 8, 6)

        is_tool = (t["type"] == "tool")
        ts = t["ts"]
        if is_tool:
            preview = (t["call"] or t["result"] or "")[:40]
            title_label = f"[工具 {ts}] {preview}…  {'▸ 展开' if collapsed else '▾ 收起'}"
        else:
            preview = (t.get("user") or t.get("assistant") or "")[:30]
            title_label = f"[对话 {ts}] {preview}…  {'▸ 展开' if collapsed else '▾ 收起'}"

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = QPushButton(title_label)
        title.setFlat(True)
        title.setStyleSheet("text-align:left; color:#8ab4f7; padding:2px;")
        head.addWidget(title, 1)
        copy_btn = PushButton("复制整段")
        if is_tool:
            full_text = f"【工具调用 {ts}】\n{t.get('call','')}\n\n【工具结果 {ts}】\n{t.get('result','')}"
        else:
            full_text = f"【Q】{t.get('user','')}\n\n【A】{t.get('assistant','')}"
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(full_text))
        head.addWidget(copy_btn)
        del_btn = PushButton("🗑 删除本轮")
        del_btn.setStyleSheet("color:#ff6b6b;")
        del_btn.clicked.connect(lambda _=False, turn=t: self._ai_delete_turn_dict(turn))
        head.addWidget(del_btn)
        v.addLayout(head)

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(12, 0, 0, 0)
        if is_tool:
            if t.get("call"):
                tr1 = QTextBrowser(); tr1.setReadOnly(True)
                tr1.setStyleSheet("background:#2d2d2d; color:#9ccc9c;")
                tr1.setPlainText("🔧 调用: " + t["call"])
                self._fit_browser_height(tr1)
                bv.addWidget(tr1)
            if t.get("result"):
                tr2 = QTextBrowser(); tr2.setReadOnly(True)
                tr2.setStyleSheet("background:#2d2d2d; color:#9ccc9c;")
                tr2.setPlainText("📤 结果: " + t["result"])
                self._fit_browser_height(tr2)
                bv.addWidget(tr2)
        else:
            if t.get("user"):
                u_browser = QTextBrowser(); u_browser.setReadOnly(True)
                u_browser.setPlainText("👤 " + t["user"])
                self._fit_browser_height(u_browser)
                bv.addWidget(u_browser)
            if t.get("assistant"):
                a_browser = QTextBrowser(); a_browser.setReadOnly(True)
                a_browser.setPlainText("🤖 " + t["assistant"])
                self._fit_browser_height(a_browser)
                bv.addWidget(a_browser)
        v.addWidget(body)
        body.setVisible(not collapsed)

        def _refit():
            # 展开后宽度才真实，重算两个回复框高度
            for br in (u_browser, a_browser):
                br.document().setTextWidth(br.viewport().width())
                br.setFixedHeight(max(30, int(br.document().size().height()) + 8))

        def _toggle():
            body.setVisible(not body.isVisible())
            open_now = body.isVisible()
            if is_tool:
                preview = (t.get("call") or t.get("result") or "")[:40]
                new_title = f"[工具 {ts}] {preview}…  {'▾ 收起' if open_now else '▸ 展开'}"
            else:
                preview = (t.get("user") or t.get("assistant") or "")[:30]
                new_title = f"[对话 {ts}] {preview}…  {'▾ 收起' if open_now else '▸ 展开'}"
            title.setText(new_title)
            if open_now:
                QTimer.singleShot(0, _refit)
            # 撑开外部「对话」卡片（ExpandGroupSettingCard 高度跟随内容重算）
            card = self.ai_page.block_cards.get("对话")
            if card is not None and hasattr(self.ai_page, "_sync_expand_height"):
                QTimer.singleShot(0, lambda: self.ai_page._sync_expand_height(card))
        title.clicked.connect(_toggle)
        return frame

    # ---- 发送 ----
    def _ai_stop(self):
        if self._ai_worker:
            self._ai_worker.stop()

    # ---- 从 context 文件解析对话历史（用户可直接编辑此文件控制 AI 记忆） ----
    def _ai_build_messages(self, conv: dict) -> list:
        import re
        p = self._ai_context_path(conv)
        if not os.path.exists(p):
            return []
        try:
            with open(p, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return []
        # 只认行首独占一行的【标签】，避免文件路径里的【】被误切
        # 匹配：行首 + 【标签】+ 换行，捕获标签名
        parts = re.split(r"(?:^|\n)【([^】]+)】\n", text)
        sys_parts = []
        chat = []
        # parts[0] 是第一个标签前的内容（分区头/空白），从 parts[1] 开始成对
        i = 1
        while i + 1 < len(parts):
            tag = parts[i].strip()
            body = parts[i + 1].strip()
            i += 2
            # 剥掉分区头行（=== xxx ===）
            body = "\n".join(l for l in body.splitlines() if not l.strip().startswith("===")).strip()
            if not body:
                continue
            if tag.startswith(("系统设定", "本地检索", "功能写入")) or tag in ("会话开始", "工具协议"):
                sys_parts.append(f"【{tag}】\n{body}")
            elif tag.startswith("用户"):
                chat.append({"role": "user", "content": body})
            elif tag.startswith("助手"):
                chat.append({"role": "assistant", "content": body})
            elif tag.startswith("工具结果"):
                # 工具结果作为 user 消息发给 AI（让它看到执行结果继续决策）
                chat.append({"role": "user", "content": f"[工具执行结果]\n{body}"})
            elif tag.startswith("工具调用"):
                pass  # 工具调用是 AI 之前的动作，不重复发
            # 其他未识别标签忽略（用户自由备注）
        system = "\n\n".join(sys_parts) if sys_parts else "你是严谨的嵌入式工程师与代码助手。"
        return [{"role": "system", "content": system}] + chat

    def _ai_send(self):
        text = self.ai_input.text().strip()
        if not text:
            return
        if self._ai_busy:
            self.ai_status_label.setText("正在等待上次请求完成…（若长时间无响应，点「停止」）")
            return
        conv = self._ai_active_conv()
        if not conv:
            self.ai_status_label.setText("请先新建会话")
            return

        # 边界：没有勾选任何项目时，清空上下文里的文件索引段，避免 AI 看到过时索引
        enabled_projects = [lp for lp in self._ai_cfg.get("local_projects", []) if lp.get("enabled")]
        if not enabled_projects:
            try:
                self._ai_remove_tag_section(conv, "功能写入: 文件索引")
            except Exception:
                pass

        profiles = self._ai_profiles()
        row = self.ai_profile_list.currentRow()
        p = profiles[row] if 0 <= row < len(profiles) else {}
        client = ModelClient(base_url=p.get("base_url", ""),
                             api_key=p.get("api_key", ""),
                             model=p.get("model", ""))

        # 角色设定由工具箱编辑框管理（保存时重写系统区）；发送时不再重复追加
        # 重置 tool-use 轮次计数
        conv.pop("tooluse_rounds", None)
        # 追加本轮到 context.txt
        try:
            self._ai_append_context(conv, "用户", text)
        except Exception:
            pass

        # 从 context.txt 重建 messages（用户编辑生效）
        messages = self._ai_build_messages(conv)
        # 同步内存历史（用于 UI 轮次渲染）
        conv["messages"] = [{"role": m["role"], "content": m["content"]} for m in messages[1:]]

        # 标题用首句
        if not conv.get("title") or conv["title"].startswith("会话"):
            conv["title"] = text[:20]
            self.ai_conv_combo.setItemText(self.ai_conv_combo.currentIndex(), conv["title"])
        _save_cfg(self._ai_cfg)
        self.ai_input.clear()

        # 渲染新轮次（用户问题先上，AI 回复空占位）
        self._ai_render_conv()

        self._ai_busy = True
        self.ai_send_btn.setEnabled(False)
        self.ai_stop_btn.setEnabled(True)
        self.ai_status_label.setText("请求中…")
        self._ai_worker = ChatWorker(client, messages,
                                     {"temperature": 0.7, "top_p": 0.9, "max_tokens": 4096},
                                     self.ai_page)
        self._ai_worker.stream_finished.connect(lambda full: self._ai_on_finished(full))
        self._ai_worker.stream_error.connect(self._ai_on_error)
        self._ai_worker.start()

    def _ai_on_finished(self, full: str):
        import re as _re
        conv = self._ai_active_conv()
        if conv:
            # 拆出 ACTION 块：助手正文只保留非 ACTION 部分，ACTION 单独存档
            action_match = _re.search(r"\[ACTION\].*?\[/ACTION\]", full, _re.S)
            if action_match and conv.get("tooluse_enabled"):
                action_block = action_match.group().strip()
                assistant_text = (full[:action_match.start()] + full[action_match.end():]).strip()
            else:
                action_block = ""
                assistant_text = full
            try:
                self._ai_append_context(conv, "助手", assistant_text)
            except Exception:
                pass
            # 检查是否有 ACTION 块，有则执行命令并回灌
            if action_block and conv.get("tooluse_enabled"):
                # 轮次硬上限：防 AI 无限循环
                conv["tooluse_rounds"] = conv.get("tooluse_rounds", 0) + 1
                if conv["tooluse_rounds"] > 10:
                    self.ai_status_label.setText("Tool-use 循环达 10 轮上限，停止")
                    conv.pop("tooluse_rounds", None)
                    _save_cfg(self._ai_cfg)
                    self._ai_busy = False
                    self.ai_send_btn.setEnabled(True)
                    self.ai_stop_btn.setEnabled(False)
                    self._ai_render_conv()
                    return
                # ACTION 块单独存档
                try:
                    self._ai_append_context(conv, "工具调用", action_block)
                except Exception:
                    pass
                self.ai_status_label.setText(f"检测到 ACTION（第 {conv['tooluse_rounds']}/10 轮），执行命令中…")
                tool_result = self._ai_run_action(full)
                # 把 TOOL_RESULT 写入 context.txt
                try:
                    self._ai_append_context(conv, "工具结果", f"```json\n{tool_result}\n```")
                except Exception:
                    pass
                # 重新同步 messages，再次请求 AI
                msgs = self._ai_build_messages(conv)
                conv["messages"] = [{"role": m["role"], "content": m["content"]} for m in msgs[1:]]
                _save_cfg(self._ai_cfg)
                self._ai_render_conv()
                # 自动再发一轮
                self.ai_input.setText("")
                self._ai_send_with_messages(msgs)
                return
            # 重新从 context.txt 同步内存历史
            msgs = self._ai_build_messages(conv)
            conv["messages"] = [{"role": m["role"], "content": m["content"]} for m in msgs[1:]]
            _save_cfg(self._ai_cfg)
        self._ai_busy = False
        self.ai_send_btn.setEnabled(True)
        self.ai_stop_btn.setEnabled(False)
        self.ai_status_label.setText("完成")
        self._ai_render_conv()

    def _ai_extract_action(self, text: str):
        """从 AI 输出里提取 [ACTION]...[/ACTION] 块，返回 JSON dict 或 None。"""
        import re, json
        m = re.search(r"\[ACTION\]\s*(\{.*?\})\s*\[/ACTION\]", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except Exception:
            return None

    def _ai_run_action(self, text: str) -> str:
        """执行 ACTION 里的命令，返回 TOOL_RESULT 文本。"""
        import subprocess, time
        action = self._ai_extract_action(text)
        if not action:
            return '{"error": "no action"}'
        cmd = action.get("cmd", "")
        timeout = action.get("timeout", 30)
        max_output = action.get("max_output", 2000)
        if not cmd:
            return '{"error": "empty cmd"}'
        t0 = time.time()
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
            duration = round(time.time() - t0, 1)
            stdout = r.stdout or ""
            stderr = r.stderr or ""
            if len(stdout) > max_output:
                stdout = f"...（截断，共 {len(stdout)} 字）\n" + stdout[-max_output:]
            if len(stderr) > max_output:
                stderr = f"...（截断，共 {len(stderr)} 字）\n" + stderr[-max_output:]
            import json
            return json.dumps({
                "exit": r.returncode,
                "stdout_tail": stdout,
                "stderr": stderr,
                "duration_s": duration,
            }, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            import json
            return json.dumps({"exit": -1, "error": f"超时（{timeout}s）"}, ensure_ascii=False)
        except Exception as e:
            import json
            return json.dumps({"exit": -1, "error": str(e)}, ensure_ascii=False)

    def _ai_send_with_messages(self, messages: list):
        """用指定 messages 列表发起一次流式请求（tool-use 循环自动续轮用）。"""
        profiles = self._ai_profiles()
        row = self.ai_profile_list.currentRow()
        p = profiles[row] if 0 <= row < len(profiles) else {}
        client = ModelClient(base_url=p.get("base_url", ""),
                             api_key=p.get("api_key", ""),
                             model=p.get("model", ""))
        sampling = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 4096}
        self._ai_busy = True
        self.ai_send_btn.setEnabled(False)
        self.ai_stop_btn.setEnabled(True)
        self.ai_status_label.setText("Tool-use 循环中…")
        self._ai_worker = ChatWorker(client, messages, sampling, self.ai_page)
        self._ai_worker.stream_finished.connect(lambda full: self._ai_on_finished(full))
        self._ai_worker.stream_error.connect(self._ai_on_error)
        self._ai_worker.start()

    def _ai_on_error(self, err: str):
        self._ai_busy = False
        self.ai_send_btn.setEnabled(True)
        self.ai_stop_btn.setEnabled(False)
        self.ai_status_label.setText(f"请求失败：{err}")
