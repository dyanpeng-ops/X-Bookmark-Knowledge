"""Phase 4 · Step 3 测试：R6 字段二分、内容索引幂等、运行态重置。

覆盖
----
* 分类完整性（DDL 与 `r6_fields` 双向一致；新增列忘归类会失败）
* 内容索引幂等：同 hash 一个字节都不写；变 hash 只改内容列
* **内容更新绝不触碰运行态列**（R6 边界的核心断言）
* 运行态重置：初始态正确、内容索引原样保留、重复重置幂等
* 重建等价：删库 → 重建 → 用同一批 normalized 内容重灌 → 内容索引完全一致，运行态为初始态
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database import r6_fields as r6  # noqa: E402
from src.database.connection import connect  # noqa: E402
from src.database.index_store import CONTENT_UPSERT_FIELDS, IndexStore  # noqa: E402
from src.database.states import (  # noqa: E402
    BookmarkStatus,
    LinkFetchStatus,
    MediaDownloadStatus,
)

NOW = "2026-10-09T15:00:00Z"
HASH_A = "a" * 64
HASH_B = "b" * 64


def content(tweet_id: str, *, text: str = "示例正文", hash_: str = HASH_A) -> dict:
    return dict(
        tweet_id=tweet_id,
        content_hash=hash_,
        username="sample_author",
        author_id="100000001",
        author_name="Sample Author",
        tweet_text=text,
        created_at="2026-09-10T13:26:07Z",
        tweet_url=f"https://x.com/sample_author/status/{tweet_id}",
        conversation_id=tweet_id,
        raw_json_path=f"normalized/{tweet_id}.json",
        markdown_path=f"knowledge/X-Bookmarks/2026/09/20260910-{tweet_id}.md",
    )


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_classification_matches_ddl(self):
        r6.assert_classification_complete(self.conn)  # 不一致会抛 R6ClassificationError

    def test_every_column_has_exactly_one_class(self):
        for table in r6.TABLES:
            for column in r6.columns_for(table, include_structural=True):
                with self.subTest(table=table, column=column):
                    self.assertIn(r6.classify(table, column),
                                  {"content", "runtime", "structural"})

    def test_unclassified_column_is_reported(self):
        self.conn.execute("ALTER TABLE bookmarks ADD COLUMN legacy_note TEXT")
        with self.assertRaises(r6.R6ClassificationError) as ctx:
            r6.assert_classification_complete(self.conn)
        self.assertIn("legacy_note", str(ctx.exception))

    def test_content_hash_column_exists_with_index(self):
        self.assertIn("content_hash", r6.actual_columns(self.conn, "bookmarks"))
        indexes = {row[1] for row in self.conn.execute("PRAGMA index_list(bookmarks)")}
        self.assertIn("idx_bookmarks_content_hash", indexes)

    def test_runtime_columns_have_initial_values(self):
        for table in r6.TABLES:
            for column in r6.RUNTIME_COLUMNS[table]:
                with self.subTest(table=table, column=column):
                    if column in r6.TIMESTAMP_RUNTIME_COLUMNS:
                        continue
                    self.assertIn((table, column), r6.RUNTIME_INITIAL_VALUES)

    def test_timestamp_reset_uses_rebuild_time(self):
        values = dict(r6.runtime_reset_assignments("bookmarks", NOW))
        self.assertEqual(values["first_synced_at"], NOW)
        self.assertEqual(values["last_synced_at"], NOW)
        self.assertEqual(values["status"], "NEW")
        self.assertEqual(values["attempts"], 0)
        self.assertIsNone(values["error_message"])


class ContentIndexTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.store = IndexStore(self.conn)

    def _used(self, tweet_id: str) -> None:
        self.conn.execute(
            "UPDATE bookmarks SET status = ?, attempts = ?, error_message = ? WHERE tweet_id = ?",
            (BookmarkStatus.PROCESSED.value, 2, "boom", tweet_id),
        )

    def test_first_write_inserts_and_returns_inserted(self):
        result = self.store.upsert_content_index(now=NOW, **content("1"))
        self.assertEqual(result.action, "inserted")
        self.assertTrue(result.wrote)
        row = self.conn.execute("SELECT * FROM bookmarks WHERE tweet_id='1'").fetchone()
        self.assertEqual(row["content_hash"], HASH_A)
        self.assertEqual(row["status"], BookmarkStatus.NEW.value)  # 运行态初始值
        self.assertEqual(row["first_synced_at"], NOW)

    def test_same_hash_writes_nothing(self):
        self.store.upsert_content_index(now=NOW, **content("1"))
        self._used("1")
        before = dict(self.conn.execute("SELECT * FROM bookmarks WHERE tweet_id='1'").fetchone())
        result = self.store.upsert_content_index(now="2099-01-01T00:00:00Z", **content("1"))
        after = dict(self.conn.execute("SELECT * FROM bookmarks WHERE tweet_id='1'").fetchone())
        self.assertEqual(result.action, "unchanged")
        self.assertFalse(result.wrote)
        self.assertEqual(before, after)  # 包括状态、时间戳：什么都没动

    def test_changed_hash_updates_content_only(self):
        self.store.upsert_content_index(now=NOW, **content("1"))
        self._used("1")
        result = self.store.upsert_content_index(
            now="2099-01-01T00:00:00Z", **content("1", text="改过的正文", hash_=HASH_B)
        )
        self.assertEqual(result.action, "updated")
        row = self.conn.execute("SELECT * FROM bookmarks WHERE tweet_id='1'").fetchone()
        self.assertEqual(row["content_hash"], HASH_B)
        self.assertEqual(row["tweet_text"], "改过的正文")
        # 运行态必须原样保留（内容刷新不得抹掉状态机记录）
        self.assertEqual(row["status"], BookmarkStatus.PROCESSED.value)
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["error_message"], "boom")
        self.assertEqual(row["first_synced_at"], NOW)  # 未被 2099 覆盖

    def test_runtime_keys_rejected_by_content_api(self):
        with self.assertRaises(ValueError) as ctx:
            self.store.upsert_content_index(
                now=NOW, tweet_id="1", content_hash=HASH_A, status="COMPLETED", attempts=9
            )
        message = str(ctx.exception)
        self.assertIn("status", message)
        self.assertIn("R6", message)

    def test_content_upsert_fields_exclude_tweet_id_and_runtime(self):
        self.assertNotIn("tweet_id", CONTENT_UPSERT_FIELDS)
        for column in r6.RUNTIME_COLUMNS["bookmarks"]:
            self.assertNotIn(column, CONTENT_UPSERT_FIELDS)

    def test_invalid_content_hash_rejected(self):
        for bad in ("", "x" * 64, "a" * 63, "A" * 64):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.store.upsert_content_index(
                        now=NOW, tweet_id="1", content_hash=bad
                    )

    def test_fts_reflects_content_update(self):
        self.store.upsert_content_index(now=NOW, **content("1", text="独特关键词甲"))
        self.store.upsert_content_index(
            now=NOW, **content("1", text="独特关键词乙", hash_=HASH_B)
        )
        hit = self.conn.execute(
            "SELECT rowid FROM bookmarks_fts WHERE bookmarks_fts MATCH '独特关键词乙'"
        ).fetchall()
        self.assertEqual(len(hit), 1)

    def test_legacy_null_hash_is_treated_as_change(self):
        # 迁移 3 之前写入的行 content_hash 为 NULL → 必须被内容写入修正
        self.conn.execute(
            "INSERT INTO bookmarks (tweet_id, first_synced_at, last_synced_at) VALUES (?, ?, ?)",
            ("9", NOW, NOW),
        )
        result = self.store.upsert_content_index(now=NOW, **content("9"))
        self.assertEqual(result.action, "updated")
        row = self.conn.execute("SELECT content_hash FROM bookmarks WHERE tweet_id='9'").fetchone()
        self.assertEqual(row["content_hash"], HASH_A)


class RuntimeResetTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.store = IndexStore(self.conn)
        self.store.upsert_content_index(now=NOW, **content("1"))
        self.store.upsert_content_index(now=NOW, **content("2"))
        self.conn.execute(
            "UPDATE bookmarks SET status=?, attempts=3, error_message='e' WHERE tweet_id='1'",
            (BookmarkStatus.FAILED.value,),
        )
        self.conn.execute(
            "INSERT INTO media (tweet_id, media_key, media_type, source_url, local_path,"
            " download_status, attempts, error_message, first_seen_at, last_updated_at)"
            " VALUES ('1','k','photo','https://a/b.png','assets/b.png',?,2,'x',?,?)",
            (MediaDownloadStatus.DOWNLOADED.value, NOW, NOW),
        )
        self.conn.execute(
            "INSERT INTO external_links (tweet_id, url, fetch_status, attempts, error_message,"
            " first_seen_at, last_updated_at) VALUES ('1','https://a.example',?,1,'y',?,?)",
            (LinkFetchStatus.FETCHED.value, NOW, NOW),
        )

    def test_resets_runtime_to_initial(self):
        summary = self.store.rebuild_runtime_state("2099-05-05T00:00:00Z")
        self.assertEqual(summary.now, "2099-05-05T00:00:00Z")
        self.assertEqual(summary.reset_counts["bookmarks"], 2)
        bookmark = self.conn.execute("SELECT * FROM bookmarks WHERE tweet_id='1'").fetchone()
        self.assertEqual(bookmark["status"], BookmarkStatus.NEW.value)
        self.assertEqual(bookmark["attempts"], 0)
        self.assertIsNone(bookmark["error_message"])
        self.assertEqual(bookmark["first_synced_at"], "2099-05-05T00:00:00Z")
        media = self.conn.execute("SELECT * FROM media").fetchone()
        self.assertEqual(media["download_status"], MediaDownloadStatus.PENDING.value)
        self.assertEqual(media["attempts"], 0)
        link = self.conn.execute("SELECT * FROM external_links").fetchone()
        self.assertEqual(link["fetch_status"], LinkFetchStatus.PENDING.value)

    def test_reset_preserves_content_index(self):
        before = self.store.content_index_snapshot()
        self.store.rebuild_runtime_state("2099-05-05T00:00:00Z")
        self.assertEqual(self.store.content_index_snapshot(), before)

    def test_reset_is_idempotent(self):
        self.store.rebuild_runtime_state(NOW)
        first = dict(self.conn.execute("SELECT * FROM bookmarks WHERE tweet_id='1'").fetchone())
        self.store.rebuild_runtime_state(NOW)
        second = dict(self.conn.execute("SELECT * FROM bookmarks WHERE tweet_id='1'").fetchone())
        self.assertEqual(first, second)


class RebuildEquivalenceTests(unittest.TestCase):
    """`rebuild-index` 的核心承诺：删库 → 用同一批内容重建 → 内容索引完全一致。"""

    def _seed_content(self, conn: sqlite3.Connection) -> None:
        """只灌**内容索引**（模拟 rebuild-index 扫 normalized/*.json）。"""

        store = IndexStore(conn)
        for index in range(1, 4):
            store.upsert_content_index(now=NOW, **content(str(index), text=f"正文{index}"))

    def _mark_runtime(self, conn: sqlite3.Connection) -> None:
        """运行态推进（这一步**没有**重建来源，重建后必然丢失）。"""

        conn.execute(
            "UPDATE bookmarks SET status='COMPLETED', attempts=7, error_message='gone'"
        )

    def test_content_index_survives_rebuild_runtime_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "index.db"

            conn = connect(db_path)
            self._seed_content(conn)
            self._mark_runtime(conn)  # 重建前：运行态已推进（COMPLETED / 7 / 'gone'）
            snapshot_before = IndexStore(conn).content_index_snapshot()
            runtime_before = dict(
                conn.execute("SELECT * FROM bookmarks WHERE tweet_id='1'").fetchone()
            )
            self.assertEqual(runtime_before["status"], "COMPLETED")
            conn.close()

            db_path.unlink()  # 删库

            conn = connect(db_path)  # 重建
            self.assertEqual(IndexStore(conn).content_index_snapshot(), ())  # 空库
            self._seed_content(conn)  # 只扫 normalized 重建内容索引
            store = IndexStore(conn)
            self.assertEqual(store.content_index_snapshot(), snapshot_before)

            # 运行态回到初始态：先前的 COMPLETED / 7 / 'gone' 无重建来源，R6 已声明可接受
            row = conn.execute("SELECT * FROM bookmarks WHERE tweet_id='1'").fetchone()
            self.assertEqual(row["status"], BookmarkStatus.NEW.value)
            self.assertEqual(row["attempts"], 0)
            self.assertIsNone(row["error_message"])
            # 且内容列逐项与重建前一致
            for column in r6.CONTENT_COLUMNS["bookmarks"]:
                with self.subTest(column=column):
                    self.assertEqual(row[column], runtime_before[column])
            conn.close()

    def test_rebuild_reset_is_what_restores_initial_state(self):
        """显式 `rebuild_runtime_state` 与"删库重建"得到同一初始态。"""

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "index.db"
            conn = connect(db_path)
            self._seed_content(conn)
            self._mark_runtime(conn)
            IndexStore(conn).rebuild_runtime_state(NOW)
            row = conn.execute("SELECT * FROM bookmarks WHERE tweet_id='1'").fetchone()
            self.assertEqual(row["status"], BookmarkStatus.NEW.value)
            self.assertEqual(row["attempts"], 0)
            conn.close()


if __name__ == "__main__":
    unittest.main()
