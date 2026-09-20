"""`src/collector/fieldtheory_adapter.py` 的验收测试（Phase 5）。

覆盖范围
--------
路径解析、`sync` 命令拼装与重试、认证/瞬时/超时错误分类、
JSONL 与 media-manifest 解析、`list|show --json` 富化读取、幂等读取。

约束
----
* 不访问网络、不调用真实 `fieldtheory`，也不读写真实上游目录：
  全部通过 `tests/support/stub_fieldtheory.py` 与临时目录完成。
* 断言不依赖本机 PATH 上是否装有所需工具。

运行方式（项目根目录）::

    .venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.collector import FieldTheoryAdapter  # noqa: E402  (path bootstrap first)
from src.collector.base import (  # noqa: E402
    UpstreamAuthError,
    UpstreamContractError,
    UpstreamExecutionError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)

STUB = Path(__file__).resolve().parent / "support" / "stub_fieldtheory.py"


class AdapterTestCase(unittest.TestCase):
    """Shared temporary-directory harness; every test is offline."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-collector-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.data_dir = self.tmp / "data"
        self.data_dir.mkdir()
        self.waits: list[float] = []

    def make_adapter(self, scenario: str = "ok", **overrides) -> FieldTheoryAdapter:
        env = {"STUB_SCENARIO": scenario}
        env.update(overrides.pop("env", {}))
        options = {
            "executable": [sys.executable, "-B", str(STUB)],
            "data_dir": self.data_dir,
            "env": env,
            "retries": 0,
            "sleeper": self.waits.append,
            "query_timeout_seconds": 30.0,
            "sync_timeout_seconds": 30.0,
        }
        options.update(overrides)
        return FieldTheoryAdapter(**options)

    def recorded_argv(self) -> str:
        return (self.data_dir / "stub-argv.txt").read_text(encoding="utf-8")


class PathResolutionTests(AdapterTestCase):
    """数据目录与可执行文件的解析优先级。"""

    def test_default_data_dir_is_home_fieldtheory(self):
        # 本机已设置用户级 FT_DATA_DIR（ADR-011 迁移到 D:），因此这里显式清空它
        # 才能验证"没有任何覆盖时回退到 ~/.fieldtheory/bookmarks"。
        # 注意：data_dir 是惰性属性，必须在 patch 生效期间读取。
        with mock.patch.dict(os.environ, {"FT_DATA_DIR": ""}):
            adapter = self.make_adapter(data_dir=None, home_dir=self.tmp)
            self.assertEqual(adapter.data_dir, self.tmp / ".fieldtheory" / "bookmarks")

    def test_machine_env_var_is_used_when_no_explicit_dir(self):
        machine_dir = self.tmp / "machine-upstream"
        with mock.patch.dict(os.environ, {"FT_DATA_DIR": str(machine_dir)}):
            adapter = self.make_adapter(data_dir=None, home_dir=self.tmp / "elsewhere")
            self.assertEqual(adapter.data_dir, machine_dir)

    def test_env_override_wins_over_home(self):
        override = self.tmp / "env-data"
        adapter = self.make_adapter(
            data_dir=None, home_dir=self.tmp, env={"FT_DATA_DIR": str(override)}
        )
        self.assertEqual(adapter.data_dir, override)

    def test_explicit_data_dir_wins_over_env(self):
        adapter = self.make_adapter(env={"FT_DATA_DIR": str(self.tmp / "env-data")})
        self.assertEqual(adapter.data_dir, self.data_dir)

    def test_artifact_paths_are_derived_from_data_dir(self):
        adapter = self.make_adapter()
        self.assertEqual(adapter.jsonl_path, self.data_dir / "bookmarks.jsonl")
        self.assertEqual(adapter.manifest_path, self.data_dir / "media-manifest.json")
        self.assertEqual(adapter.meta_path, self.data_dir / "bookmarks-meta.json")
        self.assertEqual(
            adapter.backfill_state_path, self.data_dir / "bookmarks-backfill-state.json"
        )
        self.assertEqual(adapter.database_path, self.data_dir / "bookmarks.db")
        self.assertEqual(adapter.media_dir, self.data_dir / "media")

    def test_missing_executable_raises_unavailable(self):
        adapter = self.make_adapter(executable="xbook-no-such-tool-9c1f")
        with self.assertRaises(UpstreamUnavailableError):
            _ = adapter.executable

    def test_explicit_executable_sequence_is_kept_verbatim(self):
        adapter = self.make_adapter()
        self.assertEqual(adapter.executable, (sys.executable, "-B", str(STUB)))

    def test_empty_executable_sequence_raises(self):
        adapter = self.make_adapter(executable=[])
        with self.assertRaises(UpstreamUnavailableError):
            _ = adapter.executable


