# Architecture

## Overview

X Bookmark Knowledge Pipeline turns X.com bookmarks into per-tweet Markdown inside a personal knowledge base. It is deliberately split into a **collector** (reused from upstream) and a **processor** (owned by this project):

```text
X.com
  ↓   fieldtheory CLI                     (upstream; read-only input)
~/.fieldtheory/bookmarks/{bookmarks.jsonl, media-manifest.json, media/**}
  ↓   src/collector/                      (adapter — Phase 5, NOT implemented)
data/raw/<tweet_id>.json                  (raw snapshot, never deleted — Phase 5/6)
  ↓   src/ingest/                         (Phase 6, NOT implemented)
data/state/*.db                            (SQLite = single source of truth)  ← IMPLEMENTED (Phase 4)
  ↓   src/processor/ · src/media/ · src/external/ · src/markdown/
knowledge/X-Bookmarks/YYYY/MM/YYYYMMDD-<tweet_id>.md + assets/<tweet_id>/**
  ↓   handoff                             (Phase 12)
01_Knowledge-Agent/inbox/X-Bookmarks/
  ↓   parent Knowledge-Agent
personal knowledge base
```

Current status: Phases 0–9 are implemented — state store (`src/database/`), collector adapter
(`src/collector/`), ingest (`src/ingest/`), Markdown renderer (`src/markdown/`), media localisation
(`src/media/`), external link extraction (`src/external/`) and the CLI (`src/cli/`). Phases 10–13
are unimplemented by design — see `PLAN.md` §2.

## Components

Verified directory list (2026-09-15):

| Path | Role | Status |
| --- | --- | --- |
| `src/database/` | schema, migrations, state machine, repositories, FTS5 | ✅ Phase 4 |
| `src/collector/` | adapter over the upstream CLI (read-only) | ✅ Phase 5 |
| `src/ingest/` | JSONL → normalized rows, dedup, incremental cursor, raw archives | ✅ Phase 6 |
| `src/processor/` | per-tweet assembly (thread / quote / article / links) | Phase 7, 11 (部分在 `src/markdown/`) |
| `src/media/` | media localization, stable naming, hash dedup, skip rules | ✅ Phase 8 |
| `src/external/` (+ `handlers/`) | URL resolution and content extraction | ✅ Phase 9 |
| `src/markdown/` | Markdown rendering, frontmatter, idempotent writes | ✅ Phase 7 |
| `src/scheduler/` | Windows Task Scheduler wrapper | Phase 13 |
| `src/cli/` | argument parsing, orchestration, reports (`sync`/`media`/`process`/`status`/`doctor`) | ✅ Phase 6+ |
| `data/{raw,state,logs}/` | program data (gitignored, never the knowledge base) | ✅ Phase 4+ |
| `knowledge/X-Bookmarks/` | user knowledge output: Markdown + `assets/{tweet_id}/` | ✅ Phase 7–8 |
| `config/` | `config.example.yaml` committed; `config.yaml` local only | ✅ Phase 3+ |
| `tests/` | `unittest` suite (272 cases) | ✅ Phase 8 |
| `docs/`, `research/` | environment report, open-source comparison, architecture decision | ✅ Phase 0–2 |
| `memory/`, `plans/`, `tasks/`, `.clinerules/` | agent governance layer | ✅ |

There is no `context/` or `skills/` directory in this project.

## Dependency Direction

Allowed:

```text
cli        → ingest, processor, media, external, markdown, collector, database, scheduler
ingest     → collector, database
processor  → database, markdown
media      → database
external   → database
markdown   → database
scheduler  → cli
database   → standard library only
```

Forbidden:

- any module → `cli` (no back-references into the entry layer)
- `database` → anything beyond the standard library (it must stay pure storage)
- any module → writes to upstream `~/.fieldtheory/**` (read-only input, ADR-003)
- any module → writes to the parent `01_Knowledge-Agent/knowledge/**` (handoff goes through `inbox/`, ADR-006)

## Important Interfaces

Implemented and frozen by tests (Phase 4):

- `src.database.connect(db_path, *, ensure_schema=True)` → `sqlite3.Connection`; creates the parent directory, sets `foreign_keys=ON` and `busy_timeout`, enables WAL for file databases, and applies migrations
- `src.database.apply_migrations(conn)` → resulting schema version; atomic and idempotent
- `src.database.BookmarkRepository` — `upsert_bookmark` / `upsert_media` / `upsert_external_link` (idempotent), `set_status`, `record_error`, `count_by_status`, `list_by_status`, `search` (FTS5/BM25), `delete_bookmark`
- State machine: `NEW → COLLECTED → PROCESSED → ENRICHED → COMPLETED`; any non-terminal state may enter `FAILED`; `FAILED` may re-enter the pipeline; `COMPLETED` is terminal; an invalid transition raises `InvalidStateTransition` and writes nothing
- Timestamps: `YYYY-MM-DDTHH:MM:SSZ` (UTC) via `utc_now_iso()`
- Partial-update rule: `None` in an upsert input means "not provided" and never overwrites stored data (ADR-004)

Schema v2: `schema_version`, `bookmarks` (`tweet_id` UNIQUE, CHECK on `status`), `media` (UNIQUE `tweet_id` + `media_key`), `external_links` (UNIQUE `tweet_id` + `url`), `bookmarks_fts` (FTS5 external-content table with three synchronisation triggers).

Planned and deliberately not yet defined: the collector adapter interface (`BookmarkCollector`) and the upstream field contract — `research/architecture-decision.md` §4.3 remains marked 待确认 until a real sample exists.

## Constraints

1. Read-only with respect to X: the pipeline never creates, edits or deletes bookmarks on X.
2. `data/` (program data) and `knowledge/` (user knowledge) never mix.
3. Upstream data is read-only; this project's SQLite is the only authority.
4. `tweet_id` is a tweet's unique identity; a repeated sync must add no duplicate rows or files.
5. One failing tweet, media asset or link must never fail the whole run.
6. Every network call needs timeout, retry and error recording; a failed external fetch still keeps the original URL.
7. No secrets in Git, logs or Markdown (`auth_token`, `ct0`, `client_secret`, …).
8. AI analysis is optional post-processing that may only append — never modify — `tweet_id`, `tweet_text`, `author`, `created_at`, `tweet_url`, `source`.
9. No RAG, vector database, knowledge graph or multi-agent framework in this phase (parent `AGENT.md` §13).
10. This phase targets Markdown + file system + agent only; new infrastructure requires a demonstrated limitation.
11. The project never writes outside its own root. See `AGENTS.md` §3.
