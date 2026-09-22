"""external — 外链层（Phase 9 实现）。

组成
----
* :mod:`src.external.fetcher`  —— 统一抓取封装（timeout / retry / 退避 / 重定向 / 编码探测 / 体积上限）
* :mod:`src.external.handlers` —— 分站正文抽取（`web` / `github`；`pdf` 待后续阶段）
* :mod:`src.external.resolver` —— 调度：抓取 → 抽取 → 写知识库 `assets/{tweet_id}/links/` → 回报落库

原则
----
* 网络只走 `fetcher`，且传输层可注入（测试全离线）。
* 单条外链失败不影响其余；**失败也保留原始 URL**（`external_links.url` 从不被清空）。
* 只写本项目知识库目录内；正文文件不含时间戳 → 内容不变即不重写。
"""

from __future__ import annotations

from .fetcher import (
    ALLOWED_SCHEMES,
    BlockedTargetError,
    DecodedText,
    FetchError,
    FetchedPage,
    HttpFetcher,
    HttpStatusError,
    PageTooLargeError,
    RetryableFetchError,
    TooManyRedirectsError,
    TransportFailure,
    TransportResponse,
    TransportTimeoutError,
    UnsupportedSchemeError,
    UrllibTransport,
    decode_body,
)
from .handlers import (
    ContentHandler,
    ContentHandlerError,
    ExtractedContent,
    GitHubHandler,
    NoHandlerError,
    WebHandler,
    build_handlers,
    parse_html,
    select_handler,
)

from .netguard import (
    HostResolver,
    check_url_allowed,
    host_matches_allowlist,
    is_public_address,
    system_host_resolver,
)
from .resolver import (
    LinkResolver,
    LinkStats,
    LinkTarget,
    LinkUpdate,
    link_content_name,
    link_dir_for,
    link_key_for,
    render_link_markdown,
    skip_domain_match,
)

__all__ = [
    "ALLOWED_SCHEMES",
    "BlockedTargetError",
    "ContentHandler",
    "ContentHandlerError",
    "DecodedText",
    "ExtractedContent",
    "FetchError",
    "FetchedPage",
    "GitHubHandler",
    "HostResolver",
    "HttpFetcher",
    "HttpStatusError",
    "LinkResolver",
    "LinkStats",
    "LinkTarget",
    "LinkUpdate",
    "NoHandlerError",
    "PageTooLargeError",
    "RetryableFetchError",
    "TooManyRedirectsError",
    "TransportFailure",
    "TransportResponse",
    "TransportTimeoutError",
    "UnsupportedSchemeError",
    "UrllibTransport",
    "WebHandler",
    "build_handlers",
    "check_url_allowed",
    "host_matches_allowlist",
    "is_public_address",
    "decode_body",
    "link_content_name",
    "link_dir_for",
    "link_key_for",
    "parse_html",
    "render_link_markdown",
    "select_handler",
    "skip_domain_match",
    "system_host_resolver",
]
