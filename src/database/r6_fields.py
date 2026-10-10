"""R6：SQLite 字段二分（`ARCHITECTURE.md` §6.3.1 / 决策 R6）。

背景
----
`§6.3` 曾承诺「SQLite 完全可重建（删库后扫 `normalized/*.json` + Markdown 即可）」，
但 `models.py` 里存着大量**没有重建来源**的运行态字段（`status` / `attempts` /
`error_message` / `*_at` / `download_status` / `fetch_status`）。两者冲突，R6 的裁决是
**把字段分成两类，重建语义不同**：

============== ============================================== ================
类别            字段                                            重建后
============== ============================================== ================
内容索引         `tweet_id`/`content_hash`/`path`/可搜索字段     由 `normalized` 重建，**不可丢失**
运行态          `status`/`attempts`/`error_message`/`*_at`/…    **重置为初始态**（可接受）
结构列          代理主键 `id`                                  由 SQLite 重新分配（不属两类）
============== ============================================== ================

运行态丢失为何可接受
--------------------
重建后状态机从 `NEW` 重走一遍，但 `sync`/`process`/`media`/`links` 一律以
`content_hash` 与「本地文件是否存在」做幂等判断，因此**不会重复处理、不会重复抓取**；
`attempts`/`error_message` 只是排障辅助信息。

本模块是该分类的**唯一真实来源**：DDL 变更后若忘记归类，``assert_classification_complete``
会在测试中直接报错，避免"新增字段悄悄变成无法重建"。
"""

from __future__ import annotations

import sqlite3
from typing import Any

__all__ = [
    "R6ClassificationError",
    "CONTENT_COLUMNS",
    "RUNTIME_COLUMNS",
    "STRUCTURAL_COLUMNS",
    "RUNTIME_INITIAL_VALUES",
    "TIMESTAMP_RUNTIME_COLUMNS",
    "TABLES",
    "classify",
    "columns_for",
    "assert_classification_complete",
    "runtime_reset_assignments",
    "runtime_insert_defaults",
]

#: 内容索引：可由 `normalized/*.json`（+ Markdown + assets 命名约定）重建。
CONTENT_COLUMNS: dict[str, tuple[str, ...]] = {
    "bookmarks": (
        "tweet_id",
        "content_hash",
        "author_id",
        "username",
        "author_name",
        "tweet_text",
        "created_at",
        "tweet_url",
        "conversation_id",
        "raw_json_path",
        "markdown_path",
    ),
    "media": ("tweet_id", "media_key", "media_type", "source_url", "local_path"),
    "external_links": (
        "tweet_id",
        "url",
        "resolved_url",
        "title",
        "domain",
        "content_path",
    ),
}

#: 运行态：**无重建来源**，`rebuild-index` 时重置为初始态。
RUNTIME_COLUMNS: dict[str, tuple[str, ...]] = {
    "bookmarks": ("status", "attempts", "first_synced_at", "last_synced_at", "error_message"),
    "media": (
        "download_status",
        "attempts",
        "error_message",
        "first_seen_at",
        "last_updated_at",
    ),
    "external_links": (
        "fetch_status",
        "attempts",
        "error_message",
        "first_seen_at",
        "last_updated_at",
    ),
}

#: 结构列：代理主键，重建时由 SQLite 重新分配，不属于 R6 的两类语义。
STRUCTURAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "bookmarks": ("id",),
    "media": ("id",),
    "external_links": ("id",),
}

#: 运行态的静态初始值（时间戳列见 `TIMESTAMP_RUNTIME_COLUMNS`，用重建时刻填充）。
RUNTIME_INITIAL_VALUES: dict[tuple[str, str], Any] = {
    ("bookmarks", "status"): "NEW",
    ("bookmarks", "attempts"): 0,
    ("bookmarks", "error_message"): None,
    ("media", "download_status"): "PENDING",
    ("media", "attempts"): 0,
    ("media", "error_message"): None,
    ("external_links", "fetch_status"): "PENDING",
    ("external_links", "attempts"): 0,
    ("external_links", "error_message"): None,
}

