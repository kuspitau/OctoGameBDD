# Roadmap

Task IDs are stable handoff references. Do not renumber completed tasks.

## P0 — Repository and data foundation

Goal: establish a trustworthy project-owned persistence/import/test foundation before gameplay-domain breadth.

### P0-T01 — SQLite foundation and import metadata

**Validated.**

Implemented and present on GitHub `main`:

- SQLite connection/database-location handling;
- versioned packaged SQL migration mechanism;
- foundational metadata tables:
  - schema migrations;
  - data source registry;
  - import batches/runs;
- minimal `python -m octogamedb status` CLI;
- deterministic tests for fresh DB creation, repeat initialization, constraints and CLI status.

### P0-T02 — Provenance/conflict primitives

**Validated.**

Present on GitHub `main` at commit `587146435e44960aaebf7105979a79516102f26e`:

- generic evidence groups for scalar and relation fact slots;
- relation-instance keys so multi-valued relations are not automatically conflicts;
- stable source observations keyed by source revision, with per-run import-batch links;
- deterministic/idempotent observation payload recording across repeated imports of the same revision;
- preservation of competing scalar and relation observations;
- explicit canonical-selection policy/reason metadata;
- same-group foreign-key enforcement for canonical winners;
- schema-v1 -> schema-v2 migration coverage and provenance/conflict tests.

The generic structures are evidence/provenance storage, not a replacement for explicit canonical gameplay relation tables.

### P0-T03 — Fixture/golden-case and audit skeleton

**Validated.**

Present on GitHub `main` at commit `780ccadee17a0015125c2ba4aada0d30e747edff`:

- fixture conventions separating source-shaped parser samples from synthetic semantic golden cases;
- initial provenance/audit golden case;
- generic source/trace/conflict/coverage audit functions;
- corresponding CLI commands with text and deterministic JSON output;
- reusable machine-readable import summaries;
- tests covering conflict semantics, traceability, coverage invariants, CLI output, and summary serialization.

The follow-up local-source path and in-ZIP handoff-helper workflow amendment is present on `main` at `fc0dbe0fc22610113bfc8bd9c1e07cb41d400a39`. With the full P0 foundation on the source-of-truth branch, P0 is closed for normal task routing.

## P1 — World foundation

Implement canonical:

- maps;
- zones/subzones;
- creatures;
- creature spawns;
- game objects;
- game-object spawns.

Build the first small end-to-end vertical slice from representative source fixtures before attempting full-world ingestion.

### P1-T01 — World schema and pfQuest fixture vertical slice

**Validated.**

Present on GitHub `main` at commit `d4310762f1e00b2664cb6d39eadf3e9abd407c46`:

- schema migration 3 with the six P1 canonical world tables;
- native template/zone/map IDs and template-vs-spawn separation;
- explicit `zone_percent` vs future `world` spawn coordinate spaces;
- a source-shaped pfQuest fixture parser/importer pinned to inspected upstream revision `104f35678ca39ab1fb78b655f815cc7016f5e0c8`;
- provenance-aware, idempotent canonical materialization;
- deterministic spawn identities where pfQuest provides no native spawn ID;
- a small creature/game-object location query with selected-source attribution;
- Level 1 parser/schema/import/query tests.

P1-T01 intentionally did not infer authoritative map/parent-zone identity from pfQuest source geometry and did not perform full-world ingestion.

### P1-T02 — Octo DBC map/area hierarchy vertical slice

**Validated.**

Present on GitHub `main` at commit `3302785ba6ece92df6c45df379420484d4eacb23`:

- dependency-free classic WDBC parsing for local Octo client `Map.dbc` and `AreaTable.dbc`;
- deterministic SHA-256 revision identity for the exact DBC pair;
- canonical map identity/type and area -> map / subzone -> parent-area hierarchy using the existing migration-3 schema;
- an explicit field-specific source-selection policy that allows direct Octo client DBC map/area facts to supersede lower-authority observations while preserving all evidence;
- source-only preservation of additional Map/AreaTable fields not yet promoted to canonical columns;
- derived map context for zone-only spawns through `zones.map_id`, without copying the map into the spawn row or changing `zone_percent` semantics;
- synthetic WDBC fixtures and Level 1 parser/import/idempotency/provenance/query tests;
- local-path handoff for `[source_paths].octo_dbc` and real-client compatibility for isolated unnamed AreaTable rows.

P1-T02 deliberately does not implement MPQ extraction, world-coordinate conversion, full DBC ingestion, or overlay reconciliation.

### P1-T03 — pfQuest Turtle/Octo effective world views and comparison

**Validated and present on GitHub `main`.**

Present at commit `034c5914457d6ef29a20ec28e690d2fb753d1356`:

- treats installed `pfQuest + pfQuest-turtle` as the primary current local overlay view to inspect;
- uses reviewed public `KameleonUK/pfQuest-turtle` revision `5b8eeeeb4119be9d075087f0f0e08c187b35ad61` as format/behavior evidence while treating the installed addon as version-specific Level-2 input;
- retains `pfQuest-octo` revision `dd3dc1fb80afe7a71e5c8ca8c31ca2a3ef57af67` as an optional Octo-specific comparison source rather than assuming it is globally newer;
- reproduces top-entry Turtle patch semantics: `"_"` deletes and every other patch value replaces wholesale;
- applies direct literal world-table overwrites and the reviewed Turtle phantom-zone cleanup pattern when present, without inventing cleanup absent from the installed addon or executing Lua;
- fails closed on unsupported indirect world-table mutations;
- composes only the existing P1 zones/units/objects enUS world slice into the existing `PfQuestWorldSlice` model;
- compares effective Turtle and Octo views by added/removed/changed entity IDs without selecting a winner;
- validated the launcher-installed Turtle difference where the public phantom-zone cleanup loop is absent.

