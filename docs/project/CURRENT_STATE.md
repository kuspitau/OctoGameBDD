# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must still verify the actual current head before
editing.

## Integration note for this closeout handoff

P3-T04 was implemented against GitHub `main` commit:

```text
7aba4585dc29c3a9a5bbfeb8f5f09e3b190f124b
```

At P3-T04 closeout packaging time, GitHub `main` still points to that P3-T03 closeout commit. The
human has already applied the P3-T04 implementation delta plus the subsequent test/lint correction
deltas locally, completed the prescribed disposable full-data validation, advanced the canonical DB,
and completed the final tracked quality gates successfully.

Therefore this closeout delta is **stacked on that locally applied and validated P3-T04 working tree**.
It must not be extracted onto a fresh checkout of `7aba458...` without first applying the preceding
P3-T04 implementation/test-fix handoffs. The intended serial workflow is to apply this closeout to the
validated local tree, review the combined diff, then commit/push the complete P3-T04 implementation +
closeout to `main`.

## Recently completed

### P3-T03 — quest restrictions and dependency graph

**Status: VALIDATED**

P3-T03 established migration 8 for quest/minimum level, race/class masks, prerequisite sets,
follow-ups and close/exclusive sets. Its canonical closeout produced `3,533` prerequisite sets,
`3,716` prerequisite members, `303` close sets and `1,095` close-set members with clean
same-revision idempotence and FK/integrity checks.

Detailed record: `docs/project/tasks/P3-T03.md`.

### P3-T04 — quest objectives and objective geography

**Status: VALIDATED**

P3-T04 was fully validated on 2026-08-25 against the configured real pfQuest and pfQuest-turtle
sources, first on a disposable copy and then on the canonical local database.

Validated P3-T04 source revisions:

```text
base pfQuest objectives
sha256:2acc862f732bc512482eaaec0b86a2a5d67c548d8cc50f7b6128f5ffba27a58c

pfQuest-turtle effective objectives
sha256:8e570cb4303e73fae03d6b4240b0122f0000f35dd441aca686feed039641f90f
```

The canonical evolution applied migration 9 and produced:

```text
quests                         6498
quest_objective_sets           4224
quest_creature_objectives      1484
quest_gameobject_objectives    99
quest_item_objectives          5064
quest_item_use_objectives      226
quest_area_trigger_objectives  50
quest_zone_objectives          0
area_triggers                  496
area_trigger_locations         558
item_use_target_sets           189
item_use_creature_targets      113
item_use_gameobject_targets    220
import_batches                 20
observation_groups             1182571
canonical_selections           1172691
source_observations            2083312
```

First canonical P3-T04 reconciliation:

```text
status                                  succeeded
error_count                             0
rows_read / rows_accepted               13014 / 13014
rows_skipped                            0
rows_inserted                           12723
rows_updated                            0
canonical_objective_rows_deleted        0
changed_effective_objective_quest_count 1811
changed_effective_itemreq_count         30
changed_effective_area_trigger_count    252
warning_count                           219
duplicate_source_objective_member_count 0
protected_canonical_rows_retained       0
```

The 219 warnings are explicit unresolved source evidence rather than validation failures:

```text
missing_quest_identity      188
missing_creature_identity    30
missing_item_identity         1
```

By subtype/context the validator reported:

```text
set        188
creature    28
U            2
I            1
```

No target identities were fabricated to suppress these diagnostics.

Second same-revision reconciliation:

```text
status                            succeeded
error_count                       0
rows_inserted                     0
rows_updated                      0
canonical_objective_rows_deleted  0
warning_count                     219
```

`rows_read`/`rows_accepted` increase to `13096` on the second pass because newly materialized managed
support identities (`area_triggers` / item-use target sets) join the reconciliation candidate universe;
the canonical state itself remains unchanged.

Structural checks passed:

```text
PRAGMA foreign_key_check   ok
PRAGMA integrity_check     ok
```

Representative real-data query checks passed for:

- quest `7`: creature objective `6` (`Kobold Vermin`) with derived Elwynn Forest spawn geography;
- quest `28`: game-object objective `177788` (`Shrine of Remulos`) in Moonglade;
- quest `6`: item objective `182` (`Garrick's Head`);
- quest `28`: item-use objective `15877` (`Shrine Bauble`) resolving through spell `19719` to
  game-object `177788` and its geography;
- quest `25`: area-trigger objective `2926` with source-backed coordinates in Ashenvale and
  Stonetalon Mountains.

No selected real-data `obj.Z` member exists in the validated source revisions (`Z = 0`); the schema,
parser, reconciliation and fixture tests still cover direct zone-objective support.

Final tracked quality gate after the last lint-only correction:

```text
python -m ruff check .
All checks passed!

pytest --basetemp=.pytest_tmp
97 passed in 5.31s
```

The compileall gate was also run with no reported error.

Detailed implementation/validation record: `docs/project/tasks/P3-T04.md`.

## Canonical local database

The canonical cumulative database is:

```text
data/generated/octogamedb.sqlite3
```

It is now **validated through P3-T04**, including migration:

```text
0009_quest_objectives.sql
```

The immediately preceding P3-T03 canonical state was backed up before mutation at:

```text
data/generated/octogamedb_bak.sqlite3
```

under D-029 / `docs/project/CANONICAL_DB.md`.

Future tasks must continue to replace that one-step backup immediately before any new canonical DB
mutation.

## Active task

### P3-T05 — quest item requirements and rewards

**Status: READY_FOR_IMPLEMENTATION**

Detailed task:

```text
docs/project/tasks/P3-T05.md
```

The next bounded P3 slice is source-backed quest/item quantity semantics and reward semantics:

- required item/source-item requirements and their actual quantities where the reviewed source carries
  them;
- guaranteed item rewards;
- choice item rewards;
- preservation of guaranteed-vs-choice distinction and source quantities;
- Turtle effective-view/reconciliation semantics and provenance for only that bounded fact family.

P3-T05 must not retroactively invent quantities for P3-T04 `obj.I` membership merely because a source
contains some related count field. It must map counts to the precise reviewed source relation that
carries them.

Item-started quest acquisition (`start.I`), arbitrary quest text and broader repeatability/event/
profession restrictions remain later bounded work unless primary-source inspection proves an
inseparable dependency.

## Routing guard

The next coding conversation should take P3-T05 from `docs/project/tasks/P3-T05.md` **only after** the
human has committed and pushed the combined P3-T04 implementation + this closeout so GitHub `main`
actually contains the validated P3-T04 state. If `main` still points to `7aba458...`, stop and reconcile
the unpushed local handoff instead of implementing P3-T05 against stale project state.