class SyncCommandTests(AdapterTestCase):
    """`sync` 的参数映射、结果与重试策略。"""

    def test_sync_success_reports_result_and_writes_data(self):
        adapter = self.make_adapter()
        result = adapter.sync()
        self.assertTrue(result.ok)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.attempts, 1)
        self.assertFalse(result.timed_out)
        self.assertGreaterEqual(result.duration_seconds, 0.0)
        self.assertEqual(len(adapter.read_bookmarks()), 3)

    def test_sync_default_skips_media_and_never_prompts(self):
        adapter = self.make_adapter()
        adapter.sync()
        argv = self.recorded_argv()
        self.assertIn("--yes", argv)
        self.assertIn("--no-media", argv)
        self.assertIn("--browser firefox", argv)

    def test_sync_with_media_drops_no_media_flag(self):
        adapter = self.make_adapter()
        adapter.sync(with_media=True)
        self.assertNotIn("--no-media", self.recorded_argv())

    def test_sync_maps_paging_and_enrichment_flags(self):
        adapter = self.make_adapter()
        adapter.sync(
            continue_previous=True,
            rebuild=True,
            gaps=True,
            max_pages=2,
            target_adds=10,
            max_minutes=5,
            delay_ms=700,
            folders=True,
            folder="AI",
            browser=None,
        )
        argv = self.recorded_argv()
        for expected in (
            "--continue",
            "--rebuild",
            "--gaps",
            "--max-pages 2",
            "--target-adds 10",
            "--max-minutes 5",
            "--delay-ms 700",
            "--folders",
            "--folder AI",
        ):
            self.assertIn(expected, argv)
        self.assertNotIn("--browser", argv)

    def test_sync_passes_extra_args_last(self):
        adapter = self.make_adapter()
        adapter.sync(extra_args=["--skip-profile-images"])
        self.assertTrue(self.recorded_argv().endswith("--skip-profile-images"))

    def test_auth_failure_is_not_retried(self):
        adapter = self.make_adapter(scenario="auth", retries=3)
        result = adapter.sync()
        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.attempts, 1)
        self.assertIn("Couldn't connect", result.stdout)
        self.assertEqual(self.waits, [])

    def test_transient_failure_is_retried_up_to_the_limit(self):
        adapter = self.make_adapter(scenario="transient", retries=2)
        result = adapter.sync()
        self.assertFalse(result.ok)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(self.waits, [2.0, 4.0])

    def test_flaky_run_succeeds_after_two_retries(self):
        adapter = self.make_adapter(scenario="flaky", retries=2)
        result = adapter.sync()
        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(len(adapter.read_bookmarks()), 3)

    def test_sync_timeout_is_reported_not_raised(self):
        adapter = self.make_adapter(
            scenario="slow", env={"STUB_SLEEP": "10"}, sync_timeout_seconds=1.0
        )
        result = adapter.sync()
        self.assertTrue(result.timed_out)
        self.assertFalse(result.ok)

    def test_sync_stderr_is_captured_for_logging(self):
        adapter = self.make_adapter()
        result = adapter.sync()
        self.assertIn("ExperimentalWarning", result.stderr)

    def test_upstream_unavailable_when_command_cannot_start(self):
        adapter = self.make_adapter(executable="xbook-no-such-tool-9c1f")
        with self.assertRaises(UpstreamUnavailableError):
            adapter.sync()


