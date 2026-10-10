"""CLI 入口层（Phase 6）。

命令
----
* `sync`    —— 可选调用上游采集，然后幂等入库并打印报告（M2 的验收入口）
* `process` —— 逐条渲染 Markdown 到知识库 `YYYY/MM/`（Phase 7）
* `media`   —— 把上游媒体缓存本地化到知识库 `assets/{tweet_id}/` 并回写 `media.local_path`（Phase 8）
* `links`   —— 抓取外链正文到 `assets/{tweet_id}/links/` 并回写 `external_links`（Phase 9）
* `status`  —— 只读展示配置、状态库与上游数据现状
* `doctor`  —— 环境自检（配置 / 上游可执行 / 上游数据 / 数据库 schema / 日志目录）

流水线顺序：`sync` → `media` → `links` → `process`（`process` 会读取 `media` 与 `links`
写入的知识库内路径）。

约定
----
* 业务算法不写在这里：采集在 `src/collector/`、入库在 `src/ingest/`。
* 退出码：0 成功、1 业务失败、2 配置或用法错误、3 上游失败。
* 输出只用 ASCII 标记（`[ok]`/`[warn]`/`[fail]`），避免 GBK 控制台编码异常。
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.collector import FieldTheoryAdapter
from src.collector.base import CollectorError, MediaEntry, UpstreamBookmark
from src.config import AppConfig, ConfigError, ExternalOptions, load_config
from src.database import (
    BookmarkRecord,
    BookmarkRepository,
    connect,
    parse_iso,
    schema_status,
    utc_now_iso,
)
from src.ingest import Ingestor, IngestStats
from src.canonical.validate import CanonicalValidationError
from src.collector.base import CollectorError
from src.collector.fieldtheory.adapter import FieldTheoryCollector
from src.normalizer.fieldtheory import FieldTheoryNormalizer
from src.storage.json_projection import write_all_canonical_json
from src.storage.markdown_projection import write_all_markdown
from src.storage.rebuild import (
    RUNTIME_RESET_NOTE,
    RebuildError,
    rebuild_index,
    scan_normalized,
)

__all__ = ["EXIT_OK", "EXIT_FAILURE", "EXIT_CONFIG", "EXIT_UPSTREAM", "build_parser", "main"]

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2
EXIT_UPSTREAM = 3

DEFAULT_LOG_LEVEL = "INFO"
logger = logging.getLogger("xbook.cli")


def build_parser() -> argparse.ArgumentParser:
    """构造 argparse 解析器（各子命令的参数集中在此，便于 `--help` 自查）。"""

    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="X Bookmark Knowledge Pipeline CLI",
    )
    parser.add_argument("--config", help="配置路径（默认 config/config.yaml）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出 DEBUG 日志")
    parser.add_argument("-q", "--quiet", action="store_true", help="只输出报告，不输出日志")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="采集（可选）并入库")
    sync.add_argument("--skip-collect", action="store_true", help="跳过上游 sync，只入库已有数据")
    sync.add_argument("--continue", dest="continue_previous", action="store_true", help="上游 --continue（续跑翻页）")
    sync.add_argument("--rebuild", action="store_true", help="上游 --rebuild（全量重爬）")
    sync.add_argument("--gaps", action="store_true", help="上游 --gaps（补全 article / quote）")
    sync.add_argument("--media", action="store_true", help="本次采集下载媒体（覆盖配置）")
    sync.add_argument("--max-pages", type=int, help="上游 --max-pages N")
    sync.add_argument("--limit", type=int, help="只入库前 N 条（演练用）")

    process = sub.add_parser("process", help="为已入库书签生成 Markdown（Phase 7）")
    process.add_argument("--tweet-id", help="只处理指定 tweet_id")
    process.add_argument("--overwrite", action="store_true", help="允许覆盖已存在的 Markdown")
    process.add_argument("--no-status", action="store_true", help="渲染但不同步数据库状态（诊断）")

    media = sub.add_parser("media", help="把上游媒体本地化到知识库 assets/（Phase 8）")
    media.add_argument("--tweet-id", help="只处理指定 tweet_id")
    media.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析并报告将要复制的内容，不写文件、不写数据库",
    )

    links = sub.add_parser("links", help="抓取外链正文到知识库 assets/<tweet_id>/links/（Phase 9）")
    links.add_argument("--tweet-id", help="只处理指定 tweet_id")
    links.add_argument("--limit", type=int, help="只处理前 N 条外链（演练用）")
    links.add_argument("--force", action="store_true", help="连已 FETCHED 的外链也重新抓取")
    links.add_argument(
        "--dry-run",
        action="store_true",
        help="只抓取并报告结果，不写文件、不写数据库",
    )

    normalize = sub.add_parser(
        "normalize",
        help="把上游原始数据规范化为 Canonical JSON（默认只演练）",
        description=(
            "读取上游 bookmarks.jsonl（+ data/raw/ 富化快照），经 Canonical 契约校验后写出\n"
            "data/normalized/{tweet_id}.json（原子写 + content_hash 幂等）。\n\n"
            "默认**只演练**：不创建、不修改任何文件；确认无误后加 --apply 落盘。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    normalize.add_argument("--upstream-dir", help="上游目录（默认 config 的 upstream_data_dir，回退 <data_dir>/upstream）")
    normalize.add_argument("--raw-dir", help="富化快照目录（默认配置的 raw_dir）")
    normalize.add_argument("--normalized-dir", help="输出目录（默认 <data_dir>/normalized）")
    normalize.add_argument("--limit", type=int, help="只处理前 N 条（演练用）")
    normalize.add_argument("--apply", action="store_true", help="真正落盘（默认只演练）")

    render = sub.add_parser(
        "render",
        help="把 Canonical JSON 渲染为知识库 Markdown（默认只演练）",
        description=(
            "读取 data/normalized/*.json，渲染到 knowledge/X-Bookmarks/{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md。\n\n"
            "**内容不同则不覆盖**（AGENTS §14）：内容相同跳过；不同则记为冲突且原文件保持不变，\n"
            "仅在显式 --overwrite 时改写。默认**只演练**：不创建、不修改任何文件。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    render.add_argument("--normalized-dir", help="Canonical JSON 目录（默认 <data_dir>/normalized）")
    render.add_argument("--knowledge-dir", help="知识库目录（默认配置的 knowledge_dir）")
    render.add_argument("--overwrite", action="store_true", help="允许覆盖内容不同的既有 Markdown")
    render.add_argument("--apply", action="store_true", help="真正落盘（默认只演练）")

    status = sub.add_parser("status", help="只读状态展示")
    status.add_argument("--json", action="store_true", help="以 JSON 输出")

    sub.add_parser("doctor", help="环境自检")

    rebuild = sub.add_parser(
        "rebuild-index",
        help="从 normalized/*.json 重建 SQLite 内容索引（删库重建）",
        description=(
            "扫描 normalized/*.json（CanonicalBookmark）重建 SQLite 内容索引。\n\n"
            + RUNTIME_RESET_NOTE
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    rebuild.add_argument("--normalized-dir", help="Canonical JSON 目录（默认 <data_dir>/normalized）")
    rebuild.add_argument("--raw-dir", help="原始快照目录（填充 raw_json_path；默认配置的 raw_dir）")
    rebuild.add_argument("--apply", action="store_true", help="真正执行（默认只演练并报告，不改任何文件）")
    rebuild.add_argument(
        "--in-place",
        action="store_true",
        help="不删库：按 content_hash 幂等刷新内容索引，运行态原样保留",
    )
    rebuild.add_argument("--no-backup", action="store_true", help="重建前不备份旧库（默认备份为 state.db.bak-<UTC>）")
    rebuild.add_argument(
        "--db",
        help="覆盖索引库路径（默认配置的 state_db）——用于在临时库上验收，避免写入真实 data/state/",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口；返回进程退出码。"""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return EXIT_CONFIG

    handlers = _configure_logging(config, verbose=args.verbose, quiet=args.quiet)
    try:
        if config.unknown_keys:
            logger.warning("unknown config keys ignored: %s", ", ".join(config.unknown_keys))

        dispatch = {
            "sync": _cmd_sync,
            "process": _cmd_process,
            "media": _cmd_media,
            "links": _cmd_links,
            "status": _cmd_status,
            "doctor": _cmd_doctor,
            "rebuild-index": _cmd_rebuild_index,
            "normalize": _cmd_normalize,
            "render": _cmd_render,
        }
        return dispatch[args.command](args, config)
    finally:
        # Windows 下必须关闭日志文件句柄，否则日志文件保持锁定（测试亦无法清理）。
        _teardown_logging(handlers)


