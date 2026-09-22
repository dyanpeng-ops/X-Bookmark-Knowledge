# Current State

Last Updated: 2026-09-21

## Current Phase

Phase 8 (media localisation) is complete and accepted on real data.
Phase 9 (external link extraction) is implemented; the 2026-09-20 review blockers are closed
(2026-09-21). Offline verification ran **under approval** and is green (external 94, full suite
369, exit 0). The **real-data write run** still awaits explicit approval.

## Completed

- Phase 0 — environment check → `docs/environment-report.md`
- Phase 1 — open-source comparison → `research/open-source-comparison.md`
- Phase 2 — architecture decision (user-approved) → `research/architecture-decision.md`
- Phase 3 — project skeleton (`AGENTS.md`, `README.md`, `PLAN.md`, `CHANGELOG.md`, `.gitignore`, `config/config.example.yaml`)
- Phase 4 — SQLite data model: `.venv` (Python 3.12.13), `src/database/` (9 modules), `tests/test_database.py` (68 cases)
- Phase 5 — Collector: `src/collector/` (3 modules), gates A–D closed with real data, `tests/test_collector_*.py` (76 cases)
- Phase 6 — incremental sync + CLI (2026-09-16):
  - Upstream data directory migrated from `C:\Users\gscaee\.fieldtheory\bookmarks` to `data/upstream` on `D:` (`FT_DATA_DIR`, ADR-011); verified with `status --json` and a real `sync`
  - PyYAML 6.0.3 adopted (ADR-012)
  - `src/config.py` — YAML config with typed sections, absolute path resolution, validation, unknown-key reporting
  - `src/ingest/ingest.py` — `Ingestor` / `IngestStats`: idempotent upserts, `data/raw/{tweet_id}.json` archives, per-record failure isolation, media key/type derivation, link dedupe
  - `src/cli/` — `python -m src.cli sync|status|doctor`, exit codes 0/1/2/3, console + per-day log file
  - `tests/test_config.py` (21) + `tests/test_ingest.py` (25) + `tests/test_cli.py` (17)
  - Acceptance: **204 tests, exit 0**; M2 proven (two consecutive runs, second reports `new : 0`)
- 5 defects found and fixed mid-phase (repository `changed` flag, executable-sequence resolution, log handler leak, blank URL handling, fixture fidelity)
- Phase 7 — Markdown generator (2026-09-17):
  - `src/markdown/render.py` — `RenderOptions` + `render_markdown()`: 13-key frontmatter, 8 sections (`tweet`, `thread`, `media`, `article`, `external_links`, `metadata`, `ai_analysis`, `source`), posted-date `YYYY/MM/` layout, escaping, placeholders
  - `src/markdown/writer.py` — `MarkdownWriter`: content-hash skip, refuse-overwrite (`overwrite_existing: false`; `process --overwrite` overrides), per-record failure isolation, `COLLECTED → PROCESSED` + `markdown_path`
  - `process` subcommand added to `src/cli` (reads `data/raw/` archives)
  - `thread` renders enrichment `quotedTweet`; `ai_analysis` is a placeholder for Phase 11 (ADR-015)
  - cp936 subprocess-encoding crash fixed in adapter + stub (ADR-014) — one root cause behind 14 earlier test failures
  - `tests/test_markdown.py` (23 cases)
  - Acceptance: **227 tests, exit 0**; real data — `process` twice, second run `written : 0 / unchanged : 5`, no warnings; 5 files under `knowledge/X-Bookmarks/{2026-03, 2026-06, 2026-09}/`; M3 achieved
- Phase 8 — media localisation (2026-09-20):
  - `src/media/localizer.py` — `MediaLocalizer` / `MediaSource` / `MediaUpdate` / `MediaStats`: stable
    `{media_key}{ext}` names, SHA-256 idempotency, atomic copy (`.part` + `os.replace`), skip rules,
    dry-run, per-row failure isolation
  - Source resolution (audit precondition): knowledge-local `local_path` → configured media-dir
    `local_path` → manifest index → `local_path` name → URL name; the legacy C: cache is never read
  - `media [--tweet-id] [--dry-run]` subcommand added; pipeline order is `sync → media → process`
  - `src/ingest/ingest.py` — `media.local_path` is now written only on insert (Phase 8 owns it after)
  - `src/markdown/` — `date_parts()` extracted; `render_markdown(..., media_files=...)` and
    `MarkdownWriter(..., media_lookup=...)`; `process` only accepts paths inside `knowledge_dir`
  - `tests/test_media.py` (44 cases) + an ingest regression case; the offline stub now materialises
    media files so `sync → media → process` is covered end to end
  - Acceptance: **272 tests, exit 0**; real data — `media` `copied: 6 / failed: 0` then
    `copied: 0 / unchanged: 6`; 6/6 `media.local_path` inside the knowledge tree and SHA-256-identical
    to `data/upstream/media/`; `process --overwrite` `written: 1 / unchanged: 4`; `sync --skip-collect`
    keeps `local_path` (`0 new, 0 updated, 6 unchanged`)
  - Decision recorded as ADR-016
