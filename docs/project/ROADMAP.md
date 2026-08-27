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

**VALIDATED.**

P5-T02 added deterministic aggregate + bounded drill-down inspection for the 9,880 single-value
observation groups with no canonical selection and passed full-data validation without changing the
migration-13 canonical DB.

Closeout classification is complete:

```text
expected non-canonical evidence = 9880
effective-view exclusion        = 0
coverage/reconciliation gap     = 0
policy gap                      = 0
```

All 9,880 groups come exclusively from one successful `pfquest-octo` revision/batch. P1-T04 / D-026
already defines that optional source as comparison evidence that is retained without automatic
canonical selection, so P5-T02 found no missing selection policy and no reconciliation coverage bug.

The measured comparison-only remainder is:

```text
creature                         4 subjects /    9 groups
creature_spawn                2748 subjects / 5496 groups
gameobject                        5 subjects /   11 groups
gameobject_spawn               2182 subjects / 4364 groups
```

The 9,860 spawn groups are exact `position` + `respawn_seconds` pairs over 4,930 comparison-source
spawn subjects.

Detailed task state/evidence:

```text
docs/project/tasks/P5-T02.md
```

### P5-T03 — selected-vs-comparison P1 world difference audit

**READY_FOR_IMPLEMENTATION.**

P5-T03 follows the measured P5-T02 result rather than inventing a policy correction that the data does
not justify.

It should add a deterministic read-only comparison report for the bounded P1 world families implicated
by P5-T02, centered on the optional `pfquest-octo` evidence versus the active selected/effective P1
world view.

The report should quantify and drill into comparison differences such as:

- comparison-only subjects/spawns;
- active-view-only subjects/spawns where the required source evidence permits the comparison;
- same vs differing scalar/complete-set evidence;
- template-level versus spawn-level differences;
- source revision/batch provenance and selected sibling context.

No migration, canonical mutation, automatic source promotion or selection-policy rewrite belongs in
P5-T03. Any later policy task must be justified by its measured output.

Detailed task contract:

```text
docs/project/tasks/P5-T03.md
```

Later P5 work remains routed from measured findings. Candidate bounded follow-ups include:

- an explicit policy/source correction only if P5-T03 identifies a justified Octo-specific authority
  case;
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
