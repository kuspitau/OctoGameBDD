# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must still verify the actual current head before
editing.

## Integration note for this closeout handoff

P3-T03 was implemented against GitHub `main` commit:

```text
6b105bd072a19fd8b9b1d5f4c1f7b635237f7a49
```

At closeout packaging time, GitHub `main` still points to that P3-T02 commit. The human has already
applied the preceding P3-T03 implementation delta locally and completed its full local validation and
canonical-DB evolution successfully.

Therefore this closeout delta is **stacked on that locally applied P3-T03 implementation delta**. It
must not be extracted onto a fresh checkout of `6b105bd...` without first applying the preceding
P3-T03 implementation handoff. The intended serial workflow is to apply this closeout to the already
validated local tree, then commit/push the combined P3-T03 implementation + closeout to `main`.

## Recently completed

### P3-T01 — first quest identity/endpoints vertical slice

**Status: VALIDATED**

P3-T01 established canonical native-ID quest identity plus creature/game-object giver and finisher
relations, with missing P1 endpoint targets preserved as unresolved provenance rather than fabricated
identities.

The later clean cumulative rebuild used during P3-T02 closure independently observed the base quest
revision:

```text
sha256:667303b5507015b4039508e6a8f8afc0f6c086f285d5dc56afd0addb79cbe8e3
```

and `4,433` accepted base quests.

Detailed record: `docs/project/tasks/P3-T01.md`.

### P3-T02 — pfQuest-turtle effective quest identity/endpoint reconciliation

**Status: VALIDATED**

P3-T02 reconciled the P3-T01 identity/endpoints fact family against the active Turtle-composed quest
view. Its clean cumulative closeout produced `6,498` quests, `12,145` creature endpoints and `545`
game-object endpoints with clean FK/integrity checks and same-revision idempotence.

Validated quest revisions carried into P3-T03:

```text
base pfQuest quests
sha256:667303b5507015b4039508e6a8f8afc0f6c086f285d5dc56afd0addb79cbe8e3

pfQuest-turtle quests
sha256:234f8062f8006d5dc17c526b81772cf50f8591170781ae5af8b72a86b237d25a
```

Detailed record: `docs/project/tasks/P3-T02.md`.

### P3-T03 — quest restrictions and dependency graph

**Status: VALIDATED**

The human completed the prescribed full local validation on 2026-08-24. The validation-copy wrapper
reported:

```text
[PASS] FULL LOCAL P3-T03 VALIDATION SUCCEEDED
[PASS] Canonical database remained unchanged.
```

The canonical DB was then backed up and deliberately evolved through P3-T03. Migration 8 was applied
and the real configured sources produced:

```text
base pfQuest progression revision
sha256:667303b5507015b4039508e6a8f8afc0f6c086f285d5dc56afd0addb79cbe8e3

pfQuest-turtle progression revision
sha256:234f8062f8006d5dc17c526b81772cf50f8591170781ae5af8b72a86b237d25a

first pass
status                                  succeeded
error_count                             0
rows_read / rows_accepted               12120 / 12120
rows_skipped                            0
rows_inserted                           8647
rows_updated                            6494
canonical_progression_rows_deleted      0
changed_effective_progression_count     5258
warning_count                           1
unresolved_progression_relation_count   0
duplicate_source_member_count           0
prerequisite_cycle_count                0
close_group_mismatch_count              0
close_self_missing_count                0
self_prerequisite_count                 1

second same-revision pass
rows_inserted                           0
rows_updated                            0
canonical_progression_rows_deleted      0
error_count                             0
warning_count                           1
```

The single warning is the explicitly surfaced self-prerequisite diagnostic. No unresolved target,
duplicate-member, prerequisite-cycle or close-set mismatch diagnostic was reported. The source oddity
remains audit evidence; it was not silently normalized away.

Structural checks passed:

```text
PRAGMA foreign_key_check   ok
PRAGMA integrity_check     ok
```

Representative real-data checks also passed:

- quest `2` (`Sharptalon's Claw`) selected Turtle progression provenance with `race_mask = 434`;
- quests `6`, `18`, and `783` formed the validator's three-node prerequisite-chain representative;
- quest `235` (`The Ashenvale Hunt`) exposed a complete three-member close set containing quest IDs
  `235`, `742`, and `6382` with Turtle selected provenance.

Detailed implementation/validation record: `docs/project/tasks/P3-T03.md`.

## Canonical local database

The canonical cumulative database remains:

```text
data/generated/octogamedb.sqlite3
```

It is now **validated through P3-T03**. P3-T03 validator-reported canonical counts after the successful
evolution are:

```text
quests                          6498
quest_prerequisite_sets         3533
quest_prerequisite_set_members  3716
quest_close_sets                303
quest_close_set_members         1095
import_batches                  16
observation_groups              1167121
canonical_selections            1157241
source_observations             2059171
```

Migration `0008_quest_progression.sql` is applied. The prior P3-T02 canonical state was backed up under
the D-029 lifecycle before mutation. Future tasks must continue to create/replace
`data/generated/octogamedb_bak.sqlite3` before mutating the canonical DB.

See `docs/project/CANONICAL_DB.md`.

## Active task

### P3-T04 — quest objectives and objective geography

**Status: READY_FOR_IMPLEMENTATION**

Detailed task:

```text
docs/project/tasks/P3-T04.md
```

The bounded target is the pfQuest objective family and the geography that can be derived from it:
`obj.U`, `obj.O`, `obj.I`, `obj.IR`, `obj.A`, `obj.Z`, plus the supporting `quests-itemreq` source
contract where it is required to interpret `IR` safely.

P3-T04 must inspect the pinned primary sources and Turtle composition before schema/materialization
choices. It must not infer objective quantities that the exported pfQuest `obj` lists do not carry.
Required-item quantities, guaranteed/choice rewards, and item-started quest acquisition remain outside
this task unless source inspection proves a narrow dependency that cannot be separated safely.

## Routing guard

The next coding conversation should take P3-T04 from `docs/project/tasks/P3-T04.md` after verifying
that the combined P3-T03 implementation + closeout is present on its actual base revision. Do not
route back to P3-T03 unless validation evidence is later found invalid or the source revisions change.
