"""``FieldTheoryCollector`` 测试（Phase 3，Test A/B/H/K 的一部分）。

对应任务书
----------
* §7 Field Theory → RawCollectorData；
* §8 富化数据双源（Phase 3 决策：项目内 ``<raw_dir>/<tweet_id>.json`` 快照）；
* §17 只读上游；§21 跨平台（``pathlib``）；§29-G Collector 不写 SQLite/Markdown/Knowledge/Git。

全部离线：用 ``tests/fixtures/upstream/bookmarks.sample.jsonl`` 复制的临时上游目录，
**不调用真实 fieldtheory、不联网、不写真实 ``data/``**。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.collector.base import UpstreamContractError, UpstreamUnavailableError  # noqa: E402
from src.collector.fieldtheory import COLLECTOR_NAME, FieldTheoryCollector  # noqa: E402
from src.collector.fieldtheory_adapter import FieldTheoryAdapter  # noqa: E402
from src.collector.raw_data import RawCollectorData  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "upstream"
SAMPLE_JSONL = FIXTURES / "bookmarks.sample.jsonl"
ADAPTER_SOURCE = PROJECT_ROOT / "src" / "collector" / "fieldtheory" / "adapter.py"

# fixture 中的三条记录（顺序即文件顺序）。
SAMPLE_IDS = (
    "1900000000000000101",
    "1900000000000000102",
    "1900000000000000103",
)


def _enrichment_block(tweet_id: str, **extra) -> dict:
    block = {
        "tweetId": tweet_id,
        "url": f"https://x.com/sample_author/status/{tweet_id}",
        "text": "sample",
        "authorHandle": "sample_author",
    }
    block.update(extra)
    return block


class CollectorTestCase(unittest.TestCase):
    """共享临时目录：上游 JSONL 由 fixture 复制，富化快照由测试按需写入。"""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="xbook-ft-collector-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.data_dir = self.tmp / "upstream"
        self.data_dir.mkdir()
        self.raw_dir = self.tmp / "raw"
        self.raw_dir.mkdir()
        shutil.copyfile(SAMPLE_JSONL, self.data_dir / "bookmarks.jsonl")

    def make_collector(self, *, raw_dir: Path | None = None, strict: bool = False) -> FieldTheoryCollector:
        adapter = FieldTheoryAdapter(data_dir=self.data_dir, retries=0)
        return FieldTheoryCollector(
            adapter=adapter,
            raw_dir=self.raw_dir if raw_dir is None else raw_dir,
            strict=strict,
        )

    def write_snapshot(self, tweet_id: str, payload: object) -> Path:
        path = self.raw_dir / f"{tweet_id}.json"
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        path.write_text(text, encoding="utf-8")
        return path


class CollectStructureTests(CollectorTestCase):
    """Test A：最小 RawCollectorData 结构正确。"""

    def test_minimal_structure(self):
        data = self.make_collector().collect()
        self.assertIsInstance(data, RawCollectorData)
        self.assertEqual(data.collector, COLLECTOR_NAME)
        self.assertEqual(data.cursor, None)
        self.assertEqual(len(data.items), 3)
        self.assertEqual(data.tweet_ids, SAMPLE_IDS)

    def test_item_identity_comes_from_tweet_id(self):
        data = self.make_collector().collect()
        for item, expected in zip(data.items, SAMPLE_IDS):
            self.assertEqual(item.tweet_id, expected)
            # §6.1：身份字段与 payload 内 FT 的 tweetId 一致。
            self.assertEqual(str(item.payload["tweetId"]), expected)

    def test_collect_is_deterministic(self):
        self.assertEqual(self.make_collector().collect(), self.make_collector().collect())

    def test_empty_jsonl_yields_empty_contract(self):
        (self.data_dir / "bookmarks.jsonl").write_text("", encoding="utf-8")
        data = self.make_collector().collect()
        self.assertEqual(data.items, ())
        self.assertIsNone(data.cursor)

    def test_missing_jsonl_raises_unavailable(self):
        (self.data_dir / "bookmarks.jsonl").unlink()
        with self.assertRaises(UpstreamUnavailableError):
            self.make_collector().collect()

    def test_malformed_jsonl_line_raises_contract_error(self):
        (self.data_dir / "bookmarks.jsonl").write_text("{not json}\n", encoding="utf-8")
        with self.assertRaises(UpstreamContractError):
            self.make_collector().collect()


class PayloadFidelityTests(CollectorTestCase):
    """Test K 的采集侧：FT 专属字段必须原样留在 payload。"""

    def test_payload_keeps_raw_camel_case_and_ft_only_fields(self):
        data = self.make_collector().collect()
        payload = data.items[0].payload
        for key in ("engagement", "ingestedVia", "sortIndex", "mediaObjects", "author"):
            self.assertIn(key, payload)
        # 不得被本项目 snake_case 化或改名。
        for key in ("author_name", "media_objects", "content_hash", "external_links"):
            self.assertNotIn(key, payload)

    def test_payload_is_the_verbatim_upstream_record(self):
        first_line = SAMPLE_JSONL.read_text(encoding="utf-8").splitlines()[0]
        upstream = json.loads(first_line)
        self.assertEqual(self.make_collector().collect().items[0].payload, upstream)


class EnrichmentTests(CollectorTestCase):
    """§8：富化数据来自项目内 ``<raw_dir>/<tweet_id>.json``，缺失即降级。"""

    def test_without_enrichment_all_none(self):
        data = self.make_collector().collect(with_enrichment=False)
        self.assertTrue(all(item.enrichment is None for item in data.items))

    def test_enrichment_block_loaded(self):
        block = _enrichment_block(SAMPLE_IDS[1], articleText="article body")
        self.write_snapshot(SAMPLE_IDS[1], {"enrichment": block})
        data = self.make_collector().collect()
        self.assertIsNone(data.items[0].enrichment)
        self.assertEqual(data.items[1].enrichment, block)

    def test_missing_snapshot_is_not_an_error(self):
        data = self.make_collector().collect()
        self.assertTrue(all(item.enrichment is None for item in data.items))
        self.assertEqual(self.make_collector().last_warnings, ())

    def test_snapshot_with_null_enrichment_is_none(self):
        self.write_snapshot(SAMPLE_IDS[0], {"enrichment": None})
        self.assertIsNone(self.make_collector().collect().items[0].enrichment)

    def test_unknown_extra_keys_are_ignored(self):
        self.write_snapshot(SAMPLE_IDS[0], {"schema_version": 1, "enrichment": {"a": 1}})
        self.assertEqual(self.make_collector().collect().items[0].enrichment, {"a": 1})

    def test_raw_dir_none_disables_enrichment(self):
        collector = FieldTheoryCollector(
            adapter=FieldTheoryAdapter(data_dir=self.data_dir, retries=0), raw_dir=None
        )
        self.assertTrue(all(item.enrichment is None for item in collector.collect().items))


class PerItemResilienceTests(CollectorTestCase):
    """AGENTS.md 最高优先级原则第 7 条：单条失败不得拖垮整批。"""

    def test_malformed_snapshot_is_isolated(self):
        self.write_snapshot(SAMPLE_IDS[1], "{not json}")
        collector = self.make_collector()
        data = collector.collect()
        self.assertEqual(len(data.items), 3)
        self.assertIsNone(data.items[1].enrichment)
        self.assertEqual(len(collector.last_warnings), 1)
        self.assertIn(SAMPLE_IDS[1], collector.last_warnings[0])

    def test_non_object_snapshot_is_isolated(self):
        self.write_snapshot(SAMPLE_IDS[0], "[1, 2, 3]")
        collector = self.make_collector()
        self.assertEqual(len(collector.collect().items), 3)
        self.assertEqual(len(collector.last_warnings), 1)

    def test_bad_enrichment_type_is_isolated(self):
        self.write_snapshot(SAMPLE_IDS[0], {"enrichment": ["not", "an", "object"]})
        collector = self.make_collector()
        self.assertEqual(len(collector.collect().items), 3)
        self.assertEqual(len(collector.last_warnings), 1)

    def test_non_utf8_snapshot_is_isolated(self):
        # 审计 A1 回归：UnicodeDecodeError 曾穿透 collect()，整批被拖垮。
        path = self.raw_dir / f"{SAMPLE_IDS[1]}.json"
        path.write_bytes(b'{"enrichment": {"articleText": "\xff\xfe not utf-8"}}')
        collector = self.make_collector()
        data = collector.collect()
        self.assertEqual(len(data.items), 3)
        self.assertIsNone(data.items[1].enrichment)
        self.assertEqual(len(collector.last_warnings), 1)
        self.assertIn("UnicodeDecodeError", collector.last_warnings[0])

    def test_non_utf8_snapshot_raises_in_strict_mode(self):
        path = self.raw_dir / f"{SAMPLE_IDS[1]}.json"
        path.write_bytes(b'{"enrichment": {"articleText": "\xff\xfe not utf-8"}}')
        with self.assertRaises(UpstreamContractError):
            self.make_collector(strict=True).collect()

    def test_strict_mode_raises_instead(self):
        self.write_snapshot(SAMPLE_IDS[1], "{not json}")
        with self.assertRaises(UpstreamContractError):
            self.make_collector(strict=True).collect()

    def test_warnings_reset_between_calls(self):
        snapshot = self.write_snapshot(SAMPLE_IDS[1], "{not json}")
        collector = self.make_collector()
        collector.collect()
        self.assertEqual(len(collector.last_warnings), 1)
        snapshot.unlink()
        collector.collect()
        self.assertEqual(collector.last_warnings, ())


class ReadOnlyBoundaryTests(unittest.TestCase):
    """验收 G/E：Collector 不写 SQLite/Markdown/Knowledge/Git，也不调用上游 CLI。"""

    FORBIDDEN = (
        "subprocess",
        "sqlite3",
        "shutil.rmtree",
        "write_text",
        "write_bytes",
        ".unlink(",
        "os.remove",
        "os.rename",
        "git ",
    )

    def test_collector_source_has_no_write_or_process_apis(self):
        source = ADAPTER_SOURCE.read_text(encoding="utf-8")
        for token in self.FORBIDDEN:
            self.assertNotIn(token, source, f"collector source must not use {token!r}")

    def test_collector_imports_no_canonical_layer(self):
        # 验收 E：Collector 不依赖 Canonical 层（只检查 import 语句，不检查注释用词）。
        source = ADAPTER_SOURCE.read_text(encoding="utf-8")
        imports = [line for line in source.splitlines() if line.lstrip().startswith(("import ", "from "))]
        joined = "\n".join(imports)
        self.assertNotIn("canonical", joined)
        self.assertNotIn("normalizer", joined)


if __name__ == "__main__":
    unittest.main()
