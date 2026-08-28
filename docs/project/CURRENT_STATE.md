# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must verify the actual current head before editing.

## Integration baseline for this handoff

The P5-T04 implementation was originally prepared against GitHub `main` commit:

```text
a2dba2d9d60841b10d860a94221a749e1a1d39c5
```

Commit title:

```text
Validate P5-T03 world comparison audit and route P5-T04
```

This closeout delta assumes the already delivered P5-T04 implementation plus the duplicate-membership
hotfix have been applied locally. The human should commit/push the combined P5-T04 implementation,
hotfix and this closeout together before starting a new coding conversation.

## Validated cumulative state

P0 through **P5-T04** are `VALIDATED`.

The canonical database schema remains:

```text
P4-T04 / migration 13 / 0013_recipe_acquisition_sources.sql
```

P5-T01 through P5-T04 are read-only audit work and introduce no migration.

Current validated canonical SHA-256 remains:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The D-029 one-step rollback remains the exact migration-12 canonical:

```text
sha256:6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261
```

D-025 and D-026 are unchanged. `pfquest-octo` remains comparison evidence only.

## P5-T03 validated baseline

```text
audited records               = 450659
same_value                    = 394970
different_value               =   2759
active_only                   =  32078
comparison_only               =  12600
not_directly_comparable       =   8252
```

Validated comparison source:

```text
source_key      = pfquest-octo
source_revision = sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db
```

## P5-T04 validated result — 2026-08-28

P5-T04 is fully Level-2 validated on the unchanged migration-13 canonical database.

Exact unique spawn membership baseline:

```text
creature
  shared members          = 85551
  active-only members     = 10255
  comparison-only members =  3928

gameobject
  shared members          = 59896
  active-only members     =  5750
  comparison-only members =  2362

shared total                   = 145447
active-only total              =  16005
comparison-only total          =   6290
total unique one-sided members =  22295
```

Directly comparable parent topology:

```text
directly comparable parents = 24992

shared_only                  = 22428
active_only_members          =  1274
comparison_only_members      =   154
mixed_one_sided_members      =  1136
```

Thus 2,564 / 24,992 directly comparable parents contain at least one one-sided membership.

Active complete-set provenance for the one-sided population:

```text
pfquest base effective view
  one-sided members =    31

pfquest-turtle effective view
  one-sided members = 22264
```

So 99.86% of the one-sided population belongs to an active `pfquest-turtle` complete-set context.

Threshold-free coordinate-compatible candidate analysis:

```text
members with zero compatible opposite = 12103  (54.29%)
members with exactly one candidate     =  1539  ( 6.90%)
members with multiple candidates       =  8653  (38.81%)

members with any compatible opposite   = 10192  (45.71%)

nearest-neighbour tie cardinality
  zero                                 = 12103
  one                                  = 10146
  multiple                             =    46

compatible candidate pairs             = 148050
unique nearest candidate pairs         =   8416
```

Compatible-pair distance distribution in `zone_percent` space:

```text
(0,0.1]       =     19
(0.1,0.5]     =    240
(0.5,1]       =    777
(1,2]         =   3171
(2,5]         =  20645
>5            = 123198
```

Only 4,207 / 148,050 compatible pair possibilities are within 2 zone-percentage points, while
123,198 / 148,050 are farther than 5. These are pair-level descriptive counts, not identity proofs.

The divergence is strongly concentrated by zone/direction but much less concentrated by individual
parent:

```text
top 10 zone/direction buckets = 16386 / 22295 = 73.50%
top 20 zone/direction buckets = 19728 / 22295 = 88.49%

top 10 parent concentrations  =  2334 / 22295 = 10.47%
top 25 parent concentrations  =  4123 / 22295 = 18.49%
```

Largest observed zone/direction buckets include:

```text
creature active-only     Grim Reaches          = 3262
creature active-only     Stonetalon Mountains  = 2283
gameobject active-only   Grim Reaches          = 1800
creature comparison-only Stonetalon Mountains  = 1753
creature active-only     Northwind             = 1748
gameobject active-only   Stonetalon Mountains  = 1497
```

### Validation evidence

The human ran the previously required classic suite successfully before the hotfix.

After the duplicate-membership hotfix, the autonomous local wrapper additionally passed:

```text
targeted P5-T04 pytest = 4 passed
targeted Ruff          = passed
targeted compileall    = passed
```

The Level-2 validator then passed:

```text
canonical migration-13 DB exists
no WAL/SHM sidecars
canonical SHA-256 baseline
snapshot byte identity
PRAGMA integrity_check
PRAGMA foreign_key_check
migration 13
P5-T04 scope/source/revision
exact P5-T04 membership baseline
parent/source/provenance partitions
candidate-cardinality partitions
bounded real examples
P5-T03 record/state/membership baselines unchanged
snapshot byte identity after audit
canonical byte identity after audit
```

Final canonical SHA-256 remained exactly:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The first failed Level-2 attempt is retained as useful validation history: it exposed a P5-T04 bug
where duplicate `spawn_key` rows caused a whole persisted complete set to be rejected. The hotfix
aligned P5-T04 with P5-T03 unique-set semantics and the corrected Level-2 run passed all fixed
baselines.

## Closeout interpretation

P5-T04 does **not** support automatically pairing or merging one-sided spawn identities:

- a majority (54.29%) have no coordinate-compatible opposite at all;
- only 6.90% have exactly one compatible opposite;
- 38.81% have multiple compatible opposites;
- the candidate-pair distance distribution is dominated by pairs farther than 5 zone-percentage
  points;
- the one-sided population is overwhelmingly attached to the active Turtle effective view and is
  strongly concentrated by zone.

This is stronger evidence for **source-view/content-set divergence** than for a single global
coordinate-identity problem, but P5-T04 alone cannot say which overlay introduced or removed each
membership relative to the common base source.

No authority or selection-policy change is justified yet.

## Active task

### P5-T05 — three-way base/Turtle/Octo spawn divergence attribution

**Status: READY_FOR_IMPLEMENTATION.**

Task contract:

```text
docs/project/tasks/P5-T05.md
```

P5-T05 is a bounded read-only provenance audit. It should use persisted complete-set observations to
compare three views for the same P1 spawn family:

```text
pfquest base
active selected effective view (normally pfquest-turtle)
pfquest-octo comparison
```

For every P5-T04 one-sided spawn key, determine its base/active/comparison membership vector and
partition the 22,295 members into source-attribution classes. The primary goal is to distinguish:

- an Octo-side absence/change relative to a base membership;
- a Turtle-side addition relative to base;
- a Turtle-side absence/change relative to a base membership;
- an Octo-side addition relative to base.

The task may then use the P5-T04 coordinate analysis only as secondary evidence for source-local
coordinate replacement patterns. It must not merge identities or alter canonical selection.

No new source path should be required unless persisted provenance proves insufficient.

## Next action

Implement P5-T05 from `docs/project/tasks/P5-T05.md` after the human commits and pushes the combined
P5-T04 implementation/hotfix/closeout.
