# Architecture Decision Log

Decisions are durable project memory. Do not silently change them.

A later decision may supersede an earlier one. Record the reason and consequences.

## D-001 — One physical canonical SQLite database

**Status:** accepted

Use one SQLite database for the canonical project model. Organize by logical domains through tables/modules instead of separate `items.db`, `quests.db`, etc.

## D-002 — Multi-entity model, not item-centric storage

**Status:** accepted

Items, quests, creatures, game objects, recipes, spells, zones, and maps are first-class domains. The UI may choose any entity as its current point of view.

## D-003 — Native IDs are preserved

**Status:** accepted

Keep game/source IDs alongside any internal surrogate keys. Cross-source reconciliation depends on them.

## D-004 — Raw → staging → canonical → derived

**Status:** accepted

Separate source artifacts, parsed source-shaped data, canonical normalized truth, and derived/query data.

## D-005 — Provenance is mandatory

**Status:** accepted

The system must be able to trace canonical facts/relations to source, source revision/import batch, and derivation when applicable.

## D-006 — Conflicts are preserved

**Status:** accepted

Selecting a canonical value does not delete competing source observations. Resolution policy must be explicit.

## D-007 — Explicit domain relation tables

**Status:** accepted

Important relations use dedicated tables. A generic graph relation table is not the primary persistence model.

## D-008 — Derived relations are not primary truth

**Status:** accepted

Examples such as `item -> obtainable zone` and `recipe -> available zone` should normally be derived from primitive relations. Materialized caches may be added later for measured performance needs.

## D-009 — Template entities and spawn instances are separate

**Status:** accepted

Creature/GameObject identity must not be conflated with geographic spawn records.

## D-010 — Recipe, recipe item, spell, and result item are distinct

**Status:** accepted

Crafting data must preserve the real intermediate entities/relations where sources expose them.

## D-011 — Reuse parsers selectively, own the canonical model

**Status:** accepted

Study/adapt useful parsing/resolution logic from existing projects where licensing permits. Do not build the project's canonical architecture around another project's final DB schema.

## D-012 — Audit/CLI before polished UI

**Status:** accepted

Build data correctness, traceability, conflict reporting, coverage metrics, and small end-to-end slices before the graphical explorer.

## D-013 — GitHub read-only agent workflow

**Status:** accepted

GitHub `main` is the validated source of truth. Coding conversations read GitHub, work in a temporary workspace, and return only a delta package. The human applies, validates, commits, and pushes.

## D-014 — Large data is local; small fixtures are tracked

**Status:** accepted

Full dumps, client files, scraped caches, and generated DBs stay out of Git. Small representative samples/fixtures are committed for deterministic tests.

## D-015 — Importers are idempotent

**Status:** accepted

Re-running the same importer against the same source revision must not duplicate rows or change the result spuriously.

## D-016 — Two validation levels

**Status:** accepted

Level 1: sample/unit/small integration tests that the coding conversation can run.

Level 2: full-data/local validation executed by the human on the complete project data.

A change that requires Level 2 validation is not fully validated until those checks pass.

## D-017 — Project docs are the durable memory

**Status:** accepted

`PROJECT`, `ARCHITECTURE`, `DATA_MODEL`, `DATA_SOURCES`, `DECISIONS`, `ROADMAP`, `CURRENT_STATE`, and `AI_GUIDELINES` travel with the code and must be updated when relevant.

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

Quest geography can differ by giver, finisher and objective. Recipe availability should normally be derived from the geography of its actual acquisition/learning sources.

## D-020 — UI framework choice is deferred

**Status:** accepted

A local browser UI remains the target. NiceGUI is a strong candidate, but no UI framework becomes a hard dependency before the data/query layer demonstrates its requirements.

## D-021 — Local source paths are runtime configuration

**Status:** accepted

User-machine absolute paths must not be hard-coded into tracked code or tracked configuration.

Stable local source locations belong in ignored `config.local.toml`, normally under `[source_paths]`.

When required locations are missing, coding handoffs provide task-specific discovery/configuration through `get_path.bat`.

## D-022 — Handoff BAT helpers travel inside the delta ZIP

**Status:** accepted

Transient `delete_files.bat` and `get_path.bat` helpers are included at the project root inside `changes.zip` when needed.

They are ignored by Git and are not separate delivery artifacts.

- `delete_files.bat` handles explicit deletions/rename cleanup.
- `get_path.bat` resolves required local source paths and updates `config.local.toml`.

`MANIFEST.txt` remains outside the ZIP and documents whether each helper is present and how to use it.

## D-023 — Public external formats are researched from primary sources

**Status:** accepted

When a parser/importer depends on a public addon/project/database, coding conversations inspect current primary source code/docs and relevant issues/discussions/history when necessary instead of guessing formats from memory.

The user's local copy is reserved for version-specific extraction/Level 2 validation rather than being the only source of format knowledge.

## D-024 — Geographic coordinate spaces are explicit

**Status:** accepted

Spawn/location coordinates must carry their coordinate-space semantics instead of being forced into a single generic X/Y/Z interpretation.

In particular:

- source coordinates expressed as percentages within a zone are stored as `zone_percent` and retain their zone identity;
- world-coordinate sources may use `world` with X/Y and optional Z/orientation;
- conversion between coordinate spaces is derived behavior and must be traceable to the coordinate-frame/map inputs used;
- source-specific zone/map frame fields are preserved as provenance until their canonical meaning is established from authoritative evidence.

