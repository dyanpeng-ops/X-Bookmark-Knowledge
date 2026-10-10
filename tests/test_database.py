"""src/database 的验收测试（Phase 4）。

覆盖范围（对应 `tasks/CURRENT.md` 第 4 项）
------------------------------------------
初始化、迁移、事务回滚、唯一约束、状态流转、FTS5；
并补充本项目核心要求：**同一任务跑两次不产生重复数据**（幂等 upsert 与计数不变）。

约束
----
* 不访问网络；不读写真实 `knowledge/` 或上游目录。
* 每个测试使用独立临时目录，结束后自动清理。

运行方式（项目根目录）::

    .venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database import (  # noqa: E402  (path bootstrap must run first)
    ALL_STATUS_VALUES,
    MIGRATIONS,
    SCHEMA_VERSION,
    BookmarkNotFound,
    BookmarkRecord,
    BookmarkRepository,
    BookmarkStatus,
    ExternalLinkRecord,
    InvalidStateTransition,
    MediaRecord,
    Migration,
    apply_migrations,
    connect,
    current_version,
    is_up_to_date,
    parse_iso,
    parse_status,
    pending_migrations,
    recorded_versions,
    table_exists,
    transaction,
    utc_now_iso,
)
from src.database.schema import CORE_TABLES, FTS_TABLE, MIGRATION_1  # noqa: E402
from src.database.states import is_terminal, next_status  # noqa: E402

T1 = datetime(2026, 9, 15, 8, 0, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 9, 15, 9, 30, 0, tzinfo=timezone.utc)


class DatabaseTestCase(unittest.TestCase):
    """基类：提供临时数据库、连接与 repository。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "state" / "bookmarks.db"
        self.conn = connect(self.db_path)
        self.addCleanup(self.conn.close)
        self.repo = BookmarkRepository(self.conn)

    def add_bookmark(self, tweet_id: str = "1000000000000000001", **fields: object) -> BookmarkRecord:
        """插入一条书签并返回库中记录。"""
        record = BookmarkRecord(tweet_id=tweet_id, **fields)  # type: ignore[arg-type]
        self.repo.upsert_bookmark(record)
        return self.repo.require_bookmark(tweet_id)

    def table_names(self) -> set[str]:
        rows = self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {str(row[0]) for row in rows}


class InitializationTests(DatabaseTestCase):
    """初始化：文件、目录、版本、表与索引、外键开关。"""

    def test_connect_creates_database_file_and_parent_directory(self):
        self.assertTrue(self.db_path.exists())
        self.assertTrue(self.db_path.parent.is_dir())

    def test_connect_reaches_latest_schema_version(self):
        self.assertEqual(current_version(self.conn), SCHEMA_VERSION)
        self.assertTrue(is_up_to_date(self.conn))

    def test_core_tables_and_fts_table_exist(self):
        names = self.table_names()
        for table in CORE_TABLES:
            self.assertIn(table, names)
        self.assertIn(FTS_TABLE, names)

    def test_expected_indexes_exist(self):
        rows = self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        names = {str(row[0]) for row in rows}
        for expected in (
            "idx_bookmarks_status",
            "idx_bookmarks_created_at",
            "idx_bookmarks_conversation",
            "idx_media_status",
            "idx_external_links_status",
            "idx_external_links_domain",
        ):
            self.assertIn(expected, names)

    def test_foreign_keys_pragma_is_enabled(self):
        row = self.conn.execute("PRAGMA foreign_keys").fetchone()
        self.assertEqual(int(row[0]), 1)

    def test_records_every_migration_version(self):
        self.assertEqual(recorded_versions(self.conn), [m.version for m in MIGRATIONS])


