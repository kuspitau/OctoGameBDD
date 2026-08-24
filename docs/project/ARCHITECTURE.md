# Architecture

## System shape

```text
External / local sources
        |
        v
      RAW
  exact source artifacts
        |
        v
     STAGING
  parsed, source-shaped records
        |
        v
  NORMALIZATION
        |
        v
    CANONICAL
  unified domain entities + relations
        |
        v
     DERIVED
  query projections, inferred geography,
  materialized caches, coverage metrics
        |
        +------------------+
        |                  |
        v                  v
      CLI/AUDIT          UI/API
```

## Layer rules

### Raw

Keep source data as close to the original representation as practical.

Examples:

- cached OctoDB page/API payloads;
- pfQuest Lua data;
- SQL dumps;
- extracted DBC/WDB files.

Raw data is normally local/ignored because of size.

### Staging

Parsed records still shaped according to the source.

Examples:

- `raw_pfquest_units`;
- `raw_tortoise_creature_loot`;
- parsed DBC rows.

Staging is not the canonical game model.

### Canonical

The stable project-owned representation:

- `items`;
- `item_stats`;
- `quests`;
- `creatures`;
- `creature_spawns`;
- `gameobjects`;
- `gameobject_spawns`;
- `recipes`;
- `spells`;
- `zones`;
- maps;
- explicit domain relation tables.

Canonical values must be traceable to provenance or an explicit derivation rule.

### Derived

Facts that can be computed from canonical primitives.

Examples:

```text
CreatureSpawn -> Zone
CreatureLoot  -> Item

therefore:

Item obtainable in Zone
```

Other examples:

- quest giver/finisher zones;
- recipe obtainable zones;
- zone content summaries;
- effective/flattened reference-loot views;
- cached query projections.

Derived data may later be materialized for performance, but that cache is not primary truth.

## One physical database

Use one SQLite database for canonical/project state unless a later measured constraint justifies a change.

Logical domains remain separated by tables/modules. Do not split into `items.db`, `quests.db`, etc. merely for conceptual organization.

## Relations

Prefer explicit tables with foreign-key semantics for important domain relations:

- creature loot;
- game-object loot;
- item/container loot;
- quest rewards;
- quest objectives;
- quest prerequisites;
- recipe reagents/results/sources;
- vendor items;
- trainer spells;
- spawn geography.

Avoid using a single generic `relations(from_type, from_id, relation, to_type, to_id)` table as the primary model. A generic graph projection may be generated later for navigation/UI.

## Geography

`Map`, `Zone/Subzone`, template entities, and spawn instances are separate concepts.

Do not store one arbitrary `zone_id` directly on a creature template when geography is actually represented by multiple spawn instances.

Quest geography can be multi-valued and relation-specific:

- giver;
- finisher;
- objective;
- travel/exploration when explicitly modeled.

## Provenance

Provenance is an architectural requirement.

The implementation must support answering:

- Which source supplied this fact/relation?
- Which source revision/import batch?
- Was it observed, imported, normalized, or derived?
- Were there competing source values?
- Why was a canonical value chosen?

Do not silently destroy losing/conflicting source facts.

## Importer design

Each source importer should:

1. identify source and revision;
2. parse into source-shaped staging structures;
3. normalize through project-owned logic;
4. be idempotent;
5. emit deterministic counts/warnings/errors;
6. be testable using small fixtures;
7. cache remote source artifacts when appropriate rather than repeatedly downloading/scraping them.

Importer summaries should use the shared machine-readable summary contract so the same deterministic counts/details can be consumed by tests, CLI audit surfaces, and saved artifacts.

## Public source inspection

Source adapters must be built from current source evidence rather than guessed formats.

For public addons/projects:

- inspect the primary repository and current implementation;
- consult docs/issues/discussions/history when necessary to resolve material ambiguity;
- capture representative source-shaped fixtures;
- record revisions/versions where parser semantics depend on them.

The user's installed copy is not required merely to understand a public format, but remains important for Octo/version-specific Level 2 validation.

## Local source boundary

Local user-machine paths are runtime/configuration concerns.

Tracked project code must not depend on personal absolute paths.

Use ignored:

```text
config.local.toml
```

for stable local source locations, normally under:

```toml
[source_paths]
```

When a coding handoff first needs missing local paths, provide task-specific discovery/configuration through `get_path.bat` as defined in `docs/project/LOCAL_PATHS.md`.

This keeps parser/importer code portable while still making full local validation reproducible.

## Audit surface

The CLI/audit layer is usable before gameplay-domain schemas are complete.

P0 audit commands operate on import metadata and provenance evidence:

- `source` reports registered sources and import summaries;
- `trace` follows evidence for a subject/fact back to source revision and import batches;
- `conflict` identifies evidence groups with competing distinct values and whether a canonical winner exists;
- `coverage` reports generic provenance/evidence counts.

Audit commands provide human-readable output and deterministic JSON. Generic P0 coverage is not a substitute for later domain-specific completeness metrics; those are added as canonical domains become available.

## Existing projects

Existing projects such as Tortoise-WoW Database Viewer may be studied and selectively reused/adapted where licensing permits, especially for difficult parsing/resolution logic.

Do **not** adopt an external project's final SQLite schema as OctoGameDB's core model merely for convenience. The canonical model belongs to this project.

## Query/UI direction

The first user-facing tool should be a CLI/audit surface.

The later graphical application is expected to be local/browser-based. NiceGUI is a strong candidate because the project is Python-first and needs rich tables/tooltips, but the final UI framework is deliberately deferred until the data layer is reliable.

A future split frontend/API remains possible without changing the canonical database design.
