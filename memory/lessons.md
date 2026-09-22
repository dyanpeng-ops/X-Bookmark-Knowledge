# Lessons

Record verified lessons that are likely to prevent future mistakes.

## Recorded Lessons

### 2026-09-15 — A dataclass default is not an explicit value

Problem:

`MediaRecord.download_status` and `ExternalLinkRecord.fetch_status` defaulted to `PENDING`. Because `upsert_*` treats non-`None` fields as "provided", every re-sync wrote `PENDING` back and reset a row that had already reached `DOWNLOADED`.

Cause:

The input dataclass used a domain-meaningful default for a field that also needed to express "caller did not supply this". One value carried two meanings.

Lesson:

When an input object feeds a partial update, `None` must mean "absent". Never let a dataclass default double as "the caller wants this value". If a column is `NOT NULL`, apply its default at the database boundary instead.

Evidence:

`tests/test_database.py::MediaTests::test_upsert_media_preserves_download_status_and_attempts` (regression test added together with the fix); fix recorded in `CHANGELOG.md` Phase 4 → Fixed; decision in `memory/decisions.md` ADR-004.

### 2026-09-15 — An intercepted PowerShell shim fails silently

Problem:

Running `fieldtheory --version` in PowerShell produced no output at all and no visible error, which looked like a hang or an empty result. The same command through `fieldtheory.cmd` returned `1.3.22` with exit code 0.

Cause:

Bare `fieldtheory` resolves to the npm `.ps1` shim. `Get-ExecutionPolicy -List` shows `CurrentUser = RemoteSigned`, which blocks that unsigned shim; the failure does not surface as a normal error message.

Lesson:

Treat "external CLI produced empty output" as a failure, never as success. Call Windows npm shims as `.cmd` or by absolute path, and capture exit codes at the call site.

Evidence:

`Get-ExecutionPolicy -List`; `fieldtheory --version` (silent) vs `fieldtheory.cmd --version` (`1.3.22`, exit 0). Recorded as ADR-007 and in `docs/environment-report.md` §8.

### 2026-09-15 — "Close the browser and retry" was not the real cause

Problem:

`fieldtheory sync --browser chrome` failed with the generic `Couldn't connect to your browser session.` Closing Chrome completely did not change the outcome.

Cause:

Chrome 155 stores x.com cookies with App-Bound Encryption: all 19 x.com cookie rows carry the `v20` prefix, while `fieldtheory@1.3.22` only implements `v10`/raw DPAPI decryption. The locked-file symptom was real but incidental.

Lesson:

Before repeating a workaround, produce evidence for the root cause. Comparing the encryption prefix of the cookie rows, and reading the decrypt branch in the upstream source, was what actually settled it — one probe replaced a whole class of blind retries.

Evidence:

`docs/environment-report.md` §8.2 (prefix `v20` × 19, `app_bound_encrypted_key` present, `v10`-only decrypt branch); `PLAN.md` §3 gate A.

### 2026-09-15 — Long one-line PowerShell commands are unreliable in this terminal

Problem:

Several compound one-liners (nested quoting, inline regex, here-strings) returned mangled output, reported false failures, or were silently truncated by console-buffer errors.

Cause:

The terminal's line editor throws `ArgumentOutOfRangeException` while redrawing long lines, and nested quoting is re-interpreted between the agent layer and PowerShell.

Lesson:

Prefer creating a small script file and running it, or keep commands short and single-purpose. Split work into multiple short commands instead of one long chain; verify side effects by reading the resulting files rather than trusting the echoed command text.

Evidence:

Failed/mangled invocations while generating `__init__.py` files (newlines lost) and while probing `sqlite3` FTS5; both were resolved by writing files with the editor and running a short command.

### 2026-09-15 — Governance files must be filled from measured state

Problem:

`ARCHITECTURE.md`, `memory/*`, `plans/*` arrived as empty templates whose content contradicted reality (e.g. `Completed: None yet` while Phases 0–3 were done), and `ARCHITECTURE.md` listed two directories that do not exist (`context/`, `skills/`) while omitting five that do.

Cause:

Scaffolding was added without reconciling it against the project it describes.

Lesson:

After adding or changing governance documents, reconcile every claim against the repository and re-check that cross-references resolve. A wrong context file is worse than a missing one, because agents read it first.

