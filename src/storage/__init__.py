"""Storage 层（L3 投影落地）—— Phase 4。

职责：把 CanonicalBookmark（内存 dict）落成三种地位对等的投影：

* **JSON**    ``data/normalized/{tweet_id}.json``（标准交换，入 Git）—— 本模块
* Markdown  ``knowledge/X-Bookmarks/{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md``（长期可读）
* SQLite    ``data/state/state.db``（本地索引，可重建）

边界：本包**只消费** CanonicalBookmark，不认识 Field Theory；不修改 Schema；
不写 Markdown/知识库（由 :mod:`src.markdown` 负责）；所有写盘均为「先临时文件、后原子替换」。
"""

from .rebuild import (
    RebuildError,
    RebuildPlan,
    RebuildReport,
    rebuild_index,
    scan_normalized,
)
from .markdown_projection import (
    MarkdownConflict,
    MarkdownProjectionError,
    MarkdownProjectionOutcome,
    MarkdownProjectionReport,
    markdown_path_for,
    render_markdown,
    write_all_markdown,
    write_markdown,
)
from .json_projection import (
    CanonicalJsonError,
    InvalidCanonicalBookmark,
    JsonProjectionOutcome,
    JsonProjectionReport,
    normalized_path_for,
    write_all_canonical_json,
    write_canonical_json,
)

__all__ = [
    "CanonicalJsonError",
    "MarkdownConflict",
    "MarkdownProjectionError",
    "MarkdownProjectionOutcome",
    "MarkdownProjectionReport",
    "markdown_path_for",
    "render_markdown",
    "write_all_markdown",
    "write_markdown",
    "RebuildError",
    "RebuildPlan",
    "RebuildReport",
    "rebuild_index",
    "scan_normalized",
    "InvalidCanonicalBookmark",
    "JsonProjectionOutcome",
    "JsonProjectionReport",
    "normalized_path_for",
    "safe_tweet_id",
    "write_all_canonical_json",
    "write_canonical_json",
]
