"""CanonicalBookmark schema 契约测试（离线，标准库 unittest）。

验证 `src/canonical/validate.py` 与 `schema/bookmark.schema.json` 的一致性：
- 合法样本通过校验；
- 各类非法样本（缺必填键、错类型、错时间/URI 格式、错固定值、未知键、
  越界枚举、错误 media/外链/quoted_tweet/x_article 结构）被拒绝。

同时校验 schema 文件本身的静态结构（required / properties / $defs 与校验器
对齐），防止 schema 与实现漂移。

全部离线：不读真实 data/，不联网，不写盘。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.canonical.validate import (
    CanonicalValidationError,
    REQUIRED_FIELDS,
    validate_bookmark,
)

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "bookmark.schema.json"

_CONTENT_HASH = "a" * 64  # 合法形状（不参与语义，仅格式校验）


def _valid() -> dict:
    """返回一条结构合法的 CanonicalBookmark 样本。"""
    return {
        "tweet_id": "2098040323830407200",
        "author": "小码哥",
        "author_id": "1769141715351605248",
        "author_username": "xmglab",
        "created_at": "2026-09-14T01:24:21Z",
        "text": "大家好，我是小码哥。",
        "url": "https://x.com/xmglab/status/2098040323830407200",
        "conversation_id": "2098040323830407200",
        "source": "x",
        "collector": "fieldtheory",
        "quoted_tweet": None,
        "reply_to": None,
        "thread": None,
        "media": [],
        "external_links": [],
        "x_article": None,
        "collected_at": "2026-10-08T12:00:00Z",
        "updated_at": None,
        "content_hash": _CONTENT_HASH,
    }


class ValidBookmarkTests(unittest.TestCase):
    def test_minimal_valid(self):
        # 空 media / external_links 是合法的（决策 A：字段存在、空数组）。
        validate_bookmark(_valid())

    def test_with_media_object(self):
        data = _valid()
        data["media"] = [
            {
                "type": "photo",
                "url": "https://pbs.twimg.com/media/abc.jpg",
                "expandedUrl": "https://pbs.twimg.com/media/abc.jpg",
                "width": 1200,
                "height": 800,
            }
        ]
        validate_bookmark(data)

    def test_with_external_links(self):
        data = _valid()
        data["external_links"] = ["https://github.com/Yu9191/wloc"]
        validate_bookmark(data)

    def test_with_quoted_tweet(self):
        data = _valid()
        data["quoted_tweet"] = {
            "tweet_id": "123",
            "author_handle": "someone",
            "text": "quoted",
            "url": "https://x.com/someone/status/123",
        }
        validate_bookmark(data)

    def test_with_x_article(self):
        data = _valid()
        data["x_article"] = {"title": "标题", "text": "正文", "site": "x.com"}
        validate_bookmark(data)

    def test_with_thread(self):
        data = _valid()
        data["thread"] = ["1", "2", "3"]
        validate_bookmark(data)

    def test_created_at_with_offset(self):
        data = _valid()
        data["created_at"] = "2026-09-14T01:24:21+00:00"
        validate_bookmark(data)


class RequiredFieldTests(unittest.TestCase):
    def test_missing_each_required_field(self):
        for key in REQUIRED_FIELDS:
            data = _valid()
            data.pop(key)
            with self.subTest(key=key):
                with self.assertRaises(CanonicalValidationError):
                    validate_bookmark(data)

    def test_empty_tweet_id_rejected(self):
        data = _valid()
        data["tweet_id"] = ""
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)


class TypeAndConstTests(unittest.TestCase):
    def test_wrong_type(self):
        data = _valid()
        data["tweet_id"] = 123
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)

    def test_source_const_violation(self):
        data = _valid()
        data["source"] = "graphql"  # fieldtheory 内部值，违反 D5
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)

    def test_unknown_field_rejected(self):
        data = _valid()
        data["ingestedVia"] = "graphql"  # 上游专属字段不应出现在 Canonical
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)

    def test_bad_datetime(self):
        data = _valid()
        data["created_at"] = "Sat Jun 20 12:56:42 +0000 2026"  # fieldtheory 原格式
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)

    def test_bad_uri(self):
        data = _valid()
        data["url"] = "not-a-uri"
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)

    def test_bad_content_hash(self):
        data = _valid()
        data["content_hash"] = "zzz"  # 非十六进制
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)


class MediaAndLinkTests(unittest.TestCase):
    def test_media_must_be_array(self):
        data = _valid()
        data["media"] = "not-array"
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)

    def test_media_bad_type(self):
        data = _valid()
        data["media"] = [{"type": "audio", "url": "https://x.com/a.mp3"}]
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)

    def test_media_missing_url(self):
        data = _valid()
        data["media"] = [{"type": "photo"}]
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)

    def test_external_links_must_be_uri(self):
        data = _valid()
        data["external_links"] = ["not-a-uri"]
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)


class NestedStructureTests(unittest.TestCase):
    def test_quoted_tweet_missing_text(self):
        data = _valid()
        data["quoted_tweet"] = {"tweet_id": "1", "author_handle": "a"}
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)

    def test_x_article_missing_text(self):
        data = _valid()
        data["x_article"] = {"title": "t"}
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)

    def test_thread_bad_element(self):
        data = _valid()
        data["thread"] = [1, 2]
        with self.assertRaises(CanonicalValidationError):
            validate_bookmark(data)


class SchemaFileConsistencyTests(unittest.TestCase):
    """锁定 schema 文件与校验器的 required / 字段集一致，防漂移。"""

    def setUp(self):
        self.assertTrue(
            _SCHEMA_PATH.exists(), f"schema 文件不存在: {_SCHEMA_PATH}"
        )
        self.schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_schema_is_draft_2020_12(self):
        self.assertEqual(
            self.schema.get("$schema"),
            "https://json-schema.org/draft/2020-12/schema",
        )

    def test_schema_required_matches_validator(self):
        self.assertEqual(set(self.schema["required"]), set(REQUIRED_FIELDS))

    def test_schema_rejects_additional_properties(self):
        self.assertFalse(self.schema.get("additionalProperties", True))

    def test_schema_source_const(self):
        self.assertEqual(self.schema["properties"]["source"].get("const"), "x")

    def test_schema_defs_present(self):
        for name in ("mediaObject", "quotedTweet", "xArticle"):
            self.assertIn(name, self.schema.get("$defs", {}))

    def test_schema_media_types_match(self):
        types = self.schema["$defs"]["mediaObject"]["properties"]["type"]["enum"]
        self.assertEqual(set(types), {"photo", "video", "animated_gif"})


if __name__ == "__main__":
    unittest.main()
