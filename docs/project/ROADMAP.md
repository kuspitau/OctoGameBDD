# Roadmap

Task IDs are stable handoff references. Do not renumber completed tasks.

Detailed historical/source/validation facts live in task documents and `CURRENT_STATE.md`. This
roadmap keeps phase order and the next bounded work visible without duplicating every closeout metric.

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

Full local and canonical validation completed on 2026-08-25. The second same-revision canonical pass
produced zero inserts, updates and deletes; FK/integrity checks passed. Unresolved source references
remain explicit audit evidence rather than fabricated identities.

Detailed record: `docs/project/tasks/P3-T04.md`.

### P3-T05A — establish quest quantity/reward source contract

**VALIDATED.**

P3-T05A established the semantic separation of `ReqItem`, `SrcItem`, auxiliary `ReqSource`, guaranteed
`RewItem` and choice `RewChoiceItem`, including preservation of `ReqSourceCount = 0`. D-032 remains
historical where later D-033 did not supersede it.

Detailed record: `docs/project/tasks/P3-T05A.md`.

### P3-T05B — validate Octo live quest-query and Tortoise SQL source contract

**VALIDATED.**

P3-T05B implemented and locally validated the D-033 acquisition bridge without canonical DB mutation:

- source-shaped Tortoise `quest_template` projection at pinned revision
  `61a8269151721f6467eddb05e7bed37704d0fc0b` with deterministic relevant migration replay;
- bounded actual-Octo ClassicAPI capture using pinned semantic reference
  `e793f80f6b45ed49a94dc8abdc9fcac4fe6b03dd`;
- reviewed OctoDB structural positive evidence;
- pinned CMaNGOS Vanilla fallback/baseline;
- deterministic four-source comparison with D-033 family-specific selection, conflict retention and
  conservative unknown/absence semantics;
- real `ReqSource` audit preserving explicit zero-count semantics;
- canonical SQLite hash unchanged across validation.

Level-2 validation completed on 2026-08-26. Detailed record:
`docs/project/tasks/P3-T05B.md`.

### P3-T05 — quest item requirements and rewards

**VALIDATED.**

Migration 10 now models the bounded P3 quest/item quantity and reward families while preserving D-033
and the validated P3-T05B acquisition contract:

- ordinary required item + explicit quantity;
- auxiliary `ReqSource` + raw source-count semantics;
- quest-provided/source item with nullable quantity when count evidence is unknown;
- guaranteed reward item + quantity;
- explicit choose-one reward set + quantity-bearing members;
- source-family/slot/duplicate primitive provenance before normalization;
- conservative partial-source absence and complete managed-fallback replacement;
- unresolved native targets retained as audit/provenance rather than fabricated identities;
- P3-T04 objective membership kept distinct from P3-T05 quantity evidence.

Full local validation completed on 2026-08-26. The disposable and real canonical runs both reached
schema version 10, the second same-input reconciliation produced zero canonical inserts/updates/deletes,
FK/integrity checks passed, no same-priority ambiguity or reconciliation anomaly remained, and the
D-029 backup was verified byte-identical to the migration-9 baseline before canonical evolution.

Final P3-T05 canonical family counts:

```text
quest_required_items       6100
quest_required_sources     2961
quest_provided_items       1320
quest_reward_items         2072
quest_choice_reward_items  2424
```

Detailed record: `docs/project/tasks/P3-T05.md`.

## P4 — Spells and crafting

Goal:

- spells required for item/recipe relationships;
- recipes;
- profession/skill requirements;
- results;
- reagents;
- learning/acquisition sources;
- recipe item / teaching spell / crafted item distinctions;
- derived recipe availability.

### P4-T01 — spell/recipe source and identity contract

**VALIDATED.**

D-034 now establishes the bounded P4 identity contract from pinned primary source behavior:

- `Spell.Id` remains native spell identity;
- recipe identity is separate but anchored to a proven crafting spell ID;
- profession/skill-line membership comes from `SkillLineAbility.skillId -> spellId`;
- `req_skill_value` remains distinct from trainer acquisition requirements and character level;
- teaching items/trainers point to acquisition spells and require proven `LEARN_SPELL` targets;
- crafted outputs are `CREATE_ITEM` effect-slot relations and may be multiple/variable;
- effect/item-spell slots are provenance-bearing and are not flattened.

A reduced source-shaped normalizer/fixture/test suite locks those distinctions without changing the
canonical schema or migration-10 local DB. Focused agent-side tests passed, followed by successful
human local integration validation on 2026-08-26: repository pytest, Ruff across `src`, `tests` and
`scripts`, compile checks, the deterministic P4-T01 validator, and protected-DB byte-identity checks
all passed. No source-specific/full-data rerun was required.

Detailed record: `docs/project/tasks/P4-T01.md`.

### P4-T02 — canonical spell / skill-line / recipe identity slice

**VALIDATED.**

Migration 11 and the direct-Octo DBC importer now implement the bounded D-034 canonical slice:

