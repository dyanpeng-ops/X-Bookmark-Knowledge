# Current State

Last Updated: 2026-09-20

## Current Phase

Phase 8 (media localisation) is complete and accepted on real data.
Phase 9 (external link extraction) is **not** authorized to start yet.

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

## In Progress

- Nothing. Waiting for authorization on Phase 9 (external link extraction).

## Not Started

- Phases 9–13: external link extraction, integrity tests (Test A–L), AI enrichment, pipeline handoff, scheduler

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

1. After user authorization: Phase 9 (external link extraction) in `src/external/` — unified
   timeout/retry/redirect/encoding handling, title + body extraction into `external_links`
   (`resolved_url`, `title`, `content_path`, `fetch_status`), failed fetches keep the original URL
   and fail alone, then feed the extracted text into the Markdown `## external_links` section.
   See `tasks/CURRENT.md` for the checklist.

## Notes

- Version control: initialised and pushed to the **private** GitHub repo
  `https://github.com/dyanpeng-ops/X-Bookmark-Knowledge.git` (remote name `X-Bookmark-Knowledge`, branch
  `main`, first commit `94da817`). Real bookmark content stays local: `knowledge/*` is gitignored except
  `knowledge/X-Bookmarks/README.md`; `config/config.yaml`, `data/`, `.venv/` and `*.db` remain untracked.
- Acceptance command: `.venv\Scripts\python.exe -B -m unittest discover -s tests -t .` → 272 tests, exit 0.
- Real-data commands: `.venv\Scripts\python.exe -B -m src.cli sync` (or `sync --skip-collect` offline),
  `.venv\Scripts\python.exe -B -m src.cli media` (add `--dry-run` to inspect first), and
  `.venv\Scripts\python.exe -B -m src.cli process` (both use `config/config.yaml`). Pipeline order is
  `sync → media → process`.
- Write boundaries: the project writes only inside its own tree; tests use temp directories and never
  touch real `data/`. Upstream `~/.fieldtheory` was read and later relocated to `data/upstream` by
  the upstream tool itself.
- Language note: project prose is Chinese; governance files under `memory/`, `plans/`, `tasks/` and
  `.clinerules/` are English.
