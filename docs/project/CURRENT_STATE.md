# Current State

This file is the permanent task router. GitHub `main` is the tracked source of truth. Every new coding
conversation must verify the actual current head before editing and must account explicitly for any
validated local delta not yet pushed.

## Integration baseline for this handoff

Visible GitHub `main` head while this closeout is prepared:

```text
eeb8d1393f7520264e155dcaa3e7717fec755087
Validate P5-T07 raw spawn semantics and route P5-T08
```

P5-T08 was implemented and corrected locally on top of that commit. The human then completed the full
P5-T08 validation loop successfully on 2026-08-28. This closeout/routing delta is therefore
**intentionally stacked on the validated local P5-T08 integration state** and must not be applied to a
bare `eeb8d139...` checkout without the preceding P5-T08 implementation/correction deltas.

The validated local stack includes the P5-T08 audit/validator/tests, the P5-T07 compatibility and Ruff
fixes discovered during full-suite validation, and the working P5-T08 local-validation BAT. Commit and
push that complete local stack together with this closeout before starting a new coding conversation.

## Validated cumulative state

P0 through **P5-T08** are `VALIDATED`.

The canonical schema remains:

```text
P4-T04 / migration 13 / 0013_recipe_acquisition_sources.sql
```

P5-T01 through P5-T08 are read-only audit work and introduce no migration.

Validated canonical SHA-256 remains:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The P5-T08 human run selected the project-local `data/octogamedb.sqlite3` compatibility location
because `data/generated/octogamedb.sqlite3` was absent on that machine, and verified the exact hash
above. This does not supersede D-029's canonical lifecycle/path contract; no architecture decision is
changed by P5-T08.

D-025 and D-026 remain unchanged. `pfquest-octo` remains comparison evidence only.

## Exact raw-source revisions retained by P5-T08

```text
pfquest base
sha256:5087d2d0a5b1c2706b7fc7ccb5ffd447c91aa24d91a23f102f2c7ac1d7440147

pfquest-turtle active
sha256:7fd719cac7a7a26e80c6865fa62b6100ccfa2301dabe3b2a399c0f1551372d8c

pfquest-octo comparison
sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db
```

Future work that reuses this raw-source evidence must fail closed if the configured inputs drift.

## P5 regression context

### P5-T03 / P5-T04

```text
P5-T03 audited records               = 450659
same_value                           = 394970
different_value                      =   2759
active_only                          =  32078
comparison_only                      =  12600
not_directly_comparable              =   8252

P5-T04 shared spawn members          = 145447
active-only spawn members            =  16005
comparison-only spawn members        =   6290
one-sided spawn members              =  22295
```

P5-T04 rejected a global automatic relocation/identity explanation and did not justify spawn-key
pairing or source-authority changes.

### P5-T05

```text
base_active_not_comparison     =    17
active_only_vs_base            = 15988
base_comparison_not_active     =  1571
comparison_only_vs_base        =  4719
                                -----
one-sided total                = 22295

overlay additions vs base     = 20707  (92.87733%)
base-present absences/changes  =  1588  ( 7.12267%)
```

### P5-T06

```text
parent_absent_from_base              =  7984
spawn_added_to_base_present_parent   = 12723
included additions                   = 20707
```

The four routed concentration zones contain 15,607 / 20,707 additions:

```text
Stonetalon Mountains = 5145
Grim Reaches         = 5062
Northwind            = 2872
Blackrock Depths     = 2528
```

### P5-T07

Validated raw replacement routing signal:

```text
both overlays add parents                         =  747
both whole-entry replacement parents              = 1085
different whole-entry replacement payload parents = 1085
shared exact added members in routed zones        =    3
```

This established that common top-entry replacement is widespread while exact added membership is
almost entirely source-specific.

## P5-T08 validated result — 2026-08-28

Human evidence:

```text
data/generated/validation_logs/P5-T08_validation_20260828_171220.json
```

Final local validation additionally recorded:

```text
222 pytest tests passed
Ruff passed
compileall passed
P5-T08 semantic validator passed
COMPLETE LOCAL VALIDATION PASSED
```

The fixed population is exactly 1,085 base-present parents where both overlays whole-entry replace the
same parent and both raw replacement payloads differ.

Parent kind split:

```text
creature   = 439
gameobject = 646
             ----
total      = 1085
```

Exact active/comparison effective `spawn_set` relations:

```text
active_equals_comparison      =   0  ( 0.00%)
active_strict_superset         = 472  (43.50%)
comparison_strict_superset     =   0  ( 0.00%)
partial_overlap                = 164  (15.12%)
disjoint                       = 449  (41.38%)
                                ----
total                          = 1085
```

Raw replacement semantic difference classes:

```text
spawn_membership_only          = 1084  (99.908%)
spawn_plus_other_fields        =    1  ( 0.092%)
localization_name_only         =    0
other_top_entry_fields_only    =    0
unsupported_unclassified       =    0
```

Routed contribution classes:

```text
active_only   = 603
both_sources  = 482
                ----
total         = 1085
```

All 1,085 parents are `spawn_added_to_base_present_parent`. The audit emitted 25 bounded
representative examples and classified every fixed parent exactly once.

Bulk provenance behavior is validated:

```text
base membership bulk loads             = 1
active persisted spawn_set bulk loads   = 1
comparison persisted spawn_set loads    = 1
per-parent provenance query loop        = false
```

Canonical SHA-256 is byte-identical before and after the read-only validation.

### P5 conclusion

P5-T08 resolves the current P5 world-source conflict question sufficiently to stop iterating on the
same spawn divergence without a new consumer-driven requirement:

- the disagreement is overwhelmingly field-local to complete `spawn_set` membership;
- the two effective source families are never equal on the fixed common-replacement population;
- active is a strict superset in 43.50%, but 56.50% of parents are partial-overlap or disjoint;
- comparison is never a strict superset in this population, but partial/disjoint classes still retain
  comparison-only members and therefore do not justify discarding comparison evidence;
- the single `spawn_plus_other_fields` outlier is isolated and does not justify a generalized
  non-spawn replacement policy;
- no evidence supports a global source merge, global source promotion, coordinate-based identity
  merge or D-025/D-026 change.

Current policy therefore remains conservative and field-specific: Turtle remains the selected managed
world view under D-026; `pfquest-octo` remains preserved comparison evidence; divergent complete spawn
sets retain separate source semantics.

P5 is complete for this bounded question. Reopen spawn-authority work only if a concrete P6/P7
consumer requires a more authoritative relation-specific choice or direct Octo evidence becomes
available.

## Active task

### P6-T01 — item template/stat source contract and bounded ingestion slice

**Status: READY_FOR_IMPLEMENTATION.**

Task contract:

```text
docs/project/tasks/P6-T01.md
```

P6-T01 begins the broader-ingestion phase with the item properties required by the project's intended
stat-aware search/exploration layer but deliberately deferred by P2.

Primary goal:

> Establish source-native, provenance-preserving semantics for filterable item template/stat facts,
> then implement a bounded representative ingestion slice without guessing a universal source
> priority.

The task must first inspect current primary sources and establish field-specific authority/coverage
before schema/import changes. It must not start with a full-world scrape/import.
