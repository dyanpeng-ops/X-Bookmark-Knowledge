"""媒体本地化层（Phase 8）。

职责边界
--------
* 只做「把上游媒体缓存里的字节复制到知识库自己的 `assets/`」+「回报结果」——
  **不联网、不重新下载、不删除任何源文件**（AGENTS.md 第 2 节）。
* 上游目录是**只读输入**：本层只读 `<upstream_data_dir>/media/`，绝不写入。
* 单条失败隔离：一条媒体失败不影响其余媒体（与 ingest / markdown 一致）。
* 幂等：目标文件已存在且内容哈希与源一致时跳过（不重写、不改 mtime）。

路径规则
--------
* 目标位置 `<knowledge_dir>/{YYYY}/{MM}/{assets_subdir}/{tweet_id}/{media_key}{ext}`，
  年月布局与 Markdown 产物同源（复用 `src.markdown.render.date_parts`）。
* 文件名用 `media_key`（= `sha1(source_url)[:16]`，见 `src.ingest.media_key_for`）：
  「DB 行 ↔ 文件」可直接互查，且不随上游命名变化而漂移。
* 成功后把**知识库内的绝对路径**写入 `media.local_path`；跳过或失败时**不改写**，
  于是 Markdown 侧自然回退到远程 URL（不丢信息）。

源文件解析（独立审计的前置条件）
--------------------------------
历史行里的 `local_path` 可能指向搬迁前的旧缓存
（`C:\\Users\\...\\.fieldtheory\\bookmarks\\media\\...`）。本层**只取文件名**，再到
**配置的上游媒体目录**下解析，因此不依赖旧缓存是否存在。顺序：

1. `local_path` 本身且位于知识库内 → 已本地化，判定 unchanged；
2. `local_path` 本身且位于配置的上游媒体目录内 → 直接使用；
3. 上游清单索引（`source_url → manifest localPath`）的文件名；
4. `local_path` 的文件名；
5. `source_url` 的文件名（兜底）；
6. 全部落空 → 记 FAILED（`error_message` + `attempts`），绝不用旧缓存里的同名文件充当证据。

跳过规则（不复制、不改 `local_path`，只在 `error_message` 留下 `skipped: ...` 原因）
----------------------------------------------------------------------------------
* `media.download: false`：整批跳过；
* 上游清单状态不是 `downloaded`（未下载的媒体没有可用源文件）；
* `media.download_video: false` 且类型属于 :data:`VIDEO_MEDIA_TYPES`；
* 源文件体积超过 `media.max_bytes`。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.parse import unquote, urlsplit

from src.config import MediaOptions
from src.database import MediaDownloadStatus
from src.markdown.render import date_parts

__all__ = [
    "DEFAULT_ASSETS_SUBDIR",
    "VIDEO_MEDIA_TYPES",
    "MediaError",
    "MediaLocalisationError",
    "MediaSource",
    "MediaUpdate",
    "MediaStats",
    "MediaLocalizer",
    "asset_dir_for",
    "stable_filename",
]

logger = logging.getLogger(__name__)

DEFAULT_ASSETS_SUBDIR = "assets"

#: 需要 `media.download_video: true` 才本地化的媒体类型（推文媒体对象里的原始 type）。
VIDEO_MEDIA_TYPES = frozenset({"video", "animated_gif"})

_UNSAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,8}$")
_HASH_CHUNK_BYTES = 1024 * 1024


class MediaError(RuntimeError):
    """媒体本地化失败。"""


class MediaLocalisationError(MediaError):
    """单条媒体无法本地化（源文件缺失、体积超限、读写失败等）。"""


# ── 纯函数：命名与布局 ───────────────────────────────────────────────────────


def _safe_component(value: object, default: str = "unknown") -> str:
    """把一段文本收敛成安全的单层路径组件（不允许分隔符或 `..`）。"""

    text = _UNSAFE_COMPONENT.sub("_", str(value or "").strip())
    # 去掉首尾的点与下划线，避免 "." / ".." / 隐藏文件 / 结尾空格。
    text = text.strip("._")
    return text or default


def stable_filename(media_key: str, source_name: str | None = None) -> str:
    """稳定文件名：`{media_key}{ext}`；扩展名取自源文件名，无法判定时用 `.bin`。"""

    return f"{_safe_component(media_key, 'media')}{_extension_of(source_name)}"


def _extension_of(name: str | None) -> str:
    if not name:
        return ".bin"
    suffix = Path(str(name)).suffix
    return suffix.lower() if _SAFE_SUFFIX.match(suffix or "") else ".bin"


def asset_dir_for(
    tweet_id: str, created_at: str | None, assets_subdir: str = DEFAULT_ASSETS_SUBDIR
) -> Path:
    """知识库内的媒体目录（相对 `knowledge_dir`）：`YYYY/MM/{assets_subdir}/{tweet_id}`。"""

    year, month, _ = date_parts(created_at)
    return (
        Path(year)
        / month
        / _safe_component(assets_subdir, DEFAULT_ASSETS_SUBDIR)
        / _safe_component(tweet_id, "unknown")
    )


# ── 数据结构 ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MediaSource:
    """一条待本地化的媒体（`media` 表一行 + 该书签的发帖时间）。

    `local_path` 是上游记录下来的路径，可能是旧缓存里的绝对路径（待归一）；
    `upstream_status` 是清单里的下载状态（`DOWNLOADED` / `PENDING` / ...）。
    """

    tweet_id: str
    media_key: str
    media_type: str | None = None
    source_url: str | None = None
    local_path: str | None = None
    upstream_status: str | None = None
    created_at: str | None = None

    @property
    def label(self) -> str:
        return f"{self.tweet_id}/{self.media_key}"


@dataclass(frozen=True)
class MediaUpdate:
    """一条媒体的落库意图，由调用方翻译成 repository 调用（本层不碰数据库）。"""

    tweet_id: str
    media_key: str
    status: str
    local_path: str | None = None
    error_message: str | None = None
    count_attempt: bool = False


@dataclass(frozen=True)
class MediaStats:
    """一次本地化的结果统计（CLI 报告直接使用）。"""

    attempted: int = 0
    copied: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0
    errors: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return self.failed == 0


# ── 本地化器 ─────────────────────────────────────────────────────────────────

Updater = Callable[[MediaUpdate], None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _url_filename(url: str | None) -> str | None:
    """取 URL 路径部分的文件名（去查询串与百分号编码）。"""

    if not url:
        return None
    try:
        path = urlsplit(str(url)).path
    except ValueError:
        return None
    name = Path(unquote(path)).name
    return name or None


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


class MediaLocalizer:
    """把一批媒体从上游缓存复制到知识库 `assets/`，并回报落库意图。"""

    def __init__(
        self,
        knowledge_dir: str | Path,
        upstream_media_dir: str | Path,
        *,
        options: MediaOptions | None = None,
        updater: Updater | None = None,
        upstream_index: Mapping[str, str] | None = None,
        dry_run: bool = False,
    ) -> None:
        """`upstream_media_dir` 是**配置的**上游媒体目录（只读输入）。

        `updater` 接受 :class:`MediaUpdate`（`None` 表示纯文件操作，供测试使用）。
        `upstream_index` 来自 `media-manifest.json`，键为 `sourceUrl`、值为清单里的
        `localPath`：即便 DB 里的 `local_path` 已被改写成知识库路径，也能重新定位源文件。
        `dry_run=True` 时只解析与报告，不建目录、不复制、不落库。
        """

        self._knowledge_dir = Path(knowledge_dir)
        self._knowledge_root = self._knowledge_dir.resolve()
        self._upstream_media_dir = Path(upstream_media_dir)
        self._upstream_media_root = self._upstream_media_dir.resolve()
        self._options = options or MediaOptions()
        self._updater = updater
        self._upstream_index = dict(upstream_index or {})
        self._dry_run = bool(dry_run)



    # ── 对外入口 ─────────────────────────────────────────────────────────────

    def run(self, sources: Iterable[MediaSource]) -> MediaStats:
        """逐条本地化；任何单条异常都被记录，不影响其余媒体。"""

        items = list(sources)
        copied = unchanged = skipped = failed = 0
        errors: list[tuple[str, str]] = []
        for source in items:
            try:
                outcome = self._localise_one(source)
            except Exception as exc:  # noqa: BLE001 - 单条失败必须被隔离
                message = f"{type(exc).__name__}: {exc}"
                logger.error("media localisation failed for %s: %s", source.label, message)
                errors.append((source.label, message))
                failed += 1
                continue
            if outcome == "copied":
                copied += 1
            elif outcome == "unchanged":
                unchanged += 1
            else:
                skipped += 1
        return MediaStats(
            attempted=len(items),
            copied=copied,
            unchanged=unchanged,
            skipped=skipped,
            failed=failed,
            errors=tuple(errors),
        )

    # ── 单条处理 ─────────────────────────────────────────────────────────────

    def _localise_one(self, source: MediaSource) -> str:
        media_key = str(source.media_key or "").strip()
        if not media_key:
            raise MediaLocalisationError("media row has no media_key")

        reason = self._skip_reason(source)
        if reason is not None:
            logger.info("media %s skipped: %s", source.label, reason)
            self._record_skip(source, reason)
            return "skipped"

        try:
            return self._materialise(source)
        except MediaError as exc:
            message = str(exc) or type(exc).__name__
            self._record(
                MediaUpdate(
                    tweet_id=source.tweet_id,
                    media_key=media_key,
                    status=MediaDownloadStatus.FAILED.value,
                    error_message=message,
                    count_attempt=True,
                )
            )
            raise MediaLocalisationError(f"{source.label}: {message}") from exc

    def _skip_reason(self, source: MediaSource) -> str | None:
        """返回跳过原因；`None` 表示需要真正本地化。"""

        if not self._options.download:
            return "media.download=false"
        status = str(source.upstream_status or "").strip().upper()
        if status != MediaDownloadStatus.DOWNLOADED.value:
            return f"upstream download status is {status or 'UNKNOWN'}"
        if self._is_video(source) and not self._options.download_video:
            return "video localisation disabled (media.download_video=false)"
        return None

    def _materialise(self, source: MediaSource) -> str:
        source_file = self._resolve_source_file(source)
        target = self._target_path(source, source_file)

        size = self._file_size(source_file)
        if size > self._options.max_bytes:
            reason = f"source is {size} bytes > media.max_bytes={self._options.max_bytes}"
            logger.info("media %s skipped: %s", source.label, reason)
            self._record_skip(source, reason)
            return "skipped"

        if _same_path(source_file, target):
            # 已指向知识库内的目标文件：自己与自己必然一致，不必读哈希。
            self._record_success(source, target)
            return "unchanged"

        if target.is_file() and _sha256(target) == _sha256(source_file):
            self._record_success(source, target)
            return "unchanged"

        self._copy(source_file, target)
        self._record_success(source, target)
        return "copied"

    def _resolve_source_file(self, source: MediaSource) -> Path:
        """按模块文档的 6 步顺序定位源文件；失败抛 :class:`MediaLocalisationError`。"""

        raw = str(source.local_path or "").strip()
        if raw:
            candidate = Path(raw)
            if candidate.is_file():
                if self._is_inside(candidate, self._knowledge_root):
                    return candidate
                if self._is_inside(candidate, self._upstream_media_root):
                    return candidate
            # 旧缓存路径（或已被改写的路径）：只保留文件名，到配置的媒体目录解析。

        names = self._candidate_names(source)
        for name in names:
            candidate = self._upstream_media_dir / name
            if candidate.is_file():
                return candidate
        raise MediaLocalisationError(
            f"source file not found under {self._upstream_media_dir} "
            f"(tried: {', '.join(names) or 'none'})"
        )

    def _candidate_names(self, source: MediaSource) -> list[str]:
        """候选文件名：清单索引 → DB 里的 `local_path` → URL 文件名（去重保序）。"""

        names: list[str] = []
        for value in (
            self._upstream_index.get(str(source.source_url or "")),
            source.local_path,
            _url_filename(source.source_url),
        ):
            if not value:
                continue
            name = Path(str(value).strip()).name
            if name and name not in names:
                names.append(name)
        return names

    def _target_path(self, source: MediaSource, source_file: Path) -> Path:
        directory = asset_dir_for(source.tweet_id, source.created_at, self._options.assets_subdir)
        return self._knowledge_dir / directory / stable_filename(source.media_key, source_file.name)


    def _is_video(self, source: MediaSource) -> bool:
        return str(source.media_type or "").strip().lower() in VIDEO_MEDIA_TYPES


    def _copy(self, source_file: Path, target: Path) -> None:
        """原子复制：先写同目录下的 `.part`，再 `os.replace` 覆盖目标。"""

        if self._dry_run:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        try:
            shutil.copyfile(source_file, tmp)
            os.replace(tmp, target)
        except OSError as exc:
            raise MediaLocalisationError(f"copy failed: {exc}") from exc
        finally:
            if tmp.exists():  # 失败残留不留在知识库里
                try:
                    tmp.unlink()
                except OSError:
                    logger.warning("could not remove temporary file %s", tmp)

    # ── 落库与工具 ───────────────────────────────────────────────────────────

    def _record(self, update: MediaUpdate) -> None:
        if self._dry_run or self._updater is None:
            return
        self._updater(update)

    def _record_success(self, source: MediaSource, target: Path) -> None:
        self._record(
            MediaUpdate(
                tweet_id=source.tweet_id,
                media_key=str(source.media_key),
                status=MediaDownloadStatus.DOWNLOADED.value,
                local_path=str(target),
            )
        )

    def _record_skip(self, source: MediaSource, reason: str) -> None:
        """跳过：状态保持上游原值（避免每次 sync 都被误判成"更新"），只记录原因。"""

        status = str(source.upstream_status or "").strip().upper()
        self._record(
            MediaUpdate(
                tweet_id=source.tweet_id,
                media_key=str(source.media_key),
                status=status or MediaDownloadStatus.PENDING.value,
                error_message=f"skipped: {reason}",
            )
        )

    @staticmethod
    def _file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError as exc:
            raise MediaLocalisationError(f"cannot stat source file {path}: {exc}") from exc

    @staticmethod
    def _is_inside(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root)
        except ValueError:
            return False
        return True
