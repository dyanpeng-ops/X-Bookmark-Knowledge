"""Phase 4 · Step 3：内容索引写入与运行态重置（R6 语义落地）。

职责
----
* **内容索引幂等写入**：以 ``content_hash`` 判断「内容是否已变」——
  未变则**一个字节都不写**（运行态、时间戳、FTS 全部保持不动）；
  变了只更新**内容索引列**，**绝不触碰运行态列**（`status`/`attempts`/… 归状态机管）。
* **重建语义**：`rebuild_runtime_state` 把运行态列重置为初始态（R6 §6.3.1 表二），
  内容索引列原样保留。

为什么内容更新不能顺手写运行态
------------------------------
若 `process` 更新内容时把 `status` 一起写回，状态机的"重试/失败"记录会被内容刷新抹掉，
`rebuild-index` 的「内容可重建、运行态重置」边界也就不复存在。因此本模块的 UPDATE
**只包含内容索引列**，并由测试守卫。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from . import r6_fields as r6
from .transaction import transaction

__all__ = ["IndexStore", "IndexUpsertResult", "RebuildSummary", "CONTENT_UPSERT_FIELDS"]

#: 允许由内容侧写入的 bookmarks 列（= 内容索引列去掉主键 `tweet_id`）。
CONTENT_UPSERT_FIELDS: tuple[str, ...] = tuple(
    column for column in r6.CONTENT_COLUMNS["bookmarks"] if column != "tweet_id"
)


@dataclass(frozen=True, slots=True)
class IndexUpsertResult:
    """一次内容索引写入的结果。"""

    tweet_id: str
    action: str  # inserted | unchanged | updated
    wrote: bool

    @property
    def skipped(self) -> bool:
        return self.action == "unchanged"


@dataclass(frozen=True, slots=True)
class RebuildSummary:
    """运行态重置的统计（`rebuild-index` 用）。"""

    reset_counts: Mapping[str, int]
    now: str

    @property
    def total(self) -> int:
        return sum(self.reset_counts.values())


class IndexStore:
    """薄封装：把 R6 的两类语义变成两个明确的方法。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── 内容索引 ────────────────────────────────────────────────────────────

    def upsert_content_index(
        self,
        *,
        tweet_id: str,
        content_hash: str,
        now: str,
        **content: Any,
    ) -> IndexUpsertResult:
        """幂等写入一条书签的内容索引。

        ``content`` 只接受 :data:`CONTENT_UPSERT_FIELDS` 里的键；出现运行态键直接报错
        （把"不能写运行态"变成接口约束，而不是靠自觉）。
        """

        _require_tweet_id(tweet_id)
        _require_content_hash(content_hash)
        illegal = sorted(set(content) - set(CONTENT_UPSERT_FIELDS))
        if illegal:
            raise ValueError(
                f"运行态/未知字段不得经内容索引写入（R6）: {illegal}；"
                f"允许的键: {list(CONTENT_UPSERT_FIELDS)}"
            )

        existing = self._conn.execute(
            "SELECT content_hash FROM bookmarks WHERE tweet_id = ?", (tweet_id,)
        ).fetchone()

        if existing is not None and existing["content_hash"] == content_hash:
            # 内容未变：不写盘（运行态、时间戳、FTS 触发器等一律不动）
            return IndexUpsertResult(tweet_id, "unchanged", wrote=False)

        payload = {"content_hash": content_hash, **content}
        columns = list(payload)
        with transaction(self._conn):
            if existing is None:
                defaults = r6.runtime_insert_defaults("bookmarks", now)
                all_columns = ["tweet_id", *columns, *defaults]
                values = [tweet_id, *payload.values(), *defaults.values()]
                placeholders = ", ".join("?" for _ in all_columns)
                self._conn.execute(
                    f"INSERT INTO bookmarks ({', '.join(all_columns)}) VALUES ({placeholders})",
                    values,
                )
                return IndexUpsertResult(tweet_id, "inserted", wrote=True)

            # 只更新内容索引列（白名单由 CONTENT_UPSERT_FIELDS 保证）
            assignments = ", ".join(f"{column} = ?" for column in columns)
            self._conn.execute(
                f"UPDATE bookmarks SET {assignments} WHERE tweet_id = ?",
                [*payload.values(), tweet_id],
            )
        return IndexUpsertResult(tweet_id, "updated", wrote=True)

    def content_index_snapshot(self) -> tuple[dict[str, Any], ...]:
        """按 ``tweet_id`` 排序导出内容索引（供"重建前后一致"验证）。"""

        columns = ", ".join(r6.CONTENT_COLUMNS["bookmarks"])
        rows = self._conn.execute(
            f"SELECT {columns} FROM bookmarks ORDER BY tweet_id"
        ).fetchall()
        return tuple({column: row[column] for column in r6.CONTENT_COLUMNS["bookmarks"]}
                     for row in rows)

    # ── 运行态 ──────────────────────────────────────────────────────────────

    def rebuild_runtime_state(self, now: str) -> RebuildSummary:
        """把三张表的运行态列重置为初始态；内容索引列保持不变。"""

        counts: dict[str, int] = {}
        with transaction(self._conn):
            for table in r6.TABLES:
                assignments = r6.runtime_reset_assignments(table, now)
                setters = ", ".join(f"{column} = ?" for column, _ in assignments)
                values = [value for _, value in assignments]
                cursor = self._conn.execute(f"UPDATE {table} SET {setters}", values)
                counts[table] = cursor.rowcount
        return RebuildSummary(reset_counts=counts, now=now)


def _require_tweet_id(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tweet_id must be a non-empty string")


def _require_content_hash(value: Any) -> None:
    if not isinstance(value, str) or len(value) != 64 or not all(
        ch in "0123456789abcdef" for ch in value
    ):
        raise ValueError("content_hash must be a 64-char lowercase hex digest")
