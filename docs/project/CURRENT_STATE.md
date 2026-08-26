# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must verify the actual current head before editing.

## Integration baseline for this handoff

The visible GitHub `main` head at P5-T01 closeout time is:

```text
1ecba48260046ee2c4cf112cc0a8374b26605506
```

Commit title:

```text
Validate P4-T04 recipe acquisition sources and canonical migration 13
```

The P5-T01 implementation delta was applied locally on top of that GitHub baseline and then passed
all prescribed Level-1/Level-2 validation. This closeout delta is therefore intentionally **stacked on
the already-applied, not-yet-pushed P5-T01 implementation state**.

Do not apply this closeout delta to a bare checkout of GitHub commit
`1ecba48260046ee2c4cf112cc0a8374b26605506` without first applying the P5-T01 implementation delta.

## Validated cumulative state

P0 through **P5-T01** are `VALIDATED`.

The cumulative local canonical database remains:

```text
data/generated/octogamedb.sqlite3
```

validated through:

```text
P4-T04 / migration 13 / 0013_recipe_acquisition_sources.sql
```

P5-T01 is read-only and introduced no migration.

Current validated canonical SHA-256 remains:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The D-029 one-step rollback remains the exact migration-12 canonical:

```text
data/generated/octogamedb_bak.sqlite3
sha256:6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261
```

## P5-T01 closeout

### Status

`VALIDATED`

P5-T01 established the first measured, read-only resolution baseline over the cumulative P1-P4
provenance graph.

Classical local checks reported successful:

```text
python -m pip install -e ".[dev]"
pytest --basetemp=.pytest_tmp
python -m ruff check src tests
python -m compileall -q src tests
```

The autonomous full-data validation then passed on 2026-08-27 against an isolated byte-for-byte
snapshot of the canonical migration-13 DB.

Measured real baseline:

```text
observation_group_count             = 1307532
selected_group_count                = 1297652
unselected_group_count              = 9880
empty_observation_group_count       = 0
conflict_group_count                = 64512
resolved_conflict_group_count       = 64512
unresolved_conflict_group_count     = 0
unselected_single_value_group_count = 9880
selection_policy_count              = 24
selected_source_count               = 7
fact_family_count                   = 82
```

All resolution aggregation invariants passed.

The canonical DB SHA-256 matched the validated migration-13 baseline before and after validation, and
the isolated real-data snapshot also remained byte-identical before and after `resolution`. P5-T01
therefore caused no canonical DB mutation.

Detailed closeout evidence is recorded in:

```text
docs/project/tasks/P5-T01.md
```

## Observed gap that routes the next task

P5-T01 found **zero unresolved conflicts**. The immediate P5 problem is therefore not conflict winner
selection.

Instead, all **9,880 unselected observation groups contain exactly one distinct value**. Their family
distribution is concentrated in world/spawn facts:

```text
creature.faction                         = 4
creature.level_max                       = 1
creature.level_min                       = 1
creature.name                            = 1
creature.spawn_set                       = 1
creature.world_presence                  = 1

creature_spawn.position                  = 2748
creature_spawn.respawn_seconds           = 2748

gameobject.faction                       = 5
gameobject.name                          = 2
gameobject.spawn_set                     = 2
gameobject.world_presence                = 2

gameobject_spawn.position                = 2182
gameobject_spawn.respawn_seconds         = 2182
```

These counts sum exactly to `9880`.

This is an audit signal only. It does not authorize automatic canonical selection.

## Active task

### P5-T02 — unselected single-value provenance audit

**Status: READY_FOR_IMPLEMENTATION.**

The next bounded task is to explain and classify the 9,880 unselected single-value groups before any
selection policy is changed.

Task contract:

```text
docs/project/tasks/P5-T02.md
```

P5-T02 remains read-only. It must identify which source/revision/policy gaps produce the unselected
groups, preserve drill-down provenance, and distinguish expected non-canonical evidence from genuine
missing-selection candidates. It must not automatically choose winners.

## Next action

Commit and push the already-applied P5-T01 implementation delta together with this P5-T01 closeout
delta.

After that push, the next conversation should read the new GitHub `main`, confirm P5-T01 is present
and `VALIDATED`, then implement P5-T02 from its task document.

## Next-conversation guard

Until the human commits and pushes the stacked P5-T01 implementation + closeout state, a fresh
conversation must **not** assume GitHub `main` already contains P5-T01.

Once pushed, expected durable state is:

```text
P5-T01 = VALIDATED
P5-T02 = READY_FOR_IMPLEMENTATION
canonical DB schema = migration 13
canonical DB SHA-256 = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```
