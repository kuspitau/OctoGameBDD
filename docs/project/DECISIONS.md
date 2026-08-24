# Architecture Decision Log

Decisions are durable project memory. Do not silently change them.

A later decision may supersede an earlier one. Record the reason and consequences.

## D-001 — One physical canonical SQLite database

**Status:** accepted

Use one SQLite database for the canonical project model. Organize by logical domains through
tables/modules instead of separate `items.db`, `quests.db`, etc.

## D-002 — Multi-entity model, not item-centric storage

**Status:** accepted

Items, quests, creatures, game objects, recipes, spells, zones, and maps are first-class domains. The
UI may choose any entity as its current point of view.

## D-003 — Native IDs are preserved

**Status:** accepted

Keep game/source IDs alongside any internal surrogate keys. Cross-source reconciliation depends on
them.

## D-004 — Raw → staging → canonical → derived

**Status:** accepted

Separate source artifacts, parsed source-shaped data, canonical normalized truth, and derived/query
data.

## D-005 — Provenance is mandatory

**Status:** accepted

The system must be able to trace canonical facts/relations to source, source revision/import batch,
and derivation when applicable.

## D-006 — Conflicts are preserved

**Status:** accepted

Selecting a canonical value does not delete competing source observations. Resolution policy must be
explicit.

## D-007 — Explicit domain relation tables

**Status:** accepted

Important relations use dedicated tables. A generic graph relation table is not the primary
persistence model.

## D-008 — Derived relations are not primary truth

**Status:** accepted

Examples such as `item -> obtainable zone` and `recipe -> available zone` should normally be derived
from primitive relations. Materialized caches may be added later for measured performance needs.

## D-009 — Template entities and spawn instances are separate

**Status:** accepted

Creature/GameObject identity must not be conflated with geographic spawn records.

## D-010 — Recipe, recipe item, spell, and result item are distinct

**Status:** accepted

Crafting data must preserve the real intermediate entities/relations where sources expose them.

## D-011 — Reuse parsers selectively, own the canonical model

**Status:** accepted

Study/adapt useful parsing/resolution logic from existing projects where licensing permits. Do not
build the project's canonical architecture around another project's final DB schema.

## D-012 — Audit/CLI before polished UI

**Status:** accepted

Build data correctness, traceability, conflict reporting, coverage metrics, and small end-to-end
slices before the graphical explorer.

## D-013 — GitHub read-only agent workflow

**Status:** accepted

GitHub `main` is the validated source of truth for tracked project state. Coding conversations read
GitHub, work in a temporary workspace, and return only a delta package. The human applies, validates,
commits, and pushes.

## D-014 — Large data is local; small fixtures are tracked

**Status:** accepted

Full dumps, client files, scraped caches, and generated DBs stay out of Git. Small representative
samples/fixtures are committed for deterministic tests.

## D-015 — Importers are idempotent

**Status:** accepted

Re-running the same importer against the same source revision must not duplicate rows or change the
result spuriously.

## D-016 — Two validation levels

**Status:** accepted

Level 1 is sample/unit/small integration validation available to a coding conversation. Level 2 is
full-data/local validation executed by the human. A change that requires Level 2 is not fully
validated until those checks pass.

## D-017 — Project docs are the durable memory

**Status:** accepted

`PROJECT`, `ARCHITECTURE`, `DATA_MODEL`, `DATA_SOURCES`, `DECISIONS`, `ROADMAP`, `CURRENT_STATE`,
`AI_GUIDELINES`, and task documents travel with the code and must be updated when relevant.

## D-018 — Serial validated handoffs by default

**Status:** accepted

Avoid multiple stale delta packages against different unmerged bases. Preferred loop:

```text
read current GitHub main
-> implement
-> delta package
-> human apply/test/commit/push
-> next coding conversation
```

## D-019 — Zones are first-class and quest/recipe geography is relational

**Status:** accepted

Quest geography can differ by giver, finisher and objective. Recipe availability should normally be
derived from the geography of its actual acquisition/learning sources.

## D-020 — UI framework choice is deferred

**Status:** accepted

A local browser UI remains the target. NiceGUI is a strong candidate, but no UI framework becomes a
hard dependency before the data/query layer demonstrates its requirements.

## D-021 — Local source paths are runtime configuration

**Status:** accepted

User-machine absolute paths must not be hard-coded into tracked code or tracked configuration.
Stable local source locations belong in ignored `config.local.toml`, normally under `[source_paths]`.
When required locations are missing, coding handoffs provide task-specific discovery/configuration
through `get_path.bat`.

## D-022 — Handoff BAT helpers travel inside the delta ZIP

**Status:** accepted

Transient `delete_files.bat` and `get_path.bat` helpers are included at the project root inside
`changes.zip` when needed. They are ignored by Git and are not separate delivery artifacts.
`MANIFEST.txt` remains outside the ZIP and documents whether each helper is present and how to use it.

## D-023 — Public external formats are researched from primary sources

**Status:** accepted

When a parser/importer depends on a public addon/project/database, coding conversations inspect
current primary source code/docs and relevant issues/discussions/history when necessary instead of
guessing formats from memory. The user's local copy is reserved for version-specific extraction and
Level 2 validation rather than being the only source of format knowledge.

## D-024 — Geographic coordinate spaces are explicit

**Status:** accepted

Spawn/location coordinates must carry their coordinate-space semantics instead of being forced into a
single generic X/Y/Z interpretation.

In particular:

- source coordinates expressed as percentages within a zone are stored as `zone_percent` and retain
  their zone identity;
- world-coordinate sources may use `world` with X/Y and optional Z/orientation;
- conversion between coordinate spaces is derived behavior and must be traceable to the
  coordinate-frame/map inputs used;
