"""与数据库表对应的轻量数据结构（Phase 4）。

这些 dataclass 只做"形状"映射，不承载业务逻辑；``from_row`` 接受 ``sqlite3.Row``，
``to_params`` 产出命名参数，供 repository 拼装 INSERT/UPDATE。

字段与执行计划 §7 的表设计一一对应，不额外发明字段。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .states import BookmarkStatus


@dataclass(slots=True)
class BookmarkRecord:
    """``bookmarks`` 表的一行。"""

    tweet_id: str
    author_id: str | None = None
    username: str | None = None
    author_name: str | None = None
    tweet_text: str | None = None
    created_at: str | None = None
    tweet_url: str | None = None
    conversation_id: str | None = None
    raw_json_path: str | None = None
    markdown_path: str | None = None
    status: str = BookmarkStatus.NEW.value
    attempts: int = 0
    first_synced_at: str | None = None
    last_synced_at: str | None = None
    error_message: str | None = None
    id: int | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "BookmarkRecord":
        return cls(
            id=row["id"],
            tweet_id=row["tweet_id"],
            author_id=row["author_id"],
            username=row["username"],
            author_name=row["author_name"],
            tweet_text=row["tweet_text"],
            created_at=row["created_at"],
            tweet_url=row["tweet_url"],
            conversation_id=row["conversation_id"],
            raw_json_path=row["raw_json_path"],
            markdown_path=row["markdown_path"],
            status=row["status"],
            attempts=row["attempts"],
            first_synced_at=row["first_synced_at"],
            last_synced_at=row["last_synced_at"],
            error_message=row["error_message"],
        )

    def to_params(self) -> dict[str, object]:
        return {
            "tweet_id": self.tweet_id,
            "author_id": self.author_id,
            "username": self.username,
            "author_name": self.author_name,
            "tweet_text": self.tweet_text,
            "created_at": self.created_at,
            "tweet_url": self.tweet_url,
            "conversation_id": self.conversation_id,
            "raw_json_path": self.raw_json_path,
            "markdown_path": self.markdown_path,
            "status": self.status,
            "attempts": self.attempts,
            "first_synced_at": self.first_synced_at,
            "last_synced_at": self.last_synced_at,
            "error_message": self.error_message,
        }


@dataclass(slots=True)
class MediaRecord:
    """``media`` 表的一行。

    ``download_status=None`` 表示"调用方未提供该字段"——upsert 时不会覆盖库中已有值
    （与 ``BookmarkRecord`` 的"仅更新非 None 字段"约定一致）。落库时由 repository
    回退为数据库默认值 ``PENDING``。
    """

    tweet_id: str
    media_key: str
    media_type: str | None = None
    source_url: str | None = None
    local_path: str | None = None
    download_status: str | None = None
    attempts: int = 0
    error_message: str | None = None
    first_seen_at: str | None = None
    last_updated_at: str | None = None
    id: int | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "MediaRecord":
        return cls(
            id=row["id"],
            tweet_id=row["tweet_id"],
            media_key=row["media_key"],
            media_type=row["media_type"],
            source_url=row["source_url"],
            local_path=row["local_path"],
            download_status=row["download_status"],
            attempts=row["attempts"],
            error_message=row["error_message"],
            first_seen_at=row["first_seen_at"],
            last_updated_at=row["last_updated_at"],
        )


@dataclass(slots=True)
class ExternalLinkRecord:
    """``external_links`` 表的一行。

    ``fetch_status=None`` 表示"调用方未提供该字段"——upsert 时不会覆盖库中已有值；
    落库时由 repository 回退为数据库默认值 ``PENDING``。
    """

    tweet_id: str
    url: str
    resolved_url: str | None = None
    title: str | None = None
    domain: str | None = None
    content_path: str | None = None
    fetch_status: str | None = None
    attempts: int = 0
    error_message: str | None = None
    first_seen_at: str | None = None
    last_updated_at: str | None = None
    id: int | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ExternalLinkRecord":
        return cls(
            id=row["id"],
            tweet_id=row["tweet_id"],
            url=row["url"],
            resolved_url=row["resolved_url"],
            title=row["title"],
            domain=row["domain"],
            content_path=row["content_path"],
            fetch_status=row["fetch_status"],
            attempts=row["attempts"],
            error_message=row["error_message"],
            first_seen_at=row["first_seen_at"],
            last_updated_at=row["last_updated_at"],
        )
