"""`src/external` 的验收测试（Phase 9）。

覆盖范围
--------
* 抓取封装：逐跳重定向（含相对 Location）、超时/连接失败的重试与退避、404 不重试、
  5xx/429 重试、体积上限（`Content-Length` 与截断）、scheme 白名单、编码探测（头部/meta/BOM）。
* handler：标题优先级、meta 摘要、script/nav 剥离、块级换行、canonical、GitHub 标题策略、
  按内容类型选择 handler（未实现的 `pdf` → 跳过）。
* resolver：写盘布局与内容、二次运行**不联网**、`--force`、正文被删后重抓、失败保留原始 URL、
  单条隔离、跳过规则（scheme / skip_domains / handler 禁用 / max_links_per_tweet / 尝试上限）、
  dry-run、正文文件不含时间戳（内容幂等）。
* Markdown：`## external_links` 富化渲染与 Phase 7 回退、链接文字转义。
* CLI 端到端（离线桩 + 临时目录 + 注入 fake transport）：`sync → links → process` 全链路、
  幂等、失败退出码、`--dry-run`、`external.enabled=false`、`sync` 不重置外链状态。

离线保证：本文件**不打开任何 socket**——fetcher 的传输层与 CLI 的抓取器都被替换为
脚本化假实现（`tests/README.md` 的"网络层必须可注入 fake fetcher"）。

运行方式（项目根目录）::

    .venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import importlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import EXIT_FAILURE, EXIT_OK, main as cli_main  # noqa: E402
from src.config import ExternalOptions, load_external_options  # noqa: E402
from src.database import connect  # noqa: E402
from src.external import (  # noqa: E402
    ContentHandlerError,
    FetchedPage,
    HttpFetcher,
    HttpStatusError,
    LinkResolver,
    LinkTarget,
    LinkUpdate,
    NoHandlerError,
    PageTooLargeError,
    TooManyRedirectsError,
    TransportFailure,
    TransportResponse,
    TransportTimeoutError,
    UnsupportedSchemeError,
    build_handlers,
    decode_body,
    link_dir_for,
    link_key_for,
    render_link_markdown,
    select_handler,
    skip_domain_match,
)
from src.external.handlers import GitHubHandler, WebHandler, parse_html  # noqa: E402
from src.markdown import MarkdownWriter, RenderOptions, render_markdown  # noqa: E402

STUB = PROJECT_ROOT / "tests" / "support" / "stub_fieldtheory.py"

ARTICLE_URL = "https://example.com/sample-a"
X_ARTICLE_URL = "http://x.com/i/article/1900000000000000002"
PHOTO_TWEET = "1900000000000000101"

HTML_PAGE = (
    b"<html><head><title>Sample A | Example</title>"
    b'<meta name="description" content="Sample description.">'
    b'<link rel="canonical" href="https://example.com/sample-a">'
    b"</head><body><nav>nav noise</nav><script>var x=1;</script>"
    b"<h1>Hello</h1><p>First paragraph.</p><p>Second   paragraph.</p>"
    b"<footer>footer noise</footer></body></html>"
)


def response(
    url: str,
    status: int = 200,
    *,
    body: bytes = HTML_PAGE,
    content_type: str = "text/html; charset=utf-8",
    headers: dict[str, str] | None = None,
    truncated: bool = False,
    location: str | None = None,
) -> TransportResponse:
    """构造传输层响应。"""

    merged = {"Content-Type": content_type, "Content-Length": str(len(body))}
    if location:
        merged["Location"] = location
    merged.update(headers or {})
    return TransportResponse(
        url=url, status_code=status, headers=merged, body=body, truncated=truncated
    )


class FakeTransport:
    """脚本化传输层：记录每次调用；同一 URL 的最后一个响应可被重复取用（重试用）。"""

    def __init__(self, script: dict[str, list[object]]) -> None:
        self.script = {key: list(value) for key, value in script.items()}
        self.calls: list[tuple[str, float, int, str]] = []

    def __call__(
        self, url: str, *, timeout: float, max_bytes: int, user_agent: str
    ) -> TransportResponse:
        self.calls.append((url, timeout, max_bytes, user_agent))
        queue = self.script.get(url)
        if not queue:
            raise AssertionError(f"unexpected transport call: {url}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[return-value]

    @property
    def urls(self) -> list[str]:
        return [call[0] for call in self.calls]


class RecordingSleeper:
    """记录退避/间隔时长，绝不真的 sleep。"""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def page(
    url: str,
    *,
    final_url: str | None = None,
    body: bytes = HTML_PAGE,
    content_type: str | None = "text/html; charset=utf-8",
) -> FetchedPage:
    """构造 :class:`FetchedPage`（resolver 测试用）。"""

    return FetchedPage(
        url=url,
        final_url=final_url or url,
        status_code=200,
        content_type=content_type,
        content_length=len(body),
        body=body,
    )


class ScriptedFetcher:
    """按 URL 返回页面或抛错的 fetcher（resolver 测试用，记录调用次数）。"""

    def __init__(self, script: dict[str, object]) -> None:
        self.script = dict(script)
        self.calls: list[str] = []

    def __call__(self, url: str) -> FetchedPage:
        self.calls.append(url)
        item = self.script.get(url)
        if item is None:
            raise AssertionError(f"unexpected fetch: {url}")
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[return-value]


class FetchWrapperTests(unittest.TestCase):
    """抓取封装：超时、重试、退避、重定向、体积上限、scheme 白名单。"""

    def fetcher(
        self, script: dict[str, list[object]], **overrides
    ) -> tuple[HttpFetcher, FakeTransport, RecordingSleeper]:
        transport = FakeTransport(script)
        sleeper = RecordingSleeper()
        options: dict[str, object] = {
            "timeout_seconds": 20.0,
            "retries": 2,
            "backoff_seconds": 3.0,
            "max_bytes": 1024,
            "max_redirects": 5,
            "user_agent": "test-agent/1.0",
            "transport": transport,
            "sleeper": sleeper,
        }
        options.update(overrides)
        return HttpFetcher(**options), transport, sleeper  # type: ignore[arg-type]

    def test_success_returns_page_and_passes_request_options(self):
        fetcher, transport, _ = self.fetcher({ARTICLE_URL: [response(ARTICLE_URL)]})
        result = fetcher(ARTICLE_URL)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.final_url, ARTICLE_URL)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.body, HTML_PAGE)
        self.assertEqual(transport.urls, [ARTICLE_URL])
        self.assertEqual(transport.calls[0][1], 20.0)
        self.assertEqual(transport.calls[0][2], 1024)
        self.assertEqual(transport.calls[0][3], "test-agent/1.0")

    def test_timeout_then_success_is_retried_with_backoff(self):
        fetcher, transport, sleeper = self.fetcher(
            {
                ARTICLE_URL: [
                    TransportTimeoutError("timeout after 20s"),
                    response(ARTICLE_URL),
                ]
            }
        )
        result = fetcher(ARTICLE_URL)

        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(sleeper.delays, [3.0])

    def test_persistent_timeout_raises_after_retries_and_records_attempts(self):
        fetcher, transport, sleeper = self.fetcher(
            {ARTICLE_URL: [TransportTimeoutError("timeout after 20s")]}
        )
        with self.assertRaises(TransportTimeoutError) as ctx:
            fetcher(ARTICLE_URL)

        self.assertEqual(ctx.exception.attempts, 3)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(sleeper.delays, [3.0, 6.0])

    def test_connection_failure_is_retried(self):
        fetcher, transport, _ = self.fetcher(
            {
                ARTICLE_URL: [
                    TransportFailure("connection failed: refused"),
                    response(ARTICLE_URL),
                ]
            }
        )
        self.assertEqual(fetcher(ARTICLE_URL).attempts, 2)
        self.assertEqual(len(transport.calls), 2)

    def test_server_error_is_retried_then_succeeds(self):
        fetcher, transport, _ = self.fetcher(
            {ARTICLE_URL: [response(ARTICLE_URL, status=503), response(ARTICLE_URL)]}
        )
        self.assertEqual(fetcher(ARTICLE_URL).attempts, 2)
        self.assertEqual(len(transport.calls), 2)

    def test_not_found_is_not_retried(self):
        fetcher, transport, sleeper = self.fetcher(
            {ARTICLE_URL: [response(ARTICLE_URL, status=404, body=b"missing")]}
        )
        with self.assertRaises(HttpStatusError) as ctx:
            fetcher(ARTICLE_URL)

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(sleeper.delays, [])

    def test_rate_limited_is_retried_then_raises(self):
        fetcher, transport, _ = self.fetcher({ARTICLE_URL: [response(ARTICLE_URL, status=429)]})
        with self.assertRaises(HttpStatusError) as ctx:
            fetcher(ARTICLE_URL)

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(len(transport.calls), 3)

    def test_retries_can_be_disabled(self):
        fetcher, transport, _ = self.fetcher(
            {ARTICLE_URL: [TransportTimeoutError("timeout after 20s")]}, retries=0
        )
        with self.assertRaises(TransportTimeoutError):
            fetcher(ARTICLE_URL)
        self.assertEqual(len(transport.calls), 1)

    def test_redirects_are_followed_hop_by_hop(self):
        final = "https://example.com/final"
        fetcher, transport, _ = self.fetcher(
            {
                ARTICLE_URL: [response(ARTICLE_URL, status=302, location="/final")],
                final: [response(final)],
            }
        )
        result = fetcher(ARTICLE_URL)

        self.assertEqual(result.final_url, final)
        self.assertEqual(result.redirects, (ARTICLE_URL,))
        self.assertEqual(transport.urls, [ARTICLE_URL, final])

    def test_redirect_chain_records_every_hop(self):
        second = "https://example.com/second"
        third = "https://example.com/third"
        fetcher, _, _ = self.fetcher(
            {
                ARTICLE_URL: [response(ARTICLE_URL, status=301, location=second)],
                second: [response(second, status=307, location=third)],
                third: [response(third)],
            }
        )
        result = fetcher(ARTICLE_URL)

        self.assertEqual(result.final_url, third)
        self.assertEqual(result.redirects, (ARTICLE_URL, second))

    def test_too_many_redirects_is_reported(self):
        other = "https://example.com/loop"
        fetcher, transport, _ = self.fetcher(
            {
                ARTICLE_URL: [response(ARTICLE_URL, status=302, location=other)],
                other: [response(other, status=302, location=ARTICLE_URL)],
            },
            max_redirects=1,
        )
        with self.assertRaises(TooManyRedirectsError):
            fetcher(ARTICLE_URL)
        self.assertEqual(len(transport.calls), 2)

    def test_redirect_without_location_fails(self):
        fetcher, _, _ = self.fetcher(
            {ARTICLE_URL: [response(ARTICLE_URL, status=302, location=None)]}
        )
        with self.assertRaises(TooManyRedirectsError):
            fetcher(ARTICLE_URL)

    def test_redirect_to_unsupported_scheme_fails(self):
        fetcher, _, _ = self.fetcher(
            {ARTICLE_URL: [response(ARTICLE_URL, status=302, location="file:///C:/secret.txt")]}
        )
        with self.assertRaises(UnsupportedSchemeError):
            fetcher(ARTICLE_URL)

    def test_non_http_scheme_never_touches_the_network(self):
        fetcher, transport, _ = self.fetcher({})
        with self.assertRaises(UnsupportedSchemeError):
            fetcher("mailto:someone@example.com")
        self.assertEqual(transport.calls, [])

    def test_page_over_size_limit_fails(self):
        fetcher, _, _ = self.fetcher(
            {ARTICLE_URL: [response(ARTICLE_URL, truncated=True, body=b"")]}
        )
        with self.assertRaises(PageTooLargeError) as ctx:
            fetcher(ARTICLE_URL)
        self.assertIn("max_bytes", str(ctx.exception))


class EncodingTests(unittest.TestCase):
    """编码探测：响应头 charset → BOM → `<meta charset>` → UTF-8 → 替换式解码。"""

    def test_header_charset_wins(self):
        decoded = decode_body("中文标题".encode("gbk"), "text/html; charset=GBK")
        self.assertEqual(decoded.text, "中文标题")
        self.assertEqual(decoded.encoding, "gbk")

    def test_meta_charset_is_used_when_header_has_none(self):
        body = '<meta charset="gbk"><p>中文</p>'.encode("gbk")
        decoded = decode_body(body, "text/html")
        self.assertEqual(decoded.text, '<meta charset="gbk"><p>中文</p>')
        self.assertEqual(decoded.encoding, "gbk")

    def test_bom_is_detected(self):
        decoded = decode_body("\ufeffhello".encode("utf-8"), None)
        self.assertEqual(decoded.text, "hello")
        self.assertEqual(decoded.encoding, "utf-8-sig")

    def test_unknown_charset_falls_back_to_utf8(self):
        decoded = decode_body("ok".encode("utf-8"), "text/html; charset=nonsense-9000")
        self.assertEqual(decoded.text, "ok")
        self.assertEqual(decoded.encoding, "utf-8")

    def test_undecodable_bytes_are_replaced_not_raised(self):
        decoded = decode_body(b"\xff\xfe\xff", "text/html; charset=utf-8")
        self.assertEqual(decoded.encoding, "utf-8")
        self.assertIn("\ufffd", decoded.text)


class HandlerTests(unittest.TestCase):
    """正文抽取：HTML 结构、标题优先级、GitHub 策略、handler 选择。"""

    def test_html_extraction_drops_scripts_and_navigation(self):
        document = parse_html(HTML_PAGE.decode("utf-8"))

        self.assertEqual(document.title, "Sample A | Example")
        self.assertEqual(document.description, "Sample description.")
        self.assertEqual(document.canonical_url, ARTICLE_URL)
        self.assertIn("Hello", document.text)
        self.assertIn("First paragraph.", document.text)
        self.assertIn("Second paragraph.", document.text)  # 连续空格被归一
        self.assertNotIn("nav noise", document.text)
        self.assertNotIn("footer noise", document.text)
        self.assertNotIn("var x=1", document.text)

    def test_block_tags_produce_paragraph_breaks(self):
        document = parse_html("<p>one</p><p>two</p>")
        self.assertEqual(document.text, "one\n\ntwo")

    def test_open_graph_title_wins_over_title_tag(self):
        html = (
            '<html><head><title>Site suffix</title>'
            '<meta property="og:title" content="Real Headline"></head>'
            "<body><p>body</p></body></html>"
        )
        content = WebHandler().extract(page(ARTICLE_URL, body=html.encode("utf-8")))
        self.assertEqual(content.title, "Real Headline")

    def test_twitter_title_is_used_when_og_is_absent(self):
        html = (
            '<html><head><title>Site suffix</title>'
            '<meta name="twitter:title" content="Twitter Headline"></head>'
            "<body><p>body</p></body></html>"
        )
        content = WebHandler().extract(page(ARTICLE_URL, body=html.encode("utf-8")))
        self.assertEqual(content.title, "Twitter Headline")

    def test_description_falls_back_to_og_description(self):
        html = (
            '<html><head><meta property="og:description" content="OG description">'
            "</head><body><p>body</p></body></html>"
        )
        content = WebHandler().extract(page(ARTICLE_URL, body=html.encode("utf-8")))
        self.assertEqual(content.description, "OG description")

    def test_text_plain_pages_are_supported_without_title(self):
        content = WebHandler().extract(
            page(ARTICLE_URL, body=b"line one\n\nline two", content_type="text/plain")
        )
        self.assertIsNone(content.title)
        self.assertEqual(content.body, "line one\n\nline two")

    def test_empty_html_fails_the_link_not_the_batch(self):
        with self.assertRaises(ContentHandlerError):
            WebHandler().extract(
                page(ARTICLE_URL, body=b"<html><body><script>x</script></body></html>")
            )

    def test_github_handler_uses_owner_repo_title(self):
        handler = GitHubHandler()
        url = "https://github.com/owner/repo/blob/main/README.md"
        self.assertTrue(handler.matches(url, "text/html"))
        content = handler.extract(page(url))

        self.assertEqual(content.handler, "github")
        self.assertEqual(content.title, "owner/repo")

    def test_github_handler_does_not_match_other_hosts(self):
        handler = GitHubHandler()
        self.assertFalse(handler.matches(ARTICLE_URL, "text/html"))
        self.assertFalse(handler.matches("https://github.com/owner/repo", "application/pdf"))

    def test_handler_selection_prefers_the_specific_one(self):
        handlers, _ = build_handlers(["web", "github"])
        handler = select_handler(
            url="https://github.com/owner/repo",
            content_type="text/html; charset=utf-8",
            handlers=handlers,
        )
        self.assertIsInstance(handler, GitHubHandler)

    def test_handler_selection_reports_unsupported_content_type(self):
        handlers, _ = build_handlers(["web", "github"])
        for content_type in ("application/pdf", "application/octet-stream", None):
            with self.subTest(content_type=content_type):
                with self.assertRaises(NoHandlerError) as ctx:
                    select_handler(
                        url=ARTICLE_URL, content_type=content_type, handlers=handlers
                    )
                self.assertIn("no enabled handler", str(ctx.exception))

    def test_handler_selection_respects_enabled_list(self):
        handlers, _ = build_handlers(["github"])
        with self.assertRaises(NoHandlerError):
            select_handler(url=ARTICLE_URL, content_type="text/html", handlers=handlers)

    def test_build_handlers_reports_unimplemented_names(self):
        handlers, unknown = build_handlers(["web", "github", "pdf"])
        self.assertEqual(sorted(handlers), ["github", "web"])
        self.assertEqual(unknown, ("pdf",))

    def test_build_handlers_defaults_to_implemented_ones(self):
        handlers, unknown = build_handlers(None)
        self.assertEqual(sorted(handlers), ["github", "web"])
        self.assertEqual(unknown, ())


class SkipDomainTests(unittest.TestCase):
    """跳过名单的域名匹配（含子域）。"""

    def test_matches_exact_domain_and_subdomain(self):
        self.assertEqual(skip_domain_match("x.com", ("x.com",)), "x.com")
        self.assertEqual(skip_domain_match("mobile.twitter.com", ("twitter.com",)), "twitter.com")
        self.assertIsNone(skip_domain_match("example.com", ("x.com",)))

    def test_matching_is_case_insensitive_and_ignores_port(self):
        self.assertEqual(skip_domain_match("X.COM:443", ("x.com",)), "x.com")

    def test_lookalike_domains_are_not_matched(self):
        self.assertIsNone(skip_domain_match("notx.com", ("x.com",)))
        self.assertIsNone(skip_domain_match("", ("x.com",)))


class ResolverTestCase(unittest.TestCase):
    """共用夹具：临时知识库 + 注入 fetcher / handlers / updater / sleeper。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-links-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.knowledge = self.tmp / "knowledge"
        self.updates: list[LinkUpdate] = []
        self.sleeper = RecordingSleeper()

    def options(self, **overrides) -> ExternalOptions:
        values: dict[str, object] = {
            "delay_seconds": 0.0,
            "skip_domains": (),
            "max_links_per_tweet": 10,
        }
        values.update(overrides)
        return ExternalOptions(**values)  # type: ignore[arg-type]

    def resolver(self, fetcher, **kwargs) -> LinkResolver:
        handlers, _ = build_handlers(["web", "github"])
        kwargs.setdefault("options", self.options())
        kwargs.setdefault("updater", self.updates.append)
        kwargs.setdefault("handlers", handlers)
        return LinkResolver(
            self.knowledge,
            fetcher=fetcher,
            sleeper=self.sleeper,
            **kwargs,
        )

    def target(self, url: str = ARTICLE_URL, **overrides) -> LinkTarget:
        values: dict[str, object] = {
            "tweet_id": PHOTO_TWEET,
            "url": url,
            "created_at": "2026-09-14T01:24:21Z",
        }
        values.update(overrides)
        return LinkTarget(**values)  # type: ignore[arg-type]

    def content_file(self, url: str = ARTICLE_URL) -> Path:
        return (
            self.knowledge
            / link_dir_for(PHOTO_TWEET, "2026-09-14T01:24:21Z")
            / f"{link_key_for(url)}.md"
        )


