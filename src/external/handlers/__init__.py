"""handlers — 外链分站处理器（Phase 9 起实现 `web` / `github`）。

* `web`    —— 通用 HTML / 纯文本（`html.parser`，无第三方依赖）
* `github` —— GitHub 专用标题策略（复用 `web` 的正文抽取）
* `pdf`    —— **尚未实现**（Phase 9 不引入 PDF 解析库，`config` 里配置了也只会提示，
  相关链接记 `SKIPPED` 并保留原始 URL）

每个 handler 独立可测，且失败只影响它自己处理的那一条外链（`resolver` 逐条隔离）。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .base import (
    ContentHandler,
    ContentHandlerError,
    ExtractedContent,
    NoHandlerError,
    select_handler,
)
from .github import GITHUB_HOSTS, GitHubHandler, host_of
from .web import (
    BLOCK_TAGS,
    HTML_CONTENT_TYPES,
    SKIP_TAGS,
    TEXT_CONTENT_TYPES,
    HtmlDocument,
    WebHandler,
    base_content_type,
    is_supported_content_type,
    normalise_text,
    parse_html,
)

__all__ = [
    "BLOCK_TAGS",
    "GITHUB_HOSTS",
    "HANDLER_TYPES",
    "HTML_CONTENT_TYPES",
    "IMPLEMENTED_HANDLER_NAMES",
    "SKIP_TAGS",
    "TEXT_CONTENT_TYPES",
    "ContentHandler",
    "ContentHandlerError",
    "ExtractedContent",
    "GitHubHandler",
    "HtmlDocument",
    "NoHandlerError",
    "WebHandler",
    "base_content_type",
    "build_handlers",
    "host_of",
    "is_supported_content_type",
    "normalise_text",
    "parse_html",
    "select_handler",
]

#: 已实现的 handler（键为 `external.handlers` 里的名字）。
HANDLER_TYPES: Mapping[str, type[ContentHandler]] = {
    "web": WebHandler,
    "github": GitHubHandler,
}

IMPLEMENTED_HANDLER_NAMES: tuple[str, ...] = tuple(sorted(HANDLER_TYPES))


def build_handlers(
    names: Sequence[str] | None = None,
) -> tuple[dict[str, ContentHandler], tuple[str, ...]]:
    """按配置构造 handler 表。

    返回 ``(已启用, 配置了但尚未实现的名字)``——第二个元素由 CLI 打印提示，
    不抛异常：本机旧配置里的 `pdf` 不应该让 `links` 直接跑不起来。
    """

    requested = (
        IMPLEMENTED_HANDLER_NAMES
        if names is None
        else tuple(str(name).strip().lower() for name in names if str(name).strip())
    )
    handlers: dict[str, ContentHandler] = {}
    unknown: list[str] = []
    for name in requested:
        factory = HANDLER_TYPES.get(name)
        if factory is None:
            unknown.append(name)
            continue
        handlers[name] = factory()
    return handlers, tuple(unknown)
