"""``src/storage/markdown_projection.py`` 测试（Phase 4 · Step 2）。

覆盖：路径布局（复用既有 date_parts 约定）、frontmatter（键序 + 可被 YAML 解析 + D2 语义）、
两段式正文（AI 段只放占位、不编造）、**不覆盖内容不同的既有文件**（验收 D）、
批量隔离、路径穿越防护、原子写与确定性。

全部离线：临时目录、不触网、不写真实 knowledge/。
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.markdown_projection import (  # noqa: E402
    AI_ANALYSIS_PLACEHOLDER,
    FRONTMATTER_KEYS,
    MarkdownConflict,
    MarkdownProjectionError,
    markdown_path_for,
    markdown_relative_path,
    render_frontmatter,
    render_markdown,
    write_all_markdown,
    write_markdown,
)

TWEET_ID = "2098040323830407200"


def bookmark(tweet_id: str = TWEET_ID, **overrides) -> dict:
    data = {
        "tweet_id": tweet_id,
        "author": "小码哥",
        "author_id": "1769141715351605248",
        "author_username": "xmglab",
        "created_at": "2026-09-10T13:26:07Z",
        "text": "示例正文 with unicode ✓",
        "url": f"https://x.com/xmglab/status/{tweet_id}",
        "conversation_id": tweet_id,
        "source": "x",
        "collector": "fieldtheory",
        "quoted_tweet": None,
        "reply_to": None,
        "thread": None,
        "media": [],
        "external_links": [],
        "x_article": None,
        "collected_at": "2026-09-16T02:02:41.036Z",
        "updated_at": "2026-09-16T02:02:41.036Z",
        "content_hash": "a" * 64,
    }
    data.update(overrides)
    return data


def split_frontmatter(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n")
    _, rest = text.split("---\n", 1)
    front, body = rest.split("\n---\n", 1)
    return yaml.safe_load(front), body


class PathTests(unittest.TestCase):
    def test_layout(self):
        self.assertEqual(
            markdown_relative_path(bookmark()).as_posix(),
            f"2026/09/20260910-{TWEET_ID}.md",
        )

    def test_missing_created_at_falls_back(self):
        data = bookmark()
        del data["created_at"]
        self.assertEqual(
            markdown_relative_path(data).as_posix(), f"unknown/unknown/unknown-{TWEET_ID}.md"
        )

    def test_unparseable_created_at_falls_back(self):
        self.assertEqual(
            markdown_relative_path(bookmark(created_at="not-a-date")).as_posix(),
            f"unknown/unknown/unknown-{TWEET_ID}.md",
        )

    def test_path_joins_knowledge_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = markdown_path_for(tmp, bookmark())
            self.assertTrue(str(path).startswith(tmp))
            self.assertEqual(path.name, f"20260910-{TWEET_ID}.md")

    def test_path_traversal_rejected(self):
        for bad in ("../escape", "a/b", "..", ".hidden", "CON"):
            with self.subTest(tweet_id=bad):
                with self.assertRaises(Exception):
                    markdown_relative_path(bookmark(tweet_id=bad))


class FrontmatterTests(unittest.TestCase):
    def test_keys_and_order(self):
        front = render_frontmatter(bookmark())
        lines = front.splitlines()
        self.assertEqual(lines[0], "---")
        self.assertEqual(lines[-1], "---")
        keys = [line.split(":", 1)[0] for line in lines[1:-1]]
        self.assertEqual(tuple(keys), FRONTMATTER_KEYS)

    def test_parses_as_yaml(self):
        parsed, _ = split_frontmatter(render_markdown(bookmark()))
        self.assertEqual(parsed["tweet_id"], TWEET_ID)
        self.assertEqual(parsed["source"], "x")
        self.assertEqual(parsed["collector"], "fieldtheory")
        self.assertEqual(parsed["content_hash"], "a" * 64)
        self.assertEqual(parsed["media_count"], 0)
        self.assertEqual(parsed["link_count"], 0)

    def test_author_semantics_follow_decision_d2(self):
        parsed, _ = split_frontmatter(render_markdown(bookmark()))
        self.assertEqual(parsed["author"], "小码哥")          # 显示名
        self.assertEqual(parsed["author_username"], "xmglab")  # handle
        self.assertEqual(parsed["author_id"], "1769141715351605248")

    def test_null_optional_fields(self):
        parsed, _ = split_frontmatter(render_markdown(bookmark(conversation_id=None,
                                                               collected_at=None, updated_at=None)))
        self.assertIsNone(parsed["conversation_id"])
        self.assertIsNone(parsed["collected_at"])
        self.assertIsNone(parsed["updated_at"])

    def test_counts_reflect_canonical_arrays(self):
        data = bookmark(
            media=[{"type": "photo", "url": "https://pbs.twimg.com/media/A.png",
                    "expandedUrl": None, "width": 791, "height": 340}],
            external_links=["https://example.com/a", "https://example.com/b"],
        )
        parsed, _ = split_frontmatter(render_markdown(data))
        self.assertEqual(parsed["media_count"], 1)
        self.assertEqual(parsed["link_count"], 2)

    def test_unicode_not_escaped(self):
        self.assertIn("小码哥", render_frontmatter(bookmark()))

    def test_quote_and_backslash_escaped(self):
        front = render_frontmatter(bookmark(author='He said "hi" \\ bye'))
        parsed = yaml.safe_load(front.split("---\n")[1].rsplit("---", 1)[0])
        self.assertEqual(parsed["author"], 'He said "hi" \\ bye')


class BodyTests(unittest.TestCase):
    def test_two_sections_always_present(self):
        _, body = split_frontmatter(render_markdown(bookmark()))
        self.assertIn("## Original Tweet", body)
        self.assertIn("## AI Analysis", body)

    def test_ai_section_contains_only_placeholder(self):
        _, body = split_frontmatter(render_markdown(bookmark()))
        ai_part = body.split("## AI Analysis", 1)[1]
        self.assertIn(AI_ANALYSIS_PLACEHOLDER, ai_part)
        self.assertLess(len(ai_part.strip()), 120)  # 不得夹带任何"分析内容"

    def test_original_tweet_metadata(self):
        _, body = split_frontmatter(render_markdown(bookmark()))
        self.assertIn("示例正文", body)
        self.assertIn("@xmglab", body)
        self.assertIn("2026-09-10T13:26:07Z", body)
        self.assertIn(f"https://x.com/xmglab/status/{TWEET_ID}", body)

    def test_media_rendered(self):
        data = bookmark(media=[{"type": "photo", "url": "https://pbs.twimg.com/media/A.png",
                                "expandedUrl": None, "width": 791, "height": 340}])
        _, body = split_frontmatter(render_markdown(data))
        self.assertIn("### Media", body)
        self.assertIn("https://pbs.twimg.com/media/A.png", body)
        self.assertIn("791×340", body)

    def test_external_links_rendered(self):
        _, body = split_frontmatter(render_markdown(bookmark(external_links=["https://a.example"])))
        self.assertIn("### External Links", body)
        self.assertIn("https://a.example", body)

    def test_quoted_tweet_rendered(self):
        data = bookmark(quoted_tweet={"tweet_id": "1", "author_handle": "other",
                                      "text": "被引用正文", "url": None})
        _, body = split_frontmatter(render_markdown(data))
        self.assertIn("### Quoted Tweet", body)
        self.assertIn("被引用正文", body)
        self.assertIn("@other", body)

    def test_article_rendered(self):
        data = bookmark(x_article={"title": "标题", "text": "文章正文", "site": "x.com"})
        _, body = split_frontmatter(render_markdown(data))
        self.assertIn("### Article", body)
        self.assertIn("**标题**", body)
        self.assertIn("文章正文", body)

    def test_optional_sections_absent_when_empty(self):
        _, body = split_frontmatter(render_markdown(bookmark()))
        for section in ("### Media", "### External Links", "### Quoted Tweet", "### Article"):
            self.assertNotIn(section, body)

    def test_deterministic(self):
        self.assertEqual(render_markdown(bookmark()), render_markdown(bookmark()))

    def test_missing_required_field_raises(self):
        for field in ("author", "author_username", "author_id", "created_at", "content_hash"):
            with self.subTest(field=field):
                data = bookmark()
                del data[field]
                with self.assertRaises((MarkdownProjectionError, Exception)):
                    render_markdown(data)


class WriteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="xbook-md-")
        self.addCleanup(tmp.cleanup)
        self.knowledge = Path(tmp.name) / "X-Bookmarks"

    def target(self, data=None) -> Path:
        return markdown_path_for(self.knowledge, data or bookmark())

    def test_creates_file(self):
        outcome = write_markdown(bookmark(), self.knowledge)
        self.assertTrue(outcome.written)
        self.assertEqual(outcome.reason, "created")
        self.assertTrue(self.target().is_file())
        parsed, _ = split_frontmatter(self.target().read_text(encoding="utf-8"))
        self.assertEqual(parsed["tweet_id"], TWEET_ID)

    def test_identical_rewrite_is_skipped(self):
        write_markdown(bookmark(), self.knowledge)
        before = os.stat(self.target()).st_mtime_ns
        outcome = write_markdown(bookmark(), self.knowledge)
        self.assertFalse(outcome.written)
        self.assertEqual(outcome.reason, "unchanged")
        self.assertEqual(os.stat(self.target()).st_mtime_ns, before)

    def test_conflicting_content_is_not_overwritten(self):
        path = self.target()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("人工维护的内容，不可被覆盖\n", encoding="utf-8")
        with self.assertRaises(MarkdownConflict):
            write_markdown(bookmark(), self.knowledge)
        self.assertEqual(path.read_text(encoding="utf-8"), "人工维护的内容，不可被覆盖\n")

    def test_overwrite_true_rewrites(self):
        path = self.target()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old\n", encoding="utf-8")
        outcome = write_markdown(bookmark(), self.knowledge, overwrite=True)
        self.assertTrue(outcome.written)
        self.assertEqual(outcome.reason, "updated")
        self.assertIn("## Original Tweet", path.read_text(encoding="utf-8"))

    def test_file_mode_follows_umask(self):
        write_markdown(bookmark(), self.knowledge)
        umask = os.umask(0)
        os.umask(umask)
        self.assertEqual(oct(stat.S_IMODE(os.stat(self.target()).st_mode)), oct(0o666 & ~umask))

    def test_no_temp_files_left(self):
        write_markdown(bookmark(), self.knowledge)
        leftovers = [p.name for p in self.target().parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_batch_isolates_conflict_and_error(self):
        path = self.target()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("人工内容\n", encoding="utf-8")
        broken = bookmark("1900000000000000102")
        del broken["author"]
        report = write_all_markdown(
            [bookmark(), broken, bookmark("1900000000000000103")], self.knowledge
        )
        self.assertFalse(report.ok)
        self.assertEqual(report.conflicts, 1)
        self.assertEqual(len(report.failures), 2)  # 1 冲突 + 1 错误
        self.assertTrue(
            markdown_path_for(self.knowledge, bookmark("1900000000000000103")).is_file()
        )

    def test_batch_all_good(self):
        report = write_all_markdown(
            [bookmark("1"), bookmark("2"), bookmark("3")], self.knowledge
        )
        self.assertTrue(report.ok)
        self.assertEqual(report.written, 3)


if __name__ == "__main__":
    unittest.main()
