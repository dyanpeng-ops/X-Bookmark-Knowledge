"""外链解析层（Phase 9）：把 `external_links` 行加工成知识库内的正文文件。

职责边界
--------
* 只做「调度抓取 → 抽取正文 → 写入知识库 `assets/{tweet_id}/links/` → 回报落库意图」。
* 网络在 :mod:`src.external.fetcher`，正文抽取在 :mod:`src.external.handlers`；
  本模块不直接用 `urllib`，也不改 Markdown 正文（那是 `src/markdown/`）。
* 单条隔离：一条外链失败**绝不影响**其余外链（与 ingest / media / markdown 一致）。
* 失败仍保留原始 URL：`LinkUpdate` 从不携带"清空 url"的语义，落库走
  `BookmarkRepository.set_link_status`（没有删除 url 的途径）。

路径规则
--------
* 目标文件 `<knowledge_dir>/{YYYY}/{MM}/assets/{tweet_id}/{links_subdir}/{link_key}.md`
  （年月布局与 Markdown 产物、媒体 `assets/` 同源，复用 `date_parts`）。
* `link_key = sha1(url)[:16]`（与 `media_key_for` 同一约定）→ DB 行与文件可直接互查。
* 文件内容**不含时间戳**：同一页面重复抓取得到的文本若一致就不重写（幂等）。

状态语义（`external_links.fetch_status`）
---------------------------------------
======================  ==========================================================
FETCHED + 文件存在       unchanged：本轮**不联网**（`--force` 才重抓）
PENDING / SKIPPED       尝试抓取（跳过规则在抓取前判定，不产生网络流量）
FAILED 且 attempts 未达上限  重试（自愈）
FAILED 且 attempts >= `external.max_attempts`  skipped：需 `--force` 才再试
失败                     FAILED + `error_message` + `attempts + 1`，URL 原样保留
跳过（策略）             SKIPPED + `error_message = "skipped: <原因>"`
======================  ==========================================================

跳过规则（不联网、只记原因）
----------------------------
* 非 http(s) scheme（`mailto:` / `javascript:` / `ftp:` …）；
* 域名命中 `external.skip_domains`（默认 `x.com` / `twitter.com`：X 自身链接的正文
  已由富化 `## article` 提供，直接抓只会撞登录墙）；
* 全条推文超出 `external.max_links_per_tweet`（按 `list_external_links` 的顺序取前 N 条）；
* 没有任何已启用的 handler 认领该内容类型（含尚未实现的 `pdf`）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from src.config import ExternalOptions
from src.database import LinkFetchStatus
from src.markdown.render import date_parts

from .fetcher import ALLOWED_SCHEMES, BlockedTargetError, FetchError, HttpFetcher
from .handlers import ContentHandler, ContentHandlerError, select_handler

__all__ = [
    "MAX_TITLE_LENGTH",
    "LinkResolver",
    "LinkStats",
    "LinkTarget",
    "LinkUpdate",
    "link_content_name",
    "link_dir_for",
    "link_key_for",
    "render_link_markdown",
    "skip_domain_match",
]

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 512
#: 失败时需要清空的"上一次成功"字段（复审修复）。
STALE_LINK_FIELDS: tuple[str, ...] = ("resolved_url", "title", "content_path")
_UNSAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


# ── 纯函数：命名、布局、判定 ─────────────────────────────────────────────────


def link_key_for(url: str) -> str:
    """稳定外链键：同一 URL 永远得到同一 `link_key`（sha1 前 16 位）。"""

    digest = hashlib.sha1(str(url).encode("utf-8")).hexdigest()
    return digest[:16]


def link_content_name(link_key: str) -> str:
    """正文文件名：`{link_key}.md`（抽取结果统一为文本/Markdown）。"""

    return f"{_safe_component(link_key, 'link')}.md"


def link_dir_for(tweet_id: str, created_at: str | None, links_subdir: str = "links") -> Path:
    """知识库内的相对目录：`{YYYY}/{MM}/assets/{tweet_id}/{links_subdir}`。"""

    year, month, _ = date_parts(created_at)
    return (
        Path(year)
        / month
        / "assets"
        / _safe_component(tweet_id, "unknown")
        / _safe_component(links_subdir, "links")
    )


def _safe_component(value: object, default: str) -> str:
    """收敛成安全的单层路径组件（不允许分隔符或 `..`）。"""

    text = _UNSAFE_COMPONENT.sub("_", str(value or "").strip()).strip("._")
    return text or default


def skip_domain_match(domain: str | None, skip_domains: Sequence[str]) -> str | None:
    """域名是否命中跳过名单；命中返回命中的条目，否则 None。

    同时匹配子域（`www.x.com` 命中 `x.com`），避免漏掉常见写法。
    """

    candidate = str(domain or "").strip().lower().split(":")[0]
    if not candidate:
        return None
    for entry in skip_domains:
        blocked = str(entry or "").strip().lower().lstrip(".")
        if not blocked:
            continue
        if candidate == blocked or candidate.endswith("." + blocked):
            return blocked
    return None


def host_of(url: str) -> str:
    """取 URL 主机名（小写、去端口与 userinfo）。"""

    netloc = urlsplit(str(url)).netloc.lower()
    netloc = netloc.rsplit("@", 1)[-1]
    return netloc.split(":")[0]


def render_link_markdown(
    *,
    url: str,
    resolved_url: str | None,
    title: str | None,
    description: str | None,
    domain: str | None,
    handler: str,
    body: str,
    canonical_url: str | None = None,
) -> str:
    """渲染外链正文文件（frontmatter + 正文；**不含时间戳**，保证内容幂等）。

    `resolved_url` 是重定向最终地址；`canonical_url` 是页面自报的权威地址
    （复审修复：此前解析出来却从不落盘，现同时写入产物与状态库）。
    """

    lines = ["---"]
    for key, value in (
        ("source_url", url),
        ("resolved_url", resolved_url),
        ("canonical_url", canonical_url),
        ("title", title),
        ("description", description),
        ("domain", domain),
        ("handler", handler),
    ):
        if value:
            lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    lines.append("---")
    text = str(body or "").strip()
    return "\n".join(lines) + "\n\n" + (text + "\n" if text else "")


# ── 入参与产出 ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LinkTarget:
    """一条待处理的外链（来自 `external_links` 行 + 所属书签的 `created_at`）。"""

    tweet_id: str
    url: str
    domain: str | None = None
    created_at: str | None = None
    fetch_status: str | None = None
    content_path: str | None = None
    attempts: int = 0
    title: str | None = None


@dataclass(frozen=True, slots=True)
class LinkUpdate:
    """一条外链的落库意图（`None` 字段表示"本次不修改"）。"""

    tweet_id: str
    url: str
    status: str
    resolved_url: str | None = None
    title: str | None = None
    content_path: str | None = None
    error_message: str | None = None
    count_attempt: bool = False
    #: 需要**清空**的字段（复审修复）：`None` 仍表示"本次不修改"，清空必须显式列出。
    clear_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LinkStats:
    """一次外链解析的统计结果（CLI 报告直接使用）。"""

    attempted: int = 0
    fetched: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0
    errors: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return self.failed == 0


# ── 调度器 ───────────────────────────────────────────────────────────────────


class LinkResolver:
    """逐条处理外链：抓取 → 抽取 → 写入知识库 → 回报落库意图。

    `fetcher`、`handlers`、`updater`、`sleeper` 全部注入，因此单元测试完全离线。
    """

    def __init__(
        self,
        knowledge_dir: str | Path,
        *,
        options: ExternalOptions,
        fetcher: Callable[[str], object] | None = None,
        handlers: Mapping[str, ContentHandler] | None = None,
        updater: Callable[[LinkUpdate], None] | None = None,
        dry_run: bool = False,
        force: bool = False,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._knowledge_dir = Path(knowledge_dir)
        self._options = options
        self._fetcher = fetcher if fetcher is not None else HttpFetcher(
            timeout_seconds=options.timeout_seconds,
            retries=options.retries,
            backoff_seconds=options.backoff_seconds,
            max_bytes=options.max_bytes,
            max_redirects=options.max_redirects,
            user_agent=options.user_agent,
        )
        self._handlers: Mapping[str, ContentHandler] = handlers or {}
        self._updater = updater
        self._dry_run = bool(dry_run)
        self._force = bool(force)
        self._sleep = sleeper
        #: 本轮真正发起过的网络请求数（用于礼貌间隔；`run()` 会重置）。
        self._network_calls = 0

    def run(self, targets: Iterable[LinkTarget]) -> LinkStats:
        """逐条处理；任何单条异常都被隔离成该条的 `FAILED`。"""

        self._network_calls = 0
        counters = {"fetched": 0, "unchanged": 0, "skipped": 0, "failed": 0}
        errors: list[tuple[str, str]] = []
        attempted = 0
        per_tweet: dict[str, int] = {}

        for target in targets:
            attempted += 1
            index = per_tweet.get(target.tweet_id, 0) + 1
            per_tweet[target.tweet_id] = index
            message: str | None = None
            try:
                outcome, message = self._process(target, index)
            except Exception as exc:  # noqa: BLE001 - 单条隔离：意外异常也只影响这一条
                outcome = "failed"
                message = f"{type(exc).__name__}: {exc}"
                self._record(
                    LinkUpdate(
                        tweet_id=target.tweet_id,
                        url=target.url,
                        status=LinkFetchStatus.FAILED.value,
                        error_message=message,
                        count_attempt=True,
                    )
                )
            counters[outcome] += 1
            if outcome == "failed":
                errors.append((f"{target.tweet_id}/{target.url}", message or "failed"))

        return LinkStats(
            attempted=attempted,
            fetched=counters["fetched"],
            unchanged=counters["unchanged"],
            skipped=counters["skipped"],
            failed=counters["failed"],
            errors=tuple(errors),
        )

    # ── 单条处理 ────────────────────────────────────────────────────────────

    def _process(self, target: LinkTarget, index: int) -> tuple[str, str | None]:
        """处理一条外链，返回 `(outcome, 错误信息)`；outcome ∈ fetched/unchanged/skipped/failed。"""

        if index > self._options.max_links_per_tweet:
            return self._skip(
                target, f"max_links_per_tweet ({self._options.max_links_per_tweet})"
            )

        scheme = urlsplit(str(target.url)).scheme.lower()
        if scheme not in ALLOWED_SCHEMES:
            return self._skip(target, f"unsupported scheme: {scheme or '(none)'}")

        domain = str(target.domain or host_of(target.url) or "").strip().lower()
        blocked = skip_domain_match(domain, self._options.skip_domains)
        if blocked:
            return self._skip(target, f"skip_domains ({blocked})")

        status = str(target.fetch_status or "").strip().upper()
        if not self._force and status == LinkFetchStatus.FETCHED.value:
            if self._existing_content_path(target) is not None:
                # 已完成且正文仍在知识库内 → 不联网、不写盘（幂等的关键）。
                return "unchanged", None

        attempts = max(0, int(target.attempts or 0))
        if (
            not self._force
            and status == LinkFetchStatus.FAILED.value
            and attempts >= self._options.max_attempts
        ):
            return self._skip(
                target,
                f"attempt limit reached (attempts={attempts}); use --force to retry",
            )

        if self._network_calls and self._options.delay_seconds > 0:
            self._sleep(self._options.delay_seconds)
        self._network_calls += 1
        try:
            page = self._fetcher(str(target.url))
        except BlockedTargetError as exc:
            # 复审修复：非公网目标（localhost/私网/链路本地/云元数据）属**策略拒绝**，
            # 与 skip_domains 同级 —— 记 SKIPPED + 原因，不联网、不计 attempts、不重试。
            return self._skip(target, str(exc))
        except FetchError as exc:
            return self._fail(target, str(exc))
        except Exception as exc:  # noqa: BLE001 - 传输层的意外错误也只影响这一条
            return self._fail(target, f"{type(exc).__name__}: {exc}")

        content_type = getattr(page, "content_type", None)
        final_url = str(getattr(page, "final_url", "") or target.url)
        try:
            handler = select_handler(
                url=str(target.url), content_type=content_type, handlers=self._handlers
            )
        except ContentHandlerError as exc:
            # 内容类型没有 handler（含尚未实现的 pdf）→ 策略性跳过，URL 保留。
            return self._skip(target, str(exc))

        try:
            content = handler.extract(page)
        except ContentHandlerError as exc:
            return self._fail(target, str(exc))
        except Exception as exc:  # noqa: BLE001 - handler 崩溃不影响其他外链
            return self._fail(target, f"{type(exc).__name__}: {exc}")

        canonical_url = str(getattr(content, "canonical_url", "") or "").strip() or None
        # 复审修复：状态库的 resolved_url 优先取 canonical（页面自报的权威地址）；
        # 页面没有 canonical 时退回重定向最终地址。两者都会写进正文 frontmatter。
        authoritative_url = canonical_url or final_url

        target_path = self._target_path(target)
        text = render_link_markdown(
            url=str(target.url),
            resolved_url=final_url,
            title=content.title,
            description=content.description,
            domain=domain or None,
            handler=content.handler,
            body=content.body,
            canonical_url=canonical_url,
        )
        try:
            written = self._write(target_path, text)
        except OSError as exc:
            return self._fail(target, f"cannot write {target_path.name}: {exc}")

        self._record(
            LinkUpdate(
                tweet_id=target.tweet_id,
                url=target.url,
                status=LinkFetchStatus.FETCHED.value,
                resolved_url=authoritative_url,
                title=_shorten_title(content.title),
                content_path=str(target_path),
                error_message=(
                    None if content.body.strip() else "note: no body text extracted"
                ),
            )
        )
        return ("fetched" if written else "unchanged"), None

    def _skip(self, target: LinkTarget, reason: str) -> tuple[str, None]:
        """策略性跳过：写 `SKIPPED` + 原因，不累加 `attempts`。"""

        logger.debug("skip %s: %s", target.url, reason)
        self._record(
            LinkUpdate(
                tweet_id=target.tweet_id,
                url=target.url,
                status=LinkFetchStatus.SKIPPED.value,
                error_message=f"skipped: {reason}",
            )
        )
        return "skipped", None

    def _fail(self, target: LinkTarget, reason: str) -> tuple[str, str]:
        """抓取/抽取失败：原始 URL 原样保留，只记录原因并累加尝试次数。

        复审修复：按 :meth:`_stale_fields_to_clear` 的规则决定是否清空"上一次成功"的
        `resolved_url` / `title` / `content_path`，避免出现"FAILED + 旧正文文件"的歧义状态。
        """

        clear_fields = self._stale_fields_to_clear(target)
        logger.debug("fail %s: %s (clear=%s)", target.url, reason, clear_fields or "none")
        self._record(
            LinkUpdate(
                tweet_id=target.tweet_id,
                url=target.url,
                status=LinkFetchStatus.FAILED.value,
                error_message=reason,
                count_attempt=True,
                clear_fields=clear_fields,
            )
        )
        return "failed", reason

    def _stale_fields_to_clear(self, target: LinkTarget) -> tuple[str, ...]:
        """复审修复：失败时是否丢弃"上一次成功"的正文指针 / 标题 / 权威地址。

        规则：
        * `--force` 重抓失败 → 清空（用户明确要求新内容，旧内容不得冒充当前结果）；
        * 尝试次数已达 `external.max_attempts` → 清空（不再重试，留着旧文件只会误导）；
        * 普通瞬时失败且仍有重试余地 → **保留**上一次成功正文，只记 `FAILED`。
        """

        if self._force:
            return STALE_LINK_FIELDS
        attempts = max(0, int(target.attempts or 0)) + 1
        if attempts >= max(1, int(self._options.max_attempts)):
            return STALE_LINK_FIELDS
        return ()

    # ── 写盘与落库 ──────────────────────────────────────────────────────────

    def _target_path(self, target: LinkTarget) -> Path:
        directory = link_dir_for(
            target.tweet_id, target.created_at, self._options.links_subdir
        )
        return self._knowledge_dir / directory / link_content_name(link_key_for(target.url))

    def _existing_content_path(self, target: LinkTarget) -> Path | None:
        """返回"知识库内且真实存在"的正文路径；否则 None（缺失/越界都重抓）。"""

        raw = str(target.content_path or "").strip()
        if not raw:
            return None
        candidate = Path(raw)
        if not candidate.is_file():
            return None
        try:
            candidate.resolve().relative_to(self._knowledge_dir.resolve())
        except ValueError:
            # 知识库之外的路径一律不信任（与 Phase 8 的审计结论同一原则）。
            return None
        return candidate

    def _write(self, path: Path, text: str) -> bool:
        """写正文文件；内容一致则跳过。返回"是否真的写了"（dry-run 视为写出）。"""

        if self._dry_run:
            return True
        if path.is_file():
            try:
                if path.read_text(encoding="utf-8") == text:
                    return False
            except OSError:  # 读失败按"需要重写"处理，不阻断这一条
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:  # pragma: no cover - 清理失败不应影响结果
                    logger.warning("could not remove temporary file %s", tmp)
        return True

    def _record(self, update: LinkUpdate) -> None:
        if self._dry_run or self._updater is None:
            return
        self._updater(update)


def _shorten_title(title: str | None) -> str | None:
    """标题入库前截断（`error_message` 之外的字段没有数据库层截断保护）。"""

    text = str(title or "").strip()
    if not text:
        return None
    return text[:MAX_TITLE_LENGTH]