class ResolverPathTests(unittest.TestCase):
    """命名与布局：`link_key` 稳定、年月回退、正文文件名。"""

    def test_link_key_is_stable_and_url_specific(self):
        self.assertEqual(link_key_for(ARTICLE_URL), link_key_for(ARTICLE_URL))
        self.assertNotEqual(link_key_for(ARTICLE_URL), link_key_for(X_ARTICLE_URL))
        self.assertEqual(len(link_key_for(ARTICLE_URL)), 16)

    def test_directory_follows_posted_date_and_falls_back(self):
        self.assertEqual(
            link_dir_for("123", "2026-09-14T01:24:21Z").as_posix(),
            "2026/09/assets/123/links",
        )
        self.assertEqual(
            link_dir_for("123", None).as_posix(), "unknown/unknown/assets/123/links"
        )

    def test_directory_components_cannot_escape_the_knowledge_dir(self):
        directory = link_dir_for("../evil", "2026-09-14T00:00:00Z")
        self.assertEqual(len(directory.parts), 5)
        self.assertNotIn("..", directory.parts)

    def test_rendered_content_has_no_timestamp(self):
        text = render_link_markdown(
            url=ARTICLE_URL,
            resolved_url=ARTICLE_URL,
            title="Title",
            description=None,
            domain="example.com",
            handler="web",
            body="body text",
        )
        self.assertIn('source_url: "https://example.com/sample-a"', text)
        self.assertIn("body text", text)
        self.assertNotIn("2026-", text)


