# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must still verify the actual current head before
editing.

## Integration baseline for this closeout

At closeout preparation time, visible GitHub `main` is still:

```text
ee893eb2a37808ebb791790abd8561a76da92738
```

Commit title:

```text
Refine P3-T05 source strategy with live Octo and Tortoise evidence
```

The validated P3-T05B implementation delta was applied locally on top of that commit and has not yet
been pushed to GitHub. This closeout delta is intentionally stacked on that local implementation
state. It must not be applied by itself to the visible `ee893eb...` tree.

After the human commits and pushes the combined implementation + closeout, the next conversation must
verify that the current GitHub head contains both before proceeding.

## Validated cumulative state

P0 through P3-T04 are `VALIDATED` in code/data. P3-T05A is `VALIDATED` as the historical source-
contract investigation. P3-T05B is now also `VALIDATED` after successful real-source Level-2
validation on 2026-08-26.

The canonical cumulative local database remains:

```text
data/generated/octogamedb.sqlite3
```

It remains validated through migration:

```text
0009_quest_objectives.sql
```

P3-T05A, D-033 and P3-T05B do not add a canonical migration or advance canonical SQLite data.
P3-T04 remains the latest canonical-data implementation. The P3-T05B validation explicitly confirmed
that the canonical database hash was unchanged.

## P3-T05B — validated acquisition/source bridge

### Status

```text
VALIDATED
```

Detailed record:

```text
docs/project/tasks/P3-T05B.md
```

Durable validated outcomes:

- source-shaped `tortoise-world-sql` projection over the pinned Tortoise base quest table plus
  deterministic relevant world-migration replay;
- pinned Tortoise revision:
  `61a8269151721f6467eddb05e7bed37704d0fc0b`;
- bounded manual Octo/ClassicAPI quest probe with one outstanding request at a time and no autonomous
  enumeration;
- pinned ClassicAPI semantic reference:
  `e793f80f6b45ed49a94dc8abdc9fcac4fe6b03dd`;
- deterministic live SavedVariables normalization with missing/empty/failure fields remaining
  `unknown` rather than negative complete-set evidence;
- no fabricated live `ReqSource` facts and no fabricated `srcItemID` count;
- reviewed OctoDB positive structural observations;
- pinned CMaNGOS Vanilla fallback/baseline;
- deterministic four-source comparison implementing D-033's fact-family-specific priority while
  retaining conflicts and refusing silent same-priority disagreement;
- real source auditing confirms nonzero `ReqSourceId` and explicit zero-count semantics can be
  preserved without coercing them into ordinary quest-required quantities;
- no canonical SQLite mutation.

The local `data/raw` validation workspace is not a durable project dependency. Future work must rely
on the tracked acquisition/normalization code, pinned/configured source identities and reproducible
validation procedures rather than historical temporary validation directories.

## P3-T05B Level-2 completion record

Human/local validation completed successfully on 2026-08-26.

Previously completed general gates:

```text
python -m pip install -e ".[dev]"
pytest --basetemp=.pytest_tmp
python -m ruff check src tests
python -m compileall -q src tests
```

The task-specific validator also checked the script scope omitted by those commands and then completed
all remaining Level-2 work. Final reported result:

```text
[PASS] P3-T05B LOCAL VALIDATION COMPLETE: all remaining Level-2 checks passed.
[PASS] SUMMARY: P3-T05B completed all remaining local validation checks.
[PASS] Validation script finished successfully.
```

This covered the pinned Tortoise projection/determinism checks, actual Octo/ClassicAPI capture,
reviewed OctoDB evidence, pinned CMaNGOS evidence, D-033 four-source comparison invariants, real
`ReqSource` audit cases and canonical DB non-mutation.

No additional D-033/source-contract change was required by the real-source validation.

## Active task

### P3-T05 — quest item requirements and rewards

**Status: READY_FOR_IMPLEMENTATION**

Detailed task:

```text
docs/project/tasks/P3-T05.md
```

The next conversation should implement P3-T05 using the validated P3-T05B bridge and existing D-033
field-family policy. It must not redo P3-T05B as a prerequisite merely because its local raw validation
artifacts are absent.

The cumulative canonical DB is still the P3-T04/migration-9 baseline. P3-T05 is the next task that may
introduce a new canonical migration/data evolution, so D-029 / `docs/project/CANONICAL_DB.md` applies
before any canonical write.

## Durable source strategy

D-033 remains the current bounded source-priority/acquisition decision. D-032 remains historical and
its semantic distinctions continue to apply where not superseded.

Validated field-specific priority:

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
  (Octo-specific live coverage remains unresolved)
```

Every selected fact retains its real source identity. Missing live fields/query failures remain
unknown. A Tortoise fallback is never relabeled as live Octo truth, and P3-T04 objective membership
must not manufacture P3-T05 quantities.

## Next-conversation guard

Before starting P3-T05, verify GitHub `main` contains the locally validated P3-T05B implementation and
this closeout. If GitHub still points to
`ee893eb2a37808ebb791790abd8561a76da92738`, the combined handoff has not yet been integrated and the
next conversation must not assume P3-T05B code exists on `main`.
