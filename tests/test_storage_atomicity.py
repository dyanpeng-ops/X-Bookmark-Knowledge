"""Phase 4 原子写的**崩溃安全**测试（此前完全未覆盖）。

原子写的承诺是："要么完整落盘，要么什么都没有"——即：
* 写入过程中失败（`os.replace` / `os.fsync` 抛错，模拟磁盘满、权限问题、进程被杀）；
* 不得留下**半个文件**；
* 不得破坏**既有文件**（内容仍是旧的完整版本）；
* 不得留下临时文件残骸。

用 `unittest.mock.patch` 在目标函数内部注入失败，逐条验证上述不变式。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage import json_projection, markdown_projection  # noqa: E402
from src.storage.json_projection import write_canonical_json  # noqa: E402
from src.storage.markdown_projection import write_markdown  # noqa: E402


def bookmark(tweet_id: str = "1900000000000000101", **overrides) -> dict:
    data = {
        "tweet_id": tweet_id, "author": "Sample Author", "author_id": "100000001",
        "author_username": "sample_author", "created_at": "2026-09-10T13:26:07Z",
        "text": "正文", "url": f"https://x.com/sample_author/status/{tweet_id}",
        "conversation_id": tweet_id, "source": "x", "collector": "fieldtheory",
        "quoted_tweet": None, "reply_to": None, "thread": None, "media": [],
        "external_links": [], "x_article": None, "collected_at": "2026-09-16T02:02:41.036Z",
        "updated_at": None, "content_hash": "a" * 64,
    }
    data.update(overrides)
    return data


def temp_files(directory: Path) -> list[str]:
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


class JsonAtomicityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="xbk-atomic-")
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "normalized"

    def test_failed_replace_leaves_no_partial_file(self):
        """os.replace 失败 → 目标不存在，且不留临时文件。"""

        with mock.patch.object(json_projection.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_canonical_json(bookmark(), self.out)
        self.assertFalse((self.out / "1900000000000000101.json").exists())
        self.assertEqual(temp_files(self.out), [])

    def test_failed_replace_keeps_existing_file_intact(self):
        write_canonical_json(bookmark(content_hash="a" * 64), self.out)
        target = self.out / "1900000000000000101.json"
        original = target.read_text(encoding="utf-8")

        with mock.patch.object(json_projection.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_canonical_json(bookmark(content_hash="b" * 64, text="新内容"), self.out)

        self.assertEqual(target.read_text(encoding="utf-8"), original)   # 旧内容完整
        self.assertEqual(temp_files(self.out), [])

    def test_failed_fsync_leaves_no_partial_file(self):
        with mock.patch.object(json_projection.os, "fsync", side_effect=OSError("io error")):
            with self.assertRaises(OSError):
                write_canonical_json(bookmark(), self.out)
        self.assertFalse((self.out / "1900000000000000101.json").exists())
        self.assertEqual(temp_files(self.out), [])

    def test_batch_isolates_write_failure(self):
        """批量入口：一条写入失败不得影响其它条目（AGENTS §2.7）。"""

        real_replace = os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:                    # 第二条失败
                raise OSError("disk full")
            return real_replace(src, dst, *args, **kwargs)

        with mock.patch.object(json_projection.os, "replace", side_effect=flaky_replace):
            report = json_projection.write_all_canonical_json(
                [bookmark("1900000000000000101"), bookmark("1900000000000000102"),
                 bookmark("1900000000000000103")], self.out)

        self.assertFalse(report.ok)
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(len(report.outcomes), 2)                 # 另两条成功
        written = sorted(p.name for p in self.out.glob("*.json"))
        self.assertEqual(len(written), 2)
        self.assertEqual(temp_files(self.out), [])


class MarkdownAtomicityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="xbk-atomic-md-")
        self.addCleanup(self._tmp.cleanup)
        self.knowledge = Path(self._tmp.name) / "X-Bookmarks"

    def target(self) -> Path:
        return markdown_projection.markdown_path_for(self.knowledge, bookmark())

    def test_failed_replace_leaves_no_partial_file(self):
        with mock.patch.object(markdown_projection.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_markdown(bookmark(), self.knowledge)
        self.assertFalse(self.target().exists())
        self.assertEqual(temp_files(self.target().parent), [])

    def test_failed_fsync_leaves_no_partial_file(self):
        with mock.patch.object(markdown_projection.os, "fsync", side_effect=OSError("io error")):
            with self.assertRaises(OSError):
                write_markdown(bookmark(), self.knowledge)
        self.assertFalse(self.target().exists())
        self.assertEqual(temp_files(self.target().parent), [])

    def test_failed_overwrite_keeps_previous_markdown(self):
        write_markdown(bookmark(), self.knowledge)
        target = self.target()
        original = target.read_text(encoding="utf-8")

        with mock.patch.object(markdown_projection.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_markdown(bookmark(text="新正文"), self.knowledge, overwrite=True)

        self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertEqual(temp_files(target.parent), [])


if __name__ == "__main__":
    unittest.main()
