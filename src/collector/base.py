"""Collector contracts: error types, result types and the collector protocol.

This module is dependency-free (standard library only) so that both the
upstream contract validators and the fieldtheory adapter can build on it.

Dependency direction: collector.base  <-  collector.contract  <-  collector.fieldtheory_adapter
                     collector.raw_data  <-  collector.base   <-  collector.fieldtheory
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .raw_data import RawCollectorData

__all__ = [
    "CollectorError",
    "UpstreamUnavailableError",
    "UpstreamContractError",
    "UpstreamAuthError",
    "UpstreamTimeoutError",
    "UpstreamExecutionError",
    "SyncRunResult",
    "UpstreamArtifacts",
    "MediaEntry",
    "MediaManifest",
    "UpstreamBookmark",
    "EnrichedBookmark",
    "RawCollectorData",
    "Collector",
]


class CollectorError(RuntimeError):
    """Base class for every collector failure."""


class UpstreamUnavailableError(CollectorError):
    """The upstream executable or its data directory is not usable."""


class UpstreamContractError(CollectorError):
    """Upstream data does not match the frozen field contract."""


class UpstreamAuthError(CollectorError):
    """The upstream could not use a browser session / credentials."""


class UpstreamTimeoutError(CollectorError):
    """An upstream command exceeded its allotted wall-clock budget."""


class UpstreamExecutionError(CollectorError):
    """An upstream command failed for an unclassified reason."""


@dataclass(frozen=True)
class SyncRunResult:
    """Outcome of one `sync` invocation."""

    command: tuple[str, ...]
    returncode: int
    duration_seconds: float
    attempts: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass(frozen=True)
class UpstreamArtifacts:
    """Presence and freshness of the upstream data files."""

    data_dir: str
    jsonl_path: str
    jsonl_exists: bool
    jsonl_bytes: int
    jsonl_modified_at: datetime | None
    manifest_path: str
    manifest_exists: bool
    database_path: str
    database_exists: bool
    record_count: int

    @property
    def ready(self) -> bool:
        return self.jsonl_exists and self.record_count > 0


@dataclass(frozen=True)
class MediaEntry:
    """One media-manifest entry (upstream `entries[]`)."""

    bookmark_id: str
    tweet_id: str
    tweet_url: str
    author_handle: str | None
    author_name: str | None
    source_url: str
    local_path: str
    content_type: str | None
    size_bytes: int | None
    status: str
    fetched_at: str | None


@dataclass(frozen=True)
class MediaManifest:
    """Parsed `media-manifest.json`."""

    schema_version: int
    generated_at: str | None
    limit: int | None
    max_bytes: int | None
    processed: int
    downloaded: int
    skipped_too_large: int
    failed: int
    entries: tuple[MediaEntry, ...]


@dataclass(frozen=True)
class UpstreamBookmark:
    """One record of the upstream JSONL cache, normalised to snake_case.

    `raw` keeps the untouched upstream object so that later phases can read
    fields this adapter does not model yet.
    """

    tweet_id: str
    url: str
    text: str
    author_handle: str
    author_name: str
    author_profile_image_url: str
    posted_at_raw: str
    bookmarked_at_raw: str | None
    synced_at: str | None
    conversation_id: str | None
    language: str | None
    possibly_sensitive: bool | None
    media_urls: tuple[str, ...]
    media_objects: tuple[Mapping[str, Any], ...]
    links: tuple[str, ...]
    tags: tuple[str, ...]
    engagement: Mapping[str, int]
    author: Mapping[str, Any]
    ingested_via: str | None
    sort_index: str | None
    text_expanded_at: str | None
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)


@dataclass(frozen=True)
class EnrichedBookmark:
    """One record of `fieldtheory list --json` / `fieldtheory show --json`.

    The upstream CLI exposes enrichment (article body, categories, folders,
    quoted tweet, view counts) only through these commands, never through the
    JSONL cache.
    """

    tweet_id: str
    url: str
    text: str
    author_handle: str
    article_title: str | None
    article_text: str | None
    article_site: str | None
    enriched_at: str | None
    categories: tuple[str, ...]
    primary_category: str | None
    domains: tuple[str, ...]
    primary_domain: str | None
    github_urls: tuple[str, ...]
    view_count: int | None
    media_count: int | None
    link_count: int | None
    folder_ids: tuple[str, ...]
    folder_names: tuple[str, ...]
    quoted_status_id: str | None
    quoted_tweet: Mapping[str, Any] | None
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)


@runtime_checkable
class Collector(Protocol):
    """Minimal surface every collector adapter must provide."""

    def check_ready(self) -> UpstreamArtifacts:
        """Report whether upstream data exists and is readable."""

    def sync(self, **options: Any) -> SyncRunResult:
        """Run one collection pass and return its outcome."""

    def read_bookmarks(self) -> Sequence[UpstreamBookmark]:
        """Read every bookmark currently cached upstream."""

    def collect(self) -> RawCollectorData:
        """Read upstream data into the neutral ``RawCollectorData`` contract.

        Phase 3 (task book §22) reuses this protocol instead of defining a second
        collector interface. Implementations must be read-only with respect to the
        upstream data directory and must not write SQLite/Markdown/Knowledge/Git.
        """
