# Current project state

Updated for P8-T01 validation and P8-T02 routing on 2026-09-09.

## Source-of-truth

GitHub `main` still resolves to the pre-P8 integration revision:

```text
0f48746fb2ce6cf6b2666f162851b9076f849ce5
Validate P7-T07 read-path optimization and route P8-T01
```

The P8-T01 implementation/validation delta is intentionally stacked on the user's local working tree
and has not yet been pushed to GitHub at the time of this handoff. Do not apply this finalization delta
to a clean `0f48746...` checkout by itself: first apply the earlier P8-T01 implementation delta and
its validation correction, or reconcile manually.

## Accepted canonical local database

The accepted cumulative local database remains unchanged:

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

P8-T01 was strictly read-only and introduced no migration or canonical mutation.

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
P8-T02: READY_FOR_IMPLEMENTATION
```

## P7 baseline consumed by P8

P7-T06/P7-T07 remain the validated semantic and performance owners for the first UI vertical slice.
Representative full-data P7-T07 cold zone-detail calls are approximately `5.45-7.84 s`, all below the
10-second target recorded in `docs/project/tasks/P7-T07.md`. P8 does not replace or bypass those query
contracts.

Authoritative consumer contracts:

```text
docs/project/P7_ZONE_QUERY_CONTRACT.md
docs/project/P7_WORLD_ENTITY_QUERY_CONTRACT.md
```

## P8-T01 validated result

Task record:

```text
docs/project/tasks/P8-T01.md
```

P8-T01 established:

- NiceGUI 3.x as the local/browser UI framework under D-038;
- `nicegui>=3.16,<4` as a runtime dependency;
- `octogamedb-ui` and `python -m octogamedb.ui_app` as startup paths;
- `src/octogamedb/ui_read.py` as a thin read-only adapter over P7 `query_zones()` and `inspect_zone()`;
- SQLite URI `mode=ro` plus `PRAGMA query_only=ON`; missing DB paths are never created;
- zone search by ID/name/map with query-layer sorting/state selection;
- zone-detail sections for world entities, item-acquisition evidence, quest roles, vendors, resolved
  and unresolved trainers, and five independent recipe-learning evidence views;
- explicit rendering of `unknown`, truncation, unresolved trainer relations, recipe unknown counts and
  `negative_claim_authorized=False` semantics;
- visible detail loading while the multi-second P7 call runs through NiceGUI `run.io_bound()`;
- Python-level navigation coverage through NiceGUI `user_simulation`.

The UI contains no canonical-domain SQL. Its only SQL-adjacent operations are SQLite connection safety
PRAGMAs; all zone/domain reads remain owned by P7.

## P8-T01 validation evidence

The first local gate exposed one P8 test/UX issue plus two unrelated P4 fixture failures caused by
placing pytest `--basetemp` inside the parent Git checkout. The P8 correction changed only the P8 UI
and tests; P4 production/test semantics were not weakened.

After the correction, the user reported that the automated test gate passes. The validated manual
browser checks on the real canonical DB confirmed:

- the zone list renders correctly;
- zone ID, zone name, map ID and map-name searches work when `SEARCH` is applied;
- deterministic ascending/descending sorting works when `SEARCH` is applied;
- zone detail navigation works, including representative zones and a visible
  `Loading zone detail…` state;
- world entity, item, quest, vendor, trainer and recipe sections render as expandable sections when
  evidence exists;
- coverage remains explicit rather than silently negative. Example observed on Blasted Lands:
  `Negative claim authorized: False`, `Unknown entity geography: 0`, `Known non-matches: 34490`,
  `Returned entities: 319`, with recipe-geography unknown counts still shown;
- truncation/unresolved semantics are not hidden.

The machine was restarted before the originally captured `$before` PowerShell variable could be
compared, so an intra-session before/after equality check was no longer possible. This does not block
validation because after running and stopping the UI the canonical DB hash was explicitly recomputed
as:

```text
60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

which is exactly the accepted D-029 canonical baseline recorded before P8-T01. Therefore the read-only
UI did not advance or mutate the canonical database.

On Windows/Python 3.13, stopping NiceGUI/Uvicorn with `Ctrl+C` emitted a `CancelledError` followed by
`KeyboardInterrupt`. This is shutdown noise from the interrupted server loop, not a validation or DB
integrity failure.

## Observed UX follow-up from real use

P8-T01 is functionally validated, but the first real browser session identified concrete interaction
friction:

- pressing Enter in zone/map search fields does not submit the search;
- changing sort/state controls does not refresh results until `SEARCH` is clicked;
- the separate wall of `Open <zone> (...)` links below the table is functional but poor navigation UX;
- detail loading remains visibly multi-second because it inherits the validated P7 read-path cost.

These are routed to P8-T02 as UI interaction work. P8-T02 must not reinterpret P7 query semantics or
silently turn the observed latency into a new persistence/cache architecture.

## Current task / next-conversation router

Current task:

```text
P8-T02 — zone explorer interaction polish
Status: READY_FOR_IMPLEMENTATION
Task file: docs/project/tasks/P8-T02.md
```

P8-T02 is deliberately bounded to interaction ergonomics around the already validated zone explorer:
form submission, control-application behavior and table-based navigation. It should preserve the P7
read-only/coverage contracts and avoid unrelated domain, ingestion, map, inventory, economics or
canonical-DB work.
