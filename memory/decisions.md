# Architecture & Technical Decisions

Use this file for durable decisions and, most importantly, why they were made.

## Accepted Decisions

### ADR-001 — Use the fieldtheory CLI as the Collector, behind an adapter

Date: 2026-09-15

Decision:

Collect bookmarks by invoking the upstream `fieldtheory` CLI and reading its `bookmarks.jsonl`, `media-manifest.json` and `media/` output through `src/collector/`. The project does not implement an X client.

Reason:

Upstream is MIT-licensed, actively maintained, already installed and verified on this machine, and its CLI already covers incremental sync, `--continue`, `--gaps`, media download and folder sync. Re-implementing GraphQL paging and session handling would duplicate the hardest part.

Alternatives:

(a) Adopt the whole pipeline from `fieldtheory`; (b) use `TweetKB` as the collector; (c) build a self-hosted GraphQL collector; (d) use extension-based tools (MarkHarbor, xarchive, XClipper).

Rejected Because:

(a) would take over the data directory and Markdown format, conflicting with the project-owned schema and the parent Inbox flow; (b) is macOS-first and does not declare Windows support; (c) violates "reuse before rebuild"; (d) are not scriptable for unattended runs, and XClipper's licence is non-commercial.

Reconsider When:

Upstream is unmaintained for 12 months, breaks its output format, or all three authentication paths fail (then fall back to (c)).

### ADR-002 — Pin Python 3.12.13 in a project-local `.venv`; use stdlib `unittest`

Date: 2026-09-15

Decision:

Create `.venv` from Python 3.12.13 (`%APPDATA%\uv\python\...`) and use `unittest` rather than pytest.

Reason:

The machine default is Python 3.14.3, which is too new for predictable third-party wheel coverage, while 3.12.13 is already present. `unittest` keeps third-party runtime dependencies at zero, matching the project rule to avoid unnecessary dependencies.

Alternatives:

Python 3.14.3; pytest; a bare `uv`-managed environment.

Rejected Because:

3.14 risks install failures later; pytest's advantages (parametrisation, fixtures) are not yet needed — the current suite expresses everything with plain `unittest`.

Reconsider When:

Parameterised or fixture-heavy tests appear, or a runtime dependency demands another interpreter.

### ADR-003 — The project's SQLite is the single source of truth; upstream data is read-only

Date: 2026-09-15

Decision:

`data/state/*.db` owns status, attempts and dedup. Upstream `~/.fieldtheory/**` is read-only input; the project never writes there.

Reason:

Keeps idempotency under project control, keeps knowledge output independent of upstream releases, and satisfies the parent `AGENT.md` rule that original data and derived knowledge stay separate.

Alternatives:

Treat upstream's index as authoritative; store status next to upstream data.

Rejected Because:

Upstream must stay replaceable (ADR-001) and must never be mutated by this pipeline.

Reconsider When:

Upstream exposes a stable, documented status API that removes the need for a local state store.

### ADR-004 — In upsert inputs, `None` means "not provided"

Date: 2026-09-15

Decision:

`upsert_bookmark` / `upsert_media` / `upsert_external_link` write only non-`None` fields on update. Therefore `MediaRecord.download_status` and `ExternalLinkRecord.fetch_status` default to `None` and fall back to the database default (`PENDING`) on insert only.

Reason:

A sparse upstream record must not erase archived content or reset a `DOWNLOADED` status. Discovered during Phase 4: the previous `PENDING` default silently reset download status on re-sync.

Alternatives:

Treat dataclass defaults as explicit values; introduce separate patch types.

Rejected Because:

Defaults-as-explicit-values caused the bug; patch types add surface the project does not need yet.

Reconsider When:

A caller genuinely needs to clear a field to `NULL`, which then requires an explicit sentinel value.

### ADR-005 — `last_synced_at` is written only by sync

Date: 2026-09-15

Decision:

Only `upsert_bookmark` updates `last_synced_at`; state transitions and error recording leave it untouched.

Reason:

Avoids conflating "when upstream was last read" with "when the record was last processed", which would make stale-sync detection unreliable.

Alternatives:

Update it on every write.

Rejected Because:

It would make the column useless for detecting a stalled sync.

Reconsider When:

A separate `last_processed_at` column is introduced.

### ADR-006 — Knowledge output is handed to the parent Inbox, not written into the parent knowledge base

Date: 2026-09-15

Decision:

Generate Markdown under this project's `knowledge/X-Bookmarks/`, then hand it to `01_Knowledge-Agent/inbox/X-Bookmarks/`. Do not write into the parent `knowledge/`.