class MigrationTests(DatabaseTestCase):
    """迁移：幂等、旧库升级、失败回滚、版本声明校验。"""

    def test_apply_migrations_is_idempotent(self):
        before = recorded_versions(self.conn)
        again = apply_migrations(self.conn)
        self.assertEqual(again, SCHEMA_VERSION)
        self.assertEqual(recorded_versions(self.conn), before)

    def test_pending_migrations_is_empty_for_fresh_database(self):
        self.assertEqual(pending_migrations(self.conn), [])

    def test_upgrades_legacy_v1_database_to_latest(self):
        legacy_path = Path(self._tmp.name) / "legacy.db"
        legacy = sqlite3.connect(str(legacy_path), isolation_level=None)
        try:
            for statement in MIGRATION_1.statements:
                legacy.execute(statement)
            legacy.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (1, utc_now_iso(T1)),
            )
            self.assertEqual(current_version(legacy), 1)
            self.assertFalse(table_exists(legacy, "media"))
            # 版本无关断言：v1 之后**所有**待应用迁移（原先硬编码 [2]，
            # 一旦新增迁移就会误报失败——Phase 4 Step 3 加 migration 3 时暴露）
            self.assertEqual(
                [migration.version for migration in pending_migrations(legacy)],
                [migration.version for migration in MIGRATIONS if migration.version > 1],
            )

            upgraded = apply_migrations(legacy)
            self.assertEqual(upgraded, SCHEMA_VERSION)
            self.assertTrue(table_exists(legacy, "media"))
            self.assertTrue(table_exists(legacy, "external_links"))
            self.assertTrue(table_exists(legacy, FTS_TABLE))
        finally:
            legacy.close()

    def test_failed_migration_rolls_back_completely(self):
        broken = Migration(
            version=SCHEMA_VERSION + 1,
            name="broken migration",
            statements=(
                "CREATE TABLE should_not_exist (id INTEGER PRIMARY KEY)",
                "THIS IS NOT VALID SQL",
            ),
        )
        with self.assertRaises(sqlite3.OperationalError):
            apply_migrations(self.conn, migrations=(*MIGRATIONS, broken))
        self.assertEqual(current_version(self.conn), SCHEMA_VERSION)
        self.assertFalse(table_exists(self.conn, "should_not_exist"))

    def test_duplicate_versions_are_rejected(self):
        duplicate = Migration(version=1, name="duplicate", statements=("SELECT 1",))
        with self.assertRaises(ValueError):
            apply_migrations(self.conn, migrations=(*MIGRATIONS, duplicate))

    def test_migration_versions_must_start_at_one(self):
        gap = Migration(version=5, name="gap", statements=("SELECT 1",))
        with self.assertRaises(ValueError):
            apply_migrations(self.conn, migrations=(gap,))


class ConstraintTests(DatabaseTestCase):
    """唯一约束与 CHECK 约束。"""

    def test_tweet_id_must_be_unique(self):
        self.add_bookmark("555")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO bookmarks (tweet_id, first_synced_at, last_synced_at) "
                "VALUES (?, ?, ?)",
                ("555", utc_now_iso(T1), utc_now_iso(T1)),
            )

    def test_bookmark_status_check_constraint(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO bookmarks (tweet_id, status, first_synced_at, last_synced_at) "
                "VALUES (?, ?, ?, ?)",
                ("777", "BOGUS", utc_now_iso(T1), utc_now_iso(T1)),
            )

    def test_media_status_check_constraint(self):
        self.add_bookmark("556")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO media (tweet_id, media_key, download_status, first_seen_at, "
                "last_updated_at) VALUES (?, ?, ?, ?, ?)",
                ("556", "m1", "BOGUS", utc_now_iso(T1), utc_now_iso(T1)),
            )

    def test_new_bookmark_defaults(self):
        record = self.add_bookmark("557")
        self.assertEqual(record.status, BookmarkStatus.NEW.value)
        self.assertEqual(record.attempts, 0)
        self.assertIsNone(record.error_message)
        self.assertEqual(record.first_synced_at, record.last_synced_at)


class TransactionTests(DatabaseTestCase):
    """事务：提交持久化、异常回滚、BaseException 也回滚、无残留事务。"""

    def test_commit_persists_writes(self):
        self.add_bookmark("1001")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE bookmarks SET tweet_text = ? WHERE tweet_id = ?",
                ("kept", "1001"),
            )
        self.assertEqual(self.repo.require_bookmark("1001").tweet_text, "kept")

    def test_rollback_discards_writes(self):
        self.add_bookmark("1000")
        with self.assertRaises(RuntimeError):
            with transaction(self.conn):
                self.conn.execute(
                    "UPDATE bookmarks SET tweet_text = ? WHERE tweet_id = ?",
                    ("mutated", "1000"),
                )
                raise RuntimeError("boom")
        self.assertIsNone(self.repo.require_bookmark("1000").tweet_text)
        self.assertEqual(self.repo.count_bookmarks(), 1)

    def test_rollback_on_keyboard_interrupt(self):
        self.add_bookmark("1002")
        with self.assertRaises(KeyboardInterrupt):
            with transaction(self.conn):
                self.conn.execute("DELETE FROM bookmarks")
                raise KeyboardInterrupt
        self.assertEqual(self.repo.count_bookmarks(), 1)

    def test_no_transaction_left_open_after_failure(self):
        with self.assertRaises(ValueError):
            with transaction(self.conn):
                raise ValueError("x")
        self.assertFalse(self.conn.in_transaction)


