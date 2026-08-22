"""素材预处理：把 `_in/` 里"有啥放啥"的原始文件整理成标准输入。

`_in/` 是用户仅有的原始素材，这一层**只读它**——不改、不删、不移动。
产物一律写在歌曲目录下、`_in/` 之外。
"""

from murripple.ingest.scan import IngestError, Plan, scan

__all__ = ["IngestError", "Plan", "scan"]
