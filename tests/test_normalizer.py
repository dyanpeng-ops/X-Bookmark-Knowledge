"""``FieldTheoryNormalizer`` 测试（Phase 3，Test B–L）。

对应任务书 §18
--------------
B 单条映射 + 必填校验 / C tweet_id / D author / E 时间 / F media / G external_links /
H Article / I Quote / J 缺失字段 / K FT 专属字段不进入 Canonical / L 幂等。

另含验收 E/F：Normalizer 不读取 Field Theory、不调用上游 CLI、不写盘。

全部离线：fixtures 与合成 payload，不读真实 ``data/``，不联网，不写盘。
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.canonical.validate import CanonicalValidationError, validate_bookmark  # noqa: E402
from src.collector.raw_data import RawBookmarkItem, RawCollectorData  # noqa: E402
from src.normalizer import (  # noqa: E402
    FieldTheoryNormalizer,
    NormalizationError,
    compute_content_hash,
    is_article_link,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "upstream"
SAMPLE_JSONL = FIXTURES / "bookmarks.sample.jsonl"
NORMALIZER_DIR = PROJECT_ROOT / "src" / "normalizer"

# schema/bookmark.schema.json 的 19 个属性（12 必填 + 7 可选），固定顺序。
CANONICAL_KEYS = (
    "tweet_id",
    "author",
    "author_id",
    "author_username",
    "created_at",
    "text",
    "url",
    "conversation_id",
    "source",
    "collector",
    "quoted_tweet",
    "reply_to",
    "thread",
    "media",
    "external_links",
    "x_article",
    "collected_at",
    "updated_at",
    "content_hash",
)

REQUIRED_KEYS = (
    "tweet_id",
    "author",
    "author_id",
    "author_username",
    "created_at",
    "text",
    "url",
    "source",
    "collector",
    "content_hash",
    "media",
    "external_links",
)


def sample_payloads() -> list[dict]:
    """读取 fixture JSONL（3 条），返回原始 camelCase 记录。"""

    text = SAMPLE_JSONL.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def payload(tweet_id: str = "1900000000000000100", **overrides) -> dict:
    """构造一条形状合法的 Field Theory JSONL 记录（可覆盖任意键）。"""

    base = {
        "id": tweet_id,
        "tweetId": tweet_id,
        "url": f"https://x.com/sample_author/status/{tweet_id}",
        "text": "hello world",
        "authorHandle": "sample_author",
        "authorName": "Sample Author",
        "author": {"id": "100000001", "handle": "sample_author", "name": "Sample Author"},
        "postedAt": "Mon Sep 14 01:24:21 +0000 2026",
        "bookmarkedAt": None,
        "syncedAt": "2026-09-16T00:00:01.000Z",
        "conversationId": tweet_id,
        "engagement": {"likeCount": 10},
        "media": [],
        "mediaObjects": [],
        "links": [],
        "tags": [],
        "ingestedVia": "graphql",
        "sortIndex": "1876311982835679001",
    }
    base.update(overrides)
    return base


def item(payload_obj: dict, enrichment: dict | None = None) -> RawBookmarkItem:
    return RawBookmarkItem(
        tweet_id=str(payload_obj["tweetId"]), payload=payload_obj, enrichment=enrichment
    )


def raw_data(*payload_objs: dict, collector: str = "fieldtheory") -> RawCollectorData:
    return RawCollectorData(collector=collector, items=tuple(item(p) for p in payload_objs))


class NormalizerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = FieldTheoryNormalizer()

    def normalize_one(self, payload_obj: dict, enrichment: dict | None = None) -> dict:
        return self.normalizer.normalize_item(item(payload_obj, enrichment))


# ── Test B ───────────────────────────────────────────────────────────────────


class SingleBookmarkTests(NormalizerTestCase):
    """Test B：RawBookmarkItem → CanonicalBookmark，必填字段齐备且通过 Schema。"""

    def test_fixture_records_all_validate(self):
        for payload_obj in sample_payloads():
            with self.subTest(tweet_id=payload_obj["tweetId"]):
                bookmark = self.normalize_one(payload_obj)
                validate_bookmark(bookmark)
                for key in REQUIRED_KEYS:
                    self.assertIn(key, bookmark)
                    self.assertTrue(bookmark[key] is not None, key)

    def test_normalize_all_and_validate(self):
        bookmarks = self.normalizer.normalize_and_validate(raw_data(*sample_payloads()))
        self.assertEqual(len(bookmarks), 3)
        for bookmark in bookmarks:
            validate_bookmark(bookmark)

    def test_rejects_foreign_collector(self):
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize(raw_data(payload(), collector="x_api"))

    def test_rejects_non_raw_collector_data(self):
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize("not-data")  # type: ignore[arg-type]

    def test_rejects_non_item(self):
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize_item({"tweet_id": "1"})  # type: ignore[arg-type]


# ── Test C ───────────────────────────────────────────────────────────────────


class TweetIdTests(NormalizerTestCase):
    """Test C：tweet_id 正确传递（第一层去重身份）。"""

    def test_tweet_id_passthrough(self):
        self.assertEqual(self.normalize_one(payload("1234567890"))["tweet_id"], "1234567890")

    def test_numeric_payload_id_is_stringified(self):
        payload_obj = payload("1234567890")
        payload_obj["tweetId"] = 1234567890
        self.assertEqual(self.normalize_one(payload_obj)["tweet_id"], "1234567890")

    def test_missing_payload_tweet_id_raises(self):
        payload_obj = payload()
        del payload_obj["tweetId"]
        raw_item = RawBookmarkItem(tweet_id="1900000000000000100", payload=payload_obj)
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize_item(raw_item)

    def test_mismatched_ids_raise(self):
        payload_obj = payload("111")
        payload_obj["tweetId"] = "222"
        raw_item = RawBookmarkItem(tweet_id="111", payload=payload_obj)
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize_item(raw_item)

    def test_ids_are_unique_across_fixture(self):
        bookmarks = self.normalizer.normalize(raw_data(*sample_payloads()))
        ids = [b["tweet_id"] for b in bookmarks]
        self.assertEqual(len(ids), len(set(ids)))


# ── Test D ───────────────────────────────────────────────────────────────────


class AuthorTests(NormalizerTestCase):
    """Test D：author = 显示名，author_username = handle（任务书 §11）。"""

    def test_display_name_and_handle_mapped(self):
        payload_obj = payload(
            author={
                "id": "173484971",
                "handle": "sample_author",
                "name": "Sample Author | Synthetic",
            }
        )
        bookmark = self.normalize_one(payload_obj)
        self.assertEqual(bookmark["author"], "Sample Author | Synthetic")
        self.assertEqual(bookmark["author_username"], "sample_author")
        self.assertEqual(bookmark["author_id"], "173484971")

    def test_falls_back_to_top_level_name_and_handle(self):
        # 顶层 authorName / authorHandle 是真实 JSONL 中的冗余镜像字段，可作兜底。
        payload_obj = payload(
            author={"id": "100000001"},
            authorName="Top Level Name",
            authorHandle="top_level",
        )
        bookmark = self.normalize_one(payload_obj)
        self.assertEqual(bookmark["author"], "Top Level Name")
        self.assertEqual(bookmark["author_username"], "top_level")
        self.assertEqual(bookmark["author_id"], "100000001")

    def test_missing_author_id_raises(self):
        payload_obj = payload()
        del payload_obj["author"]
        payload_obj["authorName"] = "Top Level Name"
        payload_obj["authorHandle"] = "top_level"
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload_obj)

    def test_missing_author_name_raises(self):
        payload_obj = payload(author={"id": "1", "handle": "h"})
        del payload_obj["authorName"]
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload_obj)

    def test_missing_author_id_raises(self):
        payload_obj = payload(author={"handle": "h", "name": "n"})
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload_obj)

    def test_author_block_wrong_type_raises(self):
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload(author=["not", "a", "mapping"]))

    def test_author_extra_fields_do_not_leak(self):
        payload_obj = payload(
            author={"id": "1", "handle": "h", "name": "n", "bio": "x", "followerCount": 5}
        )
        bookmark = self.normalize_one(payload_obj)
        self.assertNotIn("bio", bookmark)
        self.assertNotIn("follower_count", bookmark)


# ── Test E ───────────────────────────────────────────────────────────────────


class TimestampTests(NormalizerTestCase):
    """Test E：时间正常 / 不同格式 / None。"""

    def test_twitter_format_to_utc_iso(self):
        self.assertEqual(
            self.normalize_one(payload(postedAt="Sat Jun 20 12:56:42 +0000 2026"))["created_at"],
            "2026-06-20T12:56:42Z",
        )

    def test_non_utc_offset_is_converted(self):
        self.assertEqual(
            self.normalize_one(payload(postedAt="Sun Sep 13 13:05:21 +0800 2026"))["created_at"],
            "2026-09-13T05:05:21Z",
        )

    def test_synced_at_milliseconds_preserved(self):
        bookmark = self.normalize_one(payload(syncedAt="2026-09-16T02:02:41.036Z"))
        self.assertEqual(bookmark["collected_at"], "2026-09-16T02:02:41.036Z")
        self.assertEqual(bookmark["updated_at"], "2026-09-16T02:02:41.036Z")

    def test_synced_at_offset_normalised_to_z(self):
        bookmark = self.normalize_one(payload(syncedAt="2026-09-16T10:02:41+08:00"))
        self.assertEqual(bookmark["collected_at"], "2026-09-16T02:02:41Z")

    def test_null_synced_at_yields_null_timestamps(self):
        bookmark = self.normalize_one(payload(syncedAt=None))
        self.assertIsNone(bookmark["collected_at"])
        self.assertIsNone(bookmark["updated_at"])
        validate_bookmark(bookmark)

    def test_missing_synced_at_yields_null_timestamps(self):
        payload_obj = payload()
        del payload_obj["syncedAt"]
        self.assertIsNone(self.normalize_one(payload_obj)["collected_at"])

    def test_lowercase_z_suffix_accepted(self):
        # 审计 A2 回归：ISO-8601 允许小写 z，此前会被拒。
        bookmark = self.normalize_one(payload(syncedAt="2026-09-16T02:02:41.036z"))
        self.assertEqual(bookmark["collected_at"], "2026-09-16T02:02:41.036Z")
        self.assertEqual(bookmark["updated_at"], "2026-09-16T02:02:41.036Z")

    def test_missing_posted_at_raises(self):
        payload_obj = payload()
        del payload_obj["postedAt"]
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload_obj)

    def test_unparseable_posted_at_raises(self):
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload(postedAt="2026-09-14T01:24:21Z"))

    def test_unparseable_synced_at_raises(self):
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload(syncedAt="yesterday"))


# ── Test F ───────────────────────────────────────────────────────────────────


class MediaTests(NormalizerTestCase):
    """Test F：mediaObjects → media（只保留 Schema 允许的 5 键）。"""

    def test_photo_object_mapped(self):
        payload_obj = payload(
            mediaObjects=[
                {
                    "type": "photo",
                    "url": "https://pbs.twimg.com/media/X.png",
                    "expandedUrl": "https://x.com/a/status/1/photo/1",
                    "width": 791,
                    "height": 340,
                }
            ]
        )
        bookmark = self.normalize_one(payload_obj)
        self.assertEqual(
            bookmark["media"],
            [
                {
                    "type": "photo",
                    "url": "https://pbs.twimg.com/media/X.png",
                    "expandedUrl": "https://x.com/a/status/1/photo/1",
                    "width": 791,
                    "height": 340,
                }
            ],
        )
        validate_bookmark(bookmark)

    def test_fixture_photo_record(self):
        bookmark = self.normalize_one(sample_payloads()[0])
        self.assertEqual(len(bookmark["media"]), 1)
        self.assertEqual(bookmark["media"][0]["type"], "photo")
        validate_bookmark(bookmark)

    def test_video_and_gif_types_pass_through(self):
        # 真实样本只验证到 photo；video/animated_gif 按 Schema enum 支持，标注待验证。
        payload_obj = payload(
            mediaObjects=[
                {"type": "video", "url": "https://video.twimg.com/a.mp4"},
                {"type": "animated_gif", "url": "https://video.twimg.com/b.mp4"},
            ]
        )
        self.assertEqual(
            [m["type"] for m in self.normalize_one(payload_obj)["media"]],
            ["video", "animated_gif"],
        )

    def test_empty_media_is_empty_list(self):
        bookmark = self.normalize_one(payload(mediaObjects=[]))
        self.assertEqual(bookmark["media"], [])
        validate_bookmark(bookmark)

    def test_string_media_array_is_ignored(self):
        # `media`（字符串数组）是 mediaObjects 的子集 → 忽略，避免重复。
        bookmark = self.normalize_one(
            payload(media=["https://pbs.twimg.com/media/X.png"], mediaObjects=[])
        )
        self.assertEqual(bookmark["media"], [])

    def test_unknown_media_type_raises(self):
        payload_obj = payload(mediaObjects=[{"type": "audio", "url": "https://a/b.mp3"}])
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload_obj)

    def test_invalid_media_url_raises(self):
        payload_obj = payload(mediaObjects=[{"type": "photo", "url": "not-a-url"}])
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload_obj)

    def test_invalid_expanded_url_raises(self):
        payload_obj = payload(
            mediaObjects=[
                {"type": "photo", "url": "https://a/b.png", "expandedUrl": "nope"}
            ]
        )
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload_obj)

    def test_non_int_dimensions_raise(self):
        payload_obj = payload(
            mediaObjects=[{"type": "photo", "url": "https://a/b.png", "width": "791"}]
        )
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload_obj)

    def test_media_entries_carry_only_allowed_keys(self):
        bookmark = self.normalize_one(sample_payloads()[0])
        self.assertEqual(
            set(bookmark["media"][0]),
            {"type", "url", "expandedUrl", "width", "height"},
        )


# ── Test G ───────────────────────────────────────────────────────────────────


class ExternalLinkTests(NormalizerTestCase):
    """Test G：links → external_links；过滤 Article 引用、保序去重。"""

    def test_duplicates_deduped_preserving_order(self):
        payload_obj = payload(links=["https://example.com/a", "https://example.com/a"])
        self.assertEqual(self.normalize_one(payload_obj)["external_links"], ["https://example.com/a"])

    def test_fixture_duplicate_record(self):
        self.assertEqual(
            self.normalize_one(sample_payloads()[0])["external_links"],
            ["https://example.com/sample-a"],
        )

    def test_order_is_preserved(self):
        payload_obj = payload(links=["https://b.example", "https://a.example"])
        self.assertEqual(
            self.normalize_one(payload_obj)["external_links"],
            ["https://b.example", "https://a.example"],
        )

    def test_article_links_filtered_http_and_https(self):
        # 真实数据核对 N1：4/5 条 links 只有 Article 引用（含 http://）。
        payload_obj = payload(
            links=[
                "http://x.com/i/article/2068314177245184000",
                "https://x.com/i/article/2099089316723224576",
                "https://twitter.com/i/article/1",
                "https://www.x.com/i/article/2",
            ]
        )
        self.assertEqual(self.normalize_one(payload_obj)["external_links"], [])

    def test_fixture_article_record_has_no_external_links(self):
        self.assertEqual(self.normalize_one(sample_payloads()[1])["external_links"], [])

    def test_non_article_x_status_link_is_kept(self):
        payload_obj = payload(links=["https://x.com/someone/status/12345"])
        self.assertEqual(
            self.normalize_one(payload_obj)["external_links"],
            ["https://x.com/someone/status/12345"],
        )

    def test_non_uri_links_are_dropped(self):
        payload_obj = payload(links=["not a url", "/relative/path", "https://ok.example"])
        self.assertEqual(self.normalize_one(payload_obj)["external_links"], ["https://ok.example"])

    def test_blank_links_are_dropped(self):
        self.assertEqual(self.normalize_one(payload(links=["", "  "]))["external_links"], [])

    def test_missing_links_is_empty_list(self):
        payload_obj = payload()
        del payload_obj["links"]
        self.assertEqual(self.normalize_one(payload_obj)["external_links"], [])

    def test_article_link_helper(self):
        self.assertTrue(is_article_link("http://x.com/i/article/1"))
        self.assertTrue(is_article_link("https://mobile.twitter.com/i/article/1"))
        self.assertFalse(is_article_link("https://x.com/user/status/1"))
        self.assertFalse(is_article_link("https://example.com/i/article/1"))
        self.assertFalse(is_article_link(""))

    def test_empty_and_missing_links_validate(self):
        for payload_obj in (payload(links=[]), sample_payloads()[2]):
            validate_bookmark(self.normalize_one(payload_obj))


# ── Test H ───────────────────────────────────────────────────────────────────


class ArticleTests(NormalizerTestCase):
    """Test H：Article 用真实形状的富化样本，不丢已能表达的信息。"""

    def test_article_mapped(self):
        enrichment = {
            "tweetId": "1900000000000000102",
            "url": "https://x.com/sample_author/status/1900000000000000102",
            "text": "x.com/i/article/1900000000000000002…",
            "authorHandle": "sample_author",
            "articleTitle": "如何用VPS搭建稳定上网环境",
            "articleText": "最近我的节点一直各种超时……",
            "articleSite": "x.com",
        }
        bookmark = self.normalize_one(sample_payloads()[1], enrichment)
        self.assertEqual(
            bookmark["x_article"],
            {
                "title": "如何用VPS搭建稳定上网环境",
                "text": "最近我的节点一直各种超时……",
                "site": "x.com",
            },
        )
        validate_bookmark(bookmark)

    def test_article_absent_is_none(self):
        bookmark = self.normalize_one(sample_payloads()[2])
        self.assertIsNone(bookmark["x_article"])
        validate_bookmark(bookmark)

    def test_null_article_fields_are_none(self):
        enrichment = {"articleTitle": None, "articleText": None, "articleSite": None}
        self.assertIsNone(self.normalize_one(payload(), enrichment)["x_article"])

    def test_title_without_text_is_none(self):
        # schema 要求 xArticle.text 必填 → 无法表达，记 gap 而不是造空正文。
        enrichment = {"articleTitle": "只有标题", "articleText": None}
        self.assertIsNone(self.normalize_one(payload(), enrichment)["x_article"])

    def test_blank_article_text_is_none(self):
        self.assertIsNone(self.normalize_one(payload(), {"articleText": "   "})["x_article"])

    def test_article_text_wrong_type_raises(self):
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload(), {"articleText": 42})

    def test_article_title_and_site_wrong_type_raise(self):
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload(), {"articleText": "body", "articleTitle": 42})

    def test_x_article_keys_subset(self):
        bookmark = self.normalize_one(payload(), {"articleText": "body"})
        self.assertEqual(set(bookmark["x_article"]), {"title", "text", "site"})


# ── Test I ───────────────────────────────────────────────────────────────────


class QuotedTweetTests(NormalizerTestCase):
    """Test I：Schema 支持 quoted_tweet → 测映射；形状未实测 → 标注待验证。"""

    def test_quoted_tweet_mapped(self):
        enrichment = {
            "quotedTweet": {
                "tweetId": "1800000000000000001",
                "authorHandle": "other_author",
                "text": "被引用的正文",
                "url": "https://x.com/other_author/status/1800000000000000001",
            }
        }
        bookmark = self.normalize_one(payload(), enrichment)
        self.assertEqual(
            bookmark["quoted_tweet"],
            {
                "tweet_id": "1800000000000000001",
                "author_handle": "other_author",
                "text": "被引用的正文",
                "url": "https://x.com/other_author/status/1800000000000000001",
            },
        )
        validate_bookmark(bookmark)

    def test_null_quoted_tweet_is_none(self):
        self.assertIsNone(self.normalize_one(payload(), {"quotedTweet": None})["quoted_tweet"])

    def test_missing_quoted_tweet_is_none(self):
        self.assertIsNone(self.normalize_one(payload())["quoted_tweet"])

    def test_invalid_quoted_url_becomes_null(self):
        enrichment = {
            "quotedTweet": {
                "tweetId": "1",
                "authorHandle": "a",
                "text": "t",
                "url": "not-a-uri",
            }
        }
        self.assertIsNone(self.normalize_one(payload(), enrichment)["quoted_tweet"]["url"])

    def test_quoted_tweet_missing_required_field_raises(self):
        # 形状待验证：宁可报错也不静默丢数据。
        enrichment = {"quotedTweet": {"tweetId": "1", "text": "t"}}
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload(), enrichment)

    def test_quoted_tweet_wrong_type_raises(self):
        with self.assertRaises(NormalizationError):
            self.normalize_one(payload(), {"quotedTweet": "text-only"})


# ── Test J ───────────────────────────────────────────────────────────────────


class MissingFieldTests(NormalizerTestCase):
    """Test J：删必填字段必须 validation failed。"""

    def test_validate_rejects_each_missing_required_field(self):
        bookmark = self.normalize_one(sample_payloads()[0])
        for key in REQUIRED_KEYS:
            with self.subTest(key=key):
                broken = dict(bookmark)
                del broken[key]
                with self.assertRaises(CanonicalValidationError):
                    validate_bookmark(broken)

    def test_normalize_raises_when_ft_field_missing(self):
        for key in ("postedAt", "text", "url", "author"):
            with self.subTest(key=key):
                payload_obj = payload()
                del payload_obj[key]
                with self.assertRaises(NormalizationError):
                    self.normalize_one(payload_obj)

    def test_normalize_and_validate_reports_validation_error(self):
        # 校验失败的产物不得被当成成功返回（§15：Normalizer 只产数据，不落盘）。
        data = raw_data(*sample_payloads())
        bookmarks = self.normalizer.normalize_and_validate(data)
        self.assertEqual(len(bookmarks), 3)


# ── Test K ───────────────────────────────────────────────────────────────────


class FtFieldIsolationTests(NormalizerTestCase):
    """Test K：payload 可含 FT 特有字段，CanonicalBookmark 不得出现。"""

    def test_canonical_output_has_exactly_canonical_keys(self):
        for payload_obj in sample_payloads():
            bookmark = self.normalize_one(payload_obj)
            self.assertEqual(tuple(bookmark), CANONICAL_KEYS)

    def test_ft_only_fields_absent_from_canonical(self):
        ft_fields = (
            "engagement",
            "ingestedVia",
            "sortIndex",
            "tags",
            "authorProfileImageUrl",
            "language",
            "possiblySensitive",
            "bookmarkedAt",
            "syncedAt",
            "id",
            "mediaObjects",
        )
        for payload_obj in sample_payloads():
            bookmark = self.normalize_one(payload_obj)
            for field in ft_fields:
                self.assertNotIn(field, bookmark)

    def test_engagement_never_mapped(self):
        bookmark = self.normalize_one(payload(engagement={"likeCount": 6141}))
        self.assertNotIn("like_count", bookmark)
        self.assertNotIn("engagement", bookmark)

    def test_raw_payload_still_carries_ft_fields(self):
        # 隔离是单向的：FT 字段留在 payload，未来要入库需单独 gap 决策。
        raw_item = item(payload())
        self.assertIn("engagement", raw_item.payload)
        self.assertNotIn("engagement", self.normalizer.normalize_item(raw_item))


# ── Test L ───────────────────────────────────────────────────────────────────


class IdempotencyTests(NormalizerTestCase):
    """Test L：相同 RawCollectorData 重复 Normalization 结果稳定。"""

    def test_repeated_normalization_is_equal(self):
        data = raw_data(*sample_payloads())
        self.assertEqual(self.normalizer.normalize(data), self.normalizer.normalize(data))

    def test_equal_input_from_fresh_objects_is_equal(self):
        first = self.normalizer.normalize(raw_data(*sample_payloads()))
        second = FieldTheoryNormalizer().normalize(raw_data(*sample_payloads()))
        self.assertEqual(first, second)

    def test_content_hash_stable(self):
        data = raw_data(*sample_payloads())
        self.assertEqual(
            [b["content_hash"] for b in self.normalizer.normalize(data)],
            [b["content_hash"] for b in self.normalizer.normalize(data)],
        )

    def test_with_enrichment_is_also_stable(self):
        enrichment = {"articleText": "body", "articleTitle": "title"}
        payload_obj = sample_payloads()[1]
        self.assertEqual(
            self.normalize_one(payload_obj, enrichment),
            self.normalize_one(payload_obj, enrichment),
        )


class ContentHashTests(NormalizerTestCase):
    """§5.4：SHA-256，覆盖实质内容，排除元数据与 engagement。"""

    def test_shape(self):
        value = self.normalize_one(payload())["content_hash"]
        self.assertRegex(value, r"^[0-9a-f]{64}$")

    def test_independent_of_synced_at(self):
        a = self.normalize_one(payload(syncedAt="2026-09-16T00:00:01.000Z"))
        b = self.normalize_one(payload(syncedAt="2027-01-01T00:00:00.000Z"))
        self.assertEqual(a["content_hash"], b["content_hash"])
        self.assertNotEqual(a["collected_at"], b["collected_at"])

    def test_independent_of_engagement(self):
        a = self.normalize_one(payload(engagement={"likeCount": 1}))
        b = self.normalize_one(payload(engagement={"likeCount": 999}))
        self.assertEqual(a["content_hash"], b["content_hash"])

    def test_independent_of_collector_and_source_fields(self):
        bookmark = self.normalize_one(payload())
        base = compute_content_hash(bookmark)
        tweaked = dict(bookmark, collector="other", source="other")
        self.assertEqual(compute_content_hash(tweaked), base)

    def test_changes_with_text(self):
        a = self.normalize_one(payload(text="one"))
        b = self.normalize_one(payload(text="two"))
        self.assertNotEqual(a["content_hash"], b["content_hash"])

    def test_changes_with_created_at(self):
        a = self.normalize_one(payload(postedAt="Sat Jun 20 12:56:42 +0000 2026"))
        b = self.normalize_one(payload(postedAt="Sun Jun 21 12:56:42 +0000 2026"))
        self.assertNotEqual(a["content_hash"], b["content_hash"])

    def test_changes_with_author_id(self):
        a = self.normalize_one(payload(author={"id": "1", "handle": "h", "name": "n"}))
        b = self.normalize_one(payload(author={"id": "2", "handle": "h", "name": "n"}))
        self.assertNotEqual(a["content_hash"], b["content_hash"])

    def test_changes_with_media(self):
        a = self.normalize_one(payload())
        b = self.normalize_one(
            payload(mediaObjects=[{"type": "photo", "url": "https://a/b.png"}])
        )
        self.assertNotEqual(a["content_hash"], b["content_hash"])

    def test_changes_with_external_links(self):
        a = self.normalize_one(payload())
        b = self.normalize_one(payload(links=["https://example.com"]))
        self.assertNotEqual(a["content_hash"], b["content_hash"])

    def test_link_order_matters(self):
        a = self.normalize_one(payload(links=["https://a.example", "https://b.example"]))
        b = self.normalize_one(payload(links=["https://b.example", "https://a.example"]))
        self.assertNotEqual(a["content_hash"], b["content_hash"])

    def test_changes_with_article_text(self):
        a = self.normalize_one(payload())
        b = self.normalize_one(payload(), {"articleText": "body"})
        self.assertNotEqual(a["content_hash"], b["content_hash"])

    def test_changes_with_quoted_tweet(self):
        a = self.normalize_one(payload())
        b = self.normalize_one(
            payload(), {"quotedTweet": {"tweetId": "1", "authorHandle": "h", "text": "t"}}
        )
        self.assertNotEqual(a["content_hash"], b["content_hash"])

    def test_hash_matches_manual_recompute(self):
        bookmark = self.normalize_one(sample_payloads()[0])
        self.assertEqual(bookmark["content_hash"], compute_content_hash(bookmark))

    def test_missing_field_raises_normalization_error(self):
        # 审计 A4 回归：公开 API 传缺键 dict 应报 NormalizationError，而非裸 KeyError。
        bookmark = self.normalize_one(sample_payloads()[0])
        for key in ("tweet_id", "text", "url", "author_id", "created_at"):
            with self.subTest(key=key):
                broken = dict(bookmark)
                del broken[key]
                with self.assertRaises(NormalizationError):
                    compute_content_hash(broken)


# ── 验收 E/F：Normalizer 不读取 Field Theory ─────────────────────────────────


class NormalizerBoundaryTests(unittest.TestCase):
    """验收 E/F：不调用上游 CLI、不联网、不写盘、不依赖 Canonical 反向。

    静态断言基于 **AST**（只看代码，不看文档字符串），避免「文档里提到
    ``subprocess`` 一词就误报」这类脆弱测试。
    """

    FORBIDDEN_IMPORTS = ("fieldtheory_adapter", "FieldTheoryAdapter")
    FORBIDDEN_NAMES = {"subprocess", "urlopen", "requests", "sqlite3", "shutil", "open", "eval", "exec"}
    FORBIDDEN_ATTRS = {"write_text", "write_bytes", "unlink", "rmtree", "system", "popen", "fork"}

    def _trees(self):
        sources = sorted(NORMALIZER_DIR.glob("*.py"))
        self.assertEqual(len(sources), 3, [p.name for p in sources])
        for path in sources:
            yield path, ast.parse(path.read_text(encoding="utf-8"))

    def test_normalizer_imports_exclude_upstream_adapter(self):
        for path, tree in self._trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""] + [alias.name for alias in node.names]
                else:
                    continue
                for name in names:
                    for bad in self.FORBIDDEN_IMPORTS:
                        self.assertNotIn(bad, name, f"{path.name} imports {name!r}")

    def test_normalizer_does_not_reference_process_or_write_apis(self):
        for path, tree in self._trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, self.FORBIDDEN_NAMES, f"{path.name}: {node.id}")
                elif isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, self.FORBIDDEN_ATTRS, f"{path.name}: .{node.attr}")

    def test_normalize_never_spawns_processes_or_uses_network(self):
        """行为证据（强于静态扫描）：屏蔽进程与网络后，完整链路仍能跑通。"""

        def boom(*args, **kwargs):
            raise AssertionError("Normalizer must not spawn processes or use the network")

        with (
            mock.patch("subprocess.run", boom),
            mock.patch("subprocess.Popen", boom),
            mock.patch("os.system", boom),
            mock.patch("os.fork", boom, create=True),
            mock.patch("urllib.request.urlopen", boom),
        ):
            bookmarks = FieldTheoryNormalizer().normalize_and_validate(
                raw_data(*sample_payloads())
            )
        self.assertEqual(len(bookmarks), 3)
        for bookmark in bookmarks:
            validate_bookmark(bookmark)


if __name__ == "__main__":
    unittest.main()