class StateMachineTests(DatabaseTestCase):
    """状态流转：happy path、跳级拒绝、失败重入、终态。"""

    def test_happy_path_transitions(self):
        self.add_bookmark("2000")
        for status in ("COLLECTED", "PROCESSED", "ENRICHED", "COMPLETED"):
            self.assertEqual(self.repo.set_status("2000", status).status, status)

    def test_next_status_chain(self):
        self.assertEqual(next_status("NEW"), BookmarkStatus.COLLECTED)
        self.assertEqual(next_status("COLLECTED"), BookmarkStatus.PROCESSED)
        self.assertEqual(next_status("PROCESSED"), BookmarkStatus.ENRICHED)
        self.assertEqual(next_status("ENRICHED"), BookmarkStatus.COMPLETED)
        self.assertIsNone(next_status("COMPLETED"))
        self.assertIsNone(next_status("FAILED"))

    def test_skipping_a_state_is_rejected(self):
        self.add_bookmark("2001")
        with self.assertRaises(InvalidStateTransition):
            self.repo.set_status("2001", "COMPLETED")
        self.assertEqual(self.repo.require_bookmark("2001").status, BookmarkStatus.NEW.value)

    def test_invalid_transition_writes_nothing(self):
        self.add_bookmark("2002", tweet_text="original")
        with self.assertRaises(InvalidStateTransition):
            self.repo.set_status("2002", "ENRICHED", error_message="should not persist")
        record = self.repo.require_bookmark("2002")
        self.assertEqual(record.status, BookmarkStatus.NEW.value)
        self.assertIsNone(record.error_message)

    def test_same_status_is_a_noop(self):
        self.add_bookmark("2003")
        self.assertEqual(self.repo.set_status("2003", "NEW").status, BookmarkStatus.NEW.value)

    def test_failed_state_can_reenter_pipeline(self):
        self.add_bookmark("2004")
        failed = self.repo.record_error("2004", "network timeout")
        self.assertEqual(failed.status, BookmarkStatus.FAILED.value)
        self.assertEqual(failed.error_message, "network timeout")
        self.assertEqual(failed.attempts, 1)
        self.assertEqual(self.repo.set_status("2004", "COLLECTED").status, "COLLECTED")

    def test_completed_is_terminal(self):
        self.add_bookmark("2005")
        for status in ("COLLECTED", "PROCESSED", "ENRICHED", "COMPLETED"):
            self.repo.set_status("2005", status)
        self.assertTrue(is_terminal("COMPLETED"))
        with self.assertRaises(InvalidStateTransition):
            self.repo.set_status("2005", "PROCESSED")

    def test_success_transition_clears_previous_error(self):
        self.add_bookmark("2007")
        self.repo.record_error("2007", "temporary failure")
        self.assertIsNone(self.repo.set_status("2007", "COLLECTED").error_message)

    def test_error_message_is_truncated(self):
        self.add_bookmark("2006")
        record = self.repo.record_error("2006", "x" * 5000)
        self.assertLessEqual(len(record.error_message or ""), 1000)

    def test_parse_status_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            parse_status("NOPE")

    def test_set_status_on_missing_bookmark_raises(self):
        with self.assertRaises(BookmarkNotFound):
            self.repo.set_status("does-not-exist", "COLLECTED")