class BookmarkReaderTests(AdapterTestCase):
    """JSONL 读取与字段规范化。"""

    def test_read_bookmarks_maps_contract_fields(self):
        adapter = self.make_adapter()
        adapter.sync()
        records = adapter.read_bookmarks()
        self.assertEqual(len(records), 3)
        first = records[0]
        self.assertEqual(first.tweet_id, "1900000000000000101")
        self.assertEqual(first.url, "https://x.com/sample_author/status/1900000000000000101")
        self.assertEqual(first.author_handle, "sample_author")
        self.assertEqual(first.posted_at_raw, "Mon Sep 14 01:24:21 +0000 2026")
        self.assertIsNone(first.bookmarked_at_raw)
        self.assertEqual(first.media_urls, ("https://pbs.twimg.com/media/SAMPLE0000000001.png",))
        self.assertEqual(first.media_objects[0]["type"], "photo")
        self.assertEqual(first.engagement["likeCount"], 10)
        self.assertEqual(first.author["handle"], "sample_author")
        self.assertEqual(first.ingested_via, "graphql")
        self.assertIsNone(first.text_expanded_at)

    def test_raw_payload_is_preserved_for_later_phases(self):
        adapter = self.make_adapter()
        adapter.sync()
        first = adapter.read_bookmarks()[0]
        self.assertIn("sortIndex", first.raw)
        self.assertEqual(first.raw["sortIndex"], "1876311982835679001")

    def test_optional_text_expanded_at_is_captured(self):
        adapter = self.make_adapter()
        adapter.sync()
        records = adapter.read_bookmarks()
        self.assertEqual(records[1].text_expanded_at, "2026-09-16T00:00:30.000Z")

    def test_reading_twice_is_idempotent(self):
        adapter = self.make_adapter()
        adapter.sync()
        self.assertEqual(adapter.read_bookmarks(), adapter.read_bookmarks())

    def test_missing_jsonl_raises_unavailable(self):
        adapter = self.make_adapter()
        with self.assertRaises(UpstreamUnavailableError):
            adapter.read_bookmarks()

    def test_broken_json_line_raises_contract_error(self):
        adapter = self.make_adapter()
        adapter.sync()
        adapter.jsonl_path.write_text("{not json}\n", encoding="utf-8")
        with self.assertRaises(UpstreamContractError):
            adapter.read_bookmarks()

    def test_record_violating_contract_raises_with_line_number(self):
        adapter = self.make_adapter()
        adapter.sync()
        lines = adapter.jsonl_path.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].replace('"tweetId"', '"renamedTweetId"')
        adapter.jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(UpstreamContractError) as ctx:
            adapter.read_bookmarks()
        self.assertIn(":2", str(ctx.exception))