Evidence:

`memory/current-state.md`, `plans/ACTIVE.md`, `memory/decisions.md`, `ARCHITECTURE.md` reconciled on 2026-09-15; directory list verified with `Get-ChildItem -Recurse -Directory`.

### 2026-09-16 — "Incremental sync succeeded" does not mean "everything was collected"

Problem:

A first run limited to one page reported `Paused after reaching page limit. Run
again to continue.` The next plain `sync` answered `All caught up — no new
bookmarks since last sync`, and a `--continue` run paged 19 times with `0 new`
before reporting `reached the end of new bookmarks`.

Cause:

Upstream has two different stop rules: incremental mode gives up after three
consecutive pages without new records, while `--continue` / `--rebuild` page to
the end. A zero exit code therefore says nothing about coverage.

Lesson:

Never treat exit 0 as proof of completeness. Assert coverage from an independent
signal (`bookmarks-meta.json: totalBookmarks`, `stats --json`,
`backfill-state.stopReason`) and make the full-history switch explicit.

Evidence:

ADR-010; `src/collector/fieldtheory_adapter.py` (`sync` docstring);
`research/architecture-decision.md` §4.3.E.

### 2026-09-16 — The only trustworthy contract test is a read of real data

Problem:

The unit suite was green (142 tests) while `FieldTheoryAdapter.read_backfill_state()`
crashed on the real upstream file with `missing required key 'lastCursor'`.

Cause:

The fixtures were built from an earlier capture. A later media-only run wrote a
`bookmarks-backfill-state.json` without `lastCursor`, because that key only exists
when a run stops at a page limit. Fixture-only tests cannot notice a field that
disappears over time.

Lesson:

Keep the synthetic fixtures for logic, but always finish a contract change with a
read-only pass over the real upstream directory. Any mismatch found there is a
contract bug, not a data problem.

Evidence:

`tests/test_collector_contract.py :: test_last_cursor_is_conditional`;
`contract.BACKFILL_STOP_REASONS_OBSERVED`.

### 2026-09-16 — Nested objects need explicit required keys

Problem:

`validate_bookmark_record` accepted a `mediaObjects` entry of `{"url": ...}`
without `type`, because nested validation only checked the types of keys that
happened to be present.

Cause:

The validator was written with an empty "required" list for nested objects, so
the absence of a key was never an error.

Lesson:

For every nested structure, state the minimum keys that make it usable, and let a
test prove that omitting one of them fails. A type check alone is not a contract.

Evidence:

`contract.AUTHOR_REQUIRED_KEYS` / `ENGAGEMENT_REQUIRED_KEYS` /
`MEDIA_OBJECT_REQUIRED_KEYS`; `tests/test_collector_contract.py ::
test_media_object_shape_is_validated`.

### 2026-09-16 — Browser-based authentication is a platform matrix, not a single path

Problem:

Earlier findings concluded "authentication is broken on this machine" after Chrome
155 could not be read. Installing Firefox and logging into x.com made collection
work on the first attempt.

Cause:

The failure was specific to Chrome's App-Bound Encryption (`v20` cookies), not to
the machine, the account, or the upstream tool. Firefox stores the same cookies in
plaintext.

Lesson:

When an external tool fails on a platform-specific path, enumerate every supported
variant before declaring a blocker, and record which variant was actually tested.
`docs/environment-report.md` now keeps both the Chrome evidence and the Firefox
resolution.

Evidence:

`docs/environment-report.md` §8.2/§8.3; ADR-008.

### 2026-09-16 — A test double can overwrite real data when the target is resolved from ambient state

Problem:

While the config/env precedence was "environment variable wins", `tests/test_cli.py` ran the offline
upstream stub against the **real** upstream directory: `data/upstream/bookmarks.jsonl` was replaced by
3 synthetic fixture records, `bookmarks.db` grew to 8 rows, and `stub-argv.txt` was left behind.

Cause:

The temp config in the test set `collector.upstream_data_dir`, but `load_config` preferred the
machine-wide `FT_DATA_DIR` (set moments earlier by the relocation to `D:`). The test therefore resolved
to the production path, and the stub wrote there exactly as designed.

Lesson:

