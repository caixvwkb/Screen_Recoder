from __future__ import annotations
from core.capability import Capability


class AsrCapability(Capability):
    """语音转写能力：音频/视频 → 文字。

    复用本项目现有 asr.py（SenseVoice），走 --asr-worker 子进程模式，
    与本项目录屏后自动转写共用同一套引擎。
    """

    name = "asr"
