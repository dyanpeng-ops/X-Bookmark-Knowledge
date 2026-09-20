"""`src/media` 的验收测试（Phase 8）。

覆盖范围
--------
* 命名与布局：`stable_filename`、`asset_dir_for`（年月回退、非法字符收敛）。
* 复制：字节一致、哈希一致则跳过、源被替换后重写、缺源只失败那一条。
* 源路径归一（独立审计的前置条件）：旧缓存绝对路径、上游清单索引、已本地化行、源缺失。
* 跳过规则：`media.download=false`、视频开关、`max_bytes`、上游未下载。
* 落库意图：成功写本地路径、跳过只记原因、失败记 `error_message` + `attempts`。
* Markdown：`## media` 引用本地相对路径，未命中回退远程 URL（不丢信息）。
* CLI 端到端（离线桩 + 临时目录）：`sync → media → process` 全链路、二次运行幂等、
  `--dry-run` 不落盘，以及"再次 sync 不会把本地路径改回旧缓存路径"。

运行方式（项目根目录）::

    .venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import EXIT_FAILURE, EXIT_OK, main as cli_main  # noqa: E402
from src.config import MediaOptions  # noqa: E402
from src.database import connect  # noqa: E402
from src.ingest import media_key_for  # noqa: E402
from src.markdown import MarkdownWriter, RenderOptions, render_markdown  # noqa: E402
from src.media import (  # noqa: E402
    MediaLocalizer,
    MediaSource,
    MediaUpdate,
    asset_dir_for,
    stable_filename,
)

STUB = PROJECT_ROOT / "tests" / "support" / "stub_fieldtheory.py"

PHOTO_URL = "https://pbs.twimg.com/media/SAMPLE0000000001.png"
AVATAR_URL = "https://pbs.twimg.com/profile_images/0000000000000000001/sample_400x400.jpg"
PHOTO_TWEET = "1900000000000000101"


class MediaTestCase(unittest.TestCase):
    """共用夹具：临时的上游缓存目录 + 临时的知识库目录。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-media-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.knowledge = self.tmp / "knowledge"
        self.upstream = self.tmp / "upstream"
        self.media_dir = self.upstream / "media"
        self.media_dir.mkdir(parents=True)
        self.updates: list[MediaUpdate] = []

    def write_source(self, name: str, payload: bytes | str = b"payload") -> Path:
        path = self.media_dir / name
        path.write_bytes(payload if isinstance(payload, bytes) else payload.encode("utf-8"))
        return path

    def source(self, **overrides: object) -> MediaSource:
        values: dict[str, object] = {
            "tweet_id": "6000",
            "media_key": "abc123def456abcd",
            "media_type": "photo",
            "source_url": PHOTO_URL,
            "local_path": str(self.media_dir / "AAA.png"),
            "upstream_status": "DOWNLOADED",
            "created_at": "2026-09-14T01:24:21Z",
        }
        values.update(overrides)
        return MediaSource(**values)  # type: ignore[arg-type]

    def localizer(self, **kwargs: object) -> MediaLocalizer:
        kwargs.setdefault("updater", self.updates.append)
        return MediaLocalizer(self.knowledge, self.media_dir, **kwargs)  # type: ignore[arg-type]

    def target_of(self, source: MediaSource, name: str = "AAA.png") -> Path:
        return (
            self.knowledge
            / asset_dir_for(source.tweet_id, source.created_at, MediaOptions().assets_subdir)
            / stable_filename(source.media_key, name)
        )


