# Data Sources

The project is intentionally multi-source. No single external database is assumed to be perfectly exhaustive or perfectly authoritative for Octo.

## Priority concept

Do **not** hard-code one universal total order for every field.

Use source-aware and field/relation-aware resolution policies. As a default conceptual hierarchy:

1. Octo-specific authoritative/maintained sources;
2. data observed/extracted directly from the Octo client/server interaction;
3. close/current Turtle sources;
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

P1-T01 public-format inspection is pinned to upstream revision:

```text
104f35678ca39ab1fb78b655f815cc7016f5e0c8
```

The relevant P1 world-slice files at that revision are:

```text
db/zones.lua
db/enUS/zones.lua
db/units.lua
db/enUS/units.lua
db/objects.lua
db/enUS/objects.lua
```

The inspected pfQuest code consumes unit/object `coords` entries as positional `{x, y, zone, respawn}` records. X/Y are zone-percentage coordinates. Zone geometry records are also positional and carry pfQuest-specific coordinate/map context; P1-T01 preserves that context as source provenance instead of assigning canonical map/parent-zone semantics without an authoritative mapping.

The tracked P1-T01 source fixture mirrors those six file paths but is deliberately reduced. The parser is a dependency-free Lua literal-table subset parser, not a general Lua interpreter. Full-source compatibility must be expanded and validated deliberately before P6 full ingestion.

#### P2-T01 item/direct-loot format

P2-T01 reuses the same literal-Lua parser and inspects the item tables at the same pinned upstream
revision. The bounded inputs are:

```text
db/items.lua
db/enUS/items.lua
db/enUS/units.lua
db/enUS/objects.lua
```

Relevant source shape:

```text
pfDB["items"]["data"][item_id]["U"][creature_id] = chance_percent
pfDB["items"]["data"][item_id]["O"][gameobject_id] = chance_percent
pfDB["items"]["data"][item_id]["R"] = ...
pfDB["items"]["data"][item_id]["V"] = ...
pfDB["items"]["enUS"][item_id] = item_name
pfDB["units"]["enUS"][creature_id] = creature_name
pfDB["objects"]["enUS"][gameobject_id] = gameobject_name
```

For P2-T01:

- `U` is direct creature-loot evidence;
- `O` is direct game-object-loot evidence;
- the numeric value is preserved as the source-listed drop chance percentage;
- `R` reference-loot and `V` vendor memberships are detected/countable but deliberately not
  materialized yet;
- item identity/name and direct relations carry pfQuest source/revision/import-batch provenance;
- the unit/object enUS tables supply source identity for legitimate direct-loot targets that have no
  static P1 world record or spawn;
- the exact local four-file input set can be identified by a deterministic SHA-256 content revision.

A referenced direct `U`/`O` target may therefore exist as a relation-only canonical template with
no spawn. The importer records the pfQuest-provided name and leaves geography unknown. If the target
is absent both from the P1 world and from the corresponding pfQuest enUS name table, the import
fails closed rather than inventing a placeholder identity.

The P2 fixture under `tests/fixtures/pfquest/items_slice/` is a tiny source-shaped sample, not a
redistribution of the full item database.

The upstream pfQuest repository uses the MIT license. Tracked fixtures contain only minimal
representative structures/records.

### pfQuest-turtle

- Reviewed public repository: `https://github.com/KameleonUK/pfQuest-turtle`
- P1-T03 reviewed revision: `5b8eeeeb4119be9d075087f0f0e08c187b35ad61`
- Role: current Turtle-style pfQuest overlay present in the user's launcher-managed Octo installation; important source for custom/current world data.

Relevant composition evidence:

```text
pfQuest-turtle.toc
patchtable.lua
overwrites.lua
db/zones-turtle.lua
db/enUS/zones-turtle.lua
db/units-turtle.lua
db/enUS/units-turtle.lua
db/objects-turtle.lua
db/enUS/objects-turtle.lua
```

The addon declares a dependency on pfQuest, loads Turtle data/localization tables, then runs `overwrites.lua` before `patchtable.lua`.

The reviewed `patchtable.lua` applies the patch at **top-entry level**:

- if a patch value is the string `"_"`, the base entry is removed;
- otherwise the patch value replaces the corresponding base entry wholesale;
- this is not a recursive merge.

The reviewed Kameleon `overwrites.lua` also removes a documented set of phantom zone IDs from localized Turtle zone tables through a small loop. P1-T03 reproduces this known safe pattern without executing Lua **when the loaded source contains it**.