class ResolverRunTests(ResolverTestCase):
    """抓取、写盘、幂等与强制重抓。"""

    def test_success_writes_content_and_records_metadata(self):
        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL)})
        stats = self.resolver(fetcher).run([self.target()])

        self.assertEqual((stats.attempted, stats.fetched, stats.failed), (1, 1, 0))
        target = self.content_file()
        self.assertTrue(target.is_file())
        text = target.read_text(encoding="utf-8")
        self.assertIn("Sample A | Example", text)  # 标题写进正文 frontmatter
        self.assertIn("First paragraph.", text)

        self.assertEqual(len(self.updates), 1)
        update = self.updates[0]
        self.assertEqual(update.status, "FETCHED")
        self.assertEqual(update.url, ARTICLE_URL)
        self.assertEqual(update.resolved_url, ARTICLE_URL)
        self.assertEqual(update.title, "Sample A | Example")
        self.assertEqual(update.content_path, str(target))
        self.assertFalse(update.count_attempt)

    def test_already_fetched_row_does_not_touch_the_network(self):
        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL)})
        self.resolver(fetcher).run([self.target()])
        stamp = self.content_file().stat().st_mtime_ns

        second = self.resolver(fetcher).run(
            [self.target(fetch_status="FETCHED", content_path=str(self.content_file()))]
        )

        self.assertEqual((second.unchanged, second.fetched), (1, 0))
        self.assertEqual(fetcher.calls, [ARTICLE_URL])  # 第二轮没有联网
        self.assertEqual(self.content_file().stat().st_mtime_ns, stamp)
        self.assertEqual(len(self.updates), 1)  # unchanged 不产生落库意图

    def test_force_refetches_but_identical_content_is_not_rewritten(self):
        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL)})
        self.resolver(fetcher).run([self.target()])
        target = self.target(fetch_status="FETCHED", content_path=str(self.content_file()))
        stamp = self.content_file().stat().st_mtime_ns

        stats = self.resolver(fetcher, force=True).run([target])

        self.assertEqual((stats.fetched, stats.unchanged), (0, 1))
        self.assertEqual(len(fetcher.calls), 2)  # --force 确实重抓了
        self.assertEqual(self.content_file().stat().st_mtime_ns, stamp)

    def test_changed_page_is_rewritten(self):
        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL)})
        self.resolver(fetcher).run([self.target()])
        target = self.target(fetch_status="FETCHED", content_path=str(self.content_file()))

        updated = ScriptedFetcher(
            {ARTICLE_URL: page(ARTICLE_URL, body=b"<html><body><p>New body</p></body></html>")}
        )
        stats = self.resolver(updated, force=True).run([target])

        self.assertEqual(stats.fetched, 1)
        self.assertIn("New body", self.content_file().read_text(encoding="utf-8"))

    def test_missing_content_file_is_refetched(self):
        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL)})
        stats = self.resolver(fetcher).run(
            [self.target(fetch_status="FETCHED", content_path=str(self.tmp / "gone.md"))]
        )

        self.assertEqual(stats.fetched, 1)
        self.assertEqual(fetcher.calls, [ARTICLE_URL])

    def test_content_path_outside_the_knowledge_dir_is_not_trusted(self):
        outside = self.tmp / "outside" / "page.md"
        outside.parent.mkdir(parents=True)
        outside.write_text("stale", encoding="utf-8")

        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL)})
        stats = self.resolver(fetcher).run(
            [self.target(fetch_status="FETCHED", content_path=str(outside))]
        )

        self.assertEqual(stats.fetched, 1)
        self.assertEqual(fetcher.calls, [ARTICLE_URL])
        self.assertEqual(outside.read_text(encoding="utf-8"), "stale")

    def test_dry_run_writes_nothing(self):
        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL)})
        stats = self.resolver(fetcher, dry_run=True).run([self.target()])

        self.assertEqual(stats.fetched, 1)
        self.assertEqual(self.updates, [])
        self.assertFalse(self.knowledge.exists())

    def test_polite_delay_between_network_calls(self):
        other = "https://example.com/second"
        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL), other: page(other)})

        self.resolver(fetcher, options=self.options(delay_seconds=1.5)).run(
            [self.target(), self.target(url=other)]
        )

        self.assertEqual(self.sleeper.delays, [1.5])