class NamingTests(unittest.TestCase):
    def test_stable_filename_uses_media_key_and_lowercase_suffix(self):
        self.assertEqual(stable_filename("abc123", "Photo.PNG"), "abc123.png")

    def test_stable_filename_falls_back_to_bin(self):
        self.assertEqual(stable_filename("abc123", None), "abc123.bin")
        self.assertEqual(stable_filename("abc123", "no-extension"), "abc123.bin")

    def test_stable_filename_strips_path_separators(self):
        name = stable_filename("../../evil\\name", "x.jpg")
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)
        self.assertTrue(name.endswith(".jpg"))
        self.assertFalse(name.startswith("."))

    def test_asset_dir_follows_year_month_layout(self):
        self.assertEqual(
            asset_dir_for("6000", "2026-09-14T01:24:21Z"),
            Path("2026") / "09" / "assets" / "6000",
        )

    def test_asset_dir_falls_back_to_unknown_without_date(self):
        self.assertEqual(
            asset_dir_for("6000", None),
            Path("unknown") / "unknown" / "assets" / "6000",
        )

    def test_asset_dir_rejects_traversal_in_components(self):
        directory = asset_dir_for("../evil", "2026-09-14T00:00:00Z")
        self.assertEqual(directory.parts[:3], ("2026", "09", "assets"))
        self.assertEqual(len(directory.parts), 4)
        self.assertNotIn("/", directory.parts[-1])
        self.assertNotIn("\\", directory.parts[-1])
        self.assertNotEqual(directory.parts[-1], "..")


class CopyTests(MediaTestCase):
    def test_first_run_copies_bytes_and_records_local_path(self):
        self.write_source("AAA.png", b"hello-media")
        source = self.source()
        stats = self.localizer().run([source])

        self.assertEqual((stats.copied, stats.unchanged, stats.skipped, stats.failed), (1, 0, 0, 0))
        target = self.target_of(source)
        self.assertEqual(target.read_bytes(), b"hello-media")
        self.assertEqual(len(self.updates), 1)
        self.assertEqual(self.updates[0].status, "DOWNLOADED")
        self.assertEqual(self.updates[0].local_path, str(target))
        self.assertIsNone(self.updates[0].error_message)

    def test_second_run_is_unchanged_and_does_not_rewrite(self):
        self.write_source("AAA.png", b"hello-media")
        source = self.source()
        self.localizer().run([source])
        target = self.target_of(source)
        stamp = target.stat().st_mtime_ns

        stats = self.localizer().run([source])
        self.assertEqual((stats.copied, stats.unchanged), (0, 1))
        self.assertEqual(target.stat().st_mtime_ns, stamp)

    def test_replaced_source_is_copied_again(self):
        self.write_source("AAA.png", b"version-1")
        source = self.source()
        self.localizer().run([source])
        target = self.target_of(source)

        self.write_source("AAA.png", b"version-2-longer")
        stats = self.localizer().run([source])
        self.assertEqual((stats.copied, stats.unchanged), (1, 0))
        self.assertEqual(target.read_bytes(), b"version-2-longer")

    def test_already_localised_row_is_unchanged_without_upstream_source(self):
        """`local_path` 已指向知识库内文件：不依赖上游源文件，判定 unchanged。"""

        target = self.target_of(self.source())
        target.parent.mkdir(parents=True)
        target.write_bytes(b"already-here")
        stats = self.localizer().run([self.source(local_path=str(target))])
        self.assertEqual((stats.unchanged, stats.failed), (1, 0))
        self.assertEqual(self.updates[0].local_path, str(target))

    def test_missing_source_fails_only_that_row(self):
        self.write_source("AAA.png", b"ok")
        good = self.source(media_key="good")
        bad = self.source(media_key="bad", local_path=str(self.media_dir / "MISSING.png"))

        stats = self.localizer().run([good, bad])
        self.assertEqual((stats.attempted, stats.copied, stats.failed), (2, 1, 1))
        self.assertEqual(stats.errors[0][0], "6000/bad")

        failed = [u for u in self.updates if u.media_key == "bad"][0]
        self.assertEqual(failed.status, "FAILED")
        self.assertIn("not found", failed.error_message or "")
        self.assertTrue(failed.count_attempt)
        self.assertIsNone(failed.local_path)

    def test_missing_media_key_fails_without_touching_other_rows(self):
        self.write_source("AAA.png", b"ok")
        stats = self.localizer().run([self.source(media_key=""), self.source()])
        self.assertEqual((stats.copied, stats.failed), (1, 1))
        self.assertEqual(stats.errors[0][0], "6000/")
        # 无 media_key 的行没有 URL 可查，因此不会产生任何落库意图。
        self.assertEqual([u.media_key for u in self.updates], ["abc123def456abcd"])
        self.assertEqual(self.updates[0].status, "DOWNLOADED")

    def test_updater_failure_is_isolated(self):
        self.write_source("AAA.png", b"ok")

        def updater(update: MediaUpdate) -> None:
            if update.media_key == "boom":
                raise RuntimeError("database is locked")
            self.updates.append(update)

        stats = self.localizer(updater=updater).run(
            [self.source(media_key="boom"), self.source(media_key="fine")]
        )
        self.assertEqual((stats.copied, stats.failed), (1, 1))
        self.assertEqual(stats.errors[0][0], "6000/boom")




