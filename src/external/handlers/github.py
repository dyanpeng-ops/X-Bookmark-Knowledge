"""`github` handler：GitHub 页面的标题策略（Phase 9）。

GitHub 的 HTML 标题常带站点后缀与描述（`GitHub - owner/repo: xxx`），直接入知识库可读性差。
本 handler 在 :class:`~src.external.handlers.web.WebHandler` 的抽取结果之上，把标题换成
路径里的 `owner/repo`（gist 为 `user/id`），正文仍由通用抽取负责。

不做的：调用 GitHub API（需要 token、属于联网增强）、解析 README 的渲染分歧。
"""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlsplit

from ..fetcher import FetchedPage
from .base import ExtractedContent
from .web import WebHandler, is_supported_content_type

__all__ = ["GITHUB_HOSTS", "GitHubHandler", "host_of"]

GITHUB_HOSTS = frozenset(
    {
        "github.com",
        "www.github.com",
        "gist.github.com",
        "raw.githubusercontent.com",
    }
)


def host_of(url: str) -> str:
    """取主机名（小写、去端口与 userinfo）；解析失败返回空串。"""

    netloc = urlsplit(str(url)).netloc.lower()
    netloc = netloc.rsplit("@", 1)[-1]
    return netloc.split(":")[0]


class GitHubHandler(WebHandler):
    """GitHub 专用：标题用 `owner/repo`，其余沿用通用网页抽取。"""

    priority = 20
    name = "github"

    def matches(self, url: str, content_type: str | None) -> bool:
        return host_of(url) in GITHUB_HOSTS and is_supported_content_type(content_type)

    def extract(self, page: FetchedPage) -> ExtractedContent:
        content = super().extract(page)
        title = _repository_title(page) or content.title
        return replace(content, handler=self.name, title=title)


def _repository_title(page: FetchedPage) -> str | None:
    """从 `owner/repo/x` 形态的路径取 `owner/repo`；取不到返回 None（回退 HTML 标题）。"""

    parts = [part for part in urlsplit(str(page.final_url or page.url)).path.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return None
