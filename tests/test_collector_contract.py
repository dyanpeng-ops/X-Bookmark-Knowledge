"""Contract tests for the frozen upstream data contract.

The fixtures under `tests/fixtures/upstream/` are synthetic but structurally
identical to the real capture of 2026-09-16 (see
`research/architecture-decision.md` §4.3). The snapshot test at the top of
`BookmarkRecordContractTests` fails if the frozen key set changes, which is the
signal that a real upstream sample must be re-captured and re-reviewed.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.collector import contract  # noqa: E402  (path bootstrap must run first)
from src.collector.base import UpstreamContractError  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "upstream"

# Frozen from the real capture (fieldtheory 1.3.22, 2026-09-16, 5 records).
REAL_JSONL_REQUIRED_KEYS = (
    "id",
    "tweetId",
    "url",
    "text",
    "authorHandle",
    "authorName",
    "authorProfileImageUrl",
    "author",
    "postedAt",
    "bookmarkedAt",
    "syncedAt",
    "conversationId",
    "language",
    "possiblySensitive",
    "engagement",
    "media",
    "mediaObjects",
    "links",
    "tags",
    "ingestedVia",
    "sortIndex",
)
REAL_JSONL_OPTIONAL_KEYS = ("textExpandedAt",)


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_jsonl(name: str):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class BookmarkRecordContractTests(unittest.TestCase):
    """`bookmarks.jsonl` contract."""

    def test_frozen_key_set_matches_real_capture(self):
        self.assertEqual(contract.JSONL_REQUIRED_KEYS, REAL_JSONL_REQUIRED_KEYS)
        self.assertEqual(contract.JSONL_OPTIONAL_KEYS, REAL_JSONL_OPTIONAL_KEYS)
        self.assertEqual(contract.UPSTREAM_VERSION_SEEN, "1.3.22")

    def test_sample_records_satisfy_contract(self):
        records = load_jsonl("bookmarks.sample.jsonl")
        self.assertEqual(len(records), 3)
        for index, record in enumerate(records):
            contract.validate_bookmark_record(record, f"sample[{index}]")

    def test_record_without_optional_field_still_valid(self):
        record = load_jsonl("bookmarks.sample.jsonl")[2]
        self.assertNotIn("textExpandedAt", record)
        contract.validate_bookmark_record(record)

    def test_unknown_extra_key_is_ignored(self):
        record = load_jsonl("bookmarks.sample.jsonl")[0]
        record["someFutureField"] = {"anything": True}
        contract.validate_bookmark_record(record)

    def test_missing_required_key_raises(self):
        record = load_jsonl("bookmarks.sample.jsonl")[0]
        del record["tweetId"]
        with self.assertRaises(UpstreamContractError) as ctx:
            contract.validate_bookmark_record(record)
        self.assertIn("tweetId", str(ctx.exception))

    def test_required_key_must_not_be_null(self):
        record = load_jsonl("bookmarks.sample.jsonl")[0]
        record["text"] = None
        with self.assertRaises(UpstreamContractError):
            contract.validate_bookmark_record(record)

    def test_nullable_bookmarked_at_is_accepted(self):
        record = load_jsonl("bookmarks.sample.jsonl")[0]
        self.assertIsNone(record["bookmarkedAt"])
        contract.validate_bookmark_record(record)

    def test_wrong_scalar_type_raises(self):
        record = load_jsonl("bookmarks.sample.jsonl")[0]
        record["postedAt"] = 12345
        with self.assertRaises(UpstreamContractError) as ctx:
            contract.validate_bookmark_record(record)
        self.assertIn("postedAt", str(ctx.exception))

    def test_engagement_counter_rejects_bool(self):
        record = load_jsonl("bookmarks.sample.jsonl")[0]
        record["engagement"]["likeCount"] = True
        with self.assertRaises(UpstreamContractError):
            contract.validate_bookmark_record(record)

    def test_author_object_is_validated(self):
        record = load_jsonl("bookmarks.sample.jsonl")[0]
        record["author"]["followerCount"] = "many"
        with self.assertRaises(UpstreamContractError):
            contract.validate_bookmark_record(record)

    def test_media_entries_must_be_strings(self):
        record = load_jsonl("bookmarks.sample.jsonl")[0]
        record["media"] = [{"url": "https://example.com/a.png"}]
        with self.assertRaises(UpstreamContractError):
            contract.validate_bookmark_record(record)

    def test_media_object_shape_is_validated(self):
        record = load_jsonl("bookmarks.sample.jsonl")[0]
        record["mediaObjects"] = [{"url": "https://example.com/a.png"}]
        with self.assertRaises(UpstreamContractError) as ctx:
            contract.validate_bookmark_record(record)
        self.assertIn("type", str(ctx.exception))

    def test_record_must_be_an_object(self):
        with self.assertRaises(UpstreamContractError):
            contract.validate_bookmark_record(["not", "a", "record"])


class MediaManifestContractTests(unittest.TestCase):
    """`media-manifest.json` contract."""

    def test_sample_manifest_satisfies_contract(self):
        manifest = load_json("media-manifest.sample.json")
        contract.validate_media_manifest(manifest)
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(len(manifest["entries"]), 2)

    def test_observed_status_is_downloaded(self):
        manifest = load_json("media-manifest.sample.json")
        statuses = {entry["status"] for entry in manifest["entries"]}
        self.assertTrue(statuses.issubset(set(contract.MEDIA_STATUS_OBSERVED)))

    def test_unsupported_schema_version_raises(self):
        manifest = load_json("media-manifest.sample.json")
        manifest["schemaVersion"] = 99
        with self.assertRaises(UpstreamContractError) as ctx:
            contract.validate_media_manifest(manifest)
        self.assertIn("schemaVersion", str(ctx.exception))

    def test_missing_top_level_key_raises(self):
        manifest = load_json("media-manifest.sample.json")
        del manifest["entries"]
        with self.assertRaises(UpstreamContractError):
            contract.validate_media_manifest(manifest)

    def test_entry_missing_local_path_raises(self):
        manifest = load_json("media-manifest.sample.json")
        del manifest["entries"][0]["localPath"]
        with self.assertRaises(UpstreamContractError) as ctx:
            contract.validate_media_manifest(manifest)
        self.assertIn("localPath", str(ctx.exception))

    def test_entry_byte_count_must_be_int(self):
        manifest = load_json("media-manifest.sample.json")
        manifest["entries"][0]["bytes"] = "28243"
        with self.assertRaises(UpstreamContractError):
            contract.validate_media_manifest(manifest)


class MetaAndBackfillContractTests(unittest.TestCase):
    """`bookmarks-meta.json` and `bookmarks-backfill-state.json` contracts."""

    def test_sample_meta_satisfies_contract(self):
        contract.validate_meta(load_json("bookmarks-meta.sample.json"))

    def test_meta_requires_schema_version(self):
        payload = load_json("bookmarks-meta.sample.json")
        del payload["schemaVersion"]
        with self.assertRaises(UpstreamContractError):
            contract.validate_meta(payload)

    def test_sample_backfill_state_satisfies_contract(self):
        payload = load_json("bookmarks-backfill-state.sample.json")
        contract.validate_backfill_state(payload)
        self.assertEqual(payload["stopReason"], "end of bookmarks")

    def test_backfill_state_requires_stop_reason(self):
        payload = load_json("bookmarks-backfill-state.sample.json")
        del payload["stopReason"]
        with self.assertRaises(UpstreamContractError):
            contract.validate_backfill_state(payload)

    def test_last_cursor_is_conditional(self):
        """Real data omits `lastCursor` unless the run stopped at a page limit."""

        payload = load_json("bookmarks-backfill-state.sample.json")
        self.assertIn("lastCursor", payload)
        contract.validate_backfill_state(payload)
        del payload["lastCursor"]
        contract.validate_backfill_state(payload)

    def test_observed_stop_reasons_are_documented(self):
        self.assertIn(
            "caught up to newest stored bookmark", contract.BACKFILL_STOP_REASONS_OBSERVED
        )


class EnrichedRecordContractTests(unittest.TestCase):
    """`fieldtheory list --json` / `show --json` contract."""

    def test_sample_list_satisfies_contract(self):
        records = load_json("list.sample.json")
        self.assertEqual(len(records), 2)
        for index, record in enumerate(records):
            contract.validate_enriched_record(record, f"list[{index}]")

    def test_article_fields_are_optional(self):
        records = load_json("list.sample.json")
        self.assertIsNotNone(records[0]["articleText"])
        self.assertIsNone(records[1]["articleText"])
        for record in records:
            contract.validate_enriched_record(record)

    def test_missing_tweet_id_raises(self):
        record = load_json("list.sample.json")[0]
        del record["tweetId"]
        with self.assertRaises(UpstreamContractError):
            contract.validate_enriched_record(record)

    def test_quoted_tweet_must_be_object_or_null(self):
        record = load_json("list.sample.json")[0]
        record["quotedTweet"] = "should-be-object"
        with self.assertRaises(UpstreamContractError) as ctx:
            contract.validate_enriched_record(record)
        self.assertIn("quotedTweet", str(ctx.exception))

    def test_view_count_may_be_null(self):
        record = load_json("list.sample.json")[0]
        self.assertIsNone(record["viewCount"])
        contract.validate_enriched_record(record)

    def test_folder_names_must_be_a_list(self):
        record = load_json("list.sample.json")[1]
        record["folderNames"] = "Sample Folder"
        with self.assertRaises(UpstreamContractError):
            contract.validate_enriched_record(record)


class DatetimeParsingTests(unittest.TestCase):
    """The two upstream timestamp formats."""

    def test_parse_posted_at_rfc822_like(self):
        parsed = contract.parse_twitter_datetime("Sat Jun 20 12:56:42 +0000 2026")
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.month, 6)
        self.assertEqual(parsed.day, 20)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_parse_posted_at_rejects_garbage(self):
        with self.assertRaises(UpstreamContractError):
            contract.parse_twitter_datetime("2026-06-20T12:56:42Z")

    def test_parse_iso_with_z_suffix(self):
        parsed = contract.parse_iso_datetime("2026-09-16T02:02:41.036Z")
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.microsecond, 36000)

    def test_parse_iso_rejects_garbage(self):
        with self.assertRaises(UpstreamContractError):
            contract.parse_iso_datetime("yesterday")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
