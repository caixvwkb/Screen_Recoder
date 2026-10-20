from __future__ import annotations
from core.capability import Capability


class TerminalCapability(Capability):
    """终端执行能力：本机命令执行 + 输出回灌上下文（受限白名单，防误操作）。"""

    name = "terminal"