class SourceReconciliationTests(MediaTestCase):
    """独立审计的前置条件：旧缓存绝对路径必须先归一到配置的上游媒体目录。"""

    STALE = r"C:\Users\gscaee\.fieldtheory\bookmarks\media\AAA.png"

    def test_stale_absolute_path_is_resolved_into_configured_media_dir(self):
        self.write_source("AAA.png", b"project-copy")
        source = self.source(local_path=self.STALE)

        stats = self.localizer().run([source])
        self.assertEqual((stats.copied, stats.failed), (1, 0))
        self.assertEqual(self.target_of(source).read_bytes(), b"project-copy")
        # 落库的是知识库内路径，而不是旧缓存路径。
        self.assertTrue(str(self.updates[0].local_path).startswith(str(self.knowledge)))
        self.assertNotIn("fieldtheory", str(self.updates[0].local_path))

    def test_stale_path_is_not_used_even_if_that_file_exists(self):
        """旧缓存里存在同名文件也不算证据：只认配置的媒体目录。"""

        self.write_source("AAA.png", b"project-copy")
        legacy_cache = self.tmp / "legacy-cache"
        legacy_cache.mkdir()
        (legacy_cache / "AAA.png").write_bytes(b"legacy-copy")
        source = self.source(local_path=str(legacy_cache / "AAA.png"))

        self.localizer().run([source])
        self.assertEqual(self.target_of(source).read_bytes(), b"project-copy")

    def test_upstream_index_locates_source_after_localisation(self):
        """`local_path` 已改写成知识库路径、且文件丢失时，用清单索引重新定位源。"""

        self.write_source("AAA.png", b"payload")
        source = self.source()
        self.localizer().run([source])
        target = self.target_of(source)
        target.unlink()

        relocated = self.source(local_path=str(target))
        stats = self.localizer(
            upstream_index={PHOTO_URL: str(self.media_dir / "AAA.png")}
        ).run([relocated])
        self.assertEqual((stats.copied, stats.failed), (1, 0))
        self.assertEqual(target.read_bytes(), b"payload")

    def test_localised_row_without_index_reports_failure(self):
        """知识库文件被删且没有清单索引时：如实报失败，不乱猜源文件。"""

        source = self.source(local_path=str(self.target_of(self.source())))
        stats = self.localizer().run([source])
        self.assertEqual((stats.failed, stats.copied), (1, 0))
        self.assertEqual(self.updates[0].status, "FAILED")

    def test_upstream_file_inside_media_dir_is_used_directly(self):
        self.write_source("AAA.png", b"direct")
        stats = self.localizer().run([self.source(local_path=str(self.media_dir / "AAA.png"))])
        self.assertEqual(stats.copied, 1)

    def test_url_basename_is_used_as_last_resort(self):
        """`local_path` 缺失时退化为 URL 文件名（去查询串、去百分号编码）。"""

        self.write_source("photo.png", b"url-named")
        source = self.source(
            local_path=None,
            source_url="https://pbs.twimg.com/media/photo.png?format=png",
        )
        stats = self.localizer().run([source])
        self.assertEqual(stats.copied, 1)
        self.assertEqual(self.target_of(source, "photo.png").read_bytes(), b"url-named")



