"""数据库连接创建与初始化（Phase 4）。

约定
----
* 连接一律使用 ``isolation_level=None``，事务由 ``transaction`` 显式控制。
* 打开时设置 ``foreign_keys=ON``（保证 media/external_links 的级联删除生效）、
  ``busy_timeout``（避免并发写入直接报错）；文件库额外启用 WAL。
* ``ensure_schema=True``（默认）会在连接时自动应用迁移，因此调用方无需关心版本。
* 本模块不硬编码任何绝对路径：数据库位置由调用方通过配置解析后传入。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .migrations import apply_migrations, current_version, is_up_to_date
from .schema import SCHEMA_VERSION

MEMORY = ":memory:"
DEFAULT_BUSY_TIMEOUT_MS = 5000


def connect(
    db_path: str | Path,
    *,
    ensure_schema: bool = True,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> sqlite3.Connection:
    """打开（必要时创建）数据库并返回连接。

    ``db_path`` 为 ``":memory:"`` 时创建内存库（仅用于测试），不设 WAL。
    父目录不存在时会自动创建——因此调用方必须传入已由配置解析出的路径。
    """
    target = str(db_path)
    if target != MEMORY:
        Path(target).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(target, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if busy_timeout_ms > 0:
        conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    if target != MEMORY:
        conn.execute("PRAGMA journal_mode = WAL")

    if ensure_schema:
        apply_migrations(conn)
    return conn


def schema_status(conn: sqlite3.Connection) -> dict[str, object]:
    """返回 schema 版本信息，供 ``doctor`` / ``status`` 命令展示。"""
    return {
        "current_version": current_version(conn),
        "expected_version": SCHEMA_VERSION,
        "up_to_date": is_up_to_date(conn),
    }
