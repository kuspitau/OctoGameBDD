# Current State

## Repository state

GitHub `main` is the source-of-truth base for this delta:

- branch: `main`
- base commit: `fc0dbe0fc22610113bfc8bd9c1e07cb41d400a39`

That commit contains the P0-T03 audit/golden-case foundation plus the local source-path and in-ZIP handoff-helper workflow amendment.

Because those changes are now present on the project's validated source-of-truth branch, the stale `IMPLEMENTED_AWAITING_LOCAL_VALIDATION` wording carried by the previous router is closed for routing purposes and normal development advances into P1.

**Status:** `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`

## Current milestone

**P1 — World foundation**

## Current task

**P1-T01 — World schema and pfQuest fixture vertical slice**

Detailed task specification:

- `docs/project/tasks/P1-T01.md`

Implementation in this delta includes:

- schema migration 3 with canonical `maps`, `zones`, `creatures`, `creature_spawns`, `gameobjects`, and `gameobject_spawns`;
- explicit spawn coordinate spaces so pfQuest zone-percentage coordinates are not mislabeled as world XYZ;
- a dependency-free parser/importer for a deliberately small pfQuest-shaped six-file fixture slice;
- source registration/import-batch accounting and provenance observations using the P0 primitives;
- conservative canonical selection: first source evidence is selected only when the fact group has no existing selection;
- idempotent template/spawn materialization with deterministic spawn keys;
- a programmatic cross-entity location search that returns selected position-source attribution;
- tests for parsing, schema constraints, migration upgrade, idempotency, provenance trace links, and location queries.

## Source verification for P1-T01

The public pfQuest format was inspected rather than inferred.

Pinned upstream evidence for the fixture/parser contract:

- repository: `shagu/pfQuest`
- revision: `104f35678ca39ab1fb78b655f815cc7016f5e0c8`
- license: MIT
- relevant files: `db/zones.lua`, `db/enUS/zones.lua`, `db/units.lua`, `db/enUS/units.lua`, `db/objects.lua`, `db/enUS/objects.lua`, plus pfQuest database lookup code for coordinate semantics.

The first value in pfQuest zone geometry is retained only as source evidence (`pfquest.coordinate_frame`) in this task. It is not silently promoted to canonical map or zone-parent identity.

## Agent/sample validation for this delta

Performed in an agent workspace assembled from GitHub `main` plus this delta:

```bash
PYTHONPATH=src python -m pytest -q
```

Expected/current agent result:

```text
34 passed
```

Also performed:

```bash
PYTHONPATH=src python -m compileall -q src tests
```

Python compilation succeeds.

Editable packaging was also validated without network build isolation:

```bash
python -m pip install -e . --no-deps --no-build-isolation
python -m octogamedb status --db /tmp/p1_t01_status.sqlite3
```

The packaged migration is discovered and status reports schema version `3` / three applied migrations.

The agent environment did not contain the `ruff` module, so Ruff could not be executed there. The project dev dependency still includes Ruff and it remains part of required human validation.

## Required human validation after applying this delta

No full Octo/pfQuest local data or machine-specific source path is required for P1-T01. No `get_path.bat` is included.

From the project root, run:

```bash
git diff
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests
python -m compileall -q src tests
python -m octogamedb status --db data/generated/p1_t01_validation.sqlite3
```

Expected invariants:

- the complete repository test suite passes;
- Ruff reports no errors;
- Python compilation succeeds;
- status reports schema version `3` and three applied migrations;
- no tracked file contains a user-specific absolute source path;
- repeated fixture import tests prove no duplicate canonical rows/observations for the same revision;
- pfQuest percentage coordinates remain `coordinate_space = 'zone_percent'`.

The disposable validation database may be removed afterward from the ignored generated-data area.

## Next handoff rule

After the human validates, commits, and pushes P1-T01 to GitHub `main`, the next conversation must confirm that commit from `CURRENT_STATE.md`/`main` before advancing.

The next bounded P1 task should expand the world foundation from this fixture slice without jumping directly to full-world ingestion. In particular, authoritative map/area hierarchy and broader source coverage still need to be resolved before treating pfQuest's source-specific coordinate context as canonical geography.
