# Current Task — X Bookmark Knowledge Pipeline

> Updated: 2026-09-21 (Phase 9 review closed; offline suite green under approval)
> Status: the real-data **write** run (links / process / sync regression) still awaits approval.

## Verified project state

- Phases 0-8 are complete and accepted; Phase 9 is implemented and its 2026-09-20 review blockers are closed.
- Acceptance command: `.venv\Scripts\python.exe -m unittest discover -s tests -t .` ->
  **369 tests, exit 0** (approved run 2026-09-21). Before Phase 9 it was 272 (Phase 4: 68,
  Phase 5: 76, Phase 6: 60, Phase 7: 23, Phase 8: 44 + 1); Phase 9 adds 97 (94 in
  `tests/test_external.py`, incl. 8 review tests, + 3 database/ingest regressions).
  Everything offline - temp dirs, injected fakes; the real `data/` is untouched.
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
- `src/cli/` — `python -m src.cli sync|media|links|process|status|doctor`, exit codes 0/1/2/3.
  Pipeline order: `sync → media → links → process`.
- `src/external/` — `fetcher.py` (stdlib `urllib`, hop-by-hop redirects, timeout/retry/backoff,
  size cap, charset detection, injectable transport), `handlers/` (`web`, `github`), `resolver.py`
  (`LinkResolver`: `assets/{tweet_id}/links/{link_key}.md`, per-link isolation, `FAILED` rows stop
  at `external.max_attempts`).
- Version control (updated 2026-09-21): private GitHub remote `X-Bookmark-Knowledge`; `main`
  tracks `X-Bookmark-Knowledge/main` - pushed `932c57f`, local `66b67c6` one ahead. The Phase 9
  change set itself is still **uncommitted**; commit and push each need approval. Real bookmark
  content stays out of Git (`knowledge/*` ignored except its README); secrets stay local
  (`config/config.yaml`, `data/`, `.venv/`, `*.db`).
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

**Phase 10 (content integrity tests, Test A-L)** has not started; do not start it without
user approval. Phase 9 itself needs only the real-data write run listed under "Verification
status" below.
2. Extract title/body and write `external_links.{resolved_url, title, content_path, fetch_status}`;
   a failed fetch must keep the original URL and mark the row `FAILED` without aborting the batch.
3. Feed extracted content into the Markdown `## external_links` section.
4. Tests: timeout/retry/redirect/failure-keeps-URL, per-link isolation, idempotency, offline only.

## Phase 9 - implemented; review closed 2026-09-21; real-data run pending

Phase 9 (external link extraction, `src/external/`) is implemented:

1. Unified fetch wrapper (`fetcher.py`): stdlib `urllib`, timeout, retries with backoff, hop-by-hop
   redirects, charset detection, `max_bytes` cap, injectable transport.
2. Extraction (`handlers/`): `web` / `github`; title + body + `resolved_url` + `content_path`
   written to `external_links` with `fetch_status` (`FETCHED` / `FAILED` / `SKIPPED`); a failed
   fetch keeps the original URL and marks only that row `FAILED`.
3. Content written to `assets/{tweet_id}/links/{link_key}.md` and rendered into
   `## external_links` (`- [title](url)` + content path / final URL / failure reason).
4. Tests in `tests/test_external.py`: timeout/retry/redirect/failure-keeps-URL, per-link
   isolation, idempotency (second `links` run makes no network request), offline only.
