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
```

### P5-T02 — unselected single-value provenance audit

**VALIDATED.**

All 9,880 unselected single-value groups are intentional `pfquest-octo` comparison evidence under
P1-T04 / D-026. P5-T02 found no missing selection policy or reconciliation coverage defect.

### P5-T03 — selected-vs-comparison P1 world difference audit

**VALIDATED.**

Measured full-data result:

```text
record_count                  = 450659
same_value                    = 394970
different_value               =   2759
active_only                   =  32078
comparison_only               =  12600
not_directly_comparable       =   8252
```

Unique spawn membership differences:

```text
creature active-only / comparison-only   = 10255 / 3928
gameobject active-only / comparison-only =  5750 / 2362
total unique membership differences      = 22295
```

Shared-spawn positions have zero differing values, while only 21 shared `respawn_seconds` facts differ.

Detailed evidence:

```text
docs/project/tasks/P5-T03.md
```

### P5-T04 — pfquest-octo spawn membership divergence characterization

**VALIDATED.**

P5-T04 fully validated the unique one-sided spawn population without mutating canonical data.

Measured topology:

```text
shared members                  = 145447
active-only members             =  16005
comparison-only members         =   6290
one-sided members               =  22295

directly comparable parents     =  24992
shared_only                     =  22428
active_only_members             =   1274
comparison_only_members         =    154
mixed_one_sided_members         =   1136
```

Candidate cardinality:

```text
zero compatible opposite        = 12103  (54.29%)
exactly one candidate           =  1539  ( 6.90%)
multiple candidates             =  8653  (38.81%)
```

The active complete-set context is `pfquest-turtle` for 22,264 / 22,295 one-sided memberships.
Divergence is strongly concentrated by zone/direction: the top 10 reported zone/direction buckets
contain 73.50% of the one-sided population, while the top 10 individual parents contain only 10.47%.

The evidence does not justify automatic coordinate matching, source promotion, or a D-026 change.

Detailed evidence:

```text
docs/project/tasks/P5-T04.md
```

### P5-T05 — three-way base/Turtle/Octo spawn divergence attribution

**READY_FOR_IMPLEMENTATION.**

P5-T05 should explain the P5-T04 population by comparing each one-sided spawn membership across:

```text
pfquest base
active selected effective view
pfquest-octo comparison
```

The primary four source-attribution patterns are:

```text
base=1 active=1 comparison=0  -> comparison-side absence/change relative to base
base=0 active=1 comparison=0  -> active/Turtle-side addition relative to base
base=1 active=0 comparison=1  -> active/Turtle-side absence/change relative to base
base=0 active=0 comparison=1  -> comparison/Octo-side addition relative to base
```

P5-T05 should quantify those patterns by creature/gameobject, parent and zone/map, then use
coordinate-neighbour evidence only as a secondary descriptive layer for likely source-local moves.

It remains read-only and must not merge spawn identities, change canonical selection, promote
`pfquest-octo`, or change D-025/D-026.

Detailed contract:

```text
docs/project/tasks/P5-T05.md
```

Later P5 work remains routed from measured P5-T05 findings.

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
