# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must still verify the actual current head before
editing.

## GitHub baseline

P3-T05A source-contract investigation and this handoff were performed against GitHub `main` commit:

```text
6f5fb26076d6ec9aa95b63a9c0f53c4a0767ee3c
```

That commit contains the P3-T05 source-gate handoff and makes P3-T05A the active task.

## Validated cumulative state

P0 through P3-T04 are `VALIDATED` in code/data. P3-T05A is now `VALIDATED` as a documentation/source
contract task.

The canonical cumulative local database remains:

```text
data/generated/octogamedb.sqlite3
```

It is validated through migration:

```text
0009_quest_objectives.sql
```

P3-T05A did not mutate SQLite, add a migration or advance the canonical data state. The D-029 backup
must therefore not be replaced merely to apply this documentation delta.

P3-T04 remains the latest canonical-data implementation. Its detailed counts/idempotence/FK results
remain in `docs/project/tasks/P3-T04.md`.

## P3-T05A result

D-031's source gate is resolved without changing the established meaning of pfQuest `obj.I`.

### Preferred Octo-specific observation source

Use cached native-ID OctoDB quest-detail pages:

```text
https://octowow.st/db/?quest=<quest_id>
```

Current public inspection on 2026-08-25 confirmed explicit requirement/reward structures on both
Vanilla and Octo/Turtle custom quest pages, including:

```text
818    A Solvent Spirit
815    Break a Few Eggs
40788  Heavy Earthen Cores
40675  A Hero's Reward
```

No documented stable structured quest API or immutable public OctoDB data revision was identified.
D-032 therefore treats cached OctoDB HTML as high-priority **partial positive observation evidence**.
A parser must use recognized structural item/count data and native item links, never quest prose.
Missing pages/sections cannot authorize stale-row deletion.

OctoDB raw pages stay local under:

```text
data/raw/octodb/quests/<quest_id>.html
```

Per-page revision is SHA-256 of exact response bytes. A deterministic batch revision hashes sorted
`(quest_id, page_sha256)` pairs. Retrieval URL/native ID/time/status/content type/hash remain
provenance/import metadata. Retrieval is cache-first, rate-limited to at most one request per second by
default, with bounded transient retries and no automatic parallel scraping unless a later decision
changes that policy.

### Pinned Vanilla fallback baseline

```text
cmangos/classic-db
250a705a462c1acb457d3002359c7e0052c4dafe
Full_DB/ClassicDB_1_12_1_z2815.sql.gz
blob 0a77f5230a3d5d6db968678203dfe3b30c34b8a9

cmangos/mangos-classic semantic reference
9b682be617ac61c127c23aa60d7b4ffbc0ce37e6
```

Relevant fixed-slot families:

```text
ReqItemId[4] / ReqItemCount[4]
ReqSourceId[4] / ReqSourceCount[4]
SrcItemId / SrcItemCount
RewChoiceItemId[6] / RewChoiceItemCount[6]
RewItemId[4] / RewItemCount[4]
```

CMaNGOS is complete Vanilla baseline/fallback evidence for those slots, not Octo truth. It may be
selected only when no higher-priority Octo-specific selected observation exists for that bounded fact
family. Conflicts remain provenance.

A critical semantic result is that `ReqSource` is not an ordinary completion requirement. Current
ClassicDB explicitly uses `ReqSourceId != 0` with `ReqSourceCount = 0` to mean normal core/item-stack
drop behavior. P3-T05 must keep ordinary `ReqItem`, quest-start `SrcItem`, auxiliary `ReqSource`,
guaranteed `RewItem`, and choice `RewChoiceItem` families separate.

D-032 records the durable authority/semantics policy. Detailed evidence and retrieval rules are in
`docs/project/DATA_SOURCES.md` and `docs/project/tasks/P3-T05A.md`.

## Active task

### P3-T05 — quest item requirements and rewards

**Status: READY_FOR_IMPLEMENTATION**

Detailed task:

```text
docs/project/tasks/P3-T05.md
```

The next conversation should implement P3-T05 against D-032. The bounded implementation includes:

- canonical/provenance tables for ordinary required items + quantities;
- distinct auxiliary/source-item facts preserving raw `ReqSourceCount` semantics;
- quest-start provided item + quantity;
- guaranteed item rewards;
- explicit choice reward set + members/quantities;
- source slot/order provenance;
- cached fail-closed OctoDB page observations;
- pinned CMaNGOS ClassicDB Vanilla fallback/complete-set evidence;
- field-family-specific resolution and protected-selection behavior;
- unresolved native item IDs without fabricated placeholders;
- deterministic source revisions, idempotence, audit/query surfaces and full Level-2 validation.

Do **not** infer P3-T05 quantities from P3-T04 objective membership. Do **not** treat
`ReqSourceCount` as a turn-in quantity. Do **not** use OctoDB page absence as complete negative
evidence.

## Next-conversation guard

Take P3-T05 only after this delta has been applied, the tracked quality gate has passed, and the
result has been committed/pushed to GitHub `main`.

If GitHub `main` still points to `6f5fb26076d6ec9aa95b63a9c0f53c4a0767ee3c`, this P3-T05A closeout
has not yet been integrated; do not independently implement P3-T05 against the stale
`BLOCKED_ON_SOURCE_CONTRACT` task state.
