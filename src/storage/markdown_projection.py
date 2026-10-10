"""Markdown 投影（Phase 4 · Step 2）。

落盘位置（``ARCHITECTURE.md`` §6.1）::

    knowledge/X-Bookmarks/{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md

* 布局复用既有 :func:`src.markdown.render.date_parts`，保证与 Phase 8 的 ``assets/`` 布局**永不漂移**。
* frontmatter 以 **Canonical 契约（Phase 2 / 决策 D2、D5）为准**：``author`` = 显示名，
  ``author_username`` = handle。``ARCHITECTURE.md`` §7 示例里的 ``author: "username"`` 系 D2 明确前
  的旧写法，本实现按 D2 处理（见 ``docs/`` 决策记录）。
* 正文两段式：``## Original Tweet``（可恢复的原文）+ ``## AI Analysis``（**只放占位说明，绝不编造分析**）。
* **不覆盖内容不同的既有文件**（验收 D）：内容相同 → 跳过；内容不同 → 记为 ``conflict`` 并保持原文件不变；
  仅在显式 ``overwrite=True`` 时改写。
* 批量入口逐条隔离失败（AGENTS §2.7）。
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..markdown.render import date_parts
from .json_projection import InvalidCanonicalBookmark, safe_tweet_id

__all__ = [
    "MarkdownProjectionError",
    "MarkdownConflict",
    "MarkdownProjectionOutcome",
    "MarkdownProjectionReport",
    "markdown_relative_path",
    "markdown_path_for",
    "render_frontmatter",
    "render_markdown",
    "write_markdown",
    "write_all_markdown",
]

AI_ANALYSIS_PLACEHOLDER = (
    "_待生成：AI 分析属后处理阶段（Phase 8/11），本投影不写入任何分析内容。_"
)

#: frontmatter 键顺序（稳定；仅包含可由 CanonicalBookmark 直接推导的字段）。
FRONTMATTER_KEYS: tuple[str, ...] = (
    "tweet_id",
    "author",
    "author_username",
    "author_id",
    "created_at",
    "source",
    "collector",
    "collected_at",
    "updated_at",
    "content_hash",
    "url",
    "conversation_id",
    "media_count",
    "link_count",
)


class MarkdownProjectionError(RuntimeError):
    """Markdown 投影失败（基类）。"""


class MarkdownConflict(MarkdownProjectionError):
    """目标文件已存在且内容与本条不一致（默认拒绝覆盖）。"""


@dataclass(frozen=True)
class MarkdownProjectionOutcome:
    tweet_id: str
    path: Path
    written: bool
    reason: str  # created | unchanged | updated | conflict


@dataclass(frozen=True)
class MarkdownProjectionReport:
    outcomes: tuple[MarkdownProjectionOutcome, ...] = ()
    failures: tuple[tuple[str, str], ...] = ()

    @property
    def written(self) -> int:
        return sum(1 for o in self.outcomes if o.written)

    @property
    def conflicts(self) -> int:
        return sum(1 for o in self.outcomes if o.reason == "conflict")

    @property
    def ok(self) -> bool:
        return not self.failures and not self.conflicts


# ── 路径 ────────────────────────────────────────────────────────────────────


def markdown_relative_path(bookmark: Mapping[str, Any]) -> Path:
    """``YYYY/MM/YYYYMMDD-{tweet_id}.md``（时间不可解析时回退 ``unknown/``）。"""

    tweet_id = safe_tweet_id(_field(bookmark, "tweet_id"))
    year, month, yyyymmdd = date_parts(_optional_str(bookmark.get("created_at")))
    return Path(year) / month / f"{yyyymmdd}-{tweet_id}.md"


def markdown_path_for(knowledge_dir: str | os.PathLike[str], bookmark: Mapping[str, Any]) -> Path:
    return Path(knowledge_dir).expanduser() / markdown_relative_path(bookmark)


# ── frontmatter / 正文 ──────────────────────────────────────────────────────


#: 需要显式转义的 C0 控制字符（含 DEL）。YAML 双引号标量内用 `\\r`/`\\t`/`\\uXXXX`。
_YAML_NAMED_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _escape_yaml_string(text: str) -> str:
    """把字符串转成 YAML 双引号标量安全的内容。

    审计 F-005：此前只转义 ``\\`` / ``"`` / ``\n``，**遗漏 ``\r``/``\t`` 及其余 C0 控制字符**
    ——元数据（作者名、URL 等）一旦含制表符/回车等，frontmatter 会被解析成非法或异值的 YAML。
    """

    parts: list[str] = []
    for ch in text:
        if ch == "\\":
            parts.append("\\\\")
        elif ch == '"':
            parts.append('\\"')
        elif ch in _YAML_NAMED_ESCAPES:
            parts.append(_YAML_NAMED_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            parts.append(f"\\u{ord(ch):04x}")
        else:
            parts.append(ch)
    return "".join(parts)


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_yaml_scalar(item) for item in value) + "]"
    return f'"{_escape_yaml_string(str(value))}"'


def frontmatter_mapping(bookmark: Mapping[str, Any]) -> dict[str, Any]:
    """从 CanonicalBookmark 推导 frontmatter（仅含可推导键，不编造）。"""

    media = bookmark.get("media")
    links = bookmark.get("external_links")
    return {
        "tweet_id": _field(bookmark, "tweet_id"),
        "author": _field(bookmark, "author"),
        "author_username": _field(bookmark, "author_username"),
        "author_id": _field(bookmark, "author_id"),
        "created_at": _field(bookmark, "created_at"),
        "source": _field(bookmark, "source"),
        "collector": _field(bookmark, "collector"),
        "collected_at": bookmark.get("collected_at"),
        "updated_at": bookmark.get("updated_at"),
        "content_hash": _field(bookmark, "content_hash"),
        "url": _field(bookmark, "url"),
        "conversation_id": bookmark.get("conversation_id"),
        "media_count": len(media) if isinstance(media, Sequence) else 0,
        "link_count": len(links) if isinstance(links, Sequence) else 0,
    }


def render_frontmatter(bookmark: Mapping[str, Any]) -> str:
    mapping = frontmatter_mapping(bookmark)
    lines = ["---"]
    lines.extend(f"{key}: {_yaml_scalar(mapping[key])}" for key in FRONTMATTER_KEYS)
    lines.append("---")
    return "\n".join(lines)


def _render_original_tweet(bookmark: Mapping[str, Any]) -> str:
    text = str(bookmark.get("text") or "").strip()
    author = _field(bookmark, "author")
    username = _field(bookmark, "author_username")
    created = _field(bookmark, "created_at")
    url = _field(bookmark, "url")

    parts = ["## Original Tweet", ""]
    parts.append(text if text else "> （本条没有可展示的文本）")
    parts.append("")
    parts.append(f"- 作者：{author}（@{username}）")
    parts.append(f"- 发布于：`{created}`")
    parts.append(f"- 原文：<{url}>")

    media = bookmark.get("media") or ()
    if isinstance(media, Sequence) and len(media):
        parts.extend(["", "### Media", ""])
        for index, item in enumerate(media, 1):
            if isinstance(item, Mapping):
                kind = item.get("type") or "unknown"
                uri = item.get("url") or ""
                size = ""
                if item.get("width") and item.get("height"):
                    size = f"（{item['width']}×{item['height']}）"
                parts.append(f"- {kind}{index}：<{uri}>{size}" if kind == "photo"
                             else f"- {kind}{index}：<{uri}>")
    links = bookmark.get("external_links") or ()
    if isinstance(links, Sequence) and len(links):
        parts.extend(["", "### External Links", ""])
        parts.extend(f"- <{link}>" for link in links)
    quoted = bookmark.get("quoted_tweet")
    if isinstance(quoted, Mapping):
        parts.extend(["", "### Quoted Tweet", ""])
        quote_text = str(quoted.get("text") or "").strip()
        for line in quote_text.splitlines() or [""]:
            parts.append(f"> {line}" if line else ">")
        parts.append(">")
        parts.append(f"> —— @{quoted.get('author_handle')} · `{quoted.get('tweet_id')}`")
    article = bookmark.get("x_article")
    if isinstance(article, Mapping):
        parts.extend(["", "### Article", ""])
        title = article.get("title")
        if title:
            parts.append(f"**{title}**")
            parts.append("")
        parts.append(str(article.get("text") or "").strip())
    return "\n".join(parts)


def render_markdown(bookmark: Mapping[str, Any]) -> str:
    """渲染完整 Markdown（frontmatter + 两段式正文），结尾保证单个换行。"""

    if not isinstance(bookmark, Mapping):
        raise MarkdownProjectionError(
            f"expected a canonical bookmark mapping, got {type(bookmark).__name__}"
        )
    safe_tweet_id(_field(bookmark, "tweet_id"))  # 身份必须可安全用作文件名
    body = _render_original_tweet(bookmark)
    text = f"{render_frontmatter(bookmark)}\n\n{body}\n\n## AI Analysis\n\n{AI_ANALYSIS_PLACEHOLDER}\n"
    return text


# ── 写盘 ────────────────────────────────────────────────────────────────────


def write_markdown(
    bookmark: Mapping[str, Any],
    knowledge_dir: str | os.PathLike[str],
    *,
    overwrite: bool = False,
) -> MarkdownProjectionOutcome:
    """写一条 Markdown；内容不同且 ``overwrite=False`` 时抛 :class:`MarkdownConflict`。"""

    text = render_markdown(bookmark)
    tweet_id = str(bookmark["tweet_id"])
    target = markdown_path_for(knowledge_dir, bookmark)
    existed = target.is_file()
    if existed:
        current = target.read_text(encoding="utf-8")
        if current == text:
            return MarkdownProjectionOutcome(tweet_id, target, False, "unchanged")
        if not overwrite:
            raise MarkdownConflict(
                f"existing file differs and overwrite=False: {target}"
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(target, text)
    return MarkdownProjectionOutcome(
        tweet_id, target, True, "updated" if existed else "created"
    )


def write_all_markdown(
    bookmarks: Iterable[Mapping[str, Any]],
    knowledge_dir: str | os.PathLike[str],
    *,
    overwrite: bool = False,
) -> MarkdownProjectionReport:
    """批量写 Markdown；逐条隔离失败与冲突（不中断整批）。"""

    outcomes: list[MarkdownProjectionOutcome] = []
    failures: list[tuple[str, str]] = []
    for index, bookmark in enumerate(bookmarks):
        label = str(bookmark.get("tweet_id")) if isinstance(bookmark, Mapping) and bookmark.get("tweet_id") else f"index:{index}"
        try:
            outcomes.append(write_markdown(bookmark, knowledge_dir, overwrite=overwrite))
        except MarkdownConflict as exc:
            outcomes.append(MarkdownProjectionOutcome(label, Path(""), False, "conflict"))
            failures.append((label, f"MarkdownConflict: {exc}"))
        except (MarkdownProjectionError, InvalidCanonicalBookmark, OSError, TypeError, ValueError) as exc:
            failures.append((label, f"{type(exc).__name__}: {exc}"))
    return MarkdownProjectionReport(outcomes=tuple(outcomes), failures=tuple(failures))


# ── 内部 ────────────────────────────────────────────────────────────────────


def _field(bookmark: Mapping[str, Any], key: str) -> str:
    value = bookmark.get(key)
    if not isinstance(value, str) or not value:
        raise MarkdownProjectionError(f"canonical bookmark requires non-empty {key!r}")
    return value


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _atomic_write_text(target: Path, text: str) -> None:
    """与 JSON 投影同一策略：同目录临时文件 + ``os.replace``，权限按 umask 收敛。"""

    fd, tmp_name = -1, ""
    for attempt in range(64):
        candidate = target.parent / f".{target.name}.{os.getpid()}.{attempt}.tmp"
        try:
            fd = os.open(str(candidate), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            continue
        tmp_name = str(candidate)
        break
    else:  # pragma: no cover - 极端情况下无法创建临时文件
        raise MarkdownProjectionError(f"cannot create a temporary file next to {target}")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:  # pragma: no cover
            pass
        raise
