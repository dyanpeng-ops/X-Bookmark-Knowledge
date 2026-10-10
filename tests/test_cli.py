"""`src/cli` 的端到端测试（Phase 6）。

用 `tests/support/stub_fieldtheory.py` 代替真实上游，因此**不联网、不读真实上游目录**，
但走完整的真实链路：配置 → 适配器（子进程）→ 入库 → SQLite → 报告。

M2 的核心断言就在这里：连续两次 `sync`，第二次必须 `new : 0` 且不产生重复数据。
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import EXIT_CONFIG, EXIT_FAILURE, EXIT_OK, EXIT_UPSTREAM, main  # noqa: E402
from src.database import connect  # noqa: E402
from src.database.schema import SCHEMA_VERSION  # noqa: E402

STUB = Path(__file__).resolve().parent / "support" / "stub_fieldtheory.py"


class CliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-cli-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.config_path = self.tmp / "config.yaml"
        self.upstream_dir = self.tmp / "upstream"

    def write_config(self, *, executable: str | None = None, extra: str = "") -> Path:
        """写一份指向离线桩的临时配置；executable=None 时使用当前解释器 + 桩脚本。"""

        if executable is None:
            python = str(sys.executable)
            args = f"['-B', '{STUB.as_posix()}']"
        else:
            python = executable
            args = "[]"
        text = (
            "version: 1\n"
            "paths:\n"
            f"  project_root: '{self.tmp.as_posix()}'\n"
            "  data_dir: 'data'\n"
            "  raw_dir: 'data/raw'\n"
            "  state_dir: 'data/state'\n"
            "  log_dir: 'data/logs'\n"
            "  knowledge_dir: 'knowledge/X-Bookmarks'\n"
            "collector:\n"
            f"  executable: '{python}'\n"
            f"  executable_args: {args}\n"
            f"  upstream_data_dir: '{self.upstream_dir.as_posix()}'\n"
            "  auth:\n"
            "    method: 'firefox'\n"
            "    browser: 'firefox'\n"
            "logging:\n"
            "  level: 'INFO'\n"
            "  file_per_day: true\n"
            "  console: false\n"
        )
        text += extra
        self.config_path.write_text(text, encoding="utf-8")
        return self.config_path

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--config", str(self.config_path), *argv])
        return code, out.getvalue(), err.getvalue()

    def state_db(self) -> sqlite3.Connection:
        return connect(self.tmp / "data" / "state" / "state.db")

    def bookmark_count(self) -> int:
        connection = self.state_db()
        try:
            return int(connection.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0])
        finally:
            connection.close()


class SyncCommandTests(CliTestCase):
    def test_sync_runs_collect_and_ingest_end_to_end(self):
        self.write_config()
        code, out, _ = self.run_cli("sync")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("new           : 3", out)
        self.assertIn("failed        : 0", out)
        self.assertEqual(self.bookmark_count(), 3)

    def test_second_sync_reports_new_zero(self):
        """M2：连续两次执行，第二次 New 必须为 0，且不产生重复数据。"""

        self.write_config()
        first_code, first_out, _ = self.run_cli("sync")
        second_code, second_out, _ = self.run_cli("sync")
        self.assertEqual(first_code, EXIT_OK)
        self.assertEqual(second_code, EXIT_OK)
        self.assertIn("new           : 3", first_out)
        self.assertIn("new           : 0", second_out)
        self.assertIn("unchanged     : 3", second_out)
        self.assertEqual(self.bookmark_count(), 3)
        raw_files = sorted(path.name for path in (self.tmp / "data" / "raw").glob("*.json"))
        self.assertEqual(len(raw_files), 3)

    def test_second_sync_does_not_rewrite_raw_archives(self):
        self.write_config()
        self.run_cli("sync")
        _, out, _ = self.run_cli("sync")
        self.assertIn("raw archives  : 0 written, 3 unchanged", out)

    def test_skip_collect_reuses_existing_upstream_data(self):
        self.write_config()
        self.run_cli("sync")
        code, out, _ = self.run_cli("sync", "--skip-collect")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("new           : 0", out)

    def test_ingest_failure_yields_non_zero_exit(self):
        """契约合法但时间格式不可解析：该条入库失败 → 退出码 1，其余记录照常入库。"""

        self.write_config()
        self.run_cli("sync")
        jsonl = self.upstream_dir / "bookmarks.jsonl"
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace("Mon Sep 14 01:24:21 +0000 2026", "yesterday")
        jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
        code, out, err = self.run_cli("sync", "--skip-collect")
        self.assertEqual(code, EXIT_FAILURE)
        self.assertIn("failed        : 1", out)
        self.assertIn("[fail]", err)
        self.assertEqual(self.bookmark_count(), 3)

    def test_upstream_auth_failure_returns_upstream_exit_code(self):
        self.write_config()
        with mock.patch.dict(os.environ, {"STUB_SCENARIO": "auth"}):
            code, _, err = self.run_cli("sync")
        self.assertEqual(code, EXIT_UPSTREAM)
        self.assertIn("upstream sync", err)

    def test_media_manifest_is_ingested(self):
        self.write_config()
        self.run_cli("sync")
        connection = self.state_db()
        try:
            media = connection.execute("SELECT COUNT(*) FROM media").fetchone()[0]
            links = connection.execute("SELECT COUNT(*) FROM external_links").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(media, 2)
        self.assertGreaterEqual(links, 1)

    def test_limit_option_only_ingests_the_head(self):
        self.write_config()
        code, out, _ = self.run_cli("sync", "--limit", "1")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("new           : 1", out)
        self.assertEqual(self.bookmark_count(), 1)

    def test_missing_config_returns_config_exit_code(self):
        self.write_config()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--config", str(self.tmp / "nope.yaml"), "sync"])
        self.assertEqual(code, EXIT_CONFIG)
        self.assertIn("config file not found", err.getvalue())


class StatusCommandTests(CliTestCase):
    def test_status_json_reports_database_and_upstream(self):
        self.write_config()
        self.run_cli("sync")
        code, out, _ = self.run_cli("status", "--json")
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["database"]["total"], 3)
        # 版本无关：引用 SCHEMA_VERSION 而非硬编码 2
        # （Phase 4 Step 3 加 migration 3 时暴露了这个脆弱断言）
        self.assertEqual(payload["database"]["schema"]["current_version"], SCHEMA_VERSION)
        self.assertTrue(payload["upstream"]["ready"])
        self.assertEqual(payload["upstream"]["records"], 3)
        self.assertEqual(payload["config"]["unknown_keys"], [])

    def test_status_human_readable(self):
        self.write_config()
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Status", out)
        self.assertIn("db counts", out)


class DoctorCommandTests(CliTestCase):
    def test_doctor_passes_with_stub_upstream(self):
        self.write_config()
        self.run_cli("sync")
        code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("[ok]   upstream executable", out)
        self.assertIn("Doctor result: OK", out)

    def test_doctor_fails_when_executable_is_missing(self):
        self.write_config(executable="xbook-no-such-tool-9c1f")
        code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, EXIT_FAILURE)
        self.assertIn("[fail] upstream executable", out)
        self.assertIn("Doctor result: FAILED", out)

    def test_doctor_warns_when_upstream_data_is_missing(self):
        self.write_config()
        code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("warnings", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
