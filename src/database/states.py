"""书签状态机与相关状态词表（Phase 4 定义，执行计划 §15）。

状态流转（happy path）::

    NEW → COLLECTED → PROCESSED → ENRICHED → COMPLETED

失败：任意非终态可进入 ``FAILED``；``FAILED`` 可重入流水线（对应 ``retry`` 命令）。
``COMPLETED`` 为终态。同状态写入视为无操作（幂等）。

本模块不依赖其他项目模块，供 schema（生成 CHECK 约束）与 repository 共同使用。
"""

from __future__ import annotations

from enum import Enum


class InvalidStateTransition(ValueError):
    """当状态流转违反状态机定义时抛出。"""


class BookmarkStatus(str, Enum):
    """bookmarks.status 的取值。"""

    NEW = "NEW"
    COLLECTED = "COLLECTED"
    PROCESSED = "PROCESSED"
    ENRICHED = "ENRICHED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MediaDownloadStatus(str, Enum):
    """media.download_status 的取值。"""

    PENDING = "PENDING"
    DOWNLOADED = "DOWNLOADED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class LinkFetchStatus(str, Enum):
    """external_links.fetch_status 的取值。"""

    PENDING = "PENDING"
    FETCHED = "FETCHED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


ALL_STATUS_VALUES: tuple[str, ...] = tuple(status.value for status in BookmarkStatus)
ALL_MEDIA_STATUS_VALUES: tuple[str, ...] = tuple(status.value for status in MediaDownloadStatus)
ALL_LINK_STATUS_VALUES: tuple[str, ...] = tuple(status.value for status in LinkFetchStatus)

_TRANSITIONS: dict[BookmarkStatus, frozenset[BookmarkStatus]] = {
    BookmarkStatus.NEW: frozenset({BookmarkStatus.COLLECTED, BookmarkStatus.FAILED}),
    BookmarkStatus.COLLECTED: frozenset({BookmarkStatus.PROCESSED, BookmarkStatus.FAILED}),
    BookmarkStatus.PROCESSED: frozenset({BookmarkStatus.ENRICHED, BookmarkStatus.FAILED}),
    BookmarkStatus.ENRICHED: frozenset({BookmarkStatus.COMPLETED, BookmarkStatus.FAILED}),
    BookmarkStatus.COMPLETED: frozenset(),
    BookmarkStatus.FAILED: frozenset(
        {
            BookmarkStatus.NEW,
            BookmarkStatus.COLLECTED,
            BookmarkStatus.PROCESSED,
            BookmarkStatus.ENRICHED,
        }
    ),
}


def parse_status(value: str | BookmarkStatus) -> BookmarkStatus:
    """把字符串或枚举规范化为 ``BookmarkStatus``；非法值抛 ValueError。"""
    if isinstance(value, BookmarkStatus):
        return value
    try:
        return BookmarkStatus(str(value))
    except ValueError as exc:
        allowed = ", ".join(ALL_STATUS_VALUES)
        raise ValueError(f"unknown bookmark status: {value!r} (allowed: {allowed})") from exc


def can_transition(current: str | BookmarkStatus, new: str | BookmarkStatus) -> bool:
    """判断流转是否允许；同状态视为允许（无操作）。"""
    source = parse_status(current)
    target = parse_status(new)
    if source is target:
        return True
    return target in _TRANSITIONS[source]


def assert_transition(current: str | BookmarkStatus, new: str | BookmarkStatus) -> BookmarkStatus:
    """校验流转，非法时抛 ``InvalidStateTransition``，合法时返回目标状态。"""
    source = parse_status(current)
    target = parse_status(new)
    if can_transition(source, target):
        return target
    allowed = ", ".join(sorted(status.value for status in _TRANSITIONS[source])) or "none"
    raise InvalidStateTransition(
        f"cannot move bookmark from {source.value} to {target.value} (allowed from {source.value}: {allowed})"
    )


def next_status(current: str | BookmarkStatus) -> BookmarkStatus | None:
    """返回 happy path 上的下一个状态；终态返回 None。"""
    source = parse_status(current)
    chain = {
        BookmarkStatus.NEW: BookmarkStatus.COLLECTED,
        BookmarkStatus.COLLECTED: BookmarkStatus.PROCESSED,
        BookmarkStatus.PROCESSED: BookmarkStatus.ENRICHED,
        BookmarkStatus.ENRICHED: BookmarkStatus.COMPLETED,
    }
    return chain.get(source)


def is_terminal(current: str | BookmarkStatus) -> bool:
    """是否终态（COMPLETED）。"""
    source = parse_status(current)
    return not _TRANSITIONS[source]
