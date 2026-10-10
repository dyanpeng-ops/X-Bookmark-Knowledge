"""`src/markdown` 的验收测试（Phase 7）。

覆盖范围
--------
* 渲染（`render_markdown`）：frontmatter、各段落、占位、转义。
* 路径（`relative_output_path`）：年份/月份/文件名、缺日期回退。
* 写盘（`MarkdownWriter`）：首写、内容不变跳过、内容不同拒绝覆盖、单条失败隔离、状态推进。
* CLI `process`：端到端（离线桩）——M3 的核心断言（第二次不再产生新文件）。

运行方式（项目根目录）::

    .venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import EXIT_FAILURE, EXIT_OK, main as cli_main  # noqa: E402
from src.database import connect  # noqa: E402
from src.markdown import (  # noqa: E402
    MarkdownWriter,
    RenderOptions,
    build_frontmatter,
    relative_output_path,
    render_markdown,
)

STUB = PROJECT_ROOT / "tests" / "support" / "stub_fieldtheory.py"

POSTED_AT = "Mon Sep 14 01:24:21 +0000 2026"
UPMAP = {
    "tweetId": "1900000000000000101",
    "url": "https://x.com/sample/status/1900000000000000101",
    "text": "第一行\n第二行",
    "authorHandle": "sample",
    "authorName": "Sample Author",
    "authorProfileImageUrl": "https://pbs.twimg.com/profile_images/1/x.jpg",
    "postedAt": POSTED_AT,
    "bookmarkedAt": None,
    "syncedAt": "2026-09-16T00:00:01.000Z",
    "conversationId": "1900000000000000101",
    "language": "zh",
    "possiblySensitive": False,
    "engagement": {"likeCount": 10, "repostCount": 2, "replyCount": 1, "quoteCount": 0, "bookmarkCount": 5},
    "media": ["https://pbs.twimg.com/media/AAA.png"],
    "mediaObjects": (),
    "links": ["https://example.com/a", "https://example.com/a"],
    "tags": ["tag1"],
    "ingestedVia": "graphql",
    "sortIndex": "1",
    "author": {"id": "1", "handle": "sample", "name": "Sample Author"},
}
ENRICH = {
    "articleTitle": "测试文章",
    "articleText": "这是文章正文。",
    "primaryCategory": "tools",
    "folderNames": ["A", "B"],
}


def render(overrides=None, enrich=None):
    up = dict(UPMAP)
    up.update(overrides or {})
    return render_markdown(up, enrich, RenderOptions())


class RenderTests(unittest.TestCase):
    def test_frontmatter_has_required_keys_in_order(self):
        text = render()
        fm = text.split("---\n", 1)[1].split("\n---")[0]
        lines = [ln for ln in fm.split("\n") if ln.strip()]
        keys = [ln.split(":", 1)[0].strip() for ln in lines]
        self.assertEqual(
            keys,
            [
                "tweet_id",
                "url",
                "author_handle",
                "author_name",
                "created_at",
                "language",
                "media_count",
                "link_count",
                "engagement",
                "tags",
                "primary_category",
                "folder_names",
                "source",
            ],
        )

    def test_frontmatter_values(self):
        fm = build_frontmatter(UPMAP, ENRICH)
        self.assertEqual(fm["tweet_id"], "1900000000000000101")
        self.assertEqual(fm["created_at"], "2026-09-14T01:24:21Z")
        self.assertEqual(fm["media_count"], 1)
        self.assertEqual(fm["link_count"], 2)
        self.assertEqual(fm["primary_category"], "tools")
        self.assertEqual(fm["folder_names"], ["A", "B"])
        self.assertEqual(fm["tags"], ["tag1"])

    def test_sections_are_rendered(self):
        text = render()
        for section in ("## tweet", "## media", "## external_links", "## metadata", "## source"):
            self.assertIn(section, text)
        self.assertIn("> 第一行", text)
        self.assertIn("> 第二行", text)
        self.assertIn("https://pbs.twimg.com/media/AAA.png", text)
        self.assertIn("https://example.com/a", text)

    def test_article_section_only_when_enrichment_present(self):
        self.assertIn("_未展开文章_", render(enrich=None))
        text = render(enrich=ENRICH)
        self.assertIn("## 文章标题：测试文章", text)
        self.assertIn("这是文章正文。", text)

    def test_media_placeholder_when_none(self):
        self.assertIn("_无媒体_", render({"media": []}))

    def test_links_are_deduplicated_in_section(self):
        text = render()
        self.assertEqual(text.count("- https://example.com/a"), 1)

    def test_pipe_is_escaped(self):
        text = render({"text": "a | b"})
        self.assertIn("a \\| b", text)

    def test_thread_section_renders_quoted_tweet(self):
        enrich = dict(ENRICH)
        enrich["quotedTweet"] = {
            "tweetId": "1900000000000000999",
            "text": "被引用的内容。",
            "authorHandle": "quoted_author",
        }
        text = render(enrich=enrich)
        self.assertIn("## thread", text)
        self.assertIn("@quoted_author", text)
        self.assertIn("`1900000000000000999`", text)
        self.assertIn("> 被引用的内容。", text)

    def test_thread_section_placeholder_when_missing(self):
        self.assertIn("_无引用推文_", render(enrich=None))
        self.assertIn("_无引用推文_", render(enrich=dict(ENRICH, quotedTweet=None)))

    def test_ai_analysis_section_is_placeholder(self):
        text = render()
        self.assertIn("## ai_analysis", text)
        self.assertIn("_预留段：AI 分析将于 Phase 11 生成", text)


class PathTests(unittest.TestCase):
    def test_year_month_filename(self):
        rel = relative_output_path("123", "2026-09-14T01:24:21Z", RenderOptions())
        self.assertEqual(rel, Path("2026") / "09" / "20260914-123.md")

    def test_unknown_date_falls_back(self):
        rel = relative_output_path("123", None, RenderOptions())
        self.assertEqual(rel, Path("unknown") / "unknown" / "unknown-123.md")

    def test_custom_pattern(self):
        rel = relative_output_path(
            "123", "2026-09-14T01:24:21Z", RenderOptions(filename_pattern="note-{tweet_id}.md")
        )
        self.assertEqual(rel, Path("2026") / "09" / "note-123.md")


class WriterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-md-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.knowledge = self.tmp / "knowledge"
        self.knowledge.mkdir()
        self.raw = self.tmp / "data" / "raw"
        self.raw.mkdir(parents=True)

    def _archive(self, tweet_id, up=None, enrich=None):
        payload = {
            "schema_version": 1,
            "tweet_id": tweet_id,
            "source": "fieldtheory",
            "upstream": up or dict(UPMAP),
            "enrichment": enrich,
        }
        (self.raw / f"{tweet_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def _writer(self, options=None, status_updater=None):
        return MarkdownWriter(
            self.knowledge,
            options=options or RenderOptions(),
            status_updater=status_updater,
        )

    def test_write_creates_file_and_records_path(self):
        self._archive("1")
        calls = []
        writer = self._writer(status_updater=lambda i, s, p: calls.append((i, s, p)))
        stats = writer.run(["1"])
        self.assertEqual(stats.written, 1)
        self.assertEqual(stats.failed, 0)
        self.assertTrue((self.knowledge / "2026" / "09" / "20260914-1.md").is_file())
        self.assertEqual(calls[0][0], "1")
        self.assertEqual(calls[0][1], "PROCESSED")
        self.assertIsNotNone(calls[0][2])

    def test_second_run_creates_no_new_files(self):
        self._archive("1")
        writer = self._writer()
        first = writer.run(["1"])
        second = writer.run(["1"])
        self.assertEqual(first.written, 1)
        self.assertEqual(second.written, 0)
        self.assertEqual(second.unchanged, 1)
        files = sorted(p.name for p in (self.knowledge / "2026" / "09").glob("*.md"))
        self.assertEqual(files, ["20260914-1.md"])

    def test_different_content_refuses_overwrite(self):
        self._archive("1", up=dict(UPMAP, text="原版"))
        self._writer().run(["1"])
        self._archive("1", up=dict(UPMAP, text="改版"))
        stats = self._writer().run(["1"])
        self.assertEqual(stats.conflicts, 1)
        self.assertEqual(stats.written, 0)
        content = (self.knowledge / "2026" / "09" / "20260914-1.md").read_text(encoding="utf-8")
        self.assertIn("原版", content)

    def test_overwrite_allowed_flag(self):
        self._archive("1", up=dict(UPMAP, text="原版"))
        self._writer().run(["1"])
        self._archive("1", up=dict(UPMAP, text="改版"))
        stats = self._writer(options=RenderOptions(overwrite_existing=True)).run(["1"])
        self.assertEqual(stats.written, 1)
        content = (self.knowledge / "2026" / "09" / "20260914-1.md").read_text(encoding="utf-8")
        self.assertIn("改版", content)

    def test_missing_archive_fails_only_that_record(self):
        self._archive("1")
        stats = self._writer().run(["1", "missing"])
        self.assertEqual(stats.written, 1)
        self.assertEqual(stats.failed, 1)
        self.assertEqual(stats.errors[0][0], "missing")

    def test_default_loader_reads_real_archive_layout(self):
        self._archive("7", up=dict(UPMAP, tweetId="7", url="https://x.com/sample/status/7"))
        writer = MarkdownWriter(self.knowledge)  # 无注入 loader
        stats = writer.run(["7"])
        self.assertEqual(stats.written, 1)


class CliProcessTests(unittest.TestCase):
    """`python -m src.cli process` 端到端（离线桩 + 临时目录）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-cliproc-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.config = self.tmp / "config.yaml"
        self.upstream = self.tmp / "upstream"
        self.config.write_text(
            "version: 1\n"
            f"paths:\n  project_root: '{self.tmp.as_posix()}'\n"
            "  data_dir: 'data'\n  raw_dir: 'data/raw'\n  state_dir: 'data/state'\n"
            "  log_dir: 'data/logs'\n  knowledge_dir: 'knowledge/X-Bookmarks'\n"
            "collector:\n"
            f"  executable: '{sys.executable}'\n  executable_args: ['-B', '{STUB.as_posix()}']\n"
            f"  upstream_data_dir: '{self.upstream.as_posix()}'\n"
            "  auth:\n    method: 'firefox'\n    browser: 'firefox'\n"
            "markdown:\n"
            "  filename_pattern: '{yyyymmdd}-{tweet_id}.md'\n  frontmatter: true\n"
            "  include_sections: [tweet, media, article, external_links, metadata, source]\n"
            "  overwrite_existing: false\n"
            "logging:\n  level: 'INFO'\n  file_per_day: true\n  console: false\n",
            encoding="utf-8",
        )

    def _run(self, *argv):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(["--config", str(self.config), *argv])
        return code, out.getvalue(), err.getvalue()

    def _conn(self):
        return connect(self.tmp / "data" / "state" / "state.db")

    def test_process_after_sync_generates_markdown_and_advances_state(self):
        self._run("sync")
        conn = self._conn()
        collected = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE status='COLLECTED'").fetchone()[0]
        conn.close()
        self.assertEqual(collected, 3)

        code, out, _ = self._run("process")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("written       : 3", out)

        conn = self._conn()
        processed = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE status='PROCESSED'").fetchone()[0]
        with_path = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE markdown_path IS NOT NULL").fetchone()[0]
        conn.close()
        self.assertEqual(processed, 3)
        self.assertEqual(with_path, 3)
        # 布局按发帖年月分目录：fixture 中 101/103 在 9 月、102 在 6 月。
        md_files = sorted(p.name for p in (self.tmp / "knowledge" / "X-Bookmarks").rglob("*.md"))
        self.assertEqual(len(md_files), 3)
        self.assertTrue(
            (self.tmp / "knowledge" / "X-Bookmarks" / "2026" / "06" / "20260620-1900000000000000102.md").is_file()
        )

    def test_second_process_run_creates_no_new_files(self):
        """M3：第二次运行不产生新文件、不重写。"""

        self._run("sync")
        self._run("process")
        root = self.tmp / "knowledge" / "X-Bookmarks"
        first_files = sorted(str(p.relative_to(root)) for p in root.rglob("*.md"))
        code, out, _ = self._run("process")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("written       : 0", out)
        self.assertIn("unchanged     : 3", out)
        second_files = sorted(str(p.relative_to(root)) for p in root.rglob("*.md"))
        self.assertEqual(first_files, second_files)

    def test_process_missing_archive_fails_alone(self):
        self._run("sync")
        self._run("process")
        (self.tmp / "data" / "raw" / "1900000000000000101.json").unlink()
        conn = self._conn()
        conn.execute("UPDATE bookmarks SET status='COLLECTED' WHERE tweet_id='1900000000000000101'")
        conn.commit()
        conn.close()
        code, out, err = self._run("process")
        self.assertEqual(code, EXIT_FAILURE)
        self.assertIn("failed        : 1", out)
        self.assertIn("[fail]", err)

    def test_tweet_id_filter(self):
        self._run("sync")
        code, out, _ = self._run("process", "--tweet-id", "1900000000000000102")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("attempted     : 1", out)
        self.assertIn("written       : 1", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()