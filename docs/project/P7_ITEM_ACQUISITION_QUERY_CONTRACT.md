# P7 item acquisition/source query contract

Status: `VALIDATED`

Task: `P7-T02`

This document defines the consumer-facing composition of the validated P7-T01 item predicate contract
with the validated P2 direct/reference/vendor acquisition graph and P1 source geography. It changes no
source authority, canonical selection, schema, acquisition ingestion policy or canonical DB state.

## 1. Layering

P7-T01 remains authoritative for item identity/template/stat semantics:

```text
canonical items
+ partial materialized item_templates/item_stat_modifiers
-> P7-T01 item predicate state
```

P7-T02 adds a read-only acquisition exploration layer:

```text
P7-T01 item result
+ P2 find_item_sources(item_id)
+ P1 source spawn -> zone -> map
-> P7-T02 combined result
```

P7-T02 does not duplicate direct/reference/vendor resolution and does not persist an `item -> zone`
relation.

## 2. Stable library surface

```python
from octogamedb.item_acquisition_search import query_item_acquisitions
```

The function accepts the P7-T01 item predicate options plus:

```text
path_kinds:        direct | reference | vendor
source_kinds:      creature | gameobject
min_drop_chance:   finite 0..100 percentage
zone_id:           native canonical zone ID
map_id:            native canonical map ID
```

Returned rows preserve the full P7 item result and expose:

```text
combined_match_state
acquisition_filter.state
acquisition_filter.reason
acquisition_filter.matching_source_count
acquisition_filter.matching_path_count
sources
matching_sources
```

`sources` is the existing canonical/derived P2 source projection for the item. `matching_sources` is a
filtered projection containing only paths that satisfy the requested acquisition predicate.

## 3. Acquisition paths

Path kinds keep their P2 meanings:

### `direct`

```text
Item -> Creature/GameObject
```

The path retains its selected `loot_source` provenance and source-listed `chance_percent`.

### `reference`

```text
Item -> LootReference -> Creature/GameObject member
```

The path retains both the selected item -> reference provenance and the selected reference membership
provenance. The item-side reference chance remains the path chance.

### `vendor`

```text
Item -> vendor Creature
```

Vendor paths have no drop chance. `vendor_max_count` is preserved separately and is not a probability,
price or restock-time field.

## 4. Probability rule

P7-T02 filters only a path's own known `chance_percent`.

It never:

- treats vendor `max_count` as chance;
- combines direct and reference probabilities;
- combines probabilities across spawns/sources;
- invents an independence, exclusivity or aggregate-drop model.

When multiple paths reach the same source/spawn, they remain distinct `acquisition_paths`. If their
known chances differ, the source-level convenience `chance_percent` remains null, consistent with
`find_item_sources()`.

## 5. Geography rule

Acquisition geography is derived:

```text
Item
 -> acquisition path
 -> Creature/GameObject template
 -> Spawn
 -> Zone
 -> Map
```

A source without a canonical spawn remains a valid known acquisition source with:

```text
spawn_key = null
zone_id = null
map_id = null
```

A non-geographic filter can still match that source. A requested zone/map cannot be proven by an
unlocated source, but the result is unknown rather than a universal non-match.

When a location exists, the returned source keeps the selected spawn `position` provenance already
exposed by P2/P1 query code.

## 6. Positive-evidence filter semantics

All requested acquisition conditions are existentially applied to one concrete source/path pair.

For example:

```text
source_kind=creature
path_kind=direct
min_drop_chance=5
zone_id=33
```

means:

> there exists a known creature source/spawn in zone 33 with a known direct path whose own chance is
> at least 5%.

It does not mean that independent sources may separately satisfy different pieces of the filter.

### Acquisition filter states

```text
known_match
unknown
```

A known concrete path satisfying every requested condition is `known_match`.

If no known concrete path satisfies the filter, P7-T02 returns:

```text
state  = unknown
reason = no_known_matching_path_negative_not_proven
```