A test must not merely "use a temp directory" — the code under test must be unable to reach production
paths even when the machine has relevant environment variables. Prefer project configuration over
ambient state, and after any such fix, prove isolation by running the whole suite and comparing the
real directory's file list and timestamps before/after.

Evidence:

ADR-013; `src/config.py::_build_collector`; verification run comparing `data/upstream` before and after
204 tests (unchanged); the incident section in `CHANGELOG.md` Phase 6.

### 2026-09-16 — `UpsertResult.changed` must mean "something actually differed"

Problem:

`upsert_media()` and `upsert_external_link()` returned `changed=True` unconditionally, so every sync
reported `media rows: 0 new, 2 updated, 0 unchanged` no matter what happened.

Cause:

The bookmark upsert computed the flag by comparing supplied fields with the stored row; the media and
link upserts computed the same value locally but then threw it away in the `return`.

Lesson:

When three functions share a result contract, assert that contract for all three. Reporting flags are
part of the API: a flag that is always true silently removes the signal readers rely on (here: whether
the second run of a sync actually changed anything).

Evidence:

`src/database/repository.py` (media/link upserts now return the computed flag);
`tests/test_ingest.py::IdempotencyTests::test_media_and_links_are_idempotent`.

### 2026-09-20 — A field that a later phase owns must be write-once in earlier phases

Problem:

Phase 8 rewrote `media.local_path` from the upstream cache path to the knowledge-local path. The
very next `sync --skip-collect` put the old upstream path back, because ingest always sends the
manifest's `localPath` and `upsert_media` treats any non-`None` value as "provided". The same trap
appeared with skip states: writing `SKIPPED` would be flipped back to `DOWNLOADED` by the next
manifest read, inflating the `media updated` counter on every run.

Cause:

Two phases disagreed about who owns one column. The write path assumed "later write wins", but the
earlier phase re-runs forever (the manifest is refreshed on every sync), so the later phase's value
could never survive.

Lesson:

Decide field ownership explicitly when a phase starts, and encode it: the owning phase writes the
field, every earlier phase writes it at most once (insert-only) and any "policy skip" is recorded in
a field the earlier phase never touches (`error_message` here) instead of in a status column that
upstream keeps re-asserting. A value that a repeated upstream read can overwrite is not a state the
project actually stores.

Evidence:

`src/ingest/ingest.py` (`_ingest_media` now passes `local_path` only for new rows);
`tests/test_ingest.py::MediaTests::test_local_path_is_written_on_insert_and_never_overwritten`;
`tests/test_media.py::ProcessMediaIntegrationTests::test_reingest_after_media_does_not_revert_local_path`;
ADR-016.

## Template

### YYYY-MM-DD — Topic

Problem:

What happened.

Cause:

Why it happened.

Lesson:

What should be done differently next time.

Evidence:

Relevant files, tests, or observations.

### 2026-09-21 - a dry-run flag can suppress writes while still using the network

Problem:

`links --dry-run` was listed in a pending-verification list as an offline check; the approved run
made one real outbound HTTP request. The flag only suppresses file/DB writes.

Cause:

The description was written from the flag name, not from the code path: the resolver calls the
fetcher before any persistence branch, so dry-run cannot refuse network use.

Lesson:

Before a command goes on an approval list, read the code path and state side effects from code,
not from the flag name: does it touch the network, the disk, the DB, credentials?

Evidence:

`src/external/resolver.py` (no dry-run guard before the fetcher call); approved run 2026-09-21
(`fetched : 1`, nothing written); correction logged in `tasks/CURRENT.md` and README.

### 2026-09-21 - not verified means even the import may be broken

Problem:

Phase 9 was delivered implemented-not-verified; its first-ever test run failed at package import
(the handlers base module used the wrong relative import), and the run then surfaced two further
NameErrors that static reading had missed.

Cause:

Nothing between implementation and acceptance executed the package; each module looked correct
in isolation.

Lesson:

Treat an unverified package as unknown until executed: run the suite (after approval) before
claiming completeness, and never infer the health of untested code from tested neighbours.

Evidence:

`Ran 369 tests ... OK` on 2026-09-21 after fixing the handlers base import, the missing
`ALL_LINK_STATUS_VALUES` import in the repository, and a stray guard-clause reference.
