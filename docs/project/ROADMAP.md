# Roadmap

Task IDs are stable handoff references. Do not renumber completed tasks. Detailed source, validation
and closeout evidence lives in task documents and `CURRENT_STATE.md`.

## P0 — Repository and data foundation

Goal: trustworthy project-owned persistence/import/test/provenance infrastructure.

- **P0-T01 — SQLite foundation and import metadata: VALIDATED**
- **P0-T02 — provenance/conflict primitives: VALIDATED**
- **P0-T03 — fixture/golden-case and audit skeleton: VALIDATED**

## P1 — World foundation

Goal: maps, zones/subzones, creatures/spawns and gameobjects/spawns with explicit coordinate semantics.

- **P1-T01 — world schema and pfQuest vertical slice: VALIDATED**
- **P1-T02 — Octo DBC map/area hierarchy: VALIDATED**
- **P1-T03 — pfQuest Turtle/Octo effective world views: VALIDATED**
- **P1-T04 — overlay provenance/canonical reconciliation: VALIDATED**

## P2 — Items and acquisition

Goal: item identity plus explicit primitive acquisition paths and derived geography.

- **P2-T01 — direct creature/gameobject loot: VALIDATED**
- **P2-T02 — pfQuest reference-loot resolution: VALIDATED**
- **P2-T03 — pfQuest vendor acquisition: VALIDATED**
- **P2-T04 — pfQuest-turtle effective item/acquisition reconciliation: VALIDATED**

## P3 — Quests

Goal: quest identity, endpoints, progression, objectives, item requirements/rewards and derived
geography.

- **P3-T01 — quest identity/endpoints: VALIDATED**
- **P3-T02 — Turtle effective quest identity/endpoints: VALIDATED**
- **P3-T03 — restrictions/dependency graph: VALIDATED**
- **P3-T04 — objectives/objective geography: VALIDATED**
- **P3-T05A — item/reward source contract: VALIDATED**
- **P3-T05B — direct-Octo/Tortoise source validation: VALIDATED**
- **P3-T05 — item requirements/rewards implementation and canonical migration 10: VALIDATED**

## P4 — Recipes and crafting

Goal: first-class recipe/spell identities, profession membership, outputs, reagents and independent
learning/acquisition paths.

### P4-T01 — source/identity contract

**VALIDATED.** D-034 anchors recipe identity to a proven crafting spell while keeping learning sources
separate.

### P4-T02 — canonical spell / skill-line / recipe identity

**VALIDATED.** Migration 11 materializes spells, skill lines, recipes, profession memberships and
slot-preserving outputs from the verified Octo DBC revision.

### P4-T03 — recipe reagents and quantities

**VALIDATED.** Migration 12 materializes native reagent slots/IDs and exact `Spell.ReagentCount`
quantities. Its exact canonical file is now the D-029 rollback for validated migration 13.

### P4-T04 — recipe learning/acquisition sources

**VALIDATED.** Migration 13 materializes explicit teaching-item, trainer-creature and quest-reward
learning relations without duplicating derived teaching-item vendor/loot/zone paths. D-035 keeps exact
Octo DBC `LEARN_SPELL` as preferred learning proof and permits pinned Tortoise `spell_learn_spell` only
as lower-authority fallback.

Final full-data validation and guarded promotion on 2026-08-26 produced:

```text
recipe_count                     = 1739
teaching_item_count              = 1065
trainer_source_count             = 6376
direct_trainer_source_count      = 5834
template_trainer_source_count    = 542
quest_learning_source_count      = 16
dbc_proven_acquisition_count     = 7457
server_fallback_acquisition_count = 0
second_import                     = 0 inserted / 0 updated
foreign_key_check                 = []
integrity_check                   = ok
```

Canonical migration-13 SHA-256:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

D-029 rollback now preserves the exact migration-12 canonical:

```text
6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261
```

Detailed evidence remains in `docs/project/tasks/P4-T04.md`. P4 is closed and P5 is unblocked.

## P5 — Resolution, auditing and coverage

After P4 closes, expand:

- source-specific resolution policies;
- conflict inspection;
- trace/provenance views;
- coverage metrics;
- source-difference reports;
- data-quality/idempotency checks.

## P6 — Full Octo import / scaling

Scale importers to the full useful source set, profile performance/database size, and add materialized
derived views only where measurements justify them.

## P7 — Graphical explorer

Build the local entity explorer with Items, Quests, Creatures, GameObjects, Recipes, Spells and Zones,
including cross-entity navigation, provenance inspection, tooltips and spawn maps. UI framework choice
remains deferred until data/query requirements justify it.

## P8 — Advanced queries

Add query builder, saved searches, weighted stat profiles, item comparisons, advanced cross-domain
filters and measured materialized views where useful.

## Development strategy

For each new fact family:

1. inspect primary-source semantics;
2. distinguish authority from completeness;
3. prefer direct current Octo observations for fields they actually expose;
4. use small source-shaped fixtures;
5. validate schema/provenance/effective-view behavior;
6. add golden and conflict cases;
7. perform Level-2 validation when real local data is required;
8. advance the canonical DB only after successful validation;
9. update durable project memory before routing the next bounded task.
