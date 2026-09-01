# P7 zone-centric query contract

Status: `VALIDATED`

Task: `P7-T06`

Implementation base:

```text
97625087922318bde253657856bae97d6383116c
Validate P7-T05 world entity exploration and route P7-T06
```

This contract defines the first bounded first-class zone consumer surface over the validated
P1/P2/P3/P4 and P7-T02..P7-T05 read models. It adds no migration, source authority, ingestion policy,
canonical selection policy or persisted `zone -> everything` relation. All operations are read-only.

## Public surfaces

```text
src/octogamedb/zone_search.py
  query_zones()
  zone_query_page_to_dict()
  inspect_zone()

src/octogamedb/zone_recipe_projection.py
  project_zone_recipes()

src/octogamedb/zone_cli.py
  python -m octogamedb.zone_cli ...
```

The CLI opens SQLite with URI `mode=ro`.

## Layering

P7-T06 remains a derived composition layer:

```text
canonical zone/map identity
+ P7-T05 world-entity/spawn/role projection
+ P7-T02/P7-T03/P7-T04-owned item/quest/recipe relation semantics
+ compact positive recipe-learning inversion over the already computed zone evidence
-> P7-T06 zone-centric exploration
```

The zone view is not primary truth. It does not persist:

```text
zone -> creature/gameobject
zone -> item
zone -> quest
zone -> recipe
entity -> zone
recipe -> zone
```

Concrete geography remains owned by spawn/location relations and by the role-specific P7 contracts.

## Zone identity search

`query_zones()` searches the canonical `zones` universe and preserves zone, parent-zone and map
identity separately. Supported predicates are:

- exact native/canonical zone ID;
- case-insensitive zone-name substring;
- exact canonical map ID;
- case-insensitive canonical map-name substring;
- deterministic sort by `zone_id`, `name`, `map_id` or `map_name`;
- bounded `1..1000` result limit.

Map predicates are `unknown` when a zone's map identity/name is not materialized. Known canonical
identity/name mismatch can be `known_non_match`. Unknown map sort values stay after known values in
both ascending and descending order.

Selected zone/map name provenance is exposed when present. Parent-zone and parent-map identity are
navigation metadata, not implicit containment/classification rules beyond the canonical columns.

## Detailed zone inspection

`inspect_zone()` accepts exactly one canonical zone ID and composes bounded detail. This split is
intentional: a broad zone-name search does not trigger `N zones x full corpus` detail scans.

Controls:

```text
entity_limit: 1..1000
recipe_limit: 1..1000
include_recipes: bool = true
```

The world/entity projection delegates to P7-T05 once for the inspected zone. Item, quest, vendor and
trainer sections are then inverted from the returned concrete zone entities. When recipes are enabled,
P7-T06 derives compact positive recipe-learning evidence from those already-computed zone roles instead
of re-running the complete P7-T04 geography evaluator.

`include_recipes=false` leaves all non-recipe zone projections valid while explicitly reporting that
recipe projection was skipped; this never authorizes a recipe absence claim.

## World entities present

P7-T06 asks P7-T05 for `known_match` world entities whose concrete canonical spawn geography resolves
to the inspected zone. Every returned zone entity keeps:

- creature/gameobject identity and template fields;
- template/world-presence provenance already exposed by P7-T05;
- independent matching spawn rows;
- selected spawn position/respawn provenance;
- P7-T05 `spawn_set` completeness/duplicate diagnostics;
- P7-T05 semantic role projection.

Only spawns that concretely match the inspected zone are emitted as `matching_spawns`, while
`all_materialized_spawn_count` records that the entity may also exist elsewhere. P7-T06 never turns a
multi-spawn template into a single location.

The P7-T05 exhaustive geography-state counts are retained. If known matches exceed `entity_limit`,
`truncated_known_matches` is true and every derived role section based on returned entities is a
bounded positive projection.

## Item acquisition in a zone

