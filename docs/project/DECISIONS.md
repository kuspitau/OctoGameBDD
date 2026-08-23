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
