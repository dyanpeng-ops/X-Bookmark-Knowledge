"""ingest — 入库层（Phase 6 已实现）。

对外入口：:class:`~src.ingest.ingest.Ingestor` —— 把上游 `UpstreamBookmark` /
`EnrichedBookmark` / `MediaEntry` 幂等写入本项目的 SQLite 状态库，
并把逐条原始 JSON 归档到 `data/raw/{tweet_id}.json`。

边界：本层不做网络抓取；单条失败不中断整批。
"""

from .ingest import (
    MANIFEST_STATUS_TO_MEDIA_STATUS,
    RAW_ARCHIVE_SCHEMA_VERSION,
    IngestStats,
    Ingestor,
    domain_of,
    media_key_for,
)

__all__ = [
    "IngestStats",
    "Ingestor",
    "MANIFEST_STATUS_TO_MEDIA_STATUS",
    "RAW_ARCHIVE_SCHEMA_VERSION",
    "domain_of",
    "media_key_for",
]