- native `spells` identity plus available name/rank metadata without rank merging;
- native `skill_lines` identity plus available names;
- separate `recipes` identity anchored exactly to the proven crafting spell ID;
- native `SkillLineAbility.id` membership plus `req_skill_value`;
- one `recipe_outputs` row per `CREATE_ITEM` effect slot;
- exact native output item target retention even when the canonical `items` identity is unresolved;
- no fabricated fixed output quantity;
- deterministic three-file DBC revision, explicit exact-layout/completeness metadata and provenance;
- preservation of canonical selections governed by a foreign/custom selection policy.

The parser remains fail-closed and recognizes two explicitly reviewed `Spell.dbc` forms:
`176/704` from the P4-T01 Tortoise reference and `173/692` from standard Vanilla 1.12, the latter
observed directly in the configured Octo client. SkillLine remains `22/88` and SkillLineAbility
`15/60`. Real-source cross-file orphans outside recipe qualification are reported explicitly without
fabricating spell/skill identities; recipe-qualified missing skill-line identities remain fatal.

Human Level-2 validation completed on 2026-08-26 with source revision
`sha256:f82d41ddbb77f5958d36b2483786c819de512128ef736142c758469718f7274d`: 1,739 recipes,
15 represented skill lines, 1,739 outputs and 114 unresolved canonical item targets. The second import
was canonically idempotent, FK/integrity checks passed, and the guarded D-029 promotion advanced the
canonical local DB to migration 11. Final canonical SHA-256 is
`3e2a1b03dd688fc1b944665fcfa79cde68aacb537790f0c580480049a19ad8e7`; the rollback is the exact
migration-10 canonical `9c637ab40c2c5e3c2843e6c7d52fb5c75bbe05f57d05e2ea4d48ae7bd03b127d`.

The next bounded P4 task is P4-T03 recipe reagents/quantities; learning/acquisition sources remain a
separate later task.

Detailed record and exact validation/promotion commands: `docs/project/tasks/P4-T02.md`.

### P4-T03 — recipe reagents and quantities

**VALIDATED.**

Migration 12 and the direct-Octo reagent importer implement the bounded reagent slice without mixing
in recipe learning/acquisition sources:

- each positive `Spell.Reagent[0..7]` item ID is retained with its native slot/index;
- the exact matching `Spell.ReagentCount[0..7]` value is retained as `required_quantity`;
- all eight slots are scanned independently rather than truncating at the first empty slot;
- native reagent item IDs remain exact even when canonical `items` identity is unresolved;
- a positive reagent with quantity `0` is preserved and reported instead of guessed away;
- managed provenance selection does not overwrite a foreign/custom canonical selection;
- the importer requires the exact same three-file DBC revision as the latest successful P4-T02
  `octo-dbc-recipes/4` identity import;
- a later different DBC revision is rejected until explicit cross-revision reagent reconciliation
  semantics are designed.

Primary-source review confirmed reagent IDs/counts at physical Spell fields `42..49` / `50..57` and
current Octo client offsets `0xA8` / `0xC8`. Both reviewed Spell layouts remain supported (`176/704`,
`173/692`).

Human Level-2 validation completed on 2026-08-26 after full repository pytest/Ruff/compile gates.
The real configured Octo DBC revision was
`sha256:f82d41ddbb77f5958d36b2483786c819de512128ef736142c758469718f7274d`.
The disposable proof and guarded promotion both passed with 1,739 recipes, 5,801 reagent relations,
1,721 recipes with reagents, 85 unresolved canonical reagent-item targets and zero zero-quantity or
negative reagent slots. Same-input second import was `0/0`, FK/integrity checks passed, and the D-029
promotion advanced the canonical DB to migration 12.

Final canonical SHA-256 is
`6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261`; rollback is the exact
migration-11 canonical `3e2a1b03dd688fc1b944665fcfa79cde68aacb537790f0c580480049a19ad8e7`.

Detailed record: `docs/project/tasks/P4-T03.md`.

### P4-T04 — recipe learning/acquisition sources

**READY_FOR_RESEARCH_AND_IMPLEMENTATION.**

This is the next bounded P4 slice. Establish primary-source semantics and then materialize proven
recipe learning/acquisition relations (trainer, vendor, teaching item, quest or other evidenced
source) without conflating acquisition spells/items with canonical recipe identity. Reuse D-034,
native IDs and provenance/selection rules. Derived recipe availability should remain distinct from raw
acquisition evidence until its own contract is explicit.

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
2. distinguish source authority from source completeness/coverage;
3. prefer direct current Octo observations for fields they actually expose, without generalizing them
   to invisible server-side fields;
4. use small representative fixtures;
5. validate schema/provenance/effective-view behavior;
6. add golden cases and explicit conflict cases;
7. perform Level-2 validation against configured real data/live client inputs when required;
8. advance the canonical local DB only after successful validation;
9. then route the next bounded task.