P7-T02 does not emit acquisition `known_non_match` merely because a path/geography is absent from the
current canonical projection. P2-T04/P1 source-view completeness evidence is not generalized into a
universal negative claim for arbitrary cross-source consumer predicates.

When no acquisition filter is requested:

```text
state  = not_filtered
reason = no_acquisition_filter_requested
```

and P7-T01 result semantics are unchanged.

## 7. Combined three-state semantics

The P7 item state and acquisition state combine conservatively:

```text
P7 item known_non_match -> combined known_non_match
otherwise P7 item unknown -> combined unknown
otherwise acquisition known_match -> combined known_match
otherwise -> combined unknown
```

This mirrors P7-T01's principle that known false dominates unknown, while refusing to manufacture a
negative acquisition fact from missing evidence.

## 8. Bounding and deterministic order

Returned result limits remain:

```text
1..1000
```

Sorting uses the same P7-T01 item sort fields/order, including unknown sort values last.

With acquisition filters active, the implementation evaluates acquisition before final truncation. It
must not take an already truncated P7-T01 page and post-filter it, because that could omit later known
matches.

Summary combined-state counts are exhaustive over canonical item identities. The returned page alone
is bounded.

## 9. Provenance

P7-T02 preserves, rather than replaces, existing provenance:

- P7 selected `template.*` facts for returned materialized templates;
- direct `loot_source` selected source/revision;
- `loot_reference` selected source/revision;
- reference `loot_source_member` selected source/revision;
- `vendor_source` selected source/revision and `vendor_max_count` payload;
- selected spawn `position` source/revision for located source rows.

No new global source-priority rule is introduced.

## 10. Coverage interpretation

`materialized_acquisition_items` counts canonical item IDs that currently have at least one
materialized P2 acquisition relation in the supported direct/reference/vendor tables. It is a coverage
metric for this projection, not a claim that every other item is unobtainable.

Similarly:

- unresolved reference/source evidence can remain outside a resolved source row;
- a missing spawn means unknown geography;
- a missing supported canonical path is not universal non-acquisition evidence.

## 11. JSON contract

`item_acquisition_page_to_dict()` emits:

```text
summary
results[]
  item                       # stable P7-T01 JSON item shape
  combined_match_state
  acquisition_filter
  sources[]                  # all known P2 sources/paths for returned item
  matching_sources[]         # only paths proving the requested acquisition filter
```

Primitive P2 path dictionaries retain their existing fields, including:

```text
path_kind
chance_percent
reference_loot_id
vendor_max_count
relation_source
reference_membership_source
```

Source dictionaries retain P1-derived geography and `location_source`.

## 12. Read-only CLI

```powershell
python -m octogamedb.item_acquisition_cli [P7 item filters] [acquisition filters]
```

The CLI opens the selected SQLite database with `mode=ro`. It does not apply migrations, import source
data, refresh itemcache, promote P6 facts, or modify the D-029 backup.

## 13. Deliberate non-goals

P7-T02 does not add:

- new acquisition source families;
- weapon damage/speed/block ingestion;
- item spells/effects/tooltips;
- combined probability modeling;
- faction/accessibility modeling;
- weighted scores;
- saved searches;
- ownership/inventory/bank integration;
- generalized recipe/quest traversal;
- graphical maps/UI.

Those require later bounded tasks and, where necessary, explicit additional evidence/source contracts.
## Validation closure

Human/full-data validation completed on 2026-08-30 against the accepted schema-14 canonical DB. The
validator returned:

```text
P7_T02_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
item_identities=23336
materialized_acquisition_items=13113
direct_sample_item_id=1
reference_sample_item_id=647
vendor_sample_item_id=16
located_sample_item_id=1
unknown_acquisition_sample_item_id=2
template_acquisition_sample_item_id=3799
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

The canonical SQLite file remained byte-identical. The contract is therefore validated for the current
P2/P1 acquisition/geography families and the accepted canonical baseline.

