"""事务辅助（Phase 4）。

数据库连接使用 ``isolation_level=None``，因此事务由本模块显式控制，
以保证"写操作要么整体成功、要么整体回滚"。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """在事务中执行代码块；异常时回滚并重新抛出原异常。

    使用 ``BEGIN IMMEDIATE`` 以便尽早取得写锁，避免并发写入时的延迟失败。
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def in_transaction(conn: sqlite3.Connection) -> bool:
    """当前连接是否处于事务中（供断言与调试使用）。"""
    return bool(conn.in_transaction)