5. Regression fix: ingest now writes `fetch_status` only on insert — a repeated `sync` no longer
   resets link rows to `PENDING` (same defect class as Phase 6 defect #1).
6. Review close-out (2026-09-21): SSRF guard `src/external/netguard.py` (checked on the initial
   target and after every redirect hop), canonical URL persisted into `resolved_url` and the
   link body, and `set_link_status(..., clear_fields=...)` clearing a stale body when a forced
   or exhausted refetch fails.
7. Approved runs (2026-09-21): `tests.test_external` 94 OK; full suite 369 OK, exit 0;
   `git diff --check` clean; real-data `links --dry-run` fetched one page and wrote nothing
   (correction: `--dry-run` still makes outbound HTTP; it only suppresses writes).

## Phase 9 review (raised 2026-09-20, reviewer-assigned) — CLOSED 2026-09-21

All four findings below were **closed on 2026-09-21** (Resolution subsection under the list);
the text is kept as the reviewer's/original record. Fixing them was in scope; running the
acceptance suite was separate - it has since been approved and run (see below).

1. **BLOCKER — SSRF / sensitive-content write-through.** `src/external/fetcher.py:429`, `:452` and
   `src/external/resolver.py:455` only allow `http`/`https`: `localhost`, private ranges, link-local and
   cloud-metadata addresses (`169.254.169.254`) are not rejected, and the target is not re-validated
   after a redirect. A malicious bookmark link could make `links` read an internal service and write it
   into the knowledge base, violating `AGENTS.md` §6 (no sensitive values in Markdown products).
   Required: block non-public targets on the initial request **and after every redirect hop**, record a
   clear skip/failure reason, keep it configurable, and cover it with offline tests.
2. **MEDIUM — extracted canonical URL never reaches the product or the state store.**
   `src/external/handlers/web.py:238` parses `canonical_url`, but `src/external/resolver.py:359` persists
   the redirect-final URL, so canonical information is dropped and the canonical-parsing tests do not
   translate into an end-to-end capability. Required: carry canonical through to the persisted
   `external_links` row and/or the generated link body, and assert it end to end.
3. **MEDIUM — forced-refetch failure leaves stale content while marking `FAILED`.**
   `src/external/resolver.py:402` keeps the old `content_path`, title and resolved URL when a forced
   refetch fails, producing a "FAILED status + old body file" state that is hard to judge by hand,
   especially once `external.max_attempts` is exhausted. `set_link_status()`
   (`src/database/repository.py:580`) can only update non-empty fields, so the failure path cannot clear
   them. Required: give the repository an explicit way to clear fields (respecting ADR-004 — `None` must
   keep meaning "not provided") and use it on the forced-refetch failure path.

Lint nit (non-blocking): trailing blank lines at the end of `src/external/__init__.py` (line 93) and
`src/external/handlers/__init__.py` (line 92) — reported by `git diff --check`.

### Resolution (2026-09-21) — all four closed

1. **SSRF:** new `src/external/netguard.py` refuses non-public targets (loopback, private,
   link-local incl. `169.254.169.254`, CGNAT, multicast, reserved, IPv6 ULA; IPv4-mapped
   resolved first) on the initial request and after every redirect hop; `BlockedTargetError`
   is recorded as a policy skip (reason persisted, no attempt counted, no network). Config:
   `external.block_non_public_hosts: true`, `external.allow_hosts: []`. `host_resolver` is
   injectable so the offline tests never touch DNS.
2. **Canonical:** the handler's `canonical_url` is persisted as `external_links.resolved_url`
   (redirect-final only as fallback) and written into the link body; asserted end to end in
   `ReviewFixTests`.
3. **Stale body:** `repository.set_link_status(..., clear_fields=(...))` clears columns
   explicitly (`None` still means not provided - ADR-004 intact). The resolver clears
   `content_path`/`title`/`resolved_url` when a `--force` refetch fails or the attempt budget
   is exhausted; ordinary transient failures keep the last good body.
4. **Lint nit:** both files cleaned; `git diff --check` exits 0.

Defects the suite run itself exposed (also fixed): the wrong relative import in
`handlers/base.py` (the whole `src.external` package could not be imported), a missing
`ALL_LINK_STATUS_VALUES` import in `repository.py`, a stray `attempts_total` reference in
`fetcher._guard`, and the misleading report label `local links` (renamed `links known`).


## Verification status (Phase 9 — offline done; write run pending)


Done under approval **(2026-09-21):** the offline item 1 ran: `Ran 369 tests ... OK` (exit 0,
incl. `tests/test_external.py` 94); the real-data dry-run ran: fetched 1 / skipped 4 / failed 0,
nothing written (**correction:** the dry-run flag does NOT suppress outbound requests).
The write run (items 4-6) plus commit/push still await approval.

Offline (no network, no writes to real `data/` / `knowledge/`; temp dirs only):

1. `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -t .` — full suite (was 272; Phase 9
   adds `tests/test_external.py` + ingest/database regression cases). Expected: exit 0.
2. `.\.venv\Scripts\python.exe -B -m src.cli doctor` — config/adapter/DB self-check (read-only).

Real-data (uses `config/config.yaml`; `links` makes outbound HTTP to bookmarked pages):

3. `.\.venv\Scripts\python.exe -B -m src.cli links --dry-run` — reports what would be fetched;
   writes nothing. Expected: `cobalt.tools` fetched, the four `x.com/i/article/...` links SKIPPED.
4. `.\.venv\Scripts\python.exe -B -m src.cli links` — writes `assets/{tweet_id}/links/*.md`,
   marks rows FETCHED. Then again: second run must report `unchanged` and make **no** network
   requests.
5. `.\.venv\Scripts\python.exe -B -m src.cli process` — `## external_links` renders title +
   relative content path; then again: `written: 0 / unchanged: 5`.
6. `.\.venv\Scripts\python.exe -B -m src.cli sync --skip-collect` — must report
   `link rows : 0 new, 0 updated, 5 unchanged` (link statuses not reset).


## Hard stop

Phase 10 has not started; do not start it without authorization. **Verification is gated (user rule, 2026-09-20): read-only
inspection is allowed, but running tests, any network access (`ls-remote` / `clone` / `fetch` / `push`),
and any write to disk / database / knowledge require explicit approval — present the pending-verification
list and wait.** Do not write into `knowledge/` outside the configured knowledge directory. Never record
credentials, cookies or tokens in project files, logs or task notes.

## Audit follow-up

- Closed: `scripts/README.md` documents the CLI flow (now including `media` and `links`).
- Closed: `plans/backlog.md` contains the real backlog.
- Still open: `src/collector/contract.py` — video/multi-photo `mediaObjects` and skipped/failed
  manifest `status` strings remain `UNVERIFIED` until such samples appear; Phase 8 now has skip-rule
  tests using synthetic rows, but the contract itself stays frozen until real samples exist.
