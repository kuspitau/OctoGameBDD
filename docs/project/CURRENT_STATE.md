# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must verify the actual current head before editing.

## Integration baseline for this handoff

The visible GitHub `main` head at P5-T02 closeout time is:

```text
01b6c4d62e1ebfed75cd55de637fe027b90b98b2
```

Commit title:

```text
Validate P5-T01 resolution audit and route P5-T02
```

The P5-T02 implementation delta was applied locally on top of that GitHub baseline and then completed
the prescribed local/full-data validation. This closeout delta is therefore intentionally **stacked on
the already-applied, not-yet-pushed P5-T02 implementation state**.

Do not apply this closeout delta to a bare checkout of GitHub commit
`01b6c4d62e1ebfed75cd55de637fe027b90b98b2` without first applying the P5-T02 implementation delta.

## Validated cumulative state

P0 through **P5-T02** are `VALIDATED`.

The cumulative local canonical database remains:

```text
data/generated/octogamedb.sqlite3
```

validated through:

```text
P4-T04 / migration 13 / 0013_recipe_acquisition_sources.sql
```

P5-T01 and P5-T02 are read-only audit work and introduced no migration.

Current validated canonical SHA-256 remains:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The D-029 one-step rollback remains the exact migration-12 canonical:

```text
data/generated/octogamedb_bak.sqlite3
sha256:6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261
```

## P5-T02 closeout

### Status

`VALIDATED`

P5-T02 added the deterministic read-only `unselected` aggregate/drill-down audit for observation
groups that have no canonical selection and exactly one distinct canonical JSON value.

The supplied Level-2 capture is:

```text
P5-T02_validation_20260827_013434.json
status = LEVEL_2_VALIDATION_PASSED
```

It reproduced the P5-T01 resolution baseline exactly:

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

The canonical DB remained byte-identical before/after validation:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The P5-T02 aggregate evidence gives a complete explanation for the 9,880 unselected groups:

```text
source_key      = pfquest-octo
source revisions = 1
import batches   = 1 succeeded
observations     = 9880
groups           = 9880
```

The sole observed source revision is:

```text
sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db
```

Measured subject distribution:

```text
creature                         4 subjects /    9 groups
creature_spawn                2748 subjects / 5496 groups
gameobject                        5 subjects /   11 groups
gameobject_spawn               2182 subjects / 4364 groups
                               --------------------------
total                                        9880 groups
```

The spawn groups are exactly paired `position` + `respawn_seconds` facts:

```text
creature_spawn   2748 subjects / 5496 groups
gameobject_spawn 2182 subjects / 4364 groups
```

### Closeout classification

All 9,880 groups are classified as:

```text
expected_non_canonical_evidence = 9880
effective_view_exclusion        = 0
coverage_reconciliation_gap     = 0
policy_gap                      = 0
```

Reason: P1-T04 / D-026 explicitly defines optional `pfquest-octo` P1 world observations as
comparison evidence that is persisted without automatic canonical selection. The Level-2 aggregates
show that **every** unselected single-value group is from that comparison source and no other source.
Therefore the lack of canonical selection is intentional under the already-accepted contract rather
than evidence of a missing reconciler selection or uncovered selection policy.

A particular Octo comparison subject may still differ from, or be absent from, the active Turtle
view. That is a source-content difference to audit separately; it does not change the P5-T02 reason
that its `pfquest-octo` observation is intentionally non-canonical.

P5-T02 therefore requires no selection-policy change, canonical DB change, migration, or architecture
decision.

Detailed implementation and closeout evidence is recorded in:

```text
docs/project/tasks/P5-T02.md
```

## Active task

### P5-T03 — selected-vs-comparison P1 world difference audit

**Status: READY_FOR_IMPLEMENTATION.**

P5-T02 removed the apparent resolution gap: the only unselected single-value evidence is the optional
`pfquest-octo` comparison source already governed by D-026.

The next bounded task is therefore to measure what that comparison source actually differs on, without
changing selection behavior.

Task contract:

```text
docs/project/tasks/P5-T03.md
```

P5-T03 remains read-only. It should provide deterministic aggregate and drill-down comparison between
`pfquest-octo` P1 creature/gameobject/spawn evidence and the active selected/effective P1 world view,
so later work can decide from evidence whether any Octo-specific difference deserves a separate
policy/source task. It must not automatically promote comparison evidence.

## Next action

Apply this P5-T02 closeout delta **after** the already-applied P5-T02 implementation delta, review the
combined Git diff, then commit and push both together to `main`.

After that push, the next conversation should read the new GitHub `main`, confirm P5-T02 is present and
`VALIDATED`, then implement P5-T03 from its task document.

## Next-conversation guard

Until the human commits and pushes the stacked P5-T02 implementation + closeout state, a fresh
conversation must **not** assume GitHub `main` already contains P5-T02 or P5-T03 routing.

Once pushed, expected durable state is:

```text
P5-T02 = VALIDATED
P5-T03 = READY_FOR_IMPLEMENTATION
canonical DB schema = migration 13
canonical DB SHA-256 = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```
