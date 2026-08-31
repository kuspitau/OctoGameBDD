# Current Project State

This file is the permanent task router. Read `AGENTS.md` first, then this file, then only the
additional task-specific context it points to.

## Source of truth and integration state

The tracked GitHub `main` visible to this closeout is still:

```text
GitHub repository: kuspitau/OctoGameBDD
branch: main
tracked head: e7a25cc84df122bf2f3675a0acba262c99c8e43f
commit: Validate P7-T04 recipe exploration and route P7-T05
```

The human working tree contains the complete P7-T05 implementation handoff, its duplicate-`spawn_key`
correction and the successful Level-2 validation recorded below. This closeout is intentionally
**stacked on that validated local P7-T05 tree**; it is not a standalone patch against bare
`e7a25cc84...`.

Commit and push the complete validated P7-T05 working tree plus this closeout before starting P7-T06.
The next coding conversation must freshly resolve GitHub `main` and must not implement P7-T06 if the
new main does not contain this P7-T05 validated closure.

## Accepted cumulative canonical database

The accepted local canonical baseline remains unchanged:

```text
data/generated/octogamedb.sqlite3
schema_version = 14
latest migration = 0014_item_template_facts.sql
SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Immediate D-029 rollback remains:

```text
data/generated/octogamedb_bak.sqlite3
schema_version = 14
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

P7-T05 was read-only. Its validated closure did not mutate either SQLite file, replace the rollback,
alter source priority or authorize another P6 acquisition tranche.

## Phase state

```text
P0  foundation/provenance                         VALIDATED
P1  world foundation                              VALIDATED through P1-T04
P2  items/acquisition                             VALIDATED through P2-T04
P3  quests                                        VALIDATED through P3-T05
P4  spells/recipes/reagents/acquisition           VALIDATED through P4-T04
P5  provenance/coverage/conflict audit            VALIDATED through P5-T08
P6  broader item-template acquisition/promotion   VALIDATED through P6-T05
P7  query/exploration                             LOCAL VALIDATED through P7-T05;
                                                    P7-T06 ROUTED, WAITING FOR PUSH/MAIN REFRESH
P8  UI/application workflow                       PLANNED
```

P7-T01 owns item identity/template/stat predicates. P7-T02 owns item acquisition/source geography.
P7-T03 owns bounded quest exploration and role-specific quest geography. P7-T04 owns
recipe/reagent/learning-source exploration. P7-T05 now owns the first-class creature/gameobject
template/spawn/role query surface.

Missing materialization or derived geography remains unknown/not-proven unless an underlying
validated complete-set/source contract explicitly proves a bounded negative.

## P7-T05 validated closure — 2026-08-31

Task/contract:

```text
docs/project/tasks/P7-T05.md
docs/project/P7_WORLD_ENTITY_QUERY_CONTRACT.md
```

Implementation surfaces:

```text
src/octogamedb/world_entity_search.py
src/octogamedb/world_entity_cli.py
tests/test_world_entity_search.py
scripts/validate_p7_t05.py
```

Validated semantics to preserve:

- canonical creature/gameobject template search by kind, ID and name;
- every P1 spawn remains independent;
- zone/map predicates use positive spawn evidence plus conservative 3-state evaluation;
- selected D-026 `spawn_set` negatives require exact coverage by **distinct canonical `spawn_key`**;
- duplicate selected source members remain provenance/diagnostics and do not fabricate extra spawns;
- protected/custom extra canonical spawns, missing members and unresolved geography keep negatives
  `unknown`;
- P2 direct/reference loot and vendor roles remain separate with path-level chance semantics;
- vendor `max_count` is not chance;
- P3 giver/finisher/objective roles remain separate, including selected-but-unmaterialized evidence;
- P4 trainer `direct`/`template` semantics and unresolved native evidence are preserved;
- full quest and recipe graphs remain owned by P7-T03/P7-T04;
- deterministic bounded JSON-friendly output and strict read-only SQLite access.

Human repository gates passed:

```text
pytest --basetemp="$env:TEMP\OctoGameDB_pytest"
346 passed in 14.51s

python -m ruff check src tests
All checks passed!

python -m compileall -q src tests scripts
PASS
```

Accepted-canonical Level 2 passed:

```text
P7_T05_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
creature_identities=13842
gameobject_identities=20967
duplicate_spawn_set_sample_kind=creature
duplicate_spawn_set_sample_id=1852
duplicate_spawn_set_member_count=1
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

The accepted canonical DB remained byte-identical. No architecture decision changed.

## Routed next task

```text
P7-T06 — provenance-aware zone-centric exploration
docs/project/tasks/P7-T06.md
status: READY_FOR_IMPLEMENTATION after P7-T05 commit/push + fresh main resolve
```

P7-T06 is the missing first-class zone consumer view already required by `PROJECT.md`. It should
compose validated world, quest, item-acquisition and recipe-learning geography without persisting a
simplified universal relation. General dungeon classification is intentionally not part of this first
zone slice.

### Start gate

1. Commit/push the full validated P7-T05 implementation plus this closeout.
2. Start a fresh coding conversation.
3. Resolve actual GitHub `main`.
4. If that main contains this P7-T05 closure, read `docs/project/tasks/P7-T06.md` and implement it.
5. Otherwise stop and reconcile integration state before coding.

## Routing constraints that remain active

Further P6 acquisition remains consumer-driven. Weapon damage/speed/block, item effects/tooltips,
weighted scores, saved searches, ownership/inventory integration, generalized dungeon classification,
economics/profit modeling and graphical UI remain later bounded tasks unless a future task proves a
concrete prerequisite.
