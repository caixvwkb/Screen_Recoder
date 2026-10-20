from __future__ import annotations


class VllmManager:
    """vLLM 进程管理：一键启停、端口就绪轮询、stderr 日志捕获、退出清理进程树。

    注意：vLLM 有 worker 子进程，Windows 下退出用 taskkill /T 清进程树，
    避免残留占显存。
    """

    pass
