# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must verify the actual current head before editing.

## Integration baseline for this handoff

The visible GitHub `main` head at P5-T03 closeout time is:

```text
0bea70a43ba57c0dd3b0964da52be6c8cb3e3456
```

Commit title:

```text
Validate P5-T02 unselected audit and route P5-T03
```

The P5-T03 implementation delta was applied locally on top of that GitHub baseline and completed all
prescribed classic and Level-2/full-data validation.

This closeout delta is therefore intentionally **stacked on the already-applied, not-yet-pushed
P5-T03 implementation state**.

Do not apply this closeout delta to a bare checkout of GitHub commit
`0bea70a43ba57c0dd3b0964da52be6c8cb3e3456` without first applying the P5-T03 implementation delta.

## Validated cumulative state

P0 through **P5-T03** are `VALIDATED`.

The canonical database schema remains:

```text
P4-T04 / migration 13 / 0013_recipe_acquisition_sources.sql
```

P5-T01 through P5-T03 are read-only audit work and introduced no migration.

Current validated canonical SHA-256 remains:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The D-029 one-step rollback remains the exact migration-12 canonical:

```text
sha256:6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261
```

The local Level-2 validator accepted the canonical DB through an explicit/discovered `--db` path and
proved it byte-identical before/after validation. No tracked project-path decision is changed by the
user's local data-directory rearrangement.

## P5-T03 closeout

### Status

`VALIDATED`

Validation evidence:

```text
P5-T03_validation_20260827_225925.json
status = LEVEL_2_VALIDATION_PASSED
```

Classic local validation also passed before Level-2:

```text
pytest                         = 173 passed
ruff check src tests           = passed
compileall -q src tests        = passed
editable dev install           = passed
```

The Level-2 validator reproduced the resolution baseline exactly:

```text
observation_group_count             = 1307532
selected_group_count                = 1297652
unselected_group_count              = 9880
empty_observation_group_count       = 0
conflict_group_count                = 64512
resolved_conflict_group_count       = 64512
unresolved_conflict_group_count     = 0
unselected_single_value_group_count = 9880
```

It also preserved the P5-T02 comparison-source baseline:

```text
source_key              = pfquest-octo
source_revision         = sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db
comparison groups       = 410837
comparison observations = 411009
unselected groups       = 9880
```

Measured P5-T03 comparison totals:

```text
audited records               = 450659
compared subjects             = 192983
active selected observations  = 440779

same_value                    = 394970  (87.64%)
different_value               =   2759  ( 0.61%)
active_only                   =  32078  ( 7.12%)
comparison_only               =  12600  ( 2.80%)
not_directly_comparable       =   8252  ( 1.83%)
```

The dominant `different_value` family is `spawn_set`:

```text
creature spawn_set differing parents    = 1062
gameobject spawn_set differing parents  = 1508
total differing spawn_set parents       = 2570
share of all different_value records    = 93.15%
```

Unique spawn-membership comparison:

```text
creature
  shared members          = 85551
  active-only members     = 10255
  comparison-only members =  3928

gameobject
  shared members          = 59896
  active-only members     =  5750
  comparison-only members =  2362

total unique membership differences = 22295
```

Shared-spawn position evidence shows:

```text
creature_spawn position different_value   = 0
gameobject_spawn position different_value = 0
```

Shared-spawn `respawn_seconds` differences are small:

```text
creature_spawn respawn_seconds different_value   = 2
gameobject_spawn respawn_seconds different_value = 19
```

Template presence is also narrow:

```text
creature active-only world_presence subjects = 17
gameobject active-only world_presence subjects = 0
```

The large `not_directly_comparable` bucket is mostly template names omitted by the delta source:

```text
creature name not_directly_comparable   = 4604
gameobject name not_directly_comparable = 3073
total name NDC                          = 7677 / 8252 (93.03%)
```

### Closeout decision

P5-T03 found **no basis for a general `pfquest-octo` authority promotion or D-026 change**.

The comparison source overwhelmingly agrees where directly comparable, while the meaningful remainder
is concentrated in complete spawn-set membership differences rather than changed coordinates for
shared spawn identities.

The next bounded task is therefore not a selection-policy rewrite. It is a read-only characterization
of the 22,295 unique active-only/comparison-only spawn memberships so the project can distinguish:

- genuine additions/removals;
- likely coordinate-relocation candidates represented as one removed + one added spawn identity;
- zone/template-localized source differences;
- differences associated with base versus Turtle effective active selections.

Detailed P5-T03 implementation and closeout evidence is recorded in:

```text
docs/project/tasks/P5-T03.md
```

## Active task

### P5-T04 — pfquest-octo spawn membership divergence characterization

**Status: READY_FOR_IMPLEMENTATION.**

Task contract:

```text
docs/project/tasks/P5-T04.md
```

P5-T04 remains read-only and bounded to the P1 creature/gameobject spawn topology exposed by P5-T03.
It must not merge spawn identities, mutate canonical data, promote `pfquest-octo`, or change D-026.

Its primary job is to turn the 22,295 unique membership differences into deterministic aggregate and
drill-down evidence, including cautious relocation-candidate analysis within the same template/zone.

## Next action

Apply this P5-T03 closeout delta **after** the already-applied P5-T03 implementation delta, review the
combined Git diff, then commit and push both together to `main`.

After that push, the next conversation should read the new GitHub `main`, confirm:

```text
P5-T03 = VALIDATED
P5-T04 = READY_FOR_IMPLEMENTATION
```

and implement P5-T04 from its task document.

## Next-conversation guard

Until the human commits and pushes the stacked P5-T03 implementation + closeout state, a fresh
conversation must not assume GitHub `main` already contains the validated P5-T03 implementation.

Expected durable state after push:

```text
P5-T03 = VALIDATED
P5-T04 = READY_FOR_IMPLEMENTATION
canonical DB schema = migration 13
canonical DB SHA-256 = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
D-026 = unchanged
```
