# Current State

## Repository state

GitHub `main` used as the base for P0-T03:

- branch: `main`
- base commit: `587146435e44960aaebf7105979a79516102f26e`

That commit contains the P0-T02 provenance/conflict implementation. Its presence on validated `main` confirms P0-T02 as completed/validated and allows work to advance to P0-T03.

P0-T03 has been implemented in the current delta and passed agent/sample validation.

**Status:** `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`

The P0-T03 implementation is not part of validated GitHub `main` until the human applies this delta, runs the required local validation, reviews the diff, commits, and pushes.

## Current milestone

**P0 — Repository and data foundation**

## Current task

**P0-T03 — Fixture/golden-case and audit skeleton**

Detailed task specification:

- `docs/project/tasks/P0-T03.md`

Implementation now includes:

- explicit conventions separating source-shaped fixtures from synthetic project golden cases;
- initial provenance/audit golden case with resolved and unresolved conflicts plus legitimate multi-valued relations;
- generic audit report functions for source, trace, conflict, and coverage inspection;
- CLI commands `source`, `trace`, `conflict`, and `coverage`;
- human-readable output plus deterministic `--json` output for every new audit command;
- reusable machine-readable `ImportSummary` payloads derived from persisted import batches;
- deterministic JSON/file serialization for import summaries;
- tests covering golden coverage invariants, conflict classification/resolution state, traceability, source summaries, CLI text/JSON modes, and import-summary serialization.

No schema migration or gameplay-domain canonical tables were added. Generic coverage remains explicitly scoped to provenance/evidence until P1+ domain schemas exist.

`CURRENT_STATE.md` remains the permanent task router. Do not advance into P1 until this P0-T03 delta has been locally validated and pushed to GitHub `main`.

## Completed / validated before P0-T03

- project scope and multi-entity architecture defined;
- source strategy defined;
- raw/staging/canonical/derived separation accepted;
- provenance/conflict requirements accepted;
- GitHub read-only -> human-applied delta workflow defined;
- initial Python package/test skeleton created;
- large-data exclusion policy created;
- roadmap and decision log created;
- **P0-T01 — SQLite foundation and import metadata: VALIDATED on GitHub `main`;**
- **P0-T02 — Provenance and conflict primitives: VALIDATED on GitHub `main` at commit `587146435e44960aaebf7105979a79516102f26e`.**

## P0-T03 validation status

Agent/sample validation completed:

```bash
PYTHONPATH=src pytest -q
python -m compileall -q src tests
python -m pip install -e . --no-build-isolation --no-deps
pytest -q
```

Results:

- 27 tests passed both before and after editable package installation;
- Python compilation passed;
- the original 19 P0-T01/P0-T02 tests remain green;
- 8 new P0-T03 tests cover audit/golden/summary/CLI behavior;
- Ruff could not be executed in the agent environment because the executable is not installed.

No full Octo data is required for P0-T03 validation.

Required human validation after applying the delta:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check src tests
python -m compileall -q src tests
python -m octogamedb status --db data/generated/p0_t03_validation.sqlite3
python -m octogamedb coverage --db data/generated/p0_t03_validation.sqlite3 --json
python -m octogamedb conflict --db data/generated/p0_t03_validation.sqlite3 --json
```

Expected invariants:

- all 27 tests pass;
- Ruff reports no errors;
- Python compilation succeeds;
- the validation DB reports schema version `2` and exactly two applied migrations;
- a fresh validation DB reports zero registered sources/import batches;
- fresh `coverage --json` reports scope `generic-provenance` and zero sources, subjects, observations, canonical selections, and conflicts;
- fresh `conflict --json` reports zero conflicts and zero unresolved conflicts;
- no third schema migration is created by any P0-T03 command.

## Next handoff rule

After the human validates, commits, and pushes this delta to GitHub `main`, the next conversation should confirm P0-T03 as `VALIDATED`, close P0, and define/take the first bounded P1 world-foundation vertical-slice task before adding broad full-world ingestion.
