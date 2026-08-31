# P7 world-entity query contract

Status: `VALIDATED`

Task: `P7-T05`

Implementation base:

```text
e7a25cc84df122bf2f3675a0acba262c99c8e43f
Validate P7-T04 recipe exploration and route P7-T05
```

This contract defines the first bounded first-class creature/gameobject consumer surface over the
already-validated P1 world model. It composes P2 item-acquisition/vendor, P3 quest-role/objective and
P4 trainer evidence at query time. It adds no migration, source authority, source merge rule or
canonical fact. All operations are read-only.

## Public surfaces

```text
src/octogamedb/world_entity_search.py
  query_world_entities()
  world_entity_query_page_to_dict()

src/octogamedb/world_entity_cli.py
  python -m octogamedb.world_entity_cli ...
```

The CLI opens SQLite with URI `mode=ro`.

## Search universe

The query universe is the canonical P1 template tables:

```text
creatures
gameobjects
```

Template identity remains separate from spawn identity. A returned template may have zero, one or
many canonical spawn rows. P7-T05 does not create a persisted `entity -> zone` relation.

Supported predicates are:

- entity kind: `creature` or `gameobject`;
- exact native/canonical entity ID;
- case-insensitive canonical name substring;
- derived spawn zone ID;
- derived spawn map ID;
- deterministic sort by `entity_id`, `name` or `entity_kind`;
- bounded `1..1000` result limit.

Only already-materialized P1 template attributes are exposed. P7-T05 does not infer additional DBC
fields.

## Three-state evaluation

The query surface uses:

```text
known_match
known_non_match
unknown
```

Canonical kind/ID/name predicates are complete for the canonical template universe and therefore may
produce known positive or negative results.

Geography follows the stricter P1/D-026 rule:

1. any canonical spawn matching all requested zone/map constraints proves `known_match`;
2. a selected `spawn_set` can prove `known_non_match` only when the set of its **distinct
   `spawn_key` identities** exactly covers the current canonical materialized spawn view for the
   entity;
3. a selected member missing from canonical materialization, an extra protected/custom canonical
   spawn outside the selected set, or a requested zone/map that is unresolved for any member makes
   the negative unprovable and therefore `unknown`;
4. absence of a selected complete spawn set is `unknown`, not universal absence.

Selected source evidence may repeat the same `spawn_key`. Such duplicate serialized members remain
visible in the selected provenance payload but do not represent additional canonical spawn identities.
P7-T05 therefore deduplicates only by `spawn_key` for complete-set membership comparison and reports
the source duplicate count/keys explicitly. This is query normalization of D-026 membership evidence,
not a rewrite of provenance or a new merge/source-priority rule.

An empty selected complete set can therefore prove a bounded negative for the selected effective P1
source view when the canonical materialized view is also empty. This is not a universal game-world
absence claim.

## Spawn detail and provenance

Every canonical spawn remains independent and includes:

- `spawn_id` and stable `spawn_key`;
- coordinate space;
- x/y/z and orientation;
- respawn seconds when materialized;
- zone ID/name;
- map ID/name derived with the existing P1 `COALESCE(spawn.map_id, zone.map_id)` rule;
- selected `position` provenance when available;
- selected `respawn_seconds` provenance when available.

The entity also exposes selected `spawn_set` coverage:

- raw selected source member count;
- distinct selected `spawn_key` member count;
- duplicate source member count and duplicate `spawn_key` list;
- materialized selected member count;
- total canonical materialized count;
- unresolved selected members;
- extra canonical materialized spawns;
- whether the selected set exactly covers the canonical view;
- selected source/revision/selection evidence.

Selected `world_presence` is exposed separately with the explicit semantic label
`source_effective_view_not_universal_existence`.

## Item acquisition roles

P7-T05 reverses only the already-materialized P2 relations in which the entity participates.

For creatures:

```text
direct creature loot
reference-loot membership
vendor relation
```

For gameobjects:

```text
direct gameobject loot
reference-loot membership
```

Each item remains distinct and may contain several acquisition paths. Each path preserves:

- path kind `direct`, `reference` or `vendor`;
- exact per-path drop chance for direct/reference loot;
- reference-loot ID for reference paths;
- selected item relation provenance;
- selected reference-membership provenance;
- vendor `max_count` from the selected `vendor_source` payload.

Vendor `max_count` is never interpreted as probability, and independent direct/reference paths are
never probability-aggregated.

## Quest roles

Quest roles remain independent:

```text
giver
finisher
objective creature
objective gameobject
```

Materialized P3 endpoint/objective rows are returned with their selected relation provenance. P7-T05
also reads selected endpoint/objective relation evidence for the inspected entity so a selected
relation that is not materialized remains explicit rather than disappearing. Such a row carries:

