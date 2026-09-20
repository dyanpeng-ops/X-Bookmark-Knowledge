"""Adapter that reuses the upstream `fieldtheory` CLI as this project's Collector.

Design rules (see `research/architecture-decision.md` §2 and §5):

* The upstream CLI is the only integration point. Nothing imports upstream
  modules and nothing writes into the upstream data directory.
* Every upstream surface used here is either a documented command
  (`sync`, `list --json`, `show --json`) or a data file inside `FT_DATA_DIR`.
* Enrichment (article body, categories, quoted tweet, folders) is *not* in
  `bookmarks.jsonl`; it is only reachable through `list|show --json`.
* All output is validated against `collector.contract` before use.
* Failures are classified so the CLI layer can report them precisely.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import contract as _contract
from .base import (
    EnrichedBookmark,
    MediaEntry,
    MediaManifest,
    SyncRunResult,
    UpstreamArtifacts,
    UpstreamAuthError,
    UpstreamBookmark,
    UpstreamContractError,
    UpstreamExecutionError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)

__all__ = ["FieldTheoryAdapter"]

DEFAULT_EXECUTABLE = "fieldtheory"
DEFAULT_SYNC_TIMEOUT_SECONDS = 1800.0
DEFAULT_QUERY_TIMEOUT_SECONDS = 120.0
DEFAULT_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0

# Markers found in upstream output that mean "retrying may help".
# UNVERIFIED: only the auth markers below were produced by a real failing run;
# the network markers are a defensive allow-list.
_AUTH_MARKERS: tuple[str, ...] = (
    "couldn't connect to your browser session",
    "no ct0 csrf cookie found",
    "not logged into x",
    "appears invalid",
)
_TRANSIENT_MARKERS: tuple[str, ...] = (
    "etimedout",
    "econnreset",
    "econnrefused",
    "socket hang up",
    "fetch failed",
    "network error",
    "rate limit",
    "429",
    "502",
    "503",
    "504",
)


@dataclass(frozen=True)
class _RunOutcome:
    """Raw outcome of one process invocation."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    attempts: int
    timed_out: bool = False


