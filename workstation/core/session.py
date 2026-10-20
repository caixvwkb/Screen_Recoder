# -*- coding: utf-8 -*-
"""AI 工作站：会话与上下文（多轮历史 + token 预算裁剪）。

参考 pygpt-net 的 core/ctx/ctx.py get_history()：
- system + 按预算逆序裁剪的历史 + 当前 user 三段式
- 从最新一条往回累加，超出预算即截断更早的历史
裁剪按字符估算（无本地 tokenizer，中文 1 字符 ≈ 1 token 量级，预算留保守余量）。
"""
from __future__ import annotations


class Session:
    """单会话上下文。messages = [{"role","content"}, ...]，不含 system。"""

    def __init__(self, system_prompt: str = ""):
        self.system_prompt = system_prompt
        self.messages: list = []
        self._meta: dict = {}   # 预留：来源文件等元数据留痕

    def set_system(self, prompt: str):
        self.system_prompt = prompt

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def clear(self):
        self.messages.clear()
        self._meta.clear()

    def build_messages(self, max_history_chars: int = 6000) -> list:
        """组装发给 API 的 messages：system + 裁剪历史 + 当前 user（裁剪只作用于历史）。"""
        hist = []
        total = 0
        for m in reversed(self.messages):
            cost = len(m.get("content", ""))
            if hist and total + cost > max_history_chars:
                break                      # 超预算：截断更早的历史
            total += cost
            hist.append(m)
        hist.reverse()
        out = []
        if self.system_prompt:
            out.append({"role": "system", "content": self.system_prompt})
        out.extend(hist)
        return out

    def last_user_content(self) -> str:
        for m in reversed(self.messages):
            if m.get("role") == "user":
                return m.get("content", "")
        return ""

    def stats(self) -> dict:
        chars = sum(len(m.get("content", "")) for m in self.messages)
        return {"turns": len(self.messages), "chars": chars}
