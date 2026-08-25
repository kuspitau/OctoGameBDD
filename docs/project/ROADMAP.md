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

Detailed record: `docs/project/tasks/P3-T02.md`.

### P3-T03 — quest restrictions and dependency graph

**VALIDATED.**

Adds D-030 and migration 8 for quest/minimum level, raw race/class masks, explicit any-of prerequisite
sets, derived follow-ups and explicit per-quest close/exclusive member sets with task-specific
base/Turtle effective-view provenance.

Detailed record: `docs/project/tasks/P3-T03.md`.

### P3-T04 — quest objectives and objective geography

**VALIDATED.**

Migration 9 and the P3-T04 reconciler model the pfQuest objective families `U/O/I/IR/A/Z`, the
supporting `quests-itemreq` target-use evidence and area-trigger location evidence with explicit
source-shape/provenance semantics. Objective geography is derived through existing P1 spawns for
creature/game-object targets, through item-use targets where available, or represented directly from
source-backed area-trigger/zone evidence.

Full local and canonical validation completed on 2026-08-25. The canonical DB contains `4,224`
complete quest objective sets, `1,484` creature objectives, `99` game-object objectives, `5,064` item
objectives, `226` item-use objectives, `50` area-trigger objectives and no selected real-data direct
zone objective in the current source revisions. It also contains `496` area-trigger identities with
`558` locations and `189` item-use target sets with `333` materialized target relations.

The second same-revision canonical pass produced zero inserts, updates and deletes; FK/integrity
checks passed. `219` unresolved source references remain explicit audit evidence rather than fabricated
identities.

Detailed record: `docs/project/tasks/P3-T04.md`.

### P3-T05 — quest item requirements and rewards

**BLOCKED_ON_SOURCE_CONTRACT.**

Primary-source inspection on 2026-08-25 established that the distributed pfQuest quest export cannot
support the planned quantity/reward import faithfully:

- raw `ReqItemId*` and `ReqSourceId*` are collapsed into membership-only `obj.I`;
- their corresponding counts are not serialized;
- guaranteed and choice item rewards are not serialized;
- `quests-itemreq` is item-use target evidence, not quantity evidence;
- the reviewed/current public pfQuest-turtle quest data does not restore those fields.

D-031 forbids filling the gap by inference. The intended canonical functionality remains planned, but
implementation waits on P3-T05A.

Detailed task: `docs/project/tasks/P3-T05.md`.

### P3-T05A — establish quest quantity/reward source contract

**READY_FOR_IMPLEMENTATION.**

Next bounded scope:

- inspect Octo-specific authoritative quest data first, beginning with OctoDB and any stable structured
  payload/API or reproducible page representation it exposes;
- identify exact required-item/source-item quantity and guaranteed/choice reward semantics;
- establish deterministic source revision/caching/retrieval and provenance rules;
- determine Vanilla versus Octo/Turtle custom-quest coverage;
- use a pinned VMaNGOS/CMaNGOS-style baseline only under an explicit fallback/authority policy if
  needed;
- update source/decision/task memory so P3-T05 can resume without repeating source archaeology.

Do not add P3-T05 canonical requirement/reward tables merely to make the future model writable before
this source contract is established.

Detailed task: `docs/project/tasks/P3-T05A.md`.

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