The launcher-installed copy used for Level-2 validation can differ from the reviewed public revision. In the observed local copy, the phantom-zone cleanup loop is absent, so the effective local view correctly retains entries that the newer reviewed public `overwrites.lua` would remove. Public-revision behavior is never injected into a different installed source.

Local validation key:

```toml
[source_paths]
pfquest_turtle = "..."
```

P2-T01 does not yet compose a Turtle item overlay. The Turtle path is used during Level-2 validation
to reconstruct/reconcile the canonical P1 world before base pfQuest direct-loot relations are
materialized.

### pfQuest-octo

- Repository: `https://github.com/paokkerkir/pfQuest-octo`
- Role: Octo-specific additions/overwrites for pfQuest; especially useful as comparison/enrichment for custom content, coordinates and unit/object corrections.

P1-T03 review is pinned to:

```text
dd3dc1fb80afe7a71e5c8ca8c31ca2a3ef57af67
```

The reviewed latest commit is dated 2026-05-12 and is titled:

```text
db: revert to 1.17.2 data
```

Therefore P1-T03 does **not** assume `pfQuest-octo` is globally newer or automatically preferable to the currently maintained Turtle fork. It remains relevant because `overwrites.lua` contains explicit Octo-specific manual corrections, including unit name/faction/coordinate changes.

When pfQuest base, current Turtle and pfQuest-octo differ, preserve source identities and compare them before defining canonical policy.

Optional local key:

```toml
[source_paths]
pfquest_octo = "..."
```

#### P1-T03 effective-view contract

P1-T03 constructs independent effective views:

```text
pfQuest + pfQuest-turtle
pfQuest + pfQuest-octo   (when available)
```

It compares zone/creature/gameobject IDs that are added, removed or changed. It does **not** choose a canonical winner and does not write either overlay into SQLite. Canonical/provenance reconciliation is handled by P1-T04 because deletion and replaced spawn sets require explicit durable semantics.

#### P1-T04 provenance/reconciliation contract

P1-T04 preserves three distinct source identities in SQLite:

```text
pfquest
pfquest-turtle
pfquest-octo
```

For reproducible local validation it can derive content revisions from the exact six P1 pfQuest world files and the exact Turtle-style overlay input set (`*-turtle` files plus `overwrites.lua`). The content revision identifies the installed inputs; it does not claim equivalence with a reviewed public commit.

Effective-source deletion is recorded as:

```text
world_presence = false
```

This means absent from that effective source view, not globally nonexistent.

Creature/game-object top-entry replacement is also represented by a complete deterministic:

```text
spawn_set
```

The installed `pfquest-turtle` view is the active pfQuest-family P1 view and may supersede only base/default pfQuest selections for this bounded fact family. It does not override explicit or non-pfQuest selections. Stale canonical spawn rows selected from the managed pfQuest family are removed when absent from the selected Turtle set, while all old source observations remain.

`pfquest-octo` remains comparison evidence in P1-T04: differences are recorded under its own source revision but do not automatically mutate canonical world rows. A future decision may introduce field/relation-specific Octo selection where justified; P1-T04 deliberately does not invent one.

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

#### P1-T02 Map/Area vertical slice

P1-T02 consumes only:

```text
Map.dbc
AreaTable.dbc
```

from a local extracted DBC directory configured as:

```toml
[source_paths]
octo_dbc = "..."
```

The user's actual local files are registered as source key:

```text
octo-client-dbc
```

When an explicit client build/revision is unavailable, the importer computes a deterministic SHA-256 composite revision from the exact `Map.dbc` / `AreaTable.dbc` bytes. Re-importing unchanged files therefore reuses stable source observations while still recording a new import-batch trace.

The classic WDBC container and field semantics were checked against CMaNGOS Classic source revision:

```text
9b682be617ac61c127c23aa60d7b4ffbc0ce37e6
```

Relevant format-reference files:

```text
src/shared/Database/DBCFileLoader.cpp
src/game/Server/DBCStructure.h
src/game/Server/DBCEnums.h
src/game/Server/DBCStores.cpp
```

This CMaNGOS source is a parser/semantic reference only. CMaNGOS rows are not imported as Octo truth by P1-T02.

For the bounded facts defined by D-025, the direct Octo client DBC is authoritative for canonical map/area identity and hierarchy:

- map name/type;
- zone/area name;
- area -> map relation;
- subzone -> parent-area relation.

This does not establish a universal DBC-over-everything rule. Other fields/relations continue to use explicit source-aware policies, and all competing observations remain preserved.

The P1-T02 binary tests use small synthetic WDBC files. Real client DBC files are never committed.

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
