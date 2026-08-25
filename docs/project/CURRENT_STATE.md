# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must still verify the actual current head before
editing.

## GitHub baseline

The P3-T05 source investigation in this handoff was performed against GitHub `main` commit:

```text
56658585524b0a3a82083d24ac63105a0efb24da
```

That commit contains the validated P3-T04 implementation and closeout, so the previous P3-T04
stacked-handoff warning is no longer active.

## Validated cumulative state

P0 through P3-T04 are `VALIDATED`.

The canonical cumulative local database remains:

```text
data/generated/octogamedb.sqlite3
```

It is validated through migration:

```text
0009_quest_objectives.sql
```

P3-T04 established source-backed quest objective membership/geography for `U/O/I/IR/A/Z` plus
area-trigger and item-use-target support. Its canonical validation produced, among other rows:

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
```

The second same-revision P3-T04 canonical pass produced zero inserts, updates and deletes, and
foreign-key/integrity checks passed. Detailed validation remains in
`docs/project/tasks/P3-T04.md`.

The one-step rollback path remains:

```text
data/generated/octogamedb_bak.sqlite3
```

under D-029. No database mutation is part of the P3-T05 source-gate handoff, so this backup must not
be replaced merely to apply the documentation delta.

## P3-T05 source investigation

P3-T05 was entered as the next bounded implementation task, but primary-source inspection found that
the source pair named by the task does not carry the required quantity/reward facts in its distributed
quest representation.

Reviewed public revisions:

```text
shagu/pfQuest
104f35678ca39ab1fb78b655f815cc7016f5e0c8

KameleonUK/pfQuest-turtle
5b8eeeeb4119be9d075087f0f0e08c187b35ad61
```

Established source contract:

- pfQuest `toolbox/extractor.lua` reads `ReqItemId1..4` and `ReqSourceId1..4` into one item-membership
  set and serializes only the resulting IDs as quest `obj.I` membership;
- the distributed quest export does not preserve the corresponding raw item/source-item quantities;
- the extractor does not serialize guaranteed or choice item rewards;
- `db/quests-itemreq.lua` is item-use target evidence and carries no requirement quantity;
- the currently published pfQuest extractor was also checked on 2026-08-25 and still does not export
  `ReqItemCount`;
- the reviewed pfQuest-turtle `db/quests-turtle.lua` is empty, and the currently published file checked
  on 2026-08-25 is also empty.

Therefore assigning quantities/rewards from the existing pfQuest/Turtle files would violate D-023 and
P3-T05's own no-inference requirement. D-031 records the durable source gate.

## Active task

### P3-T05A — establish quest quantity/reward source contract

**Status: READY_FOR_IMPLEMENTATION**

Detailed task:

```text
docs/project/tasks/P3-T05A.md
```

P3-T05A must select and validate a reproducible source contract for:

- required item IDs and quantities;
- any distinct required source/provided-item IDs and quantities;
- guaranteed item reward IDs and quantities;
- choice item reward IDs and quantities;
- complete-set/absence/order semantics needed for reconciliation.

Follow `DATA_SOURCES.md` source priority. Evaluate Octo-specific authoritative data such as OctoDB
first. If a Vanilla VMaNGOS/CMaNGOS-style source is needed as a baseline/fallback, pin the exact source
revision and define a field/relation-specific authority policy rather than treating it as Octo truth.

P3-T05 implementation remains blocked until P3-T05A establishes that contract. Do not add migration
10, requirement/reward canonical tables, or inferred quantities before then.

## Next-conversation guard

The next coding conversation should take P3-T05A only after this documentation delta has been applied,
committed and pushed to GitHub `main`.

If GitHub `main` still points to `56658585524b0a3a82083d24ac63105a0efb24da`, this handoff has not
yet been integrated; do not independently implement P3-T05 against the old `READY_FOR_IMPLEMENTATION`
routing.
