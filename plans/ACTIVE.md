# Active Plan

## Milestone

**M1 — SQLite data model, migrations and tests (Phase 4). Status: COMPLETE (2026-09-15).**

**M2 — `python -m src.cli sync` running end to end with idempotency. Status: COMPLETE (2026-09-16).**

**M3 — one Markdown file per bookmark under `knowledge/X-Bookmarks/YYYY/MM/` with a stable
frontmatter and a no-overwrite guarantee (Phase 7). Status: COMPLETE (2026-09-17, real data).**

**Media — upstream media localised into the knowledge tree, `media.local_path` reconciled onto
knowledge-local paths, and `## media` referencing them (Phase 8). Status: COMPLETE (2026-09-20,
real data).**

Immediate next phase: **Phase 9 — external link extraction.** Implemented (2026-09-20), **awaiting
user-approved verification** — see `tasks/CURRENT.md` for the pending-verification list.

Phase 8 closed the audit precondition: the six stale C:-rooted `media.local_path` values were
resolved by file name under the configured `data/upstream/media/`, copied into `assets/{tweet_id}/`,
and rewritten in SQLite.

Next milestone: **M4 — external link extraction usable, failures keep the original
URL (Phase 9).** Implemented; acceptance run not yet authorized.

## Progress

Phase 4 → M1: complete.

Phase 5 → M2 prerequisite: complete.

Phase 6 → M2:

- [x] Decide the YAML parsing dependency (PyYAML 6.0.3, ADR-012)
- [x] Relocate the upstream data directory to `data/upstream` on `D:` (ADR-011)
- [x] Implement `src/config.py` (typed sections, absolute paths, validation)
- [x] Implement `src/ingest/` (idempotent upserts, raw archives, failure isolation)
- [x] Implement `python -m src.cli sync` with a run report and non-zero exit codes
- [x] Implement `status` and `doctor`
- [x] Add `tests/test_config.py` (21), `tests/test_ingest.py` (25), `tests/test_cli.py` (17)
- [x] Prove idempotency: two consecutive runs, the second reports `new : 0`
- [x] Update `PLAN.md`, `CHANGELOG.md`, governance files

Phase 7 → M3 (complete, 2026-09-17):

- [x] Implement `src/markdown/` (naming, frontmatter, 8 sections incl. `thread` / `ai_analysis`)
- [x] Write into `knowledge/X-Bookmarks/YYYY/MM/` only (posted-date layout)
- [x] Advance bookmark state `COLLECTED → PROCESSED` and record `markdown_path`
- [x] `tests/test_markdown.py`: only-once creation, no-overwrite, content fidelity (23 cases)
- [x] Fix cp936 subprocess-encoding crash in adapter + stub (ADR-014)
- [x] Real-data acceptance: `process` twice → second run `written: 0 / unchanged: 5`, no warnings

Phase 8 → media localisation / audit precondition (complete, 2026-09-20):

- [x] Implement `src/media/localizer.py` (stable names, SHA-256 idempotency, atomic copy, dry-run)
- [x] Reconcile stale absolute `media.local_path` inputs by file name under the configured upstream
      media directory; never read the legacy C: cache
- [x] Skip rules honoured: `media.download=false`, upstream status != `downloaded`,
      `download_video=false` for `video`/`animated_gif`, `max_bytes`
- [x] Add the `media [--tweet-id] [--dry-run]` subcommand; document `sync → media → process`
- [x] Make `ingest` write `media.local_path` only on insert (Phase 8 owns it afterwards)
- [x] Render `## media` from knowledge-local relative paths (`render_markdown(media_files=...)`,
      `MarkdownWriter(media_lookup=...)`); fall back to the remote URL when unmapped
- [x] `tests/test_media.py` (44 cases) + ingest regression case; offline stub now materialises media
- [x] Real-data acceptance: `media` → `copied: 6 / failed: 0`, then `unchanged: 6 / copied: 0`;
      `process --overwrite` → `written: 1 / unchanged: 4`; `sync --skip-collect` keeps `local_path`

Phase 9 → external links / M4 (implemented 2026-09-20, **awaiting user-approved verification**):

- [x] `src/external/fetcher.py` — stdlib `urllib` fetch wrapper: timeout, retries with backoff,
      hop-by-hop redirects (`max_redirects`), charset detection, `max_bytes` cap, injectable transport
