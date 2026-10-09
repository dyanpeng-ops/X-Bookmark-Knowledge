"""RawCollectorData —— Collector 与 Normalizer 之间的边界契约（Phase 3 冻结）。

数据流（任务书 §1 / §6）::

    Field Theory → Collector Adapter → RawCollectorData
                 → Normalizer → CanonicalBookmark → Schema Validator

设计红线
--------
* **这不是项目的最终数据模型**。它只保证「哪一条 + 原始结构」，Field Theory
  专属字段（``engagement`` / ``ingestedVia`` / ``sortIndex`` / ``tags`` …）只能
  停留在 ``payload`` / ``enrichment`` 内，不得自动进入 Canonical Schema。
* ``tweet_id`` 是稳定身份（第一层去重）；Canonical 层不得使用 FT 内部 ID。
* 本模块**只依赖标准库**，不 import ``src.canonical``（Raw 层不认识 Canonical），
  也不 import 任何 Collector 实现，避免循环依赖。

与任务书 §6 的差异（已获用户批准的显式偏差，记录于
``docs/phase3-preflight-review.md`` 决策记录）：

* ``items`` 类型为 ``tuple``（任务书写 ``list``）——不可变更有利于幂等与测试；
* ``RawBookmarkItem`` 在 ``tweet_id`` + ``payload`` 之外增加可选 ``enrichment``：
  Article 正文 / 被引用推文只存在于富化数据中，必须跨过 Collector→Normalizer
  边界才能映射；任务书 §6.1 的措辞是「**至少**含 tweet_id + payload」，故允许。
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "RawDataContractError",
    "RawBookmarkItem",
    "RawCollectorData",
]


class RawDataContractError(ValueError):
    """RawCollectorData 契约被违反（类型/结构错误）。

    与 ``NormalizationError`` 的分工：本错误表示「Raw 边界本身不合法」，
    而不是「上游字段映射不出 Canonical 字段」。
    """


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


@dataclass(frozen=True)
class RawBookmarkItem:
    """一条由 Collector 读出的原始书签。

    :param tweet_id: 跨采集器的稳定身份字符串。契约**只要求非空字符串**——
        X 推文 ID 是纯数字，但本契约不强制 ``isdigit()``，以便未来接入
        SaveBox / X API / 人工导入等采集器（审计 A3：文档与实现对齐）。
    :param payload: Field Theory ``bookmarks.jsonl`` 原始记录（camelCase 原样保留）。
    :param enrichment: 可选富化块（Article / quotedTweet 等），来自上游
        ``list|show --json`` 的产物；结构同样保持原始 camelCase，不做 snake_case 化。
    """

    tweet_id: str
    payload: Mapping[str, Any]
    enrichment: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not _is_nonempty_str(self.tweet_id):
            raise RawDataContractError("RawBookmarkItem.tweet_id must be a non-empty str")
        if not isinstance(self.payload, Mapping):
            raise RawDataContractError(
                "RawBookmarkItem.payload must be a mapping, got "
                f"{type(self.payload).__name__}"
            )
        if self.enrichment is not None and not isinstance(self.enrichment, Mapping):
            raise RawDataContractError(
                "RawBookmarkItem.enrichment must be a mapping or None, got "
                f"{type(self.enrichment).__name__}"
            )


@dataclass(frozen=True)
class RawCollectorData:
    """一次 Collector 读取的完整输出（冻结契约）。

    :param collector: 采集器标识（如 ``"fieldtheory"``），必须非空。
    :param items: 原始书签序列；构造时统一收敛为 ``tuple``。
    :param cursor: 分页游标；无分页能力时为 ``None``（Field Theory 无游标）。
    """

    collector: str
    items: tuple[RawBookmarkItem, ...] = ()
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not _is_nonempty_str(self.collector):
            raise RawDataContractError("RawCollectorData.collector must be a non-empty str")
        if isinstance(self.items, (str, bytes)) or not isinstance(self.items, Sequence):
            raise RawDataContractError(
                "RawCollectorData.items must be a sequence of RawBookmarkItem, got "
                f"{type(self.items).__name__}"
            )
        items = tuple(self.items)
        for index, item in enumerate(items):
            if not isinstance(item, RawBookmarkItem):
                raise RawDataContractError(
                    f"RawCollectorData.items[{index}] must be RawBookmarkItem, got "
                    f"{type(item).__name__}"
                )
        if items is not self.items:
            object.__setattr__(self, "items", items)
        if self.cursor is not None and not _is_nonempty_str(self.cursor):
            raise RawDataContractError(
                "RawCollectorData.cursor must be a non-empty str or None"
            )

    def __len__(self) -> int:
        return len(self.items)

    @property
    def tweet_ids(self) -> tuple[str, ...]:
        """按文件顺序返回全部 ``tweet_id``（便于幂等/去重断言）。"""

        return tuple(item.tweet_id for item in self.items)
