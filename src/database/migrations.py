"""schema 版本读取与迁移执行（Phase 4）。

``schema_version`` 表记录已应用的版本；``apply_migrations`` 在**单个事务**内顺序应用
所有未执行的迁移，因此失败时不会留下"迁移只做了一半"的数据库。

版本号约定：从 1 开始、严格递增、声明顺序即执行顺序（由 ``_validate`` 校验）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from .clock import utc_now_iso
from .schema import MIGRATIONS, SCHEMA_VERSION, Migration
from .transaction import transaction

VERSION_TABLE = "schema_version"


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """表或虚拟表是否存在（FTS5 表在 sqlite_master 中也是 table 类型）。"""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def recorded_versions(conn: sqlite3.Connection) -> list[int]:
    """返回已记录的版本号（升序）；未初始化时返回空列表。"""
    if not table_exists(conn, VERSION_TABLE):
        return []
    rows = conn.execute(f"SELECT version FROM {VERSION_TABLE} ORDER BY version").fetchall()
    return [int(row[0]) for row in rows]


def current_version(conn: sqlite3.Connection) -> int:
    """当前 schema 版本；未初始化时返回 0。"""
    versions = recorded_versions(conn)
    return versions[-1] if versions else 0


def pending_migrations(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> list[Migration]:
    """按版本升序返回尚未应用的迁移。"""
    applied = set(recorded_versions(conn))
    return [
        migration
        for migration in sorted(migrations, key=lambda item: item.version)
        if migration.version not in applied
    ]


def apply_migrations(
    conn: sqlite3.Connection,
    *,
    migrations: Sequence[Migration] = MIGRATIONS,
    now: object | None = None,
) -> int:
    """应用所有未执行的迁移并返回最终版本号。

    已是最新时直接返回当前版本，不产生写入（幂等）。
    """
    _validate(migrations)
    pending = pending_migrations(conn, migrations)
    if not pending:
        return current_version(conn)

    stamp = utc_now_iso(now)  # type: ignore[arg-type]
    with transaction(conn):
        for migration in pending:
            for statement in migration.statements:
                conn.execute(statement)
            conn.execute(
                f"INSERT OR REPLACE INTO {VERSION_TABLE} (version, applied_at) VALUES (?, ?)",
                (migration.version, stamp),
            )
    return current_version(conn)


def is_up_to_date(conn: sqlite3.Connection) -> bool:
    """schema 是否已达到代码声明的最新版本。"""
    return current_version(conn) == SCHEMA_VERSION


def _validate(migrations: Sequence[Migration]) -> None:
    versions = [migration.version for migration in migrations]
    if not versions:
        raise ValueError("no migrations declared")
    if len(set(versions)) != len(versions):
        raise ValueError("duplicate migration versions declared")
    expected = list(range(1, len(versions) + 1))
    if versions != expected:
        raise ValueError(f"migration versions must be 1..N in order, got {versions}")
