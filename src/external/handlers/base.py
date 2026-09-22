"""外链正文抽取的公共约定（Phase 9）。

* `ContentHandler` 只做「已取回的页面字节 → 标题/摘要/正文」，不联网（网络在 `fetcher.py`）。
* handler 之间互不影响：某个 handler 抛出异常只会让那一条外链失败（`resolver` 逐条隔离）。
* 选择器按 `priority` 从具体到通用（GitHub 先于 web），避免"通用 handler 吞掉专用策略"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..fetcher import FetchedPage

__all__ = [
    "ContentHandler",
    "ContentHandlerError",
    "ExtractedContent",
    "NoHandlerError",
    "select_handler",
]


class ContentHandlerError(RuntimeError):
    """handler 无法处理该页面（内容类型不支持、解析失败等）。"""


class NoHandlerError(ContentHandlerError):
    """没有任何已启用的 handler 认领这个（URL, content-type）。"""


@dataclass(frozen=True, slots=True)
class ExtractedContent:
    """一条外链抽取出的内容（`body` 为已归一化的纯文本/Markdown）。"""

    handler: str
    title: str | None = None
    description: str | None = None
    body: str = ""
    canonical_url: str | None = None


class ContentHandler:
    """handler 基类：子类实现 :meth:`matches` 与 :meth:`extract`。"""

    #: 小者优先（更具体的 handler 用更小的值）。
    priority: int = 100

    @property
    def name(self) -> str:  # pragma: no cover - 子类覆写
        raise NotImplementedError

    def matches(self, url: str, content_type: str | None) -> bool:  # pragma: no cover
        raise NotImplementedError

    def extract(self, page: FetchedPage) -> ExtractedContent:  # pragma: no cover
        raise NotImplementedError


def select_handler(
    *,
    url: str,
    content_type: str | None,
    handlers: Mapping[str, ContentHandler],
) -> ContentHandler:
    """选出处理该页面的 handler；无人认领时抛 :class:`NoHandlerError`。

    `handlers` 是"已启用"的映射（`{handler_name: handler}`），因此未实现/未启用的
    策略天然不会命中，调用方据异常原因记为 `SKIPPED`。
    """

    matched = [
        handler for handler in handlers.values() if handler.matches(url, content_type)
    ]
    if not matched:
        kind = (content_type or "unknown").split(";")[0].strip() or "unknown"
        enabled = ", ".join(sorted(handlers)) or "none"
        raise NoHandlerError(
            f"no enabled handler for content-type {kind} (enabled: {enabled})"
        )
    return min(matched, key=lambda handler: (handler.priority, handler.name))
