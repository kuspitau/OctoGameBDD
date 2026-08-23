# Roadmap

Task IDs are stable handoff references. Do not renumber completed tasks.

## P0 — Repository and data foundation

Goal: establish a trustworthy project-owned persistence/import/test foundation before gameplay-domain breadth.

### P0-T01 — SQLite foundation and import metadata

**Next task.**

Implement:

- SQLite connection/database-location handling;
- versioned migration mechanism;
- foundational metadata tables:
  - schema metadata/version;
  - data source registry;
  - import batches/runs;
- minimal CLI/status command;
- deterministic tests for fresh DB creation and repeat initialization.

No gameplay tables, remote downloads, or UI in this task.

### P0-T02 — Provenance/conflict primitives

Define and implement project-owned primitives sufficient to preserve:

- source observations;
- provenance of scalar facts and relations;
- competing values;
- canonical-selection metadata.

Do not over-generalize before representative domain cases exist.

### P0-T03 — Fixture/golden-case and audit skeleton

Add:

- fixture conventions;
- initial golden cases;
- CLI/audit scaffolding for source/trace/conflict/coverage commands;
- machine-readable import summaries.

## P1 — World foundation

Implement canonical:

- maps;
- zones/subzones;
- creatures;
- creature spawns;
- game objects;
- game-object spawns.

Build the first small end-to-end vertical slice from representative source fixtures before attempting full-world ingestion.

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
