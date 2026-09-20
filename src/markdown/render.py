"""Markdown 产物层（Phase 7）：把一条书签渲染为一份独立 Markdown 文件。

边界
----
* 只做"渲染 + 写盘"，不联网、不下载媒体。
* `## media` 段落可接收 Phase 8 本地化结果（`render_markdown(..., media_files=...)`）：
  命中本地文件时引用知识库内的相对路径，否则保留远程 URL。
* 幂等：同路径文件若内容一致则跳过（不覆盖）；内容不同且 `overwrite_existing=false` 时抛错。
* 来源数据：
  - 原始与富化载荷来自 `data/raw/{tweet_id}.json`（其中 `upstream` 是上游 JSONL 记录、
    `enrichment` 是 `fieldtheory list|show --json` 的富化记录，可含 article 正文与 quoted tweet）；
  - 数据库行（`BookmarkRecord`）提供 `markdown_path` 等状态。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from src.collector.contract import parse_twitter_datetime

__all__ = [
    "DEFAULT_FILENAME_PATTERN",
    "YEAR_MONTH_LAYOUT",
    "MarkdownError",
    "MarkdownRenderError",
    "MarkdownConflictError",
    "RenderOptions",
    "render_markdown",
    "build_frontmatter",
    "section_names_for",
    "relative_output_path",
    "date_parts",
]

logger = logging.getLogger(__name__)

DEFAULT_FILENAME_PATTERN = "{yyyymmdd}-{tweet_id}.md"
YEAR_MONTH_LAYOUT = "year_month"

FRONTMATTER_KEYS: tuple[str, ...] = (
    "tweet_id",
    "url",
    "author_handle",
    "author_name",
    "created_at",
    "language",
    "media_count",
    "link_count",
    "engagement",
    "tags",
    "primary_category",
    "folder_names",
    "source",
)


def _now_iso(now: Any = None) -> str:
    if now is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(now, datetime):
        return now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(now)


class MarkdownError(RuntimeError):
    """Markdown 渲染或写入失败。"""


class MarkdownRenderError(MarkdownError):
    """渲染阶段失败（来源数据不完整）。"""


class MarkdownConflictError(MarkdownError):
    """目标文件已存在且内容不同，且不允许覆盖。"""


@dataclass(frozen=True)
class RenderOptions:
    """一次渲染的参数。"""

    filename_pattern: str = DEFAULT_FILENAME_PATTERN
    layout: str = YEAR_MONTH_LAYOUT
    frontmatter: bool = True
    # 顺序与 config.example.yaml 的 markdown.include_sections 保持一致。
    include_sections: tuple[str, ...] = (
        "tweet",
        "thread",
        "media",
        "article",
        "external_links",
        "metadata",
        "ai_analysis",
        "source",
    )
    overwrite_existing: bool = False
    clock: Callable[[Any], str] = _now_iso


# ── 工具 ─────────────────────────────────────────────────────────────────────


def _md_escape(text: str) -> str:
    """只转义最可能在 Markdown 中断句的字符；保留中文与链接。"""

    value = str(text).replace("\r\n", "\n").replace("\r", "\n")
    # 先转义反斜杠再转义竖线，避免把 `|`→`\|` 再被误转成 `\\|`。
    return value.replace("\\", "\\\\").replace("|", "\\|")


def _iso_created_at(upstream: Mapping[str, Any]) -> str | None:
    """把 `postedAt`（RFC822 风格）转成 ISO UTC；失败返回 None。"""

    raw = upstream.get("postedAt")
    if not raw:
        return None
    try:
        parsed = parse_twitter_datetime(raw)
    except Exception:  # noqa: BLE001 - 渲染不应因单个字段崩溃
        logger.warning("unparseable postedAt %r", raw)
        return None
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _engagement_lines(engagement: Mapping[str, Any]) -> list[str]:
    labels = [
        ("likeCount", "Likes"),
        ("repostCount", "Reposts"),
        ("replyCount", "Replies"),
        ("quoteCount", "Quotes"),
        ("bookmarkCount", "Bookmarks"),
    ]
    return [
        f"- {label}: {int(engagement.get(key) or 0)}"
        for key, label in labels
        if engagement.get(key) is not None
    ]


def section_names_for(options: RenderOptions) -> list[str]:
    """返回应包含的段落名（已按 `include_sections` 去重、保序）。"""

    result: list[str] = []
    for name in options.include_sections:
        if name not in result:
            result.append(name)
    return result


def build_frontmatter(
    upstream: Mapping[str, Any], enrichment: Mapping[str, Any] | None
) -> dict[str, Any]:
    """构造 frontmatter 字典（键序稳定、值可被 YAML 序列化）。"""

    engagement = upstream.get("engagement") or {}
    media_urls = upstream.get("media") or ()
    tags = list(upstream.get("tags") or ())
    return {
        "tweet_id": upstream.get("tweetId"),
        "url": upstream.get("url"),
        "author_handle": upstream.get("authorHandle"),
        "author_name": upstream.get("authorName"),
        "created_at": _iso_created_at(upstream),
        "language": upstream.get("language"),
        "media_count": len(media_urls),
        "link_count": len(upstream.get("links") or ()),
        "engagement": dict(engagement),
        "tags": tags,
        "primary_category": (enrichment or {}).get("primaryCategory"),
        "folder_names": list((enrichment or {}).get("folderNames") or ()),
        "source": upstream.get("ingestedVia"),
    }


def date_parts(created_at: str | None) -> tuple[str, str, str]:
    """把 ISO `created_at` 拆成知识库布局用的 `(年, 月, YYYYMMDD)`。

    缺失或不可解析时三点都回退为 `unknown`（与 `relative_output_path` 同一约定，
    Phase 8 的媒体 `assets/` 目录复用它，保证两处布局永远一致）。
    """

    if not created_at:
        return "unknown", "unknown", "unknown"
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(created_at))
    if not match:
        return "unknown", "unknown", "unknown"
    year, month, day = match.groups()
    return year, month, year + month + day


def relative_output_path(
    tweet_id: str,
    created_at: str | None,
    options: RenderOptions,
) -> Path:
    """计算知识库内的相对路径：`YYYY/MM/YYYYMMDD-{tweet_id}.md`。

    `created_at` 必须是 ISO-8601 字符串（或 None）；年份/月份缺失时落到
    `unknown/unknown/`，文件名里的日期同样回退为 `unknown`。
    """

    year, month, yyyymmdd = date_parts(created_at)
    filename = options.filename_pattern.format(yyyymmdd=yyyymmdd, tweet_id=tweet_id)
    return Path(year) / month / filename


# ── 段落渲染 ─────────────────────────────────────────────────────────────────


def _render_section_tweet(upstream: Mapping[str, Any]) -> str:
    text = str(upstream.get("text") or "").strip()
    if not text:
        return "> （本条没有可展示的文本）"
    lines = _md_escape(text).split("\n")
    return "\n".join(f"> {line}" for line in lines) if len(lines) > 1 else f"> {lines[0]}"


def _render_section_media(
    upstream: Mapping[str, Any], media_files: Mapping[str, str] | None = None
) -> str:
    """媒体段落。

    `media_files`：`{source_url: 相对本 Markdown 文件的路径}`（Phase 8 本地化后的产物）。
    命中则引用知识库内的本地相对路径，未命中则保留远程 URL——本地化失败或未开启时
    **不丢信息**（与 Phase 9 外链"失败也保留原始 URL"同一原则）。
    """

    urls = upstream.get("media") or ()
    if not urls:
        return "_无媒体_"
    mapping = media_files or {}
    blocks: list[str] = []
    for url in urls:
        key = str(url)
        local = mapping.get(key)
        blocks.append(f"![]({local})" if local else f"![]({key})")
        blocks.append("")
    return "\n".join(blocks).rstrip()


def _render_section_article(enrichment: Mapping[str, Any] | None) -> str:
    if not enrichment:
        return "_未展开文章_"
    title = enrichment.get("articleTitle")
    body = enrichment.get("articleText")
    if not body:
        return f"- 标题：{_md_escape(title) if title else '（无）'}"
    parts: list[str] = []
    if title:
        parts.append(f"## 文章标题：{_md_escape(title)}")
    parts.append(_md_escape(body))
    return "\n\n".join(parts)


def _render_section_external_links(upstream: Mapping[str, Any]) -> str:
    links = [str(url) for url in (upstream.get("links") or ()) if str(url).strip()]
    if not links:
        return "_无外链_"
    seen: list[str] = []
    for url in links:
        if url not in seen:
            seen.append(url)
    return "\n".join(f"- {url}" for url in seen)


def _render_section_metadata(upstream: Mapping[str, Any], enrichment: Mapping[str, Any] | None) -> str:
    lines: list[str] = []
    engagement = upstream.get("engagement") or {}
    eng_lines = _engagement_lines(engagement)
    author = upstream.get("author") or {}
    if author.get("name"):
        lines.append(f"- 作者：{_md_escape(author['name'])}（@{_md_escape(upstream.get('authorHandle'))}）")
    if upstream.get("postedAt"):
        lines.append(f"- 发布于：`{_md_escape(str(upstream['postedAt']))}`")
    if upstream.get("language"):
        lines.append(f"- 语言：{upstream['language']}")
    if upstream.get("conversationId"):
        lines.append(f"- 会话 ID：`{upstream['conversationId']}`")
    if eng_lines:
        lines.append("- 互动：" + "；".join(eng_lines))
    enriched = enrichment or {}
    if enriched.get("primaryCategory"):
        lines.append(f"- 分类：{enriched['primaryCategory']}")
    folders = list(enriched.get("folderNames") or ())
    if folders:
        lines.append(f"- 文件夹：{', '.join(str(f) for f in folders)}")
    return "\n".join(lines) if lines else "_无更多元数据_"


def _render_section_thread(enrichment: Mapping[str, Any] | None) -> str:
    """引用推文/线程上下文（来自富化 `quotedTweet`；JSONL 中不携带）。"""

    quoted = (enrichment or {}).get("quotedTweet")
    if not isinstance(quoted, Mapping) or not quoted:
        return "_无引用推文_"
    lines: list[str] = []
    header: list[str] = []
    if quoted.get("authorHandle"):
        header.append(f"@{_md_escape(str(quoted['authorHandle']))}")
    if quoted.get("tweetId"):
        header.append(f"`{str(quoted['tweetId'])}`")
    if header:
        lines.append("- 引用：" + " ".join(header))
    text = str(quoted.get("text") or "").strip()
    if text:
        lines.extend(f"> {line}" for line in _md_escape(text).split("\n"))
    return "\n".join(lines) if lines else "_无引用推文内容_"


def _render_section_ai_analysis() -> str:
    """占位段：AI 增强在 Phase 11 实现（默认关闭），本阶段不写入任何分析内容。"""

    return "_预留段：AI 分析将于 Phase 11 生成（当前不含任何分析内容）_"


def _render_section_source(upstream: Mapping[str, Any]) -> str:
    url = upstream.get("url")
    if not url:
        return "_无来源链接_"
    return f"原文：<{url}>"


_SECTION_RENDERERS: dict[str, Any] = {
    "tweet": lambda u, e, m: _render_section_tweet(u),
    "thread": lambda u, e, m: _render_section_thread(e),
    "media": lambda u, e, m: _render_section_media(u, m),
    "article": lambda u, e, m: _render_section_article(e),
    "external_links": lambda u, e, m: _render_section_external_links(u),
    "metadata": lambda u, e, m: _render_section_metadata(u, e),
    "ai_analysis": lambda u, e, m: _render_section_ai_analysis(),
    "source": lambda u, e, m: _render_section_source(u),
}


def render_markdown(
    upstream: Mapping[str, Any],
    enrichment: Mapping[str, Any] | None,
    options: RenderOptions,
    *,
    media_files: Mapping[str, str] | None = None,
) -> str:
    """渲染整份 Markdown 文本（含可选 frontmatter + 各段落）。

    `media_files` 为可选的 `{source_url: 相对本文件的路径}` 映射（Phase 8 媒体本地化），
    缺省时 `## media` 段落沿用远程 URL（Phase 7 行为完全不变）。
    """

    parts: list[str] = []
    if options.frontmatter:
        frontmatter = build_frontmatter(upstream, enrichment)
        lines = ["---"]
        for key in FRONTMATTER_KEYS:
            if key in frontmatter:
                lines.append(f"{key}: {_dump_scalar(frontmatter[key])}")
        lines.append("---")
        parts.append("\n".join(lines))

    for name in section_names_for(options):
        renderer = _SECTION_RENDERERS.get(name)
        if renderer is None:
            logger.warning("unknown markdown section requested: %s", name)
            continue
        try:
            body = renderer(upstream, enrichment, media_files)
        except Exception as exc:  # noqa: BLE001 - 单段失败不能丢弃整份
            logger.warning("section %r failed: %s", name, exc)
            body = f"_（段落 {name} 渲染失败）_"
        parts.append(f"## {name}\n\n{body}")

    return "\n\n".join(parts).rstrip() + "\n"


def _dump_scalar(value: Any) -> str:
    """把 frontmatter 值转成可被 YAML 解析的标量行。"""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value)
    if "\n" in text or text.startswith(("#", "!", "&", "*", "{", "[", ">", "|", "'", '"')):
        return json.dumps(text, ensure_ascii=False)
    return text