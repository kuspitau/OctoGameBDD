# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must still verify the actual current head before
editing.

## Integration note for this closeout

The P3-T02 implementation/Level-1 delta was prepared against GitHub `main`
`cc1f5694a6602ea97e5b6d88840c8d6d645f2627`, but at the time of this closeout that implementation
had not yet been pushed to GitHub. This closeout documentation is therefore **stacked on the local
working tree after the P3-T02 implementation delta has been applied**.

Do not treat a GitHub checkout that still routes to P3-T01 as already containing P3-T02. The human
must commit/push the implementation and this closeout before the next coding conversation begins.

## Recently completed

### P3-T01 — first quest identity/endpoints vertical slice

**Status: VALIDATED**

P3-T01 is closed. The earlier human transition reported successful Level-2 validation; no historical
metrics were invented for that transition. The later clean cumulative rebuild performed during
P3-T02 closure independently re-exercised the base importer against the configured real pfQuest
source and observed:

- base quest revision:
  `sha256:667303b5507015b4039508e6a8f8afc0f6c086f285d5dc56afd0addb79cbe8e3`;
- `4,433` accepted base quests;
- `7,945` creature giver/finisher endpoints and `471` game-object endpoints in the import summary;
- `30` explicit unresolved endpoint diagnostics for targets absent from the current P1 canonical
  identity set;
- no fabricated endpoint target identities.

P3-T01 remains bounded to quest identity/name plus creature/game-object giver/finisher endpoints.

### P3-T02 — pfQuest-turtle effective quest identity/endpoint reconciliation

**Status: VALIDATED**

P3-T02 completed full local validation on 2026-08-24 against a clean cumulative rebuild using the
configured real pfQuest, pfQuest-turtle and Octo DBC inputs.

Validated revisions relevant to the quest layer:

```text
base pfQuest quests
sha256:667303b5507015b4039508e6a8f8afc0f6c086f285d5dc56afd0addb79cbe8e3

pfQuest-turtle quests
sha256:234f8062f8006d5dc17c526b81772cf50f8591170781ae5af8b72a86b237d25a
```

First real P3-T02 reconciliation:

```text
status                                      succeeded
error_count                                 0
rows_read                                   5481
rows_accepted                               5481
rows_skipped                                0
rows_inserted                               6652
rows_updated                                73
canonical_relations_or_identities_deleted   313
warning_count                               0
unresolved_endpoints                        0
inactive_endpoint_quests                    0
```

Second same-revision reconciliation:

```text
status                                      succeeded
error_count                                 0
rows_inserted                               0
rows_updated                                0
canonical_relations_or_identities_deleted   0
warning_count                               0
```

Additional acceptance evidence:

- `PRAGMA foreign_key_check` returned no violations;
- `PRAGMA integrity_check` passed;
- base + Turtle complete-view evidence was validated on `10,962` touched quest fact groups;
- `10,357` managed primitive endpoint attributions were checked;
- endpoint provenance split observed by the validator:
  - inherited base: `97`;
  - Turtle-patched: `10,260`;
- a managed primitive quest-name attribution was validated;
- representative changed quest `109` selected Turtle `quest_presence` and `quest_endpoint_set` using
  policy `pfquest-turtle-effective-quests`;
- quest `109` finisher creature `234` resolved through existing P1 geography to spawn `1561`, zone
  `40` (`Westfall`), map `0` (`Eastern Kingdoms`), `zone_percent` coordinates `(56.3, 47.5)`.

The complete repository pytest battery, Ruff and `compileall` had already been reported successful by
the human before the clean rebuild and were intentionally not repeated by the rebuild validator.

Detailed task/validation record: `docs/project/tasks/P3-T02.md`.

## Canonical local database

The human then finalized cleanup so the local data tree contains the canonical DB at:

```text
data/generated/octogamedb.sqlite3
```

plus tracked `data/README.md`.

That SQLite DB was rebuilt from a fresh file through the validated P1/P2 chain, P3-T01 and P3-T02.
Final observed canonical counts included:

```text
maps                         57
zones                        1480
creatures                    13842
creature_spawns              110048
gameobjects                  20967
gameobject_spawns            74924
items                        23336
creature_loot                322054
gameobject_loot              8511
loot_references              666
item_reference_loot          10429
vendor_items                 20149
quests                       6498
quest_creature_endpoints     12145
quest_gameobject_endpoints   545
data_sources                  4
import_batches                12
canonical_selections          1098706
source_observations           1954854
```

It contained no failed/running import batch and passed final FK/integrity checks.

Under D-029 this DB is now the **canonical local cumulative data baseline through P3-T02**. Before any
future mutation, create/replace:

```text
data/generated/octogamedb_bak.sqlite3
```

See `docs/project/CANONICAL_DB.md`.

## Active task

### P3-T03 — quest restrictions and dependency graph

**Status: READY_FOR_IMPLEMENTATION**

The next bounded P3 task is defined in:

```text
docs/project/tasks/P3-T03.md
```

It should extend the already validated effective quest identity/endpoints model with the next
coherent source family rather than jumping to full quest ingestion.

Primary investigation/implementation target:

- quest level / minimum level;
- race and class restrictions;
- prerequisite quest relations;
- exclusive/closing quest-group semantics;
- derived follow-up relationships where they are truly the reverse of prerequisite evidence;
- corresponding pfQuest-turtle effective-view/reconciliation semantics and provenance.

Objectives, required items, rewards, quest text and item-start behavior remain deferred unless
primary-source inspection demonstrates that a specific field is inseparable from this bounded model.

## Routing guard

The next coding conversation must first verify that GitHub `main` contains the P3-T02 implementation
and this closeout. If GitHub still routes to P3-T01/P3-T02, stop and reconcile the unpushed local
handoff rather than implementing P3-T03 against stale `main`.

When P3-T03 needs cumulative full-data validation, use the canonical local DB contract instead of
rebuilding or guessing an old validation database. Back up the canonical DB before any write.
