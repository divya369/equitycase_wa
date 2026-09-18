# CLAUDE.md

All project rules and the standard structure live in AGENTS.md (shared with
other coding agents). Read and follow it:

@AGENTS.md

## Working with Claude

- Build phases one at a time (plan: P0–P11) and wait for the user's "go" on
  the next phase.
- After a change: `make check`; for DB changes also verify the migration
  round-trip (`make downgrade` + `make migrate`, `uv run alembic check`).
- Never print `.env` values — check keys by name/length only.