class UpsertIdempotencyTests(DatabaseTestCase):
    """幂等：同一任务跑两次不产生重复数据，也不重置处理状态。"""

    def test_first_upsert_creates_record(self):
        result = self.repo.upsert_bookmark(
            BookmarkRecord(tweet_id="3000", tweet_text="hello", username="alice"),
            now=T1,
        )
        self.assertTrue(result.created)
        self.assertEqual(result.record.status, BookmarkStatus.NEW.value)
        self.assertEqual(result.record.first_synced_at, "2026-09-15T08:00:00Z")
        self.assertEqual(result.record.last_synced_at, "2026-09-15T08:00:00Z")
        self.assertEqual(self.repo.count_bookmarks(), 1)

    def test_second_upsert_is_idempotent(self):
        record = BookmarkRecord(tweet_id="3001", tweet_text="hello")
        self.repo.upsert_bookmark(record, now=T1)
        self.repo.set_status("3001", "COLLECTED")
        self.repo.set_status("3001", "PROCESSED")

        again = self.repo.upsert_bookmark(record, now=T2)
        self.assertFalse(again.created)
        self.assertFalse(again.changed)
        self.assertEqual(self.repo.count_bookmarks(), 1)
        self.assertEqual(again.record.status, "PROCESSED")
        self.assertEqual(again.record.first_synced_at, "2026-09-15T08:00:00Z")
        self.assertEqual(again.record.last_synced_at, "2026-09-15T09:30:00Z")

    def test_upsert_preserves_error_and_attempts(self):
        self.repo.upsert_bookmark(BookmarkRecord(tweet_id="3002", tweet_text="a"), now=T1)
        self.repo.record_error("3002", "boom")
        again = self.repo.upsert_bookmark(BookmarkRecord(tweet_id="3002", tweet_text="a"), now=T2)
        self.assertEqual(again.record.status, BookmarkStatus.FAILED.value)
        self.assertEqual(again.record.attempts, 1)
        self.assertEqual(again.record.error_message, "boom")

    def test_upsert_reports_content_change(self):
        self.repo.upsert_bookmark(BookmarkRecord(tweet_id="3003", tweet_text="old"), now=T1)
        result = self.repo.upsert_bookmark(
            BookmarkRecord(tweet_id="3003", tweet_text="new"), now=T2
        )
        self.assertFalse(result.created)
        self.assertTrue(result.changed)
        self.assertEqual(result.record.tweet_text, "new")

    def test_upsert_ignores_none_fields(self):
        self.repo.upsert_bookmark(
            BookmarkRecord(tweet_id="3004", tweet_text="keep me", username="alice"), now=T1
        )
        result = self.repo.upsert_bookmark(
            BookmarkRecord(tweet_id="3004", author_name="Alice"), now=T2
        )
        self.assertEqual(result.record.tweet_text, "keep me")
        self.assertEqual(result.record.username, "alice")
        self.assertEqual(result.record.author_name, "Alice")

    def test_existing_status_is_not_reset_by_payload_status(self):
        self.repo.upsert_bookmark(BookmarkRecord(tweet_id="3005"), now=T1)
        for status in ("COLLECTED", "PROCESSED", "ENRICHED", "COMPLETED"):
            self.repo.set_status("3005", status)
        again = self.repo.upsert_bookmark(BookmarkRecord(tweet_id="3005", status="NEW"), now=T2)
        self.assertEqual(again.record.status, BookmarkStatus.COMPLETED.value)

    def test_repeated_sync_reports_zero_new(self):
        payload = [BookmarkRecord(tweet_id=f"4{i}", tweet_text=f"text {i}") for i in range(5)]
        first_new = sum(1 for item in payload if self.repo.upsert_bookmark(item, now=T1).created)
        second_new = sum(1 for item in payload if self.repo.upsert_bookmark(item, now=T2).created)
        self.assertEqual((first_new, second_new), (5, 0))
        self.assertEqual(self.repo.count_bookmarks(), 5)

    def test_upsert_rejects_empty_tweet_id(self):
        with self.assertRaises(ValueError):
            self.repo.upsert_bookmark(BookmarkRecord(tweet_id="   "))

    def test_upsert_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            self.repo.upsert_bookmark(BookmarkRecord(tweet_id="3006", status="NOPE"))

    def test_count_by_status_covers_all_statuses(self):
        counts = self.repo.count_by_status()
        self.assertEqual(set(counts), set(ALL_STATUS_VALUES))
        self.assertEqual(sum(counts.values()), 0)

    def test_list_by_status_orders_newest_first(self):
        for index, created in enumerate(
            ("2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z", "2026-09-02T00:00:00Z")
        ):
            self.add_bookmark(f"5{index}", created_at=created)
        listed = [record.tweet_id for record in self.repo.list_by_status("NEW")]
        self.assertEqual(listed, ["51", "52", "50"])
        self.assertEqual(len(self.repo.list_by_status("NEW", limit=2)), 2)


