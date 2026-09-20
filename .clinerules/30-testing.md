# Testing

**Verification gate (user rule, 2026-09-20): never start verification on your own.**

- Read-only inspection (reading files, searching, `git status` / `git log`, `--help`) may be done directly.
- Running tests, any network access, and any write to disk / database / knowledge base need explicit
  approval first: present the exact commands, the purpose and the impact, then wait.
- After implementing, stop and report a "pending verification" list. Until it is approved and run, the
  task is **"implemented, not verified"** — never claim it is verified.

After approval:

1. Run the task acceptance tests.
2. Run relevant regression tests when practical.
3. Do not mark the task complete when required tests fail.
4. Report exact failures and commands used.
