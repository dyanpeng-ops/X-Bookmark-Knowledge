"""``FieldTheoryNormalizer`` —— ``RawCollectorData → CanonicalBookmark``（任务书 §9）。

权威字段定义：``schema/bookmark.schema.json``（Phase 2 冻结，Phase 3 不得修改）。
校验器：``src/canonical/validate.py``。

本模块的硬边界
--------------
* **不读上游**：本模块自身不 import 上游适配器（``fieldtheory_adapter``），
  不执行任何 CLI，不做网络请求（运行期行为已由 ``tests/test_normalizer.py`` 用
  「屏蔽 subprocess / urlopen 后仍能跑通」证明）。所有上游读取都已在 Collector
  完成（任务书 §24）。
  已知残留：``from ..collector.base`` / ``..collector.contract`` 会先触发
  ``src.collector.__init__``，因而 **import 期**会连带加载 Phase 5 的适配器模块
  （含 ``subprocess``）。这只是模块加载，不产生任何上游调用；彻底解耦需拆包
  （属架构决策，见 ``docs/phase3-preflight-review.md`` §10.6）。
* **不写盘**：不写 SQLite / Markdown / Git / ``data/``（任务书 §25）。
* Canonical 层（``src/canonical/``）不得反向依赖本模块。

本模块的字段映射与对真实数据的核对结论记录于
``docs/phase3-preflight-review.md``「决策与修正记录」。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from ..canonical.validate import MEDIA_TYPES, is_uri, validate_bookmark
from ..collector.base import UpstreamContractError
from ..collector.contract import parse_twitter_datetime
from ..collector.raw_data import RawBookmarkItem, RawCollectorData
from .errors import NormalizationError

__all__ = [
    "FieldTheoryNormalizer",
    "compute_content_hash",
    "is_article_link",
    "ARTICLE_LINK_HOSTS",
]

# Canonical 固定值：数据来源是 X；fieldtheory 只是 Collector（任务书 §9.4）。
SOURCE = "x"
COLLECTOR_NAME = "fieldtheory"

# `x.com/i/article/<id>` 是 X Article 的引用，不是外链（预检修正 N1）。
# 过滤 scheme 无关：真实数据里同时出现 `http://` 与 `https://`。
ARTICLE_LINK_HOSTS = frozenset(
    {
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
    }
)
_ARTICLE_PATH_PREFIX = "/i/article/"

# Canonical 输出键的固定顺序（19 键 = 12 必填 + 7 可选，见 schema）。
_CANONICAL_KEYS: tuple[str, ...] = (
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


def is_article_link(url: str) -> bool:
    """判断 URL 是否是 X Article 引用（``x.com/i/article/...``）。"""

    if not isinstance(url, str) or not url:
        return False
    parsed = urlparse(url)
    if not parsed.netloc:
        return False
    host = parsed.netloc.rsplit("@", 1)[-1].split(":", 1)[0].lower()
    return host in ARTICLE_LINK_HOSTS and parsed.path.startswith(_ARTICLE_PATH_PREFIX)


def compute_content_hash(bookmark: Mapping[str, Any]) -> str:
    """按 ``ARCHITECTURE.md`` §5.4 计算内容哈希（SHA-256 十六进制）。

    覆盖字段（9 项）：``tweet_id`` + ``text`` + ``url`` + ``author_id`` +
    ``created_at`` + ``media[]``（有序）+ ``external_links[]``（有序）+
    ``quoted_tweet``（若存在）+ ``x_article.text``（若存在）。

    不覆盖：``collected_at`` / ``updated_at`` / ``collector`` / ``source``
    （元数据）与 ``engagement``（互动数流动）。这样重采集不会因时间戳变化而
    误判「内容已变」，跨设备去重才成立。
    """

    x_article = bookmark.get("x_article")
    material = {
        "tweet_id": bookmark["tweet_id"],
        "text": bookmark["text"],
        "url": bookmark["url"],
        "author_id": bookmark["author_id"],
        "created_at": bookmark["created_at"],
        "media": [dict(item) for item in bookmark.get("media") or ()],
        "external_links": list(bookmark.get("external_links") or ()),
        "quoted_tweet": bookmark.get("quoted_tweet"),
        "x_article": {"text": x_article["text"]} if isinstance(x_article, Mapping) else None,
    }
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _require_nonempty(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise NormalizationError(f"{where} must be a non-empty str, got {value!r}")
    return value


def _optional_str(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizationError(f"{where} must be a str or null, got {type(value).__name__}")
    return value or None


def _format_utc(parsed: datetime) -> str:
    """把 aware/naive datetime 规范化为 Canonical 的 UTC ISO-8601（``...Z``）。"""

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if parsed.microsecond:
        return f"{parsed.strftime('%Y-%m-%dT%H:%M:%S')}.{parsed.microsecond // 1000:03d}Z"
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_utc(value: str, where: str) -> str:
    """解析并规范化上游 ISO-8601 时间戳。

    确定性：同一输入永远得到同一输出（不使用 ``now()``），
    Test L（幂等）与跨设备 ``content_hash`` 去重都依赖这一点。
    """

    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"{where} is not a parseable ISO-8601 datetime: {value!r}") from exc
    return _format_utc(parsed)


def _as_sequence(value: Any, where: str) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise NormalizationError(f"{where} must be an array, got {type(value).__name__}")
    return value


class FieldTheoryNormalizer:
    """把 Field Theory 的 ``RawCollectorData`` 映射为 CanonicalBookmark dict。

    输出是 ``dict``（而非 dataclass），直接对接 ``canonical.validate``（决策 1）。
    """

    collector_name = COLLECTOR_NAME
    source = SOURCE

    # ── 公开接口 ────────────────────────────────────────────────────────────

    def normalize(self, data: RawCollectorData) -> tuple[dict[str, Any], ...]:
        """映射全部条目（不做 Schema 校验）。"""

        self._check_collector(data)
        return tuple(self.normalize_item(item) for item in data.items)

    def normalize_and_validate(self, data: RawCollectorData) -> tuple[dict[str, Any], ...]:
        """映射并逐条通过 ``validate_bookmark``（任务书 §15 的完整链路）。

        任一条不合格即抛 ``CanonicalValidationError``，绝不落盘。
        """

        bookmarks = self.normalize(data)
        for bookmark in bookmarks:
            validate_bookmark(bookmark)
        return bookmarks

    def normalize_item(self, item: RawBookmarkItem) -> dict[str, Any]:
        """映射单条 ``RawBookmarkItem``；字段不全/类型不符时抛 ``NormalizationError``。"""

        if not isinstance(item, RawBookmarkItem):
            raise NormalizationError(
                f"expected RawBookmarkItem, got {type(item).__name__}"
            )
        payload = item.payload
        if not isinstance(payload, Mapping):
            raise NormalizationError("RawBookmarkItem.payload must be a mapping")

        tweet_id = _require_nonempty(item.tweet_id, "tweet_id")
        payload_id = payload.get("tweetId")
        if payload_id is None:
            raise NormalizationError("payload is missing 'tweetId'")
        if str(payload_id) != tweet_id:
            raise NormalizationError(
                f"tweet_id mismatch: item={tweet_id!r} payload={str(payload_id)!r}"
            )

        bookmark: dict[str, Any] = {
            "tweet_id": tweet_id,
            "author": self._author_name(payload),
            "author_id": self._author_id(payload),
            "author_username": self._author_username(payload),
            "created_at": self._created_at(payload),
            "text": _require_nonempty(payload.get("text"), "payload['text']"),
            "url": self._url(payload),
            "conversation_id": _optional_str(
                payload.get("conversationId"), "payload['conversationId']"
            ),
            "source": self.source,
            "collector": self.collector_name,
            "quoted_tweet": self._quoted_tweet(item.enrichment),
            # FT 数据不携带 reply_to / thread；显式写 null = 已记录的 Schema gap
            # （Schema 中两者可空，Phase 3 不为其扩张数据源）。
            "reply_to": None,
            "thread": None,
            "media": self._media(payload),
            "external_links": self._external_links(payload),
            "x_article": self._x_article(item.enrichment),
            "collected_at": self._timestamp(payload, "payload['syncedAt']"),
            "updated_at": self._timestamp(payload, "payload['syncedAt']"),
        }
        bookmark["content_hash"] = compute_content_hash(bookmark)
        # 固定键顺序（便于 diff / 幂等断言）。
        return {key: bookmark[key] for key in _CANONICAL_KEYS}

    # ── 内部：入口校验 ──────────────────────────────────────────────────────

    def _check_collector(self, data: RawCollectorData) -> None:
        if not isinstance(data, RawCollectorData):
            raise NormalizationError(
                f"expected RawCollectorData, got {type(data).__name__}"
            )
        if data.collector != self.collector_name:
            raise NormalizationError(
                f"{type(self).__name__} cannot normalize collector {data.collector!r}"
            )

    # ── 内部：author ────────────────────────────────────────────────────────

    @staticmethod
    def _author_block(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        block = payload.get("author")
        if block is None:
            return {}
        if not isinstance(block, Mapping):
            raise NormalizationError(
                f"payload['author'] must be an object, got {type(block).__name__}"
            )
        return block

    def _author_name(self, payload: Mapping[str, Any]) -> str:
        block = self._author_block(payload)
        for candidate in (block.get("name"), payload.get("authorName")):
            if isinstance(candidate, str) and candidate:
                return candidate
        raise NormalizationError("author display name is missing (author.name / authorName)")

    def _author_id(self, payload: Mapping[str, Any]) -> str:
        block = self._author_block(payload)
        return _require_nonempty(block.get("id"), "payload['author']['id']")

    def _author_username(self, payload: Mapping[str, Any]) -> str:
        block = self._author_block(payload)
        for candidate in (block.get("handle"), payload.get("authorHandle")):
            if isinstance(candidate, str) and candidate:
                return candidate
        raise NormalizationError("author handle is missing (author.handle / authorHandle)")

    # ── 内部：基础字段 ──────────────────────────────────────────────────────

    @staticmethod
    def _created_at(payload: Mapping[str, Any]) -> str:
        raw = payload.get("postedAt")
        if not isinstance(raw, str) or not raw:
            raise NormalizationError("payload['postedAt'] must be a non-empty str")
        try:
            parsed = parse_twitter_datetime(raw)
        except UpstreamContractError as exc:
            raise NormalizationError(f"unparseable payload['postedAt']: {raw!r}") from exc
        return _format_utc(parsed)

    @staticmethod
    def _url(payload: Mapping[str, Any]) -> str:
        url = payload.get("url")
        if not isinstance(url, str) or not url:
            raise NormalizationError("payload['url'] must be a non-empty str")
        if not is_uri(url):
            raise NormalizationError(f"payload['url'] is not a valid URI: {url!r}")
        return url

    @staticmethod
    def _timestamp(payload: Mapping[str, Any], where: str) -> str | None:
        raw = payload.get("syncedAt")
        if raw is None:
            return None
        if not isinstance(raw, str) or not raw:
            raise NormalizationError(f"{where} must be a non-empty str or null")
        return _iso_utc(raw, where)

    # ── 内部：media / external_links ────────────────────────────────────────

    @staticmethod
    def _media(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        """``mediaObjects`` → Canonical ``mediaObject``（只保留 Schema 允许的 5 键）。

        上游 ``media``（字符串数组）是 ``mediaObjects`` 的子集，忽略以避免重复。
        """

        raw = _as_sequence(payload.get("mediaObjects"), "payload['mediaObjects']")
        media: list[dict[str, Any]] = []
        for index, obj in enumerate(raw):
            where = f"payload['mediaObjects'][{index}]"
            if not isinstance(obj, Mapping):
                raise NormalizationError(f"{where} must be an object")
            mtype = obj.get("type")
            if mtype not in MEDIA_TYPES:
                raise NormalizationError(
                    f"{where}['type'] must be one of {MEDIA_TYPES}, got {mtype!r}"
                )
            url = obj.get("url")
            if not is_uri(url):
                raise NormalizationError(f"{where}['url'] is not a valid URI: {url!r}")
            entry: dict[str, Any] = {
                "type": mtype,
                "url": url,
                "expandedUrl": None,
                "width": None,
                "height": None,
            }
            expanded = obj.get("expandedUrl")
            if expanded is not None:
                if not is_uri(expanded):
                    raise NormalizationError(
                        f"{where}['expandedUrl'] is not a valid URI: {expanded!r}"
                    )
                entry["expandedUrl"] = expanded
            for key in ("width", "height"):
                value = obj.get(key)
                if value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, int):
                    raise NormalizationError(
                        f"{where}[{key!r}] must be int or null, got {type(value).__name__}"
                    )
                entry[key] = value
            media.append(entry)
        return media

    @staticmethod
    def _external_links(payload: Mapping[str, Any]) -> list[str]:
        """``links`` → ``external_links``：过滤 Article 引用、保序去重。

        真实数据核对结果（预检 N1/N2）：
        * 5 条中 4 条的 ``links`` 只有 ``x.com/i/article/...``（一条 ``http://``），
          过滤后为空数组——这是正确语义，Article 正文走 ``x_article``；
        * 真实数据存在完全重复的外链，故做保序去重；
        * 非绝对 URI 无法进入 Canonical 契约（``format: uri``），丢弃并记录为
          gap（见 Phase 3 Review）。
        """

        raw = _as_sequence(payload.get("links"), "payload['links']")
        links: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                raise NormalizationError(
                    f"payload['links'] entries must be str, got {type(item).__name__}"
                )
            value = item.strip()
            if not value or value in seen:
                continue
            if is_article_link(value) or not is_uri(value):
                continue
            seen.add(value)
            links.append(value)
        return links

    # ── 内部：富化字段 ──────────────────────────────────────────────────────

    @staticmethod
    def _enrichment(enrichment: Mapping[str, Any] | None) -> Mapping[str, Any]:
        if enrichment is None:
            return {}
        if not isinstance(enrichment, Mapping):
            raise NormalizationError(
                f"enrichment must be a mapping or None, got {type(enrichment).__name__}"
            )
        return enrichment

    def _x_article(self, enrichment: Mapping[str, Any] | None) -> dict[str, Any] | None:
        """Article → ``xArticle``（``text`` 必填；仅 ``articleText`` 存在时映射）。"""

        block = self._enrichment(enrichment)
        text = block.get("articleText")
        if text is None or (isinstance(text, str) and not text.strip()):
            # 有标题无正文时无法表达（schema 要求 xArticle.text 必填）→ 记 gap，不映射。
            return None
        if not isinstance(text, str):
            raise NormalizationError(
                f"enrichment['articleText'] must be a str or null, got {type(text).__name__}"
            )
        title = _optional_str(block.get("articleTitle"), "enrichment['articleTitle']")
        site = _optional_str(block.get("articleSite"), "enrichment['articleSite']")
        return {"title": title, "text": text, "site": site}

    def _quoted_tweet(self, enrichment: Mapping[str, Any] | None) -> dict[str, Any] | None:
        """quotedTweet → ``quotedTweet``（``tweetId``/``authorHandle``/``text`` 必填）。

        ⚠️ 形状**待验证**：现有真实样本（5 条）与 fixtures 中 ``quotedTweet`` 均为
        ``null``，无实测非空样本。此处按字段名直译并严格校验；若上游实际形状不同，
        报 ``NormalizationError`` 而不是静默丢数据（记录于 Phase 3 Review）。
        """

        block = self._enrichment(enrichment)
        quoted = block.get("quotedTweet")
        if quoted is None:
            return None
        if not isinstance(quoted, Mapping):
            raise NormalizationError(
                f"enrichment['quotedTweet'] must be an object or null, got {type(quoted).__name__}"
            )
        tweet_id = quoted.get("tweetId") or quoted.get("id")
        handle = quoted.get("authorHandle") or quoted.get("authorUsername")
        text = quoted.get("text")
        url = quoted.get("url") or quoted.get("expandedUrl")
        if tweet_id is None:
            raise NormalizationError(
                "enrichment['quotedTweet'] is missing 'tweetId'"
            )
        result = {
            "tweet_id": _require_nonempty(
                str(tweet_id), "enrichment['quotedTweet']['tweetId']"
            ),
            "author_handle": _require_nonempty(
                handle, "enrichment['quotedTweet']['authorHandle']"
            ),
            "text": _require_nonempty(text, "enrichment['quotedTweet']['text']"),
            "url": url if is_uri(url) else None,
        }
        return result