Item rows are a zone-centered inversion of already validated P7-T05/P7-T02 roles on concretely
located source entities. Paths remain independent:

```text
direct
reference
vendor
```

Each path preserves its existing fields and provenance, including per-path drop chance,
`reference_loot_id`, reference-membership provenance, vendor `vendor_max_count`, selected vendor
provenance and the matching concrete source spawns.

P7-T06 never combines direct/reference probabilities, probabilities across sources/spawns, or vendor
stock metadata. `vendor_max_count` is not a probability.

A source with unresolved/missing geography is not included as a positive zone path and is not proof
that the item cannot be acquired there.

## Quest roles in a zone

P7-T06 keeps P7-T05/P7-T03 semantic roles in separate collections:

```text
given       <- giver
finished    <- finisher
objectives  <- creature/gameobject objective
```

A quest may appear in several collections. Role rows keep quest identity, relation materialization
status, selected provenance and concrete matching source spawns. Selected relation evidence that is
not materialized remains explicitly marked; role geography is never converted into a different quest
role.

This first zone slice intentionally projects creature/gameobject objective geography in the direct
zone role lists. Broader P7-T03 objective geography remains owned by P7-T03.

## Vendors and trainers

Vendor presence is derived only from a known materialized vendor creature relation plus a concrete
creature spawn in the zone. Vendor item rows retain their independent vendor path metadata.

Trainer rows preserve direct/template distinctions and P7-T05/P7-T04 provenance. A trainer relation is
a positive zone trainer only when it resolves to the same canonical creature whose spawn proves zone
geography. An unresolved P4 `creature_id` remains in `unknown_relations` with
`geography_state = unknown`; native-entry resemblance never fabricates the missing canonical relation.

## Recipe-learning sources in a zone

Recipe availability is not collapsed into a generic zone relation. P7-T06 exposes five independent
positive-evidence sections:

```text
teaching_item
trainer
quest_reward_spell.giver
quest_reward_spell.finisher
quest_reward_spell.objective
```

The validated implementation does **not** run the complete P7-T04 query five times. Instead,
`project_zone_recipes()` inverts the positive zone evidence already computed by P7-T06:

- a teaching item known obtainable in the zone identifies recipes taught by that item;
- a resolved trainer present in the zone identifies recipes taught by that trainer;
- a quest-learning recipe is projected independently when its resolved quest appears in the zone as
  giver, finisher or creature/gameobject objective.

Returned recipe rows keep canonical recipe identity, `detail_owner = P7-T04` and
`zone_learning_evidence` describing the positive path that caused inclusion. Full P7-T04 recipe detail
is deliberately not duplicated in the zone view.

For each role the summary records known positive recipe identities and treats the remainder as
`unknown`, not `known_non_match`. This is a positive-evidence projection; absence never establishes
universal recipe unavailability.

## Three-state and coverage semantics

P7-T06 uses the established vocabulary:

```text
known_match
known_non_match
unknown
```

Rules:

1. concrete canonical geography can prove positive inclusion;
2. P7-T05 may retain bounded `known_non_match` evidence under its validated complete `spawn_set`
   contract;
3. unresolved/missing geography remains `unknown`;
4. result truncation never authorizes a negative;
5. P7-T06 introduces no new complete set covering all contents of a zone;
6. compact recipe projection is positive-only and never converts missing evidence to a negative.

Top-level zone-detail coverage therefore deliberately reports:

```text
state = unknown
negative_claim_authorized = false
```

This does not make known positive contents uncertain; it states only that the projection is not a
universal proof that no additional supported or unresolved content belongs to the zone.

## Determinism and bounds

For a fixed database and argument set:

- zone search order is deterministic;
- world-entity order is delegated to deterministic P7-T05 sorting;
- item paths are ordered by path kind/source/reference identity;
- quest rows are ordered by quest/source identity;
- vendor/trainer rows are deterministic;
- recipe identities are selected deterministically by canonical recipe ID;
- compact recipe SQL uses bounded chunks for already-known evidence IDs;
- JSON conversion uses dictionaries/lists/scalars only.

