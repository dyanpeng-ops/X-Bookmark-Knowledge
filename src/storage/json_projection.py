"""Canonical JSON 投影（Phase 4 · Step 1）。

落盘位置（``ARCHITECTURE.md`` §6.2 / §13）::

    data/normalized/{tweet_id}.json

设计要点
--------
* **契约校验前置**：写盘前必须通过 ``canonical.validate.validate_bookmark``，
  保证磁盘上的 normalized JSON 永远合法（验收 A）。
* **原子写**：先写同目录临时文件，``flush`` + ``fsync`` 后 ``os.replace`` 替换，
  避免中途崩溃留下半截 JSON；异常时清理临时文件。
* **幂等**：目标文件已存在且 ``content_hash`` 与本次相同 → **不重写**（不动 mtime），
  满足「内容未变即跳过」的跨设备同步语义（验收 B）。
* **路径安全**：``tweet_id`` 来自不可信上游，必须拒绝含路径分隔符 / ``..`` / 控制字符的取值，
  防止写出目录之外（验收 H）。
* **单条隔离**：批量入口逐条 try/except，单条失败不中断整批（AGENTS §2.7，验收 F）。
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..canonical.validate import CanonicalValidationError, validate_bookmark

__all__ = [
    "CanonicalJsonError",
    "InvalidCanonicalBookmark",
    "JsonProjectionOutcome",
    "JsonProjectionReport",
    "normalized_path_for",
    "write_all_canonical_json",
    "write_canonical_json",
]

#: 文件名中禁止出现的字符（跨平台）：路径分隔符与 NUL。
_FORBIDDEN_IN_NAME = ("/", "\\", "\x00")

#: 序列化参数固定，保证同一 bookmark 产生**逐字节相同**的文件内容（确定性）。
_DUMP_KWARGS: dict[str, Any] = {
    "ensure_ascii": False,
    "indent": 2,
    "sort_keys": True,
}


class CanonicalJsonError(RuntimeError):
    """Canonical JSON 投影失败（基类）。"""


class InvalidCanonicalBookmark(CanonicalJsonError):
    """待落盘的 bookmark 不是合法 CanonicalBookmark，或身份不可安全用作文件名。"""


@dataclass(frozen=True)
class JsonProjectionOutcome:
    """一条 bookmark 的落盘结果。"""

    tweet_id: str
    path: Path
    written: bool
    reason: str  # "created" | "updated" | "unchanged"


@dataclass(frozen=True)
class JsonProjectionReport:
    """批量落盘结果：成功明细 + 逐条失败（不因单条失败中断整批）。"""

    outcomes: tuple[JsonProjectionOutcome, ...] = ()
    failures: tuple[tuple[str, str], ...] = ()

    @property
    def written(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.written)

    @property
    def unchanged(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.written)

    @property
    def ok(self) -> bool:
        return not self.failures


def normalized_path_for(normalized_dir: str | os.PathLike[str], tweet_id: str) -> Path:
    """返回 ``<normalized_dir>/<tweet_id>.json``；``tweet_id`` 不安全时抛错。"""

    safe_id = _safe_tweet_id(tweet_id)
    return Path(normalized_dir).expanduser() / f"{safe_id}.json"


def write_canonical_json(
    bookmark: Mapping[str, Any],
    normalized_dir: str | os.PathLike[str],
) -> JsonProjectionOutcome:
    """把一条 CanonicalBookmark 写为 ``<normalized_dir>/<tweet_id>.json``。

    内容未变（``content_hash`` 相同）时不重写文件；返回 :class:`JsonProjectionOutcome`
    说明实际发生了什么。bookmark 不合法时抛 :class:`InvalidCanonicalBookmark`。
    """

    if not isinstance(bookmark, Mapping):
        raise InvalidCanonicalBookmark(
            f"expected a canonical bookmark mapping, got {type(bookmark).__name__}"
        )

    tweet_id = _safe_tweet_id(bookmark.get("tweet_id"))
    try:
        validate_bookmark(bookmark)
    except CanonicalValidationError as exc:
        raise InvalidCanonicalBookmark(f"invalid canonical bookmark {tweet_id!r}: {exc}") from exc

    target = Path(normalized_dir).expanduser() / f"{tweet_id}.json"
    existed = target.is_file()
    if existed and _read_content_hash(target) == bookmark["content_hash"]:
        return JsonProjectionOutcome(
            tweet_id=tweet_id, path=target, written=False, reason="unchanged"
        )

    text = json.dumps(dict(bookmark), **_DUMP_KWARGS) + "\n"
    _atomic_write_text(target, text)
    return JsonProjectionOutcome(
        tweet_id=tweet_id,
        path=target,
        written=True,
        reason="updated" if existed else "created",
    )


def write_all_canonical_json(
    bookmarks: Iterable[Mapping[str, Any]],
    normalized_dir: str | os.PathLike[str],
) -> JsonProjectionReport:
    """批量落盘，逐条隔离失败（单条失败不影响其它条目）。"""

    outcomes: list[JsonProjectionOutcome] = []
    failures: list[tuple[str, str]] = []
    for index, bookmark in enumerate(bookmarks):
        label = _label_of(bookmark, index)
        try:
            outcomes.append(write_canonical_json(bookmark, normalized_dir))
        except (CanonicalJsonError, OSError) as exc:
            failures.append((label, f"{type(exc).__name__}: {exc}"))
    return JsonProjectionReport(outcomes=tuple(outcomes), failures=tuple(failures))


# ── 内部 ────────────────────────────────────────────────────────────────────


def _safe_tweet_id(value: Any) -> str:
    """校验 tweet_id 可安全用作文件名（不可信输入）。"""

    if not isinstance(value, str) or not value.strip():
        raise InvalidCanonicalBookmark(f"tweet_id must be a non-empty str, got {value!r}")
    if value != value.strip():
        raise InvalidCanonicalBookmark(f"tweet_id must not have surrounding whitespace: {value!r}")
    if any(token in value for token in _FORBIDDEN_IN_NAME):
        raise InvalidCanonicalBookmark(f"tweet_id contains a path separator or NUL: {value!r}")
    if value.startswith(".") or value in {".", ".."}:
        raise InvalidCanonicalBookmark(f"tweet_id must not start with '.': {value!r}")
    return value


def _label_of(bookmark: Any, index: int) -> str:
    if isinstance(bookmark, Mapping):
        value = bookmark.get("tweet_id")
        if isinstance(value, str) and value:
            return value
    return f"index:{index}"


def _read_content_hash(path: Path) -> str | None:
    """读取既有文件的 ``content_hash``；不可读/结构不符时返回 ``None``（视为需重写）。"""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, Mapping):
        return None
    value = data.get("content_hash")
    return value if isinstance(value, str) else None


def _atomic_write_text(target: Path, text: str) -> None:
    """同目录临时文件 + ``os.replace`` 原子替换；异常时清理临时文件。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:  # pragma: no cover - 清理失败不掩盖原始异常
            pass
        raise
