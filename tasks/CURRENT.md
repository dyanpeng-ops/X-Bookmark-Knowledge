# Current Task — X Bookmark Knowledge Pipeline

> Updated: 2026-09-20 (after Phase 8 completion)
> Status: Phase 8 complete, media localised end to end. Phase 9 is the next candidate and needs authorization.

## Verified project state

- Phases 0–8 are complete.
- Acceptance command: `.venv\Scripts\python.exe -m unittest discover -s tests -t .` → **272 tests, exit 0**
  (Phase 4: 68, Phase 5: 76, Phase 6: 60, Phase 7: 23, Phase 8: 44 + 1 ingest regression; all offline —
  the suite uses temp dirs and leaves the real `data/` untouched).
- `src/database/` — schema versioning, migrations, state machine, idempotent upserts, FTS5.
- `src/collector/` — `contract.py` (frozen upstream contract), `base.py`, `fieldtheory_adapter.py`
  (CLI adapter; injects `PYTHONIOENCODING=utf-8`, ADR-014).
- `src/config.py` — YAML config (PyYAML 6.0.3), typed sections, absolute paths, validation.
- `src/ingest/ingest.py` — idempotent ingest, raw JSON archives, per-record failure isolation,
  `media.local_path` written **only on insert** (Phase 8 owns it afterwards).
- `src/markdown/` — `render.py` (frontmatter + 8 sections, posted-date layout, `date_parts()`,
  optional `media_files`) and `writer.py` (hash-based skip, refuse-overwrite,
  `COLLECTED → PROCESSED`, optional `media_lookup`).
- `src/media/localizer.py` — media localisation: stable `{media_key}{ext}` names, SHA-256 idempotency,
  atomic copy, skip rules, dry-run, stale-path reconciliation.
- `src/cli/` — `python -m src.cli sync|media|process|status|doctor`, exit codes 0/1/2/3.
  Pipeline order: `sync → media → process`.
- Real-data acceptance (2026-09-20): `media --dry-run` → 6/6 resolvable; `media` first run
  `copied: 6 / failed: 0`; second run `copied: 0 / unchanged: 6`; all six `media.local_path` values
  now point inside `knowledge/X-Bookmarks/{YYYY}/{MM}/assets/{tweet_id}/` and match the
  `data/upstream/media/` sources byte for byte; `process --overwrite` → `written: 1 / unchanged: 4`
  (only the media-bearing file changed), then `written: 0 / unchanged: 5`; `sync --skip-collect`
  → `media rows : 0 new, 0 updated, 6 unchanged` (localisation does not regress).

## Independent audit feedback (2026-09-17) — closed by Phase 8

- **Stale `media.local_path` values:** all six rows pointed at
  `C:\Users\gscaee\.fieldtheory\bookmarks\media\...`. Closed: the media layer only ever takes the
  *file name* from those values and resolves it under the configured `<upstream_data_dir>/media/`;
  it never reads the legacy cache, and regression tests cover both a stale absolute path and a
  same-named file in a legacy directory.
- **Source-path reconciliation rule:** implemented as a documented 5-step order (see
  `src/media/localizer.py` docstring) that ends in an explicit `FAILED` row rather than a guess.
- **`config/config.example.yaml` comment** about `upstream_data_dir` precedence: corrected earlier.
- **Phase ordering:** Phase 8 is complete; `plans/ACTIVE.md` now points at Phase 9.
- **Governance gap on `src/config.py`:** the previously unused `MediaOptions` / `load_media_options()`
  scaffolding is now the media layer's typed configuration, covered by tests and documented here.

## Phase 8 decisions recorded

- Every media row in the manifest is localised, including `profile_image` rows; the `## media`
  section only references tweet-owned media, so avatars are stored but not rendered.
- Policy skips do **not** write `SKIPPED`; they keep the upstream status and record
  `error_message = "skipped: <reason>"`, otherwise every `sync` would flip the row back to
  `DOWNLOADED` and inflate `media updated` counts.
- Stable file name = `{media_key}{ext}` with `media_key = sha1(source_url)[:16]`, so DB rows and
  files map onto each other directly.
- `media.download_video: false` stays the default; video/`animated_gif` rows are skipped with a
  recorded reason.

## Next task, after authorization

Phase 9 — external link extraction (`src/external/`):

1. Unified fetch wrapper: timeout, retries with backoff, redirect handling, encoding detection,
   size cap (`external.*` config already exists).
2. Extract title/body and write `external_links.{resolved_url, title, content_path, fetch_status}`;
   a failed fetch must keep the original URL and mark the row `FAILED` without aborting the batch.
3. Feed extracted content into the Markdown `## external_links` section.
4. Tests: timeout/retry/redirect/failure-keeps-URL, per-link isolation, idempotency, offline only.

## Hard stop

Do not start Phase 9 without authorization. Do not write into `knowledge/` outside the configured
knowledge directory. Never record credentials, cookies or tokens in project files, logs or task notes.

## Audit follow-up

- Closed: `scripts/README.md` documents the CLI flow (now including `media`).
- Closed: `plans/backlog.md` contains the real backlog.
- Still open: `src/collector/contract.py` — video/multi-photo `mediaObjects` and skipped/failed
  manifest `status` strings remain `UNVERIFIED` until such samples appear; Phase 8 now has skip-rule
  tests using synthetic rows, but the contract itself stays frozen until real samples exist.
