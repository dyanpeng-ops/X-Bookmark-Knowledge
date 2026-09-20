"""Markdown 写盘与状态推进（Phase 7）。

依赖注入一个"加载函数"，使本模块可被单测直接使用（不读写真实 `data/`）。
Phase 8 追加一个可选的 `media_lookup`，把媒体本地化结果带进 `## media` 段落。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .render import (
    MarkdownConflictError,
    MarkdownRenderError,
    RenderOptions,
    render_markdown,
)

__all__ = ["MarkdownStats", "MarkdownWriter"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarkdownStats:
    """一次写盘的结果统计。"""

    attempted: int = 0
    written: int = 0
    unchanged: int = 0
    conflicts: int = 0
    failed: int = 0
    errors: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.conflicts == 0


class MarkdownWriter:
    """对一批记录渲染 Markdown 并写入知识库；单条失败被隔离。"""

    def __init__(
        self,
        knowledge_dir: str | Path,
        *,
        raw_dir: str | Path | None = None,
        options: RenderOptions | None = None,
        loader: Callable[[str], Mapping[str, Any]] | None = None,
        status_updater: Callable[[str, str, str | None], None] | None = None,
        media_lookup: Callable[[str], Mapping[str, str]] | None = None,
    ) -> None:
        """`loader` 接受 tweet_id、返回原始归档 dict（含 `upstream`/`enrichment`）。

        `raw_dir`：默认加载器读取原始归档的目录（应为 `<root>/data/raw`）；
        为 None 时退化为 `knowledge_dir.parent / \"data\" / \"raw\"`（兼容测试单层布局）。

        `status_updater` 接受 (tweet_id, status, markdown_path) 以推进状态并记录产物路径；
        为 None 时跳过（纯渲染测试用）。

        `media_lookup`（Phase 8）接受 tweet_id、返回 `{source_url: 路径}`，路径可以是
        绝对路径，也可以是**相对 knowledge_dir** 的路径；本类会换算成相对 Markdown
        文件自身的 POSIX 路径。返回空 / 抛错时 `## media` 段落回退为远程 URL。
        """

        self._knowledge_dir = Path(knowledge_dir)
        self._raw_dir = Path(raw_dir) if raw_dir is not None else None
        self._options = options or RenderOptions()
        self._loader = loader
        self._status_updater = status_updater
        self._media_lookup = media_lookup

    def _resolve_loader(self) -> Callable[[str], Mapping[str, Any]]:
        if self._loader is not None:
            return self._loader

        def _load(tweet_id: str) -> Mapping[str, Any]:
            raw_dir = self._raw_dir if self._raw_dir is not None else self._knowledge_dir.parent / "data" / "raw"
            path = raw_dir / f"{tweet_id}.json"
            if not path.is_file():
                raise MarkdownRenderError(f"raw archive not found: {path}")
            return json.loads(path.read_text(encoding="utf-8"))

        return _load

    def run(self, tweet_ids: list[str]) -> MarkdownStats:
        """逐条渲染写盘；任何单条异常都会被记录，不影响其余记录。"""

        loader = self._resolve_loader()
        written = unchanged = conflicts = failed = 0
        errors: list[tuple[str, str]] = []
        for tweet_id in tweet_ids:
            try:
                payload = loader(tweet_id)
                upstream = payload.get("upstream") or {}
                enrichment = payload.get("enrichment")
                outcome = self._write_one(tweet_id, upstream, enrichment)
                if outcome == "written":
                    written += 1
                elif outcome == "unchanged":
                    unchanged += 1
                else:
                    conflicts += 1
            except MarkdownConflictError as exc:  # noqa: BLE001 - 拒绝覆盖是冲突，不是失败
                logger.warning("markdown conflict for %s: %s", tweet_id, exc)
                errors.append((tweet_id, f"{type(exc).__name__}: {exc}"))
                conflicts += 1
            except Exception as exc:  # noqa: BLE001 - 单条失败必须被隔离
                message = f"{type(exc).__name__}: {exc}"
                logger.error("markdown failed for %s: %s", tweet_id, message)
                errors.append((tweet_id, message))
                failed += 1
        return MarkdownStats(
            attempted=len(tweet_ids),
            written=written,
            unchanged=unchanged,
            conflicts=conflicts,
            failed=failed,
            errors=tuple(errors),
        )

    def _write_one(
        self, tweet_id: str, upstream: Mapping[str, Any], enrichment: Mapping[str, Any] | None
    ) -> str:
        """渲染一条并写盘；返回 'written' / 'unchanged' / 'conflict'。"""

        created_at = _iso_from_upstream(upstream)
        rel = relative_path_for(tweet_id, created_at, self._options)
        target = self._knowledge_dir / rel

        text = render_markdown(
            upstream,
            enrichment,
            self._options,
            media_files=self._resolve_media_files(tweet_id, target),
        )
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing == text:
                self._advance(tweet_id, target)
                return "unchanged"
            if not self._options.overwrite_existing:
                raise MarkdownConflictError(
                    f"refusing to overwrite {target} (overwrite_existing=false)"
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        self._advance(tweet_id, target)
        return "written"

    def _advance(self, tweet_id: str, target: Path) -> None:
        if self._status_updater is not None:
            self._status_updater(tweet_id, "PROCESSED", str(target))

    def _resolve_media_files(self, tweet_id: str, target: Path) -> dict[str, str]:
        """把媒体查询结果换算为"相对本 Markdown 文件"的 POSIX 路径。

        查询失败不终止渲染：`## media` 段落回退远程 URL 即可（单条失败隔离）。
        """

        if self._media_lookup is None:
            return {}
        try:
            raw = self._media_lookup(tweet_id) or {}
        except Exception as exc:  # noqa: BLE001 - 媒体缺失不该让 Markdown 失败
            logger.warning("media lookup failed for %s: %s", tweet_id, exc)
            return {}
        resolved: dict[str, str] = {}
        for url, value in raw.items():
            text = str(value or "").strip()
            if not text:
                continue
            candidate = Path(text)
            if not candidate.is_absolute():
                candidate = self._knowledge_dir / candidate
            try:
                display = os.path.relpath(candidate, target.parent)
            except ValueError:
                # 跨盘符（Windows）无法计算相对路径：保留原路径而不是让整条记录失败。
                display = str(candidate)
            resolved[str(url)] = display.replace("\\", "/")
        return resolved


def _iso_from_upstream(upstream: Mapping[str, Any]) -> str | None:
    raw = upstream.get("postedAt")
    if not raw:
        return None
    try:
        from src.collector.contract import parse_twitter_datetime

        from datetime import timezone as _tz

        return (
            parse_twitter_datetime(raw)
            .astimezone(_tz.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except Exception:  # noqa: BLE001
        return None


def relative_path_for(
    tweet_id: str, created_at: str | None, options: RenderOptions
) -> Path:
    """由 ISO created_at 计算知识库内相对路径（复用 render.relative_output_path）。"""

    from .render import relative_output_path

    return relative_output_path(tweet_id, created_at, options)