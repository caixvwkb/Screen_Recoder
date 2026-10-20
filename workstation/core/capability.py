from __future__ import annotations


class Capability:
    """能力抽象基类：每个能力 = 一个可被模型/UI 调用的独立功能。

    子类实现 name / describe / run，注册到能力注册表后
    可被对话路由（用户说"识图"→ ocr 能力）或手动调用。
    """

    name: str = ""

    def describe(self) -> str:
        return ""

    def run(self, *args, **kwargs):
        raise NotImplementedError