P1-T03 intentionally does not write to SQLite. This prevents top-entry deletion and replaced spawn-list semantics from being silently forced into scalar canonical-selection behavior.

### P1-T04 — overlay provenance/canonical reconciliation

**Present on GitHub `main` at commit `582810dfe6ae41e4eec9af303d6f98a772830ef8`.**

P1-T04 consumes the P1-T03 effective-view contract without adding a migration:

- records source-view entity membership as scalar `world_presence` evidence so an overlay deletion is negative source evidence rather than a universal tombstone;
- records creature/game-object complete spawn membership as deterministic `spawn_set` evidence;
- registers base pfQuest, current Turtle overlay and optional Octo overlay as distinct source identities/revisions;
- lets the installed Turtle effective view supersede only default/base pfQuest selections for the bounded P1 world fact family;
- preserves explicit/non-pfQuest selections and leaves D-025 DBC geography authority unchanged;
- reconciles Turtle additions/changes into the existing canonical world tables;
- removes stale canonical spawns selected from the managed pfQuest family when absent from the selected complete Turtle set, while retaining their historical provenance;
- retains removed template/zone identity rows when selected non-pfQuest evidence or canonical dependencies still support them;
- records optional `pfQuest-octo` differences as comparison evidence without automatic canonical mutation;
- requires an already imported matching base pfQuest revision so a later base import cannot reintroduce stale spawns within the same validation flow;
- adds focused idempotence/provenance/protection tests.

P1-T04 is the bounded closure of the P1 overlay-reconciliation ambiguity. Full-world import remains deferred to P6.

## P2 — Items and acquisition

Implement:

- items;
- item stats/effects/requirements;
- creature loot;
- game-object loot;
- item/container loot;
- specialized loot families as needed;
- vendors;
- source/location queries.

Add reference-loot handling when required by the chosen source.

### P2-T01 — first item/acquisition vertical slice

**Validated.**

P2-T01 establishes the first bounded item/acquisition path on top of the P0/P1 foundation:

- migration 4 adds canonical `items`, `creature_loot`, and `gameobject_loot`;
- parses pfQuest item names plus direct `U` creature and `O` game-object loot relations;
- preserves source-listed drop chance percentages and provenance;
- preserves native item/source IDs and explicit domain relation tables;
- retains named direct-loot targets as relation-only templates when the static P1 world has no
  canonical template, without inventing spawns/geography;
- still fails closed when neither canonical P1 identity nor pfQuest enUS identity exists;
- derives item geography through P1 spawns/zones/maps rather than storing `item -> zone` truth;
- passes full-data idempotence and provenance validation.

Full-data validation observed `17,712` items, `198,811` creature-loot links, `8,298` game-object-loot
links, `10,209` deferred reference-loot links, and `13,860` deferred vendor links.

### P2-T02 — pfQuest reference-loot resolution

**Next bounded task.**

Resolve the `R` reference-loot family that P2-T01 deliberately counted but did not materialize. The
task must first establish pfQuest's exact reference-loot representation and expansion semantics from
primary source code, then add the smallest provenance-preserving canonical representation/query
behavior needed to make referenced loot contribute correctly to item acquisition.

P2-T02 must preserve direct `U`/`O` semantics, avoid duplicating derived source geography, remain
idempotent, and use reduced source-shaped fixtures before full-data validation. Vendor `V` relations
remain deferred unless reference-loot semantics prove they are inseparable.

## P3 — Quests

Implement:

- quest identity/restrictions;
- givers;
- finishers;
- prerequisites/follow-ups;
- objectives;
- required items;
- rewards (guaranteed vs choice);
- derived quest geography.

## P4 — Spells and crafting

Implement:

- spells required for item/recipe relationships;
- recipes;
- profession/skill requirements;
- results;
- reagents;
- learning/acquisition sources;
- recipe item / teaching spell / crafted item distinctions;
- derived recipe availability.

## P5 — Resolution, auditing and coverage

Expand:

- source-specific resolution policies;
- conflict inspection;
- trace/provenance views;
- coverage metrics;
- source-difference reports;
- data-quality checks;
- idempotency checks.

Example coverage metrics:

- items with stats/source/icon;
- creatures with spawns/zones/loot;
- quests with giver/finisher/objectives/rewards;
- recipes with result/reagents/source.

## P6 — Full Octo import

Scale importers to full available data from:

- pfQuest;
- current pfQuest-turtle;
- pfQuest-octo where it contributes distinct Octo evidence;
- OctoDB;
- client DBC/WDB;
- selected Turtle/Vanilla enrichment sources.

Profile performance and database size. Keep the full generated DB local.

## P7 — Graphical explorer

Build local UI with entity tabs/views:

- Items
- Quests
- Creatures
- GameObjects
- Recipes
- Spells
- Zones

Core capabilities:

- search;
- sorting/filtering;
- configurable columns;
- clickable cross-entity navigation;
- WoW-like item tooltips;
- source/provenance inspection;
- spawn maps.

NiceGUI is the current leading candidate but remains uncommitted until this phase.

## P8 — Advanced queries

Add:

- query builder;
- saved searches;
- weighted stat profiles/scores;
- item comparisons;
- advanced cross-domain filters;
- richer map views;
- optional materialized derived views after measurement.

## Development strategy

Do not use "import the whole game" as the first acceptance test.

For each new domain:

1. use small representative fixtures;
2. validate semantics and provenance;
3. add golden cases;
4. then scale to full local data.