class ResolverFailureTests(ResolverTestCase):
    """失败与跳过：原始 URL 必须保留，单条失败不得影响批次。"""

    def test_failure_records_reason_and_keeps_the_url(self):
        fetcher = ScriptedFetcher(
            {ARTICLE_URL: HttpStatusError(404, ARTICLE_URL, attempts=3)}
        )
        stats = self.resolver(fetcher).run([self.target()])

        self.assertEqual((stats.failed, stats.fetched), (1, 0))
        self.assertEqual(stats.errors[0][0], f"{PHOTO_TWEET}/{ARTICLE_URL}")

        update = self.updates[0]
        self.assertEqual(update.url, ARTICLE_URL)  # 原始 URL 原样保留
        self.assertEqual(update.status, "FAILED")
        self.assertEqual(update.error_message, "HTTP 404")
        self.assertTrue(update.count_attempt)
        self.assertIsNone(update.content_path)
        self.assertFalse(self.content_file().exists())

    def test_one_failure_does_not_stop_the_batch(self):
        good = "https://example.com/good"
        bad = "https://example.com/bad"
        fetcher = ScriptedFetcher(
            {
                ARTICLE_URL: page(ARTICLE_URL),
                good: page(good),
                bad: TransportTimeoutError("timeout after 20s"),
            }
        )
        stats = self.resolver(fetcher).run(
            [self.target(), self.target(url=bad), self.target(url=good)]
        )

        self.assertEqual((stats.attempted, stats.fetched, stats.failed), (3, 2, 1))
        self.assertEqual(len(stats.errors), 1)
        self.assertTrue(self.content_file().is_file())
        self.assertTrue(self.content_file(good).is_file())

    def test_unexpected_fetcher_error_is_isolated(self):
        fetcher = ScriptedFetcher({ARTICLE_URL: ValueError("boom")})
        stats = self.resolver(fetcher).run([self.target()])

        self.assertEqual(stats.failed, 1)
        self.assertTrue(self.updates[0].error_message.startswith("ValueError"))

    def test_unsupported_scheme_is_skipped_without_network(self):
        fetcher = ScriptedFetcher({})
        stats = self.resolver(fetcher).run([self.target(url="mailto:someone@example.com")])

        self.assertEqual((stats.skipped, stats.failed), (1, 0))
        self.assertEqual(fetcher.calls, [])
        self.assertEqual(self.updates[0].status, "SKIPPED")
        self.assertIn("unsupported scheme", self.updates[0].error_message or "")
        self.assertFalse(self.updates[0].count_attempt)

    def test_skip_domains_short_circuits_before_the_network(self):
        fetcher = ScriptedFetcher({})
        stats = self.resolver(
            fetcher, options=self.options(skip_domains=("x.com", "twitter.com"))
        ).run([self.target(url=X_ARTICLE_URL)])

        self.assertEqual(stats.skipped, 1)
        self.assertEqual(fetcher.calls, [])
        self.assertIn("skip_domains (x.com)", self.updates[0].error_message or "")

    def test_disabled_handler_skips_the_link(self):
        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL)})
        stats = self.resolver(fetcher, handlers={"github": GitHubHandler()}).run(
            [self.target()]
        )

        self.assertEqual(stats.skipped, 1)
        self.assertIn("no enabled handler", self.updates[0].error_message or "")

    def test_pdf_pages_are_skipped_but_keep_the_url(self):
        fetcher = ScriptedFetcher(
            {ARTICLE_URL: page(ARTICLE_URL, content_type="application/pdf")}
        )
        stats = self.resolver(fetcher).run([self.target()])

        self.assertEqual(stats.skipped, 1)
        self.assertEqual(self.updates[0].url, ARTICLE_URL)
        self.assertIn("application/pdf", self.updates[0].error_message or "")

    def test_links_beyond_the_per_tweet_cap_are_skipped(self):
        other = "https://example.com/second"
        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL)})
        stats = self.resolver(fetcher, options=self.options(max_links_per_tweet=1)).run(
            [self.target(), self.target(url=other)]
        )

        self.assertEqual((stats.fetched, stats.skipped), (1, 1))
        self.assertEqual(fetcher.calls, [ARTICLE_URL])
        self.assertIn("max_links_per_tweet", self.updates[-1].error_message or "")

    def test_failed_rows_are_retried_until_the_attempt_limit(self):
        fetcher = ScriptedFetcher({ARTICLE_URL: page(ARTICLE_URL)})
        retried = self.resolver(fetcher).run(
            [self.target(fetch_status="FAILED", attempts=1)]
        )
        self.assertEqual(retried.fetched, 1)
        self.assertEqual(fetcher.calls, [ARTICLE_URL])

    def test_attempt_limit_stops_the_retries(self):
        fetcher = ScriptedFetcher({})
        stats = self.resolver(fetcher, options=self.options(max_attempts=3)).run(
            [self.target(fetch_status="FAILED", attempts=3)]
        )

        self.assertEqual((stats.skipped, stats.failed), (1, 0))
        self.assertEqual(fetcher.calls, [])
        self.assertIn("attempt limit reached", self.updates[0].error_message or "")

    def test_page_without_body_is_fetched_with_a_note(self):
        fetcher = ScriptedFetcher(
            {
                ARTICLE_URL: page(
                    ARTICLE_URL, body=b"<html><head><title>Only a title</title></head></html>"
                )
            }
        )
        stats = self.resolver(fetcher).run([self.target()])

        self.assertEqual(stats.fetched, 1)
        self.assertEqual(self.updates[0].title, "Only a title")
        self.assertIn("no body text", self.updates[0].error_message or "")


