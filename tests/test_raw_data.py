"""``RawCollectorData`` / ``RawBookmarkItem`` 契约测试（Phase 3，Test A）。

对应任务书
----------
* §6 冻结契约：``collector`` / ``items`` / ``cursor`` 与 ``tweet_id`` / ``payload``；
* §18 Test A：最小 RawCollectorData 结构正确；
* §22 Collector 接口被复用（不另起第二套），且 Phase 3 的 Collector 只读。

全部离线：不读真实 ``data/``、不联网、不写盘。
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.collector.base import Collector  # noqa: E402  (path bootstrap first)
from src.collector.fieldtheory import FieldTheoryCollector  # noqa: E402
from src.collector.raw_data import (  # noqa: E402
    RawBookmarkItem,
    RawCollectorData,
    RawDataContractError,
)


def make_item(tweet_id: str = "1900000000000000101", **overrides) -> RawBookmarkItem:
    payload = overrides.pop("payload", {"tweetId": tweet_id, "text": "sample"})
    return RawBookmarkItem(tweet_id=tweet_id, payload=payload, **overrides)


class RawBookmarkItemTests(unittest.TestCase):
    """§6.1：``tweet_id`` 负责身份，``payload`` 保留 Collector 原始结构。"""

    def test_minimal_item(self):
        item = make_item()
        self.assertEqual(item.tweet_id, "1900000000000000101")
        self.assertEqual(item.payload["text"], "sample")
        self.assertIsNone(item.enrichment)

    def test_payload_keeps_raw_camel_case(self):
        # payload 不得被 snake_case 化：FT 专属字段原样保留。
        item = make_item(
            payload={"tweetId": "1900000000000000101", "engagement": {"likeCount": 1}}
        )
        self.assertIn("engagement", item.payload)
        self.assertNotIn("like_count", item.payload)

    def test_empty_tweet_id_rejected(self):
        with self.assertRaises(RawDataContractError):
            make_item(tweet_id="")

    def test_non_str_tweet_id_rejected(self):
        with self.assertRaises(RawDataContractError):
            RawBookmarkItem(tweet_id=123, payload={})  # type: ignore[arg-type]

    def test_non_mapping_payload_rejected(self):
        with self.assertRaises(RawDataContractError):
            RawBookmarkItem(tweet_id="1", payload=["not", "a", "mapping"])  # type: ignore[arg-type]

    def test_enrichment_accepts_mapping_or_none(self):
        self.assertIsNone(make_item(enrichment=None).enrichment)
        self.assertEqual(make_item(enrichment={"articleText": "x"}).enrichment, {"articleText": "x"})

    def test_enrichment_rejects_other_types(self):
        with self.assertRaises(RawDataContractError):
            make_item(enrichment="article")  # type: ignore[arg-type]

    def test_item_is_frozen(self):
        item = make_item()
        with self.assertRaises(FrozenInstanceError):
            item.tweet_id = "other"  # type: ignore[misc]


class RawCollectorDataTests(unittest.TestCase):
    """§6：Collector 与 Normalizer 之间的边界，不是项目最终数据模型。"""

    def test_minimal_container(self):
        data = RawCollectorData(collector="fieldtheory", items=(make_item(),), cursor=None)
        self.assertEqual(data.collector, "fieldtheory")
        self.assertEqual(len(data.items), 1)
        self.assertIsNone(data.cursor)

    def test_items_coerced_to_tuple(self):
        # Phase 3 决策：list 入参被收敛为不可变 tuple，保证幂等语义。
        data = RawCollectorData(collector="fieldtheory", items=[make_item()])  # type: ignore[arg-type]
        self.assertIsInstance(data.items, tuple)

    def test_default_items_is_empty_tuple(self):
        data = RawCollectorData(collector="fieldtheory")
        self.assertEqual(data.items, ())
        self.assertEqual(len(data), 0)
        self.assertEqual(data.tweet_ids, ())

    def test_tweet_ids_preserves_order(self):
        data = RawCollectorData(
            collector="fieldtheory",
            items=(make_item("2"), make_item("1"), make_item("3")),
        )
        self.assertEqual(data.tweet_ids, ("2", "1", "3"))

    def test_empty_collector_rejected(self):
        with self.assertRaises(RawDataContractError):
            RawCollectorData(collector="", items=())

    def test_item_type_enforced(self):
        with self.assertRaises(RawDataContractError):
            RawCollectorData(collector="fieldtheory", items=({"tweet_id": "1"},))  # type: ignore[arg-type]

    def test_items_must_be_sequence(self):
        with self.assertRaises(RawDataContractError):
            RawCollectorData(collector="fieldtheory", items="not-a-sequence")  # type: ignore[arg-type]

    def test_cursor_must_be_str_or_none(self):
        self.assertEqual(RawCollectorData(collector="c", cursor="next").cursor, "next")
        for bad in ("", 0, []):
            with self.assertRaises(RawDataContractError):
                RawCollectorData(collector="c", cursor=bad)  # type: ignore[arg-type]

    def test_container_is_frozen(self):
        data = RawCollectorData(collector="fieldtheory")
        with self.assertRaises(FrozenInstanceError):
            data.collector = "other"  # type: ignore[misc]


class CollectorInterfaceTests(unittest.TestCase):
    """§22：复用既有 Protocol，只新增 ``collect()``，不设计第二套接口。"""

    def test_protocol_declares_collect(self):
        self.assertTrue(hasattr(Collector, "collect"))
        self.assertTrue(callable(Collector.collect))

    def test_protocol_keeps_phase5_surface(self):
        for name in ("check_ready", "sync", "read_bookmarks", "collect"):
            self.assertTrue(hasattr(Collector, name), name)

    def test_fieldtheory_collector_surface_is_read_only(self):
        # §17：Collector 只读上游；Phase 3 的 Collector 不暴露会写上游的 sync()。
        self.assertTrue(callable(FieldTheoryCollector.collect))
        self.assertTrue(callable(FieldTheoryCollector.check_ready))
        self.assertFalse(hasattr(FieldTheoryCollector, "sync"))
        self.assertFalse(hasattr(FieldTheoryCollector, "read_bookmarks"))


if __name__ == "__main__":
    unittest.main()