class MediaTests(DatabaseTestCase):
    """媒体行：(tweet_id, media_key) 唯一、幂等 upsert、状态与路径更新。"""

    def setUp(self) -> None:
        super().setUp()
        self.add_bookmark("6000")

    def test_upsert_media_creates_then_updates(self):
        first = self.repo.upsert_media(
            MediaRecord(
                tweet_id="6000",
                media_key="3_1",
                media_type="photo",
                source_url="https://img.example/1.jpg",
            ),
            now=T1,
        )
        self.assertTrue(first.created)
        self.assertEqual(first.record.download_status, "PENDING")
        self.assertEqual(len(self.repo.list_media("6000")), 1)

        second = self.repo.upsert_media(
            MediaRecord(
                tweet_id="6000",
                media_key="3_1",
                source_url="https://img.example/1.jpg",
                local_path="assets/6000/image-01.jpg",
            ),
            now=T2,
        )
        self.assertFalse(second.created)
        self.assertEqual(len(self.repo.list_media("6000")), 1)
        self.assertEqual(second.record.local_path, "assets/6000/image-01.jpg")
        self.assertEqual(second.record.first_seen_at, "2026-09-15T08:00:00Z")
        self.assertEqual(second.record.last_updated_at, "2026-09-15T09:30:00Z")

    def test_upsert_media_preserves_download_status_and_attempts(self):
        self.repo.upsert_media(MediaRecord(tweet_id="6000", media_key="m9"), now=T1)
        self.repo.set_media_status("6000", "m9", "DOWNLOADED", count_attempt=True)
        again = self.repo.upsert_media(
            MediaRecord(tweet_id="6000", media_key="m9", source_url="https://img.example/9.jpg"),
            now=T2,
        )
        self.assertEqual(again.record.download_status, "DOWNLOADED")
        self.assertEqual(again.record.attempts, 1)

    def test_media_requires_existing_bookmark(self):
        with self.assertRaises(BookmarkNotFound):
            self.repo.upsert_media(MediaRecord(tweet_id="missing", media_key="k"))

    def test_media_key_must_not_be_empty(self):
        with self.assertRaises(ValueError):
            self.repo.upsert_media(MediaRecord(tweet_id="6000", media_key="  "))

    def test_set_media_status_records_path_and_attempt(self):
        self.repo.upsert_media(
            MediaRecord(tweet_id="6000", media_key="m1", source_url="https://img.example/1.jpg"),
            now=T1,
        )
        record = self.repo.set_media_status(
            "6000",
            "m1",
            "DOWNLOADED",
            local_path="assets/6000/image-01.jpg",
            count_attempt=True,
            now=T2,
        )
        self.assertEqual(record.download_status, "DOWNLOADED")
        self.assertEqual(record.local_path, "assets/6000/image-01.jpg")
        self.assertEqual(record.attempts, 1)

    def test_upsert_media_with_explicit_status_updates_it(self):
        """回归测试：显式提供 download_status 时必须生效（None 才表示"不修改"）。"""
        self.repo.upsert_media(MediaRecord(tweet_id="6000", media_key="m3"), now=T1)
        again = self.repo.upsert_media(
            MediaRecord(tweet_id="6000", media_key="m3", download_status="SKIPPED"), now=T2
        )
        self.assertEqual(again.record.download_status, "SKIPPED")

    def test_media_failure_does_not_remove_row(self):
        self.repo.upsert_media(MediaRecord(tweet_id="6000", media_key="m2"), now=T1)
        record = self.repo.set_media_status(
            "6000", "m2", "FAILED", error_message="timeout", count_attempt=True
        )
        self.assertEqual(record.download_status, "FAILED")
        self.assertEqual(record.error_message, "timeout")
        self.assertEqual(len(self.repo.list_media("6000")), 1)