class FieldTheoryAdapter:
    """Collector adapter around the upstream `fieldtheory` CLI."""

    def __init__(
        self,
        executable: str | Sequence[str] | None = None,
        data_dir: str | os.PathLike[str] | None = None,
        home_dir: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        sync_timeout_seconds: float = DEFAULT_SYNC_TIMEOUT_SECONDS,
        query_timeout_seconds: float = DEFAULT_QUERY_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._executable_spec = executable
        self._env_overrides = dict(env or {})
        self._home_dir = Path(home_dir).expanduser() if home_dir else Path.home()
        self._explicit_data_dir = Path(data_dir).expanduser() if data_dir else None
        self.sync_timeout_seconds = float(sync_timeout_seconds)
        self.query_timeout_seconds = float(query_timeout_seconds)
        self.retries = max(0, int(retries))
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        self._sleep = sleeper
        self._resolved_executable: tuple[str, ...] | None = None

    # ── paths ────────────────────────────────────────────────────────────────

    @property
    def data_dir(self) -> Path:
        """Upstream bookmarks directory (`FT_DATA_DIR` wins, then `~/.fieldtheory`)."""

        if self._explicit_data_dir is not None:
            return self._explicit_data_dir
        override = self._env_overrides.get("FT_DATA_DIR") or os.environ.get("FT_DATA_DIR")
        if override:
            return Path(override).expanduser()
        return self._home_dir / ".fieldtheory" / "bookmarks"

    @property
    def jsonl_path(self) -> Path:
        return self.data_dir / "bookmarks.jsonl"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "media-manifest.json"

    @property
    def meta_path(self) -> Path:
        return self.data_dir / "bookmarks-meta.json"

    @property
    def backfill_state_path(self) -> Path:
        return self.data_dir / "bookmarks-backfill-state.json"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "bookmarks.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def executable(self) -> tuple[str, ...]:
        """Resolved upstream command, e.g. ``('D:\\\\nodejs\\\\npm_global\\\\fieldtheory.CMD',)``."""

        if self._resolved_executable is None:
            self._resolved_executable = self._resolve_executable()
        return self._resolved_executable

    # ── readiness ────────────────────────────────────────────────────────────

    def check_ready(self) -> UpstreamArtifacts:
        """Validate the upstream data files and report their state."""

        jsonl = self.jsonl_path
        exists = jsonl.is_file()
        count = 0
        modified: datetime | None = None
        size = 0
        if exists:
            stat = jsonl.stat()
            size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            count = len(self.read_bookmarks())
        return UpstreamArtifacts(
            data_dir=str(self.data_dir),
            jsonl_path=str(jsonl),
            jsonl_exists=exists,
            jsonl_bytes=size,
            jsonl_modified_at=modified,
            manifest_path=str(self.manifest_path),
            manifest_exists=self.manifest_path.is_file(),
            database_path=str(self.database_path),
            database_exists=self.database_path.is_file(),
            record_count=count,
        )

    # ── collection ───────────────────────────────────────────────────────────

    def sync(
        self,
        browser: str | None = "firefox",
        with_media: bool = False,
        rebuild: bool = False,
        continue_previous: bool = False,
        gaps: bool = False,
        max_pages: int | None = None,
        target_adds: int | None = None,
        max_minutes: int | None = None,
        folders: bool = False,
        folder: str | None = None,
        delay_ms: int | None = None,
        extra_args: Sequence[str] = (),
        timeout_seconds: float | None = None,
    ) -> SyncRunResult:
        """Run one upstream `sync`.

        `continue_previous` maps to upstream `--continue` (resume a page-limited
        run); a plain incremental run stops after three stale pages, so paging
        through the whole history requires `--continue` or `--rebuild`.
        """

        args: list[str] = ["sync", "--yes"]
        if browser:
            args += ["--browser", browser]
        if not with_media:
            args.append("--no-media")
        if rebuild:
            args.append("--rebuild")
        if continue_previous:
            args.append("--continue")
        if gaps:
            args.append("--gaps")
        if folders:
            args.append("--folders")
        if folder:
            args += ["--folder", folder]
        if max_pages is not None:
            args += ["--max-pages", str(int(max_pages))]
        if target_adds is not None:
            args += ["--target-adds", str(int(target_adds))]
        if max_minutes is not None:
            args += ["--max-minutes", str(int(max_minutes))]
        if delay_ms is not None:
            args += ["--delay-ms", str(int(delay_ms))]
        args += [str(item) for item in extra_args]

        timeout = self.sync_timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        outcome = self._run(args, timeout=timeout, retry_transient=True)
        return SyncRunResult(
            command=outcome.command,
            returncode=outcome.returncode,
            duration_seconds=outcome.duration_seconds,
            attempts=outcome.attempts,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            timed_out=outcome.timed_out,
        )

    # ── upstream file readers ────────────────────────────────────────────────

    def read_bookmarks(self) -> tuple[UpstreamBookmark, ...]:
        """Read every record of `bookmarks.jsonl` in file order."""

        path = self.jsonl_path
        if not path.is_file():
            raise UpstreamUnavailableError(
                f"upstream JSONL not found: {path}. Run `fieldtheory sync` first."
            )
        records: list[UpstreamBookmark] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise UpstreamContractError(
                        f"{path}:{line_number}: invalid JSON ({exc.msg})"
                    ) from exc
                where = f"{path.name}:{line_number}"
                _validate_bookmark(payload, where)
                records.append(_to_bookmark(payload))
        return tuple(records)

    def read_media_manifest(self) -> MediaManifest:
        """Read and validate `media-manifest.json`."""

        payload = self._read_json_file(self.manifest_path, "media-manifest.json")
        _validate_manifest(payload)
        entries = tuple(_to_media_entry(entry) for entry in payload["entries"])
        return MediaManifest(
            schema_version=int(payload["schemaVersion"]),
            generated_at=payload.get("generatedAt"),
            limit=payload.get("limit"),
            max_bytes=payload.get("maxBytes"),
            processed=int(payload.get("processed") or 0),
            downloaded=int(payload.get("downloaded") or 0),
            skipped_too_large=int(payload.get("skippedTooLarge") or 0),
            failed=int(payload.get("failed") or 0),
            entries=entries,
        )

    def read_meta(self) -> Mapping[str, Any]:
        """Read and validate `bookmarks-meta.json`."""

        payload = self._read_json_file(self.meta_path, "bookmarks-meta.json")
        _validate_meta(payload)
        return payload

    def read_backfill_state(self) -> Mapping[str, Any]:
        """Read and validate `bookmarks-backfill-state.json` (`stopReason` lives here)."""

        payload = self._read_json_file(self.backfill_state_path, "bookmarks-backfill-state.json")
        _validate_backfill_state(payload)
        return payload

    # ── enriched reads (the only surface that carries article text) ──────────

    def list_enriched(self, limit: int | None = None, timeout_seconds: float | None = None) -> tuple[EnrichedBookmark, ...]:
        """Read enriched records through `fieldtheory list --json`.

        This is the bulk source for article bodies, categories, folders and
        quoted tweets; `bookmarks.jsonl` never contains them.
        """

        args = ["list", "--json"]
        if limit is not None:
            args += ["--limit", str(int(limit))]
        outcome = self._run(args, timeout=self._timeout(timeout_seconds), retry_transient=True)
        self._raise_on_failure(outcome)
        payload = _extract_json(outcome.stdout, "list --json")
        if isinstance(payload, Mapping):
            payload = [payload]
        if not isinstance(payload, list):
            raise UpstreamContractError(
                f"list --json: expected an array, got {type(payload).__name__}"
            )
        records: list[EnrichedBookmark] = []
        for index, record in enumerate(payload):
            where = f"list --json[{index}]"
            _validate_enriched(record, where)
            records.append(_to_enriched(record))
        return tuple(records)

    def show_enriched(self, tweet_id: str, timeout_seconds: float | None = None) -> EnrichedBookmark:
        """Read one enriched record through `fieldtheory show <tweet_id> --json`."""

        if not str(tweet_id).strip():
            raise ValueError("tweet_id must be a non-empty string")
        args = ["show", str(tweet_id), "--json"]
        outcome = self._run(args, timeout=self._timeout(timeout_seconds), retry_transient=True)
        self._raise_on_failure(outcome)
        payload = _extract_json(outcome.stdout, f"show {tweet_id} --json")
        _validate_enriched(payload, f"show {tweet_id} --json")
        return _to_enriched(payload)

    def upstream_version(self, timeout_seconds: float | None = None) -> str:
        """Return the upstream CLI version string, e.g. `1.3.22`."""

        outcome = self._run(
            ["--version"], timeout=self._timeout(timeout_seconds), retry_transient=False
        )
        self._raise_on_failure(outcome)
        return outcome.stdout.strip()

    # ── internals ────────────────────────────────────────────────────────────

    def _timeout(self, override: float | None) -> float:
        return self.query_timeout_seconds if override is None else float(override)

    def _resolve_executable(self) -> tuple[str, ...]:
        spec = self._executable_spec
        if isinstance(spec, (list, tuple)):
            if not spec:
                raise UpstreamUnavailableError("executable override must not be empty")
            # 序列形式表示"命令 + 前置参数"（如 `python -B stub.py`）：
            # 首元素仍必须真实存在，否则 doctor 会误判为可用。
            return (self._resolve_one(str(spec[0])), *(str(part) for part in spec[1:]))
        return (self._resolve_one(spec or DEFAULT_EXECUTABLE),)

    @staticmethod
    def _resolve_one(name: str) -> str:
        if os.path.sep in name or "/" in name:
            resolved = shutil.which(name) or (name if Path(name).is_file() else None)
        else:
            resolved = shutil.which(name)
        if not resolved:
            raise UpstreamUnavailableError(
                f"upstream executable not found on PATH: {name}. "
                "Install it with `npm install -g fieldtheory`."
            )
        return str(resolved)

    def _read_json_file(self, path: Path, label: str) -> Any:
        if not path.is_file():
            raise UpstreamUnavailableError(f"upstream {label} not found: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise UpstreamContractError(f"{label}: invalid JSON ({exc.msg})") from exc

    def _run(self, args: Sequence[str], timeout: float, retry_transient: bool) -> _RunOutcome:
        """Invoke upstream with timeout and a bounded retry loop."""

        command = self.executable + tuple(str(a) for a in args)
        env = os.environ.copy()
        env.update(self._env_overrides)
        env["FT_DATA_DIR"] = str(self.data_dir)
        # Keep upstream output stable for parsing and logging.
        env.setdefault("NO_COLOR", "1")
        # Python-based upstreams (incl. the test stub) otherwise inherit the
        # console code page: on Chinese Windows (cp936) they crash with
        # UnicodeEncodeError when writing non-GBK characters such as `✓`.
        # Inert for the Node-based real CLI.
        env.setdefault("PYTHONIOENCODING", "utf-8")

        max_attempts = 1 + (self.retries if retry_transient else 0)
        attempt = 0
        started = time.monotonic()
        last: _RunOutcome | None = None
        while attempt < max_attempts:
            attempt += 1
            timed_out = False
            try:
                completed = subprocess.run(
                    list(command),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    env=env,
                    check=False,
                )
                stdout, stderr, returncode = completed.stdout, completed.stderr, completed.returncode
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                stdout = _as_text(exc.stdout)
                stderr = _as_text(exc.stderr)
                returncode = -1
            except FileNotFoundError as exc:
                raise UpstreamUnavailableError(f"cannot execute {command[0]}: {exc}") from exc
            except OSError as exc:
                raise UpstreamUnavailableError(f"cannot execute {command[0]}: {exc}") from exc

            last = _RunOutcome(
                command=command,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=time.monotonic() - started,
                attempts=attempt,
                timed_out=timed_out,
            )
            if returncode == 0 and not timed_out:
                return last
            if attempt >= max_attempts or not self._is_transient(last):
                break
            self._sleep(self.retry_backoff_seconds * attempt)
        assert last is not None
        return last

    @staticmethod
    def _is_transient(outcome: _RunOutcome) -> bool:
        text = f"{outcome.stdout}\n{outcome.stderr}".lower()
        if any(marker in text for marker in _AUTH_MARKERS):
            return False
        return outcome.timed_out or any(marker in text for marker in _TRANSIENT_MARKERS)

    def _raise_on_failure(self, outcome: _RunOutcome) -> None:
        if outcome.timed_out:
            raise UpstreamTimeoutError(
                f"upstream timed out after {outcome.duration_seconds:.1f}s "
                f"({outcome.attempts} attempt(s)): {' '.join(outcome.command)}"
            )
        if outcome.returncode == 0:
            return
        text = f"{outcome.stdout}\n{outcome.stderr}".lower()
        tail = _tail(outcome.stderr or outcome.stdout)
        if any(marker in text for marker in _AUTH_MARKERS):
            raise UpstreamAuthError(
                "upstream could not use a browser session. Log into x.com in the "
                f"configured browser (or pass cookies/OAuth) and retry. Output: {tail}"
            )
        raise UpstreamExecutionError(
            f"upstream exited with code {outcome.returncode}: {' '.join(outcome.command)}. "
            f"Output: {tail}"
        )


# ── module-level helpers ─────────────────────────────────────────────────────


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _tail(text: str, limit: int = 400) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned[-limit:] if len(cleaned) > limit else cleaned


def _extract_json(stdout: str, label: str) -> Any:
    """Parse CLI stdout as JSON, tolerating leading/trailing noise.

    Upstream prints progress spinners on some commands; the fallback slices the
    outermost array/object so a stray log line cannot break ingestion.
    """

    text = (stdout or "").strip()
    if not text:
        raise UpstreamContractError(f"{label}: produced no output")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    candidates = [index for index in (text.find("["), text.find("{")) if index >= 0]
    if not candidates:
        raise UpstreamContractError(f"{label}: no JSON found in output")
    start = min(candidates)
    end = max(text.rfind("]"), text.rfind("}"))
    if end <= start:
        raise UpstreamContractError(f"{label}: truncated JSON in output")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise UpstreamContractError(f"{label}: invalid JSON ({exc.msg})") from exc


def _validate_bookmark(payload: Any, where: str) -> None:
    _contract.validate_bookmark_record(payload, where)


def _validate_manifest(payload: Any) -> None:
    _contract.validate_media_manifest(payload)


def _validate_meta(payload: Any) -> None:
    _contract.validate_meta(payload)


def _validate_backfill_state(payload: Any) -> None:
    _contract.validate_backfill_state(payload)


def _validate_enriched(payload: Any, where: str) -> None:
    _contract.validate_enriched_record(payload, where)


def _to_bookmark(payload: Mapping[str, Any]) -> UpstreamBookmark:
    """Normalise one upstream JSONL record to snake_case."""

    return UpstreamBookmark(
        tweet_id=str(payload["tweetId"]),
        url=str(payload["url"]),
        text=payload["text"],
        author_handle=str(payload["authorHandle"]),
        author_name=str(payload["authorName"]),
        author_profile_image_url=str(payload["authorProfileImageUrl"]),
        posted_at_raw=str(payload["postedAt"]),
        bookmarked_at_raw=payload.get("bookmarkedAt"),
        synced_at=payload.get("syncedAt"),
        conversation_id=payload.get("conversationId"),
        language=payload.get("language"),
        possibly_sensitive=payload.get("possiblySensitive"),
        media_urls=tuple(str(item) for item in payload.get("media") or ()),
        media_objects=tuple(payload.get("mediaObjects") or ()),
        links=tuple(str(item) for item in payload.get("links") or ()),
        tags=tuple(str(item) for item in payload.get("tags") or ()),
        engagement=dict(payload.get("engagement") or {}),
        author=dict(payload.get("author") or {}),
        ingested_via=payload.get("ingestedVia"),
        sort_index=payload.get("sortIndex"),
        text_expanded_at=payload.get("textExpandedAt"),
        raw=dict(payload),
    )


def _to_media_entry(payload: Mapping[str, Any]) -> MediaEntry:
    return MediaEntry(
        bookmark_id=str(payload["bookmarkId"]),
        tweet_id=str(payload["tweetId"]),
        tweet_url=payload.get("tweetUrl") or "",
        author_handle=payload.get("authorHandle"),
        author_name=payload.get("authorName"),
        source_url=str(payload["sourceUrl"]),
        local_path=str(payload["localPath"]),
        content_type=payload.get("contentType"),
        size_bytes=payload.get("bytes"),
        status=str(payload["status"]),
        fetched_at=payload.get("fetchedAt"),
    )


def _to_enriched(payload: Mapping[str, Any]) -> EnrichedBookmark:
    """Normalise one `list|show --json` record to snake_case."""

    return EnrichedBookmark(
        tweet_id=str(payload["tweetId"]),
        url=str(payload["url"]),
        text=payload["text"],
        author_handle=str(payload["authorHandle"]),
        article_title=payload.get("articleTitle"),
        article_text=payload.get("articleText"),
        article_site=payload.get("articleSite"),
        enriched_at=payload.get("enrichedAt"),
        categories=tuple(str(item) for item in payload.get("categories") or ()),
        primary_category=payload.get("primaryCategory"),
        domains=tuple(str(item) for item in payload.get("domains") or ()),
        primary_domain=payload.get("primaryDomain"),
        github_urls=tuple(str(item) for item in payload.get("githubUrls") or ()),
        view_count=payload.get("viewCount"),
        media_count=payload.get("mediaCount"),
        link_count=payload.get("linkCount"),
        folder_ids=tuple(str(item) for item in payload.get("folderIds") or ()),
        folder_names=tuple(str(item) for item in payload.get("folderNames") or ()),
        quoted_status_id=payload.get("quotedStatusId"),
        quoted_tweet=payload.get("quotedTweet"),
        raw=dict(payload),
    )