UPSTREAM: dict[str, object] = {
    "tweetId": "1001",
    "url": "https://x.com/sample_author/status/1001",
    "text": "sample body",
    "links": [ARTICLE_URL, X_ARTICLE_URL],
    "postedAt": "Mon Sep 14 01:24:21 +0000 2026",
    "media": [],
    "engagement": {"likeCount": 1},
    "ingestedVia": "graphql",
}


def render(link_details=None) -> str:
    return render_markdown(
        UPSTREAM, None, RenderOptions(), link_details=link_details
    )


class ExternalLinksSectionTests(unittest.TestCase):
    """`## external_links` 段：富化渲染、Phase 7 回退、转义。"""

    def section(self, text: str) -> str:
        start = text.index("## external_links")
        return text[start:]

    def test_plain_url_list_without_details(self):
        section = self.section(render())
        self.assertIn(f"- {ARTICLE_URL}", section)
        self.assertNotIn("正文：", section)

    def test_pending_links_keep_the_phase_seven_shape(self):
        section = self.section(
            render({ARTICLE_URL: {"fetch_status": "PENDING", "error_message": None}})
        )
        self.assertIn(f"- {ARTICLE_URL}", section)
        self.assertNotIn("正文：", section)

    def test_fetched_link_shows_title_path_and_final_url(self):
        section = self.section(
            render(
                {
                    ARTICLE_URL: {
                        "title": "Sample A",
                        "resolved_url": "https://example.com/final",
                        "content_path": f"assets/{PHOTO_TWEET}/links/abc.md",
                        "fetch_status": "FETCHED",
                    }
                }
            )
        )
        self.assertIn(f"- [Sample A]({ARTICLE_URL})", section)
        self.assertIn("  - 最终地址：https://example.com/final", section)
        self.assertIn(f"  - 正文：`assets/{PHOTO_TWEET}/links/abc.md`", section)

    def test_same_final_url_is_not_repeated(self):
        section = self.section(
            render({ARTICLE_URL: {"title": "Sample A", "resolved_url": ARTICLE_URL}})
        )
        self.assertNotIn("最终地址", section)

    def test_failure_keeps_the_url_and_shows_the_reason(self):
        section = self.section(
            render(
                {
                    ARTICLE_URL: {
                        "fetch_status": "FAILED",
                        "error_message": "HTTP 404",
                    }
                }
            )
        )
        self.assertIn(f"- {ARTICLE_URL}", section)
        self.assertIn("  - 抓取失败：HTTP 404", section)

    def test_skip_reason_does_not_repeat_the_skipped_prefix(self):
        section = self.section(
            render(
                {
                    X_ARTICLE_URL: {
                        "fetch_status": "SKIPPED",
                        "error_message": "skipped: skip_domains (x.com)",
                    }
                }
            )
        )
        self.assertIn(f"- {X_ARTICLE_URL}", section)
        self.assertIn("  - 已跳过：skip_domains (x.com)", section)
        self.assertNotIn("skipped: skip_domains", section)

    def test_link_titles_are_escaped(self):
        section = self.section(
            render({ARTICLE_URL: {"title": "Broken [title] here", "fetch_status": "FETCHED"}})
        )
        self.assertIn(f"- [Broken \\[title\\] here]({ARTICLE_URL})", section)

    def test_multiline_titles_are_collapsed(self):
        section = self.section(
            render({ARTICLE_URL: {"title": "line one\nline two", "fetch_status": "FETCHED"}})
        )
        self.assertIn(f"- [line one line two]({ARTICLE_URL})", section)