class ArtifactReaderTests(AdapterTestCase):
    """media-manifest / meta / backfill-state 读取与就绪检查。"""

    def test_read_media_manifest_maps_entries(self):
        adapter = self.make_adapter()
        adapter.sync()
        manifest = adapter.read_media_manifest()
        self.assertEqual(manifest.schema_version, 1)
        self.assertEqual(manifest.downloaded, 2)
        self.assertEqual(manifest.failed, 0)
        self.assertEqual(len(manifest.entries), 2)
        entry = manifest.entries[0]
        self.assertEqual(entry.bookmark_id, "1900000000000000101")
        self.assertEqual(entry.content_type, "image/png")
        self.assertEqual(entry.size_bytes, 28243)
        self.assertEqual(entry.status, "downloaded")

    def test_missing_manifest_raises_unavailable(self):
        adapter = self.make_adapter()
        with self.assertRaises(UpstreamUnavailableError):
            adapter.read_media_manifest()

    def test_read_meta_exposes_total_bookmarks(self):
        adapter = self.make_adapter()
        adapter.sync()
        self.assertEqual(adapter.read_meta()["totalBookmarks"], 3)

    def test_read_backfill_state_exposes_stop_reason(self):
        adapter = self.make_adapter()
        adapter.sync()
        self.assertEqual(adapter.read_backfill_state()["stopReason"], "end of bookmarks")

    def test_check_ready_reports_artifacts_after_sync(self):
        adapter = self.make_adapter()
        adapter.sync()
        artifacts = adapter.check_ready()
        self.assertTrue(artifacts.ready)
        self.assertTrue(artifacts.jsonl_exists)
        self.assertTrue(artifacts.manifest_exists)
        self.assertFalse(artifacts.database_exists)
        self.assertEqual(artifacts.record_count, 3)
        self.assertGreater(artifacts.jsonl_bytes, 0)
        self.assertIsNotNone(artifacts.jsonl_modified_at)
        self.assertEqual(artifacts.data_dir, str(self.data_dir))

    def test_check_ready_on_empty_directory_is_not_ready(self):
        adapter = self.make_adapter()
        artifacts = adapter.check_ready()
        self.assertFalse(artifacts.ready)
        self.assertEqual(artifacts.record_count, 0)
        self.assertIsNone(artifacts.jsonl_modified_at)


class EnrichedReaderTests(AdapterTestCase):
    """`list --json` / `show --json` 富化读取。"""

    def test_list_enriched_returns_records(self):
        adapter = self.make_adapter()
        records = adapter.list_enriched()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].tweet_id, "1900000000000000102")
        self.assertEqual(records[0].article_title, "Synthetic article title")
        self.assertIn("Synthetic article body", records[0].article_text)

    def test_list_enriched_passes_limit_flag(self):
        adapter = self.make_adapter()
        adapter.list_enriched(limit=5)
        self.assertIn("--limit 5", self.recorded_argv())

    def test_list_enriched_tolerates_noisy_stdout(self):
        adapter = self.make_adapter(env={"STUB_NOISE": "1"})
        records = adapter.list_enriched()
        self.assertEqual(len(records), 2)

    def test_list_enriched_maps_classification_and_folders(self):
        adapter = self.make_adapter()
        second = adapter.list_enriched()[1]
        self.assertEqual(second.categories, ("tools",))
        self.assertEqual(second.primary_category, "tools")
        self.assertEqual(second.folder_names, ("Sample Folder",))
        self.assertEqual(second.view_count, 120)
        self.assertEqual(second.quoted_status_id, "1900000000000000999")
        self.assertEqual(second.quoted_tweet["authorHandle"], "quoted_author")

    def test_show_enriched_returns_single_record(self):
        adapter = self.make_adapter()
        record = adapter.show_enriched("1900000000000000102")
        self.assertEqual(record.tweet_id, "1900000000000000102")
        self.assertEqual(record.author_handle, "sample_author")

    def test_show_enriched_rejects_blank_id(self):
        adapter = self.make_adapter()
        with self.assertRaises(ValueError):
            adapter.show_enriched("   ")

    def test_show_enriched_unknown_id_raises_execution_error(self):
        adapter = self.make_adapter()
        with self.assertRaises(UpstreamExecutionError):
            adapter.show_enriched("1900000000000000999")

    def test_auth_failure_raises_auth_error_for_queries(self):
        adapter = self.make_adapter(scenario="auth", retries=2)
        with self.assertRaises(UpstreamAuthError):
            adapter.list_enriched()
        self.assertEqual(self.waits, [])

    def test_query_timeout_raises_timeout_error(self):
        adapter = self.make_adapter(
            scenario="slow", env={"STUB_SLEEP": "10"}, query_timeout_seconds=1.0
        )
        with self.assertRaises(UpstreamTimeoutError):
            adapter.list_enriched()

    def test_upstream_version_is_parsed(self):
        adapter = self.make_adapter()
        self.assertEqual(adapter.upstream_version(), "9.9.9")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
