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

**Implemented — awaiting local validation.**

This delta resolves the main geography dependency intentionally deferred by P1-T01:

- dependency-free classic WDBC parsing for local Octo client `Map.dbc` and `AreaTable.dbc`;
- deterministic SHA-256 revision identity for the exact DBC pair;
- canonical map identity/type and area -> map / subzone -> parent-area hierarchy using the existing migration-3 schema;
- an explicit field-specific source-selection policy that allows direct Octo client DBC map/area facts to supersede lower-authority observations while preserving all evidence;
- source-only preservation of additional Map/AreaTable fields not yet promoted to canonical columns;
- derived map context for zone-only spawns through `zones.map_id`, without copying the map into the spawn row or changing `zone_percent` semantics;
- synthetic WDBC fixtures and Level 1 parser/import/idempotency/provenance/query tests;
- local-path handoff for `[source_paths].octo_dbc` and required Level-2 validation against the user's actual client files.

P1-T02 deliberately does not implement MPQ extraction, world-coordinate conversion, full DBC ingestion, or pfQuest-octo reconciliation.

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
- pfQuest-octo;
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
