"""`src/ingest` 的验收测试（Phase 6）。

核心断言
--------
* 首次入库：新建、归档原始 JSON、状态落 `COLLECTED`。
* **第二次入库：`new == 0`、无重复行、原始归档不重写**（本项目最核心的幂等要求）。
* 单条失败被隔离：其余记录照常入库，失败记录写入 `error_message` 与 `attempts`。
* 媒体清单状态映射、外链去重与域名提取。

运行方式（项目根目录）::

    .venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.collector.base import MediaEntry, UpstreamBookmark  # noqa: E402
from src.database import (  # noqa: E402
    BookmarkRepository,
    BookmarkStatus,
    MediaDownloadStatus,
    connect,
)
from src.ingest import Ingestor, domain_of, media_key_for  # noqa: E402

POSTED_AT = "Mon Sep 14 01:24:21 +0000 2026"


def make_bookmark(tweet_id: str = "1900000000000000101", **overrides) -> UpstreamBookmark:
    """构造一条结构合法的上游记录，可按需覆写字段。"""

    values = {
        "tweet_id": tweet_id,
        "url": f"https://x.com/sample_author/status/{tweet_id}",
        "text": "sample text",
        "author_handle": "sample_author",
        "author_name": "Sample Author",
        "author_profile_image_url": "https://pbs.twimg.com/profile_images/1/sample_normal.jpg",
        "posted_at_raw": POSTED_AT,
        "bookmarked_at_raw": None,
        "synced_at": "2026-09-16T00:00:01.000Z",
        "conversation_id": tweet_id,
        "language": "en",
        "possibly_sensitive": False,
        "media_urls": (),
        "media_objects": (),
        "links": (),
        "tags": (),
        "engagement": {"likeCount": 1, "repostCount": 0, "replyCount": 0, "quoteCount": 0, "bookmarkCount": 0},
        "author": {"id": "1001", "handle": "sample_author", "name": "Sample Author"},
        "ingested_via": "graphql",
        "sort_index": "1",
        "text_expanded_at": None,
        "raw": {"tweetId": tweet_id, "text": "sample text"},
    }
    values.update(overrides)
    if "raw" not in overrides:
        # raw 必须跟随实际字段变化，否则"内容变化触发重写"的幂等测试会失真。
        values["raw"] = {
            "tweetId": values["tweet_id"],
            "text": values["text"],
            "url": values["url"],
            "links": list(values["links"]),
        }
    return UpstreamBookmark(**values)


def make_media(
    tweet_id: str = "1900000000000000101",
    source_url: str = "https://pbs.twimg.com/media/SAMPLE0000000001.png",
    **overrides,
) -> MediaEntry:
    values = {
        "bookmark_id": tweet_id,
        "tweet_id": tweet_id,
        "tweet_url": f"https://x.com/sample_author/status/{tweet_id}",
        "author_handle": "sample_author",
        "author_name": "Sample Author",
        "source_url": source_url,
        "local_path": r"C:\synthetic\media\file.png",
        "content_type": "image/png",
        "size_bytes": 1234,
        "status": "downloaded",
        "fetched_at": "2026-09-16T00:00:04.000Z",
    }
    values.update(overrides)
    return MediaEntry(**values)


class IngestTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-ingest-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.raw_dir = self.tmp / "raw"
        self.connection: sqlite3.Connection = connect(":memory:")
        self.addCleanup(self.connection.close)
        self.repository = BookmarkRepository(self.connection)
        self.ingestor = Ingestor(self.repository, self.raw_dir)


class FirstRunTests(IngestTestCase):
    def test_new_records_are_stored_as_collected(self):
        stats = self.ingestor.run([make_bookmark("1"), make_bookmark("2")])
        self.assertEqual(stats.fetched, 2)
        self.assertEqual(stats.new, 2)
        self.assertEqual(stats.failed, 0)
        self.assertTrue(stats.ok)
        self.assertEqual(self.repository.count_bookmarks(), 2)
        self.assertEqual(stats.status_counts[BookmarkStatus.COLLECTED.value], 2)

    def test_mapped_fields_match_upstream_record(self):
        self.ingestor.run([make_bookmark("1")])
        record = self.repository.require_bookmark("1")
        self.assertEqual(record.tweet_id, "1")
        self.assertEqual(record.username, "sample_author")
        self.assertEqual(record.author_name, "Sample Author")
        self.assertEqual(record.author_id, "1001")
        self.assertEqual(record.tweet_text, "sample text")
        self.assertEqual(record.tweet_url, "https://x.com/sample_author/status/1")
        self.assertEqual(record.created_at, "2026-09-14T01:24:21Z")
        self.assertEqual(record.status, BookmarkStatus.COLLECTED.value)

    def test_raw_archive_is_written_and_linked(self):
        self.ingestor.run([make_bookmark("1")])
        path = self.raw_dir / "1.json"
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["tweet_id"], "1")
        self.assertEqual(payload["source"], "fieldtheory")
        self.assertIsNone(payload["enrichment"])
        self.assertEqual(self.repository.require_bookmark("1").raw_json_path, str(path))

    def test_stats_report_raw_counts(self):
        stats = self.ingestor.run([make_bookmark("1"), make_bookmark("2")])
        self.assertEqual(stats.raw_written, 2)
        self.assertEqual(stats.raw_skipped, 0)


class IdempotencyTests(IngestTestCase):
    """本项目最核心的要求：同一份数据跑两次不产生任何重复。"""

    def test_second_run_reports_no_new_records(self):
        bookmarks = [make_bookmark("1"), make_bookmark("2")]
        first = self.ingestor.run(bookmarks)
        second = self.ingestor.run(bookmarks)
        self.assertEqual(first.new, 2)
        self.assertEqual(second.new, 0)
        self.assertEqual(second.unchanged, 2)
        self.assertEqual(second.updated, 0)
        self.assertEqual(self.repository.count_bookmarks(), 2)

    def test_second_run_does_not_rewrite_raw_archives(self):
        bookmarks = [make_bookmark("1")]
        self.ingestor.run(bookmarks)
        before = (self.raw_dir / "1.json").read_text(encoding="utf-8")
        second = self.ingestor.run(bookmarks)
        after = (self.raw_dir / "1.json").read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertEqual(second.raw_skipped, 1)
        self.assertEqual(second.raw_written, 0)

    def test_second_run_keeps_advanced_state(self):
        bookmarks = [make_bookmark("1")]
        self.ingestor.run(bookmarks)
        self.repository.set_status("1", BookmarkStatus.PROCESSED)
        second = self.ingestor.run(bookmarks)
        self.assertEqual(second.collected_transitions, 0)
        self.assertEqual(self.repository.require_bookmark("1").status, "PROCESSED")

    def test_raw_archive_is_rewritten_when_content_changes(self):
        self.ingestor.run([make_bookmark("1", text="first")])
        second = self.ingestor.run([make_bookmark("1", text="second")])
        self.assertEqual(second.updated, 1)
        self.assertEqual(second.raw_written, 1)
        payload = json.loads((self.raw_dir / "1.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["upstream"]["text"], "second")

    def test_media_and_links_are_idempotent(self):
        bookmarks = [make_bookmark("1", links=("https://example.com/a",))]
        media = [make_media("1")]
        first = self.ingestor.run(bookmarks, media=media)
        second = self.ingestor.run(bookmarks, media=media)
        self.assertEqual(first.media_new, 1)
        self.assertEqual(second.media_new, 0)
        self.assertEqual(second.media_unchanged, 1)
        self.assertEqual(first.links_new, 1)
        self.assertEqual(second.links_unchanged, 1)
        self.assertEqual(len(self.repository.list_media("1")), 1)
        self.assertEqual(len(self.repository.list_external_links("1")), 1)


class LinkTests(IngestTestCase):
    def test_duplicate_links_are_collapsed(self):
        stats = self.ingestor.run(
            [make_bookmark("1", links=("https://cobalt.tools", "https://cobalt.tools"))]
        )
        self.assertEqual(stats.links_new, 1)
        self.assertEqual(len(self.repository.list_external_links("1")), 1)

    def test_domain_is_extracted(self):
        self.ingestor.run(
            [
                make_bookmark(
                    "1", links=("https://Example.COM/path?a=1", "http://x.com/i/article/9")
                )
            ]
        )
        links = {link.url: link.domain for link in self.repository.list_external_links("1")}
        self.assertEqual(links["https://Example.COM/path?a=1"], "example.com")
        self.assertEqual(links["http://x.com/i/article/9"], "x.com")

    def test_blank_links_are_skipped_without_failing_the_record(self):
        stats = self.ingestor.run([make_bookmark("1", links=("", "   "))])
        self.assertEqual(stats.links_new, 0)
        self.assertEqual(stats.failed, 0)
        self.assertEqual(self.repository.require_bookmark("1").status, "COLLECTED")
        self.assertEqual(self.repository.list_external_links("1"), [])

    def test_reingest_does_not_reset_fetch_status(self):
        """Phase 9 回归：重复 sync 不得把外链抓取结果重置回 PENDING。"""

        url = "https://example.com/a"
        bookmarks = [make_bookmark("1", links=(url,))]
        self.ingestor.run(bookmarks)
        self.repository.set_link_status(
            "1",
            url,
            "FETCHED",
            resolved_url="https://example.com/a",
            title="Example",
            content_path="assets/1/links/abc.md",
        )

        stats = self.ingestor.run(bookmarks)

        self.assertEqual(stats.links_unchanged, 1)
        record = self.repository.require_external_link("1", url)
        self.assertEqual(record.fetch_status, "FETCHED")
        self.assertEqual(record.content_path, "assets/1/links/abc.md")
        self.assertEqual(record.title, "Example")

    def test_domain_of_handles_garbage(self):
        self.assertEqual(domain_of("not a url"), "")
        self.assertEqual(domain_of("https://a.b:8443/x"), "a.b:8443")


class MediaTests(IngestTestCase):
    def test_manifest_status_maps_to_media_status(self):
        self.ingestor.run(
            [make_bookmark("1")],
            media=[
                make_media("1", "https://pbs.twimg.com/media/AAA.png"),
                make_media("1", "https://pbs.twimg.com/media/BBB.jpg", status="failed"),
                make_media("1", "https://pbs.twimg.com/media/CCC.mp4", status="skipped_too_large"),
                make_media("1", "https://pbs.twimg.com/media/DDD.png", status="mystery"),
            ],
        )
        statuses = {
            media.source_url: media.download_status for media in self.repository.list_media("1")
        }
        self.assertEqual(statuses["https://pbs.twimg.com/media/AAA.png"], "DOWNLOADED")
        self.assertEqual(statuses["https://pbs.twimg.com/media/BBB.jpg"], "FAILED")
        self.assertEqual(statuses["https://pbs.twimg.com/media/CCC.mp4"], "SKIPPED")
        self.assertEqual(statuses["https://pbs.twimg.com/media/DDD.png"], "PENDING")

    def test_media_type_is_derived(self):
        self.ingestor.run(
            [
                make_bookmark(
                    "1",
                    media_objects=(
                        {"type": "photo", "url": "https://pbs.twimg.com/media/AAA.png"},
                    ),
                )
            ],
            media=[
                make_media("1", "https://pbs.twimg.com/media/AAA.png"),
                make_media("1", "https://pbs.twimg.com/profile_images/1/x_400x400.jpg"),
                make_media(
                    "1",
                    "https://pbs.twimg.com/media/ZZZ.bin",
                    content_type="application/octet-stream",
                ),
            ],
        )
        types = {media.source_url: media.media_type for media in self.repository.list_media("1")}
        self.assertEqual(types["https://pbs.twimg.com/media/AAA.png"], "photo")
        self.assertEqual(
            types["https://pbs.twimg.com/profile_images/1/x_400x400.jpg"], "profile_image"
        )
        self.assertEqual(types["https://pbs.twimg.com/media/ZZZ.bin"], "unknown")

    def test_media_key_is_stable_for_the_same_url(self):
        first = media_key_for("https://pbs.twimg.com/media/AAA.png")
        second = media_key_for("https://pbs.twimg.com/media/AAA.png")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        self.assertNotEqual(first, media_key_for("https://pbs.twimg.com/media/BBB.png"))

    def test_media_status_enum_is_stored(self):
        self.ingestor.run([make_bookmark("1")], media=[make_media("1")])
        stored = self.repository.require_media("1", media_key_for(make_media("1").source_url))
        self.assertEqual(stored.download_status, MediaDownloadStatus.DOWNLOADED.value)
        self.assertEqual(stored.media_type, "photo")

    def test_local_path_is_written_on_insert_and_never_overwritten(self):
        """Phase 8 接管 `media.local_path`：重复入库不得把知识库路径改回上游旧路径。"""

        entry = make_media("1")
        self.ingestor.run([make_bookmark("1")], media=[entry])
        key = media_key_for(entry.source_url)
        self.assertEqual(self.repository.require_media("1", key).local_path, entry.local_path)

        # 模拟 Phase 8 写入知识库内的本地路径后，上游再次同步。
        self.repository.set_media_status("1", key, "DOWNLOADED", local_path="D:/kb/2026/09/1.png")
        self.ingestor.run([make_bookmark("1")], media=[make_media("1", local_path=r"C:\other\file.png")])

        stored = self.repository.require_media("1", key)
        self.assertEqual(stored.local_path, "D:/kb/2026/09/1.png")


class FailureIsolationTests(IngestTestCase):
    """单条失败不得让整批失败（AGENTS.md 最高优先级原则第 7 条）。"""

    def test_one_bad_record_does_not_stop_the_batch(self):
        bookmarks = [
            make_bookmark("1"),
            make_bookmark("2", posted_at_raw="not-a-timestamp"),
            make_bookmark("3"),
        ]
        stats = self.ingestor.run(bookmarks)
        self.assertEqual(stats.fetched, 3)
        self.assertEqual(stats.new, 2)
        self.assertEqual(stats.failed, 1)
        self.assertFalse(stats.ok)
        self.assertEqual(len(stats.errors), 1)
        self.assertEqual(stats.errors[0][0], "2")
        self.assertEqual(self.repository.count_bookmarks(), 3)
        self.assertIsNotNone(self.repository.get_bookmark("1"))
        self.assertIsNotNone(self.repository.get_bookmark("3"))

    def test_failed_record_gets_status_error_and_attempt(self):
        self.ingestor.run([make_bookmark("2", posted_at_raw="not-a-timestamp")])
        record = self.repository.require_bookmark("2")
        self.assertEqual(record.status, BookmarkStatus.FAILED.value)
        self.assertEqual(record.attempts, 1)
        self.assertIn("UpstreamContractError", record.error_message or "")

    def test_failed_record_recovers_on_next_run(self):
        self.ingestor.run([make_bookmark("2", posted_at_raw="not-a-timestamp")])
        stats = self.ingestor.run([make_bookmark("2")])
        self.assertEqual(stats.failed, 0)
        self.assertEqual(stats.collected_transitions, 1)
        record = self.repository.require_bookmark("2")
        self.assertEqual(record.status, BookmarkStatus.COLLECTED.value)
        self.assertIsNone(record.error_message)


class EnrichmentTests(IngestTestCase):
    def _enriched(self, tweet_id: str = "1"):
        from src.collector.base import EnrichedBookmark

        return EnrichedBookmark(
            tweet_id=tweet_id,
            url=f"https://x.com/sample_author/status/{tweet_id}",
            text="x.com/i/article/1...",
            author_handle="sample_author",
            article_title="Synthetic article",
            article_text="Synthetic body",
            article_site=None,
            enriched_at="2026-09-16T00:00:30.000Z",
            categories=(),
            primary_category="unclassified",
            domains=(),
            primary_domain=None,
            github_urls=(),
            view_count=None,
            media_count=0,
            link_count=1,
            folder_ids=(),
            folder_names=(),
            quoted_status_id=None,
            quoted_tweet=None,
            raw={"tweetId": tweet_id, "articleText": "Synthetic body"},
        )

    def test_enrichment_is_stored_in_the_raw_archive(self):
        stats = self.ingestor.run([make_bookmark("1")], enrichment={"1": self._enriched()})
        self.assertEqual(stats.enriched, 1)
        payload = json.loads((self.raw_dir / "1.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["enrichment"]["articleText"], "Synthetic body")

    def test_missing_enrichment_leaves_archive_with_null(self):
        stats = self.ingestor.run([make_bookmark("1")])
        self.assertEqual(stats.enriched, 0)
        payload = json.loads((self.raw_dir / "1.json").read_text(encoding="utf-8"))
        self.assertIsNone(payload["enrichment"])

    def test_enrichment_for_another_tweet_is_ignored(self):
        stats = self.ingestor.run([make_bookmark("1")], enrichment={"9": self._enriched("9")})
        self.assertEqual(stats.enriched, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
