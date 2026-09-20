"""SQLite schema 定义与版本化 DDL（Phase 4）。

设计要点
--------
* 每个版本对应一个 ``Migration``；DDL 以元组形式声明，由 ``migrations.apply_migrations``
  在单个事务内顺序执行。
* ``bookmarks.tweet_id`` 具唯一约束，是"同一任务跑两次不产生重复数据"的第一道闸门。
* ``status`` / ``download_status`` / ``fetch_status`` 的 CHECK 约束由 ``states`` 模块的
  枚举自动生成，避免词表与代码脱节。
* 全文检索使用 FTS5 外部内容表（``content='bookmarks'``），并通过触发器保持同步。
  注意：``unicode61`` 分词把连续 CJK 字符视为单个 token，中文子串检索需在 Phase 7 复核。

DDL 中的表名/列名与执行计划 §7 的字段表保持一致，不额外发明字段。
"""

from __future__ import annotations

from dataclasses import dataclass

from .states import ALL_LINK_STATUS_VALUES, ALL_MEDIA_STATUS_VALUES, ALL_STATUS_VALUES


@dataclass(frozen=True, slots=True)
class Migration:
    """一次 schema 迁移。``version`` 必须从 1 开始且唯一。"""

    version: int
    name: str
    statements: tuple[str, ...]


def _check(column: str, values: tuple[str, ...]) -> str:
    """由状态词表生成 CHECK 约束片段。"""
    quoted = ", ".join("'" + value + "'" for value in values)
    return f"CHECK ({column} IN ({quoted}))"


_STATUS_CHECK = _check("status", ALL_STATUS_VALUES)
_MEDIA_STATUS_CHECK = _check("download_status", ALL_MEDIA_STATUS_VALUES)
_LINK_STATUS_CHECK = _check("fetch_status", ALL_LINK_STATUS_VALUES)

CORE_TABLES: tuple[str, ...] = ("schema_version", "bookmarks", "media", "external_links")
FTS_TABLE = "bookmarks_fts"

MIGRATION_1 = Migration(
    version=1,
    name="core bookmark storage",
    statements=(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS bookmarks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id        TEXT NOT NULL UNIQUE,
            author_id       TEXT,
            username        TEXT,
            author_name     TEXT,
            tweet_text      TEXT,
            created_at      TEXT,
            tweet_url       TEXT,
            conversation_id TEXT,
            raw_json_path   TEXT,
            markdown_path   TEXT,
            status          TEXT NOT NULL DEFAULT 'NEW',
            attempts        INTEGER NOT NULL DEFAULT 0,
            first_synced_at TEXT NOT NULL,
            last_synced_at  TEXT NOT NULL,
            error_message   TEXT,
            {_STATUS_CHECK}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_bookmarks_status ON bookmarks (status)",
        "CREATE INDEX IF NOT EXISTS idx_bookmarks_created_at ON bookmarks (created_at)",
        "CREATE INDEX IF NOT EXISTS idx_bookmarks_conversation ON bookmarks (conversation_id)",
    ),
)

MIGRATION_2 = Migration(
    version=2,
    name="media, external links and full-text search",
    statements=(
        f"""
        CREATE TABLE IF NOT EXISTS media (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id        TEXT NOT NULL,
            media_key       TEXT NOT NULL,
            media_type      TEXT,
            source_url      TEXT,
            local_path      TEXT,
            download_status TEXT NOT NULL DEFAULT 'PENDING',
            attempts        INTEGER NOT NULL DEFAULT 0,
            error_message   TEXT,
            first_seen_at   TEXT NOT NULL,
            last_updated_at TEXT NOT NULL,
            UNIQUE (tweet_id, media_key),
            FOREIGN KEY (tweet_id) REFERENCES bookmarks (tweet_id) ON DELETE CASCADE,
            {_MEDIA_STATUS_CHECK}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_media_tweet ON media (tweet_id)",
        "CREATE INDEX IF NOT EXISTS idx_media_status ON media (download_status)",
        f"""
        CREATE TABLE IF NOT EXISTS external_links (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id        TEXT NOT NULL,
            url             TEXT NOT NULL,
            resolved_url    TEXT,
            title           TEXT,
            domain          TEXT,
            content_path    TEXT,
            fetch_status    TEXT NOT NULL DEFAULT 'PENDING',
            attempts        INTEGER NOT NULL DEFAULT 0,
            error_message   TEXT,
            first_seen_at   TEXT NOT NULL,
            last_updated_at TEXT NOT NULL,
            UNIQUE (tweet_id, url),
            FOREIGN KEY (tweet_id) REFERENCES bookmarks (tweet_id) ON DELETE CASCADE,
            {_LINK_STATUS_CHECK}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_external_links_tweet ON external_links (tweet_id)",
        "CREATE INDEX IF NOT EXISTS idx_external_links_status ON external_links (fetch_status)",
        "CREATE INDEX IF NOT EXISTS idx_external_links_domain ON external_links (domain)",
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
            tweet_text,
            username,
            author_name,
            content='bookmarks',
            content_rowid='id',
            tokenize='unicode61'
        )
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS {FTS_TABLE}_ai AFTER INSERT ON bookmarks BEGIN
            INSERT INTO {FTS_TABLE} (rowid, tweet_text, username, author_name)
            VALUES (new.id, new.tweet_text, new.username, new.author_name);
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS {FTS_TABLE}_ad AFTER DELETE ON bookmarks BEGIN
            INSERT INTO {FTS_TABLE} ({FTS_TABLE}, rowid, tweet_text, username, author_name)
            VALUES ('delete', old.id, old.tweet_text, old.username, old.author_name);
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS {FTS_TABLE}_au AFTER UPDATE ON bookmarks BEGIN
            INSERT INTO {FTS_TABLE} ({FTS_TABLE}, rowid, tweet_text, username, author_name)
            VALUES ('delete', old.id, old.tweet_text, old.username, old.author_name);
            INSERT INTO {FTS_TABLE} (rowid, tweet_text, username, author_name)
            VALUES (new.id, new.tweet_text, new.username, new.author_name);
        END
        """,
    ),
)

MIGRATIONS: tuple[Migration, ...] = (MIGRATION_1, MIGRATION_2)

SCHEMA_VERSION: int = max(migration.version for migration in MIGRATIONS)