class SkipRuleTests(MediaTestCase):
    def test_download_disabled_skips_every_row_without_writing(self):
        self.write_source("AAA.png", b"payload")
        stats = self.localizer(options=MediaOptions(download=False)).run([self.source()])
        self.assertEqual((stats.skipped, stats.copied, stats.failed), (1, 0, 0))
        self.assertFalse(self.knowledge.exists())
        self.assertIn("media.download=false", self.updates[0].error_message or "")
        self.assertIsNone(self.updates[0].local_path)

    def test_video_is_skipped_unless_enabled(self):
        self.write_source("clip.mp4", b"video-bytes")
        source = self.source(media_type="video", local_path=str(self.media_dir / "clip.mp4"))

        stats = self.localizer().run([source])
        self.assertEqual((stats.skipped, stats.copied), (1, 0))
        self.assertIn("download_video", self.updates[0].error_message or "")

        allowed = self.localizer(options=MediaOptions(download_video=True)).run([source])
        self.assertEqual((allowed.copied, allowed.skipped), (1, 0))

    def test_animated_gif_counts_as_video(self):
        self.write_source("anim.mp4", b"gif-bytes")
        source = self.source(media_type="animated_gif", local_path=str(self.media_dir / "anim.mp4"))
        stats = self.localizer().run([source])
        self.assertEqual((stats.skipped, stats.copied), (1, 0))

    def test_oversized_source_is_skipped(self):
        self.write_source("AAA.png", b"x" * 64)
        stats = self.localizer(options=MediaOptions(max_bytes=8)).run([self.source()])
        self.assertEqual((stats.skipped, stats.copied), (1, 0))
        self.assertIn("max_bytes", self.updates[0].error_message or "")
        self.assertFalse(self.knowledge.exists())

    def test_upstream_not_downloaded_is_skipped(self):
        self.write_source("AAA.png", b"payload")
        stats = self.localizer().run([self.source(upstream_status="PENDING")])
        self.assertEqual((stats.skipped, stats.copied), (1, 0))
        self.assertEqual(self.updates[0].status, "PENDING")
        self.assertIn("upstream download status", self.updates[0].error_message or "")

    def test_skip_keeps_upstream_status_and_does_not_count_attempt(self):
        self.write_source("AAA.png", b"payload")
        self.localizer(options=MediaOptions(download=False)).run([self.source()])
        self.assertEqual(self.updates[0].status, "DOWNLOADED")
        self.assertFalse(self.updates[0].count_attempt)


class DryRunTests(MediaTestCase):
    def test_dry_run_reports_without_writing_anything(self):
        self.write_source("AAA.png", b"payload")
        stats = self.localizer(dry_run=True, updater=None).run([self.source()])
        self.assertEqual((stats.copied, stats.failed), (1, 0))
        self.assertFalse(self.knowledge.exists())
        self.assertEqual(self.updates, [])

    def test_dry_run_still_reports_missing_sources(self):
        stats = self.localizer(dry_run=True, updater=None).run([self.source()])
        self.assertEqual((stats.failed, stats.copied), (1, 0))
        self.assertFalse(self.knowledge.exists())



RENDER_UPSTREAM = {
    "tweetId": "6000",
    "url": "https://x.com/sample/status/6000",
    "text": "正文",
    "authorHandle": "sample",
    "authorName": "Sample Author",
    "authorProfileImageUrl": "https://pbs.twimg.com/profile_images/1/x.jpg",
    "postedAt": "Mon Sep 14 01:24:21 +0000 2026",
    "bookmarkedAt": None,
    "syncedAt": "2026-09-16T00:00:01.000Z",
    "conversationId": "6000",
    "language": "zh",
    "possiblySensitive": False,
    "engagement": {"likeCount": 1, "repostCount": 0, "replyCount": 0},
    "media": [PHOTO_URL],
    "mediaObjects": (),
    "links": [],
    "tags": [],
    "ingestedVia": "graphql",
    "sortIndex": "1",
    "author": {"id": "1", "handle": "sample", "name": "Sample Author"},
}


