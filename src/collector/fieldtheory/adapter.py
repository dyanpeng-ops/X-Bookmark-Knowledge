"""``src.collector.fieldtheory`` —— Field Theory 作为「一个 Collector 实现」。

Phase 3 交付（任务书 §7）：

* :class:`FieldTheoryCollector` —— 把 Field Theory 上游数据读成
  :class:`~src.collector.raw_data.RawCollectorData`，让 Field Theory 只是
  Collector，而不是项目的数据模型（任务书 §5 R1）。

边界
----
* **只读**上游数据：``bookmarks.jsonl`` 与项目内的富化快照
  ``<raw_dir>/<tweet_id>.json``。绝不写入、绝不删除、绝不修改 X 书签。
* **不执行上游 CLI**：本模块不调用 ``fieldtheory sync/list/show``，因此
  Phase 3 的采集路径完全离线（富化数据来源已由用户决策为 ``data/raw/`` 快照）。
  上游 CLI 的调用与重试仍由既有 :class:`~src.collector.fieldtheory_adapter.FieldTheoryAdapter`
  负责（Phase 5 交付物，保持不动）。
* 不写 SQLite / Markdown / Knowledge / Git（任务书 §4.2、验收 G）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..base import UpstreamContractError
from ..fieldtheory_adapter import FieldTheoryAdapter
from ..raw_data import RawBookmarkItem, RawCollectorData

__all__ = ["FieldTheoryCollector", "COLLECTOR_NAME"]

COLLECTOR_NAME = "fieldtheory"


class FieldTheoryCollector:
    """``Field Theory → RawCollectorData``（任务书 §7）。

    :param adapter: 可注入的上游读取器；缺省时按参数构造
        :class:`FieldTheoryAdapter`（其 ``read_bookmarks()`` 已做上游契约校验）。
    :param raw_dir: 项目内富化快照目录（``<tweet_id>.json`` 的 ``enrichment`` 块）。
        为 ``None`` 时不做富化，Article / quoted_tweet 由 Normalizer 映射为
        ``None``（合法：Canonical Schema 中二者均可空）。
    :param strict: 为 ``True`` 时，单条富化快照损坏直接抛错；缺省 ``False``
        表示「单条失败不拖垮整批」（AGENTS.md 最高优先级原则第 7 条），失败原因
        记入 :attr:`last_warnings`。
    """

    def __init__(
        self,
        adapter: FieldTheoryAdapter | None = None,
        *,
        raw_dir: str | Path | None = None,
        data_dir: str | Path | None = None,
        executable: str | Sequence[str] | None = None,
        home_dir: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        strict: bool = False,
    ) -> None:
        if adapter is None:
            adapter = FieldTheoryAdapter(
                executable=executable,
                data_dir=data_dir,
                home_dir=home_dir,
                env=env,
            )
        self._adapter = adapter
        self._raw_dir = Path(raw_dir).expanduser() if raw_dir is not None else None
        self.strict = bool(strict)
        self.last_warnings: tuple[str, ...] = ()

    # ── 属性 ────────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Collector 标识，写入 Canonical ``collector`` 字段。"""

        return COLLECTOR_NAME

    @property
    def adapter(self) -> FieldTheoryAdapter:
        return self._adapter

    @property
    def data_dir(self) -> Path:
        return self._adapter.data_dir

    @property
    def raw_dir(self) -> Path | None:
        return self._raw_dir

    def check_ready(self):
        """透传上游就绪检查（不被本项目写操作污染）。"""

        return self._adapter.check_ready()

    # ── 采集 ────────────────────────────────────────────────────────────────

    def collect(self, *, with_enrichment: bool = True) -> RawCollectorData:
        """读取全部书签并返回冻结契约。

        上游整体不可用/JSONL 结构损坏时抛 ``Upstream*Error``（既有分类）；
        单条富化快照问题默认降级为 ``enrichment=None`` 并记入 ``last_warnings``。
        """

        bookmarks = self._adapter.read_bookmarks()
        warnings: list[str] = []
        items: list[RawBookmarkItem] = []
        for bookmark in bookmarks:
            enrichment = None
            if with_enrichment:
                try:
                    enrichment = self._read_enrichment(bookmark.tweet_id)
                except UpstreamContractError as exc:
                    if self.strict:
                        raise
                    warnings.append(str(exc))
            items.append(
                RawBookmarkItem(
                    tweet_id=str(bookmark.tweet_id),
                    payload=self._payload_of(bookmark),
                    enrichment=enrichment,
                )
            )
        self.last_warnings = tuple(warnings)
        return RawCollectorData(collector=COLLECTOR_NAME, items=tuple(items), cursor=None)

    # ── 内部 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _payload_of(bookmark: Any) -> Mapping[str, Any]:
        """取上游记录的原始 camelCase dict（``UpstreamBookmark.raw``）。"""

        payload = getattr(bookmark, "raw", None)
        if not isinstance(payload, Mapping) or not payload:
            raise UpstreamContractError(
                f"upstream record {getattr(bookmark, 'tweet_id', '?')!r} carries no raw payload"
            )
        return payload

    def _read_enrichment(self, tweet_id: str) -> Mapping[str, Any] | None:
        """读取 ``<raw_dir>/<tweet_id>.json`` 的 ``enrichment`` 块（只读、可缺失）。"""

        if self._raw_dir is None:
            return None
        path = self._raw_dir / f"{tweet_id}.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UpstreamContractError(
                f"{path}: unreadable enrichment snapshot ({exc})"
            ) from exc
        if not isinstance(payload, Mapping):
            raise UpstreamContractError(
                f"{path}: expected a JSON object, got {type(payload).__name__}"
            )
        block = payload.get("enrichment")
        if block is None:
            return None
        if not isinstance(block, Mapping):
            raise UpstreamContractError(
                f"{path}: 'enrichment' must be an object or null, got {type(block).__name__}"
            )
        return block
