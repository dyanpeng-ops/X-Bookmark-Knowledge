"""``src/storage/json_projection.py`` 测试（Phase 4 · Step 1）。

覆盖：路径布局、原子写、内容哈希幂等、非法 Canonical 拒绝、路径穿越防护、
单条失败隔离（AGENTS §2.7）、序列化确定性。

全部离线：临时目录、不触网、不写真实 ``data/``、零第三方依赖。
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.canonical.validate import validate_bookmark  # noqa: E402
from src.storage import json_projection  # noqa: E402
from src.storage.json_projection import (  # noqa: E402
    CanonicalJsonError,
    InvalidCanonicalBookmark,
    normalized_path_for,
    write_all_canonical_json,
    write_canonical_json,
)

TWEET_ID = "1900000000000000101"


def bookmark(tweet_id: str = TWEET_ID, **overrides) -> dict:
    """返回一条结构合法的 CanonicalBookmark。"""

    data = {
        "tweet_id": tweet_id,
        "author": "Sample Author",
        "author_id": "100000001",
        "author_username": "sample_author",
        "created_at": "2026-09-14T01:24:21Z",
        "text": "示例正文 with unicode ✓",
        "url": f"https://x.com/sample_author/status/{tweet_id}",
        "conversation_id": tweet_id,
        "source": "x",
        "collector": "fieldtheory",
        "quoted_tweet": None,
        "reply_to": None,
        "thread": None,
        "media": [],
        "external_links": [],
        "x_article": None,
        "collected_at": "2026-09-16T00:00:01Z",
        "updated_at": None,
        "content_hash": "a" * 64,
    }
    data.update(overrides)
    return data


class JsonProjectionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="xbook-storage-json-")
        self.addCleanup(tmp.cleanup)
        self.out_dir = Path(tmp.name) / "normalized"

    def target(self, tweet_id: str = TWEET_ID) -> Path:
        return self.out_dir / f"{tweet_id}.json"

    def read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


class WriteTests(JsonProjectionTestCase):
    def test_writes_canonical_json(self):
        data = bookmark()
        outcome = write_canonical_json(data, self.out_dir)
        self.assertTrue(outcome.written)
        self.assertEqual(outcome.reason, "created")
        self.assertEqual(outcome.path, self.target())
        self.assertTrue(self.target().is_file())
        on_disk = self.read_json(self.target())
        self.assertEqual(on_disk, data)
        validate_bookmark(on_disk)  # 落盘内容仍合法

    def test_creates_parent_directories(self):
        self.assertFalse(self.out_dir.exists())
        write_canonical_json(bookmark(), self.out_dir)
        self.assertTrue(self.out_dir.is_dir())

    def test_serialization_is_deterministic(self):
        write_canonical_json(bookmark(), self.out_dir)
        first = self.target().read_bytes()
        write_canonical_json(bookmark(content_hash="b" * 64), self.out_dir)
        # 同一输入重复序列化 → 逐字节一致（只换内容哈希后差异仅该字段）
        write_canonical_json(bookmark(), self.out_dir)
        self.assertEqual(self.target().read_bytes(), first)

    def test_unicode_is_written_raw(self):
        write_canonical_json(bookmark(), self.out_dir)
        raw = self.target().read_text(encoding="utf-8")
        self.assertIn("示例正文", raw)
        self.assertNotIn("\\u793a", raw)

    def test_file_ends_with_newline(self):
        write_canonical_json(bookmark(), self.out_dir)
        self.assertTrue(self.target().read_text(encoding="utf-8").endswith("\n"))

    def test_no_temp_files_left_behind(self):
        write_canonical_json(bookmark(), self.out_dir)
        leftovers = [p.name for p in self.out_dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class IdempotencyTests(JsonProjectionTestCase):
    def test_unchanged_content_is_not_rewritten(self):
        write_canonical_json(bookmark(), self.out_dir)
        before = os.stat(self.target()).st_mtime_ns
        outcome = write_canonical_json(bookmark(), self.out_dir)
        self.assertFalse(outcome.written)
        self.assertEqual(outcome.reason, "unchanged")
        self.assertEqual(os.stat(self.target()).st_mtime_ns, before)

    def test_changed_content_hash_rewrites(self):
        write_canonical_json(bookmark(), self.out_dir)
        outcome = write_canonical_json(bookmark(text="改了正文", content_hash="c" * 64), self.out_dir)
        self.assertTrue(outcome.written)
        self.assertEqual(outcome.reason, "updated")
        on_disk = self.read_json(self.target())
        self.assertEqual(on_disk["content_hash"], "c" * 64)
        self.assertEqual(on_disk["text"], "改了正文")

    def test_corrupt_existing_file_is_rewritten(self):
        self.target().parent.mkdir(parents=True, exist_ok=True)
        self.target().write_text("{not json", encoding="utf-8")
        outcome = write_canonical_json(bookmark(), self.out_dir)
        self.assertTrue(outcome.written)
        self.assertEqual(outcome.reason, "updated")
        self.assertEqual(self.read_json(self.target()), bookmark())

    def test_existing_file_without_content_hash_is_rewritten(self):
        self.target().parent.mkdir(parents=True, exist_ok=True)
        self.target().write_text(json.dumps({"tweet_id": TWEET_ID}), encoding="utf-8")
        outcome = write_canonical_json(bookmark(), self.out_dir)
        self.assertTrue(outcome.written)
        self.assertEqual(outcome.reason, "updated")


class ValidationTests(JsonProjectionTestCase):
    def test_invalid_bookmark_is_rejected_without_writing(self):
        broken = bookmark()
        del broken["text"]
        with self.assertRaises(InvalidCanonicalBookmark):
            write_canonical_json(broken, self.out_dir)
        self.assertFalse(self.target().exists())

    def test_missing_content_hash_is_rejected(self):
        broken = bookmark()
        del broken["content_hash"]
        with self.assertRaises(InvalidCanonicalBookmark):
            write_canonical_json(broken, self.out_dir)

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(InvalidCanonicalBookmark):
            write_canonical_json(bookmark(engagement={"likeCount": 1}), self.out_dir)

    def test_non_mapping_is_rejected(self):
        with self.assertRaises(InvalidCanonicalBookmark):
            write_canonical_json("not-a-bookmark", self.out_dir)  # type: ignore[arg-type]


class SelfAuditFindingsTests(JsonProjectionTestCase):
    """Step 1 自审发现的两项缺陷回归（审计前自查，2026-10-09）。"""

    def test_written_file_mode_follows_umask_not_0600(self):
        """F1：mkstemp 固定 0600 会让 normalized JSON 变成仅属主可读。"""

        write_canonical_json(bookmark(), self.out_dir)
        umask = os.umask(0)
        os.umask(umask)
        expected = 0o666 & ~umask
        actual = stat.S_IMODE(os.stat(self.target()).st_mode)
        self.assertEqual(oct(actual), oct(expected))
        # 常规 umask（022/002）下必须至少 group/other 可读，不得是 0600
        if umask & 0o077 != 0o077:
            self.assertNotEqual(oct(actual), oct(0o600))

    def test_control_characters_in_tweet_id_are_rejected(self):
        """F2：文档声称拒绝控制字符，实现原先只查 NUL——`1\\n2.json` 曾漏网。"""

        for value in ("1\n2", "1\t2", "1\r2", "1\x1f2", "1\x7f2"):
            with self.subTest(tweet_id=value):
                with self.assertRaises(InvalidCanonicalBookmark):
                    write_canonical_json(bookmark(tweet_id=value), self.out_dir)
        # 被拒后不得留下任何文件（目录可能压根没被创建）
        leftovers = list(self.out_dir.iterdir()) if self.out_dir.exists() else []
        self.assertEqual(leftovers, [])


class AuditFindingRegressionTests(JsonProjectionTestCase):
    """P1/P2：Muse 审计 F-001 与 F-004 的回归用例。"""

    def test_serialization_error_does_not_abort_batch(self):
        """F-001：循环引用曾导致批次中断且后续条目静默丢失。"""

        bad = bookmark("9")
        bad["media"] = [{"type": "photo", "url": "https://a/b.png"}]
        bad["media"][0]["self"] = bad["media"][0]  # 循环引用（validate 不检查 media 内部未知键）

        report = write_all_canonical_json([bookmark("1"), bad, bookmark("3")], self.out_dir)

        self.assertFalse(report.ok)
        self.assertEqual(len(report.outcomes), 2)
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0][0], "9")
        self.assertIn("Circular", report.failures[0][1])
        self.assertTrue((self.out_dir / "1.json").is_file())
        self.assertTrue((self.out_dir / "3.json").is_file())
        self.assertFalse((self.out_dir / "9.json").exists())

    def test_single_serialization_error_raises_domain_error(self):
        bad = bookmark("9")
        bad["media"] = [{"type": "photo", "url": "https://a/b.png"}]
        bad["media"][0]["self"] = bad["media"][0]
        with self.assertRaises(CanonicalJsonError):
            write_canonical_json(bad, self.out_dir)

    def test_windows_reserved_device_names_rejected(self):
        """F-004：`CON.json` 在 Windows 上等同设备名，必须对称拒绝。"""

        for value in ("CON", "con", "Nul", "COM1", "lpt9", "CON.json", "aux.md"):
            with self.subTest(tweet_id=value):
                with self.assertRaises(InvalidCanonicalBookmark):
                    normalized_path_for(self.out_dir, value)
                with self.assertRaises(InvalidCanonicalBookmark):
                    write_canonical_json(bookmark(tweet_id=value), self.out_dir)

    def test_ordinary_ids_still_accepted(self):
        for value in ("1900000000000000101", "1.5", "console", "COM10", "savebox:abc"):
            with self.subTest(tweet_id=value):
                self.assertTrue(normalized_path_for(self.out_dir, value).name.endswith(".json"))


class PathSafetyTests(JsonProjectionTestCase):
    def test_path_for_tweet_id(self):
        self.assertEqual(normalized_path_for(self.out_dir, "123"), self.out_dir / "123.json")

    def test_unsafe_tweet_ids_rejected(self):
        unsafe = (
            "../../etc/passwd",
            "a/b",
            "a\\b",
            "..",
            ".",
            ".hidden",
            "",
            "   ",
            " 123",
            "123 ",
            "12\x003",
        )
        for value in unsafe:
            with self.subTest(tweet_id=value):
                with self.assertRaises(InvalidCanonicalBookmark):
                    normalized_path_for(self.out_dir, value)

    def test_non_string_tweet_id_rejected(self):
        for value in (None, 123, ["1"]):
            with self.subTest(tweet_id=value):
                with self.assertRaises(InvalidCanonicalBookmark):
                    normalized_path_for(self.out_dir, value)  # type: ignore[arg-type]

    def test_unsafe_tweet_id_in_bookmark_rejected(self):
        with self.assertRaises(InvalidCanonicalBookmark):
            write_canonical_json(bookmark(tweet_id="../../escape"), self.out_dir)
        self.assertFalse((self.out_dir.parent / "escape.json").exists())


class AtomicWriteTests(JsonProjectionTestCase):
    def test_failed_replace_leaves_no_partial_file(self):
        with mock.patch.object(json_projection.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                write_canonical_json(bookmark(), self.out_dir)
        self.assertFalse(self.target().exists())
        self.assertEqual([p.name for p in self.out_dir.iterdir()], [])


class BatchTests(JsonProjectionTestCase):
    def test_batch_writes_all_valid_items(self):
        report = write_all_canonical_json(
            [bookmark("1"), bookmark("2"), bookmark("3")], self.out_dir
        )
        self.assertTrue(report.ok)
        self.assertEqual(len(report.outcomes), 3)
        self.assertEqual(report.written, 3)
        self.assertEqual(sorted(p.name for p in self.out_dir.iterdir()),
                         ["1.json", "2.json", "3.json"])

    def test_batch_isolates_invalid_items(self):
        broken = bookmark("2")
        del broken["url"]
        report = write_all_canonical_json(
            [bookmark("1"), broken, bookmark("3")], self.out_dir
        )
        self.assertFalse(report.ok)
        self.assertEqual(len(report.outcomes), 2)
        self.assertEqual(len(report.failures), 1)
        label, message = report.failures[0]
        self.assertEqual(label, "2")
        self.assertIn("InvalidCanonicalBookmark", message)
        self.assertTrue((self.out_dir / "1.json").is_file())
        self.assertTrue((self.out_dir / "3.json").is_file())
        self.assertFalse((self.out_dir / "2.json").exists())

    def test_batch_reports_unchanged(self):
        write_all_canonical_json([bookmark("1")], self.out_dir)
        report = write_all_canonical_json([bookmark("1")], self.out_dir)
        self.assertEqual((report.written, report.unchanged), (0, 1))

    def test_batch_label_for_unidentifiable_item(self):
        report = write_all_canonical_json([{"author": "x"}], self.out_dir)
        self.assertEqual(report.failures[0][0], "index:0")

    def test_batch_continues_after_os_error(self):
        original = json_projection._atomic_write_text
        calls = {"n": 0}

        def flaky(target: Path, text: str) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk full")
            original(target, text)

        with mock.patch.object(json_projection, "_atomic_write_text", side_effect=flaky):
            report = write_all_canonical_json(
                [bookmark("1"), bookmark("2"), bookmark("3")], self.out_dir
            )
        self.assertEqual(len(report.outcomes), 2)
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0][0], "2")


if __name__ == "__main__":
    unittest.main()
