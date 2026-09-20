"""database — 数据层（Phase 4 实现）。

职责边界（见 `AGENTS.md` 第 3 节）
--------------------------------
* 拥有：SQLite schema、迁移、状态机、幂等 upsert、错误记录、FTS5 检索。
* 不拥有：网络抓取、Markdown 渲染、知识库文件写入、AI 分析。
* 不含业务编排：由 `ingest` / `processor` / `cli` 调用本层。

对外入口即下面的导出符号；上层代码不应依赖本包未导出的实现细节。
"""

from __future__ import annotations

from .clock import TIMESTAMP_FORMAT, parse_iso, utc_now, utc_now_iso
from .connection import MEMORY, connect, schema_status
from .migrations import (
    apply_migrations,
    current_version,
    is_up_to_date,
    pending_migrations,
    recorded_versions,
    table_exists,
)
from .models import BookmarkRecord, ExternalLinkRecord, MediaRecord
from .repository import BookmarkNotFound, BookmarkRepository, UpsertResult
from .schema import MIGRATIONS, SCHEMA_VERSION, Migration
from .states import (
    ALL_LINK_STATUS_VALUES,
    ALL_MEDIA_STATUS_VALUES,
    ALL_STATUS_VALUES,
    BookmarkStatus,
    InvalidStateTransition,
    LinkFetchStatus,
    MediaDownloadStatus,
    assert_transition,
    can_transition,
    is_terminal,
    next_status,
    parse_status,
)
from .transaction import in_transaction, transaction

__all__ = [
    "connect",
    "MEMORY",
    "schema_status",
    "apply_migrations",
    "current_version",
    "is_up_to_date",
    "pending_migrations",
    "recorded_versions",
    "table_exists",
    "MIGRATIONS",
    "Migration",
    "SCHEMA_VERSION",
    "BookmarkRecord",
    "MediaRecord",
    "ExternalLinkRecord",
    "BookmarkRepository",
    "BookmarkNotFound",
    "UpsertResult",
    "BookmarkStatus",
    "MediaDownloadStatus",
    "LinkFetchStatus",
    "InvalidStateTransition",
    "ALL_STATUS_VALUES",
    "ALL_MEDIA_STATUS_VALUES",
    "ALL_LINK_STATUS_VALUES",
    "assert_transition",
    "can_transition",
    "is_terminal",
    "next_status",
    "parse_status",
    "TIMESTAMP_FORMAT",
    "parse_iso",
    "utc_now",
    "utc_now_iso",
    "transaction",
    "in_transaction",
]

