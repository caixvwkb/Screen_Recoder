# -*- coding: utf-8 -*-
"""AI 工作站：模型客户端（OpenAI 兼容 API + SSE 流式）。

参考 pygpt-net 的 provider/api/openai（openai SDK + base_url 装配）：
- 不自己写 SSE 解析，用 openai SDK 的 stream=True 生成器
- base_url 指到本地/远端 /v1、api_key 任意串（本地服务照 Ollama 分支写法）
- DeepSeek 系模型的 reasoning_content（思维链）单独分流，UI 可区分显示
网络请求在调用方线程执行（QThread），本类纯同步生成器，不碰 UI。
"""
from __future__ import annotations

import json
import os

CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")


def _load_cfg() -> dict:
    try:
        with open(CFG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cfg(cfg: dict) -> None:
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class ModelClient:
    """OpenAI 兼容流式对话客户端。

    chat_stream() 返回生成器，逐段 yield (kind, text)：
      ("reasoning", ...) 思维链增量（DeepSeek-R1 系）
      ("text", ...)      正文增量
    """

    def __init__(self, base_url: str = "", api_key: str = "", model: str = ""):
        # DeepSeek 官方（2026-10 文档）：base_url=https://api.deepseek.com（SDK 自动拼端点），
        # 模型名 deepseek-flash（V4.1-Flash）或 deepseek-v4-pro；旧 deepseek-chat 名已下线
        self.base_url = base_url.strip() or "https://api.deepseek.com"
        self.api_key = api_key.strip() or "dummy"
        self.model = model.strip() or "deepseek-flash"

    # ---------- 配置持久化（workstation/config.json 的 api 段） ----------
    @staticmethod
    def load_config() -> dict:
        cfg = _load_cfg()
        return cfg.get("api", {})

    @staticmethod
    def save_config(base_url: str, api_key: str, model: str) -> None:
        cfg = _load_cfg()
        cfg["api"] = {"base_url": base_url, "api_key": api_key, "model": model}
        _save_cfg(cfg)

    def _client(self):
        from openai import OpenAI
        return OpenAI(base_url=self.base_url, api_key=self.api_key)

    def chat_stream(self, messages: list, temperature: float = 0.7,
                    top_p: float = 0.9, max_tokens: int = 4096):
        """流式对话：yield (kind, delta_text)。异常直接抛出由调用方处理。"""
        try:
            stream = self._client().chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
            )
        except Exception as e:
            raise RuntimeError(f"请求失败（检查 base_url/api_key/网络）: {e}") from e
        for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            r = getattr(delta, "reasoning_content", None)
            if r:
                yield ("reasoning", r)
            c = getattr(delta, "content", None)
            if c:
                yield ("text", c)

    def chat(self, messages: list, temperature: float = 0.7,
             top_p: float = 0.9, max_tokens: int = 4096) -> str:
        """非流式一次性对话（自测用）。"""
        resp = self._client().chat.completions.create(
            model=self.model, messages=messages,
            temperature=temperature, top_p=top_p, max_tokens=max_tokens)
        return resp.choices[0].message.content or ""