Reason:

The parent `AGENT.md` requires new material to enter through `inbox/` and to reach `knowledge/` only after analysis. X bookmarks are raw/derived material, not distilled knowledge.

Alternatives:

Write directly into `01_Knowledge-Agent/knowledge/{AI,Agent,...}`.

Rejected Because:

It would bypass the parent Inbox workflow and violate the "knowledge vs. source material" separation.

Reconsider When:

The parent workflow itself changes.

### ADR-007 — Invoke upstream through `fieldtheory.cmd`

Date: 2026-09-15

Decision:

The adapter must call `fieldtheory.cmd` or an absolute executable path, never bare `fieldtheory`, when running under PowerShell.

Reason:

Measured on this machine: bare `fieldtheory` resolves to the `.ps1` shim, which the `RemoteSigned` execution policy blocks silently (no output, no error surfaced); `fieldtheory.cmd --version` returns `1.3.22` normally.

Alternatives:

Rely on PATH resolution; launch with `-ExecutionPolicy Bypass`.

Rejected Because:

Silent failure is the worst outcome for a scheduled task, and weakening the host execution policy is not acceptable.

Reconsider When:

The execution policy changes or upstream ships a single cross-shell launcher.

## Decision Template

### ADR-008 — Windows 认证采用 Firefox 会话，不实现 Cookie 解密

Date: 2026-09-16

Decision:

The Collector uses `fieldtheory sync --browser firefox`. The project never
implements cookie decryption itself; manual `--cookies` and OAuth stay as
documented fallbacks only.

Reason:

Chrome 155 marks x.com cookies with App-Bound Encryption (prefix `v20`) and
`fieldtheory@1.3.22` only decrypts `v10`/raw DPAPI, so the Chrome path fails with
`Couldn't connect to your browser session.` Firefox 156 stores cookies in
plaintext `cookies.sqlite`; a real run succeeded immediately
(`✓ 5 new bookmarks synced`, exit 0).

Alternatives:

Manual `--cookies <ct0> <auth_token>`; OAuth via a self-built X developer app;
reimplementing Chrome ABE decryption inside this project.

Rejected Because:

Manual cookies are secrets that must be pasted by hand and leak easily; OAuth
needs credentials and an unclear free-tier bookmark permission; implementing
ABE decryption would duplicate upstream behaviour and break the adapter
boundary defined in ADR-001.

Reconsider When:

Upstream fixes `v20` support (then Chrome can be revisited), or Firefox stops
being usable/installable on the machine, or OAuth prerequisites become known and
stable.

### ADR-009 — Enrichment is read via `list --json`, not from the JSONL cache

Date: 2026-09-16

Decision:

`bookmarks.jsonl` supplies raw records only. Article bodies, categories,
folders, view counts and quoted tweets are read through
`fieldtheory list --json` (bulk) and `fieldtheory show <id> --json` (single).

Reason:

Real sample: the JSONL has 21 fixed keys and the article-style bookmarks carry
only a `x.com/i/article/…` placeholder in `text`. The enriched values
(article text of 12558 / 11149 / 2842 / 1898 chars) exist only in the upstream
SQLite database and are exposed exclusively through those CLI commands. Reading
the database file directly would couple this project to an undocumented internal
schema.

Alternatives:

Parsing `bookmarks.db` directly with `sqlite3`; fetching article bodies
ourselves in Phase 9; running `--gaps` and hoping the JSONL is updated.

Rejected Because:

Direct DB access violates "the upstream CLI is the only integration point";
self-fetching is Phase 9 work that would duplicate an existing capability;
`--gaps` only added `textExpandedAt` to the JSONL and left article text in the DB.

Reconsider When:

`list --json` cannot express pagination for large libraries (hundreds of rows) —
then re-evaluate `list --json --limit` batching or per-id `show` calls.

### ADR-010 — Full history requires `--continue` or `--rebuild`

Date: 2026-09-16

Decision:

The first collection (and any "fill the history" run) must pass `--continue` or
`--rebuild`. A plain incremental `sync` is only for the daily top-up.

Reason:

Measured behaviour: the default incremental mode stops after three consecutive
pages with no new records (`stalePageLimit = 3`), and a second plain `sync`
reported `All caught up — no new bookmarks since last sync` even though the run
before it had been limited to one page. Only `--continue` and `--rebuild` page
through the whole list.

Alternatives:

Repeatedly calling plain `sync`; assuming `--max-pages` state resumes
automatically.

Rejected Because:

A plain repeat stops before reaching older bookmarks, silently producing an
incomplete archive — the worst failure mode for a knowledge pipeline.

