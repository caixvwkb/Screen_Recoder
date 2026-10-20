from __future__ import annotations
from core.capability import Capability


class OcrCapability(Capability):
    """识图能力：图片 → OCR 文字 → 文本模型理解。

    复用本项目现有 OCR 引擎（rapidocr_onnxruntime，主进程模式），
    不跨项目、不重复开发——直接 import 项目根模块即可。
    """

    name = "ocr"
