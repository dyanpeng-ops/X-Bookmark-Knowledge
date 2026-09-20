"""markdown — 知识库 Markdown 产物层（Phase 7 已实现）。

渲染（`render.py`）与写盘（`writer.py`）分离：

* :func:`render_markdown` —— 纯函数，把上游记录 + 富化记录渲染为 Markdown 文本。
* :class:`MarkdownWriter` —— 读 `data/raw/*.json` → 渲染 → 写入
  `knowledge/X-Bookmarks/YYYY/MM/YYYYMMDD-{tweet_id}.md`，并推进状态、记录产物路径。
"""

from .render import (
    DEFAULT_FILENAME_PATTERN,
    MarkdownConflictError,
    MarkdownError,
    MarkdownRenderError,
    RenderOptions,
    build_frontmatter,
    relative_output_path,
    render_markdown,
    section_names_for,
)
from .writer import MarkdownStats, MarkdownWriter

__all__ = [
    "DEFAULT_FILENAME_PATTERN",
    "MarkdownConflictError",
    "MarkdownError",
    "MarkdownRenderError",
    "MarkdownStats",
    "MarkdownWriter",
    "RenderOptions",
    "build_frontmatter",
    "relative_output_path",
    "render_markdown",
    "section_names_for",
]