Reconsider When:

Upstream changes its staleness rule or documents automatic resume.

### ADR-011 — Upstream data directory is relocatable via `FT_DATA_DIR`

Date: 2026-09-16

Decision:

The adapter resolves the upstream data directory as
explicit argument > `FT_DATA_DIR` > `~/.fieldtheory/bookmarks`, and always sets
`FT_DATA_DIR` explicitly for the subprocess it spawns. Media may be redirected
to the D: drive when its volume grows.

Reason:

`C:` has only ~6.4 GB free while the project (and its media archive) lives on
`D:`. Upstream defaults to `~/.fieldtheory/bookmarks` on `C:` and allows up to
200 MB per media asset (`--media-max-bytes`), so an unfiltered media run can fill
the system drive.

Alternatives:

Editing upstream config files; leaving media on `C:` and monitoring usage;
downloading media with `--no-media` forever.

Rejected Because:

Editing upstream files breaks the read-only boundary; leaving media on `C:`
leaves an unmitigated disk-space risk; never archiving media would lose assets
the knowledge base is supposed to be self-contained about.

Reconsider When:

Media volume stays small (current sample: 6 files, ~166 KB) so relocation is
unnecessary, or the user decides media should live elsewhere.

### ADR-012 — PyYAML is the configuration parser

Date: 2026-09-16

Decision:

`config/config.yaml` is parsed with PyYAML (`pyyaml==6.0.3`), pinned in `requirements.txt`. It is the
project's first third-party runtime dependency.

Reason:

The configuration is already published as YAML (`config/config.example.yaml`) with nested mappings,
lists and comments. The standard library has no YAML parser, and hand-writing a good-enough subset
would have to handle quoting, escapes, indentation and type coercion — all easy to get subtly wrong
in a file that controls where data is written.

Alternatives:

Hand-rolled YAML subset parser; switching to INI/TOML (stdlib `tomllib` is read-only but available);
JSON configuration.

Rejected Because:

A hand-rolled parser is the highest-risk option for a file that decides filesystem targets; moving to
INI/TOML would break the already-reviewed example config and lose nested structure; JSON cannot carry
comments, and this config is meant to be read by a human.

Reconsider When:

A "zero third-party dependency" constraint is imposed (then: move to INI and migrate the example
config), or a YAML feature we rely on proves problematic.

### ADR-013 — Configuration wins over environment variables

Date: 2026-09-16

Decision:

`collector.upstream_data_dir` is taken from `config/config.yaml` first; `FT_DATA_DIR` is only consulted
when the config leaves it empty. The adapter still exports the resolved directory to the upstream
subprocess as `FT_DATA_DIR`.

Reason:

A machine-wide environment variable cannot be seen or overridden by a repository checkout, which made
an offline test write 3 synthetic fixture records into the real upstream directory (see the Phase 6
incident). The project's configuration file is the single place that defines where this project reads
and writes.

Alternatives:

Keep environment-first precedence (needed for ad-hoc switches); require an explicit `--upstream-dir`
CLI flag instead of reading the environment at all.

Rejected Because:

Environment-first makes repository behaviour depend on invisible machine state; a CLI flag alone would
leave the adapter unusable without the CLI wrapper.

Reconsider When:

Multiple checkouts must share one upstream directory on the same machine — then add an explicit
`--upstream-dir` option rather than relying on ambient variables.

### ADR-014 — Force UTF-8 in upstream subprocesses (env `PYTHONIOENCODING`) and in the test stub's streams

Date: 2026-09-17

Decision:

`FieldTheoryAdapter._run()` sets `PYTHONIOENCODING=utf-8` in the environment passed to the upstream
subprocess, and `tests/support/stub_fieldtheory.py` reconfigures its own `stdout`/`stderr` to
UTF-8 (`errors="replace"`) at startup.

Reason:

On Chinese Windows the console code page is cp936 (GBK). The upstream CLI prints non-GBK
characters (`✓`, `⠋`) in its progress output; the child process raised
`UnicodeEncodeError: 'charmap' codec can't encode character ...` and every collector test crashed.
This single root cause produced 14 test failures across `test_cli`, `test_collector_fieldtheory` and
`test_markdown`. Pinning the child's Python IO encoding to UTF-8 removes the dependency on the
ambient console code page; the stub does the same for its own streams so the parent side (which
decodes with UTF-8) always receives valid bytes.

Alternatives:

Set the console code page to 65001 in the test harness (`chcp` / `SetConsoleOutputCP`); use
`errors="replace"` on the adapter side only; wrap all output decoding in try/except.