```text
relation_materialized = false
relation_resolution_reason = selected_relation_not_materialized
```

The owning quest ID/name resolution is shown independently. Full quest traversal/progression detail
remains owned by P7-T03; the world-entity row contains `quest_detail_owner = P7-T03` rather than
copying that graph.

Semantic quest role is not derived from entity geography. A giver is not silently a finisher or an
objective.

## Trainer roles

Only creatures can expose trainer relations. P7-T05 reads validated P4 `recipe_trainer_sources` rows
for the inspected native trainer entry and preserves:

- `direct` vs `template` trainer kind;
- native trainer entry;
- nullable canonical creature resolution;
- trainer template ID only for template-expanded rows;
- acquisition wrapper spell/proof fields;
- trainer cost, required skill and required character level;
- selected trainer-source provenance.

An unresolved P4 `creature_id` remains unresolved even if the native entry is visible in the entity
view; P7-T05 does not fabricate a direct trainer fact. Full recipe detail remains owned by P7-T04 and
is referenced with `recipe_detail_owner = P7-T04`.

## Template provenance

For already-materialized template fields, selected provenance is returned when available. Creature
fields are limited to the current P1 canonical columns (`name`, level range, faction, classification,
creature type and NPC flags). Gameobjects expose `name` and `object_type` only.

P7-T05 creates no selection policy and never re-resolves competing observations.

## Determinism and bounds

For a fixed DB and argument set, candidate evaluation, sorting, role ordering and JSON conversion are
deterministic. Geography data and selected `spawn_set` evidence are preloaded once when a geography
predicate is active; expensive role/provenance detail is loaded only for results retained after state
selection, sort and limit.

## CLI examples

```text
python -m octogamedb.world_entity_cli --kind creature --entity-id 198 --json
python -m octogamedb.world_entity_cli --name-contains trainer --kind creature --json
python -m octogamedb.world_entity_cli --kind creature --zone 1519 --json
python -m octogamedb.world_entity_cli --kind gameobject --map 0 --include-unknown --json
python -m octogamedb.world_entity_cli --zone 12 --sort-by name --limit 50 --json
```

The IDs above are examples only. Accepted-canonical validation discovers representative IDs
dynamically.

## Validation

Focused synthetic tests cover:

- creature/gameobject ID and name search;
- independent multi-spawn retention;
- selected spawn provenance;
- duplicate selected `spawn_set` members normalized by distinct `spawn_key` for coverage while
  retaining explicit duplicate diagnostics;
- positive geography;
- complete-set bounded negative geography;
- unknown geography without a complete set;
- protected/materialized extra spawn -> `unknown`;
- unresolved map -> `unknown`;
- direct/reference loot paths;
- vendor relation and stock/count separation from chance;
- quest giver/finisher/objective separation;
- selected unmaterialized quest relation;
- direct/template/unresolved trainer rows;
- unlocated templates;
- deterministic sorting/limit/JSON;
- read-only CLI byte preservation.

Accepted-canonical validation is provided by:

```text
python scripts/validate_p7_t05.py --db data/generated/octogamedb.sqlite3
```

The validator is read-only, discovers representative IDs at runtime, checks schema version 14,
foreign keys/integrity, the accepted canonical SHA before/after, and must end with:

```text
P7_T05_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

## Validated human closure — 2026-08-31

The corrected integrated repository passed all required human gates:

```text
pytest --basetemp="$env:TEMP\OctoGameDB_pytest"
346 passed in 14.51s

python -m ruff check src tests
All checks passed!

python -m compileall -q src tests scripts
PASS

P7_T05_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
creature_identities=13842
gameobject_identities=20967
duplicate_spawn_set_sample_kind=creature
duplicate_spawn_set_sample_id=1852
duplicate_spawn_set_member_count=1
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

The dynamic sample IDs are observations rather than acceptance constants. The closure confirms the
real-data duplicate-membership shape, clean schema/FK/integrity checks and byte-identical preservation
of the accepted canonical database.

P7-T05 is therefore `VALIDATED`. This file is the authoritative bounded world-entity query contract
unless a later explicit decision supersedes it.

## Next routing action

Commit/push the complete validated P7-T05 working tree plus this closeout. After a fresh GitHub `main`
resolve confirms that integration, route `docs/project/tasks/P7-T06.md`. Do not implement P7-T06 on
the older `e7a25cc84...` base.

## Non-goals

P7-T05 does not add:

- new world/template/spawn ingestion;
- a global source merge/priority rule;
- a persisted universal `entity -> zone` relation;
- route planning or graphical maps;
- generalized zone/dungeon views;
- creature combat/stat simulation;
- item ownership/inventory/bank state;
- AH/economic/craft-profit logic;
- saved searches, weighted scores or UI configuration.