class ExternalLinkTests(DatabaseTestCase):
    """外链行：(tweet_id, url) 唯一、幂等 upsert、失败仍保留原始 URL。"""

    def setUp(self) -> None:
        super().setUp()
        self.add_bookmark("7000")

    def test_upsert_link_creates_then_updates(self):
        first = self.repo.upsert_external_link(
            ExternalLinkRecord(tweet_id="7000", url="https://example.com/a"), now=T1
        )
        self.assertTrue(first.created)
        self.assertEqual(first.record.fetch_status, "PENDING")

        second = self.repo.upsert_external_link(
            ExternalLinkRecord(
                tweet_id="7000",
                url="https://example.com/a",
                title="Example",
                domain="example.com",
            ),
            now=T2,
        )
        self.assertFalse(second.created)
        self.assertEqual(len(self.repo.list_external_links("7000")), 1)
        self.assertEqual(second.record.title, "Example")
        self.assertEqual(second.record.domain, "example.com")

    def test_link_requires_existing_bookmark(self):
        with self.assertRaises(BookmarkNotFound):
            self.repo.upsert_external_link(
                ExternalLinkRecord(tweet_id="missing", url="https://example.com/x")
            )

    def test_url_must_not_be_empty(self):
        with self.assertRaises(ValueError):
            self.repo.upsert_external_link(ExternalLinkRecord(tweet_id="7000", url=""))

    def test_failed_fetch_keeps_original_url(self):
        url = "https://example.com/broken"
        self.repo.upsert_external_link(ExternalLinkRecord(tweet_id="7000", url=url), now=T1)
        record = self.repo.set_link_status(
            "7000", url, "FAILED", error_message="HTTP 404", count_attempt=True, now=T2
        )
        self.assertEqual(record.url, url)
        self.assertEqual(record.fetch_status, "FAILED")
        self.assertEqual(record.error_message, "HTTP 404")
        self.assertEqual(record.attempts, 1)

    def test_successful_fetch_records_resolved_url_and_path(self):
        url = "https://example.com/redirect"
        self.repo.upsert_external_link(ExternalLinkRecord(tweet_id="7000", url=url), now=T1)
        record = self.repo.set_link_status(
            "7000",
            url,
            "FETCHED",
            resolved_url="https://example.com/final",
            content_path="assets/7000/link-01.md",
            now=T2,
        )
        self.assertEqual(record.fetch_status, "FETCHED")
        self.assertEqual(record.resolved_url, "https://example.com/final")
        self.assertEqual(record.content_path, "assets/7000/link-01.md")

    def test_upsert_link_with_explicit_status_updates_it(self):
        """回归测试：显式提供 fetch_status 时必须生效（None 才表示"不修改"）。"""
        url = "https://example.com/explicit"
        self.repo.upsert_external_link(ExternalLinkRecord(tweet_id="7000", url=url), now=T1)
        again = self.repo.upsert_external_link(
            ExternalLinkRecord(tweet_id="7000", url=url, fetch_status="SKIPPED"), now=T2
        )
        self.assertEqual(again.record.fetch_status, "SKIPPED")

    def test_multiple_links_per_tweet_are_independent(self):
        for suffix in ("a", "b"):
            self.repo.upsert_external_link(
                ExternalLinkRecord(tweet_id="7000", url=f"https://example.com/{suffix}"), now=T1
            )
        self.assertEqual(len(self.repo.list_external_links("7000")), 2)

    def test_set_link_status_updates_title(self):
        """Phase 9：抓取成功时标题也要落库（渲染层直接用）。"""

        url = "https://example.com/titled"
        self.repo.upsert_external_link(ExternalLinkRecord(tweet_id="7000", url=url), now=T1)
        record = self.repo.set_link_status(
            "7000", url, "FETCHED", title="A title", now=T2
        )
        self.assertEqual(record.title, "A title")

        # 未提供 title 时不得清空已有标题（部分更新语义）。
        again = self.repo.set_link_status("7000", url, "FETCHED", now=T2)
        self.assertEqual(again.title, "A title")

    def test_count_links_reports_status_breakdown(self):
        for index, status in enumerate(("FETCHED", "FAILED", "FAILED"), start=1):
            url = f"https://example.com/{index}"
            self.repo.upsert_external_link(ExternalLinkRecord(tweet_id="7000", url=url), now=T1)
            if status != "PENDING":
                self.repo.set_link_status("7000", url, status, now=T2)

        counts = self.repo.count_external_links_by_status()
        self.assertEqual(counts["FETCHED"], 1)
        self.assertEqual(counts["FAILED"], 2)
        self.assertEqual(counts["PENDING"], 0)
        self.assertEqual(counts["SKIPPED"], 0)
        self.assertEqual(self.repo.count_external_links(), 3)
        self.assertEqual(
            [link.fetch_status for link in self.repo.list_links_by_status("FAILED")],
            ["FAILED", "FAILED"],
        )


