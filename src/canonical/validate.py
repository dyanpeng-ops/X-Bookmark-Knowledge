"""CanonicalBookmark 校验器（标准库实现，零第三方依赖）。

本模块把 `schema/bookmark.schema.json` 定义的约束落实为可执行的校验逻辑。
它不是通用 JSON Schema 引擎，只覆盖 CanonicalBookmark 契约用到的子集：
type / required / enum / const / format(date-time|uri) / pattern。

设计取舍（见 ARCHITECTURE.md §5.2 与 CHANGELOG Phase 2）：
- 项目红线「依赖最小化、优先标准库」，故不引入 `jsonschema`。
- 校验逻辑与 schema 字段一一对应，测试同时锁定 schema 与校验器，避免
  「schema 与实现两份校验」漂移。

校验规则与 `schema/bookmark.schema.json` 保持一致；两者任何一处变更须同步。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

__all__ = [
    "CanonicalValidationError",
    "REQUIRED_FIELDS",
    "MEDIA_TYPES",
    "CONTENT_HASH_PATTERN",
    "validate_bookmark",
    "is_iso8601",
    "is_uri",
]


class CanonicalValidationError(ValueError):
    """CanonicalBookmark 校验失败。message 指明具体字段与原因。"""


# 与 schema 的 required 数组一致（含 media / external_links，决策 A：永远存在、可空数组）。
REQUIRED_FIELDS: tuple[str, ...] = (
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

# mediaObject.type 的合法取值。
MEDIA_TYPES: tuple[str, ...] = ("photo", "video", "animated_gif")

# content_hash：SHA-256 十六进制，64 字符。
CONTENT_HASH_PATTERN: re.Pattern[str] = re.compile(r"^[0-9a-f]{64}$")

# source 固定为 "x"（决策 D5）。
_SOURCE_CONST = "x"

# quotedTweet / xArticle 的必填键。
_QUOTED_REQUIRED = ("tweet_id", "author_handle", "text")
_X_ARTICLE_REQUIRED = ("text",)


def is_iso8601(value: str) -> bool:
    """判断字符串是否为合法 ISO-8601 时间（接受 `Z` 与 `+00:00` 偏移）。"""
    if not isinstance(value, str):
        return False
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        return False


def is_uri(value: str) -> bool:
    """判断字符串是否为合法绝对 URI（含 scheme，如 http/https）。"""
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _require_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if value is None:
        raise CanonicalValidationError(f"missing required field '{key}'")
    if not isinstance(value, str):
        raise CanonicalValidationError(
            f"field '{key}' must be str, got {type(value).__name__}"
        )
    return value


def _require_nonempty_str(data: Mapping[str, Any], key: str) -> str:
    value = _require_str(data, key)
    if not value:
        raise CanonicalValidationError(f"field '{key}' must not be empty")
    return value


def _check_optional_str_or_null(data: Mapping[str, Any], key: str) -> None:
    if key not in data:
        return
    value = data[key]
    if value is not None and not isinstance(value, str):
        raise CanonicalValidationError(
            f"field '{key}' must be str or null, got {type(value).__name__}"
        )


def _check_media_objects(items: Sequence[Any]) -> None:
    for index, obj in enumerate(items):
        where = f"media[{index}]"
        if not isinstance(obj, Mapping):
            raise CanonicalValidationError(f"{where} must be an object")
        for req in ("type", "url"):
            if req not in obj:
                raise CanonicalValidationError(f"{where} missing required field '{req}'")
        mtype = obj["type"]
        if mtype not in MEDIA_TYPES:
            raise CanonicalValidationError(
                f"{where}.type must be one of {MEDIA_TYPES}, got {mtype!r}"
            )
        if not is_uri(obj["url"]):
            raise CanonicalValidationError(f"{where}.url is not a valid URI")
        for opt in ("expandedUrl",):
            if opt in obj and obj[opt] is not None and not is_uri(obj[opt]):
                raise CanonicalValidationError(f"{where}.{opt} is not a valid URI")
        for opt in ("width", "height"):
            if opt in obj and obj[opt] is not None:
                if isinstance(obj[opt], bool) or not isinstance(obj[opt], int):
                    raise CanonicalValidationError(
                        f"{where}.{opt} must be int or null"
                    )


def _check_quoted_tweet(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalValidationError("quoted_tweet must be an object or null")
    for req in _QUOTED_REQUIRED:
        if req not in value or not isinstance(value[req], str):
            raise CanonicalValidationError(f"quoted_tweet missing/ill-typed field '{req}'")


def _check_x_article(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalValidationError("x_article must be an object or null")
    if "text" not in value or not isinstance(value["text"], str):
        raise CanonicalValidationError("x_article missing required string field 'text'")


def validate_bookmark(data: Mapping[str, Any]) -> None:
    """校验一条 CanonicalBookmark，失败抛 `CanonicalValidationError`。

    未知字段会被拒绝（与 schema 的 `additionalProperties: false` 一致）。
    """

    if not isinstance(data, Mapping):
        raise CanonicalValidationError(f"expected an object, got {type(data).__name__}")

    allowed = {
        "tweet_id", "author", "author_id", "author_username", "created_at",
        "text", "url", "conversation_id", "source", "collector",
        "quoted_tweet", "reply_to", "thread", "media", "external_links",
        "x_article", "collected_at", "updated_at", "content_hash",
    }
    for key in data:
        if key not in allowed:
            raise CanonicalValidationError(f"unknown field '{key}'")

    # 必填字符串字段
    for key in REQUIRED_FIELDS:
        if key in ("media", "external_links"):
            continue
        _require_nonempty_str(data, key)

    # 固定值
    if data.get("source") != _SOURCE_CONST:
        raise CanonicalValidationError(
            f"field 'source' must equal {_SOURCE_CONST!r}, got {data.get('source')!r}"
        )

    # 时间格式
    for key in ("created_at", "collected_at", "updated_at"):
        if key not in data or data[key] is None:
            if key == "created_at":
                raise CanonicalValidationError("field 'created_at' is required")
            continue
        if not is_iso8601(data[key]):
            raise CanonicalValidationError(f"field '{key}' is not a valid ISO-8601 datetime")

    # URL
    if not is_uri(data["url"]):
        raise CanonicalValidationError("field 'url' is not a valid URI")

    # content_hash 格式
    if not CONTENT_HASH_PATTERN.match(data["content_hash"]):
        raise CanonicalValidationError(
            "field 'content_hash' must be a 64-char lowercase hex string"
        )

    # 可选字符串/空
    for key in ("conversation_id", "reply_to"):
        _check_optional_str_or_null(data, key)

    # media：必填数组，元素为 mediaObject
    media = data.get("media")
    if not isinstance(media, list):
        raise CanonicalValidationError("field 'media' must be an array")
    _check_media_objects(media)

    # external_links：必填数组，元素为 URI
    links = data.get("external_links")
    if not isinstance(links, list):
        raise CanonicalValidationError("field 'external_links' must be an array")
    for index, url in enumerate(links):
        if not is_uri(url):
            raise CanonicalValidationError(f"external_links[{index}] is not a valid URI")

    # thread：数组或 null
    if "thread" in data and data["thread"] is not None:
        thread = data["thread"]
        if not isinstance(thread, list) or not all(isinstance(x, str) for x in thread):
            raise CanonicalValidationError("field 'thread' must be an array of str or null")

    # quoted_tweet / x_article：对象或 null
    if data.get("quoted_tweet") is not None:
        _check_quoted_tweet(data["quoted_tweet"])
    if data.get("x_article") is not None:
        _check_x_article(data["x_article"])
