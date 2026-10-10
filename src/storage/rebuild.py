"""Phase 4 · Step 4：`rebuild-index` —— 删库重建内容索引（决策 D4 + R6）。

命令契约
--------
扫描 ``normalized/*.json``（CanonicalBookmark）重建 SQLite 内容索引；
**运行态字段没有重建来源，重建后一律重置为初始态**（R6 §6.3.1）。

两种模式
--------
* **整库重建**（默认）：备份旧库 → 建新库 → 逐条写入内容索引。运行态回到初始态。
* **就地刷新**（``in_place=True``）：不删库，按 ``content_hash`` 幂等刷新内容索引，
  **运行态原样保留**。用于"索引坏了但处理进度要留着"的修复场景。

为何默认只演练
--------------
重建会丢弃运行态（重试计数、错误信息、媒体/外链状态），属于"可接受但不可逆"的操作，
因此 CLI 默认 ``--dry-run`` 语义，必须显式 ``--apply`` 才落盘。
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..canonical.validate import CanonicalValidationError, validate_bookmark
from ..database.connection import connect
from ..database.index_store import IndexStore
from .json_projection import safe_tweet_id
from .markdown_projection import markdown_relative_path

__all__ = [
    "RebuildError",
    "NormalizedEntry",
    "RebuildPlan",
    "RebuildReport",
    "RUNTIME_RESET_NOTE",
    "scan_normalized",
    "rebuild_from_plan",
    "rebuild_index",
]

#: R6 要求的「运行态重建即重置」说明（同时写进 CLI 帮助文本）。
RUNTIME_RESET_NOTE = (
    "运行态字段（bookmarks.status/attempts/error_message/first_synced_at/last_synced_at、"
    "media.download_status、external_links.fetch_status）**没有重建来源**，"
    "整库重建后一律重置为初始态（NEW / 0 / NULL / PENDING，时间戳=重建时刻）；"
    "内容索引（tweet_id / content_hash / 路径 / 可搜索字段）由 normalized/*.json 完整重建。"
    "若需保留处理进度，请使用 --in-place（按 content_hash 幂等刷新，不动运行态）。"
)


class RebuildError(RuntimeError):
    """重建过程的前置条件不满足（如 normalized 目录缺失）。"""


@dataclass(frozen=True, slots=True)
class NormalizedEntry:
    tweet_id: str
    source: Path
    bookmark: Mapping[str, Any]

    @property
    def content_hash(self) -> str:
        return str(self.bookmark["content_hash"])


@dataclass(frozen=True, slots=True)
class RebuildPlan:
    normalized_dir: Path
    entries: tuple[NormalizedEntry, ...] = ()
    failures: tuple[tuple[str, str], ...] = ()

    @property
    def scanned(self) -> int:
        return len(self.entries) + len(self.failures)

    @property
    def indexable(self) -> int:
        return len(self.entries)


@dataclass(frozen=True, slots=True)
class RebuildReport:
    plan: RebuildPlan
    db_path: Path
    applied: bool = False
    in_place: bool = False
    backup_path: Path | None = None
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    runtime_initial_state: int | None = None

    @property
    def written(self) -> int:
        return self.inserted + self.updated

    @property
    def ok(self) -> bool:
        return not self.plan.failures


def scan_normalized(normalized_dir: str | Path) -> RebuildPlan:
    """扫描并校验 ``normalized/*.json``；坏文件记入 ``failures`` 但不中断（AGENTS §2.7）。"""

    root = Path(normalized_dir).expanduser()
    if not root.is_dir():
        raise RebuildError(f"normalized 目录不存在: {root}")

    entries: list[NormalizedEntry] = []
    failures: list[tuple[str, str]] = []
    seen: dict[str, Path] = {}
    for path in sorted(root.glob("*.json")):
        if path.name.startswith("."):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failures.append((path.name, f"{type(exc).__name__}: {exc}"))
            continue
        if not isinstance(payload, Mapping):
            failures.append((path.name, "顶层不是 JSON 对象"))
            continue
        try:
            validate_bookmark(payload)
            tweet_id = safe_tweet_id(payload["tweet_id"])
        except (CanonicalValidationError, ValueError, KeyError) as exc:
            failures.append((path.name, f"{type(exc).__name__}: {exc}"))
            continue
        if tweet_id in seen:
            failures.append((path.name, f"tweet_id 重复（已在 {seen[tweet_id].name} 出现）"))
            continue
        seen[tweet_id] = path
        entries.append(NormalizedEntry(tweet_id=tweet_id, source=path, bookmark=payload))
    return RebuildPlan(normalized_dir=root, entries=tuple(entries), failures=tuple(failures))


def rebuild_from_plan(
    plan: RebuildPlan,
    *,
    db_path: str | Path,
    apply: bool = False,
    in_place: bool = False,
    backup: bool = True,
    raw_dir: str | Path | None = None,
    now: str | None = None,
) -> RebuildReport:
    """按计划重建索引。``apply=False`` 时只产出计划（不改任何文件）。"""

    db = Path(db_path).expanduser()
    stamp = (now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if not apply:
        return RebuildReport(plan=plan, db_path=db, applied=False, in_place=in_place)

    backup_path: Path | None = None
    if not in_place:
        backup_path = _discard_database(db, backup=backup, stamp=stamp)

    connection = connect(db)
    try:
        store = IndexStore(connection)
        inserted = updated = unchanged = 0
        for entry in plan.entries:
            result = store.upsert_content_index(
                now=stamp,
                tweet_id=entry.tweet_id,
                content_hash=entry.content_hash,
                **_content_columns(entry, raw_dir=raw_dir),
            )
            if result.action == "inserted":
                inserted += 1
            elif result.action == "updated":
                updated += 1
            else:
                unchanged += 1
        runtime_initial = int(
            connection.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
        ) if not in_place else None
    finally:
        connection.close()

    return RebuildReport(
        plan=plan,
        db_path=db,
        applied=True,
        in_place=in_place,
        backup_path=backup_path,
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        runtime_initial_state=runtime_initial,
    )


def rebuild_index(
    normalized_dir: str | Path,
    *,
    db_path: str | Path,
    apply: bool = False,
    in_place: bool = False,
    backup: bool = True,
    raw_dir: str | Path | None = None,
    now: str | None = None,
) -> RebuildReport:
    """扫描 + 重建的一步入口。"""

    plan = scan_normalized(normalized_dir)
    return rebuild_from_plan(
        plan, db_path=db_path, apply=apply, in_place=in_place, backup=backup,
        raw_dir=raw_dir, now=now,
    )


# ── 内部 ────────────────────────────────────────────────────────────────────


def _content_columns(entry: NormalizedEntry, *, raw_dir: str | Path | None) -> dict[str, Any]:
    """把 CanonicalBookmark 映射成内容索引列（权威字段 → 索引列）。"""

    bookmark = entry.bookmark
    raw_path: str | None = None
    if raw_dir is not None:
        candidate = Path(raw_dir).expanduser() / f"{entry.tweet_id}.json"
        raw_path = str(candidate) if candidate.is_file() else None
    return {
        "author_id": bookmark.get("author_id"),
        "username": bookmark.get("author_username"),
        "author_name": bookmark.get("author"),
        "tweet_text": bookmark.get("text"),
        "created_at": bookmark.get("created_at"),
        "tweet_url": bookmark.get("url"),
        "conversation_id": bookmark.get("conversation_id"),
        "raw_json_path": raw_path,
        "markdown_path": markdown_relative_path(bookmark).as_posix(),
    }


def _discard_database(db: Path, *, backup: bool, stamp: str) -> Path | None:
    """备份（或删除）旧库及其 WAL/SHM 附属文件；返回备份路径。"""

    if not db.exists():
        return None
    backup_path: Path | None = None
    if backup:
        safe_stamp = stamp.replace(":", "").replace("-", "")
        backup_path = db.with_name(f"{db.name}.bak-{safe_stamp}")
        shutil.copy2(db, backup_path)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db) + suffix)
        if candidate.exists():
            candidate.unlink()
    return backup_path
