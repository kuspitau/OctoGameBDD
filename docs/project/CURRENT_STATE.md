# Current State

## Repository state

GitHub `main` used as the base for P0-T02:

- branch: `main`
- base commit: `43159c33e76777af101ae957c1c5a7078a57ed53`

That commit contains the P0-T01 SQLite foundation. Per the prior handoff contract, its presence on
validated `main` confirms P0-T01 as completed/validated and allows work to advance to P0-T02.

P0-T02 has been implemented in the current delta and passed agent/sample validation.

**Status:** `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`

The P0-T02 implementation is not part of validated GitHub `main` until the human applies this delta,
runs the required local validation, reviews the diff, commits, and pushes.

## Current milestone

**P0 — Repository and data foundation**

## Current task

**P0-T02 — Provenance and conflict primitives**

Detailed task specification:

- `docs/project/tasks/P0-T02.md`

Implementation now includes:

- schema migration `0002_provenance_primitives.sql`;
- `observation_groups` for stable scalar/relation evidence slots;
- relation `fact_instance_key` support so legitimate multi-valued relations remain distinct;
- stable `source_observations` keyed by source revision plus `observation_import_batches` links for
  every import run that observed them;
- deterministic canonical JSON payload serialization;
- idempotent scalar and relation observation helpers;
- explicit current canonical selection with policy/reason metadata;
- database enforcement that a canonical selection references an observation from the same group;
- tests covering conflicts, traceability, relation cardinality cases, constraints, and v1 -> v2 upgrade.

These generic tables are an evidence/provenance layer only. They do not replace the explicit
canonical domain relation tables required by the architecture.

`CURRENT_STATE.md` remains the permanent task router. Do not advance to P0-T03 until this P0-T02
delta has been locally validated and pushed to GitHub `main`.

## Completed / validated before P0-T02

- project scope and multi-entity architecture defined;
- source strategy defined;
- raw/staging/canonical/derived separation accepted;
- provenance/conflict requirements accepted;
- GitHub read-only -> human-applied delta workflow defined;
- initial Python package/test skeleton created;
- large-data exclusion policy created;
- roadmap and decision log created;
- **P0-T01 — SQLite foundation and import metadata: VALIDATED on GitHub `main`**.

## P0-T02 validation status

Agent/sample validation completed:

```bash
PYTHONPATH=src pytest -q
python -m compileall -q src tests
python -m pip install -e . --no-build-isolation --no-deps
pytest -q
python -m octogamedb status --db <temporary-test-path>
python -m octogamedb status --db <same-temporary-test-path>
```

Results:

- 19 tests passed both via `PYTHONPATH=src` and after editable package installation;
- Python compilation passed;
- SQLite integrity smoke check returned `ok` and `PRAGMA foreign_key_check` returned zero rows;
- fresh status reported schema version `2` and two applied migrations;
- repeated status remained at exactly two applied migrations;
- Ruff could not be executed in the agent environment because the executable is not installed.

No full Octo data is required for P0-T02 validation.

Required human validation after applying the delta:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check src tests
python -m octogamedb status --db data/generated/p0_t02_validation.sqlite3
python -m octogamedb status --db data/generated/p0_t02_validation.sqlite3
```

Expected invariants:

- all tests pass;
- Ruff reports no errors;
- the validation DB reports schema version `2`;
- it reports exactly two applied migrations;
- a fresh validation DB reports zero sources and zero import batches;
- repeating `status` does not create a third migration record;
- the test suite verifies upgrade from a schema-v1 database to schema v2 without recreating the DB;
- repeating the same source revision in a new import batch reuses stable observations while recording
  the additional batch link.

## Next handoff rule

After the human validates, commits, and pushes this delta to GitHub `main`, the next conversation
should confirm P0-T02 as `VALIDATED` and advance `CURRENT_STATE.md` to **P0-T03 — Fixture/golden-case
and audit skeleton**.
