# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must verify the actual current head before editing.

## Integration baseline for this handoff

P5-T05 implementation was delivered as a local delta stacked on GitHub `main` commit:

```text
26df062594e888206171ed9cb3d1027bf29a3473
```

Commit title:

```text
Validate P5-T04 spawn divergence audit and route P5-T05
```

The human applied that P5-T05 delta and completed all required local validation successfully on
2026-08-28. This closeout/routing delta is intentionally stacked on that validated local integration
state; if the P5-T05 implementation has not yet been pushed, GitHub `main` will temporarily lag this
handoff.

## Validated cumulative state

P0 through **P5-T05** are `VALIDATED`.

The canonical database schema remains:

```text
P4-T04 / migration 13 / 0013_recipe_acquisition_sources.sql
```

P5-T01 through P5-T05 are read-only audit work and introduce no migration.

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

Active complete-set provenance for the one-sided population:

```text
pfquest base effective view   =    31
pfquest-turtle effective view = 22264
```

Threshold-free P5-T04 coordinate-compatible candidate baseline:

```text
zero compatible opposite        = 12103
exactly one compatible opposite =  1539
multiple compatible opposites   =  8653

nearest-neighbour ties
  zero                           = 12103
  one                            = 10146
  multiple                       =    46

compatible candidate pairs       = 148050
unique nearest candidate pairs   =   8416
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

P5-T04 therefore did not justify global spawn-key pairing/merging or a source-authority change.

## P5-T05 validated result — 2026-08-28

Full local Level-2 validation passed against the exact migration-13 canonical SHA-256:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The canonical DB and validation snapshot remained byte-identical, SQLite integrity/FKs passed, and
the exact P5-T03/P5-T04 baselines were reproduced.

Measured P5-T05 three-way attribution:

```text
base_active_not_comparison     =    17  ( 0.07625%)
active_only_vs_base            = 15988  (71.71115%)
base_comparison_not_active     =  1571  ( 7.04642%)
comparison_only_vs_base        =  4719  (21.16618%)
                                -----
one-sided total                = 22295
```

Interpretive boundary:

```text
overlay additions vs base      = 20707  (92.87733%)
base-present absences/changes  =  1588  ( 7.12267%)
```

Source-local replacement candidates are not dominant:

```text
active-side eligible / zero-compatible     = 17559 / 13563
active-side mutual-nearest pairs           =   542

comparison-side eligible / zero-compatible =  4736 /  4721
comparison-side mutual-nearest pairs       =     6
```

Validated addition-relative-base concentration combines creature/gameobject memberships:

```text
Stonetalon Mountains = 5145
Grim Reaches         = 5062
Northwind            = 2872
Blackrock Depths     = 2528

top 3 = 13079 / 20707 = 63.16%
top 4 = 15607 / 20707 = 75.37%
```

This does not establish source authority. D-025/D-026 remain unchanged and `pfquest-octo` remains
comparison evidence only.

Local validation layout note: the exact canonical SHA-matching DB was discovered at the legacy
relative path `data/octogamedb.sqlite3`. This does **not** supersede D-029, whose normal canonical
path remains `data/generated/octogamedb.sqlite3`. P5-T06 is read-only, so this is non-blocking; a
future canonical-mutating task must resolve the path contract before writing.

## Active task

### P5-T06 — overlay-addition coverage by base-parent and zone provenance

**Status: READY_FOR_IMPLEMENTATION.**

Task contract:

```text
docs/project/tasks/P5-T06.md
```

Routing basis:

- 20,707 / 22,295 one-sided memberships are additions relative to base;
- 15,988 are active/Turtle-side additions and 4,719 are Octo-comparison-side additions;
- geometric replacement evidence is too sparse to prioritize identity normalization;
- 63.16% of the 20,707 addition-relative-base memberships are concentrated in the top three
  zones.

P5-T06 must remain read-only and operate from persisted migration-13 provenance. It will decompose
only:

```text
active_only_vs_base
comparison_only_vs_base
```

by parent base-presence evidence, overlay source, parent, zone/map and cross-overlay
parent/zone coverage. It must distinguish:

```text
base-absent parent / whole-content addition
base-present parent / extra spawn membership
```

without changing canonical selection, source authority, D-025/D-026, or spawn identity.

No new local source path or raw-addon reload is required for the planned audit.

## Next action

Implement P5-T06 from `docs/project/tasks/P5-T06.md`. Keep the scope limited to the validated
P5-T05 addition-relative-base population and use the P5-T05 fixed counts as regression baselines.
