"""Synthetic stand-in for the upstream `fieldtheory` CLI (tests only).

The real CLI needs a logged-in browser session and network access, so the
adapter tests drive this script instead. It reproduces the surfaces the adapter
depends on: `sync`, `list --json`, `show <id> --json`, `--version`, the data
files inside `FT_DATA_DIR`, and the failure texts observed in real runs.

Scenarios are selected with the `STUB_SCENARIO` environment variable.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstream"

AUTH_FAILURE_TEXT = "  Couldn't connect to your browser session.\n"
TRANSIENT_FAILURE_TEXT = "TypeError: fetch failed\n    cause: ETIMEDOUT\n"
HTTP_FAILURE_TEXT = "Error: upstream responded with HTTP 503\n"


def _force_utf8_stdio() -> None:
    """Piped stdout defaults to the console code page (cp936 on Chinese
    Windows); the stub emits `✓`/`⠋`, which GBK cannot encode. Force UTF-8 so
    the stub behaves identically on every machine."""

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _data_dir() -> pathlib.Path:
    return pathlib.Path(os.environ["FT_DATA_DIR"])


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _write_outputs(data_dir: pathlib.Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for target, source in (
        ("bookmarks.jsonl", "bookmarks.sample.jsonl"),
        ("media-manifest.json", "media-manifest.sample.json"),
        ("bookmarks-meta.json", "bookmarks-meta.sample.json"),
        ("bookmarks-backfill-state.json", "bookmarks-backfill-state.sample.json"),
    ):
        (data_dir / target).write_text(_read_fixture(source), encoding="utf-8")
    (data_dir / "media").mkdir(exist_ok=True)
    _write_media_files(data_dir)


def _media_bytes(entry: dict) -> bytes:
    """Deterministic stand-in for a downloaded binary (the media phase only copies bytes)."""

    return ("stub-media:" + str(entry.get("sourceUrl") or "")).encode("utf-8")


def _write_media_files(data_dir: pathlib.Path) -> None:
    """Materialise one file per downloaded manifest entry.

    The manifest keeps its synthetic absolute `localPath` (mirroring the real fixture),
    while the bytes live under `<FT_DATA_DIR>/media/<basename>` — exactly the stale-path
    reconciliation case Phase 8 must handle.
    """

    manifest_path = data_dir / "media-manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    media_dir = data_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    for entry in manifest.get("entries", []):
        if str(entry.get("status", "")).lower() != "downloaded":
            continue
        name = pathlib.Path(str(entry.get("localPath") or "")).name
        if not name:
            continue
        (media_dir / name).write_bytes(_media_bytes(entry))


def _bump_attempts(data_dir: pathlib.Path) -> int:
    data_dir.mkdir(parents=True, exist_ok=True)
    marker = data_dir / "stub-attempts.txt"
    count = int(marker.read_text(encoding="utf-8")) + 1 if marker.exists() else 1
    marker.write_text(str(count), encoding="utf-8")
    return count


def _record_argv(argv: list[str], data_dir: pathlib.Path) -> None:
    """Persist the raw argv so tests can assert the flags the adapter passed."""

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "stub-argv.txt").write_text(" ".join(argv), encoding="utf-8")


def _sync(argv: list[str], scenario: str) -> int:
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    if scenario == "auth":
        sys.stdout.write(AUTH_FAILURE_TEXT)
        return 1
    if scenario == "transient":
        sys.stdout.write(TRANSIENT_FAILURE_TEXT)
        return 1
    if scenario == "http500":
        sys.stdout.write(HTTP_FAILURE_TEXT)
        return 1
    if scenario == "crash":
        sys.stderr.write("unexpected internal error\n")
        return 3
    if scenario == "flaky":
        if _bump_attempts(data_dir) < 3:
            sys.stdout.write(TRANSIENT_FAILURE_TEXT)
            return 1

    _write_outputs(data_dir)
    sys.stderr.write("(node:1) ExperimentalWarning: SQLite is an experimental feature\n")
    sys.stdout.write("\n  ✓ 3 new bookmarks synced (3 total)\n  ✓ Data written\n")
    return 0


def _list(argv: list[str]) -> int:
    payload = _read_fixture("list.sample.json")
    if os.environ.get("STUB_NOISE") == "1":
        sys.stdout.write("  ⠋ Syncing bookmarks...  0 new\n")
        sys.stdout.write(payload)
        sys.stdout.write("\n  done\n")
    else:
        sys.stdout.write(payload)
    return 0


def _show(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("missing tweet id\n")
        return 2
    records = json.loads(_read_fixture("list.sample.json"))
    match = next((item for item in records if item["tweetId"] == argv[1]), None)
    if match is None:
        sys.stderr.write(f"bookmark not found: {argv[1]}\n")
        return 4
    sys.stdout.write(json.dumps(match, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    _force_utf8_stdio()
    scenario = os.environ.get("STUB_SCENARIO", "ok")
    if not argv:
        return 2
    if argv[0] in ("--version", "-V"):
        sys.stdout.write("9.9.9\n")
        return 0
    _record_argv(argv, _data_dir())
    if scenario == "auth":
        sys.stdout.write(AUTH_FAILURE_TEXT)
        return 1
    if scenario == "slow":
        time.sleep(float(os.environ.get("STUB_SLEEP", "30")))
    if argv[0] == "sync":
        return _sync(argv, scenario)
    if argv[0] == "list":
        return _list(argv)
    if argv[0] == "show":
        return _show(argv)
    sys.stderr.write(f"unknown command: {argv[0]}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