class MediaSectionRenderTests(unittest.TestCase):
    def test_media_section_uses_local_relative_path(self):
        text = render_markdown(
            RENDER_UPSTREAM,
            None,
            RenderOptions(),
            media_files={PHOTO_URL: "assets/6000/abc.png"},
        )
        self.assertIn("![](assets/6000/abc.png)", text)
        self.assertNotIn(PHOTO_URL, text)

    def test_media_section_falls_back_to_remote_url(self):
        text = render_markdown(RENDER_UPSTREAM, None, RenderOptions(), media_files={})
        self.assertIn(f"![]({PHOTO_URL})", text)

    def test_default_call_keeps_phase7_behaviour(self):
        text = render_markdown(RENDER_UPSTREAM, None, RenderOptions())
        self.assertIn(f"![]({PHOTO_URL})", text)



class WriterMediaLookupTests(MediaTestCase):
    """`MarkdownWriter` 把媒体查询结果换算成"相对 Markdown 文件自身"的路径。"""

    def _archive(self, tweet_id: str, upstream: dict | None = None) -> None:
        raw = self.tmp / "data" / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "tweet_id": tweet_id,
            "source": "fieldtheory",
            "upstream": dict(upstream or RENDER_UPSTREAM, tweetId=tweet_id),
            "enrichment": None,
        }
        (raw / f"{tweet_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def _asset(self, name: str = "abc.png") -> Path:
        target = self.knowledge / "2026" / "09" / "assets" / "6000" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"local-bytes")
        return target

    def _writer(self, lookup) -> MarkdownWriter:
        return MarkdownWriter(
            self.knowledge,
            raw_dir=self.tmp / "data" / "raw",
            media_lookup=lookup,
        )

    def _content(self) -> str:
        return (self.knowledge / "2026" / "09" / "20260914-6000.md").read_text(encoding="utf-8")

    def test_absolute_lookup_path_is_rendered_relative_to_the_markdown_file(self):
        self._archive("6000")
        asset = self._asset()
        stats = self._writer(lambda tweet_id: {PHOTO_URL: str(asset)}).run(["6000"])
        self.assertEqual(stats.written, 1)
        self.assertIn("![](assets/6000/abc.png)", self._content())

    def test_knowledge_relative_lookup_path_is_accepted(self):
        self._archive("6000")
        self._asset()
        self._writer(lambda tweet_id: {PHOTO_URL: "2026/09/assets/6000/abc.png"}).run(["6000"])
        self.assertIn("![](assets/6000/abc.png)", self._content())

    def test_lookup_failure_falls_back_to_remote_url(self):
        self._archive("6000")

        def broken(tweet_id: str) -> dict:
            raise RuntimeError("database is locked")

        stats = self._writer(broken).run(["6000"])
        self.assertEqual(stats.written, 1)
        self.assertIn(f"![]({PHOTO_URL})", self._content())

    def test_cross_drive_lookup_path_does_not_fail_the_record(self):
        """跨盘符无法算相对路径时保留原路径，记录仍然写成功（单条失败隔离）。"""

        self._archive("6000")
        stats = self._writer(lambda tweet_id: {PHOTO_URL: "Z:/elsewhere/abc.png"}).run(["6000"])
        self.assertEqual((stats.written, stats.failed), (1, 0))
        self.assertIn("![](Z:/elsewhere/abc.png)", self._content())