class LinkLookupWriterTests(unittest.TestCase):
    """`MarkdownWriter` 把知识库内的正文绝对路径换算成相对本文件的路径。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-links-writer-")
        self.addCleanup(self._tmp.cleanup)
        self.knowledge = Path(self._tmp.name) / "knowledge"
        self.content = (
            self.knowledge / "2026" / "09" / "assets" / "1001" / "links" / "abc.md"
        )
        self.content.parent.mkdir(parents=True)
        self.content.write_text("body", encoding="utf-8")

    def test_absolute_content_path_is_rendered_relative_to_the_markdown_file(self):
        writer = MarkdownWriter(
            self.knowledge,
            loader=lambda tweet_id: {"upstream": UPSTREAM, "enrichment": None},
            options=RenderOptions(),
            link_lookup=lambda tweet_id: {
                ARTICLE_URL: {
                    "title": "Sample A",
                    "fetch_status": "FETCHED",
                    "content_path": str(self.content),
                }
            },
        )
        stats = writer.run(["1001"])

        self.assertEqual(stats.written, 1)
        text = (
            self.knowledge / "2026" / "09" / "20260914-1001.md"
        ).read_text(encoding="utf-8")
        self.assertIn("- [Sample A](" + ARTICLE_URL + ")", text)
        self.assertIn("`assets/1001/links/abc.md`", text)
        self.assertNotIn(str(self.knowledge), text)

    def test_lookup_failure_falls_back_to_plain_urls(self):
        def broken(tweet_id: str):
            raise RuntimeError("db gone")

        writer = MarkdownWriter(
            self.knowledge,
            loader=lambda tweet_id: {"upstream": UPSTREAM, "enrichment": None},
            options=RenderOptions(),
            link_lookup=broken,
        )
        stats = writer.run(["1001"])

        self.assertEqual(stats.written, 1)
        text = (
            self.knowledge / "2026" / "09" / "20260914-1001.md"
        ).read_text(encoding="utf-8")
        self.assertIn(f"- {ARTICLE_URL}", text)


class CliLinkTestCase(unittest.TestCase):
    """`python -m src.cli links` 端到端（离线上游桩 + 临时目录 + 注入 fake transport）。"""

    EXTERNAL_BLOCK = (
        "external:\n"
        "  enabled: true\n"
        "  delay_seconds: 0\n"
        "  skip_domains: []\n"
    )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-clilinks-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.config_path = self.tmp / "config.yaml"
        self.upstream = self.tmp / "upstream"
        self.knowledge = self.tmp / "knowledge" / "X-Bookmarks"
        self.fetcher = ScriptedFetcher(
            {ARTICLE_URL: page(ARTICLE_URL), X_ARTICLE_URL: page(X_ARTICLE_URL)}
        )
        # 抓取器在 CLI 里单独一层，测试用假实现替换它（本文件全程不打开 socket）。
        patcher = mock.patch.object(
            importlib.import_module("src.cli.main"),
            "_build_link_fetcher",
            lambda config, options: self.fetcher,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write_config()

    def write_config(self, external_block: str | None = None) -> Path:
        block = self.EXTERNAL_BLOCK if external_block is None else external_block
        text = (
            "version: 1\n"
            f"paths:\n  project_root: '{self.tmp.as_posix()}'\n"
            "  data_dir: 'data'\n  raw_dir: 'data/raw'\n  state_dir: 'data/state'\n"
            "  log_dir: 'data/logs'\n  knowledge_dir: 'knowledge/X-Bookmarks'\n"
            "collector:\n"
            f"  executable: '{sys.executable}'\n  executable_args: ['-B', '{STUB.as_posix()}']\n"
            f"  upstream_data_dir: '{self.upstream.as_posix()}'\n"
            "  auth:\n    method: 'firefox'\n    browser: 'firefox'\n"
            + block
            + "logging:\n  level: 'INFO'\n  file_per_day: true\n  console: false\n"
        )
        self.config_path.write_text(text, encoding="utf-8")
        return self.config_path

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(["--config", str(self.config_path), *argv])
        return code, out.getvalue(), err.getvalue()

    def link_rows(self) -> dict[str, sqlite3.Row]:
        connection = connect(self.tmp / "data" / "state" / "state.db")
        connection.row_factory = sqlite3.Row
        try:
            return {
                str(row["url"]): row
                for row in connection.execute("SELECT * FROM external_links")
            }
        finally:
            connection.close()

    def content_file(self, tweet_id: str, url: str) -> Path:
        return (
            self.knowledge
            / "2026"
            / "09"
            / "assets"
            / tweet_id
            / "links"
            / f"{link_key_for(url)}.md"
        )


class CliLinkTests(CliLinkTestCase):
    """`links` 命令本身：抓取、跳过、失败退出码、dry-run。"""

    def test_links_fetches_pages_and_records_knowledge_paths(self):
        self.run_cli("sync")
        code, out, _ = self.run_cli("links")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("fetched       : 2", out)
        self.assertIn("handlers      : github, web", out)

        rows = self.link_rows()
        self.assertEqual(len(rows), 2)
        for row in rows.values():
            self.assertEqual(row["fetch_status"], "FETCHED")
            self.assertIsNotNone(row["title"])
            # 审计回归：正文必须落在本项目知识库内，而不是知识库之外。
            self.assertTrue(str(row["content_path"]).startswith(str(self.knowledge)))
        self.assertTrue(self.content_file("1900000000000000101", ARTICLE_URL).is_file())

    def test_second_run_is_unchanged_and_does_not_fetch(self):
        self.run_cli("sync")
        self.run_cli("links")
        self.fetcher.calls.clear()

        code, out, _ = self.run_cli("links")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("unchanged     : 2", out)
        self.assertEqual(self.fetcher.calls, [])

    def test_failing_link_keeps_the_url_and_sets_the_exit_code(self):
        self.fetcher.script[ARTICLE_URL] = HttpStatusError(404, ARTICLE_URL, attempts=3)
        self.run_cli("sync")

        code, out, err = self.run_cli("links")

        self.assertEqual(code, EXIT_FAILURE)
        self.assertIn("failed        : 1", out)
        self.assertIn("fetched       : 1", out)
        self.assertIn(ARTICLE_URL, err)

        failed = self.link_rows()[ARTICLE_URL]
        self.assertEqual(failed["url"], ARTICLE_URL)  # 原始 URL 未被清空
        self.assertEqual(failed["fetch_status"], "FAILED")
        self.assertEqual(failed["error_message"], "HTTP 404")
        self.assertEqual(failed["attempts"], 1)

    def test_dry_run_writes_nothing(self):
        self.run_cli("sync")

        code, out, _ = self.run_cli("links", "--dry-run")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("dry run       : true", out)
        self.assertIn("fetched       : 2", out)
        self.assertFalse(self.knowledge.exists())
        for row in self.link_rows().values():
            self.assertEqual(row["fetch_status"], "PENDING")
            self.assertIsNone(row["content_path"])

    def test_disabled_external_skips_the_whole_command(self):
        self.run_cli("sync")
        self.write_config(external_block="external:\n  enabled: false\n")

        code, out, err = self.run_cli("links")

        self.assertEqual(code, EXIT_OK)
        self.assertNotIn("Link report", out)
        self.assertIn("external.enabled=false", err)
        for row in self.link_rows().values():
            self.assertEqual(row["fetch_status"], "PENDING")

    def test_default_skip_domains_skip_x_links(self):
        self.run_cli("sync")
        self.write_config(external_block="external:\n  enabled: true\n  delay_seconds: 0\n")

        code, out, _ = self.run_cli("links")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("skipped       : 1", out)
        self.assertEqual(self.fetcher.calls, [ARTICLE_URL])
        skipped = self.link_rows()[X_ARTICLE_URL]
        self.assertEqual(skipped["fetch_status"], "SKIPPED")
        self.assertIn("skip_domains (x.com)", skipped["error_message"])

    def test_unimplemented_handlers_are_reported_not_fatal(self):
        self.run_cli("sync")
        self.write_config(
            external_block=(
                "external:\n  enabled: true\n  delay_seconds: 0\n"
                "  skip_domains: []\n  handlers: ['web', 'github', 'pdf']\n"
            )
        )

        code, _, err = self.run_cli("links")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("not implemented yet, ignored: pdf", err)

    def test_tweet_id_filter_limits_the_batch(self):
        self.run_cli("sync")

        code, out, _ = self.run_cli("links", "--tweet-id", "1900000000000000101")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("attempted     : 1", out)
        self.assertEqual(self.fetcher.calls, [ARTICLE_URL])

    def test_no_links_is_not_an_error(self):
        self.run_cli("sync")
        self.run_cli("links")

        code, _, err = self.run_cli("links", "--tweet-id", "1900000000000000103")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("no external links to resolve", err)


class CliLinkPipelineTests(CliLinkTestCase):
    """`links` → `process` 的衔接，以及 `sync` 不得回退外链状态。"""

    def test_process_after_links_renders_title_and_relative_path(self):
        self.run_cli("sync")
        self.run_cli("links")

        code, out, _ = self.run_cli("process")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("links known   : 2 bookmark(s)", out)
        text = (
            self.knowledge / "2026" / "09" / "20260914-1900000000000000101.md"
        ).read_text(encoding="utf-8")
        self.assertIn(f"- [Sample A | Example]({ARTICLE_URL})", text)
        self.assertIn(
            f"`assets/1900000000000000101/links/{link_key_for(ARTICLE_URL)}.md`", text
        )
        self.assertNotIn(str(self.knowledge), text)

    def test_second_process_run_is_unchanged(self):
        self.run_cli("sync")
        self.run_cli("links")
        self.run_cli("process")

        code, out, _ = self.run_cli("process")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("written       : 0", out)
        self.assertIn("unchanged     : 3", out)

    def test_process_without_links_keeps_plain_urls(self):
        """Phase 7 行为不变：没跑 `links` 时 `## external_links` 仍是纯 URL 列表。"""

        self.run_cli("sync")

        code, out, _ = self.run_cli("process")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("links known   : 2 bookmark(s)", out)
        text = (
            self.knowledge / "2026" / "09" / "20260914-1900000000000000101.md"
        ).read_text(encoding="utf-8")
        self.assertIn(f"- {ARTICLE_URL}", text)
        self.assertNotIn("正文：", text)

    def test_resync_does_not_reset_fetch_status(self):
        self.run_cli("sync")
        self.run_cli("links")
        before = {url: row["fetch_status"] for url, row in self.link_rows().items()}

        code, out, _ = self.run_cli("sync", "--skip-collect")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("link rows     : 0 new, 0 updated, 2 unchanged", out)
        after = {url: row["fetch_status"] for url, row in self.link_rows().items()}
        self.assertEqual(before, after)
        self.assertEqual(set(after.values()), {"FETCHED"})

    def test_status_reports_link_counts(self):
        self.run_cli("sync")
        self.run_cli("links")

        code, out, _ = self.run_cli("status")

        self.assertEqual(code, EXIT_OK)
        self.assertIn("FETCHED 2", out)
        self.assertIn("db links      : 2 total", out)

    def test_status_json_includes_link_counts(self):
        self.run_cli("sync")
        self.run_cli("links")

        code, out, _ = self.run_cli("status", "--json")

        payload = json.loads(out)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["database"]["links"]["total"], 2)
        self.assertEqual(payload["database"]["links"]["counts"]["FETCHED"], 2)



class ReviewFixTests(unittest.TestCase):
    """复审修复（2026-09-20）：SSRF 守卫、canonical 落库/落产物、失败清理旧字段。"""

    def test_netguard_blocks_non_public_targets(self):
        from src.external.netguard import check_url_allowed

        urls = (
            "http://localhost/x",
            "http://127.0.0.1:8080/x",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.10/x",
            "http://10.0.0.5/x",
            "http://[::1]/x",
            "http://[fd00::1]/x",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertIsNotNone(
                    check_url_allowed(url, resolver=lambda host: ["127.0.0.1"])
                )

    def test_netguard_allows_public_targets_and_allowlist(self):
        from src.external.netguard import check_url_allowed

        public = lambda host: ["93.184.216.34"]  # 注入解析器：测试不打开 socket
        self.assertIsNone(check_url_allowed("https://example.com/x", resolver=public))
        self.assertIsNone(
            check_url_allowed("https://example.com/x", resolver=lambda host: ["93.184.216.34"])
        )
        self.assertIsNone(check_url_allowed("http://localhost:8080/x", allow_hosts=("localhost",)))

    def test_netguard_blocks_hostname_resolving_to_private(self):
        from src.external.netguard import check_url_allowed

        reason = check_url_allowed("https://internal.example/x", resolver=lambda host: ["10.1.2.3"])
        self.assertIn("non-public", reason or "")

    def test_fetcher_refuses_blocked_target_without_network(self):
        from src.external.fetcher import BlockedTargetError, HttpFetcher

        def transport(*args, **kwargs):  # pragma: no cover - 必须不被调用
            raise AssertionError("transport must not be called")

        fetcher = HttpFetcher(transport=transport, host_resolver=lambda host: ["10.0.0.1"])
        with self.assertRaises(BlockedTargetError):
            fetcher("https://evil.example/x")

    def test_link_resolver_default_fetcher_inherits_security_options(self):
        """审计 CFG-01：不注入 fetcher 时，安全配置也必须生效（此前被静默丢弃）。

        `LinkResolver` 拿得到 `options`，却曾漏传给默认构造的 `HttpFetcher`，导致
        `external.allow_hosts` / `block_non_public_hosts` 在「不注入 fetcher」的调用方式下失效。
        """

        from src.config import load_external_options
        from src.external.fetcher import HttpFetcher
        from src.external.resolver import LinkResolver

        options = load_external_options(
            {"block_non_public_hosts": False, "allow_hosts": ["localhost"]}
        )
        with tempfile.TemporaryDirectory(prefix="xbook-resolver-cfg-") as tmp:
            resolver = LinkResolver(Path(tmp), options=options)
            fetcher = resolver._fetcher
            self.assertIsInstance(fetcher, HttpFetcher)
            self.assertFalse(fetcher.block_non_public_hosts)
            self.assertEqual(fetcher.allow_hosts, ("localhost",))
            # 行为验证（不触网、不做 DNS）：关闭开关后私网目标不再被拦
            fetcher._guard("http://10.0.0.5/x")

    def test_link_resolver_default_fetcher_keeps_strict_default(self):
        """反向用例：默认配置下默认分支仍是最严格取值（防止未来把默认写反）。"""

        from src.config import load_external_options
        from src.external.fetcher import BlockedTargetError
        from src.external.resolver import LinkResolver

        with tempfile.TemporaryDirectory(prefix="xbook-resolver-cfg-") as tmp:
            resolver = LinkResolver(Path(tmp), options=load_external_options({}))
            self.assertTrue(resolver._fetcher.block_non_public_hosts)
            self.assertEqual(resolver._fetcher.allow_hosts, ())
            with self.assertRaises(BlockedTargetError):
                resolver._fetcher._guard("http://10.0.0.5/x")

    def test_fetcher_rechecks_target_after_redirect(self):
        from src.external.fetcher import BlockedTargetError, HttpFetcher

        calls = []

        class Redirect:
            status_code = 302
            url = "https://public.example/x"
            headers = {}
            body = b""

            def header(self, name):
                return "http://169.254.169.254/latest/meta-data/" if name == "location" else None

        def transport(url, **kwargs):
            calls.append(url)
            return Redirect()

        fetcher = HttpFetcher(transport=transport, host_resolver=lambda host: ["93.184.216.34"])
        with self.assertRaises(BlockedTargetError):
            fetcher("https://public.example/x")
        # 只发出第一跳：重定向目标在第二次请求之前就被拒绝
        self.assertEqual(calls, ["https://public.example/x"])

    def test_resolver_skips_blocked_target_without_attempt(self):
        from src.config import load_external_options
        from src.external.fetcher import BlockedTargetError
        from src.external.resolver import LinkResolver, LinkTarget

        updates = []

        def fetcher(url):
            raise BlockedTargetError("blocked target (non-public address 127.0.0.1)")

        with tempfile.TemporaryDirectory() as tmp:
            resolver = LinkResolver(
                tmp, options=load_external_options({}), fetcher=fetcher, updater=updates.append
            )
            stats = resolver.run([LinkTarget(tweet_id="1", url="http://127.0.0.1/x")])
        self.assertEqual((stats.skipped, stats.failed), (1, 0))
        self.assertEqual(updates[0].status, "SKIPPED")
        self.assertFalse(updates[0].count_attempt)
        self.assertIn("blocked target", updates[0].error_message or "")

    def test_resolver_persists_canonical_url(self):
        from src.config import load_external_options
        from src.external.handlers.web import WebHandler
        from src.external.resolver import LinkResolver, LinkTarget

        updates = []

        class Page:
            content_type = "text/html"
            final_url = "https://cdn.example/x"

            def text(self):
                return (
                    '<html><head><link rel="canonical" href="https://example.com/c">'
                    "<title>T</title></head><body>Body</body></html>"
                )

        with tempfile.TemporaryDirectory() as tmp:
            resolver = LinkResolver(
                tmp,
                options=load_external_options({}),
                fetcher=lambda url: Page(),
                handlers={"web": WebHandler()},
                updater=updates.append,
            )
            stats = resolver.run(
                [
                    LinkTarget(
                        tweet_id="1",
                        url="https://example.com/x",
                        created_at="2026-09-14T01:24:21Z",
                    )
                ]
            )
            body_text = Path(updates[0].content_path).read_text(encoding="utf-8")
        self.assertEqual(stats.fetched, 1)
        self.assertEqual(updates[0].resolved_url, "https://example.com/c")
        body = body_text
        self.assertIn("canonical_url", body)
        self.assertIn("https://cdn.example/x", body)

    def test_resolver_clears_stale_fields_only_when_forced_or_exhausted(self):
        from src.config import load_external_options
        from src.external.fetcher import TransportFailure
        from src.external.resolver import LinkResolver, LinkTarget

        def run(force, attempts):
            updates = []

            def fetcher(url):
                raise TransportFailure("boom")

            with tempfile.TemporaryDirectory() as tmp:
                resolver = LinkResolver(
                    tmp,
                    options=load_external_options({}),
                    fetcher=fetcher,
                    updater=updates.append,
                    force=force,
                )
                resolver.run(
                    [
                        LinkTarget(
                            tweet_id="1",
                            url="https://example.com/x",
                            fetch_status="FETCHED",
                            content_path="old.md",
                            attempts=attempts,
                        )
                    ]
                )
            return [update for update in updates if update.status == "FAILED"][0]

        cleared = ("resolved_url", "title", "content_path")
        self.assertEqual(run(True, 0).clear_fields, cleared)
        self.assertEqual(run(False, 0).clear_fields, ())
        self.assertEqual(run(False, 99).clear_fields, cleared)

    def test_set_link_status_can_clear_fields(self):
        from src.database import BookmarkRecord, BookmarkRepository, ExternalLinkRecord, connect

        connection = connect(":memory:")
        try:
            repository = BookmarkRepository(connection)
            repository.upsert_bookmark(BookmarkRecord(tweet_id="1"))
            repository.upsert_external_link(
                ExternalLinkRecord(
                    tweet_id="1",
                    url="https://example.com/x",
                    resolved_url="https://example.com/final",
                    title="old title",
                    content_path="old.md",
                )
            )
            repository.set_link_status(
                "1",
                "https://example.com/x",
                "FAILED",
                error_message="boom",
                clear_fields=("resolved_url", "title", "content_path"),
            )
            row = repository.require_external_link("1", "https://example.com/x")
            self.assertIsNone(row.resolved_url)
            self.assertIsNone(row.title)
            self.assertIsNone(row.content_path)
            self.assertEqual(row.url, "https://example.com/x")
            with self.assertRaises(ValueError):
                repository.set_link_status(
                    "1", "https://example.com/x", "FAILED", clear_fields=("url",)
                )
        finally:
            connection.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