This prevents percentage coordinates from being silently mislabeled as world coordinates and keeps future map/area reconciliation explicit.

## D-025 — Direct Octo DBC is authoritative for canonical map/area hierarchy facts

**Status:** accepted

For the bounded map/area fact family established in P1-T02, observations from the user's actual Octo client `Map.dbc` and `AreaTable.dbc` may supersede lower-authority canonical selections.

This policy applies to:

- map name and map kind/type normalization;
- zone/area name;
- area -> map identity;
- subzone/area -> parent-area identity.

Consequences:

- competing pfQuest, Vanilla, Turtle, or other source observations remain preserved in the provenance layer under D-006;
- the winning selection records the explicit `octo-client-dbc-geography` policy and reason;
- this is field-specific source authority, not a universal rule that every DBC field outranks every other source;
- the exact local DBC pair is identified by a deterministic content-derived revision when possible;
- a spawn's map may be derived at query time from its canonical zone's `map_id` when no direct spawn map is present;
- deriving that map context does not modify the spawn row and does not convert or relabel `zone_percent` coordinates.

D-025 resolves the map/area authority deliberately deferred by P1-T01 while preserving D-005, D-006, D-008, and D-024.

## D-026 — Effective-source deletion and complete-set replacement are provenance facts

**Status:** accepted

P1-T04 needs to reconcile Turtle-style overlay replacement semantics without confusing source-view
absence with universal game non-existence and without losing the provenance of canonical rows that
must be removed.

For the bounded P1 world view:

- entity membership in one effective source view is recorded as scalar `world_presence` evidence;
- `world_presence = false` means "absent from this effective source view", not an unconditional
  global tombstone;
- creature/game-object spawn membership is additionally recorded as a scalar complete `spawn_set`
  observation for the template;
- the existing per-spawn `position` and `respawn_seconds` observations remain the attribute
  evidence for members of that set.

When the installed Turtle effective view is active:

- it may supersede default/base pfQuest selections for this bounded fact family;
- it does not silently supersede explicit or non-pfQuest selections;
- optional `pfQuest-octo` remains comparison evidence unless a later explicit policy selects it;
- stale canonical spawn rows selected from the managed pfQuest family may be deleted when they are
  absent from the selected complete Turtle set;
- deleting a materialized row never deletes its source observations;
- a removed template/zone identity is retained when selected non-pfQuest evidence or a canonical
  dependency still supports keeping it.

Consequences:

- no schema migration is required for P1-T04 because the existing generic scalar provenance
  primitives can represent source-view membership and complete-set facts;
- a historical spawn can retain a selected position observation even when it is no longer a member
  of the selected template `spawn_set`; membership and attributes are intentionally distinct facts;
- D-025 remains authoritative for its DBC geography fact family;
- this decision is bounded to the current effective P1 world-view problem and is not yet a generic
  deletion framework for every future gameplay domain.

## D-027 — Turtle item overlay uses bounded P2 complete-set reconciliation

**Status:** accepted

P2-T04 must reproduce the installed pfQuest-turtle item view without silently extending D-026 from
P1 world entities to every future domain.

For the currently supported P2 fact family only:

- `item_presence` records whether an item has an effective usable enUS identity in the source view;
- `item_acquisition_set` records the complete supported U/O/R/V acquisition set for a patched item
  data entry;
- `loot_reference_presence` records whether a patched refloot entry exists in the effective view;
- `loot_reference_member_set` records the complete U/O membership set of a patched refloot entry;
- existing individual `name`, `loot_source`, `loot_reference`, `vendor_source`, and
  `loot_source_member` observations remain the attribute/relation evidence used by audit and query
  surfaces.

The active installed `pfquest-turtle` view may supersede only default/base pfQuest selections for
these bounded facts. "Managed" is determined by the selection policy as well as the source key: an
explicit/custom selection remains protected even when its observation comes from source key
`pfquest`. A protected complete-set selection governs membership without synthesizing Turtle
primitive relation evidence for rows that Turtle did not supply. A stale canonical P2 relation may
be removed only when its selected relation provenance belongs to the replaceable managed policy and
the selected complete set excludes it. Removing materialized rows never removes source observations.

Top-entry composition follows the source itself: `"_"` removes the corresponding base table entry;
all other patch values replace it wholesale; supported direct literal `overwrites.lua` mutations are
applied before patching. Item data absence and item-name absence remain separate facts because
pfQuest's `SearchItemID` gates acquisition lookup on the data table while name lookup uses the
localization table.

A relation-only creature/game-object target may still be materialized from its effective enUS
identity without inventing a spawn. Level-2 validation demonstrated that real Turtle acquisition
data can contain direct/vendor target IDs with no canonical P1 identity and no effective enUS
identity. Those relations are retained as explicit source provenance and reported as unresolved, but
they are not materialized into FK-backed domain tables and no placeholder identity is invented.
Reference-only missing identity follows the same non-fabrication principle. An effective name
removal while supported acquisition data remains is rejected as ambiguous under the current
non-null canonical item-name model rather than guessed.

Consequences:

- no schema migration is required; generic scalar provenance already stores the complete-set facts;
- P1 geography remains independent and is reused only to derive source locations;
- this policy is limited to item name + U/O/R/V + one-level refloot membership and is not a generic
  overlay/deletion rule for later item stats, quests, recipes, economics, or UI domains.
