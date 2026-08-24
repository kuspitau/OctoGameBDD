# Changelog

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