Rejected Because:

Changing the console code page leaks into the surrounding shell and other processes;
`errors="replace"` in the adapter alone does not stop the child from crashing (the failure is on the
child's write path); broad exception swallowing would mask real upstream errors.

Reconsider When:

Upstream switches its progress output to a non-emoji/box-drawing-safe charset, or the project moves
to a runner that controls the console code page centrally.

### ADR-015 — Implement `thread` and `ai_analysis` Markdown sections instead of dropping them from config

Date: 2026-09-17

Decision:

`markdown.include_sections` in `config.example.yaml` lists `thread` and `ai_analysis`; the renderer
implements both. `## thread` renders the enrichment `quotedTweet` (author handle, tweet id, quoted
text) from `data/raw/{tweet_id}.json`, with a `_无引用推文_` placeholder when absent.
`## ai_analysis` is an explicit placeholder paragraph for now; the Phase 11 AI writer must write its
content under the same `## ai_analysis` heading.

Reason:

Both sections are part of the declared config contract, and every unknown section name produced a
warning per file on every `process` run. The quoted-tweet data is already available in the raw
archives, so `thread` adds real value at zero extra collection cost. A stable placeholder heading
gives Phase 11 a fixed write target and keeps the file layout constant before and after enrichment.

Alternatives:

Remove both names from the config; implement only `thread` and keep `ai_analysis` as a warning.

Rejected Because:

Removing config keys shrinks the declared contract and silently changes the Markdown layout for the
knowledge base; leaving a permanent warning is noise that masks genuinely misconfigured sections.

Reconsider When:

Phase 11's AI design changes where analysis content lives (e.g., frontmatter-only), or the `quotedTweet`
enrichment shape diverges from the frozen contract.

### ADR-016 — Media localisation owns `media.local_path`; policy skips are recorded, not stored as `SKIPPED`

Date: 2026-09-20

Decision:

Phase 8 copies every manifest media row into `knowledge/X-Bookmarks/{YYYY}/{MM}/assets/{tweet_id}/`
under the stable name `{media_key}{ext}` (`media_key = sha1(source_url)[:16]`), then writes that
knowledge-local absolute path into `media.local_path`. Consequences:

1. The ingest layer writes `media.local_path` **only when it inserts the row**; a later `sync` never
   overwrites it. The field means "where this project keeps the bytes", not "where upstream put them".
2. Source files are located by **file name** under the configured `<upstream_data_dir>/media/`
   (manifest index first, then `local_path`'s name, then the URL's name). The legacy C: cache is never
   read, even when a same-named file exists there. An unresolvable row is recorded as `FAILED`.
3. Policy skips (`media.download=false`, upstream status != `downloaded`, `download_video=false` for
   `video`/`animated_gif`, size over `media.max_bytes`) keep the row's upstream status and write
   `error_message = "skipped: <reason>"` instead of setting `SKIPPED`.

Reason:

The upstream manifest is re-read on every `sync` and always claims `downloaded`; if Phase 8 wrote
`SKIPPED` (or let ingest keep writing `local_path`), each sync would flip the row back and report
"everything updated" — the same defect class as Phase 6's hard-coded `changed = True`, and it would
erase the localisation result. Keeping skips as a reason string makes the state durable without
fighting the upstream status vocabulary, and lets the Markdown layer fall back to the remote URL
(information is never lost) for anything that is not local.

Alternatives:

Store the knowledge path in a new `media.knowledge_path` column and leave `local_path` untouched;
write `SKIPPED` for policy skips; trust `local_path` directly (including legacy absolute paths);
skip `profile_image` rows entirely.

Rejected Because:

A new column is a schema change the audit did not ask for, and `local_path` already means "the local
copy this project knows about". Writing `SKIPPED` loses the upstream truth and churns on every sync.
Trusting `local_path` would make the knowledge base depend on a `C:` cache the project no longer
owns (explicitly forbidden by the audit). Excluding `profile_image` rows would leave five of six rows
pointing outside the knowledge tree, contradicting the same audit expectation; avatars are stored but
never referenced by `## media`.

Reconsider When:

Upstream stops including `profile_image` entries in the manifest, the media set grows large enough
that storing avatars matters, or Phase 12's handoff wants a relative (not absolute) `local_path` in
the database.


Reconsider When:

Upstream stops including `profile_image` entries in the manifest, the media set grows large enough
that storing avatars matters, or Phase 12's handoff wants a relative (not absolute) `local_path` in
the database.

### ADR-017 — External links use the standard library only (`urllib` + `html.parser`); redirects are followed hop by hop; the transport is injectable

Date: 2026-09-20

Decision:

Phase 9's fetch wrapper (`src/external/fetcher.py`) uses only the standard library:
`urllib.request` with a `_NoRedirectHandler` so that 3xx responses surface to the wrapper, which
follows them hop by hop (recording the chain, applying `max_redirects`, resolving relative
`Location` with `urljoin`, rejecting non-http(s) hops). Content extraction (`src/external/handlers/`)
parses HTML with `html.parser`. The transport is a callable injected into `HttpFetcher`, so every
test is offline; `urllib` never runs inside the test suite. Requests carry
`Accept-Encoding: identity` because the standard library does not decompress.

Reason:

The project rule is "minimal dependencies" (AGENTS.md §5) and the pending PLAN.md entry already
preferred stdlib `urllib`. Redirects must be visible (they decide `resolved_url`, which the
knowledge base shows for auditing) — letting `urllib` follow them silently would lose the chain
and the hop limit. HTML extraction needs "title + description + readable body", not full
readability scoring; `html.parser` with a skip-tag list is deterministic, fast, and testable.

Alternatives:

`httpx`/`requests` for fetching; `trafilatura`/`readability`/`beautifulsoup4` for extraction;
letting `urllib` follow redirects by default; storing partial bodies when the size cap is exceeded.

Rejected Because:

Every HTTP/HTML dependency adds a version to pin for a workload of ~1 page per bookmarked link.
Auto-redirects hide the final URL and the hop count from the database. Partial HTML bodies produce
misleading "extracted content", so an over-size page fails cleanly with the original URL retained.
A PDF handler was considered for Phase 9 but deferred: stdlib cannot parse PDFs, so `pdf` links are
recorded as `SKIPPED` (reason stored, URL retained) until Phase 10 evaluates a real dependency.

Reconsider When:

A real bookmark sample needs HTTP/2, JS rendering, or readability-quality extraction — then the
dependency decision must be recorded in CHANGELOG.md with the sample evidence.

### ADR-018 — Link content lives in `assets/{tweet_id}/links/{link_key}.md`; `fetch_status` is written by ingest only on insert; FAILED rows stop retrying at `external.max_attempts`

Date: 2026-09-20

Decision:

1. Extracted link content is written to
   `knowledge/X-Bookmarks/{YYYY}/{MM}/assets/{tweet_id}/links/{link_key}.md` with
   `link_key = sha1(url)[:16]` — the same naming contract as media keys. The file carries a
   timestamp-free frontmatter (`source_url` / `resolved_url` / `title` / `description` / `domain`
   / `handler`) plus the body, so re-fetching an unchanged page rewrites nothing.
2. The ingest layer writes `external_links.fetch_status = PENDING` only when it **inserts** the
   row (the same rule Phase 8 introduced for `media.local_path`). A repeated `sync` therefore never
   resets `FETCHED`/`FAILED`/`SKIPPED` back to `PENDING`.
3. A `FETCHED` row whose content file still exists inside the knowledge tree is reported
   `unchanged` **without touching the network**; `links --force` re-fetches. `FAILED` rows are
   retried until `external.max_attempts` (default 3), then reported skipped until `--force`.
4. `x.com`/`twitter.com` are in the default `external.skip_domains`: their article bodies already
   come from enrichment (`## article`), and direct fetches hit a login wall.

Reason:

Idempotency must survive every command in the pipeline. Ingest re-runs on every `sync`, so a
status reset there would undo all fetch work — the same defect class as Phase 6's hard-coded
`changed = True`. Not re-fetching completed links keeps `links` a no-network operation on the
second run, which is the project's core acceptance criterion applied to the network layer. A
bounded retry count prevents permanently dead links from burning attempts on every run.

Alternatives:

Inline extracted text into the tweet's Markdown; store extracted content in `data/`; retry FAILED
forever; fetch X article links directly instead of relying on enrichment.

Rejected Because:

Inlining makes per-tweet files rewrite on every upstream page change and breaks the "one tweet =
one file" shape; `data/` is program data, not the knowledge base (red line in AGENTS.md §3);
unbounded retries are wasted traffic; X fetches fail by design (login wall).

Reconsider When:

Phase 12's handoff requires the extracted content next to the tweet file, or a policy decision
changes how often the pipeline should re-fetch refreshed pages.


### ADR-XXX — Title

Date: YYYY-MM-DD

Decision:

What was chosen.

Reason:

Why it was chosen.

Alternatives:

What alternatives were considered.

Rejected Because:

Why they were rejected.

Reconsider When:

Conditions that would justify revisiting the decision.
