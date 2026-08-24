# Roadmap

Task IDs are stable handoff references. Do not renumber completed tasks.

Detailed historical/source/validation facts live in the task documents and `CURRENT_STATE.md`. This
roadmap keeps the phase order and the next bounded work visible without duplicating every closeout
metric.

## P0 — Repository and data foundation

Goal: establish trustworthy project-owned persistence/import/test/provenance infrastructure.

- **P0-T01 — SQLite foundation and import metadata: VALIDATED**
- **P0-T02 — provenance/conflict primitives: VALIDATED**
- **P0-T03 — fixture/golden-case and audit skeleton: VALIDATED**

P0 established migrations, data-source/import-batch metadata, generic provenance/conflict primitives,
audit CLI surfaces, fixture conventions and the serial GitHub-read-only delta handoff workflow.

## P1 — World foundation

Goal: canonical maps, zones/subzones, creatures, creature spawns, game objects and game-object spawns,
with authoritative hierarchy and effective overlay reconciliation.

- **P1-T01 — world schema and pfQuest vertical slice: VALIDATED**
- **P1-T02 — Octo DBC map/area hierarchy: VALIDATED**
- **P1-T03 — pfQuest Turtle/Octo effective world views: VALIDATED**
- **P1-T04 — overlay provenance/canonical reconciliation: VALIDATED**

Key durable outcomes include template/spawn separation, explicit coordinate spaces, DBC-authoritative
map/area hierarchy, Turtle complete spawn-set reconciliation and optional pfQuest-octo comparison
evidence.

## P2 — Items and acquisition

Goal: item identity plus explicit acquisition paths and derived geography.

- **P2-T01 — direct creature/game-object loot: VALIDATED**
- **P2-T02 — pfQuest reference-loot resolution: VALIDATED**
- **P2-T03 — pfQuest vendor acquisition: VALIDATED**
- **P2-T04 — pfQuest-turtle effective item/acquisition reconciliation: VALIDATED**

Current P2 canonical support covers item identity, direct loot, one-level reference loot and vendors,
with source provenance and Turtle effective-view reconciliation. Rich item stats/effects/requirements,
new specialized loot families and economics remain deferred.

## P3 — Quests

Goal:

- quest identity/restrictions;
- givers/finishers;
- prerequisites/follow-ups;
- objectives;
- required items;
- rewards (guaranteed vs choice);
- derived quest geography.

### P3-T01 — first quest identity/endpoints vertical slice

**VALIDATED.**

Provides canonical native-ID quest identity plus explicit creature/game-object giver and finisher
relations. Missing P1 endpoint targets remain unresolved provenance without fabricated identities.
Endpoint geography is derived through P1.

Detailed record: `docs/project/tasks/P3-T01.md`.

### P3-T02 — pfQuest-turtle effective quest identity/endpoint reconciliation

**VALIDATED.**

Adds D-028 and reconciles the P3-T01 fact family against the installed Turtle effective view using
`quest_presence` and `quest_endpoint_set`, source-correct primitive provenance, protected explicit
selections, stale managed-endpoint cleanup and same-revision idempotence.

Full local validation completed on 2026-08-24. A fresh cumulative rebuild through P3-T02 produced a
clean canonical local DB with `6,498` quests, `12,145` creature endpoints and `545` game-object
endpoints and passed FK/integrity validation.

Detailed record: `docs/project/tasks/P3-T02.md`.

### P3-T03 — quest restrictions and dependency graph

**READY_FOR_IMPLEMENTATION.**

Next bounded scope:

- quest level and minimum/required level;
- race/class restrictions;
- prerequisite relations;
- derived follow-ups where appropriate;
- exclusive/closing quest-group semantics;
- explicit Turtle effective-view/reconciliation rules for this new fact family.

Primary-source inspection must confirm `lvl`, `min`, `race`, `class`, `pre`, and `close` semantics
before schema/materialization decisions. Do not silently generalize D-028.

Objectives, required items and rewards remain deferred to later bounded P3 tasks.

Detailed task: `docs/project/tasks/P3-T03.md`.

### Later P3 tasks — to be numbered when bounded

After P3-T03, choose the smallest coherent next vertical slice from:

- objectives (creature/gameobject/item);
- required item quantities/requirements;
- guaranteed rewards;
- choice rewards;
- item-started quest acquisition;
- additional restrictions/text needed by real source coherence.

Do not bundle all remaining quest fields into one task merely to "finish P3".

## P4 — Spells and crafting

Implement:

- spells required for item/recipe relationships;
- recipes;
- profession/skill requirements;
- results;
- reagents;
- learning/acquisition sources;
- recipe item / teaching spell / crafted item distinctions;
- derived recipe availability.

## P5 — Resolution, auditing and coverage

Expand:

- source-specific resolution policies;
- conflict inspection;
- trace/provenance views;
- coverage metrics;
- source-difference reports;
- data-quality checks;
- idempotency checks.

## P6 — Full Octo import / scaling

Scale importers to full available data from the useful source set, profile performance/database size,
and add materialized derived views only where measurements justify them.

The full generated DB remains local. D-029 / `CANONICAL_DB.md` governs its normal cumulative
lifecycle.

## P7 — Graphical explorer

Build the local entity explorer with tabs/views for Items, Quests, Creatures, GameObjects, Recipes,
Spells and Zones, including search/filter/sort, cross-entity navigation, provenance inspection,
tooltips and spawn maps.

NiceGUI remains a leading candidate but is not committed before the data/query layer demonstrates its
requirements.

## P8 — Advanced queries

Add:

- query builder;
- saved searches;
- weighted stat profiles/scores;
- item comparisons;
- advanced cross-domain filters;
- richer map views;
- optional measured materialized views.

## Development strategy

For each new domain/fact family:

1. inspect primary source semantics;
2. use small representative fixtures;
3. validate schema/provenance/effective-view behavior;
4. add golden cases;
5. perform Level-2 validation against configured real data;
6. advance the canonical local DB only after successful validation;
7. then route the next bounded task.
