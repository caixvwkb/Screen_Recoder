from __future__ import annotations


class ModelClient:
    """模型客户端抽象：OpenAI 兼容 API + SSE 流式。

    职责：组装 messages、解析 data:/[DONE]、分流 reasoning_content、
    增量回调渲染。网络用 httpx 异步流式，不阻塞 UI 主线程。
    """

    pass
