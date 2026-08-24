# Data Sources

The project is intentionally multi-source. No single external database is assumed to be perfectly exhaustive or perfectly authoritative for Octo.

## Priority concept

Do **not** hard-code one universal total order for every field.

Use source-aware and field/relation-aware resolution policies. As a default conceptual hierarchy:

1. Octo-specific authoritative/maintained sources;
2. data observed/extracted directly from the Octo client/server interaction;
3. close Turtle 1.18.x sources;
4. Vanilla VMaNGOS/CMaNGOS-style baselines;
5. fallback/community data where explicitly approved.

Preserve disagreements even when a canonical winner is selected.

## Primary sources

### OctoDB

- URL: `https://octowow.st/db/`
- Role: primary Octo-specific reference for items/NPCs/quests/objects/spells and their relations where exposed.
- Import strategy:
  - cache raw pages/payloads;
  - parse reproducibly;
  - rate-limit politely;
  - record source URL/ID and retrieval/import metadata;
  - do not repeatedly hit the website when cached source data exists.

### pfQuest

- Repository: `https://github.com/shagu/pfQuest`
- Role: broad Vanilla-style structured Lua dataset; useful skeleton for units, objects, quests, items, zones, coordinates and relations.

### pfQuest-octo

- Repository: `https://github.com/paokkerkir/pfQuest-octo`
- Role: Octo-specific additions/overwrites for pfQuest; especially valuable for custom content, coordinates, quest/object/unit corrections and relations.

When pfQuest base and pfQuest-octo differ, preserve both source identities and apply explicit Octo override semantics during normalization.

### Octo client DBC

Extract from the user's actual Octo client where available.

Useful areas include:

- maps/zones/area hierarchy;
- spells and icons;
- skill/profession data;
- item display/set/random-property metadata;
- creature types/families/display data;
- locks/factions/talents and other client-side reference tables.

These files are local/large and normally remain outside Git.

### Octo client WDB cache

Potential files include item/creature/gameobject/quest caches.

Role:

- highly valuable direct observations from Octo;
- useful for custom entries and conflict checking.

Limitation:

- cache coverage depends on what the client has actually queried, so it is not inherently exhaustive.

## Secondary / enrichment sources

### Tortoise-WoW 1.18.1 restoration data

- Repository: `https://github.com/Penqle/tortoise-wow`
- Role: close Turtle-lineage SQL world data for creatures, spawns, game objects, quests, vendors, loot, spells and other world structures.
- Treat as enrichment/fallback, not automatically as Octo truth.

### Tortoise-WoW Database Viewer

- Repository: `https://github.com/Xian55/tortoise-db-viewer`
- Role: technical reference for parsing, normalization, loot-reference resolution, DBC+SQL joins, spell/item/recipe reconstruction and local SQLite exploration.
- Strategy: study/selectively adapt useful algorithms where licensing allows; do not adopt its final schema as OctoGameDB's canonical architecture.

### VMaNGOS / CMaNGOS / ClassicDB lineage

Useful for:

- Vanilla baselines;
- loot templates;
- quest/world structures;
- cross-checking missing or unchanged content;
- identifying custom vs baseline data.

Example ClassicDB repository:
- `https://github.com/classicdb/database`

## Research vs local extraction

Distinguish two needs.

### Understanding a public source

When implementing an adapter/parser for a public addon or database:

- inspect the current primary repository/source;
- follow relevant code references;
- consult docs/issues/discussions/history when the format or semantics are unclear;
- do not infer field meaning from memory alone;
- do not require the user's installed addon solely to learn a public format.

### Accessing the user's local source data

When the actual installed/local source is needed for extraction or Level 2 validation:

- read `docs/project/LOCAL_PATHS.md`;
- use `config.local.toml` for stable machine-specific paths;
- generate `get_path.bat` when required paths are not already configured;
- validate the located source/version before importing.

This distinction allows coding agents to build correct adapters from public evidence while the human later validates against their exact Octo installation.

## Source registry requirements

Every importer must register:

- stable source key;
- human-readable name;
- source kind;
- source URL/path when appropriate;
- source revision/commit/build when available;
- retrieval/import timestamp;
- parser/importer version if useful.

Every import run should create an import-batch record with:

- rows read;
- rows accepted;
- rows skipped;
- warnings;
- errors;
- inserted/updated counts;
- source revision.

## Licensing

Before copying/adapting code or redistributing extracted data from third-party projects, verify the relevant license and redistribution terms.

The repository should favor code that can rebuild local data from user-provided/downloaded sources rather than committing large third-party datasets.