- **Phase 9 — external link extraction (2026-09-20; review closed 2026-09-21, offline suite
  green under approval; **real-data write run pending**):
  - `src/external/fetcher.py` — stdlib-only `HttpFetcher` (`urllib` + explicit hop-by-hop redirects),
    timeout/retry/backoff, `Content-Length` + read-cap size limit, BOM/meta charset detection,
    injectable transport (tests never open a socket)
  - `src/external/handlers/` — `web` (`html.parser`: title/description/canonical/body with skip-tag
    list) and `github` (`owner/repo` title strategy); `pdf` deliberately deferred (skipped with reason)
  - `src/external/resolver.py` — `LinkResolver`: per-link isolation, `link_key = sha1(url)[:16]`,
    writes `assets/{tweet_id}/links/{link_key}.md` (timestamp-free → content idempotent),
    FETCHED rows with an existing knowledge-local file are `unchanged` **without network**,
    FAILED rows stop retrying at `external.max_attempts` (default 3) until `--force`
  - `src/config.py` — `ExternalOptions` + `load_external_options()` (new keys: `delay_seconds`,
    `max_redirects`, `max_attempts`, `skip_domains` (default `x.com`/`twitter.com`), `links_subdir`)
  - `src/cli/main.py` — `links [--tweet-id] [--limit] [--force] [--dry-run]` subcommand;
    `status` now reports external-link status counts; pipeline order is `sync → media → links → process`
  - `src/markdown/` — `## external_links` renders `- [title](url)` + content path / final URL /
    failure reason when `link_details` are supplied, and is byte-identical to Phase 7 when they are not
  - `src/ingest/ingest.py` — `fetch_status` is now written only on insert (same rule as
    `media.local_path`; regression test in `tests/test_ingest.py`)
  - `src/database/repository.py` — `set_link_status()` also writes `title`; added
    `count_external_links()` / `count_external_links_by_status()` / `list_links_by_status()`
  - `tests/test_external.py` (offline; transport and CLI fetcher are fake-injected)
  - Decisions recorded as ADR-017 (stdlib-only fetch/extract) and ADR-018 (paths, insert-only
    `fetch_status`, attempt cap, X.com skip)

  - Review close-out (2026-09-21): netguard SSRF guard (initial target and every redirect hop;
    hits recorded as policy skips), canonical URL persisted into `resolved_url` and the link
    body, `clear_fields` stale-body clearing in `set_link_status`; external suite grew to 94
  - Approved runs (2026-09-21): external 94 OK, full suite 369 OK (exit 0), `git diff --check`
    clean,
    `links --dry-run` wrote nothing but **did** make outbound requests (correction logged)

## In Progress

- Await the real-data **write** run: `links` -> `process` -> second `links` ->
  `sync --skip-collect` (details in `tasks/CURRENT.md`). Committing/pushing Phase 9 also
  awaits approval.

## Not Started

- Phases 10–13: content integrity tests (Test A–L), AI enrichment, pipeline handoff, scheduler

## Current Problems

- None blocking.
- Contract areas still `UNVERIFIED` in `src/collector/contract.py`: video/multi-photo `mediaObjects`,
  and manifest `status` strings for skipped/failed media — relevant to Phase 8; no such samples
  exist in the current 5-record corpus.
- The Phase 6 upstream cache pollution is fully remediated (verified 2026-09-17): `data/upstream`
  holds the 5 real records + 6 media files, no `stub-argv.txt`; the C: migration source is kept as a
  backup.

## Resolved (2026-09-17) — historical note

- **Upstream cache polluted by a test run (needs user authorization to clear).** While the config-vs-env precedence was still "env wins", `tests/test_cli.py` drove the offline stub against the *real* `data/upstream`, overwriting `bookmarks.jsonl` with 3 synthetic fixture records and adding them to `bookmarks.db` (now 8 rows). Also left `data/upstream/stub-argv.txt`.
  - Root cause fixed (config now wins, ADR-013) and verified: a full test run leaves `data/upstream` byte-for-byte and timestamp-for-timestamp unchanged.
  - Real data was recovered from the original directory `C:\Users\gscaee\.fieldtheory\bookmarks` (the migration source, kept as backup).
  - Remediation completed and verified 2026-09-17; no further action needed.
- `config/config.yaml` exists locally (gitignored) and is validated by `tests/test_config.py`.

## Next Step

1. On approval: the real-data write run (`links` / `process` / second `links` /
   `sync --skip-collect`); then commit and push, each with separate approval.
2. After acceptance: Phase 10 (content integrity tests, Test A–L).

## Notes

- Version control: initialised and pushed to the **private** GitHub repo
  `https://github.com/dyanpeng-ops/X-Bookmark-Knowledge.git` (remote name `X-Bookmark-Knowledge`, branch
  `main`, first commit `94da817`). Real bookmark content stays local: `knowledge/*` is gitignored except
  `knowledge/X-Bookmarks/README.md`; `config/config.yaml`, `data/`, `.venv/` and `*.db` remain untracked.
- Acceptance command: `.venv\Scripts\python.exe -B -m unittest discover -s tests -t .` -> 369
  tests, exit 0 (approved run 2026-09-21; it was 272 before Phase 9).
- Real-data commands: `.venv\Scripts\python.exe -B -m src.cli sync` (or `sync --skip-collect` offline),
  `.venv\Scripts\python.exe -B -m src.cli media` (add `--dry-run` to inspect first),
  `.venv\Scripts\python.exe -B -m src.cli links` (`--dry-run` / `--force` / `--tweet-id` / `--limit`),
  and `.venv\Scripts\python.exe -B -m src.cli process` (both use `config/config.yaml`). Pipeline order
  is `sync → media → links → process`.
- Write boundaries: the project writes only inside its own tree; tests use temp directories and never
  touch real `data/`. Upstream `~/.fieldtheory` was read and later relocated to `data/upstream` by
  the upstream tool itself.
- Language note: project prose is Chinese; governance files under `memory/`, `plans/`, `tasks/` and
  `.clinerules/` are English.
