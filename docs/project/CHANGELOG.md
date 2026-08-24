# Changelog

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
