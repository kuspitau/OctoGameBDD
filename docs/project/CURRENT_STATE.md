# Current State

## Repository state

GitHub `main` at the start of P0-T01 was:

- branch: `main`
- base commit: `bd60bffbf29fa0f808355f7838c9ca6bb48fe08c`

P0-T01 has been implemented in the current delta and passed agent/sample validation.

**Status:** `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`

The implementation is not yet part of validated GitHub `main` until the human applies this delta,
runs the required local validation, reviews the diff, commits, and pushes.

## Current milestone

**P0 — Repository and data foundation**

## Current task

**P0-T01 — SQLite foundation and import metadata**

Detailed task specification:

- `docs/project/tasks/P0-T01.md`

Implementation now includes:

- project-owned SQLite connection handling with foreign-key enforcement;
- packaged, deterministic versioned SQL migrations;
- `schema_migrations`, `data_sources`, and `import_batches`;
- `python -m octogamedb status --db <path>`;
- tests for initialization, idempotency, constraints, foreign keys, rollback, migration recording,
  and CLI status behavior.

`CURRENT_STATE.md` is the permanent task router. Do not advance to P0-T02 until this P0-T01 delta
has been locally validated and pushed to GitHub `main`.

## Completed before P0-T01

- project scope and multi-entity architecture defined;
- source strategy defined;
- raw/staging/canonical/derived separation accepted;
- provenance/conflict requirements accepted;
- GitHub read-only -> human-applied delta workflow defined;
- initial Python package/test skeleton created;
- large-data exclusion policy created;
- roadmap and decision log created.

## P0-T01 validation status

Agent/sample validation completed:

```bash
python -m pytest -q
python -m octogamedb status --db <temporary-test-path>
```

Ruff could not be executed in the agent environment because the executable is not installed; it remains part of required human validation.

Required human validation after applying the delta:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check src tests
python -m octogamedb status
python -m octogamedb status --db data/generated/p0_t01_validation.sqlite3
```

Expected invariants:

- all tests pass;
- Ruff reports no errors;
- default status creates/opens `data/generated/octogamedb.sqlite3`;
- custom status creates/opens the requested path;
- both report schema version `1`, one applied migration, and zero sources/import batches on a fresh DB;
- repeating either status command does not add another migration record.

## Next handoff rule

After the human validates, commits, and pushes this delta to GitHub `main`, the next conversation
should confirm P0-T01 as `VALIDATED` and advance `CURRENT_STATE.md` to **P0-T02 — Provenance/conflict
primitives**.