class CliMediaTestCase(unittest.TestCase):
    """`python -m src.cli media` 端到端（离线桩 + 临时目录）。"""

    MEDIA_BLOCK = (
        "media:\n"
        "  download: true\n"
        "  download_video: false\n"
        "  max_bytes: 20971520\n"
        "  stable_naming: true\n"
        "  assets_subdir: 'assets'\n"
    )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-climedia-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.config_path = self.tmp / "config.yaml"
        self.upstream = self.tmp / "upstream"
        self.knowledge = self.tmp / "knowledge" / "X-Bookmarks"
        self.write_config()

    def write_config(self, media_block: str | None = None) -> Path:
        text = (
            "version: 1\n"
            f"paths:\n  project_root: '{self.tmp.as_posix()}'\n"
            "  data_dir: 'data'\n  raw_dir: 'data/raw'\n  state_dir: 'data/state'\n"
            "  log_dir: 'data/logs'\n  knowledge_dir: 'knowledge/X-Bookmarks'\n"
            "collector:\n"
            f"  executable: '{sys.executable}'\n  executable_args: ['-B', '{STUB.as_posix()}']\n"
            f"  upstream_data_dir: '{self.upstream.as_posix()}'\n"
            "  auth:\n    method: 'firefox'\n    browser: 'firefox'\n"
            + (self.MEDIA_BLOCK if media_block is None else media_block)
            + "logging:\n  level: 'INFO'\n  file_per_day: true\n  console: false\n"
        )
        self.config_path.write_text(text, encoding="utf-8")
        return self.config_path

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(["--config", str(self.config_path), *argv])
        return code, out.getvalue(), err.getvalue()

    def media_rows(self) -> dict[tuple[str, str], sqlite3.Row]:
        connection = connect(self.tmp / "data" / "state" / "state.db")
        connection.row_factory = sqlite3.Row
        try:
            return {
                (row["tweet_id"], row["media_key"]): row
                for row in connection.execute("SELECT * FROM media")
            }
        finally:
            connection.close()

    def photo_target(self) -> Path:
        key = media_key_for(PHOTO_URL)
        return self.knowledge / "2026" / "09" / "assets" / PHOTO_TWEET / f"{key}.png"

    def markdown_file(self) -> Path:
        return self.knowledge / "2026" / "09" / f"20260914-{PHOTO_TWEET}.md"


class CliMediaTests(CliMediaTestCase):
    """`media` 子命令本身的端到端断言。"""

    def test_media_command_copies_files_and_records_knowledge_paths(self):
        self.run_cli("sync")
        code, out, _ = self.run_cli("media")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("copied        : 2", out)
        self.assertIn("failed        : 0", out)

        target = self.photo_target()
        self.assertTrue(target.is_file())
        self.assertEqual(
            target.read_bytes(),
            (self.upstream / "media" / "SAMPLE0000000001.png").read_bytes(),
        )

        rows = self.media_rows()
        self.assertEqual(len(rows), 2)
        photo = rows[(PHOTO_TWEET, media_key_for(PHOTO_URL))]
        self.assertEqual(Path(photo["local_path"]).resolve(), target.resolve())
        # 审计回归：落库路径必须位于本项目知识库内，而不是旧缓存目录。
        for row in rows.values():
            self.assertTrue(str(row["local_path"]).startswith(str(self.knowledge)))
            self.assertNotIn("synthetic", str(row["local_path"]))

    def test_second_media_run_is_unchanged_and_does_not_rewrite(self):
        self.run_cli("sync")
        self.run_cli("media")
        target = self.photo_target()
        stamp = target.stat().st_mtime_ns

        code, out, _ = self.run_cli("media")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("copied        : 0", out)
        self.assertIn("unchanged     : 2", out)
        self.assertEqual(target.stat().st_mtime_ns, stamp)

    def test_media_failure_is_isolated_and_exits_non_zero(self):
        self.run_cli("sync")
        (self.upstream / "media" / "sample_400x400.jpg").unlink()

        code, out, err = self.run_cli("media")
        self.assertEqual(code, EXIT_FAILURE)
        self.assertIn("copied        : 1", out)
        self.assertIn("failed        : 1", out)
        self.assertIn("[fail]", err)

        failed = [row for row in self.media_rows().values() if row["download_status"] == "FAILED"]
        self.assertEqual(len(failed), 1)
        self.assertGreaterEqual(failed[0]["attempts"], 1)
        self.assertIn("not found", failed[0]["error_message"])
        # 失败行保留原路径，不写坏数据。
        self.assertIn("synthetic", failed[0]["local_path"])
        self.assertTrue(self.photo_target().is_file())

    def test_media_tweet_id_filter_limits_scope(self):
        self.run_cli("sync")
        code, out, _ = self.run_cli("media", "--tweet-id", PHOTO_TWEET)
        self.assertEqual(code, EXIT_OK)
        # fixture 里两条媒体行都属于该推文（一条推文图片 + 一条作者头像）。
        self.assertIn("attempted     : 2", out)
        self.assertTrue(self.photo_target().is_file())

        # 没有媒体行的书签：一条也不处理，报告为 warn 而不是失败。
        code, out, err = self.run_cli("media", "--tweet-id", "1900000000000000103")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("no media rows to localise", err)

    def test_media_dry_run_writes_nothing(self):
        self.run_cli("sync")
        code, out, _ = self.run_cli("media", "--dry-run")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("dry run       : true", out)
        self.assertIn("copied        : 2", out)
        self.assertFalse(self.knowledge.exists())
        for row in self.media_rows().values():
            self.assertIn("synthetic", row["local_path"])

    def test_media_skips_everything_when_download_disabled(self):
        self.run_cli("sync")
        self.write_config(media_block="media:\n  download: false\n")

        code, out, err = self.run_cli("media")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("skipped       : 2", out)
        self.assertIn("media.download=false", err)
        self.assertFalse(self.knowledge.exists())
        for row in self.media_rows().values():
            self.assertIn("synthetic", row["local_path"])


