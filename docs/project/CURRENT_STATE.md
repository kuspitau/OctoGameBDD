# Current State

## Repository state

GitHub `main` is the base for this workflow-hardening delta:

- branch: `main`
- base commit: `780ccadee17a0015125c2ba4aada0d30e747edff`

That commit contains the P0-T03 fixture/golden-case and audit skeleton.

Because P0-T03 is now present on the validated source-of-truth branch, this delta treats P0-T03 as having reached GitHub `main` and closes the stale "not yet pushed" wording from the previous handoff.

This delta implements a project-workflow amendment for local source discovery/configuration and handoff helper placement.

**Status:** `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`

## Current milestone

**P0 — Repository and data foundation / workflow hardening before P1**

## Current task

**Workflow amendment — local source paths and in-ZIP BAT helpers**

Implementation in this delta defines:

- public external addon/project formats must be researched from current primary sources rather than guessed;
- user-specific absolute paths must not be hard-coded;
- stable machine-specific locations belong in ignored `config.local.toml` under `[source_paths]`;
- task-specific `get_path.bat` is generated when missing local paths are needed;
- `get_path.bat` follows reuse -> discover -> ask -> validate -> config-update behavior;
- `delete_files.bat` is generated only when deletions/renames are required;
- both BAT helpers, when required, are placed at the project root **inside `changes.zip`**;
- `MANIFEST.txt` remains outside the ZIP and documents helper usage;
- `.gitignore` ignores `get_path.bat` alongside other handoff artifacts.

Detailed contract:

- `docs/project/LOCAL_PATHS.md`
- `docs/project/AI_GUIDELINES.md`
- `docs/project/WORKFLOW.md`

## Completed / validated on GitHub main before this delta

- project scope and multi-entity architecture;
- source strategy;
- raw/staging/canonical/derived separation;
- provenance/conflict requirements;
- GitHub read-only -> human-applied delta workflow;
- P0-T01 — SQLite foundation and import metadata;
- P0-T02 — provenance and conflict primitives;
- P0-T03 — fixture/golden-case and audit skeleton, present on `main` at `780ccadee17a0015125c2ba4aada0d30e747edff`.

## Validation for this workflow delta

No gameplay schema/code behavior is changed.

Required human validation after applying the delta:

```bash
git diff
python -m pip install -e ".[dev]"
pytest
ruff check src tests
python -m compileall -q src tests
```

Expected invariants:

- existing test suite remains green;
- Ruff reports no errors;
- Python compilation succeeds;
- `config.local.toml` remains ignored by Git;
- `get_path.bat` is ignored by Git;
- future handoffs place required `delete_files.bat` / `get_path.bat` inside `changes.zip`, not beside it.

## Next handoff rule

After the human validates, commits, and pushes this workflow amendment to GitHub `main`, the next normal coding conversation may close P0 and define/take the first bounded P1 world-foundation vertical-slice task before broad full-world ingestion.
