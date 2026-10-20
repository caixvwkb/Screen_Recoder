from __future__ import annotations
from core.capability import Capability


class FileIoCapability(Capability):
    """文件读写：多选/扫目录、=== 路径 === 标记、token 总量估算、输出保存。"""

    name = "file_io"
