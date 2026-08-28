# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must verify the actual current head before editing.

## Integration baseline for this handoff

P5-T07 is implemented as a delta against GitHub `main` commit:

```text
77d894b27d0f1d62e93ac295d0ef79e8e86e2854
```

Commit title:

```text
Validate P5-T06 overlay addition audit and route P5-T07
```

That commit contains the human-validated P5-T06 closeout. The human then applied the P5-T07
implementation plus the provenance-query and bulk-loading performance hotfixes locally and completed
all required validation successfully on 2026-08-28.

This closeout/routing delta is intentionally stacked on that validated local P5-T07 integration
state. GitHub `main` still points at the P5-T06 closeout while this package is being prepared; do not
apply this closeout to a bare P5-T06 checkout without the preceding P5-T07 implementation/hotfixes.

## Validated cumulative state

P0 through **P5-T07** are `VALIDATED`.

The canonical database schema remains:

```text
P4-T04 / migration 13 / 0013_recipe_acquisition_sources.sql
```

P5-T01 through P5-T07 are read-only audit work and introduce no migration.

Current validated canonical SHA-256 remains:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The D-029 one-step rollback remains the exact migration-12 canonical:

```text
sha256:6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261
```

D-025 and D-026 are unchanged. `pfquest-octo` remains comparison evidence only.

## P5-T07 validated source revisions

```text
pfquest base
sha256:5087d2d0a5b1c2706b7fc7ccb5ffd447c91aa24d91a23f102f2c7ac1d7440147

pfquest-turtle active
sha256:7fd719cac7a7a26e80c6865fa62b6100ccfa2301dabe3b2a399c0f1551372d8c

pfquest-octo comparison
sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db
```

The successful Level-2 run reproduced all three revisions exactly. Future raw-source follow-ups must
continue to fail closed if those configured inputs drift.

## P5-T03/P5-T04 validated regression context

P5-T03 comparison baseline:

```text
audited records               = 450659
same_value                    = 394970
different_value               =   2759
active_only                   =  32078
comparison_only               =  12600
not_directly_comparable       =   8252
```

P5-T04 unique spawn-membership baseline:

```text
shared total                   = 145447
active-only total              =  16005
comparison-only total          =   6290
total unique one-sided members =  22295
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

## P5-T06 validated result — 2026-08-28

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

P5-T06 did not justify a source-authority change. D-025/D-026 remain unchanged and `pfquest-octo`
remains comparison evidence only.

## P5-T07 validated result — 2026-08-28

Classical local checks passed before Level-2:

```text
python -m pip install -e ".[dev]"
pytest --basetemp="$env:TEMP\OctoGameDB_pytest"
python -m ruff check src tests
python -m compileall -q src tests
```

The final Level-2 run passed against the exact migration-13 canonical SHA and exact three raw-source
revisions. Evidence:

```text
data/generated/validation_logs/P5-T07_validation_20260828_125654.json
```

Core regression totals:

```text
P5-T06 included additions = 20707
P5-T07 four-zone total     = 15607

Stonetalon Mountains       = 5145
Grim Reaches               = 5062
Northwind                  = 2872
Blackrock Depths           = 2528
```

Four-zone raw semantic split:

```text
zone                     parent-absent  base-parent-extra  active  comparison  total
Stonetalon Mountains          1952           3193          3780      1365      5145
Grim Reaches                  1915           3147          5062         0      5062
Northwind                     1584           1288          2872         0      2872
Blackrock Depths                 6           2522          1403      1125      2528
```

Descriptive signals:

- Stonetalon Mountains: 62.060253% base-present extra membership; both source families contribute.
- Grim Reaches: 62.169103% base-present extra membership; active source family only in this slice.
- Northwind: 55.153203% parent-absent membership; active-only custom/overlay-content candidate.
- Blackrock Depths: 99.762658% base-present extra membership; both source families contribute.

Cross-overlay raw replacement evidence for the audited parent population:

```text
parents where both overlays add                         =  747
parents where both overlays whole-entry replace         = 1085
those with different replacement payloads               = 1085
shared exact added members in the four routed zones     =    3
```

This is the routing signal: common parent replacement is widespread, but exact added membership is
almost entirely source-specific. P5-T07 therefore does **not** justify treating Turtle and
pfquest-octo as interchangeable enrichment sources or promoting either source globally.

Duplicate diagnostics remained bounded and deterministic:

```text
base raw duplicate rows       =  2
active overlay duplicate rows = 45
comparison duplicate rows     = 45
```

Duplicates collapse by the established deterministic `spawn_key` rule. No new identity or
coordinate-normalization rule was introduced.

Level-2 additionally passed:

- exact scope/read-only declaration;
- SQLite integrity and foreign keys on an isolated snapshot;
- exact source revisions;
- all zone/member/parent/source/transformation aggregate reconciliations;
- persisted `spawn_set` equality for bounded raw-effective parent examples;
- deterministic repeated JSON;
- real examples for every contributing raw transformation class;
- snapshot byte identity after the audit;
- canonical DB byte identity before/after.

P5-T07 required two implementation corrections discovered by real-data validation:

- provenance lookup now follows `observation_import_batches` rather than a nonexistent direct
  `source_observations.import_batch_id` column;
- persisted spawn-set provenance is bulk-loaded once per source side instead of issuing an N+1 query
  per parent.

Both corrections preserve the same audit semantics and introduce no migration or canonical write.

## Active task

### P5-T08 — shared-parent overlay replacement semantic divergence audit

**Status: READY_FOR_IMPLEMENTATION.**

Task contract:

```text
docs/project/tasks/P5-T08.md
```

P5-T08 is a bounded read-only follow-up to the 1,085 audited parents where both overlays perform a
whole-entry replacement and all 1,085 raw replacement payloads differ.

Primary question:

> When Turtle and pfquest-octo both replace the same base parent, what exact source-native semantic
> differences account for their divergent effective spawn memberships?

Required classification is exact/set-based, not proximity-based. At minimum compare base, active and
comparison effective spawn sets for each common replaced parent and classify:

- active equals comparison;
- active strict superset of comparison;
- comparison strict superset of active;
- partial overlap;
- disjoint;
- differences confined to spawn membership versus differences also present in other raw top-entry
  fields.

Stratify by parent kind, routed zone contribution, base-parent class and source-side contribution.
Retain representative source-relative file/top-entry evidence.

P5-T08 must not:

- change D-025/D-026;
- promote a source;
- mutate the canonical DB;
- merge spawn identities;
- introduce distance-threshold pairing;
- infer equivalence from geographic proximity.

The goal is to determine whether a later authority/coverage decision can be made per relation/field
and source family, or whether the source families require separate semantics.
