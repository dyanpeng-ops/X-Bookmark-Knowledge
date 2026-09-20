# Execution

Cline is primarily an execution agent.

- Follow `tasks/CURRENT.md`.
- Do not expand scope without justification.
- Prefer existing patterns.
- Avoid unnecessary dependencies.
- Do not make major architectural changes without explicit authorization.
- **Never start verification on your own (user rule, 2026-09-20).** Read-only inspection (reading files,
  searching, `git status` / `git log` / `--help`) is allowed. Running tests, any network access
  (`ls-remote` / `clone` / `fetch` / `push` / link fetching) and any write (files, database, knowledge
  base) require explicit approval first.
- When asking for approval, give the exact commands, the purpose and the impact (network? disk? duration?).
  Then wait — do not "helpfully" verify beforehand.