- [x] `src/external/handlers/` — `web` (`html.parser`) + `github`; `pdf` deferred (skipped with reason)
- [x] `src/external/resolver.py` — `LinkResolver`: per-link isolation, knowledge-local content files,
      `unchanged` without network, attempt cap (`external.max_attempts`, `--force` overrides)
- [x] `ExternalOptions` + `load_external_options()`; `skip_domains` default `x.com`/`twitter.com`
- [x] `links [--tweet-id] [--limit] [--force] [--dry-run]` subcommand; `status` reports link counts
- [x] `## external_links` renders title/path/reason via `link_lookup`; Phase 7 shape unchanged
      when no links have been fetched
- [x] `ingest` writes `fetch_status` only on insert (regression test in `tests/test_ingest.py`)
- [x] `tests/test_external.py` (offline; transport + CLI fetcher are fake-injected)
- [ ] Acceptance run (see `tasks/CURRENT.md` — pending approval)

## Current Task

See `tasks/CURRENT.md`.

Phase 8 has been completed and accepted on real data (2026-09-20); all six `media.local_path`
values hold knowledge-local paths and the media layer no longer reads the legacy C: cache.
Phase 9 (external links) is implemented and awaiting user-approved verification.

## Dependencies

- Phase 7 depends on the Phase 6 ingest output (rows in `bookmarks`, archives in `data/raw/`).
- Phase 8 (media localisation) consumes the `media` rows written by the ingest layer and the
  `data/upstream/media/` cache; its output (`media.local_path`) is consumed by `process`.
- Phase 9 (external links) consumes the `external_links` rows created by the ingest layer and writes
  content into `knowledge/.../assets/{tweet_id}/links/`.

## Definition of Done

M1 — achieved: 68 tests, schema versioning idempotent, `tweet_id` unique, invalid transitions raise.

Phase 5 prerequisite — achieved: frozen contract locked by a snapshot test, read-only adapter,
`ALL REAL-DATA READS OK`.

M2 — achieved (2026-09-16):

- `python -m src.cli sync` prints a report and returns 0.
- Two consecutive runs: the second reports `new : 0` / `unchanged : N`; the database keeps N rows and
  `data/raw/` keeps N files, none rewritten.
- A record that cannot be ingested fails alone: exit code 1, `error_message` + `attempts` recorded in
  SQLite, other records still ingested.
- Acceptance: `Ran 204 tests ... OK`, exit 0.

M3 — achieved (2026-09-17, real data):

- A second run of the Markdown phase creates no new files and rewrites nothing
  (`written: 0 / unchanged: 5`, exit 0, no warnings).
- Every generated file carries the configured frontmatter fields, and the tweet text, media links,
  article body and external links appear in the configured sections (5/5 files inspected).
- Acceptance: `Ran 227 tests ... OK`, exit 0.

Phase 8 — achieved (2026-09-20, real data):

- `media` is idempotent: first run `copied: 6 / failed: 0`, second run `copied: 0 / unchanged: 6`.
- All six `media.local_path` values point inside `knowledge/X-Bookmarks/{YYYY}/{MM}/assets/{tweet_id}/`
  and match the `data/upstream/media/` sources byte for byte; the legacy C: cache is never read.
- `process --overwrite` rewrites only the file whose `## media` section changed
  (`written: 1 / unchanged: 4`), then `written: 0 / unchanged: 5`.
- A repeated `sync --skip-collect` reports `media rows : 0 new, 0 updated, 6 unchanged`, i.e. the
  knowledge-local paths survive re-ingest.
- A missing source file fails that row alone (exit code 1, `media.error_message` + `attempts`
  recorded) while the remaining rows are still localised.
- Acceptance: `Ran 272 tests ... OK`, exit 0.

M4 — implemented (2026-09-20), awaiting acceptance:

- External link extraction (Phase 9) usable; a failed fetch still keeps the original URL.
- `links` is idempotent: the first run fetches and writes `assets/{tweet_id}/links/{link_key}.md`;
  the second reports `unchanged` without network access.
- `sync` re-runs never reset `fetch_status` (`0 new, 0 updated, N unchanged` on the link rows).
- Acceptance: full offline suite green; real-data `links --dry-run` → `links` → `process` →
  `links` (unchanged) → `sync --skip-collect` (no reset). All runs pending approval.
