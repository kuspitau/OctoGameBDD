# P7 quest query contract

Status: `VALIDATED`

Task: `P7-T03`

This contract defines the first bounded consumer-facing quest search and progression exploration
surface over the already-validated P3 quest model. It adds no migration, source authority or canonical
fact. All operations are read-only.

## Public surfaces

```text
src/octogamedb/quest_search.py
  query_quests()
  quest_query_page_to_dict()
  traverse_quest_progression()

src/octogamedb/quest_cli.py
  python -m octogamedb.quest_cli ...
```

The CLI opens SQLite with `mode=ro`.

## Search universe and scalar predicates

The query universe is the canonical `quests` identity table. Native quest IDs and canonical titles are
stable identity predicates. The supported scalar search predicates are:

- exact native quest ID;
- case-insensitive title substring;
- minimum/maximum known quest level;
- minimum/maximum known minimum-player level.

Race and class masks are exposed unchanged through the P3 read model. P7-T03 does not invent labels or
expand those masks into classes/races.

Known identity/title/level evidence uses the same three-state vocabulary as the earlier P7 query
surfaces:

```text
known_match
known_non_match
unknown
```

A requested level predicate is `unknown` when that scalar is not materialized. A known-false scalar
predicate dominates conjunction and yields `known_non_match`.

## Relation-specific geography

P7-T03 does not define a universal quest zone. Geography filters remain role-specific:

```text
giver_zone / giver_map
finisher_zone / finisher_map
objective_zone / objective_map
```

Within one role, requested zone and map conditions must be satisfied by the same concrete known
location.

Giver and finisher locations are derived from their selected creature/game-object endpoint identities
through P1 spawns. Objective geography reuses the P3-T04 read model and includes:

- creature objectives (`U`);
- game-object objectives (`O`);
- item-use target locations (`IR`);
- source-backed area-trigger locations (`A`);
- direct source-backed zone context (`Z`).

Plain item objective membership (`I`) has no invented geography.

These are positive-evidence filters. A known matching location proves `known_match`. Failure to find a
known matching location remains `unknown` with a role-specific
`no_known_matching_<role>_location_negative_not_proven` reason. Missing spawns, unresolved targets or
partial geography never become universal proof that a quest is absent from a requested place.

## Endpoint selection and unresolved evidence

`quest_by_id()` remains the P3 base read model. P7-T03 enriches it at query time with selected endpoint
relation provenance already present in the generic evidence tables.

For each endpoint the P7 view exposes:

- giver/finisher role;
- creature/game-object target kind and native ID;
- target name when the canonical identity exists;
- materialization/resolution status;
- selected primitive provenance when present;
- derived known locations;
- explicit unknown-geography reason when no canonical spawn is known.

Selected primitive endpoints that could not be materialized are retained in output with their native
target ID instead of disappearing.

When a selected `quest_endpoint_set` complete-set fact exists, the P7 view also exposes its selected
member count, selected-materialized count, completeness, unresolved members and selection provenance.
When no selected complete-set fact exists, completeness is reported as unknown rather than inferred
from currently materialized endpoints.

## Progression semantics

Prerequisites retain P3-T03 `any_of` semantics. P7-T03 reads the selected
`quest_prerequisite_set` evidence so selected IDs that could not be materialized remain visible.
Materialized members and unresolved selected members remain distinguishable.

Follow-ups remain derived reverse edges of materialized selected prerequisite membership. They are not
new canonical facts.

Close sets retain `exclusive_group_member_set` semantics and are exposed separately. They are never
traversed as generic prerequisite/follow-up edges merely because two quests share a close set.

### Bounded traversal

`traverse_quest_progression()` supports explicit directions:

```text
prerequisite
follow_up
```

Traversal is breadth-first, deterministic and bounded by both `max_depth` and `max_nodes`. Its `depth`
is a shortest-edge-distance projection, **not** a canonical chain-step number:

```text
depth_is_chain_step = false
```

The result preserves:

- branching/alternative members;
- unresolved target IDs;
- incomplete prerequisite sets;
- cycle edges encountered on the active traversal path;
- truncation caused by depth/node bounds;
- an aggregate ambiguity flag.

No unique linear order is inferred for branching, converging, cyclic or incomplete graphs.

## Objective and item facts

The P7 quest result embeds the existing P3-T04 objective read model and P3-T05 item-fact read model;
it does not reconstruct their semantics.

The following distinctions remain mandatory:

```text
objective item membership != explicit required-item quantity
required source item       != turn-in quantity
provided quantity may be unknown
reward item                != choice reward item
choice reward set          = choose_one
```

No quantity is inferred from objective membership, target identity equality, slot position or a
default value of one.

## Provenance

P7-T03 exposes existing selected provenance rather than defining a new selection policy:

- canonical quest-name selection as `identity_provenance`;
- selected giver/finisher primitive relation provenance;
- selected endpoint complete-set provenance when available;
- P3 progression scalar/set/member provenance;
- P3 objective provenance;
- P3 item-fact selection/source evidence.

Competing source observations remain in the generic provenance layer and are not discarded or resolved
by the query layer.

## Determinism and bounds

Search output is deterministic for a fixed database and argument set. Supported sort keys are:

```text
quest_id
name
quest_level
minimum_level
```

Unknown numeric sort values are kept after known values and are secondarily ordered by native quest ID.
Search `limit` is bounded to `1..1000`; traversal depth to `0..20`; traversal nodes to `1..500`.

JSON output uses only JSON-compatible dictionaries/lists/scalars.

## CLI examples

```text
python -m octogamedb.quest_cli --quest-id 123 --json
python -m octogamedb.quest_cli --title-contains "escort" --min-quest-level 30 --json
python -m octogamedb.quest_cli --giver-zone 10 --include-unknown --json
python -m octogamedb.quest_cli --objective-map 1 --objective-zone 40 --json
python -m octogamedb.quest_cli --quest-id 123 --traverse prerequisite --max-depth 4 --json
python -m octogamedb.quest_cli --quest-id 123 --traverse follow_up --max-depth 4 --json
```

## Validation status

P7-T03 completed repository gates and accepted-canonical Level-2 validation on 2026-08-30. The
canonical migration-14 database remained byte-identical and the final marker was:

```text
P7_T03_LOCAL_VALIDATION_OK
```

The authoritative detailed validation record remains:

```text
docs/project/tasks/P7-T03.md
docs/project/CURRENT_STATE.md
```

## Non-goals and deferred work

P7-T03 deliberately does not add:

- a persisted `quest -> zone` relation;
- generalized dungeon/raid classification;
- a route optimizer;
- canonical chain-step numbering;
- live character quest state;
- ownership/inventory/bank integration;
- new quest ingestion;
- saved searches or graphical UI.

Those remain separately routed consumer tasks.