class ProcessMediaIntegrationTests(CliMediaTestCase):
    """`media` → `process` 的衔接：Markdown 引用本地相对路径，且再次 sync 不倒退。"""

    def test_process_after_media_references_local_paths(self):
        self.run_cli("sync")
        self.run_cli("media")

        code, out, _ = self.run_cli("process")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("local media   : 1 bookmark(s)", out)

        text = self.markdown_file().read_text(encoding="utf-8")
        key = media_key_for(PHOTO_URL)
        self.assertIn(f"![](assets/{PHOTO_TWEET}/{key}.png)", text)
        self.assertNotIn(PHOTO_URL, text)

    def test_process_without_media_keeps_remote_urls(self):
        """Phase 7 行为不变：未本地化时 `## media` 仍是远程 URL。"""

        self.run_cli("sync")
        code, out, _ = self.run_cli("process")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("local media   : 0 bookmark(s)", out)
        self.assertIn(PHOTO_URL, self.markdown_file().read_text(encoding="utf-8"))

    def test_process_ignores_paths_outside_the_knowledge_dir(self):
        """审计回归：旧缓存路径即使真实存在也不得被 Markdown 引用。"""

        self.run_cli("sync")
        legacy = self.tmp / "legacy-cache"
        legacy.mkdir()
        (legacy / "SAMPLE0000000001.png").write_bytes(b"legacy")
        connection = connect(self.tmp / "data" / "state" / "state.db")
        try:
            connection.execute(
                "UPDATE media SET local_path = ? WHERE source_url = ?",
                (str(legacy / "SAMPLE0000000001.png"), PHOTO_URL),
            )
            connection.commit()
        finally:
            connection.close()

        self.run_cli("process")
        text = self.markdown_file().read_text(encoding="utf-8")
        self.assertIn(PHOTO_URL, text)
        self.assertNotIn("legacy-cache", text)

    def test_reingest_after_media_does_not_revert_local_path(self):
        self.run_cli("sync")
        self.run_cli("media")
        before = {key: row["local_path"] for key, row in self.media_rows().items()}

        code, out, _ = self.run_cli("sync", "--skip-collect")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("media rows    : 0 new, 0 updated, 2 unchanged", out)

        after = {key: row["local_path"] for key, row in self.media_rows().items()}
        self.assertEqual(before, after)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
