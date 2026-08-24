# Current State

## Repository state

GitHub `main` is the source-of-truth base for this delta:

- branch: `main`
- base commit: `034c5914457d6ef29a20ec28e690d2fb753d1356`

That commit is `Implement P1-T03 pfQuest Turtle primary overlay and Octo comparison`.
P1-T03 is therefore present on the validated source-of-truth branch and closed for normal routing.

**Status:** `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`

## Current milestone

**P1 — World foundation**

## Current task

**P1-T04 — overlay provenance/canonical reconciliation**

Detailed task specification:

- `docs/project/tasks/P1-T04.md`

## Implementation in this delta

- adds `pfquest_overlay_reconcile.py`;
- records source-view membership as `world_presence = true/false` provenance rather than treating
  Turtle deletions as universal tombstones;
- records creature/game-object spawn membership as deterministic complete `spawn_set` facts;
- registers current Turtle and optional Octo overlays as distinct source identities/revisions;
- lets the installed Turtle effective view supersede only default/base pfQuest selections for this
  bounded P1 world fact family;
- preserves explicit/non-pfQuest selections, including the separate D-025 DBC geography policy;
- reconciles Turtle additions/changes into the existing migration-3 world tables;
- removes stale canonical spawns only when their selected position source belongs to the managed
  pfQuest family, while retaining historical source observations;
- retains an absent template/zone when selected non-pfQuest evidence or canonical dependencies
  still support it;
- records optional `pfQuest-octo` differences as comparison evidence only;
- adds deterministic content-derived revision helpers for the exact P1 pfQuest and overlay input
  file sets;
- introduces no schema migration.

The durable semantics are recorded in D-026 and `docs/project/tasks/P1-T04.md`.

## Local path/config state

P1-T04 introduces no new path key. It reuses the P1-T03 configuration:

```toml
[source_paths]
pfquest = "<installed pfQuest directory>"
pfquest_turtle = "<installed pfQuest-turtle directory>"
```

Optional:

```toml
pfquest_octo = "<installed pfQuest-octo directory>"
```

The previous task already established and validated these keys, so this delta does not include a
new `get_path.bat`.

## Agent/sample validation

Because the execution environment does not expose a complete mounted checkout, a focused
workspace was assembled with the existing SQLite/provenance/world-schema contracts plus the new
P1-T04 module/tests.

Performed:

```bash
PYTHONPATH=src python -m pytest -q tests/test_pfquest_overlay_reconcile.py
```

Result:

```text
4 passed
```

Coverage includes:

- Turtle complete-set reconciliation and stale spawn removal;
- preservation of historical pfQuest spawn evidence after canonical deletion;
- repeat-run idempotence;
- negative Turtle presence with an explicit non-pfQuest selection;
- optional Octo comparison evidence without canonical mutation.

Also performed:

```bash
python -m py_compile \
  src/octogamedb/importers/pfquest_overlay_reconcile.py \
  tests/test_pfquest_overlay_reconcile.py
```

Result: success.

Ruff was not available in the execution environment (`No module named ruff`). The full repository
suite and Ruff remain required locally.

## Required local validation

From the project root, first run the complete suite:

```bash
git diff
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests
python -m compileall -q src tests
```

Then run a fresh P1-T04 integration against the installed addons from PowerShell:

