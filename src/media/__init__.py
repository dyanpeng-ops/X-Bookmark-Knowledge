"""media — 媒体层（Phase 8 实现）。

（Phase 8）媒体本地化：上游 `media/` 缓存 → 知识库 `assets/{tweet_id}/`，
稳定命名、内容哈希去重、跳过规则、变更结果回报调用方落库。
不联网、不重新下载、不删除源文件，也不修改 Markdown 正文。
"""

from __future__ import annotations

from .localizer import (
    DEFAULT_ASSETS_SUBDIR,
    VIDEO_MEDIA_TYPES,
    MediaError,
    MediaLocalisationError,
    MediaLocalizer,
    MediaSource,
    MediaStats,
    MediaUpdate,
    asset_dir_for,
    stable_filename,
)

__all__ = [
    "DEFAULT_ASSETS_SUBDIR",
    "VIDEO_MEDIA_TYPES",
    "MediaError",
    "MediaLocalisationError",
    "MediaLocalizer",
    "MediaSource",
    "MediaStats",
    "MediaUpdate",
    "asset_dir_for",
    "stable_filename",
]

