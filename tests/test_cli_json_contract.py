"""`status --json` 的**机器可读契约**测试。

为什么单独成文件：该载荷会被后续阶段（Phase 8 Knowledge-Agent、外部集成）与
自动化流水线消费。**键改名/删除/类型变化都会静默破坏消费者**，
而现有测试只断言了其中少数几个键。这里把契约**冻结**下来：
顶层键集合、各分区必需键与类型、以及"目录缺失/存在"两种情形下的稳定性。

契约变更时的正确做法：**同步改本文件**（让变更可见、可审），而不是删断言。
"""

from __future__ import annotations

import importlib
import io
import contextlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 注意：`src.cli.__init__` 会重导出 main，必须取模块属性，不能用 `import src.cli.main as cli`
cli_main = importlib.import_module("src.cli.main")
main = cli_main.main

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "upstream" / "bookmarks.sample.jsonl"

#: 冻结的顶层键集合（新增键是兼容变更，但仍应在此登记）。
TOP_LEVEL_KEYS = {"config", "database", "upstream", "canonical"}

DATABASE_KEYS = {"counts", "schema", "total", "links", "last_synced_at"}
CONFIG_KEYS = {"project_root", "raw_dir", "state_db", "knowledge_dir", "log_dir",
               "source", "unknown_keys"}
UPSTREAM_KEYS = {"executable", "data_dir", "ready", "records", "jsonl_exists", "jsonl_bytes",
                 "jsonl_modified_at", "manifest_exists", "database_exists"}
CANONICAL_KEYS = {"normalized_dir", "normalized_files", "pipeline"}
CANONICAL_PIPELINE = ["normalize", "render", "rebuild-index"]


class StatusJsonContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="xbk-json-contract-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir(parents=True)
        shutil.copy2(FIXTURE, self.upstream / "bookmarks.jsonl")
        (self.root / "data" / "raw").mkdir(parents=True)
        self.normalized = self.root / "data" / "normalized"
        cfg_dir = self.root / "config"
        cfg_dir.mkdir(parents=True)
        self.config = cfg_dir / "config.yaml"
        self.config.write_text(
            "version: 1\n"
            "paths:\n"
            f"  project_root: '{self.root.as_posix()}'\n"
            "  data_dir: 'data'\n  raw_dir: 'data/raw'\n  state_dir: 'data/state'\n"
            "  log_dir: 'data/logs'\n  knowledge_dir: 'knowledge/X-Bookmarks'\n"
            "collector:\n"
            f"  executable: '{Path(sys.executable).as_posix()}'\n"
            "  executable_args: []\n"
            f"  upstream_data_dir: '{self.upstream.as_posix()}'\n"
            "  auth:\n    method: 'firefox'\n    browser: 'firefox'\n"
            "logging:\n  level: 'INFO'\n  file_per_day: true\n  console: false\n",
            encoding="utf-8")

    def status_payload(self) -> dict:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--config", str(self.config), "status", "--json"])
        self.assertEqual(code, cli_main.EXIT_OK)
        return json.loads(buffer.getvalue())

    # ── 契约本身 ────────────────────────────────────────────────────────────

    def test_top_level_keys_are_frozen(self):
        payload = self.status_payload()
        self.assertEqual(set(payload), TOP_LEVEL_KEYS)

    def test_database_section_shape(self):
        payload = self.status_payload()
        self.assertTrue(DATABASE_KEYS <= set(payload["database"]))
        self.assertIsInstance(payload["database"]["total"], int)
        self.assertIsInstance(payload["database"]["schema"], dict)
        self.assertIn("current_version", payload["database"]["schema"])
        self.assertIsInstance(payload["database"]["links"], dict)
        self.assertIsInstance(payload["database"]["counts"], dict)

    def test_config_section_shape(self):
        payload = self.status_payload()
        self.assertTrue(CONFIG_KEYS <= set(payload["config"]))
        self.assertIsInstance(payload["config"]["unknown_keys"], list)

    def test_upstream_section_shape(self):
        payload = self.status_payload()
        self.assertTrue(UPSTREAM_KEYS <= set(payload["upstream"]))
        self.assertIsInstance(payload["upstream"]["ready"], bool)
        self.assertIsInstance(payload["upstream"]["records"], int)
        self.assertIsInstance(payload["upstream"]["jsonl_bytes"], int)

    def test_canonical_section_shape(self):
        payload = self.status_payload()
        self.assertTrue(CANONICAL_KEYS <= set(payload["canonical"]))
        self.assertIsInstance(payload["canonical"]["normalized_files"], int)
        self.assertEqual(payload["canonical"]["pipeline"], CANONICAL_PIPELINE)

    # ── 两种目录情形下的稳定性 ──────────────────────────────────────────────

    def test_valid_when_normalized_dir_missing(self):
        payload = self.status_payload()
        self.assertFalse(self.normalized.exists())
        self.assertEqual(payload["canonical"]["normalized_files"], 0)

    def test_count_reflects_normalized_files(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--config", str(self.config), "normalize", "--apply"])
        self.assertEqual(code, cli_main.EXIT_OK)
        expected = len(list(self.normalized.glob("*.json")))
        self.assertGreater(expected, 0)
        self.assertEqual(self.status_payload()["canonical"]["normalized_files"], expected)

    def test_json_output_is_pure_json(self):
        """`--json` 必须只输出 JSON（消费者直接解析）——不夹带人类可读文本。"""

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            main(["--config", str(self.config), "status", "--json"])
        text = buffer.getvalue().strip()
        self.assertTrue(text.startswith("{"))
        self.assertTrue(text.endswith("}"))
        json.loads(text)                       # 不应抛异常


if __name__ == "__main__":
    unittest.main()