```powershell
@'
import tomllib
from pathlib import Path

from octogamedb.db import apply_migrations, connect_database
from octogamedb.importers.pfquest_overlay_reconcile import (
    compute_pfquest_overlay_revision,
    compute_pfquest_world_revision,
    import_pfquest_overlay_world,
)
from octogamedb.importers.pfquest_world import import_pfquest_world_slice

config = tomllib.loads(Path("config.local.toml").read_text(encoding="utf-8"))
paths = config["source_paths"]
pfquest = Path(paths["pfquest"])
turtle = Path(paths["pfquest_turtle"])
octo = Path(paths["pfquest_octo"]) if paths.get("pfquest_octo") else None

db_path = Path("data/generated/p1_t04_validation.sqlite3")
if db_path.exists():
    db_path.unlink()

base_revision = compute_pfquest_world_revision(pfquest)
turtle_revision = compute_pfquest_overlay_revision(turtle)
print("base_revision", base_revision)
print("turtle_revision", turtle_revision)

with connect_database(db_path) as connection:
    apply_migrations(connection)
    base = import_pfquest_world_slice(
        connection,
        source_root=pfquest,
        source_revision=base_revision,
    )
    first = import_pfquest_overlay_world(
        connection,
        pfquest_root=pfquest,
        overlay_root=turtle,
        pfquest_revision=base_revision,
        overlay_kind="turtle",
        overlay_revision=turtle_revision,
    )
    second = import_pfquest_overlay_world(
        connection,
        pfquest_root=pfquest,
        overlay_root=turtle,
        pfquest_revision=base_revision,
        overlay_kind="turtle",
        overlay_revision=turtle_revision,
    )

    print("BASE", base.to_dict())
    print("TURTLE_FIRST", first.to_dict())
    print("TURTLE_SECOND", second.to_dict())

    assert second.rows_inserted == 0
    assert second.rows_updated == 0
    assert second.details["stale_creature_spawns_deleted"] == 0
    assert second.details["stale_gameobject_spawns_deleted"] == 0
    assert second.details["canonical_templates_deleted"] == 0
    assert second.details["canonical_zones_deleted"] == 0

    stale_selected = connection.execute(
        """
        SELECT COUNT(*)
        FROM canonical_selections AS cs
        JOIN observation_groups AS og ON og.id = cs.observation_group_id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        LEFT JOIN creature_spawns AS csp
          ON og.subject_kind = 'creature_spawn' AND csp.spawn_key = og.subject_key
        LEFT JOIN gameobject_spawns AS gsp
          ON og.subject_kind = 'gameobject_spawn' AND gsp.spawn_key = og.subject_key
        WHERE og.fact_key = 'position'
          AND ds.source_key IN ('pfquest', 'pfquest-turtle')
          AND og.subject_kind IN ('creature_spawn', 'gameobject_spawn')
          AND csp.spawn_key IS NULL
          AND gsp.spawn_key IS NULL
        """
    ).fetchone()[0]
    print("historical selected spawn observations without canonical row", stale_selected)

    turtle_negative = connection.execute(
        """
        SELECT COUNT(*)
        FROM observation_groups AS og
        JOIN source_observations AS so ON so.observation_group_id = og.id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.fact_key = 'world_presence'
          AND ds.source_key = 'pfquest-turtle'
          AND so.source_revision = ?
          AND so.value_json = 'false'
        """,
        (turtle_revision,),
    ).fetchone()[0]
    print("turtle negative presence observations", turtle_negative)

    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    if octo is not None and octo.is_dir():
        octo_revision = compute_pfquest_overlay_revision(octo)
        before = {
            "zones": connection.execute("SELECT COUNT(*) FROM zones").fetchone()[0],
            "creatures": connection.execute("SELECT COUNT(*) FROM creatures").fetchone()[0],
            "creature_spawns": connection.execute(
                "SELECT COUNT(*) FROM creature_spawns"
            ).fetchone()[0],
            "gameobjects": connection.execute("SELECT COUNT(*) FROM gameobjects").fetchone()[0],
            "gameobject_spawns": connection.execute(
                "SELECT COUNT(*) FROM gameobject_spawns"
            ).fetchone()[0],
        }
        comparison = import_pfquest_overlay_world(
            connection,
            pfquest_root=pfquest,
            overlay_root=octo,
            pfquest_revision=base_revision,
            overlay_kind="octo",
            overlay_revision=octo_revision,
        )
        after = {
            "zones": connection.execute("SELECT COUNT(*) FROM zones").fetchone()[0],
            "creatures": connection.execute("SELECT COUNT(*) FROM creatures").fetchone()[0],
            "creature_spawns": connection.execute(
                "SELECT COUNT(*) FROM creature_spawns"
            ).fetchone()[0],
            "gameobjects": connection.execute("SELECT COUNT(*) FROM gameobjects").fetchone()[0],
            "gameobject_spawns": connection.execute(
                "SELECT COUNT(*) FROM gameobject_spawns"
            ).fetchone()[0],
        }
        print("OCTO_COMPARISON", comparison.to_dict())
        assert comparison.details["comparison_only"] is True
        assert before == after
'@ | python -
```

Expected invariants:

- the complete repository test suite passes;
- Ruff reports no errors;
- Python compilation succeeds;
- the fresh base pfQuest import succeeds;
- the first Turtle reconciliation records source-view evidence and may insert/update/delete
  canonical P1 rows according to the installed data;
- the second reconciliation of the same exact revisions reports zero canonical changes/deletions;
- removed/replaced pfQuest spawn observations remain in provenance even when their canonical spawn
  rows are gone;
- `world_presence = false` observations are retained for Turtle removals;
- SQLite `PRAGMA foreign_key_check` is empty;
- optional Octo comparison records evidence with `comparison_only=true` and leaves canonical P1 row
  counts unchanged;
- the validation database is local/generated only and must not be committed.

## Known limitations

- P1-T04 reconciles only the static enUS P1 world subset already supported by P1-T03.
- `world_presence` and `spawn_set` are bounded provenance facts for effective world views, not a
  generic deletion framework for all future domains.
- `pfQuest-octo` remains comparison evidence until a later explicit field/relation policy chooses it.
- full installed-source behavior remains Level-2 validation because local addon data is not in Git.

## Next handoff rule

After local validation, commit and push P1-T04 to `main`. The next conversation must confirm the
resulting main commit before advancing.

Next bounded work: define **P2-T01 — first item/acquisition vertical slice** from the validated
P0/P1 foundation; do not jump directly to full-world/P6 ingestion.
