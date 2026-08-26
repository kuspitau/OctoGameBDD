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

- **P4-T01 — source/identity contract: VALIDATED**
- **P4-T02 — canonical spell / skill-line / recipe identity: VALIDATED**
- **P4-T03 — recipe reagents and quantities: VALIDATED**
- **P4-T04 — recipe learning/acquisition sources: VALIDATED**

Canonical migration-13 SHA-256 remains:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

## P5 — Resolution, auditing and coverage

Goal: make accumulated multi-source evidence measurable and inspectable before changing resolution
policies or scaling additional source families.

### P5-T01 — resolution audit baseline

**VALIDATED.**

P5-T01 added a read-only provenance-resolution inventory and validated it on the real cumulative
migration-13 DB.

Measured baseline:

```text
observation groups                 = 1307532
selected                           = 1297652
unselected                         = 9880
conflicts                          = 64512
resolved conflicts                 = 64512
unresolved conflicts               = 0
unselected single-value groups     = 9880
empty groups                       = 0
selection policies                 = 24
selected sources                   = 7
fact families                      = 82
```

The canonical DB remained byte-identical during validation.

### P5-T02 — unselected single-value provenance audit

**READY_FOR_IMPLEMENTATION.**

Explain and classify the 9,880 unselected single-value groups before any policy changes.

The measured family distribution is limited to creature/gameobject identity/presence/spawn-set facts
and creature/gameobject spawn position/respawn facts, with the overwhelming majority in spawn facts.

P5-T02 must remain read-only and provide deterministic drill-down/grouping sufficient to decide
whether each class represents:

- expected non-canonical evidence;
- intentionally excluded effective-view data;
- an importer/reconciler coverage gap;
- or a genuine missing-selection candidate.

It must not auto-select canonical observations.

Detailed task contract:

```text
docs/project/tasks/P5-T02.md
```

Later P5 work remains routed from measured findings. Candidate bounded follow-ups include:

- explicit policy correction for genuine missing-selection classes discovered by P5-T02;
- deeper source-difference reports;
- domain-specific coverage/completeness metrics;
- broader data-quality/idempotency audits.

Any later task that changes source-selection policy must document the authority/behavior change rather
than silently embedding it in audit code.

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