# ── 日志 ─────────────────────────────────────────────────────────────────────


def _configure_logging(config: AppConfig, *, verbose: bool, quiet: bool) -> list[logging.Handler]:
    """控制台 + 按日文件日志（`data/logs/YYYY-MM-DD.log`）；返回新建的处理器。

    调用方必须在使用结束后调用 :func:`_teardown_logging` 关闭它们。
    """

    level_name = "DEBUG" if verbose else config.logging.level
    level = getattr(logging, str(level_name).upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    created: list[logging.Handler] = []

    if config.logging.console and not quiet:
        console = logging.StreamHandler(stream=sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)
        created.append(console)

    if config.logging.file_per_day:
        log_dir = config.paths.log_dir
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"{utc_now_iso()[:10]}.log"
            file_handler = logging.FileHandler(path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
            created.append(file_handler)
        except OSError as exc:  # 日志失败不应阻断命令
            print(f"[warn] cannot open log file in {log_dir}: {exc}", file=sys.stderr)

    return created


def _teardown_logging(handlers: Sequence[logging.Handler]) -> None:
    """从 root logger 摘除并关闭本次命令创建的处理器（幂等）。"""

    root = logging.getLogger()
    for handler in handlers:
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001 - 关闭失败不应影响退出码
            pass
    logging.shutdown()



def _build_adapter(config: AppConfig) -> FieldTheoryAdapter:
    return FieldTheoryAdapter(
        executable=config.collector.command,
        data_dir=config.collector.upstream_data_dir,
        retries=2,
    )


# ── sync ─────────────────────────────────────────────────────────────────────


def _cmd_sync(args: argparse.Namespace, config: AppConfig) -> int:
    adapter = _build_adapter(config)
    media_requested = bool(args.media) or config.collector.sync.media

    if not args.skip_collect:
        code = _collect_upstream(args, config, adapter, with_media=media_requested)
        if code != EXIT_OK:
            return code
    else:
        logger.info("upstream collection skipped by --skip-collect")

    try:
        artifacts = adapter.check_ready()
    except CollectorError as exc:
        print(f"[fail] upstream data unavailable: {exc}", file=sys.stderr)
        return EXIT_UPSTREAM
    if not artifacts.ready:
        print(
            f"[fail] no upstream bookmarks found at {artifacts.data_dir}; "
            "run `python -m src.cli sync` without --skip-collect first",
            file=sys.stderr,
        )
        return EXIT_UPSTREAM

    try:
        bookmarks: Sequence[UpstreamBookmark] = adapter.read_bookmarks()
    except CollectorError as exc:
        print(f"[fail] cannot read upstream bookmarks: {exc}", file=sys.stderr)
        return EXIT_UPSTREAM
    if args.limit is not None and args.limit >= 0:
        bookmarks = bookmarks[: args.limit]

    enrichment = _load_enrichment(adapter)
    media_entries = _load_media_entries(adapter)

    connection = connect(config.paths.state_db_path)
    try:
        repository = BookmarkRepository(connection)
        ingestor = Ingestor(repository, config.paths.raw_dir)
        stats = ingestor.run(bookmarks, enrichment=enrichment, media=media_entries)
        last_synced = _max_last_synced_at(connection)
    finally:
        connection.close()

    _print_report(config, artifacts, stats, len(enrichment), last_synced)
    if stats.errors:
        for tweet_id, message in stats.errors[:5]:
            print(f"[fail] {tweet_id}: {message}", file=sys.stderr)
    return EXIT_OK if stats.ok else EXIT_FAILURE


def _cmd_process(args: argparse.Namespace, config: AppConfig) -> int:
    """为已入库书签生成 Markdown；推进 `COLLECTED -> PROCESSED` 并记录产物路径。"""

    from src.markdown import MarkdownWriter, RenderOptions

    knowledge_dir = config.paths.knowledge_dir
    section = config.section("markdown")
    include_sections = section.get("include_sections") if isinstance(section.get("include_sections"), list) else None
    options = RenderOptions(
        filename_pattern=str(section.get("filename_pattern") or "{yyyymmdd}-{tweet_id}.md"),
        frontmatter=bool(section.get("frontmatter", True)),
        include_sections=tuple(include_sections) if include_sections else RenderOptions().include_sections,
        overwrite_existing=bool(args.overwrite),
    )

    # 确定要处理的 tweet_id 集合：处理全部书签，让写盘层用内容比对判断
    # written/unchanged/conflict/failed（幂等）。若只想处理新增，可叠加状态过滤。
    connection = connect(config.paths.state_db_path)
    try:
        repository = BookmarkRepository(connection)
        if args.tweet_id:
            record = repository.get_bookmark(args.tweet_id)
            tweet_ids = [args.tweet_id] if record is not None else []
        else:
            tweet_ids = [r.tweet_id for r in repository.list_bookmarks()]
    finally:
        connection.close()

    if not tweet_ids:
        print(f"[warn] no bookmarks to process at {config.paths.state_db_path}", file=sys.stderr)
        return EXIT_OK

    def status_updater(tweet_id: str, status: str, markdown_path: str | None) -> None:
        """推进状态并记录产物路径；upsert 只更新非 None 字段，保留其余内容与计数。"""

        conn = connect(config.paths.state_db_path)
        try:
            repo = BookmarkRepository(conn)
            repo.set_status(tweet_id, status, error_message=None)
            if markdown_path:
                repo.upsert_bookmark(
                    BookmarkRecord(tweet_id=tweet_id, markdown_path=markdown_path)
                )
        finally:
            conn.close()

    # Phase 8：只把"位于知识库内且真实存在"的媒体路径交给渲染层，
    # 旧缓存路径（如 C:\...\.fieldtheory\...）与缺失文件一律回退远程 URL。
    media_paths = _local_media_paths(config, tweet_ids)
    # Phase 9：同理，只有知识库内的外链正文才会被 `## external_links` 引用。
    link_details = _local_link_details(config, tweet_ids)

    writer = MarkdownWriter(
        knowledge_dir,
        raw_dir=config.paths.raw_dir,
        options=options,
        status_updater=None if args.no_status else status_updater,
        media_lookup=media_paths.get,
        link_lookup=link_details.get,
    )
    stats = writer.run(tweet_ids)

    print("Markdown report")
    print(f"  knowledge dir : {knowledge_dir}")
    print(f"  local media   : {len(media_paths)} bookmark(s)")
    print(f"  links known   : {len(link_details)} bookmark(s)")
    print(f"  attempted     : {stats.attempted}")
    print(f"  written       : {stats.written}")
    print(f"  unchanged     : {stats.unchanged}")
    print(f"  conflicts     : {stats.conflicts}")
    print(f"  failed        : {stats.failed}")
    for tweet_id, message in stats.errors[:5]:
        print(f"[fail] {tweet_id}: {message}", file=sys.stderr)
    return EXIT_OK if stats.ok else EXIT_FAILURE


def _local_media_paths(config: AppConfig, tweet_ids: Sequence[str]) -> dict[str, dict[str, str]]:
    """`{tweet_id: {source_url: 相对 knowledge_dir 的 POSIX 路径}}`，供 `process` 渲染使用。

    只接受"位于知识库内且真实存在"的文件：上游旧缓存里的绝对路径（审计发现的历史遗留）
    因为不在 `knowledge_dir` 下会被排除，Markdown 于是回退远程 URL，
    **绝不引用知识库之外的文件**。
    """

    knowledge_root = config.paths.knowledge_dir.resolve()
    found: dict[str, dict[str, str]] = {}
    connection = connect(config.paths.state_db_path)
    try:
        repository = BookmarkRepository(connection)
        for tweet_id in tweet_ids:
            paths: dict[str, str] = {}
            for media in repository.list_media(tweet_id):
                if not media.source_url or not media.local_path:
                    continue
                candidate = Path(media.local_path)
                if not candidate.is_file():
                    continue
                try:
                    relative = candidate.resolve().relative_to(knowledge_root)
                except ValueError:
                    continue
                paths[media.source_url] = relative.as_posix()
            if paths:
                found[tweet_id] = paths
    finally:
        connection.close()
    return found


def _cmd_media(args: argparse.Namespace, config: AppConfig) -> int:
    """把上游媒体缓存本地化到知识库 `assets/`，并回写 `media.local_path`（Phase 8）。"""

    from src.config import load_media_options
    from src.media import MediaLocalizer, MediaSource, MediaUpdate

    options = load_media_options(config.section("media"))
    adapter = _build_adapter(config)
    upstream_media_dir = adapter.media_dir

    connection = connect(config.paths.state_db_path)
    try:
        repository = BookmarkRepository(connection)
        if args.tweet_id:
            record = repository.get_bookmark(args.tweet_id)
            bookmarks = [record] if record is not None else []
        else:
            bookmarks = repository.list_bookmarks()
        sources = [
            MediaSource(
                tweet_id=bookmark.tweet_id,
                media_key=media.media_key,
                media_type=media.media_type,
                source_url=media.source_url,
                local_path=media.local_path,
                upstream_status=media.download_status,
                created_at=bookmark.created_at,
            )
            for bookmark in bookmarks
            for media in repository.list_media(bookmark.tweet_id)
        ]
    finally:
        connection.close()

    if not sources:
        print(f"[warn] no media rows to localise at {config.paths.state_db_path}", file=sys.stderr)
        return EXIT_OK

    if not options.download:
        print(
            "[warn] media.download=false; media localisation is disabled by configuration",
            file=sys.stderr,
        )

    def updater(update: MediaUpdate) -> None:
        """逐条落库；与 `process` 一致，每条自开连接（避免长事务锁住状态库）。"""

        conn = connect(config.paths.state_db_path)
        try:
            BookmarkRepository(conn).set_media_status(
                update.tweet_id,
                update.media_key,
                update.status,
                local_path=update.local_path,
                error_message=update.error_message,
                count_attempt=update.count_attempt,
            )
        finally:
            conn.close()

    localizer = MediaLocalizer(
        config.paths.knowledge_dir,
        upstream_media_dir,
        options=options,
        updater=None if args.dry_run else updater,
        upstream_index=_upstream_media_index(adapter),
        dry_run=bool(args.dry_run),
    )
    stats = localizer.run(sources)

    print("Media report")
    print(f"  knowledge dir : {config.paths.knowledge_dir}")
    print(f"  upstream media: {upstream_media_dir}")
    if args.dry_run:
        print("  dry run       : true (no file or database change)")
    print(f"  attempted     : {stats.attempted}")
    print(f"  copied        : {stats.copied}")
    print(f"  unchanged     : {stats.unchanged}")
    print(f"  skipped       : {stats.skipped}")
    print(f"  failed        : {stats.failed}")
    for label, message in stats.errors[:5]:
        print(f"[fail] {label}: {message}", file=sys.stderr)
    return EXIT_OK if stats.ok else EXIT_FAILURE


def _local_link_details(
    config: AppConfig, tweet_ids: Sequence[str]
) -> dict[str, dict[str, dict[str, object]]]:
    """`{tweet_id: {url: 详情}}`，供 `process` 渲染 `## external_links`（Phase 9）。

    只接受"位于知识库内且真实存在"的 `content_path`：路径缺失或越界时只保留状态与标题，
    Markdown 里不会引用知识库之外的文件（与 Phase 8 媒体路径同一原则）。
    `PENDING` 行也照常返回——渲染层会把它们显示成 Phase 7 的纯 URL 列表。
    """

    knowledge_root = config.paths.knowledge_dir.resolve()
    found: dict[str, dict[str, dict[str, object]]] = {}
    connection = connect(config.paths.state_db_path)
    try:
        repository = BookmarkRepository(connection)
        for tweet_id in tweet_ids:
            details: dict[str, dict[str, object]] = {}
            for link in repository.list_external_links(tweet_id):
                detail: dict[str, object] = {
                    "title": link.title,
                    "resolved_url": link.resolved_url,
                    "fetch_status": link.fetch_status,
                    "error_message": link.error_message,
                }
                if link.content_path:
                    candidate = Path(link.content_path)
                    if candidate.is_file():
                        try:
                            detail["content_path"] = candidate.resolve().relative_to(
                                knowledge_root
                            ).as_posix()
                        except ValueError:
                            pass  # 知识库之外：不引用
                details[link.url] = detail
            if details:
                found[tweet_id] = details
    finally:
        connection.close()
    return found


def _build_link_fetcher(config: AppConfig, options: ExternalOptions) -> Any:
    """构造外链抓取器（单独一层便于测试注入 fake transport）。"""

    from src.external import HttpFetcher

    return HttpFetcher(
        timeout_seconds=options.timeout_seconds,
        retries=options.retries,
        backoff_seconds=options.backoff_seconds,
        max_bytes=options.max_bytes,
        max_redirects=options.max_redirects,
        user_agent=options.user_agent,
        block_non_public_hosts=options.block_non_public_hosts,
        allow_hosts=options.allow_hosts,
    )


def _cmd_links(args: argparse.Namespace, config: AppConfig) -> int:
    """抓取外链正文到知识库 `assets/{tweet_id}/links/` 并回写 `external_links`（Phase 9）。"""

    from src.config import load_external_options
    from src.external import LinkResolver, LinkTarget, build_handlers

    options = load_external_options(config.section("external"))
    if not options.enabled:
        print(
            "[warn] external.enabled=false; external link resolution is disabled by configuration",
            file=sys.stderr,
        )
        return EXIT_OK

    handlers, unimplemented = build_handlers(options.handlers)
    if unimplemented:
        print(
            f"[warn] external.handlers: not implemented yet, ignored: {', '.join(unimplemented)}",
            file=sys.stderr,
        )

    connection = connect(config.paths.state_db_path)
    try:
        repository = BookmarkRepository(connection)
        if args.tweet_id:
            record = repository.get_bookmark(args.tweet_id)
            bookmarks = [record] if record is not None else []
        else:
            bookmarks = repository.list_bookmarks()
        targets = [
            LinkTarget(
                tweet_id=bookmark.tweet_id,
                url=link.url,
                domain=link.domain,
                created_at=bookmark.created_at,
                fetch_status=link.fetch_status,
                content_path=link.content_path,
                attempts=link.attempts,
                title=link.title,
            )
            for bookmark in bookmarks
            for link in repository.list_external_links(bookmark.tweet_id)
        ]
    finally:
        connection.close()

    if args.limit is not None and args.limit >= 0:
        targets = targets[: args.limit]
    if not targets:
        print(f"[warn] no external links to resolve at {config.paths.state_db_path}", file=sys.stderr)
        return EXIT_OK

    def updater(update: Any) -> None:
        """逐条落库；与 `media` 一致，每条自开连接（避免长事务锁住状态库）。"""

        conn = connect(config.paths.state_db_path)
        try:
            BookmarkRepository(conn).set_link_status(
                update.tweet_id,
                update.url,
                update.status,
                resolved_url=update.resolved_url,
                title=update.title,
                content_path=update.content_path,
                error_message=update.error_message,
                count_attempt=update.count_attempt,
                clear_fields=update.clear_fields,
            )
        finally:
            conn.close()

    resolver = LinkResolver(
        config.paths.knowledge_dir,
        options=options,
        fetcher=_build_link_fetcher(config, options),
        handlers=handlers,
        updater=None if args.dry_run else updater,
        dry_run=bool(args.dry_run),
        force=bool(args.force),
    )
    stats = resolver.run(targets)

    print("Link report")
    print(f"  knowledge dir : {config.paths.knowledge_dir}")
    print(f"  handlers      : {', '.join(sorted(handlers)) or 'none'}")
    if args.dry_run:
        print("  dry run       : true (no file or database change)")
    if args.force:
        print("  force         : true (already fetched links are refetched)")
    print(f"  attempted     : {stats.attempted}")
    print(f"  fetched       : {stats.fetched}")
    print(f"  unchanged     : {stats.unchanged}")
    print(f"  skipped       : {stats.skipped}")
    print(f"  failed        : {stats.failed}")
    for label, message in stats.errors[:5]:
        print(f"[fail] {label}: {message}", file=sys.stderr)
    return EXIT_OK if stats.ok else EXIT_FAILURE


def _upstream_media_index(adapter: FieldTheoryAdapter) -> dict[str, str]:
    """`media-manifest.json` 的 `sourceUrl -> localPath` 索引（清单不可用时为空）。

    有了它，即便 `media.local_path` 已被改写成知识库路径，Phase 8 仍能重新定位源文件。
    """

    try:
        manifest = adapter.read_media_manifest()
    except CollectorError as exc:
        logger.warning("media manifest unavailable, source index is empty: %s", exc)
        return {}
    return {
        entry.source_url: entry.local_path
        for entry in manifest.entries
        if entry.source_url and entry.local_path
    }


def _collect_upstream(
    args: argparse.Namespace,
    config: AppConfig,
    adapter: FieldTheoryAdapter,
    *,
    with_media: bool,
) -> int:
    """调用上游 `fieldtheory sync`；失败时返回非零退出码，不继续入库。"""

    sync_config = config.collector.sync
    extra_args = list(sync_config.extra_args)
    if with_media and sync_config.skip_profile_images:
        extra_args.insert(0, "--skip-profile-images")

    browser = config.collector.auth.browser if config.collector.auth.method == "firefox" else None
    if config.collector.auth.method == "cookies":
        # 未实现：手工 Cookie 需要把 ct0/auth_token 传给上游 `--cookies`，
        # 而这两个值等价于密码，本项目暂不实现该路径（见 README 第 7 节）。
        print(
            "[fail] collector.auth.method=cookies is not implemented yet; "
            "use method: firefox (verified) or run the upstream CLI manually",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        result = adapter.sync(
            browser=browser,
            with_media=with_media,
            rebuild=bool(args.rebuild),
            continue_previous=bool(args.continue_previous),
            gaps=bool(args.gaps),
            max_pages=args.max_pages,
            max_minutes=sync_config.max_minutes,
            delay_ms=sync_config.delay_ms,
            extra_args=extra_args,
        )
    except CollectorError as exc:
        print(f"[fail] upstream sync failed: {exc}", file=sys.stderr)
        return EXIT_UPSTREAM

    if not result.ok:
        tail = " ".join((result.stderr or result.stdout or "").split())[-300:]
        print(
            f"[fail] upstream sync exited with {result.returncode} "
            f"(attempts={result.attempts}, timed_out={result.timed_out}): {tail}",
            file=sys.stderr,
        )
        return EXIT_UPSTREAM

    logger.info(
        "upstream sync ok (attempts=%d, %.1fs)", result.attempts, result.duration_seconds
    )
    return EXIT_OK


def _load_enrichment(adapter: FieldTheoryAdapter) -> Mapping[str, Any]:
    """读取富化记录（Article 正文的唯一来源）。失败时降级为空并继续入库。"""

    try:
        records = adapter.list_enriched()
    except CollectorError as exc:
        logger.warning("enrichment unavailable, continuing without it: %s", exc)
        return {}
    logger.info("enrichment records: %d", len(records))
    return {record.tweet_id: record for record in records}


def _load_media_entries(adapter: FieldTheoryAdapter) -> Sequence[MediaEntry]:
    """读取媒体清单；文件不存在时按"无媒体"处理。"""

    try:
        manifest = adapter.read_media_manifest()
    except CollectorError as exc:
        logger.warning("media manifest unavailable, continuing without it: %s", exc)
        return ()
    logger.info("media manifest entries: %d", len(manifest.entries))
    return manifest.entries


def _max_last_synced_at(connection: sqlite3.Connection) -> str | None:
    row = connection.execute("SELECT MAX(last_synced_at) FROM bookmarks").fetchone()
    return row[0] if row is not None else None


def _print_report(
    config: AppConfig,
    artifacts: Any,
    stats: IngestStats,
    enrichment_count: int,
    last_synced: str | None,
) -> None:
    """打印同步报告（Fetched/New/Skipped/Failed + 状态分布）。"""

    print("")
    print("Sync report")
    print(f"  finished at   : {utc_now_iso()}")
    print(f"  upstream dir  : {artifacts.data_dir}")
    print(f"  upstream rows : {artifacts.record_count}")
    print(f"  enrichment    : {enrichment_count} record(s) from `list --json`")
    print(f"  fetched       : {stats.fetched}")
    print(f"  new           : {stats.new}")
    print(f"  updated       : {stats.updated}")
    print(f"  unchanged     : {stats.unchanged}")
    print(f"  failed        : {stats.failed}")
    print(f"  transitions   : NEW/FAILED -> COLLECTED = {stats.collected_transitions}")
    print(f"  raw archives  : {stats.raw_written} written, {stats.raw_skipped} unchanged")
    print(
        f"  media rows    : {stats.media_new} new, {stats.media_updated} updated, "
        f"{stats.media_unchanged} unchanged"
    )
    print(
        f"  link rows     : {stats.links_new} new, {stats.links_updated} updated, "
        f"{stats.links_unchanged} unchanged"
    )
    counts = " | ".join(f"{key} {value}" for key, value in sorted(stats.status_counts.items()))
    print(f"  db status     : {counts}")
    print(f"  last synced   : {last_synced or '-'}")
    print(f"  state db      : {config.paths.state_db_path}")
    print("")


# ── status ───────────────────────────────────────────────────────────────────


def _canonical_status(config: Config) -> dict[str, object]:
    """`status --json` 的 `canonical` 分区。

    单独成函数的原因：该分区是**机器可读契约**的一部分（见
    `tests/test_cli_json_contract.py`），提取后变异测试才能验证它确实被断言保护。
    """

    normalized_dir = config.paths.data_dir / "normalized"
    return {
        "normalized_dir": str(normalized_dir),
        "normalized_files": (
            len([item for item in normalized_dir.glob("*.json")])
            if normalized_dir.is_dir()
            else 0
        ),
        "pipeline": ["normalize", "render", "rebuild-index"],
    }


def _cmd_status(args: argparse.Namespace, config: AppConfig) -> int:
    """只读展示：配置、状态库、上游数据现状。"""

    import json

    adapter = _build_adapter(config)
    connection = connect(config.paths.state_db_path)
    try:
        repository = BookmarkRepository(connection)
        payload: dict[str, Any] = {
            "config": {
                "source": str(config.source_path) if config.source_path else None,
                "project_root": str(config.project_root),
                "state_db": str(config.paths.state_db_path),
                "raw_dir": str(config.paths.raw_dir),
                "log_dir": str(config.paths.log_dir),
                "knowledge_dir": str(config.paths.knowledge_dir),
                "unknown_keys": list(config.unknown_keys),
            },
            "database": {
                "schema": schema_status(connection),
                "counts": repository.count_by_status(),
                "total": repository.count_bookmarks(),
                "links": {
                    "counts": repository.count_external_links_by_status(),
                    "total": repository.count_external_links(),
                },
                "last_synced_at": _max_last_synced_at(connection),
            },
            "upstream": {
                "executable": list(config.collector.command),
                "data_dir": str(adapter.data_dir),
            },
        }
        # Canonical 流水线（Phase 4–5）现状：只读统计，不写盘
        payload["canonical"] = _canonical_status(config)
    finally:
        connection.close()

    try:
        artifacts = adapter.check_ready()
        payload["upstream"].update(
            {
                "ready": artifacts.ready,
                "records": artifacts.record_count,
                "jsonl_exists": artifacts.jsonl_exists,
                "jsonl_bytes": artifacts.jsonl_bytes,
                "jsonl_modified_at": (
                    artifacts.jsonl_modified_at.isoformat()
                    if artifacts.jsonl_modified_at
                    else None
                ),
                "manifest_exists": artifacts.manifest_exists,
                "database_exists": artifacts.database_exists,
            }
        )
    except CollectorError as exc:
        payload["upstream"]["error"] = str(exc)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK

    config_info = payload["config"]
    print("Status")
    print(f"  config        : {config_info['source'] or '(defaults; config/config.yaml missing)'}")
    print(f"  project root  : {config_info['project_root']}")
    print(f"  state db      : {config_info['state_db']}")
    db = payload["database"]
    print(
        f"  schema        : v{db['schema']['current_version']} "
        f"(expected v{db['schema']['expected_version']})"
    )
    print(f"  db total      : {db['total']}")
    canonical = payload.get("canonical") or {}
    print(
        f"  canonical     : {canonical.get('normalized_files', 0)} 个 normalized JSON"
        f" @ {canonical.get('normalized_dir', '(unknown)')}"
    )
    print(f"  db counts     : " + " | ".join(f"{k} {v}" for k, v in sorted(db["counts"].items())))
    links = db.get("links") or {"counts": {}, "total": 0}
    print(f"  db links      : {links['total']} total | " + " | ".join(
        f"{k} {v}" for k, v in sorted(links["counts"].items())
    ))
    print(f"  last synced   : {db['last_synced_at'] or '-'}")
    up = payload["upstream"]
    print(f"  upstream cmd  : {' '.join(up['executable'])}")
    print(f"  upstream dir  : {up['data_dir']}")
    if "error" in up:
        print(f"  upstream      : [fail] {up['error']}")
    else:
        marker = "[ok]" if up.get("ready") else "[warn]"
        print(
            f"  upstream      : {marker} records={up.get('records')} "
            f"manifest={up.get('manifest_exists')}"
        )
    if config.unknown_keys:
        print(f"  unknown keys  : {', '.join(config.unknown_keys)}")
    return EXIT_OK


# ── doctor ───────────────────────────────────────────────────────────────────


def _cmd_doctor(args: argparse.Namespace, config: AppConfig) -> int:
    """环境自检；任一"必需项"失败则返回非零退出码。"""

    results: list[tuple[str, bool, bool, str]] = []

    def check(name: str, ok: bool, detail: str, *, critical: bool = True) -> None:
        results.append((name, ok, critical, detail))

    check(
        "config file",
        config.source_path is not None,
        str(config.source_path) if config.source_path else "config/config.yaml not found",
    )
    check("project root", config.project_root.is_dir(), str(config.project_root))
    check("config version", config.version in (1,), f"version={config.version}")
    if config.unknown_keys:
        check("config keys", False, f"unknown: {', '.join(config.unknown_keys)}", critical=False)

    adapter = _build_adapter(config)
    try:
        executable_ok, executable_detail = True, " ".join(adapter.executable)
    except CollectorError as exc:
        executable_ok, executable_detail = False, str(exc)
    check("upstream executable", executable_ok, executable_detail)

    if executable_ok:
        try:
            check("upstream version", True, adapter.upstream_version(), critical=False)
        except CollectorError as exc:
            check("upstream version", False, str(exc), critical=False)

    try:
        artifacts = adapter.check_ready()
        check(
            "upstream data",
            artifacts.ready,
            f"records={artifacts.record_count} dir={artifacts.data_dir}",
            critical=False,
        )
    except CollectorError as exc:
        check("upstream data", False, str(exc), critical=False)

    try:
        connection = connect(config.paths.state_db_path)
        try:
            schema = schema_status(connection)
        finally:
            connection.close()
        check(
            "state database",
            bool(schema["up_to_date"]),
            f"schema v{schema['current_version']} at {config.paths.state_db_path}",
        )
    except Exception as exc:  # noqa: BLE001 - doctor 需要报告而不是抛出
        check("state database", False, f"{type(exc).__name__}: {exc}")

    log_ok, log_detail = _probe_writable_dir(config.paths.log_dir)
    check("log directory", log_ok, log_detail, critical=False)

    # Canonical 流水线（Phase 4–5）：只读检查 normalized 目录是否就绪
    normalized_dir = config.paths.data_dir / "normalized"
    if normalized_dir.is_dir():
        normalized_count = len(list(normalized_dir.glob("*.json")))
        check(
            "canonical normalized",
            True,
            f"{normalized_count} JSON at {normalized_dir}",
            critical=False,
        )
    else:
        check(
            "canonical normalized",
            False,
            f"缺失（先跑 `normalize --apply`；演练不会创建）：{normalized_dir}",
            critical=False,
        )

    upstream_dir = config.collector.upstream_data_dir or adapter.data_dir
    on_c_drive = str(upstream_dir).upper().startswith("C:")
    check(
        "upstream drive",
        not on_c_drive,
        str(upstream_dir) + (" (on C:, limited free space)" if on_c_drive else ""),
        critical=False,
    )

    print("Doctor")
    for name, ok, critical, detail in results:
        marker = "[ok]  " if ok else ("[fail]" if critical else "[warn]")
        print(f"  {marker} {name:<20} {detail}")
    failed_critical = [name for name, ok, critical, _ in results if critical and not ok]
    warnings = [name for name, ok, critical, _ in results if not critical and not ok]
    print("")
    if failed_critical:
        print(f"Doctor result: FAILED ({', '.join(failed_critical)})")
        return EXIT_FAILURE
    suffix = f" (warnings: {', '.join(warnings)})" if warnings else ""
    print(f"Doctor result: OK{suffix}")
    return EXIT_OK


def _probe_writable_dir(path: Path) -> tuple[bool, str]:
    """在目标目录建一个临时文件确认可写，随后立即删除。"""

    probe = path / ".write-probe"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, str(path)
    except OSError as exc:
        return False, f"{path}: {exc}"


def _cmd_rebuild_index(args: argparse.Namespace, config: AppConfig) -> int:
    """`rebuild-index`：从 `normalized/*.json` 重建内容索引（默认只演练）。"""

    normalized_dir = Path(args.normalized_dir) if args.normalized_dir else (
        config.paths.data_dir / "normalized"
    )
    raw_dir = Path(args.raw_dir) if args.raw_dir else config.paths.raw_dir
    db_path = Path(args.db) if getattr(args, "db", None) else config.paths.state_db_path

    try:
        report = rebuild_index(
            normalized_dir,
            db_path=db_path,
            apply=bool(args.apply),
            in_place=bool(args.in_place),
            backup=not args.no_backup,
            raw_dir=raw_dir,
        )
    except RebuildError as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return EXIT_CONFIG

    mode = "APPLY" if report.applied else "DRY-RUN"
    print(f"[{mode}] normalized: {report.plan.normalized_dir}")
    print(f"         index db  : {report.db_path}")
    print(f"         scanned   : {report.plan.scanned} 个 JSON（可索引 {report.plan.indexable}）")
    if report.applied:
        if report.in_place:
            print(f"         in-place  : inserted={report.inserted} updated={report.updated} "
                  f"unchanged={report.unchanged}（运行态保留）")
        else:
            print(f"         重建完成  : inserted={report.inserted}（运行态重置为初始态）")
            if report.backup_path:
                print(f"         旧库备份  : {report.backup_path}")
    else:
        print("         演练模式  : 未改任何文件；加 --apply 执行")
    if report.plan.failures:
        print(f"         failures  : {len(report.plan.failures)}")
        for name, reason in report.plan.failures[:10]:
            print(f"           - {name}: {reason}")
        return EXIT_FAILURE
    return EXIT_OK


def _cmd_normalize(args: argparse.Namespace, config: AppConfig) -> int:
    """`normalize`：上游 → Canonical JSON（默认只演练，不写盘）。"""

    upstream_dir = Path(args.upstream_dir) if args.upstream_dir else (
        config.collector.upstream_data_dir or (config.paths.data_dir / "upstream")
    )
    raw_dir = Path(args.raw_dir) if args.raw_dir else config.paths.raw_dir
    normalized_dir = Path(args.normalized_dir) if args.normalized_dir else (
        config.paths.data_dir / "normalized"
    )

    adapter = FieldTheoryAdapter(
        executable=config.collector.command, data_dir=upstream_dir, retries=2
    )
    collector = FieldTheoryCollector(adapter=adapter, raw_dir=raw_dir)
    try:
        raw_data = collector.collect()
    except CollectorError as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return EXIT_UPSTREAM
    except OSError as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return EXIT_FAILURE

    try:
        bookmarks = FieldTheoryNormalizer().normalize_and_validate(raw_data)
    except CanonicalValidationError as exc:
        print(f"[fail] canonical 校验失败: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    if args.limit:
        bookmarks = bookmarks[: max(0, args.limit)]

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] upstream : {upstream_dir}")
    print(f"         enrichment: {raw_dir}")
    print(f"         output    : {normalized_dir}")
    print(f"         canonical : {len(bookmarks)} 条通过校验"
          f"（富化警告 {len(getattr(collector, 'last_warnings', ()) or ())}）")
    if not args.apply:
        print("         演练模式  : 未创建/未修改任何文件；加 --apply 落盘")
        return EXIT_OK

    report = write_all_canonical_json(bookmarks, normalized_dir)
    created = sum(1 for outcome in report.outcomes if outcome.reason == "created")
    unchanged = sum(1 for outcome in report.outcomes if outcome.reason == "unchanged")
    print(f"         落盘完成  : created={created} unchanged={unchanged} "
          f"failures={len(report.failures)}")
    for label, reason in report.failures[:10]:
        print(f"           - {label}: {reason}")
    return EXIT_OK if report.ok else EXIT_FAILURE


def _cmd_render(args: argparse.Namespace, config: AppConfig) -> int:
    """`render`：Canonical JSON → Markdown（默认只演练；不覆盖内容不同的既有文件）。"""

    normalized_dir = Path(args.normalized_dir) if args.normalized_dir else (
        config.paths.data_dir / "normalized"
    )
    knowledge_dir = Path(args.knowledge_dir) if args.knowledge_dir else config.paths.knowledge_dir

    try:
        plan = scan_normalized(normalized_dir)
    except RebuildError as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return EXIT_CONFIG

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] normalized: {normalized_dir}")
    print(f"         knowledge : {knowledge_dir}")
    print(f"         scanned   : {plan.scanned} 个 JSON（可渲染 {plan.indexable}）")
    if plan.failures:
        print(f"         failures  : {len(plan.failures)}")
        for name, reason in plan.failures[:10]:
            print(f"           - {name}: {reason}")
    if not args.apply:
        print("         演练模式  : 未创建/未修改任何文件；加 --apply 落盘")
        return EXIT_FAILURE if plan.failures else EXIT_OK

    report = write_all_markdown(
        [entry.bookmark for entry in plan.entries], knowledge_dir, overwrite=args.overwrite
    )
    print(f"         渲染完成  : written={report.written} conflicts={report.conflicts} "
          f"failures={len(report.failures)}")
    for label, reason in report.failures[:10]:
        print(f"           - {label}: {reason}")
    return EXIT_OK if (report.ok and not plan.failures) else EXIT_FAILURE
