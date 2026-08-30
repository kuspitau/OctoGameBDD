# P7 item query/filter contract

Status: `VALIDATED`

Task: `P7-T01`

This document defines the first stable consumer-facing item query contract over the accepted
migration-14 item-template/stat projection. It does not change source authority, canonical selection,
schema, or acquisition policy.

## 1. Query universe

The query universe is the canonical `items` table. Every row has a native item ID and canonical name.
The migration-14 `item_templates` / `item_stat_modifiers` projection is intentionally partial over
that universe.

A missing `item_templates` row therefore means:

```text
unknown / not materialized under current template coverage
```

It does **not** mean that the item has no quality, armor, resistance, stat, or other P6 template
property in the game.

This is the direct consumer consequence of D-036 and D-037.

## 2. Coverage states

Every returned item exposes template/stat coverage explicitly:

```text
template = materialized | unknown_not_materialized
stat_slots = complete_within_materialized_template | unknown_not_materialized
```

For a materialized template, the P6 source contract treats the ten raw stat slots as a complete set.
Consequently, if a requested raw stat type is absent from `item_stat_modifiers` for a materialized
item, that stat predicate is a **known non-match**. The same absence on an item without a template row
is **unknown**.

No default or fallback value is introduced for an unknown template.

## 3. Predicate states

Each evaluated predicate receives one of:

```text
known_match
known_non_match
unknown
```

Identity/name predicates are evaluated from canonical `items` and are always known. Migration-14
scalar/stat predicates are known only when the template row is materialized.

Multiple predicates use conservative three-valued conjunction:

1. any known false predicate -> `known_non_match`;
2. otherwise any unknown predicate -> `unknown`;
3. otherwise -> `known_match`.

This matters when an item is already ruled out by a known identity/name predicate: another unavailable
template predicate does not make the conjunction unknown.

## 4. Supported P7-T01 filters

The stable library surface is:

```python
octogamedb.item_search.query_items(...)
```

P7-T01 supports:

- native item ID;
- case-insensitive name substring;
- exact quality;
- exact class/subclass IDs;
- exact inventory type;
- minimum/maximum item level;
- minimum/maximum required level;
- minimum armor;
- minimum durability;
- minimum holy/fire/nature/frost/shadow/arcane resistance;
- repeatable raw stat-type minimums.

Raw stat type IDs remain numeric. A stat predicate matches when at least one materialized raw slot of
that type meets the minimum; repeated slots are not summed or otherwise combined without a separate
semantic rule. P7-T01 does not invent labels before a validated enum/DBC contract exists.

The previous P6 helper `query_item_templates()` remains available unchanged in behavior for existing
callers. New consumers should use `query_items()` because it exposes unknown coverage instead of
silently restricting the universe to materialized templates.

## 5. Output and provenance

`query_items()` returns:

- exhaustive summary counts over canonical item identities;
- materialized vs unknown template counts;
- exhaustive `known_match` / `known_non_match` / `unknown` counts for the requested predicates;
- a bounded result page;
- per-result template/stat coverage;
- current materialized scalar values, or `None` when unknown;
- ordered raw stat modifiers;
- per-predicate state and observed value;
- selected `template.*` provenance trace with source revision, selection policy and reason.

Only returned materialized templates load detailed provenance traces. Summary classification still
covers the entire canonical item identity universe before the output limit is applied.

`item_query_page_to_dict()` defines the deterministic JSON-friendly representation.

## 6. Sorting and bounds

Supported sort keys are:

```text
item_id
name
quality
class_id
subclass_id
inventory_type
item_level
required_level
armor
max_durability
holy_resistance
fire_resistance
nature_resistance
frost_resistance
shadow_resistance
arcane_resistance
```

Ordering is deterministic. When the selected sort field is unavailable because template coverage is
unknown, known values are ordered first and unknown values are placed last. Native `item_id` provides
the deterministic tie-break/order for unknown values.

The output limit is mandatory and constrained to `1..1000`. It bounds returned rows, not the
exhaustive state counts in the summary.

By default only `known_match` rows are returned. Callers may additionally request
`known_non_match` and/or `unknown` rows for diagnostics or exploration.

## 7. CLI

The read-only CLI is:

```text
python -m octogamedb.item_query_cli
```

Representative commands:

```text
python -m octogamedb.item_query_cli --quality 3 --max-required-level 40 --json
python -m octogamedb.item_query_cli --inventory-type 5 --stat 3:10 --stat 7:5 --json
python -m octogamedb.item_query_cli --min-armor 100 --include-unknown --sort-by armor --desc
```

The CLI opens the SQLite database with `mode=ro`, does not apply migrations, does not trigger
acquisition, and does not create or update canonical data.

## 8. Explicit non-goals

P7-T01 does not add:

- schema migrations;
- source-priority or canonical-selection rules;
- fallback/default item-template values;
- automatic P6 acquisition/promotion;
- weapon damage/speed/block semantics;
- item effects/spells/tooltips;
- weighted scores or derived optimization rankings;
- saved searches;
- item acquisition traversal;
- graphical UI.

Those remain later bounded P7/P8 tasks when justified by a concrete consumer requirement.

## 9. Validation closure

Level 1 proved on a synthetic migration-14-shaped database:

- known match / known non-match / unknown separation;
- complete-stat-set behavior for materialized templates;
- combined predicates;
- deterministic sorting and limits;
- selected template provenance;
- deterministic JSON output;
- compatibility of the P6 helper;
- CLI byte-level read-only behavior;
- validator byte-level read-only behavior.

Focused result:

```text
9 passed
```

Human Level 2 completed on 2026-08-30 against the accepted real canonical baseline. The validator ran
on a TEMP byte-identical snapshot and returned:

```text
P7_T01_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
item_identities=23336
materialized_templates=18
unknown_templates=23318
match_sample_item_id=3565
nonmatch_sample_item_id=3565
unknown_sample_item_id=1
stat_sample=3565:type4>=3
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

The original canonical DB and the TEMP snapshot compared byte-identical before and after the complete
validation. P7-T01 is therefore `VALIDATED`.
