# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must still verify the actual current head before
editing.

## Integration baseline for this closeout

At closeout preparation time, visible GitHub `main` is still:

```text
9555290b6be21d7e9153652a661f680a0ed47b18
```

Commit title:

```text
Validate P3-T05B source contract and unblock P3-T05
```

The validated P3-T05 implementation is currently a **local stacked integration state** and has not
yet been pushed to GitHub. It consists of:

1. the full P3-T05 implementation handoff
   `changes.zip` SHA-256
   `0d6648912565ab3af70c21d6a017977c148dda2b1fa68382d4741787e7106f44`;
2. the corrective P3-T05 handoff
   `changes.zip` SHA-256
   `9735c0aa8f5f236d3066d5d57940c07f7e59e7d08c7f9ba73095cd3f3cb560fc`;
3. this P3-T05 closeout handoff.

This closeout must be applied only on top of that local P3-T05 integration state. It must not be
applied by itself to visible GitHub `main`.

After the human commits and pushes the combined implementation + correction + closeout, the next
conversation must verify the new `main` head before proceeding.

## Validated cumulative state

P0 through P3-T05 are now `VALIDATED` in code/data. P3-T05A and P3-T05B remain the validated
source-contract predecessors for the P3-T05 quantity/reward slice.

The canonical cumulative local database is:

```text
data/generated/octogamedb.sqlite3
```

and is now validated through:

```text
0010_quest_item_facts.sql
```

The immediate rollback file remains:

```text
data/generated/octogamedb_bak.sqlite3
```

and is the byte-identical migration-9/P3-T04 pre-P3-T05 state produced under D-029.

## P3-T05 — validated quest item requirements and rewards

### Status

```text
VALIDATED
```

Detailed implementation/validation record:

```text
docs/project/tasks/P3-T05.md
```

Human/local validation completed successfully on 2026-08-26.

General tracked quality gates passed before Level 2:

```text
python -m pip install -e ".[dev]"
pytest --basetemp=.pytest_tmp
python -m ruff check src tests
python -m compileall -q src tests
```

The task-specific Level-2 validation then reacquired/revalidated the real source inputs and confirmed:

- deterministic full Tortoise projection at pinned revision
  `61a8269151721f6467eddb05e7bed37704d0fc0b`;
- bounded live Octo/ClassicAPI evidence with capture hash
  `71de2543b3b7e008dd229d82cb5372e163e08c117cc3b354229ff2b0ef71dedc`;
- reviewed OctoDB evidence revision
  `0f81f0908cc3b8082ae2897901b88c61f24c916c04bf3c4c6b627eb09f53e533`;
- pinned CMaNGOS evidence revision
  `250a705a462c1acb457d3002359c7e0052c4dafe:0a77f5230a3d5d6db968678203dfe3b30c34b8a9`;
- D-033 four-source comparison with no same-priority ambiguity;
- a real raw `ReqSourceCount = 0` observation retained as provenance without creating a zero ordinary
  requirement quantity;
- migration 10 on a disposable copy, with second-pass zero inserts/updates/deletes;
- FK/integrity success, read-model checks and source-provenance audits;
- D-029 canonical mode on an isolated shadow copy before real canonical mutation.

The deliberate real canonical evolution then succeeded:

```text
schema_version = 10
migration       = 0010_quest_item_facts.sql

quest_required_items       = 6100
quest_required_sources     = 2961
quest_provided_items       = 1320
quest_reward_items         = 2072
quest_choice_reward_items  = 2424
```

Final direct canonical checks reported:

```text
foreign_key_check               = []
integrity_check                  = ["ok"]
failed_import_batches            = 0
invalid_required_quantity_count  = 0
```

The accepted D-033 comparison hash is:

```text
ac376ec58584c59446eb6c6d448b6f6565fb3f14593c27b60c13e539e43cea50
```

Canonical hashes at closeout:

```text
migration-9 backup:
3dc2a49092d108a1274e55e3052b3ba74711b5ec0f675c9ff2a201c287617443

validated migration-10 canonical:
9c637ab40c2c5e3c2843e6c7d52fb5c75bbe05f57d05e2ea4d48ae7bd03b127d
```

The 268 unresolved item/quest targets remain explicit warnings/provenance evidence. They are not
fabricated identities and did not produce FK/integrity failures. Four cross-source value conflicts
remain retained for audit; none is a same-priority ambiguity.

## Durable P3-T05 policy

D-033 remains the governing field-family source policy:

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
```

Operational consequences remain:

- missing/failed live fields are unknown, not complete empty evidence;
- partial live/OctoDB absence does not delete selected positive facts;
- complete Tortoise fixed-slot evidence may replace stale managed fallback facts only within the
  family whose completeness contract is established;
- explicit/custom selections remain protected;
- raw `ReqSourceCount = 0` is source/drop-control evidence, not an ordinary zero required quantity;
- P3-T04 objective membership stays separate from P3-T05 quantity-bearing requirements.

## Active task

### P4-T01 — spell/recipe source and identity contract

**Status: READY_FOR_IMPLEMENTATION**

Detailed task:

```text
docs/project/tasks/P4-T01.md
```

This is the first bounded P4 task. It must establish the source/identity semantics needed to preserve
the project's required distinctions between:

- native spell identity;
- the learned/crafting spell that performs a recipe;
- an item that teaches/unlocks a recipe;
- the crafted result item;
- profession/skill-line membership and rank/skill requirements.

Do not begin a broad reagents/acquisition/economics import before those identities and source
completeness rules are evidenced. P4-T01 should prefer primary/current source inspection and
source-shaped fixtures over assumptions.

The validated migration-10 canonical DB is the cumulative local baseline available to P4-T01, but
P4-T01 should not mutate it unless its task-specific implementation and validation protocol explicitly
requires a new migration and follows D-029.

## Next-conversation guard

Before starting P4-T01, verify GitHub `main` contains the complete P3-T05 implementation, correction
and this closeout. If `main` still points to
`9555290b6be21d7e9153652a661f680a0ed47b18`, the local handoffs have not yet been integrated and the
next conversation must not assume P3-T05 code/project memory exists on GitHub.
