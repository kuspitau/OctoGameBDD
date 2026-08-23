# Current State

## Repository state

Project bootstrap prepared for the **initial GitHub push**.

Expected branch/source of truth after the human pushes this repository:

- branch: `main`
- state: initial planning/bootstrap
- no validated gameplay-data implementation yet

The first coding conversation must read the actual GitHub `main` revision and record its base commit/ref before producing a delta.

## Current milestone

**P0 — Repository and data foundation**

## Current task

**P0-T01 — SQLite foundation and import metadata**

Detailed task specification:

- `docs/project/tasks/P0-T01.md`

`CURRENT_STATE.md` is the permanent task router. Future conversations must determine the current/next task from this file, not from historical task documents.

## Completed

- project scope and multi-entity architecture defined;
- source strategy defined;
- raw/staging/canonical/derived separation accepted;
- provenance/conflict requirements accepted;
- GitHub read-only -> human-applied delta workflow defined;
- initial Python package/test skeleton created;
- large-data exclusion policy created;
- roadmap and decision log created.

## Not yet implemented

- database connection/migrations;
- source registry/import-batch schema;
- canonical gameplay tables;
- importers;
- provenance storage;
- conflict resolver;
- audit/coverage CLI;
- full-data fixtures/imports;
- graphical UI.

## Validation status

The bootstrap repository contains only a package smoke test.

Suggested initial human validation after extraction:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
python -m pip install -e ".[dev]"
pytest
```

Expected result: package smoke test passes.

## Next handoff rule

After P0-T01 is implemented by a coding conversation, it should be marked:

`IMPLEMENTED_AWAITING_LOCAL_VALIDATION`

The human then applies the returned delta, runs the requested local tests, reviews `git diff`, commits, pushes to GitHub, and only then should `CURRENT_STATE.md` be advanced to a validated state in the next accepted update.
