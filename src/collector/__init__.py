"""collector — 采集适配层。

（Phase 5 已实现）定义采集结果类型与「只读上游」的 fieldtheory CLI 适配器：
只读上游数据（bookmarks.jsonl / media-manifest.json / media/）与上游 CLI 的
JSON 输出，绝不写入上游目录。

对外入口：

* :class:`FieldTheoryAdapter` —— 调用 `fieldtheory sync/list/show`，并把结果
  规范化为本项目的数据类。
* :mod:`src.collector.contract` —— 对上游字段契约的冻结与校验。
"""

from .base import (
    Collector,
    CollectorError,
    EnrichedBookmark,
    MediaEntry,
    MediaManifest,
    SyncRunResult,
    UpstreamArtifacts,
    UpstreamAuthError,
    UpstreamBookmark,
    UpstreamContractError,
    UpstreamExecutionError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)
from .fieldtheory_adapter import FieldTheoryAdapter

__all__ = [
    "Collector",
    "CollectorError",
    "EnrichedBookmark",
    "FieldTheoryAdapter",
    "MediaEntry",
    "MediaManifest",
    "SyncRunResult",
    "UpstreamArtifacts",
    "UpstreamAuthError",
    "UpstreamBookmark",
    "UpstreamContractError",
    "UpstreamExecutionError",
    "UpstreamTimeoutError",
    "UpstreamUnavailableError",
]

