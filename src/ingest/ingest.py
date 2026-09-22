"""入库层（Phase 6）：把上游记录写入本项目唯一的权威状态库。

职责边界
--------
* 只做"读取 → 归一化 → 幂等写入"，**不做网络抓取**（网络在 `src/external/`，Phase 9）。
* 逐条 try/except：**单条失败绝不让整批失败**，失败写入 `error_message` 并累加 `attempts`。
* 幂等：同一份上游数据重复入库，第二次的 `new` 必须为 0，且不产生重复行、不重置状态。
* `media.local_path` 只在**首次插入**时写入：该字段在 Phase 8 之后由媒体层接管
  （存放知识库内的本地路径），重复入库不得用上游旧缓存路径覆盖它。
* 同理 `external_links.fetch_status` 也只在**首次插入**时写入 `PENDING`：该字段在
  Phase 9 之后由外链层接管（`FETCHED` / `FAILED` / `SKIPPED`），重复入库不得把它重置。

原始留档
--------
每条书签的完整上游 JSON 会写入 `data/raw/{tweet_id}.json`，内容**不含时间戳**，
因此可以用"内容是否变化"判断是否需要重写（AGENTS.md 第 5 节的幂等要求）。
时间信息保存在 SQLite（`first_synced_at` / `last_synced_at`）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from src.collector.base import EnrichedBookmark, MediaEntry, UpstreamBookmark
from src.collector.contract import parse_twitter_datetime
from src.database import (
    BookmarkRecord,
    BookmarkRepository,
    BookmarkStatus,
    ExternalLinkRecord,
    LinkFetchStatus,
    MediaDownloadStatus,
    MediaRecord,
    utc_now_iso,
)

__all__ = ["RAW_ARCHIVE_SCHEMA_VERSION", "IngestStats", "Ingestor", "media_key_for", "domain_of"]

logger = logging.getLogger(__name__)

RAW_ARCHIVE_SCHEMA_VERSION = 1

MANIFEST_STATUS_TO_MEDIA_STATUS: Mapping[str, MediaDownloadStatus] = {
    "downloaded": MediaDownloadStatus.DOWNLOADED,
    # UNVERIFIED: only "downloaded" was observed in real manifests; the two
    # mappings below are inferred from the upstream counter names.
    "skipped_too_large": MediaDownloadStatus.SKIPPED,
    "failed": MediaDownloadStatus.FAILED,
}


def media_key_for(source_url: str) -> str:
    """稳定媒体键：同一 URL 永远得到同一 media_key（sha1 前 16 位）。"""

    digest = hashlib.sha1(str(source_url).encode("utf-8")).hexdigest()
    return digest[:16]


def domain_of(url: str) -> str:
    """提取主机名（小写、无端口）；解析失败返回空串。"""

    try:
        return urlsplit(str(url)).netloc.lower()
    except ValueError:
        return ""


def _media_type_of(entry: MediaEntry, media_objects: Sequence[Mapping[str, Any]]) -> str:
    """判断媒体类型：作者头像 / 推文媒体对象类型 / 由 content-type 推断。"""

    if "/profile_images/" in entry.source_url:
        return "profile_image"
    for obj in media_objects:
        if str(obj.get("url") or "") == entry.source_url:
            kind = str(obj.get("type") or "").strip()
            if kind:
                return kind
    content_type = (entry.content_type or "").lower()
    if content_type.startswith("image/"):
        return "photo"
    if content_type.startswith("video/"):
        return "video"
    return "unknown"


def _media_status_of(status: str) -> MediaDownloadStatus:
    return MANIFEST_STATUS_TO_MEDIA_STATUS.get(
        str(status).strip().lower(), MediaDownloadStatus.PENDING
    )


@dataclass(frozen=True)
class IngestStats:
    """一次入库的统计结果（同步报告直接使用）。"""

    fetched: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    collected_transitions: int = 0
    raw_written: int = 0
    raw_skipped: int = 0
    media_new: int = 0
    media_updated: int = 0
    media_unchanged: int = 0
    links_new: int = 0
    links_updated: int = 0
    links_unchanged: int = 0
    enriched: int = 0
    errors: tuple[tuple[str, str], ...] = ()
    status_counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.failed == 0


class Ingestor:
    """把上游记录写入 `bookmarks` / `media` / `external_links`。"""

    def __init__(
        self,
        repository: BookmarkRepository,
        raw_dir: str | Path,
        *,
        clock: Callable[[Any], str] = utc_now_iso,
    ) -> None:
        self._repository = repository
        self._raw_dir = Path(raw_dir)
        self._clock = clock

    # ── 对外入口 ─────────────────────────────────────────────────────────────

    def run(
        self,
        bookmarks: Sequence[UpstreamBookmark],
        *,
        enrichment: Mapping[str, EnrichedBookmark] | None = None,
        media: Iterable[MediaEntry] = (),
        now: Any = None,
    ) -> IngestStats:
        """逐条入库；任何单条异常都会被记录，不影响其余记录。"""

        enriched = dict(enrichment or {})
        media_by_tweet: dict[str, list[MediaEntry]] = {}
        for entry in media:
            media_by_tweet.setdefault(entry.tweet_id, []).append(entry)

        counters: dict[str, int] = {
            "fetched": len(bookmarks),
            "new": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
            "collected_transitions": 0,
            "raw_written": 0,
            "raw_skipped": 0,
            "media_new": 0,
            "media_updated": 0,
            "media_unchanged": 0,
            "links_new": 0,
            "links_updated": 0,
            "links_unchanged": 0,
            "enriched": 0,
        }
        errors: list[tuple[str, str]] = []

        for bookmark in bookmarks:
            try:
                self._ingest_one(
                    bookmark,
                    enrichment=enriched.get(bookmark.tweet_id),
                    media=media_by_tweet.get(bookmark.tweet_id, ()),
                    counters=counters,
                    now=now,
                )
            except Exception as exc:  # noqa: BLE001 - 单条失败必须被隔离
                message = f"{type(exc).__name__}: {exc}"
                logger.error("ingest failed for %s: %s", bookmark.tweet_id, message)
                errors.append((bookmark.tweet_id, message))
                counters["failed"] += 1
                self._record_failure(bookmark.tweet_id, message, now=now)

        return IngestStats(
            **counters,
            errors=tuple(errors),
            status_counts=self._repository.count_by_status(),
        )

    # ── 单条处理 ─────────────────────────────────────────────────────────────

    def _ingest_one(
        self,
        bookmark: UpstreamBookmark,
        *,
        enrichment: EnrichedBookmark | None,
        media: Sequence[MediaEntry],
        counters: dict[str, int],
        now: Any,
    ) -> None:
        existing = self._repository.get_bookmark(bookmark.tweet_id)

        raw_path, raw_written = self._write_raw_archive(bookmark, enrichment)
        counters["raw_written" if raw_written else "raw_skipped"] += 1
        if enrichment is not None:
            counters["enriched"] += 1

        record = BookmarkRecord(
            tweet_id=bookmark.tweet_id,
            author_id=str(bookmark.author.get("id") or "") or None,
            username=bookmark.author_handle or None,
            author_name=bookmark.author_name or None,
            tweet_text=bookmark.text or None,
            created_at=utc_now_iso(parse_twitter_datetime(bookmark.posted_at_raw)),
            tweet_url=bookmark.url or None,
            conversation_id=bookmark.conversation_id or None,
            raw_json_path=str(raw_path),
            status=BookmarkStatus.COLLECTED.value,
        )
        result = self._repository.upsert_bookmark(record, now=now)
        if result.created:
            counters["new"] += 1
        elif result.changed:
            counters["updated"] += 1
        else:
            counters["unchanged"] += 1

        # 新建时已直接落 COLLECTED；已存在但仍是 NEW/FAILED 的记录推进状态，
        # 顺带清空历史错误（set_status 的 error_message=None 语义）。
        if existing is not None and existing.status in (
            BookmarkStatus.NEW.value,
            BookmarkStatus.FAILED.value,
        ):
            self._repository.set_status(bookmark.tweet_id, BookmarkStatus.COLLECTED)
            counters["collected_transitions"] += 1

        self._ingest_media(bookmark, media, counters)
        self._ingest_links(bookmark, counters, now=now)

    def _ingest_media(
        self, bookmark: UpstreamBookmark, media: Sequence[MediaEntry], counters: dict[str, int]
    ) -> None:
        for entry in media:
            media_key = media_key_for(entry.source_url)
            # `local_path` 是"该媒体字节在本项目的落点"，由 Phase 8 本地化后接管：
            # 已存在的行不再被上游路径覆盖，否则每次 sync 都会把知识库本地路径改回旧缓存路径。
            existing = self._repository.get_media(bookmark.tweet_id, media_key)
            record = MediaRecord(
                tweet_id=bookmark.tweet_id,
                media_key=media_key,
                media_type=_media_type_of(entry, bookmark.media_objects),
                source_url=entry.source_url,
                local_path=None if existing is not None else (entry.local_path or None),
                download_status=_media_status_of(entry.status).value,
            )
            result = self._repository.upsert_media(record)
            if result.created:
                counters["media_new"] += 1
            elif result.changed:
                counters["media_updated"] += 1
            else:
                counters["media_unchanged"] += 1

    def _ingest_links(
        self, bookmark: UpstreamBookmark, counters: dict[str, int], *, now: Any
    ) -> None:
        seen: set[str] = set()
        for url in bookmark.links:
            if not url or not str(url).strip():
                continue  # 空白 URL 会让 upsert 抛错，必须在这里挡掉
            if url in seen:
                continue  # 上游 links 会重复（实测 https://cobalt.tools 出现两次）
            seen.add(url)
            record = ExternalLinkRecord(
                tweet_id=bookmark.tweet_id,
                url=url,
                domain=domain_of(url) or None,
                # 与 media.local_path 同一规则（Phase 8 教训）：fetch_status 只在**首次插入**时写入。
                # 否则每次 sync 都会把 Phase 9 抓取好的 FETCHED/FAILED 重置回 PENDING，
                # 使外链抓取结果每轮同步都倒退（回归测试见 tests/test_ingest.py）。
                fetch_status=(
                    None
                    if self._repository.get_external_link(bookmark.tweet_id, url) is not None
                    else LinkFetchStatus.PENDING.value
                ),
            )
            result = self._repository.upsert_external_link(record, now=now)
            if result.created:
                counters["links_new"] += 1
            elif result.changed:
                counters["links_updated"] += 1
            else:
                counters["links_unchanged"] += 1

    # ── 原始留档与失败记录 ───────────────────────────────────────────────────

    def _write_raw_archive(
        self, bookmark: UpstreamBookmark, enrichment: EnrichedBookmark | None
    ) -> tuple[Path, bool]:
        """写入（内容未变则跳过）逐条原始 JSON，返回 (路径, 是否真的写了)。"""

        payload = {
            "schema_version": RAW_ARCHIVE_SCHEMA_VERSION,
            "tweet_id": bookmark.tweet_id,
            "source": "fieldtheory",
            "upstream": dict(bookmark.raw),
            "enrichment": dict(enrichment.raw) if enrichment is not None else None,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        path = self._raw_dir / f"{bookmark.tweet_id}.json"
        if path.is_file():
            try:
                if path.read_text(encoding="utf-8") == text:
                    return path, False
            except OSError:  # 读失败按"需要重写"处理，不阻断入库
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path, True

    def _record_failure(self, tweet_id: str, message: str, *, now: Any) -> None:
        """把失败写进状态库；即使该书签此前不存在也要留下痕迹。"""

        try:
            if self._repository.get_bookmark(tweet_id) is None:
                self._repository.upsert_bookmark(
                    BookmarkRecord(tweet_id=tweet_id, status=BookmarkStatus.FAILED.value),
                    now=now,
                )
            self._repository.record_error(
                tweet_id, message, status=BookmarkStatus.FAILED, count_attempt=True
            )
        except Exception as exc:  # noqa: BLE001 - 记录失败本身也不能抛出去
            logger.error("could not record ingest failure for %s: %s", tweet_id, exc)

