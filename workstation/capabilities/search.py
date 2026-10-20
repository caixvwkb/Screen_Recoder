from __future__ import annotations
from core.capability import Capability


class SearchCapability(Capability):
    """库检索能力：给模型用的检索工具（调 searcher，返回相关文件路径+摘要）。"""

    name = "search"
