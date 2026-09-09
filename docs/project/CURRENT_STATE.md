# Current project state

Updated for P8-T02 validated closure and P8-T03 routing on 2026-09-09.

## Source-of-truth / integration state

The visible GitHub `main` revision at P8-T02 implementation start and throughout this unpushed local
handoff was:

```text
8b129c7401a253a46312c8d6aebb03291994b851
Validate P8-T01 NiceGUI zone explorer and route P8-T02
```

P8-T02 implementation, its first local-gate correction, and this validation closure are intentionally
stacked on the user's local working tree and are not yet represented by that visible GitHub revision.
The human should commit/push the complete local P8-T02 state before the next coding conversation treats
GitHub `main` as containing P8-T02.

## Accepted canonical local database

The accepted cumulative local database remains:

```text
data/generated/octogamedb.sqlite3
schema_version = 14
latest migration = 0014_item_template_facts.sql
SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Immediate D-029 rollback snapshot remains:

```text
data/generated/octogamedb_bak.sqlite3
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

P8-T01/P8-T02 are strictly read-only and introduced no migration or canonical mutation.

## Phase status

```text
P0: VALIDATED
P1: VALIDATED through P1-T04
P2: VALIDATED through P2-T04
P3: VALIDATED through P3-T05
P4: VALIDATED through P4-T04
P5: VALIDATED through P5-T08
P6: VALIDATED through P6-T05
P7-T01: VALIDATED
P7-T02: VALIDATED
P7-T03: VALIDATED
P7-T04: VALIDATED
P7-T05: VALIDATED
P7-T06: VALIDATED
P7-T07: VALIDATED
P8-T01: VALIDATED
P8-T02: VALIDATED
P8-T03: READY_FOR_IMPLEMENTATION
```

## P7/P8 semantic baseline

P7 remains the owner of consumer/query semantics. P8 is a thin NiceGUI presentation layer and must not
create parallel canonical SQL truth or silently collapse unknown coverage.

Validated contracts relevant to the current UI work include:

```text
docs/project/P7_ZONE_QUERY_CONTRACT.md
docs/project/P7_WORLD_ENTITY_QUERY_CONTRACT.md
docs/project/P7_ITEM_QUERY_CONTRACT.md
docs/project/P7_ITEM_ACQUISITION_QUERY_CONTRACT.md
```

P7-T07 representative full-data cold zone-detail calls remain approximately `5.45-7.84 s`, below its
10-second target. P8 may clarify loading behavior but must not introduce persistence/caching merely to
hide that validated read cost.

## P8-T01 validated foundation

P8-T01 established the application baseline under D-038:

- NiceGUI 3.x (`nicegui>=3.16,<4`);
- `octogamedb-ui` / `python -m octogamedb.ui_app` startup paths;
- `src/octogamedb/ui_read.py` as a thin read-only adapter over P7 queries;
- SQLite URI `mode=ro` plus `PRAGMA query_only=ON`;
- no canonical-domain SQL in the UI;
- explicit unknown/truncation/unresolved/negative-claim rendering;
- `run.io_bound()` for multi-second read paths;
- stable NiceGUI user-simulation coverage.

## P8-T02 validated result

Task record:

```text
docs/project/tasks/P8-T02.md
```

P8-T02 validated the zone-explorer interaction polish:

- Enter submits Zone ID, zone name, Map ID and map-name searches through the same shared search action;
- sort field/direction and inclusion-state switches apply automatically;
- the interaction model is explicit in the search card;
- the old post-table wall of `Open <zone> (...)` links is removed;
- zone navigation is table-native through an `Open` action column;
- Python owns route navigation after the scoped table action emits only `zone_id`;
- stable markers make NiceGUI simulation tests deterministic;
- visible detail-loading feedback remains for the validated multi-second P7 read path.

`src/octogamedb/ui_read.py`, P7 semantics, schema, migrations and canonical selection are unchanged.

### Automated validation

The first local gate collected 367 tests and exposed only two test-simulation assumptions plus one Ruff
SIM117 finding. After the focused correction, the user confirmed the complete gate passes:

```powershell
pytest --basetemp="$env:TEMP\OctoGameDB_pytest"
python -m ruff check src tests
python -m compileall -q src tests
```

Validated result:

```text
pytest: all 367 tests pass
Ruff: All checks passed!
compileall: passed
```

### Browser / canonical validation

The user confirmed all P8-T02 browser checks behave correctly, including Enter submission, immediate
sort/state application, table-native navigation, loading feedback and preserved coverage semantics.

After stopping the UI:

```text
$after = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
$before -eq $after = True
```

Therefore the UI preserved the accepted canonical DB byte-for-byte.

## Current task / next-conversation router

Next task:

```text
P8-T03 — item explorer vertical slice
Status: READY_FOR_IMPLEMENTATION
Task file: docs/project/tasks/P8-T03.md
```

P8-T03 should expose the already validated P7-T01/P7-T02 item and acquisition contracts through the
existing NiceGUI/read-only architecture. It must not broaden into saved searches, weighted scores,
item comparison, tooltip/icon work, inventory ownership, crafting economics, P6 acquisition or schema
mutation in the same task.

Before implementing P8-T03, the next conversation must read fresh GitHub `main`. If the human has not
yet pushed the validated P8-T02 local state, do not assume these files/code exist on GitHub; reconcile
that integration state first.
