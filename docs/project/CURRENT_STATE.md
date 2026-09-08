# Current project state

Updated for P7-T07 validated closure and P8-T01 routing on 2026-09-03.

## Source-of-truth

Fresh GitHub `main` resolved at task start to:

```text
50411e9b3abc0d3dd30b60b71208edbd7588ee4b
Validate P7-T06 zone exploration and route P7-T07
```

This satisfies the P7-T07 base guard: P7-T06, `zone_recipe_projection.py`, its validated closeout and
`docs/project/tasks/P7-T07.md` are integrated on `main`.

## Accepted canonical local database

The accepted cumulative local database remains:

```text
data/generated/octogamedb.sqlite3
schema_version = 14
latest migration = 0014_item_template_facts.sql
SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Immediate D-029 rollback snapshot remains:

```text
data/generated/octogamedb_bak.sqlite3
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

P7-T07 remains read-only. No canonical mutation or schema change is authorized by this handoff.

## Phase status

```text
P0: VALIDATED
P1: VALIDATED through P1-T04
P2: VALIDATED through P2-T04
P3: VALIDATED through P3-T05
P4: VALIDATED through P4-T04
P5: VALIDATED through P5-T08
P6: VALIDATED through P6-T05
P7-T01: VALIDATED
P7-T02: VALIDATED
P7-T03: VALIDATED
P7-T04: VALIDATED
P7-T05: VALIDATED
P7-T06: VALIDATED
P7-T07: VALIDATED
P8-T01: READY_FOR_IMPLEMENTATION
```

## P7-T06 accepted baseline

P7-T06 is the validated derived/read-only zone-composition layer over canonical zones/maps, P7-T05
world entities/spawns/roles, P7-T02 item acquisition, P7-T03 quest roles and the compact positive
recipe-learning projection introduced by `zone_recipe_projection.py`.

Accepted full-data timings that motivated P7-T07 remain the pre-optimization baseline:

```text
inspect_zone(12, include_recipes=False) = 27.60 s
inspect_zone(1,  include_recipes=False) = 31.44 s
inspect_zone(14, include_recipes=False) = 41.25 s
inspect_zone(1,  include_recipes=True)  = 32.31 s
inspect_zone(3,  include_recipes=True)  = 20.85 s
```

The small recipe/no-recipe delta indicates the residual hot path is primarily below the compact recipe
projection, in the P7-T05 world-entity/geography/role/provenance composition.

## P7-T07 validated optimization

Task router:

```text
docs/project/tasks/P7-T07.md
```

The human completed both accepted-canonical profiling runs. The database remained byte-identical and
all profiling invariants passed. Cold timings were:

```text
no recipes: zone 1  = 29.056 s (692 entities)
no recipes: zone 12 = 25.231 s (614 entities)
no recipes: zone 14 = 38.401 s (928 entities)
with recipes: zone 1 = 32.664 s (692 entities)
with recipes: zone 3 = 19.344 s (305 entities)
```

Repeated calls were not materially faster than cold calls, so the debt is query-shape/Python
hydration overhead rather than primarily first-read database I/O.

The measured dominant cost is the P7-T05 quest selected-relation fallback used during retained entity
hydration. For the no-recipe samples:

```text
zone 1:  1,384 _selected_relation_rows calls = 21.835 s = 75.1% of total
zone 12: 1,228 _selected_relation_rows calls = 19.241 s = 76.3% of total
zone 14: 1,856 _selected_relation_rows calls = 30.102 s = 78.4% of total
```

The call count is exactly two global selected-relation lookups per returned entity: one endpoint
lookup and one objective lookup. Each lookup omits `subject_key`, so the accepted composite unique
index on `observation_groups(subject_kind, subject_key, fact_key, fact_instance_key)` cannot narrow
through the skipped column. Repeating that scan for every retained entity is the measured N+1.

The implemented optimization in `src/octogamedb/world_entity_search.py` is deliberately request-local
and read-only:

- load selected quest `endpoint`, `objective_creature`, and `objective_gameobject` relations once per
  `query_world_entities()` call;
- index those selected rows in memory by `(fact_key, fact_instance_key)`;
- preserve the existing `_selected_relation_rows()` path as the fallback when no batch index is
  supplied;
- feed the batch through `_entity_detail()` -> `_quest_roles()` -> `_selected_quest_role_rows()`;
- preserve the same selected value/provenance payload and the same validation of target/role
  semantics;
- introduce no migration, persistent cache, canonical write, or architecture decision. D-008 remains
  unchanged.

`tests/test_p7_t07_relation_batch.py` compares batched results directly to the legacy lookup and
asserts that cached per-entity role reads issue no relation SQL. `scripts/profile_p7_t07.py` now also
times the batch loader and records plans for both the legacy relation shape and the batched shape.

## Post-optimization full-data result

The human reran the P7-T06 semantic validator and both P7-T07 profiles on the accepted canonical DB.
All read-only database invariants passed and the canonical SHA remained byte-identical.

Observed cold timings:

```text
no recipes: zone 1  29.056 s -> 6.650 s  = 4.37x faster (-77.1%)
no recipes: zone 12 25.231 s -> 5.451 s  = 4.63x faster (-78.4%)
no recipes: zone 14 38.401 s -> 7.484 s  = 5.13x faster (-80.5%)
with recipes: zone 1 32.664 s -> 6.733 s  = 4.85x faster (-79.4%)
with recipes: zone 3 19.344 s -> 7.845 s  = 2.47x faster (-59.4%)
```

Representative cold median improved from `29.056 s` to `6.650 s` without recipes (`4.37x`) and from
`26.004 s` to `7.289 s` for the recipe sample (`3.57x`). Every representative optimized cold call is
below 10 seconds, so the task performance objective is met.

Every cold and repeated optimized run records exactly one
`detail.selected_quest_relation_index` load and zero `detail.selected_relation_rows` calls. The batch
load itself costs roughly `0.15-0.21 s`; the measured N+1 is removed rather than hidden by warm-cache
behavior.

P7-T06 semantic validation also passed after the optimization:

```text
P7_T06_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
zone_identities=1480
validated_zone_detail_count=5
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=True
```

## Repository-gate status

After stacking the Ruff hotfix over the optimization, the complete available project snapshot and the
human local tree satisfy the final gates:

```text
complete snapshot pytest gate: 357 passed
python -m compileall -q src tests scripts: PASS
pyproject.toml parse: PASS
python -m ruff check src tests scripts: All checks passed!
```

Together with the accepted-canonical P7-T06 semantic rerun and both optimized profiling reports, this
closes P7-T07 as `VALIDATED`. No additional profiling, migration, persistent cache, or canonical DB
mutation is required.

## Current task — P8-T01 local/browser UI foundation

Task router:

```text
docs/project/tasks/P8-T01.md
```

P8-T01 is `READY_FOR_IMPLEMENTATION`. It should establish the first user-facing local/browser UI as a
read-only consumer of the validated P7 query contracts, using a bounded zone-centric vertical slice.
The framework choice must be justified from current primary documentation before implementation;
NiceGUI remains only a previously identified candidate, not a preselected architecture decision.

The first UI slice must reuse P7 query functions rather than duplicate canonical SQL or invent new
semantic projections. Generalized dungeon/instance UX, persistent saved-query state, maps, ownership,
craft economics and other richer UI features remain deferred until the shell/zone slice is validated.

## Next-conversation guard

Do not re-open P7-T07 unless a regression or new performance measurement warrants it. Start from
`docs/project/tasks/P8-T01.md`, resolve GitHub `main` fresh, and preserve the stacked-local-state guard
until the human commits/pushes the complete P7-T07 closure.
