# Current State

## Repository state

GitHub `main` is the source-of-truth base for this delta:

- branch: `main`
- base commit: `d4310762f1e00b2664cb6d39eadf3e9abd407c46`

That commit is `Implement P1-T01 world schema and pfQuest vertical slice`. P1-T01 is therefore confirmed on the project's validated source-of-truth branch and is closed for routing purposes.

**Status:** `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`

## Current milestone

**P1 — World foundation**

## Current task

**P1-T02 — Octo DBC map/area hierarchy vertical slice**

Detailed task specification:

- `docs/project/tasks/P1-T02.md`

Implementation in this delta includes:

- dependency-free classic WDBC parsing for `Map.dbc` and `AreaTable.dbc`;
- deterministic content-derived revision identity for the exact two-file DBC input;
- canonical `maps` and `zones` materialization using the existing migration-3 schema;
- authoritative zone -> map and subzone -> parent-zone hierarchy from direct Octo client DBC evidence;
- an explicit field-specific canonical-selection policy for map/area identity and hierarchy, while retaining competing source observations;
- source-only retention of selected AreaTable/Map metadata that is not yet promoted into canonical columns;
- derived map context in world-location queries through `spawn.zone_id -> zones.map_id` when the spawn has no direct `map_id`;
- preservation of `zone_percent` coordinate semantics with no coordinate conversion;
- synthetic source-shaped WDBC fixtures and focused parser/import/provenance/query tests;
- a task-specific `get_path.bat` handoff helper for `[source_paths].octo_dbc`.

No schema migration is required for P1-T02; migration 3 already provides the necessary map/zone hierarchy columns.

## Source verification for P1-T02

The DBC format was inspected rather than inferred.

Pinned public format evidence:

- repository: `cmangos/mangos-classic`
- revision: `9b682be617ac61c127c23aa60d7b4ffbc0ce37e6`
- relevant files:
  - `src/shared/Database/DBCFileLoader.cpp`;
  - `src/game/Server/DBCStructure.h`;
  - `src/game/Server/DBCEnums.h`;
  - `src/game/Server/DBCStores.cpp`.

The public source is used only to establish the classic WDBC layout and field semantics. The actual canonical source for this task is the user's local Octo client `Map.dbc` / `AreaTable.dbc` pair, whose exact bytes are represented by a deterministic SHA-256 composite revision at import time.

The tracked WDBC fixture is synthetic/test-owned and does not redistribute Octo client data.

## Agent/sample validation for this delta

The GitHub connector exposes repository contents but does not mount a checkout into the execution container. A focused agent workspace was therefore assembled from the GitHub `main` dependencies needed by P1-T02 plus this delta.

Performed:

```bash
PYTHONPATH=src python -m pytest -q
```

Focused P1-T02 result:

```text
6 passed
```

Also performed:

```bash
python -m compileall -q src tests
```

Python compilation succeeds.

Editable packaging was validated without network build isolation:

```bash
python -m pip install -e . --no-deps --no-build-isolation
```

A fixture import against a fresh database also succeeded with:

- schema version: `3`;
- maps: `2`;
- zones: `3`;
- hierarchy links: `1`;
- second unchanged import: `rows_inserted = 0`, `rows_updated = 0`.

The agent container did not contain the `ruff` module, so Ruff could not be executed there.

Because a complete Git checkout was not mountable in the execution environment, the pre-existing full repository suite was not re-executed by the agent. The focused tests exercise the new parser/importer, provenance-selection behavior, idempotency, and modified world-location query. The full repository suite remains required below.

## Required local path/config step

P1-T02 needs the user's extracted Octo client DBC directory.

After extracting `changes.zip` over the project root, run from the project root:

```bat
get_path.bat
```

Successful resolution must leave a valid ignored `config.local.toml` entry:

```toml
[source_paths]
octo_dbc = "<directory containing Map.dbc and AreaTable.dbc>"
```

The helper reuses a valid configured path, checks a small set of safe candidates, otherwise asks for the directory, validates both required files, and preserves unrelated configuration.

## Required human/full-data validation

From the project root, run:

```bash
git diff
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests
python -m compileall -q src tests
```

Then import the real local DBC pair twice into a disposable generated database. In PowerShell from the project root:

```powershell
@'
import tomllib
from pathlib import Path

from octogamedb.db import apply_migrations, connect_database
from octogamedb.importers.octo_dbc_world import import_octodbc_world

config = tomllib.loads(Path("config.local.toml").read_text(encoding="utf-8"))
source_root = config["source_paths"]["octo_dbc"]

with connect_database("data/generated/p1_t02_validation.sqlite3") as connection:
    apply_migrations(connection)
    first = import_octodbc_world(connection, source_root=source_root)
    second = import_octodbc_world(connection, source_root=source_root)
    print("FIRST")
    print(first.to_json())
    print("SECOND")
    print(second.to_json())
    print("schema_version", connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
    print("maps", connection.execute("SELECT COUNT(*) FROM maps").fetchone()[0])
    print("zones", connection.execute("SELECT COUNT(*) FROM zones").fetchone()[0])
    print("subzones", connection.execute("SELECT COUNT(*) FROM zones WHERE parent_zone_id IS NOT NULL").fetchone()[0])
'@ | python -
```

Expected invariants:

- the complete repository test suite passes;
- Ruff reports no errors;
- Python compilation succeeds;
- the real DBC import reports `status = "succeeded"` and `source_key = "octo-client-dbc"`;
- the automatically generated `source_revision` begins with `sha256:`;
- `maps > 0`, `zones > 0`, and normal client data should yield `subzones > 0`;
- schema version remains `3`;
- the second unchanged import reports `rows_inserted = 0` and `rows_updated = 0`;
- repeated import does not duplicate stable source observations for the same revision but does retain per-import-batch trace links;
- no tracked file contains a user-specific absolute source path;
- existing pfQuest spawn observations remain `coordinate_space = 'zone_percent'`;
- map context returned for a zone-only spawn is derived from the canonical zone map and does not rewrite the spawn coordinate space.

The disposable validation database may be removed afterward from the ignored generated-data area.

## Known limitation for local validation

P1-T02 reads already extracted `Map.dbc` and `AreaTable.dbc`. It does not add MPQ extraction. If the user's client does not currently expose an extracted DBC directory containing those two files, `get_path.bat` will fail validation rather than invent a path; extraction must be handled before this Level-2 import can be completed.

## Next handoff rule

After the human validates, commits, and pushes P1-T02 to GitHub `main`, the next conversation must confirm that new commit from `CURRENT_STATE.md` / `main` before advancing.

The next bounded P1 task should expand source coverage without jumping directly to full-world ingestion. The two most immediate remaining concerns are Octo-specific pfQuest-octo reconciliation/override semantics and adding a source with native world-coordinate spawn data; the next conversation should choose the smallest dependency-ordered slice from the updated source-of-truth state.

### Real Octo DBC compatibility note

Local Level-2 validation found one `AreaTable.dbc` row (area ID `3884`) whose localized-name fields 11-18 are all empty. It is unreferenced as a parent by every other area in the exported client DBC. P1-T02 therefore treats unnamed, unreferenced area rows as skipped source records: they are not given invented canonical names, are counted in `rows_skipped`/`warning_count`, and their IDs are reported in import details. A named area that references such a skipped parent still fails validation rather than silently breaking hierarchy.