Zone identity search remains explicitly limited rather than offset-paginated in this first slice.

## CLI examples

```text
python -m octogamedb.zone_cli --zone-id 1519 --json
python -m octogamedb.zone_cli --name-contains "strangle" --sort-by name --json
python -m octogamedb.zone_cli --map-id 0 --limit 50 --json
python -m octogamedb.zone_cli --map-name-contains "kalimdor" --json
python -m octogamedb.zone_cli --zone-id 1519 --details --json
python -m octogamedb.zone_cli --zone-id 1519 --details --entity-limit 500 --recipe-limit 250
```

IDs are usage examples only. Accepted-canonical validation discovers representative IDs dynamically.

## Validation coverage

Focused synthetic/integrated P7-T06 tests cover:

- zone ID/name/map search and parent hierarchy;
- missing map evidence -> `unknown`;
- deterministic sort/limit/JSON;
- independent same-zone multi-spawn retention;
- direct/reference/vendor item paths and vendor count/chance separation;
- giver/finisher/creature/gameobject objective role separation;
- vendor projection;
- resolved trainer vs unresolved native trainer relation;
- compact teaching-item/trainer/quest-role recipe projection;
- compact recipe limit/truncation reporting;
- explicit unknown/truncation coverage;
- read-only CLI byte preservation.

Accepted-canonical validation is provided by:

```powershell
python -u scripts/validate_p7_t06.py --db data/generated/octogamedb.sqlite3
```

The validator opens the DB read-only, requires schema 14 and the accepted canonical SHA, dynamically
finds representative zone/multi-spawn/item/quest/trainer/recipe cases, runs foreign-key and integrity
checks, and verifies byte-identical preservation.

## Validated human closure — 2026-09-01

The human confirmed repository pytest, Ruff and compileall all passed. The corrected
accepted-canonical validation then completed:

```text
P7_T06_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
zone_identities=1480
identity_sample_zone_id=1
multi_spawn_sample_zone_id=12
direct_item_sample_zone_id=1
reference_item_sample_zone_id=1
vendor_item_sample_zone_id=1
quest_giver_sample_zone_id=1
quest_finisher_sample_zone_id=1
quest_objective_sample_zone_id=1
teaching_recipe_sample_zone_id=1
trainer_recipe_sample_zone_id=1
quest_recipe_sample_zone_id=3
validated_zone_detail_count=5
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=True
```

The dynamic sample IDs are observations rather than acceptance constants. P7-T06 is therefore
`VALIDATED` and this file is its authoritative bounded zone query contract unless a later explicit
decision supersedes it.

## Runtime/performance finding

The first human Level-2 attempt exposed a pathological full-recipe scan and was interrupted. The final
compact recipe projection fixed that defect. The successful run then measured:

```text
zone 12, without recipes: 27.60 s
zone 1,  without recipes: 31.44 s
zone 14, without recipes: 41.25 s
zone 1,  with recipes:    32.31 s
zone 3,  with recipes:    20.85 s
```

The remaining latency is primarily below the recipe projection, in the world-entity/role/provenance
path. It is retained as measured performance debt and routed to P7-T07. P7-T06 semantics are closed;
performance optimization must preserve this contract.

## Next routing action

Commit/push the complete validated P7-T06 working tree plus this closeout. After a fresh GitHub `main`
resolve confirms integration, route:

```text
docs/project/tasks/P7-T07.md
```

## Non-goals

P7-T06 does not add schema migrations/canonical mutation, new source priority, a universal complete
set of all zone contents, persisted zone shortcuts, generalized dungeon/raid classification, route
planning, faction/accessibility inference, weighted scores, saved searches, ownership state,
economics or graphical UI.