- source-specific zone/map frame fields are preserved as provenance until their canonical meaning is
  established from authoritative evidence.

## D-025 — Direct Octo DBC is authoritative for canonical map/area hierarchy facts

**Status:** accepted

For the bounded map/area fact family established in P1-T02, observations from the user's actual Octo
client `Map.dbc` and `AreaTable.dbc` may supersede lower-authority canonical selections.

This applies to map name/kind and zone/area name, map identity and parent-area identity. Competing
observations remain preserved. Selection records the explicit `octo-client-dbc-geography` policy.
This is field-specific authority, not a universal DBC priority. Spawn map context may be derived from
its canonical zone without rewriting coordinate space or the spawn row.

## D-026 — Effective-source deletion and complete-set replacement are provenance facts

**Status:** accepted

P1-T04 reconciles Turtle-style overlay replacement without confusing source-view absence with
universal game non-existence.

For bounded P1 world facts:

- `world_presence` records entity membership in an effective source view;
- `world_presence = false` is negative source evidence, not a global tombstone;
- creature/game-object full spawn membership is stored as deterministic `spawn_set` evidence;
- per-spawn `position` and `respawn_seconds` remain primitive attribute evidence.

The installed Turtle effective view may supersede only default/base pfQuest selections for this
bounded family. Explicit/non-pfQuest selections remain protected. Stale managed pfQuest-family spawn
rows may be removed when absent from the selected complete set, while historical source observations
remain. Optional `pfQuest-octo` remains comparison evidence unless explicitly selected. D-025 keeps
its map/area authority.

## D-027 — Turtle item overlay uses bounded P2 complete-set reconciliation

**Status:** accepted

P2-T04 defines item-specific effective-view facts instead of silently generalizing D-026:

```text
item_presence
item_acquisition_set
loot_reference_presence
loot_reference_member_set
```

Existing primitive `name`, `loot_source`, `loot_reference`, `vendor_source`, and
`loot_source_member` observations remain the detailed evidence.

The active Turtle item view may replace only managed/default base selections. Explicit/custom
selections remain protected even when their observation source key is `pfquest`. Stale canonical P2
relations are removed only when their selected primitive relation is managed and the selected
complete set excludes them. Missing target identity stays unresolved evidence without fabricated
canonical templates/spawns. Turtle top-entry `"_"` deletion and replace-whole semantics are reproduced
from the source, including supported direct literal overwrites before patching.

This decision remains limited to the P2 identity + U/O/R/V + one-level refloot family.

## D-028 — Turtle quest identity/endpoints use bounded complete-view reconciliation

**Status:** accepted

P3-T02 defines a quest-specific effective-view policy for the P3-T01 fact family instead of silently
generalizing D-026 or D-027.

Complete effective-view facts are:

```text
quest_presence
quest_endpoint_set
```

`quest_presence` is true when the composed effective source view has a usable enUS title for the
quest. `quest_endpoint_set` is the complete supported giver/finisher set over the P3-T01 endpoint
families:

```text
(giver|finisher) × (creature|gameobject) × native target ID
```

Primitive `name` and `endpoint` observations remain source-specific:

- inherited base facts remain `pfquest` evidence;
- facts actually introduced/replaced by the Turtle quest patch are `pfquest-turtle` evidence.

The managed Turtle selection policy is:

```text
pfquest-turtle-effective-quests
```

It may supersede only the corresponding managed/default base quest view. Explicit/custom canonical
selections remain protected, including custom policies selecting an observation whose source key is
still `pfquest`.

A stale canonical endpoint may be removed only when the selected primitive endpoint relation is
managed and the selected complete endpoint set excludes it. Quest identity may be removed for an
absent effective title only when no protected selected support requires retaining it. Historical
observations are never deleted.

A Turtle-added usable title can activate a quest whose base data row existed but P3-T01 skipped for
missing base enUS title; inherited base endpoint facts keep base provenance. Missing P1 endpoint
identity remains explicit unresolved evidence and does not create a fake creature/game-object,
spawn, or geography.

The Turtle quest revision hashes the exact bounded load/composition inputs and validates the relevant
TOC/XML/patchtable markers. D-028 is limited to quest identity and giver/finisher endpoints; later
quest restrictions, dependencies, objectives and rewards require their own source/model review.

## D-029 — The generated canonical DB is a local validated baseline with one-step backup

**Status:** accepted

GitHub `main` remains the source of truth for tracked code, migrations, importers, tests and project
memory. The large generated data state is intentionally local.

When `CURRENT_STATE.md` records that a cumulative local DB has been successfully built and validated,
this path is the canonical local data baseline:

```text
data/generated/octogamedb.sqlite3
```

It represents all validated import/reconciliation stages through the level named in
`CURRENT_STATE.md`. It is the preferred cumulative real-data starting point for later tests and
project evolution instead of guessing among historical validation DBs or rebuilding from zero for
every task.

Before **any mutation** of the canonical local DB, create or replace:

```text
data/generated/octogamedb_bak.sqlite3
```

with an exact copy of the canonical DB. The `_bak` file is a one-step rollback state, not historical
version storage; replace an existing `_bak` on the next canonical mutation cycle.

Exploratory, destructive or first-run Level-2 validation should use a dedicated copy when practical.
If canonical evolution fails after writes, restore from `_bak` before considering the canonical state
valid. A task is not allowed to claim that the canonical DB advanced until its required Level-2
checks pass.

Both the canonical DB and `_bak` are ignored generated artifacts and must never be committed or
included in `changes.zip`. The project must remain capable of rebuilding the canonical DB from a
fresh SQLite file using tracked code plus configured local sources. The canonical local DB is a
validated working baseline, not an irreplaceable source artifact.

The operational details live in `docs/project/CANONICAL_DB.md`.
