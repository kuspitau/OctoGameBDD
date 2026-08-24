# Changelog

## 2026-08-24 — P2-T01 full-data validation and P2-T02 routing

- Completed P2-T01 Level-2 validation against the configured full pfQuest/pfQuest-turtle inputs.
- Validated 17,712 items, 198,811 direct creature-loot links and 8,298 direct game-object-loot links.
- Confirmed exactly two relation-only game-object templates in the validated dataset and no relation-only creature templates.
- Confirmed same-revision item re-import idempotence with zero canonical inserts/updates.
- Confirmed a real item-source query derives Turtle-selected Tanaris spawn geography while preserving separate pfQuest loot-relation provenance.
- Recorded 10,209 deferred reference-loot links and 13,860 deferred vendor links.
- Marked P2-T01 `VALIDATED` and routed the next bounded task to P2-T02 reference-loot resolution.


## 2026-08-24 — P2-T01 Level-2 relation-only source compatibility correction

- Level-2 full-data validation found direct game-object loot references to IDs `180523` and `180671` that were not materialized by the P1 static-world slice.
- Verified from pfQuest's enUS object table that these are real named templates: `Apple Bob` and `Xandivious' Demon Bag`.
- Corrected the P2-T01 assumption that every direct-loot target must already be a P1 static-world template.
- The item importer now reads pfQuest unit/object enUS names and materializes missing direct-loot targets as relation-only templates with provenance, without inventing spawns or geography.
- Targets missing both canonical P1 identity and pfQuest enUS identity still fail closed.
- Expanded deterministic item-source revision coverage to the four actual inputs and expanded focused tests from seven to eight cases.

## 2026-08-24 — P2-T01 first item/acquisition vertical slice

- Confirmed P1-T04 is present on GitHub `main` at commit `582810dfe6ae41e4eec9af303d6f98a772830ef8` and advanced normal routing to P2-T01.
- Defined P2-T01 as a bounded `item -> direct loot source -> P1 spawn -> zone/map` vertical slice rather than starting full P2/P6 ingestion.
- Added migration 4 with canonical `items`, `creature_loot`, and `gameobject_loot` tables while preserving native IDs and explicit domain relations.
- Inspected pfQuest item structure at the already pinned upstream revision `104f35678ca39ab1fb78b655f815cc7016f5e0c8` and mapped direct `U`/`O` relations to creature/game-object loot with source-listed percentage chances.
- Added deterministic content-derived revisions for the exact `db/items.lua` + `db/enUS/items.lua` input pair.
- Added provenance-aware item-name and direct-loot relation materialization with same-revision idempotence.
- Added fail-closed preflight for direct loot relations whose creature/game-object target is absent from the canonical P1 world.
- Counted but deliberately deferred pfQuest `R` reference-loot and `V` vendor relations.
- Added `find_item_sources()` plus `import-pfquest-items` and `item-sources` CLI surfaces, deriving geography through P1 spawns/zones/maps rather than persisting `item -> zone` truth.
- Added a reduced source-shaped pfQuest item fixture and seven focused parser/revision/import/provenance/query/failure/CLI tests.
- Added `.pytest_tmp/` to `.gitignore` and a safe handoff deletion helper for test artifacts accidentally tracked by the P1-T04 base commit.
- Marked P2-T01 `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`.

## 2026-08-24 — P1-T04 overlay provenance/canonical reconciliation

- Confirmed P1-T03 is present on GitHub `main` at commit `034c5914457d6ef29a20ec28e690d2fb753d1356` and advanced normal routing to P1-T04.
- Recorded D-026: effective-source deletion is source-view `world_presence` evidence rather than a universal tombstone, and replace-whole spawn membership is preserved as a complete `spawn_set` fact.
- Added distinct persisted source identities for current `pfquest-turtle` and optional `pfquest-octo` overlay evidence.
- Added deterministic content-derived revisions for the exact P1 pfQuest and Turtle-style overlay file sets used locally.
- Added Turtle reconciliation that may supersede only default/base pfQuest selections for the bounded P1 world fact family while preserving explicit/non-pfQuest selections and D-025 DBC geography authority.
- Added complete-set stale-spawn cleanup: pfQuest-family canonical spawn rows absent from the selected Turtle set are removed while their historical source observations remain.
- Added conservative template/zone deletion so non-pfQuest selected evidence and canonical FK dependencies retain identity anchors.
- Kept `pfQuest-octo` comparison-only: its changed/removed/added effective-view evidence is stored without automatic canonical materialization.
- Added focused tests for complete-set replacement, historical provenance retention, repeat-run idempotence, negative presence with external support, and Octo comparison-only behavior.
- Introduced no schema migration and reused the P1-T03 local path contract.
- Marked P1-T04 `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`.

## 2026-08-24 — P1-T03 local Turtle revision compatibility correction

- Level-2 validation found that the launcher-installed `pfQuest-turtle` is not behavior-identical to the reviewed public Kameleon revision: local `overwrites.lua` lacks the public phantom-zone cleanup loop and therefore retains zone 5138 (`The Deadmines`).
- Corrected the validation contract: supported overwrite loops are applied only when present in the loaded source; public-reference mutations are never synthesized into a differing local addon.
- Added a regression test proving that absence of the phantom-zone cleanup leaves the corresponding overlay zone intact.

## 2026-08-24 — P1-T03 Turtle/Octo effective world views

- Confirmed P1-T02 is present on GitHub `main` at commit `3302785ba6ece92df6c45df379420484d4eacb23` and advanced normal routing to P1-T03.
- Corrected the initial P1-T03 source assumption after local discovery showed the Octo launcher installation already contains `pfQuest-turtle`.
- Inspected current `KameleonUK/pfQuest-turtle` revision `5b8eeeeb4119be9d075087f0f0e08c187b35ad61` and retained `paokkerkir/pfQuest-octo` revision `dd3dc1fb80afe7a71e5c8ca8c31ca2a3ef57af67` as a separate optional comparison source.
- Stopped treating `pfQuest-octo` as automatically newer: its reviewed latest commit reverts its DB to 1.17.2 data, while the reviewed current Turtle fork is newer.
- Added a shared Turtle-style world overlay loader for the existing P1 zones, units and objects slice.
- Reproduced top-entry patch semantics, direct literal overwrite assignments and the reviewed Turtle phantom-zone cleanup without executing Lua.
- Added fail-closed detection for unsupported indirect world-table mutations.
- Added deterministic effective-view comparison reporting added/removed/changed IDs without choosing a canonical winner.
- Updated local path handling so `pfquest` + `pfquest_turtle` are required and an existing `pfquest_octo` remains an optional comparison source.
- Deferred SQLite/provenance reconciliation to P1-T04 so entry deletion and replaced spawn sets receive explicit durable semantics.
- Marked P1-T03 `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`.

## 2026-08-24 — P1-T02 Octo DBC map/area hierarchy slice

- Added real-client compatibility for isolated unnamed `AreaTable.dbc` rows: skip without inventing a canonical name, report the skipped ID/count, and retain strict parent-reference validation.
- Confirmed the P1-T01 implementation is present on GitHub `main` at commit `d4310762f1e00b2664cb6d39eadf3e9abd407c46` and advanced normal routing to P1-T02.
- Defined P1-T02 as the bounded resolution of authoritative map/area hierarchy deliberately deferred by P1-T01.
- Inspected the classic WDBC container and Map/AreaTable field semantics in `cmangos/mangos-classic` revision `9b682be617ac61c127c23aa60d7b4ffbc0ce37e6` instead of guessing the binary format.
- Added a dependency-free local `Map.dbc` / `AreaTable.dbc` parser with deterministic content-derived source revision identity.
- Added provenance-aware, idempotent canonical map/zone materialization using the existing migration-3 schema.
- Recorded D-025: direct Octo client DBC evidence is authoritative for the bounded canonical map/area identity/hierarchy facts while lower-authority observations remain preserved.
- Preserved extra Map/AreaTable fields as source observations rather than prematurely widening the canonical schema.
- Updated world-location queries so a spawn without direct `map_id` can derive map context through its canonical zone, without altering the spawn row or `zone_percent` coordinate semantics.
- Added synthetic source-shaped WDBC fixtures and focused tests for parsing, revision identity, invalid files, idempotency, provenance selection, and derived map context.
- Added task-specific `get_path.bat` handoff support for `[source_paths].octo_dbc` and documented required validation against the user's real client DBC pair.
- Marked P1-T02 `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`.

## 2026-08-24 — P1-T01 world schema and pfQuest fixture slice

- Closed the stale P0 router state after confirming the local-path/handoff workflow amendment is present on GitHub `main` at `fc0dbe0fc22610113bfc8bd9c1e07cb41d400a39`.
- Defined P1-T01 as the first bounded world-foundation task.
- Added schema migration 3 with canonical maps, zones, creature/game-object templates, and separate spawn tables.
- Made spawn coordinate space explicit so pfQuest zone-percentage X/Y values are not mislabeled as world XYZ coordinates.
- Recorded D-024: geographic coordinate spaces are explicit and cross-space conversion remains a traceable derived operation.
- Inspected public pfQuest revision `104f35678ca39ab1fb78b655f815cc7016f5e0c8` and its MIT license before defining the source fixture/parser contract.
- Added a reduced source-shaped pfQuest six-file world fixture and dependency-free Lua literal-table parser/importer.
- Added provenance-aware, idempotent materialization that preserves existing explicit canonical selections.
- Added deterministic spawn keys for source records without native spawn IDs.
- Added a small creature/game-object location query with selected position-source attribution.
- Added Level 1 parser, migration, schema-constraint, idempotency, provenance, and query tests.
- Marked P1-T01 `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`.

## 2026-08-24 — Local source-path and handoff-helper workflow

- Confirmed the P0-T03 implementation is present on GitHub `main` at `780ccadee17a0015125c2ba4aada0d30e747edff`.
- Added the durable local-source path contract in `docs/project/LOCAL_PATHS.md`.
- Established `[source_paths]` in ignored `config.local.toml` as the location for stable user-machine source paths.
- Required future coding conversations to research public external addon/project formats from primary current sources instead of guessing.
- Defined task-specific `get_path.bat`: reuse configured values, discover safe candidates, ask only when unresolved/ambiguous, validate targets, and update `config.local.toml` idempotently.
- Changed the handoff contract so required `delete_files.bat` and `get_path.bat` are included at the project root inside `changes.zip`.
- Added `get_path.bat` to generated handoff artifacts ignored by Git.
- Marked this workflow amendment `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`.

## 2026-08-24 — P0-T03 fixture/golden-case and audit skeleton

- Confirmed P0-T02 as validated after its implementation reached GitHub `main` at commit `587146435e44960aaebf7105979a79516102f26e`.
- Formalized fixture conventions separating source-shaped importer samples from synthetic project-owned golden cases.
- Added an initial provenance/audit golden case containing a resolved scalar conflict, an unresolved relation conflict, and legitimate multi-valued relations.
- Added generic source, trace, conflict, and provenance-coverage audit reports.
- Added `source`, `trace`, `conflict`, and `coverage` CLI commands with human-readable and deterministic JSON modes.
- Added reusable machine-readable import summaries with deterministic JSON serialization/file output.
- Added Level 1 tests for golden coverage invariants, conflict classification, traceability, source/import summaries, CLI text/JSON output, and summary serialization.
- Kept P0-T03 schema-neutral: no new migration or gameplay-domain canonical tables were added.
- Marked P0-T03 `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`.

## 2026-08-24 — P0-T02 provenance and conflict primitives

- Confirmed P0-T01 as validated after its implementation reached GitHub `main`.
- Added schema migration 2 with provenance evidence groups, source observations, and canonical selection metadata.
- Added relation-instance grouping so multiple legitimate relations of the same type are not automatically treated as conflicts.
- Added deterministic canonical JSON serialization and idempotent scalar/relation observation helpers, including reuse across repeated import batches of the same source revision.
- Added `observation_import_batches` so repeated runs remain traceable without duplicating stable observations, with source/revision consistency enforced by SQLite.
- Added explicit canonical selection policy/reason handling with same-group foreign-key enforcement.
- Added Level 1 tests for schema-v1 upgrade, cross-run idempotency, revision separation, provenance link integrity, scalar conflicts, relation traceability, multi-valued relations, competing relation targets, constraints, and canonical selection behavior.
- Kept the generic provenance structures explicitly separate from future canonical domain relation tables.
- Marked P0-T02 `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`.

## 2026-08-24 — P0-T01 SQLite foundation

- Added project-owned SQLite connection handling with foreign-key enforcement and deterministic commit/rollback/close behavior.
- Added packaged versioned SQL migrations and migration recording.
- Added foundational `data_sources` and `import_batches` metadata tables.
- Added `python -m octogamedb status` with custom database-path support.
- Added Level 1 tests for initialization, idempotency, migration recording, foreign keys, metadata constraints, rollback behavior, and CLI status.
- Marked P0-T01 `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`.

## 2026-08-24 — Initial project bootstrap

- Created project-owned durable planning/context documents.
- Established multi-entity architecture.
- Established raw/staging/canonical/derived layers.
- Established provenance and conflict-preservation requirements.
- Established source strategy for OctoDB, pfQuest/pfQuest-octo, Octo client data, Turtle/Tortoise and Vanilla baselines.
- Established GitHub read-only -> delta ZIP -> local validation -> human push workflow.
- Created minimal Python package and smoke test.
- Defined P0-T01 as the first coding task.
- Made `CURRENT_STATE.md` the permanent task router and placed the P0-T01 task specification under `docs/project/tasks/`.
