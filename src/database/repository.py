"""数据访问层：bookmarks / media / external_links 的读写与状态流转（Phase 4）。

关键约定
--------
1. **幂等 upsert**：``upsert_bookmark`` 以 ``tweet_id`` 为唯一键。已存在的记录不会被重复插入，
   且**保留** ``status`` / ``attempts`` / ``first_synced_at`` / ``error_message``，只刷新
   本次真正提供的内容字段与 ``last_synced_at``。这是"同一任务跑两次不产生重复数据"的实现基础。
2. **部分更新**：传入值为 ``None`` 的字段视为"本次未提供"，不会覆盖库中已有值。
   避免上游返回稀疏记录时把已归档内容擦掉。
3. **状态流转**：所有状态变更都经 ``states.assert_transition`` 校验，非法流转抛
   ``InvalidStateTransition``，且不产生任何写入。
4. 每次写操作都在显式事务内完成（``transaction``）。

本模块不含网络、不含文件系统操作，只负责数据库语义。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .clock import utc_now_iso
from .models import BookmarkRecord, ExternalLinkRecord, MediaRecord
from .states import (
    ALL_STATUS_VALUES,
    BookmarkStatus,
    MediaDownloadStatus,
    LinkFetchStatus,
    assert_transition,
    parse_status,
)
from .transaction import transaction

MAX_ERROR_MESSAGE_LENGTH = 1000
DEFAULT_SEARCH_LIMIT = 20

BOOKMARK_CONTENT_FIELDS: tuple[str, ...] = (
    "author_id",
    "username",
    "author_name",
    "tweet_text",
    "created_at",
    "tweet_url",
    "conversation_id",
    "raw_json_path",
    "markdown_path",
)

MEDIA_CONTENT_FIELDS: tuple[str, ...] = (
    "media_type",
    "source_url",
    "local_path",
)

LINK_CONTENT_FIELDS: tuple[str, ...] = (
    "resolved_url",
    "title",
    "domain",
    "content_path",
)


class BookmarkNotFound(LookupError):
    """按 tweet_id 未找到书签。"""


@dataclass(frozen=True, slots=True)
class UpsertResult:
    """upsert 结果：``created`` 是否新建，``changed`` 提供的内容是否与库中不同。"""

    record: BookmarkRecord | MediaRecord | ExternalLinkRecord
    created: bool
    changed: bool


def _truncate(message: object, limit: int = MAX_ERROR_MESSAGE_LENGTH) -> str:
    text = str(message)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _status_value(value: object, enum_type: type, default: str) -> str:
    """把可选的枚举/字符串状态规范化为字符串；``None`` 时回退为数据库默认值。

    输入数据结构用 ``None`` 表示"未提供该字段"，而数据库列保持 NOT NULL 语义；
    顺便用枚举做一次取值校验，非法值抛 ValueError。
    """
    if value is None:
        return default
    return enum_type(str(value)).value  # type: ignore[attr-defined]


def _require_tweet_id(tweet_id: str) -> str:
    if not isinstance(tweet_id, str) or not tweet_id.strip():
        raise ValueError("tweet_id must be a non-empty string")
    return tweet_id.strip()


class BookmarkRepository:
    """bookmarks / media / external_links 的统一入口。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── bookmarks ────────────────────────────────────────────────────────
    def get_bookmark(self, tweet_id: str) -> BookmarkRecord | None:
        """按 tweet_id 读取；不存在返回 None。"""
        row = self._conn.execute(
            "SELECT * FROM bookmarks WHERE tweet_id = ?",
            (_require_tweet_id(tweet_id),),
        ).fetchone()
        return BookmarkRecord.from_row(row) if row is not None else None

    def require_bookmark(self, tweet_id: str) -> BookmarkRecord:
        """按 tweet_id 读取；不存在抛 ``BookmarkNotFound``。"""
        record = self.get_bookmark(tweet_id)
        if record is None:
            raise BookmarkNotFound(f"bookmark not found: {tweet_id}")
        return record

    def count_bookmarks(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM bookmarks").fetchone()
        return int(row[0])

    def upsert_bookmark(self, record: BookmarkRecord, *, now: object | None = None) -> UpsertResult:
        """插入或更新一条书签；实现增量同步的幂等写入。

        新建时：``first_synced_at`` = ``last_synced_at`` = 当前时间，``attempts`` = 0，
        ``status`` 取 ``record.status``（默认 ``NEW``）。
        已存在时：只更新本次提供的（非 None）内容字段与 ``last_synced_at``，
        并保留 ``status`` / ``attempts`` / ``first_synced_at`` / ``error_message``。
        """
        tweet_id = _require_tweet_id(record.tweet_id)
        parse_status(record.status)  # 提前校验，避免把非法状态写进库
        stamp = utc_now_iso(now)  # type: ignore[arg-type]

        existing = self.get_bookmark(tweet_id)
        with transaction(self._conn):
            if existing is None:
                self._conn.execute(
                    """
                    INSERT INTO bookmarks (
                        tweet_id, author_id, username, author_name, tweet_text,
                        created_at, tweet_url, conversation_id, raw_json_path,
                        markdown_path, status, attempts, first_synced_at,
                        last_synced_at, error_message
                    ) VALUES (
                        :tweet_id, :author_id, :username, :author_name, :tweet_text,
                        :created_at, :tweet_url, :conversation_id, :raw_json_path,
                        :markdown_path, :status, 0, :first_synced_at,
                        :last_synced_at, NULL
                    )
                    """,
                    {
                        "tweet_id": tweet_id,
                        "author_id": record.author_id,
                        "username": record.username,
                        "author_name": record.author_name,
                        "tweet_text": record.tweet_text,
                        "created_at": record.created_at,
                        "tweet_url": record.tweet_url,
                        "conversation_id": record.conversation_id,
                        "raw_json_path": record.raw_json_path,
                        "markdown_path": record.markdown_path,
                        "status": parse_status(record.status).value,
                        "first_synced_at": stamp,
                        "last_synced_at": stamp,
                    },
                )
                return UpsertResult(self.require_bookmark(tweet_id), True, True)

            updates = {
                field: getattr(record, field)
                for field in BOOKMARK_CONTENT_FIELDS
                if getattr(record, field) is not None
            }
            changed = any(getattr(existing, field) != value for field, value in updates.items())
            assignments = [f"{field} = :{field}" for field in updates]
            assignments.append("last_synced_at = :last_synced_at")
            params: dict[str, object] = dict(updates)
            params["last_synced_at"] = stamp
            params["tweet_id"] = tweet_id
            self._conn.execute(
                f"UPDATE bookmarks SET {', '.join(assignments)} WHERE tweet_id = :tweet_id",
                params,
            )
            return UpsertResult(self.require_bookmark(tweet_id), False, changed)

    def set_status(
        self,
        tweet_id: str,
        status: str | BookmarkStatus,
        *,
        error_message: str | None = None,
        attempts_delta: int = 0,
    ) -> BookmarkRecord:
        """流转状态并按需记录/清除错误信息。

        * 非法流转抛 ``InvalidStateTransition``，且不写入任何数据。
        * ``error_message=None`` 表示顺带清除历史错误（成功路径的常见用法）。
        * ``last_synced_at`` 只在 ``upsert_bookmark`` 中更新，此处不修改，避免语义混淆。
        """
        current = self.require_bookmark(tweet_id)
        target = assert_transition(current.status, status)
        with transaction(self._conn):
            self._conn.execute(
                """
                UPDATE bookmarks
                   SET status = ?, error_message = ?, attempts = attempts + ?
                 WHERE tweet_id = ?
                """,
                (
                    target.value,
                    None if error_message is None else _truncate(error_message),
                    int(attempts_delta),
                    _require_tweet_id(tweet_id),
                ),
            )
        return self.require_bookmark(tweet_id)

    def record_error(
        self,
        tweet_id: str,
        message: object,
        *,
        status: str | BookmarkStatus = BookmarkStatus.FAILED,
        count_attempt: bool = True,
    ) -> BookmarkRecord:
        """记录一次失败：写入 ``error_message``、按需累加 ``attempts`` 并流转状态。"""
        return self.set_status(
            tweet_id,
            status,
            error_message=_truncate(message),
            attempts_delta=1 if count_attempt else 0,
        )

    def count_by_status(self) -> dict[str, int]:
        """返回全部状态的计数（含 0），便于同步报告直接打印。"""
        counts = {value: 0 for value in ALL_STATUS_VALUES}
        rows = self._conn.execute("SELECT status, COUNT(*) FROM bookmarks GROUP BY status")
        for status, total in rows:
            counts[str(status)] = int(total)
        return counts

    def list_by_status(
        self,
        status: str | BookmarkStatus,
        *,
        limit: int | None = None,
    ) -> list[BookmarkRecord]:
        """按状态列出书签（新的在前）。"""
        params: list[object] = [parse_status(status).value]
        sql = "SELECT * FROM bookmarks WHERE status = ? ORDER BY created_at DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [BookmarkRecord.from_row(row) for row in rows]

    def list_bookmarks(
        self,
        *,
        limit: int | None = None,
    ) -> list[BookmarkRecord]:
        """列出全部书签（任何状态；新的在前）。供 process 等需要全量幂等处理的路径使用。"""
        sql = "SELECT * FROM bookmarks ORDER BY created_at DESC, id DESC"
        params: list[object] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [BookmarkRecord.from_row(row) for row in rows]

    def search(self, query: str, *, limit: int = DEFAULT_SEARCH_LIMIT) -> list[BookmarkRecord]:
        """FTS5 全文检索（BM25 排序）；查询语法非法时抛 ValueError。"""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("search query must be a non-empty string")
        try:
            rows = self._conn.execute(
                """
                SELECT bookmarks.*
                  FROM bookmarks_fts
                  JOIN bookmarks ON bookmarks.id = bookmarks_fts.rowid
                 WHERE bookmarks_fts MATCH ?
                 ORDER BY bm25(bookmarks_fts), bookmarks.id DESC
                 LIMIT ?
                """,
                (query, int(limit)),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError(f"invalid full-text search query: {query!r}") from exc
        return [BookmarkRecord.from_row(row) for row in rows]

    def delete_bookmark(self, tweet_id: str) -> bool:
        """删除一条书签及其媒体/外链（外键级联）。返回是否确实删除。

        仅用于测试与显式清理；常规流程不得调用。
        """
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM bookmarks WHERE tweet_id = ?",
                (_require_tweet_id(tweet_id),),
            )
        return cursor.rowcount > 0

    # ── media ────────────────────────────────────────────────────────────
    def get_media(self, tweet_id: str, media_key: str) -> MediaRecord | None:
        row = self._conn.execute(
            "SELECT * FROM media WHERE tweet_id = ? AND media_key = ?",
            (_require_tweet_id(tweet_id), media_key),
        ).fetchone()
        return MediaRecord.from_row(row) if row is not None else None

    def require_media(self, tweet_id: str, media_key: str) -> MediaRecord:
        record = self.get_media(tweet_id, media_key)
        if record is None:
            raise LookupError(f"media not found: tweet_id={tweet_id} media_key={media_key}")
        return record

    def list_media(self, tweet_id: str) -> list[MediaRecord]:
        rows = self._conn.execute(
            "SELECT * FROM media WHERE tweet_id = ? ORDER BY media_key",
            (_require_tweet_id(tweet_id),),
        ).fetchall()
        return [MediaRecord.from_row(row) for row in rows]

    def upsert_media(self, record: MediaRecord, *, now: object | None = None) -> UpsertResult:
        """按 (tweet_id, media_key) 幂等写入媒体行。

        已存在时保留 ``download_status`` / ``attempts`` / ``first_seen_at``，
        仅更新本次提供的字段与 ``last_updated_at``。
        """
        tweet_id = _require_tweet_id(record.tweet_id)
        if not isinstance(record.media_key, str) or not record.media_key.strip():
            raise ValueError("media_key must be a non-empty string")
        if self.get_bookmark(tweet_id) is None:
            raise BookmarkNotFound(f"cannot attach media to unknown bookmark: {tweet_id}")
        stamp = utc_now_iso(now)  # type: ignore[arg-type]
        row = self._conn.execute(
            "SELECT * FROM media WHERE tweet_id = ? AND media_key = ?",
            (tweet_id, record.media_key),
        ).fetchone()

        with transaction(self._conn):
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO media (
                        tweet_id, media_key, media_type, source_url, local_path,
                        download_status, attempts, error_message,
                        first_seen_at, last_updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)
                    """,
                    (
                        tweet_id,
                        record.media_key,
                        record.media_type,
                        record.source_url,
                        record.local_path,
                        _status_value(
                            record.download_status,
                            MediaDownloadStatus,
                            MediaDownloadStatus.PENDING.value,
                        ),
                        stamp,
                        stamp,
                    ),
                )
            else:
                existing = MediaRecord.from_row(row)
                supplied: dict[str, object] = {
                    field: getattr(record, field)
                    for field in MEDIA_CONTENT_FIELDS
                    if getattr(record, field) is not None
                }
                if record.download_status is not None:
                    supplied["download_status"] = record.download_status
                changed = any(getattr(existing, key) != value for key, value in supplied.items())
                assignments = [f"{key} = :{key}" for key in supplied]
                assignments.append("last_updated_at = :last_updated_at")
                params: dict[str, object] = dict(supplied)
                params["last_updated_at"] = stamp
                params["tweet_id"] = tweet_id
                params["media_key"] = record.media_key
                self._conn.execute(
                    f"UPDATE media SET {', '.join(assignments)} "
                    "WHERE tweet_id = :tweet_id AND media_key = :media_key",
                    params,
                )
        if row is None:
            return UpsertResult(self.require_media(tweet_id, record.media_key), True, True)
        return UpsertResult(self.require_media(tweet_id, record.media_key), False, changed)

    def set_media_status(
        self,
        tweet_id: str,
        media_key: str,
        status: str | MediaDownloadStatus,
        *,
        local_path: str | None = None,
        error_message: str | None = None,
        count_attempt: bool = False,
        now: object | None = None,
    ) -> MediaRecord:
        """更新单个媒体的下载状态、本地路径与错误信息（供 Phase 8 使用）。"""
        target = (
            MediaDownloadStatus(str(status))
            if not isinstance(status, MediaDownloadStatus)
            else status
        )
        self.require_media(tweet_id, media_key)
        assignments = ["download_status = ?", "error_message = ?", "last_updated_at = ?"]
        params: list[object] = [
            target.value,
            None if error_message is None else _truncate(error_message),
            utc_now_iso(now),  # type: ignore[arg-type]
        ]
        if local_path is not None:
            assignments.append("local_path = ?")
            params.append(local_path)
        if count_attempt:
            assignments.append("attempts = attempts + 1")
        params.extend([_require_tweet_id(tweet_id), media_key])
        with transaction(self._conn):
            self._conn.execute(
                f"UPDATE media SET {', '.join(assignments)} WHERE tweet_id = ? AND media_key = ?",
                params,
            )
        return self.require_media(tweet_id, media_key)

    # ── external links ───────────────────────────────────────────────────
    def get_external_link(self, tweet_id: str, url: str) -> ExternalLinkRecord | None:
        row = self._conn.execute(
            "SELECT * FROM external_links WHERE tweet_id = ? AND url = ?",
            (_require_tweet_id(tweet_id), url),
        ).fetchone()
        return ExternalLinkRecord.from_row(row) if row is not None else None

    def require_external_link(self, tweet_id: str, url: str) -> ExternalLinkRecord:
        record = self.get_external_link(tweet_id, url)
        if record is None:
            raise LookupError(f"external link not found: tweet_id={tweet_id} url={url}")
        return record

    def list_external_links(self, tweet_id: str) -> list[ExternalLinkRecord]:
        rows = self._conn.execute(
            "SELECT * FROM external_links WHERE tweet_id = ? ORDER BY url",
            (_require_tweet_id(tweet_id),),
        ).fetchall()
        return [ExternalLinkRecord.from_row(row) for row in rows]

    def upsert_external_link(
        self,
        record: ExternalLinkRecord,
        *,
        now: object | None = None,
    ) -> UpsertResult:
        """按 (tweet_id, url) 幂等写入外链行。

        已存在时保留 ``fetch_status`` / ``attempts`` / ``first_seen_at``，
        仅更新本次提供的字段与 ``last_updated_at``。
        """
        tweet_id = _require_tweet_id(record.tweet_id)
        if not isinstance(record.url, str) or not record.url.strip():
            raise ValueError("url must be a non-empty string")
        if self.get_bookmark(tweet_id) is None:
            raise BookmarkNotFound(f"cannot attach link to unknown bookmark: {tweet_id}")
        stamp = utc_now_iso(now)  # type: ignore[arg-type]
        row = self._conn.execute(
            "SELECT * FROM external_links WHERE tweet_id = ? AND url = ?",
            (tweet_id, record.url),
        ).fetchone()

        with transaction(self._conn):
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO external_links (
                        tweet_id, url, resolved_url, title, domain, content_path,
                        fetch_status, attempts, error_message,
                        first_seen_at, last_updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)
                    """,
                    (
                        tweet_id,
                        record.url,
                        record.resolved_url,
                        record.title,
                        record.domain,
                        record.content_path,
                        _status_value(
                            record.fetch_status,
                            LinkFetchStatus,
                            LinkFetchStatus.PENDING.value,
                        ),
                        stamp,
                        stamp,
                    ),
                )
            else:
                existing = ExternalLinkRecord.from_row(row)
                supplied: dict[str, object] = {
                    field: getattr(record, field)
                    for field in LINK_CONTENT_FIELDS
                    if getattr(record, field) is not None
                }
                if record.fetch_status is not None:
                    supplied["fetch_status"] = record.fetch_status
                changed = any(getattr(existing, key) != value for key, value in supplied.items())
                assignments = [f"{key} = :{key}" for key in supplied]
                assignments.append("last_updated_at = :last_updated_at")
                params: dict[str, object] = dict(supplied)
                params["last_updated_at"] = stamp
                params["tweet_id"] = tweet_id
                params["url"] = record.url
                self._conn.execute(
                    f"UPDATE external_links SET {', '.join(assignments)} "
                    "WHERE tweet_id = :tweet_id AND url = :url",
                    params,
                )
        if row is None:
            return UpsertResult(self.require_external_link(tweet_id, record.url), True, True)
        return UpsertResult(self.require_external_link(tweet_id, record.url), False, changed)

    def set_link_status(
        self,
        tweet_id: str,
        url: str,
        status: str | LinkFetchStatus,
        *,
        resolved_url: str | None = None,
        content_path: str | None = None,
        error_message: str | None = None,
        count_attempt: bool = False,
        now: object | None = None,
    ) -> ExternalLinkRecord:
        """更新单条外链的抓取状态与产出路径（供 Phase 9 使用）。

        抓取失败时仍保留原始 ``url``：本方法没有删除或清空 ``url`` 的途径，
        以满足执行计划 §12"绝不能丢失原始 URL"的要求。
        """
        target = (
            LinkFetchStatus(str(status)) if not isinstance(status, LinkFetchStatus) else status
        )
        self.require_external_link(tweet_id, url)
        assignments = ["fetch_status = ?", "error_message = ?", "last_updated_at = ?"]
        params: list[object] = [
            target.value,
            None if error_message is None else _truncate(error_message),
            utc_now_iso(now),  # type: ignore[arg-type]
        ]
        if resolved_url is not None:
            assignments.append("resolved_url = ?")
            params.append(resolved_url)
        if content_path is not None:
            assignments.append("content_path = ?")
            params.append(content_path)
        if count_attempt:
            assignments.append("attempts = attempts + 1")
        params.extend([_require_tweet_id(tweet_id), url])
        with transaction(self._conn):
            self._conn.execute(
                f"UPDATE external_links SET {', '.join(assignments)} "
                "WHERE tweet_id = ? AND url = ?",
                params,
            )
        return self.require_external_link(tweet_id, url)






