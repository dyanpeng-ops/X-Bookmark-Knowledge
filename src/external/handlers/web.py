"""`web` handler：从 HTML / 纯文本页面抽取标题、摘要与正文（Phase 9）。

只用标准库 `html.parser`（ADR-017），不引入 readability/lxml/bs4：

* 跳过的标签：`script` / `style` / `noscript` / `template` / `svg` / `iframe` / `form` /
  `nav` / `header` / `footer` / `aside` 等"非正文"区域，避免把导航与脚本写进知识库。
* 块级标签产生换行，随后统一归一化空白（连续空格折叠、连续空行折叠、去首尾空行）。
* 标题优先级：`og:title` → `twitter:title` → `<title>`（`<title>` 常带站点后缀，故排在后面）。
* 抽出 `<link rel="canonical">` 作为 `canonical_url`，与重定向后的 URL 一起供人核查。

明确不做的：排版还原、懒加载内容、需 JS 渲染的页面、阅读模式打分。JS-only 页面抽不到
文字时按"无可抽取内容"失败处理（原始 URL 仍然保留）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from ..fetcher import FetchedPage
from .base import ContentHandler, ContentHandlerError, ExtractedContent

__all__ = [
    "BLOCK_TAGS",
    "HTML_CONTENT_TYPES",
    "SKIP_TAGS",
    "TEXT_CONTENT_TYPES",
    "HtmlDocument",
    "WebHandler",
    "base_content_type",
    "is_supported_content_type",
    "normalise_text",
    "parse_html",
]

HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "application/xml", "text/xml")
TEXT_CONTENT_TYPES = ("text/plain",)

SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "canvas",
        "iframe",
        "form",
        "button",
        "select",
        "option",
        "nav",
        "header",
        "footer",
        "aside",
        "dialog",
    }
)
BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)

_TITLE_KEYS = ("og:title", "twitter:title")
_DESCRIPTION_KEYS = ("description", "og:description", "twitter:description")
_WHITESPACE = re.compile(r"[ \t\f\v]+")


def base_content_type(content_type: str | None) -> str:
    """取 `Content-Type` 的主类型（小写、去掉参数）；缺失返回空串。"""

    return str(content_type or "").split(";")[0].strip().lower()


def is_supported_content_type(content_type: str | None) -> bool:
    """`web` handler 是否处理该内容类型（HTML / XHTML / XML / 纯文本）。"""

    return base_content_type(content_type) in HTML_CONTENT_TYPES + TEXT_CONTENT_TYPES


def normalise_text(text: str) -> str:
    """归一化空白：折叠行内空白、压缩连续空行、去掉首尾空行。"""

    cleaned = str(text).replace("\xa0", " ").replace("\u200b", "")
    cleaned = _WHITESPACE.sub(" ", cleaned)
    lines: list[str] = []
    for raw in cleaned.split("\n"):
        line = raw.strip()
        if line:
            lines.append(line)
        elif lines and lines[-1] != "":
            lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class HtmlDocument:
    """从 HTML 文本中抽出的最小信息集合。"""

    title: str | None
    description: str | None
    text: str
    canonical_url: str | None = None
    meta: dict[str, str] | None = None


class _TextExtractor(HTMLParser):
    """把 HTML 转成带段落的纯文本，并收集 title / meta / canonical。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    # ── HTMLParser 回调 ─────────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = str(tag).lower()
        if lowered in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lowered == "title":
            self._in_title = True
        elif lowered == "meta":
            self._record_meta(attrs)
        elif lowered == "link":
            self._record_link(attrs)
        if lowered in BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = str(tag).lower()
        if lowered in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if lowered == "title":
            self._in_title = False
        elif lowered in BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(str(data))
            return
        if self._skip_depth or not str(data).strip():
            return
        self._chunks.append(str(data))

    # ── 内部 ────────────────────────────────────────────────────────────────

    def _record_meta(self, attrs) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        key = (
            values.get("name") or values.get("property") or values.get("itemprop") or ""
        ).strip()
        content = values.get("content", "").strip()
        if key and content:
            self.meta.setdefault(key.lower(), content)

    def _record_link(self, attrs) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if values.get("rel", "").strip().lower() == "canonical" and values.get("href"):
            self.canonical = values["href"].strip()

    # ── 结果 ────────────────────────────────────────────────────────────────

    @property
    def title(self) -> str | None:
        for key in _TITLE_KEYS:
            value = self.meta.get(key)
            if value:
                return normalise_text(value)
        inline = normalise_text(" ".join(self.title_parts))
        return inline or None

    @property
    def description(self) -> str | None:
        for key in _DESCRIPTION_KEYS:
            value = self.meta.get(key)
            if value:
                return normalise_text(value)
        return None

    @property
    def text(self) -> str:
        return normalise_text("".join(self._chunks))


def parse_html(text: str) -> HtmlDocument:
    """把 HTML 文本解析为 :class:`HtmlDocument`（畸形 HTML 也不抛异常）。"""

    parser = _TextExtractor()
    try:
        parser.feed(str(text))
        parser.close()
    except Exception as exc:  # noqa: BLE001 - 解析器对畸形输入可能抛任意异常
        raise ContentHandlerError(f"HTML parse failed: {exc}") from exc
    return HtmlDocument(
        title=parser.title,
        description=parser.description,
        text=parser.text,
        canonical_url=parser.canonical,
        meta=dict(parser.meta),
    )


class WebHandler(ContentHandler):
    """通用网页 handler：HTML/XHTML/XML → 标题 + 摘要 + 正文；`text/plain` → 正文。"""

    priority = 100
    name = "web"

    def matches(self, url: str, content_type: str | None) -> bool:
        return is_supported_content_type(content_type)

    def extract(self, page: FetchedPage) -> ExtractedContent:
        base = base_content_type(page.content_type)
        raw = page.text()
        if base in TEXT_CONTENT_TYPES:
            body = normalise_text(raw)
            if not body:
                raise ContentHandlerError("page contains no extractable text")
            return ExtractedContent(handler=self.name, body=body)

        document = parse_html(raw)
        body = document.text
        if not body and not document.title:
            raise ContentHandlerError("page contains no extractable text")
        return ExtractedContent(
            handler=self.name,
            title=document.title,
            description=document.description,
            body=body,
            canonical_url=document.canonical_url,
        )
