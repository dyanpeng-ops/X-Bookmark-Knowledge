"""Phase 5 增量测试：`normalize` / `render` 命令 + `xbk` 入口声明。

覆盖
----
* `normalize`：默认**只演练**（不创建目录/文件）；`--apply` 落 Canonical JSON；
  二次 `--apply` 幂等（全部 unchanged）；`--limit` 生效。
* `render`：默认**只演练**；`--apply` 写 Markdown；既有内容不同 → 记为冲突且**原文件不变**；
  `--overwrite` 才改写。
* `pyproject.toml` 声明 `xbk` 入口（静态校验；实际生效需 `pip install -e .`）。

全部离线：临时项目目录 + 仓库自带的合成 fixture，不触真实 `data/`、`knowledge/`，不联网。
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli.main import EXIT_FAILURE, EXIT_OK, main  # noqa: E402
from src.storage.json_projection import write_canonical_json  # noqa: E402
from src.storage.rebuild import scan_normalized  # noqa: E402

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "upstream" / "bookmarks.sample.jsonl"


def bookmark(tweet_id: str, *, text: str = "示例正文") -> dict:
    return {
        "tweet_id": tweet_id, "author": "Sample Author", "author_id": "100000001",
        "author_username": "sample_author", "created_at": "2026-09-10T13:26:07Z",
        "text": text, "url": f"https://x.com/sample_author/status/{tweet_id}",
        "conversation_id": tweet_id, "source": "x", "collector": "fieldtheory",
        "quoted_tweet": None, "reply_to": None, "thread": None, "media": [],
        "external_links": [], "x_article": None, "collected_at": "2026-09-16T02:02:41.036Z",
        "updated_at": None, "content_hash": "a" * 64,
    }


class CliCanonicalTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="xbk-cli-canonical-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir(parents=True)
        shutil.copy2(FIXTURE, self.upstream / "bookmarks.jsonl")
        (self.root / "data" / "raw").mkdir(parents=True)
        self.normalized = self.root / "data" / "normalized"
        self.knowledge = self.root / "knowledge" / "X-Bookmarks"
        self.config = self._write_config()

    def _write_config(self) -> Path:
        cfg_dir = self.root / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        path = cfg_dir / "config.yaml"
        path.write_text(
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
            encoding="utf-8",
        )
        return path

    def run_cli(self, *argv: str) -> int:
        return main(["--config", str(self.config), *argv])

    def normalized_files(self) -> list[Path]:
        return sorted(self.normalized.glob("*.json")) if self.normalized.exists() else []


class NormalizeTests(CliCanonicalTestCase):
    def test_dry_run_writes_nothing(self):
        code = self.run_cli("normalize")
        self.assertEqual(code, EXIT_OK)
        self.assertFalse(self.normalized.exists())

    def test_apply_writes_canonical_json(self):
        code = self.run_cli("normalize", "--apply")
        self.assertEqual(code, EXIT_OK)
        files = self.normalized_files()
        self.assertEqual(len(files), len(FIXTURE.read_text(encoding="utf-8").strip().splitlines()))
        plan = scan_normalized(self.normalized)
        self.assertEqual(plan.failures, ())          # 全部通过 Canonical 校验
        self.assertEqual(plan.indexable, len(files))

    def test_second_apply_is_idempotent(self):
        self.run_cli("normalize", "--apply")
        before = {p.name: p.stat().st_mtime_ns for p in self.normalized_files()}
        self.run_cli("normalize", "--apply")
        after = {p.name: p.stat().st_mtime_ns for p in self.normalized_files()}
        self.assertEqual(before, after)              # 内容未变 → 一个字节都没重写

    def test_limit_restricts_output(self):
        self.run_cli("normalize", "--apply", "--limit", "1")
        self.assertEqual(len(self.normalized_files()), 1)

    def test_missing_upstream_returns_non_zero(self):
        (self.upstream / "bookmarks.jsonl").unlink()
        self.assertNotEqual(self.run_cli("normalize", "--apply"), EXIT_OK)
        self.assertFalse(self.normalized.exists())


class RenderTests(CliCanonicalTestCase):
    def seed(self, count: int = 2) -> None:
        for index in range(count):
            write_canonical_json(bookmark(f"190000000000000020{index}"), self.normalized)

    def markdown_files(self) -> list[Path]:
        return sorted(self.knowledge.rglob("*.md")) if self.knowledge.exists() else []

    def test_dry_run_writes_nothing(self):
        self.seed()
        self.assertEqual(self.run_cli("render"), EXIT_OK)
        self.assertEqual(self.markdown_files(), [])

    def test_apply_writes_markdown(self):
        self.seed(2)
        self.assertEqual(self.run_cli("render", "--apply"), EXIT_OK)
        files = self.markdown_files()
        self.assertEqual(len(files), 2)
        body = files[0].read_text(encoding="utf-8")
        self.assertIn("## Original Tweet", body)
        self.assertIn("## AI Analysis", body)
        self.assertIn("tweet_id:", body)

    def test_conflicting_existing_file_is_not_overwritten(self):
        self.seed(1)
        self.run_cli("render", "--apply")
        target = self.markdown_files()[0]
        target.write_text("人工维护的内容，不可覆盖\n", encoding="utf-8")
        code = self.run_cli("render", "--apply")
        self.assertEqual(code, EXIT_FAILURE)                     # 冲突 → 非零
        self.assertEqual(target.read_text(encoding="utf-8"), "人工维护的内容，不可覆盖\n")

    def test_overwrite_flag_rewrites(self):
        self.seed(1)
        self.run_cli("render", "--apply")
        target = self.markdown_files()[0]
        target.write_text("old\n", encoding="utf-8")
        self.assertEqual(self.run_cli("render", "--apply", "--overwrite"), EXIT_OK)
        self.assertIn("## Original Tweet", target.read_text(encoding="utf-8"))

    def test_missing_normalized_dir_returns_config_error(self):
        from src.cli.main import EXIT_CONFIG
        self.assertEqual(self.run_cli("render", "--apply"), EXIT_CONFIG)


class StatusCanonicalTests(CliCanonicalTestCase):
    """`status` 应只读报告 Canonical 流水线现状（不写盘）。"""

    def status_json(self) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.run_cli("status", "--json")
        return code, json.loads(buffer.getvalue())

    def test_reports_zero_when_no_normalized_files(self):
        code, payload = self.status_json()
        self.assertEqual(code, EXIT_OK)
        self.assertIn("canonical", payload)
        self.assertEqual(payload["canonical"]["normalized_files"], 0)

    def test_counts_normalized_files(self):
        write_canonical_json(bookmark("1900000000000000301"), self.normalized)
        write_canonical_json(bookmark("1900000000000000302"), self.normalized)
        _, payload = self.status_json()
        self.assertEqual(payload["canonical"]["normalized_files"], 2)
        self.assertEqual(payload["canonical"]["pipeline"],
                         ["normalize", "render", "rebuild-index"])

    def test_human_readable_mentions_canonical(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.run_cli("status")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("canonical", buffer.getvalue())


class DoctorCanonicalTests(CliCanonicalTestCase):
    """`doctor` 应只读报告 Canonical normalized 目录是否就绪（非关键项，不改变退出码）。"""

    def run_doctor(self) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.run_cli("doctor")
        return code, buffer.getvalue()

    def test_doctor_reports_missing_normalized_dir(self):
        code, out = self.run_doctor()
        self.assertIn("canonical normalized", out)
        self.assertIn("缺失", out)
        self.assertEqual(code, EXIT_OK)          # 非关键项 ⇒ 不影响退出码

    def test_doctor_counts_normalized_files(self):
        write_canonical_json(bookmark("1900000000000000401"), self.normalized)
        write_canonical_json(bookmark("1900000000000000402"), self.normalized)
        _, out = self.run_doctor()
        self.assertIn("2 JSON", out)


class EntryPointTests(unittest.TestCase):
    def test_pyproject_declares_xbk_entry_point(self):
        payload = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(payload["project"]["scripts"]["xbk"], "src.cli.main:main")

    def test_entry_target_is_importable(self):
        from src.cli.main import main as entry
        self.assertTrue(callable(entry))


if __name__ == "__main__":
    unittest.main()
