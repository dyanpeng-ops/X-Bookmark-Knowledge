"""Frozen upstream data contract (fieldtheory 1.3.22 on Windows).

Every rule below was derived from a real sample captured on 2026-09-16 and is
recorded in `research/architecture-decision.md` §4.3. Rules that were *not*
observed against real data are marked `UNVERIFIED`.

Validation is deliberately forward compatible: required keys must exist, known
keys must have the documented type, and unknown keys are ignored so a minor
upstream release cannot break ingestion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from .base import UpstreamContractError

__all__ = [
    "UPSTREAM_TOOL",
    "UPSTREAM_VERSION_SEEN",
    "CONTRACT_CAPTURED_AT",
    "JSONL_REQUIRED_KEYS",
    "JSONL_OPTIONAL_KEYS",
    "JSONL_KEY_TYPES",
    "AUTHOR_REQUIRED_KEYS",
    "AUTHOR_KEY_TYPES",
    "ENGAGEMENT_REQUIRED_KEYS",
    "ENGAGEMENT_KEY_TYPES",
    "MEDIA_OBJECT_REQUIRED_KEYS",
    "MEDIA_OBJECT_KEY_TYPES",
    "MANIFEST_REQUIRED_KEYS",
    "MANIFEST_KEY_TYPES",
    "MANIFEST_ENTRY_KEY_TYPES",
    "MANIFEST_SCHEMA_VERSIONS",
    "MEDIA_STATUS_OBSERVED",
    "META_KEY_TYPES",
    "BACKFILL_REQUIRED_KEYS",
    "BACKFILL_STOP_REASONS_OBSERVED",
    "ENRICHED_REQUIRED_KEYS",
    "ENRICHED_KEY_TYPES",
    "validate_bookmark_record",
    "validate_media_manifest",
    "validate_enriched_record",
    "validate_meta",
    "validate_backfill_state",
    "parse_twitter_datetime",
    "parse_iso_datetime",
]

UPSTREAM_TOOL = "fieldtheory"
UPSTREAM_VERSION_SEEN = "1.3.22"
CONTRACT_CAPTURED_AT = "2026-09-16"

# ── bookmarks.jsonl ──────────────────────────────────────────────────────────
# The JSONL is the raw per-bookmark cache. It never carries enrichment: article
# bodies, quoted tweets and classification live in the upstream SQLite database
# and are exposed through `fieldtheory list|show --json` only.

JSONL_REQUIRED_KEYS: tuple[str, ...] = (
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

# Observed only after `sync --gaps`; absent on untouched records.
JSONL_OPTIONAL_KEYS: tuple[str, ...] = ("textExpandedAt",)

JSONL_KEY_TYPES: Mapping[str, str] = {
    "id": "str",
    "tweetId": "str",
    "url": "str",
    "text": "str",
    "authorHandle": "str",
    "authorName": "str",
    "authorProfileImageUrl": "str",
    "author": "dict",
    "postedAt": "str",
    "bookmarkedAt": "str?",  # null on 5/5 real records
    "syncedAt": "str",
    "conversationId": "str?",
    "language": "str?",
    "possiblySensitive": "bool?",
    "engagement": "dict",
    "media": "list",
    "mediaObjects": "list",
    "links": "list",
    "tags": "list",
    "ingestedVia": "str?",
    "sortIndex": "str?",
    "textExpandedAt": "str?",
}

AUTHOR_REQUIRED_KEYS: tuple[str, ...] = ("id", "handle", "name")

AUTHOR_KEY_TYPES: Mapping[str, str] = {
    "id": "str",
    "handle": "str",
    "name": "str",
    "profileImageUrl": "str?",
    "bio": "str?",
    "followerCount": "int?",
    "followingCount": "int?",
    "isVerified": "bool?",
    "location": "str?",
    "snapshotAt": "str?",
}

ENGAGEMENT_REQUIRED_KEYS: tuple[str, ...] = (
    "likeCount",
    "repostCount",
    "replyCount",
    "quoteCount",
    "bookmarkCount",
)

ENGAGEMENT_KEY_TYPES: Mapping[str, str] = {
    "likeCount": "int?",
    "repostCount": "int?",
    "replyCount": "int?",
    "quoteCount": "int?",
    "bookmarkCount": "int?",
}

MEDIA_OBJECT_REQUIRED_KEYS: tuple[str, ...] = ("type", "url")

# UNVERIFIED: the photo variant below was observed on one real record
# (type/url/expandedUrl/width/height), but no video or multi-photo record was
# captured, so additional fields on those variants stay unconfirmed.
MEDIA_OBJECT_KEY_TYPES: Mapping[str, str] = {
    "type": "str",
    "url": "str",
    "expandedUrl": "str?",
    "width": "int?",
    "height": "int?",
}

# ── media-manifest.json ──────────────────────────────────────────────────────

MANIFEST_REQUIRED_KEYS: tuple[str, ...] = (
    "schemaVersion",
    "generatedAt",
    "limit",
    "maxBytes",
    "processed",
    "downloaded",
    "skippedTooLarge",
    "failed",
    "entries",
)

MANIFEST_KEY_TYPES: Mapping[str, str] = {
    "schemaVersion": "int",
    "generatedAt": "str?",
    "limit": "int?",
    "maxBytes": "int?",
    "processed": "int?",
    "downloaded": "int?",
    "skippedTooLarge": "int?",
    "failed": "int?",
    "entries": "list",
}

MANIFEST_ENTRY_KEY_TYPES: Mapping[str, str] = {
    "bookmarkId": "str",
    "tweetId": "str",
    "tweetUrl": "str?",
    "authorHandle": "str?",
    "authorName": "str?",
    "sourceUrl": "str",
    "localPath": "str",
    "contentType": "str?",
    "bytes": "int?",
    "status": "str",
    "fetchedAt": "str?",
}

MANIFEST_SCHEMA_VERSIONS: tuple[int, ...] = (1,)

# Only `downloaded` was observed. UNVERIFIED: skippedTooLarge/failed stayed 0 in
# the sample, so the status strings used on those paths are unknown.
MEDIA_STATUS_OBSERVED: tuple[str, ...] = ("downloaded",)

# ── bookmarks-meta.json / bookmarks-backfill-state.json ──────────────────────

META_KEY_TYPES: Mapping[str, str] = {
    "provider": "str",
    "schemaVersion": "int",
    "lastIncrementalSyncAt": "str?",
    "totalBookmarks": "int?",
}

BACKFILL_REQUIRED_KEYS: tuple[str, ...] = (
    "provider",
    "lastRunAt",
    "totalRuns",
    "totalAdded",
    "lastAdded",
    "lastSeenIds",
    "stopReason",
)

# `lastCursor` is conditional: it only exists on runs that stopped at a page
# limit (`stopReason: "max pages reached"`). Confirmed on real data 2026-09-16
# after a media-only run left the key out entirely.
#
# Observed `stopReason` values (non-exhaustive, upstream may add more):
BACKFILL_STOP_REASONS_OBSERVED: tuple[str, ...] = (
    "max pages reached",
    "end of bookmarks",
    "caught up to newest stored bookmark",
)

BACKFILL_KEY_TYPES: Mapping[str, str] = {
    "provider": "str?",
    "lastRunAt": "str?",
    "totalRuns": "int?",
    "totalAdded": "int?",
    "lastAdded": "int?",
    "lastSeenIds": "list?",
    "stopReason": "str?",
    "lastCursor": "str?",
}

# ── fieldtheory list --json / show --json ────────────────────────────────────
# Enriched shape. It is a database row, not a JSONL record: only this surface
# carries article text, quoted tweets, categories and folder membership.

ENRICHED_REQUIRED_KEYS: tuple[str, ...] = (
    "tweetId",
    "url",
    "text",
    "authorHandle",
)

ENRICHED_KEY_TYPES: Mapping[str, str] = {
    "id": "str?",
    "tweetId": "str",
    "url": "str",
    "text": "str",
    "authorHandle": "str",
    "authorName": "str?",
    "authorProfileImageUrl": "str?",
    "postedAt": "str?",
    "bookmarkedAt": "str?",
    "categories": "list?",
    "primaryCategory": "str?",
    "domains": "list?",
    "primaryDomain": "str?",
    "githubUrls": "list?",
    "links": "list?",
    "mediaCount": "int?",
    "linkCount": "int?",
    "likeCount": "int?",
    "repostCount": "int?",
    "replyCount": "int?",
    "quoteCount": "int?",
    "bookmarkCount": "int?",
    "viewCount": "int?",
    "folderIds": "list?",
    "folderNames": "list?",
    "articleTitle": "str?",
    "articleText": "str?",
    "articleSite": "str?",
    "syncedAt": "str?",
    "enrichedAt": "str?",
    "quotedStatusId": "str?",
    "quotedTweet": "dict?",
}

_TYPE_CHECKS: Mapping[str, tuple[type, ...]] = {
    "str": (str,),
    "int": (int,),
    "bool": (bool,),
    "list": (list,),
    "dict": (dict,),
}


def _check_value(key: str, value: Any, spec: str, where: str) -> None:
    optional = spec.endswith("?")
    base = spec[:-1] if optional else spec
    if value is None:
        if optional:
            return
        raise UpstreamContractError(f"{where}: key '{key}' must not be null (expected {base})")
    if base == "int":
        # bool is an int subclass; upstream counters are never booleans.
        if isinstance(value, bool) or not isinstance(value, int):
            raise UpstreamContractError(
                f"{where}: key '{key}' must be int, got {type(value).__name__}"
            )
        return
    if not isinstance(value, _TYPE_CHECKS[base]):
        raise UpstreamContractError(
            f"{where}: key '{key}' must be {base}, got {type(value).__name__}"
        )


def _check_keys(
    payload: Mapping[str, Any],
    required: Sequence[str],
    key_types: Mapping[str, str],
    where: str,
) -> None:
    if not isinstance(payload, Mapping):
        raise UpstreamContractError(f"{where}: expected an object, got {type(payload).__name__}")
    for key in required:
        if key not in payload:
            raise UpstreamContractError(f"{where}: missing required key '{key}'")
    for key, spec in key_types.items():
        if key in payload:
            _check_value(key, payload[key], spec, where)


def validate_bookmark_record(record: Mapping[str, Any], where: str = "bookmarks.jsonl") -> None:
    """Validate one JSONL record; unknown extra keys are ignored."""

    _check_keys(record, JSONL_REQUIRED_KEYS, JSONL_KEY_TYPES, where)
    _check_keys(record["author"], AUTHOR_REQUIRED_KEYS, AUTHOR_KEY_TYPES, f"{where}[author]")
    _check_keys(
        record["engagement"],
        ENGAGEMENT_REQUIRED_KEYS,
        ENGAGEMENT_KEY_TYPES,
        f"{where}[engagement]",
    )
    for index, obj in enumerate(record["mediaObjects"]):
        _check_keys(
            obj,
            MEDIA_OBJECT_REQUIRED_KEYS,
            MEDIA_OBJECT_KEY_TYPES,
            f"{where}[mediaObjects][{index}]",
        )
    for key in ("media", "links", "tags"):
        for index, value in enumerate(record[key]):
            if not isinstance(value, str):
                raise UpstreamContractError(
                    f"{where}[{key}][{index}]: expected str, got {type(value).__name__}"
                )


def validate_media_manifest(payload: Mapping[str, Any], where: str = "media-manifest.json") -> None:
    """Validate the whole media manifest, including every entry."""

    _check_keys(payload, MANIFEST_REQUIRED_KEYS, MANIFEST_KEY_TYPES, where)
    version = payload["schemaVersion"]
    if version not in MANIFEST_SCHEMA_VERSIONS:
        raise UpstreamContractError(
            f"{where}: unsupported schemaVersion {version}; "
            f"supported: {list(MANIFEST_SCHEMA_VERSIONS)}"
        )
    for index, entry in enumerate(payload["entries"]):
        _check_keys(
            entry, MANIFEST_ENTRY_KEY_TYPES, MANIFEST_ENTRY_KEY_TYPES, f"{where}[entries][{index}]"
        )


def validate_enriched_record(record: Mapping[str, Any], where: str = "list --json") -> None:
    """Validate one enriched record from `list --json` / `show --json`."""

    _check_keys(record, ENRICHED_REQUIRED_KEYS, ENRICHED_KEY_TYPES, where)
    quoted = record.get("quotedTweet")
    if quoted is not None and not isinstance(quoted, Mapping):
        raise UpstreamContractError(f"{where}: 'quotedTweet' must be an object or null")


def validate_meta(payload: Mapping[str, Any], where: str = "bookmarks-meta.json") -> None:
    _check_keys(payload, ("provider", "schemaVersion"), META_KEY_TYPES, where)


def validate_backfill_state(
    payload: Mapping[str, Any], where: str = "bookmarks-backfill-state.json"
) -> None:
    _check_keys(payload, BACKFILL_REQUIRED_KEYS, BACKFILL_KEY_TYPES, where)


def parse_twitter_datetime(value: str) -> datetime:
    """Parse the upstream `postedAt` format, e.g. `Sat Jun 20 12:56:42 +0000 2026`."""

    if not isinstance(value, str):
        raise UpstreamContractError(f"postedAt must be a string, got {type(value).__name__}")
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    except ValueError as exc:
        raise UpstreamContractError(f"unparseable postedAt value: {value!r}") from exc


def parse_iso_datetime(value: str) -> datetime:
    """Parse an upstream ISO-8601 UTC timestamp such as `2026-09-16T02:02:41.036Z`."""

    if not isinstance(value, str):
        raise UpstreamContractError(f"expected ISO-8601 string, got {type(value).__name__}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise UpstreamContractError(f"unparseable ISO-8601 value: {value!r}") from exc