#: NOT NULL 的时间戳类运行态列：重建时置为**重建时刻**（不代表首次采集时间）。
TIMESTAMP_RUNTIME_COLUMNS: frozenset[str] = frozenset(
    {"first_synced_at", "last_synced_at", "first_seen_at", "last_updated_at"}
)

TABLES: tuple[str, ...] = tuple(CONTENT_COLUMNS)

CLASS_CONTENT = "content"
CLASS_RUNTIME = "runtime"
CLASS_STRUCTURAL = "structural"


class R6ClassificationError(RuntimeError):
    """DDL 中的列未按 R6 归类（新增字段忘了归类时触发）。"""


def columns_for(table: str, *, include_structural: bool = False) -> tuple[str, ...]:
    """返回某表的内容索引 + 运行态列（默认不含结构列）。"""

    _require_table(table)
    columns = CONTENT_COLUMNS[table] + RUNTIME_COLUMNS[table]
    return columns + STRUCTURAL_COLUMNS[table] if include_structural else columns


def classify(table: str, column: str) -> str:
    """返回 ``content`` / ``runtime`` / ``structural``；未知列抛错。"""

    _require_table(table)
    if column in CONTENT_COLUMNS[table]:
        return CLASS_CONTENT
    if column in RUNTIME_COLUMNS[table]:
        return CLASS_RUNTIME
    if column in STRUCTURAL_COLUMNS[table]:
        return CLASS_STRUCTURAL
    raise R6ClassificationError(f"unclassified column: {table}.{column}")


def actual_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    """读取真实表的列名（`PRAGMA table_info`）。"""

    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return tuple(row[1] for row in rows)


def assert_classification_complete(conn: sqlite3.Connection) -> None:
    """校验「DDL 里的列」与「本模块的归类」完全一致（双向）。

    任一侧多出/缺少列都报错——这是防止 DDL 演进后 R6 语义悄悄失效的护栏。
    """

    problems: list[str] = []
    for table in TABLES:
        actual = set(actual_columns(conn, table))
        declared = set(columns_for(table, include_structural=True))
        unclassified = sorted(actual - declared)
        missing = sorted(declared - actual)
        if unclassified:
            problems.append(f"{table}: 未归类列 {unclassified}")
        if missing:
            problems.append(f"{table}: 归类了不存在的列 {missing}")
        duplicated = [
            column
            for column in actual
            if sum(
                column in group
                for group in (
                    CONTENT_COLUMNS[table],
                    RUNTIME_COLUMNS[table],
                    STRUCTURAL_COLUMNS[table],
                )
            )
            != 1
        ]
        if duplicated:
            problems.append(f"{table}: 列被重复归类或漏归类 {sorted(duplicated)}")
    if problems:
        raise R6ClassificationError("R6 分类与 DDL 不一致 → " + "；".join(problems))


def runtime_reset_assignments(table: str, now: str) -> tuple[tuple[str, Any], ...]:
    """返回 ``rebuild`` 时该表运行态列的 ``(column, value)`` 赋值（参数化用）。"""

    _require_table(table)
    assignments: list[tuple[str, Any]] = []
    for column in RUNTIME_COLUMNS[table]:
        if column in TIMESTAMP_RUNTIME_COLUMNS:
            assignments.append((column, now))
        else:
            assignments.append((column, RUNTIME_INITIAL_VALUES[(table, column)]))
    return tuple(assignments)


def runtime_insert_defaults(table: str, now: str) -> dict[str, Any]:
    """新建内容索引行时运行态列的初始值。"""

    return dict(runtime_reset_assignments(table, now))


def _require_table(table: str) -> None:
    if table not in CONTENT_COLUMNS:
        raise R6ClassificationError(f"unknown table: {table!r}")
