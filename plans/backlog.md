# Backlog

Items waiting on a future Phase, a user decision, or new data samples. Ordered by phase.

## Phase 8 — media localisation (DONE, 2026-09-20)

- Closed: stale `media.local_path` rows reconciled by file name under the configured
  `data/upstream/media/`; the legacy C: cache is never read; regression tests cover a stale absolute
  path, a same-named file inside a legacy directory, a missing source and a replaced source.
- Closed: files copied to `knowledge/X-Bookmarks/YYYY/MM/assets/{tweet_id}/{media_key}{ext}` with
  hash-based skip; `media.download_video: false` and `media.max_bytes` honoured.
- Closed: `media.local_path` now holds knowledge-local paths and `## media` references them
  (`process --overwrite` rewritten the single affected file).
- Resolved decision (PLAN.md §5.5): videos stay remote by default (`media.download_video: false`);
  enabling them is a one-line config change.
- Still open: contract verification — video / multi-photo `mediaObjects` and skipped/failed manifest
  `status` strings remain `UNVERIFIED` in `src/collector/contract.py`; no such samples exist in the
  current 5-record corpus. The Phase 8 skip rules are covered with synthetic rows meanwhile.
- Noted for Phase 12: `media.local_path` is an absolute path; the inbox handoff may want a
  knowledge-relative form (ADR-016, "Reconsider When").

## Phase 9 — external link extraction

- `src/external/` fetch wrapper (timeout / retry / redirect / encoding) + web / github / pdf handlers
  per `config.yaml`.
- A failed fetch must keep the original URL in the Markdown and in `external_links`.

## Phase 10 — integrity tests (Test A–L)

- End-to-end integrity matrix + sampling report (see PLAN.md milestone M5).

## Phase 11 — AI enrichment

- Write analysis under the existing `## ai_analysis` heading and `ai_*` frontmatter fields only
  (ADR-015; `ai.protected_fields` must stay untouched).
- User decision still open (PLAN.md §5.6): AI engine selection.

## Phase 12 — pipeline handoff

- Explicit, rollback-able handoff of `knowledge/X-Bookmarks/` to the parent
  `01_Knowledge-Agent/inbox/` (ADR-006); requires user confirmation per AGENTS.md §8.

## Phase 13 — scheduler

- `scripts/install-scheduler.ps1` / `uninstall-scheduler.ps1` / `run-sync.ps1` (PowerShell 5.1).

## Repository / housekeeping

- `git init` decision still open (PLAN.md §5.3).
- Keep `config/config.yaml` in sync with `config/config.example.yaml` when sections change.
