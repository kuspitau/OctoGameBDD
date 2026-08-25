# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must still verify the actual current head before
editing.

## GitHub baseline

This source-strategy audit and handoff were prepared against GitHub `main` commit:

```text
6d1fab728a6eda5e61409cbc468d458ae9056238
```

That commit is the human-applied P3-T05A closeout (`Establish P3-T05 quest quantity/reward source
contract`). It contains D-032, validated P3-T05A project memory, and routes directly to P3-T05.

## Validated cumulative state

P0 through P3-T04 are `VALIDATED` in code/data. P3-T05A remains `VALIDATED` as the source-contract
investigation that established the OctoDB + CMaNGOS strategy from the sources known at that time.

The canonical cumulative local database remains:

```text
data/generated/octogamedb.sqlite3
```

It is validated through migration:

```text
0009_quest_objectives.sql
```

Neither P3-T05A nor this later source-strategy audit mutates SQLite, adds a migration or advances the
canonical data state. Do not replace the D-029 backup merely to apply this documentation delta.

P3-T04 remains the latest canonical-data implementation. Its detailed counts/idempotence/FK results
remain in `docs/project/tasks/P3-T04.md`.

## Post-P3-T05A source-strategy audit

After P3-T05A was completed, further public-source investigation found two inputs that materially
improve the planned P3-T05 acquisition strategy.

### 1. Direct Octo quest observations through ClassicAPI

Pinned semantic reference:

```text
https://github.com/brues-code/ClassicAPI
master @ e793f80f6b45ed49a94dc8abdc9fcac4fe6b03dd
```

At that revision, `C_QuestLog.RequestLoadQuestByID(questID)` can request/load quest static data and
settles through `QUEST_DATA_LOAD_RESULT`; `C_QuestLog.GetQuestDetails(questID)` exposes:

- ordinary item requirements as native item ID + exact count;
- guaranteed item rewards as native item ID + exact count;
- choice item rewards as native item ID + exact count;
- `srcItemID` for the quest-start source/provided item.

This is direct positive evidence from the actual Octo client/server interaction when executed in the
user's live client. It is **not** a complete server quest-template dump. The exposed contract does not
provide `ReqSourceId/ReqSourceCount` or a `SrcItemCount`, and other server-enforced quest restrictions
are also absent from the Vanilla quest-query cache. Query failure/missing fields therefore remain
unknown rather than negative complete-set evidence.

### 2. Structured Turtle 1.18.1 world SQL

Pinned public reference:

```text
https://github.com/Penqle/tortoise-wow
main @ 61a8269151721f6467eddb05e7bed37704d0fc0b
```

The repository describes itself as an unofficial community restoration of Turtle-WoW 1.18.1 build
7272 and documents a database lifecycle based on `sql/base` plus server-applied updates. It contains a
source-shaped `quest_template` with the P3-T05 fixed-slot requirement/source/provided/reward families
and current/custom Turtle-lineage content.

This is substantially closer and broader evidence for Octo-oriented work than a Vanilla-only
CMaNGOS baseline, but it is **not automatically Octo production truth**. Its Turtle 1.18.1 restoration
lineage makes it highly relevant for comparison/coverage while any disagreement with direct Octo
evidence remains a source conflict.

### Supporting references

```text
Questie-Octo
https://github.com/SandreaSub/Questie-Octo
main @ 389af5f003f1a0f05132a7d39410c7d184700800
```

Its provenance notes use current Turtle/Tortoise server source for server-side quest/spawn/script
checks while separately treating direct Octo client extracts as authority for client-side facts. This
corroborates Tortoise as useful Octo-oriented audit evidence, not as universal Octo truth.

```text
Tortoise DB Viewer
https://github.com/Xian55/tortoise-db-viewer
main @ f274ac2b00aa7e3b25def609bd354ca4feb298e9
```

Its builder demonstrates a practical base-SQL + ordered-migration staging pipeline, but its final
`quest_item` projection already normalizes source families (including suppressing some duplicated
`ReqSource` entries). It is therefore a technical/parser reference and cross-check only. P3-T05 must
consume source-shaped Tortoise quest facts itself.

## Decision update

D-033 records the new bounded P3-T05 authority strategy and **supersedes D-032 only for current source
priority/acquisition**. D-032 remains the durable historical P3-T05A result and its semantic findings
remain in force unless contradicted by later validated evidence.

Target P3-T05 ordering to validate in P3-T05B:

```text
ReqItem + count:
  Octo live query -> OctoDB -> Tortoise SQL -> CMaNGOS Vanilla

Guaranteed reward + count:
  Octo live query -> OctoDB -> Tortoise SQL -> CMaNGOS Vanilla

Choice reward + count:
  Octo live query -> OctoDB -> Tortoise SQL -> CMaNGOS Vanilla

SrcItem ID:
  Octo live query -> OctoDB -> Tortoise SQL -> CMaNGOS Vanilla

SrcItem count:
  OctoDB when structurally explicit -> Tortoise SQL -> CMaNGOS Vanilla

ReqSource ID/count:
  Tortoise SQL -> CMaNGOS Vanilla
  (Octo-specific live coverage still unresolved)
```

Every selected fact retains its real source identity. A Tortoise fallback is never relabeled as live
Octo truth. OctoDB remains partial positive HTML evidence. CMaNGOS remains the pinned Vanilla fallback
and semantics reference. pfQuest/P3-T04 objective membership still cannot manufacture P3-T05
quantities.

## Active task

### P3-T05B — validate Octo live quest-query and Tortoise SQL source contract

**Status: READY_FOR_IMPLEMENTATION**

Detailed task:

```text
docs/project/tasks/P3-T05B.md
```

The next conversation should implement and validate this acquisition/source-contract bridge before
P3-T05 schema work resumes. The bounded work includes:

- a source-shaped Tortoise `quest_template` adapter over the pinned base + relevant ordered world
  migrations;
- deterministic source revision/content hashing and small fixtures;
- preservation of native slot/family semantics, including duplicate IDs and `ReqSourceCount = 0`;
- a small, user-triggered ClassicAPI quest probe using one outstanding request at a time;
- local raw capture/provenance for direct Octo positive observations;
- representative Vanilla/custom comparisons across Octo live, OctoDB, Tortoise and CMaNGOS;
- explicit validation of missing/unknown fields without treating absence as a complete empty set;
- no canonical P3-T05 migration or canonical DB mutation.

P3-T05 is temporarily `BLOCKED_ON_P3-T05B`. Its canonical direction is unchanged; only its source
acquisition/priority strategy is being strengthened before implementation.

## Next-conversation guard

Take P3-T05B only after this delta has been applied, the tracked quality gate has passed, and the
result has been committed/pushed to GitHub `main`.

If GitHub `main` still points to:

```text
6d1fab728a6eda5e61409cbc468d458ae9056238
```

then this post-P3-T05A strategy update has not yet been integrated. Do **not** start P3-T05 directly
from the old D-032-only routing; first integrate/reconcile this handoff.
