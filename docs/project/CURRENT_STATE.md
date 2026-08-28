# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must verify the actual current head before editing.

## Integration baseline for this handoff

P5-T06 implementation was delivered as a local delta stacked on GitHub `main` commit:

```text
24548eafa8a3f78997b6e31556ab605c00244087
```

Commit title:

```text
Validate P5-T05 spawn attribution audit and route P5-T06
```

The human applied that P5-T06 delta and completed both the classical repository checks and the
required Level-2/full-data validation successfully on 2026-08-28.

This closeout/routing delta is intentionally stacked on that validated local integration state. If
the P5-T06 implementation has not yet been pushed, GitHub `main` will temporarily lag this handoff.
Do not apply this closeout to a bare P5-T05 checkout without the preceding P5-T06 implementation.

## Validated cumulative state

P0 through **P5-T06** are `VALIDATED`.

The canonical database schema remains:

```text
P4-T04 / migration 13 / 0013_recipe_acquisition_sources.sql
```

P5-T01 through P5-T06 are read-only audit work and introduce no migration.

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

P5-T04 did not justify global spawn-key pairing/merging or a source-authority change.

## P5-T05 validated result — 2026-08-28

Measured three-way attribution:

```text
base_active_not_comparison     =    17
active_only_vs_base            = 15988
base_comparison_not_active     =  1571
comparison_only_vs_base        =  4719
                                -----
one-sided total                = 22295
```

Interpretive boundary:

```text
overlay additions vs base      = 20707  (92.87733%)
base-present absences/changes  =  1588  ( 7.12267%)
```

P5-T05 showed sparse source-local replacement evidence and concentrated addition-relative-base
geography, routing P5-T06.

## P5-T06 validated result — 2026-08-28

Classical repository checks reported passed:

```text
python -m pip install -e ".[dev]"
pytest --basetemp="$env:TEMP\OctoGameDB_pytest"
python -m ruff check src tests
python -m compileall -q src tests
```

The autonomous Level-2 validator selected the exact SHA-matching migration-13 DB at the legacy
project-relative path:

```text
data/octogamedb.sqlite3
```

This remains a validation-layout note only and does not supersede the D-029 normal canonical path
`data/generated/octogamedb.sqlite3`.

Level-2 acceptance passed:

- exact canonical SHA-256;
- migration 13;
- SQLite integrity and foreign keys;
- exact P5-T05 four-pattern regression;
- deterministic repeated P5-T06 summary;
- complete source/kind/parent/zone reconciliation;
- bounded real provenance examples for both base-parent classes and all parent/zone overlay classes;
- snapshot byte identity;
- canonical DB byte identity.

Measured base-parent split:

```text
parent_absent_from_base              =  7984  (38.55701%)
spawn_added_to_base_present_parent   = 12723  (61.44299%)
                                        -----
included additions                   = 20707
```

By P5-T05 addition pattern:

```text
active_only_vs_base
  parent_absent_from_base            =  5904
  spawn_added_to_base_present_parent = 10084
  total                              = 15988

comparison_only_vs_base
  parent_absent_from_base            =  2080
  spawn_added_to_base_present_parent =  2639
  total                              =  4719
```

By subject kind:

```text
creature_spawn
  parent_absent_from_base            = 4743
  spawn_added_to_base_present_parent = 8243

gameobject_spawn
  parent_absent_from_base            = 3241
  spawn_added_to_base_present_parent = 4480
```

Parent-level overlay coverage:

```text
active additions only       = 1375 parents /  8844 members
comparison additions only   =  158 parents /   946 members
both overlays add           = 1023 parents / 10917 members
```

Zone/map-level overlay coverage:

```text
active additions only       = 25 zone/map groups /  9438 members
comparison additions only   =  5 zone/map groups /   509 members
both overlays add           = 33 zone/map groups / 10760 members
```

The four dominant zones explain 75.370648% of all 20,707 additions:

```text
rank  zone                     active  comparison  parent-absent  base-parent-extra  total
1     Stonetalon Mountains      3780      1365          1952           3193          5145
2     Grim Reaches              5062         0          1915           3147          5062
3     Northwind                 2872         0          1584           1288          2872
4     Blackrock Depths          1403      1125             6           2522          2528
                                                                      -----
top four total                                                               15607
```

Interpretation:

- the global population is not predominantly explained by parents absent from base;
- extra spawn membership under base-present parents is the larger class (61.44%);
- more than half the members fall in same-parent and same-zone grouping contexts where both
  overlays contribute distinct additions;
- concentration is primarily geographic rather than dominated by a tiny handful of parent templates;
- Blackrock Depths is an especially strong base-present-parent case (2522 / 2528 additions);
- Grim Reaches and Northwind provide large active-only concentrated source-family cases.

P5-T06 therefore does not justify a source-authority change. D-025/D-026 remain unchanged and
`pfquest-octo` remains comparison evidence only.

## Active task

### P5-T07 — concentrated spawn-addition raw-source semantic audit

**Status: READY_FOR_IMPLEMENTATION.**

Task contract:

```text
docs/project/tasks/P5-T07.md
```

Routing basis:

- top four zones account for 15,607 / 20,707 additions (75.37%);
- `spawn_added_to_base_present_parent` is the larger global class;
- 10,917 members are under parents where both overlays add distinct members;
- 10,760 members are in zone/map groups where both overlays add distinct members;
- the four dominant zones jointly cover ordinary/base-present, custom/active-only, both-overlay and
  parent-absent patterns.

P5-T07 must inspect the exact raw source semantics behind those concrete concentrations before any
broader source-authority or spawn-membership policy review.

No canonical mutation, migration, source promotion or spawn identity merge is authorized.

## Next action

Implement P5-T07 from `docs/project/tasks/P5-T07.md`.

The next conversation must treat this closeout as stacked on the locally validated P5-T06
implementation if GitHub `main` has not yet been pushed forward. It must verify the actual current
GitHub head before editing.