class FullTextSearchTests(DatabaseTestCase):
    """FTS5：可检索、索引跟随更新与删除、入参校验。"""

    def test_search_finds_inserted_text(self):
        self.add_bookmark("8000", tweet_text="distributed systems reading list", username="alice")
        self.add_bookmark("8001", tweet_text="unrelated cooking notes", username="bob")
        hits = self.repo.search("distributed")
        self.assertEqual([hit.tweet_id for hit in hits], ["8000"])

    def test_search_matches_username_column(self):
        self.add_bookmark("8002", tweet_text="hello world", username="carol")
        self.assertEqual([hit.tweet_id for hit in self.repo.search("carol")], ["8002"])

    def test_search_index_follows_update(self):
        self.add_bookmark("8003", tweet_text="alpha")
        self.assertEqual(len(self.repo.search("alpha")), 1)
        self.repo.upsert_bookmark(BookmarkRecord(tweet_id="8003", tweet_text="beta"), now=T2)
        self.assertEqual(self.repo.search("alpha"), [])
        self.assertEqual([hit.tweet_id for hit in self.repo.search("beta")], ["8003"])

    def test_search_index_follows_delete(self):
        self.add_bookmark("8004", tweet_text="gamma")
        self.assertEqual(len(self.repo.search("gamma")), 1)
        self.assertTrue(self.repo.delete_bookmark("8004"))
        self.assertEqual(self.repo.search("gamma"), [])
        self.assertFalse(self.repo.delete_bookmark("8004"))

    def test_search_respects_limit(self):
        for index in range(3):
            self.add_bookmark(f"81{index}", tweet_text="shared keyword")
        self.assertEqual(len(self.repo.search("shared")), 3)
        self.assertEqual(len(self.repo.search("shared", limit=2)), 2)

    def test_search_rejects_empty_query(self):
        with self.assertRaises(ValueError):
            self.repo.search("   ")

    def test_search_rejects_invalid_syntax(self):
        with self.assertRaises(ValueError):
            self.repo.search('"unterminated')


class CascadeTests(DatabaseTestCase):
    """外键级联：删除书签同时清理媒体与外链。"""

    def test_delete_bookmark_removes_dependents(self):
        self.add_bookmark("9000")
        self.repo.upsert_media(MediaRecord(tweet_id="9000", media_key="m1"), now=T1)
        self.repo.upsert_external_link(
            ExternalLinkRecord(tweet_id="9000", url="https://example.com"), now=T1
        )
        self.assertEqual(len(self.repo.list_media("9000")), 1)
        self.assertEqual(len(self.repo.list_external_links("9000")), 1)

        self.assertTrue(self.repo.delete_bookmark("9000"))
        self.assertEqual(self.repo.list_media("9000"), [])
        self.assertEqual(self.repo.list_external_links("9000"), [])
        self.assertEqual(self.repo.count_bookmarks(), 0)


class ClockTests(unittest.TestCase):
    """时间戳格式与解析。"""

    def test_utc_now_iso_format(self):
        self.assertEqual(utc_now_iso(T1), "2026-09-15T08:00:00Z")

    def test_naive_datetime_is_treated_as_utc(self):
        naive = datetime(2026, 9, 15, 8, 0, 0)
        self.assertEqual(utc_now_iso(naive), "2026-09-15T08:00:00Z")

    def test_parse_iso_roundtrip(self):
        self.assertEqual(parse_iso(utc_now_iso(T1)), T1)

    def test_parse_iso_rejects_bad_input(self):
        for bad in ("", "2026-09-15", "not-a-timestamp"):
            with self.assertRaises(ValueError):
                parse_iso(bad)


if __name__ == "__main__":  # pragma: no cover - 便于直接运行本文件
    unittest.main(verbosity=2)







