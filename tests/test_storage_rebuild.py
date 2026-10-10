"""Phase 4 · Step 4 测试：`rebuild-index`（D4 + R6）。

覆盖
----
* 扫描：缺失目录报错、坏 JSON / 非法 Canonical / 重复 tweet_id 记入 failures 但不中断
* 演练：`apply=False` 不创建/不修改任何文件
* 整库重建：**删库 → 重建 → 内容索引与删库前逐条一致**（任务书 S4 指定用例）
* **运行态重置**：重建后 status/attempts/error_message 回到初始态（R6）
* 就地刷新：运行态保留 + 按 content_hash 幂等（第二次全部 unchanged）
* 备份：默认生成 `state.db.bak-<UTC>`；--no-backup 跳过
* 字段映射：username←author_username、author_name←author、markdown_path 确定性
* CLI：帮助文本含重置语义、演练不落盘、apply 建库、目录缺失返回 EXIT_CONFIG
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli.main import EXIT_CONFIG, EXIT_FAILURE, EXIT_OK, build_parser, main  # noqa: E402
from src.database.connection import connect  # noqa: E402
from src.database.index_store import IndexStore  # noqa: E402
from src.database.r6_fields import CONTENT_COLUMNS  # noqa: E402
from src.database.states import BookmarkStatus  # noqa: E402
from src.storage.json_projection import write_canonical_json  # noqa: E402
from src.storage.rebuild import (  # noqa: E402
    RUNTIME_RESET_NOTE,
    RebuildError,
    rebuild_index,
    scan_normalized,
)

NOW = "2026-10-10T12:00:00Z"


def bookmark(tweet_id: str, *, text: str = "示例正文", hash_seed: str = "a") -> dict:
    return {
        "tweet_id": tweet_id,
        "author": "Sample Author",
        "author_id": "100000001",
        "author_username": "sample_author",
        "created_at": "2026-09-10T13:26:07Z",
        "text": text,
        "url": f"https://x.com/sample_author/status/{tweet_id}",
        "conversation_id": tweet_id,
        "source": "x",
        "collector": "fieldtheory",
        "quoted_tweet": None,
        "reply_to": None,
        "thread": None,
        "media": [],
        "external_links": [],
        "x_article": None,
        "collected_at": "2026-09-16T02:02:41.036Z",
        "updated_at": None,
        "content_hash": hash_seed * 64,
    }


class RebuildTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="xbk-rebuild-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.normalized = self.root / "data" / "normalized"
        self.normalized.mkdir(parents=True)
        self.db = self.root / "data" / "state" / "state.db"

    def seed_normalized(self, count: int = 3) -> None:
        for index in range(1, count + 1):
            write_canonical_json(bookmark(str(1900000000000000100 + index),
                                          text=f"正文{index}",
                                          hash_seed=chr(96 + index)),
                                 self.normalized)

    def snapshot(self) -> tuple:
        conn = connect(self.db)
        try:
            return IndexStore(conn).content_index_snapshot()
        finally:
            conn.close()


class ScanTests(RebuildTestCase):
    def test_missing_dir_raises(self):
        with self.assertRaises(RebuildError):
            scan_normalized(self.root / "nope")

    def test_scans_valid_entries(self):
        self.seed_normalized(3)
        plan = scan_normalized(self.normalized)
        self.assertEqual(plan.scanned, 3)
        self.assertEqual(plan.indexable, 3)
        self.assertEqual(plan.failures, ())

    def test_broken_json_recorded_but_scan_continues(self):
        self.seed_normalized(2)
        (self.normalized / "broken.json").write_text("{not json", encoding="utf-8")
        plan = scan_normalized(self.normalized)
        self.assertEqual(plan.indexable, 2)
        self.assertEqual(len(plan.failures), 1)
        self.assertIn("broken.json", plan.failures[0][0])

    def test_non_object_json_rejected(self):
        (self.normalized / "list.json").write_text("[1, 2]", encoding="utf-8")
        plan = scan_normalized(self.normalized)
        self.assertEqual(len(plan.failures), 1)
        self.assertIn("顶层不是 JSON 对象", plan.failures[0][1])

    def test_invalid_canonical_rejected(self):
        payload = bookmark("1900000000000000999")
        del payload["author_username"]
        (self.normalized / "bad.json").write_text(json.dumps(payload), encoding="utf-8")
        plan = scan_normalized(self.normalized)
        self.assertEqual(plan.indexable, 0)
        self.assertEqual(len(plan.failures), 1)

    def test_duplicate_tweet_id_detected(self):
        payload = bookmark("1900000000000000101")
        (self.normalized / "a.json").write_text(json.dumps(payload), encoding="utf-8")
        (self.normalized / "b.json").write_text(json.dumps(payload), encoding="utf-8")
        plan = scan_normalized(self.normalized)
        self.assertEqual(plan.indexable, 1)
        self.assertIn("tweet_id 重复", plan.failures[0][1])


class DryRunTests(RebuildTestCase):
    def test_dry_run_touches_nothing(self):
        self.seed_normalized(2)
        before = sorted(p.name for p in self.normalized.iterdir())
        report = rebuild_index(self.normalized, db_path=self.db, apply=False)
        self.assertFalse(report.applied)
        self.assertEqual(report.inserted, 0)
        self.assertFalse(self.db.exists())                      # 未建库
        self.assertEqual(sorted(p.name for p in self.normalized.iterdir()), before)
        self.assertEqual(list(self.db.parent.glob("*.bak-*")), [])


class FullRebuildTests(RebuildTestCase):
    def test_rebuild_creates_content_index(self):
        self.seed_normalized(3)
        report = rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        self.assertTrue(report.applied)
        self.assertEqual(report.inserted, 3)
        self.assertEqual(report.runtime_initial_state, 3)
        self.assertEqual(len(self.snapshot()), 3)

    def test_corrupt_database_raises_domain_error(self):
        """目标文件存在但不是合法 SQLite ⇒ 领域错误（而非原始 sqlite3 异常）。"""

        self.seed_normalized(1)
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.db.write_bytes(b"this is not a sqlite database")
        # 用 --in-place：整库重建会先删掉旧库，只有就地刷新才会**打开**既有库
        with self.assertRaises(RebuildError) as ctx:
            rebuild_index(self.normalized, db_path=self.db, apply=True, in_place=True, now=NOW)
        message = str(ctx.exception)
        self.assertIn("损坏", message)
        # 不静默销毁用户文件
        self.assertEqual(self.db.read_bytes(), b"this is not a sqlite database")

    def test_full_rebuild_replaces_corrupt_database(self):
        """整库重建的语义是「删库重建」：损坏文件被备份/替换，不应因读不动而失败。"""

        self.seed_normalized(1)
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.db.write_bytes(b"garbage")
        report = rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        self.assertEqual(report.inserted, 1)
        self.assertIsNotNone(report.backup_path)          # 旧文件已备份（未静默丢失）

    def test_content_index_identical_after_deleting_db(self):
        """任务书 S4 指定：删库 → 重建 → 内容索引一致。"""

        self.seed_normalized(3)
        rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        before = self.snapshot()
        self.db.unlink()                                     # 删库
        rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW, backup=False)
        self.assertEqual(self.snapshot(), before)

    def test_runtime_state_reset_after_rebuild(self):
        """R6：运行态无重建来源 → 重建后回初始态。"""

        self.seed_normalized(2)
        rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        conn = connect(self.db)
        conn.execute("UPDATE bookmarks SET status=?, attempts=5, error_message='boom'",
                     (BookmarkStatus.COMPLETED.value,))
        conn.close()

        rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        conn = connect(self.db)
        try:
            row = conn.execute("SELECT * FROM bookmarks LIMIT 1").fetchone()
            self.assertEqual(row["status"], BookmarkStatus.NEW.value)
            self.assertEqual(row["attempts"], 0)
            self.assertIsNone(row["error_message"])
        finally:
            conn.close()

    def test_backup_created_by_default(self):
        self.seed_normalized(1)
        rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        report = rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        self.assertIsNotNone(report.backup_path)
        self.assertTrue(report.backup_path.is_file())
        self.assertIn(".bak-", report.backup_path.name)

    def test_no_backup_skips_copy(self):
        self.seed_normalized(1)
        rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        report = rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW, backup=False)
        self.assertIsNone(report.backup_path)
        self.assertEqual(list(self.db.parent.glob("*.bak-*")), [])

    def test_field_mapping(self):
        self.seed_normalized(1)
        rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        row = self.snapshot()[0]
        self.assertEqual(row["username"], "sample_author")     # ← author_username
        self.assertEqual(row["author_name"], "Sample Author")  # ← author
        self.assertEqual(row["tweet_text"], "正文1")
        self.assertEqual(row["markdown_path"],
                         f"2026/09/20260910-1900000000000000101.md")

    def test_raw_json_path_filled_when_present(self):
        self.seed_normalized(1)
        raw_dir = self.root / "data" / "raw"
        raw_dir.mkdir(parents=True)
        (raw_dir / "1900000000000000101.json").write_text("{}", encoding="utf-8")
        rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW, raw_dir=raw_dir)
        self.assertIn("1900000000000000101.json", self.snapshot()[0]["raw_json_path"])

    def test_failures_do_not_block_good_entries(self):
        self.seed_normalized(2)
        (self.normalized / "broken.json").write_text("{oops", encoding="utf-8")
        report = rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        self.assertEqual(report.inserted, 2)
        self.assertFalse(report.ok)
        self.assertEqual(len(report.plan.failures), 1)


class InPlaceTests(RebuildTestCase):
    def _rebuild_and_mark(self) -> None:
        self.seed_normalized(2)
        rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW)
        conn = connect(self.db)
        conn.execute("UPDATE bookmarks SET status=?, attempts=4", (BookmarkStatus.PROCESSED.value,))
        conn.close()

    def test_in_place_keeps_runtime_and_is_idempotent(self):
        self._rebuild_and_mark()
        first = rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW, in_place=True)
        self.assertEqual(first.unchanged, 2)          # 内容未变 → 一条都没写
        self.assertEqual(first.written, 0)
        conn = connect(self.db)
        try:
            row = conn.execute("SELECT * FROM bookmarks LIMIT 1").fetchone()
            self.assertEqual(row["status"], BookmarkStatus.PROCESSED.value)  # 运行态保留
            self.assertEqual(row["attempts"], 4)
        finally:
            conn.close()

    def test_in_place_updates_only_changed_content(self):
        self._rebuild_and_mark()
        write_canonical_json(
            bookmark("1900000000000000101", text="改过的正文", hash_seed="f"), self.normalized
        )
        report = rebuild_index(self.normalized, db_path=self.db, apply=True, now=NOW, in_place=True)
        self.assertEqual(report.updated, 1)
        self.assertEqual(report.unchanged, 1)
        conn = connect(self.db)
        try:
            row = conn.execute(
                "SELECT * FROM bookmarks WHERE tweet_id='1900000000000000101'"
            ).fetchone()
            self.assertEqual(row["tweet_text"], "改过的正文")
            self.assertEqual(row["status"], BookmarkStatus.PROCESSED.value)  # 仍保留
        finally:
            conn.close()


class CliTests(RebuildTestCase):
    def _config(self) -> Path:
        cfg = self.root / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        path = cfg / "config.yaml"
        path.write_text(
            "version: 1\n"
            "paths:\n"
            f"  project_root: '{self.root.as_posix()}'\n"
            "  data_dir: 'data'\n  raw_dir: 'data/raw'\n  state_dir: 'data/state'\n"
            "  log_dir: 'data/logs'\n  knowledge_dir: 'knowledge/X-Bookmarks'\n"
            "collector:\n"
            f"  executable: '{Path(sys.executable).as_posix()}'\n"
            "  executable_args: []\n"
            "  auth:\n    method: 'firefox'\n    browser: 'firefox'\n"
            "logging:\n  level: 'INFO'\n  file_per_day: true\n  console: false\n",
            encoding="utf-8",
        )
        return path

    def test_help_documents_runtime_reset(self):
        help_text = build_parser().format_help()
        self.assertIn("rebuild-index", help_text)
        self.assertIn("rebuild-index", [a for a in build_parser()._subparsers._group_actions[0].choices])
        import contextlib, io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(["rebuild-index", "--help"])
        self.assertIn("重置为初始态", buffer.getvalue())
        self.assertIn("in-place", buffer.getvalue())

    def test_cli_dry_run_does_not_create_db(self):
        self.seed_normalized(2)
        code = main(["--config", str(self._config()), "rebuild-index"])
        self.assertEqual(code, EXIT_OK)
        self.assertFalse(self.db.exists())

    def test_cli_apply_creates_db(self):
        self.seed_normalized(2)
        code = main(["--config", str(self._config()), "rebuild-index", "--apply"])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(self.db.exists())
        self.assertEqual(len(self.snapshot()), 2)

    def test_cli_db_override_writes_temp_database(self):
        """--db 覆盖：验收时可指向临时库，不碰真实 data/state/。"""

        self.seed_normalized(2)
        temp_db = self.root / "tmp-index" / "index.db"
        code = main(["--config", str(self._config()), "rebuild-index", "--apply",
                     "--db", str(temp_db)])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(temp_db.is_file())
        self.assertFalse(self.db.exists())          # 真实库未被创建/写入

    def test_cli_missing_normalized_dir_returns_config_error(self):
        code = main(["--config", str(self._config()), "rebuild-index", "--apply",
                     "--normalized-dir", str(self.root / "nope")])
        self.assertEqual(code, EXIT_CONFIG)

    def test_cli_reports_failures_with_nonzero_exit(self):
        self.seed_normalized(1)
        (self.normalized / "broken.json").write_text("{oops", encoding="utf-8")
        code = main(["--config", str(self._config()), "rebuild-index", "--apply"])
        self.assertEqual(code, EXIT_FAILURE)
        self.assertEqual(len(self.snapshot()), 1)   # 好条目仍写入


if __name__ == "__main__":
    unittest.main()
