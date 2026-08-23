# AI Coding Guidelines

These rules define how coding conversations work on this project.

## Source of truth

GitHub `main` is the validated source of truth.

The agent/conversation is expected to have **read-only GitHub access**. It must not assume that prior chat history is available or current.

## Start-of-task protocol

`CURRENT_STATE.md` is the permanent task router. Determine the current/next task from it. If it links to a task specification in `docs/project/tasks/`, read that file. Never infer the current task from an older task document.

Before editing:

1. Read `AGENTS.md`.
2. Read `docs/project/CURRENT_STATE.md`.
3. Read `docs/project/PROJECT.md`.
4. Read `docs/project/DECISIONS.md`.
5. Read only the additional architecture/data/source documents relevant to the assigned task.
6. Identify the current GitHub base commit/revision if the integration exposes it.
7. Inspect:
   - primary implementation files;
   - callers/importers/dependencies;
   - relevant tests;
   - relevant project-memory docs.
8. Confirm internally that the task is being implemented against the current `main`, not a stale snapshot.

Do not load/read the entire repository without need. Expand context deliberately as dependencies are discovered.

## Architecture discipline

Do not silently overturn established decisions.

If an accepted design causes a concrete problem:

1. describe the conflict;
2. propose the alternative;
3. update `DECISIONS.md` with a new decision that supersedes the old one;
4. update affected architecture/data docs;
5. include those files in the delta package.

Preserve:

- native IDs;
- raw/staging/canonical/derived separation;
- provenance;
- source conflicts;
- template/spawn separation;
- recipe/spell/item distinctions;
- explicit domain relations;
- idempotent import behavior.

## Testing discipline

### Level 1 — agent/sample validation

Run all feasible:

- unit tests;
- parser tests;
- schema/migration tests;
- small integration tests using tracked fixtures;
- syntax/lint checks appropriate to the task.

### Level 2 — human/full-data validation

When the change affects full imports, large files, the real Octo client, real SQL dumps, or other unavailable local data, provide **exact commands and expected invariants** for the human to run.

Do not claim full validation if Level 2 was required but not performed.

Use status wording:

- `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`
- `VALIDATED`

as appropriate.

## Project-memory updates

Before delivery, consider every project-memory file:

- `CURRENT_STATE.md` — update when implementation status/progress changes;
- `ROADMAP.md` — update when task status/order/scope changes;
- `DECISIONS.md` — update for architecture decisions;
- `ARCHITECTURE.md` / `DATA_MODEL.md` / `DATA_SOURCES.md` — update when their facts/contracts change;
- `CHANGELOG.md` — record user-visible/project-significant changes.

Code and project memory must not drift apart.

## Delta-package delivery contract

The agent has read-only GitHub access. At the end of a coding task it must return:

1. `changes.zip`
2. `MANIFEST.txt`
3. `delete_files.bat` **only if deletions/renames are required**

### `changes.zip`

Must contain **only**:

- files newly added by the task;
- files whose content differs from the GitHub base revision.

Paths inside the ZIP must be project-root relative.

Do **not** include:

- unchanged files;
- full repository snapshots "just to be safe";
- large/raw/generated data;
- `MANIFEST.txt`;
- `delete_files.bat`.

The human extracts `changes.zip` over the root of the local project.

### `MANIFEST.txt`

Must state:

```text
Project:
Task:
Base branch:
Base commit/revision: <hash/ref if available>

Modified:
- ...

Added:
- ...

Deleted:
- ...

Renamed:
- old -> new

Agent/sample validation performed:
- command
- result

Required human/full-data validation:
- exact command
- expected invariant/result

Known limitations / unresolved questions:
- ...
```

If the connector cannot expose an exact commit hash, say so explicitly and record the most precise ref available. Never invent a hash.

### `delete_files.bat`

Only create this when files must be removed from the user's working tree.

Safety requirements:

- paths must be relative to the project root;
- no `..`;
- no wildcards;
- no broad recursive delete;
- list each target explicitly;
- use `if exist` guards;
- the BAT must be human-readable and match the `Deleted:` section of the manifest exactly.

For a rename:

- the new path is included in `changes.zip`;
- the old path is listed as a deletion and removed by the BAT.

## Human application loop

The expected user workflow is:

```text
GitHub main
-> coding conversation reads current state
-> conversation returns delta artifacts
-> human extracts changes.zip
-> human reviews MANIFEST.txt
-> human runs delete_files.bat if present
-> human runs git diff
-> human runs requested Level 2 tests
-> human commits
-> human pushes main
-> next conversation reads the new GitHub state
```

Do not design a workflow that depends on the agent pushing to GitHub.

## Concurrent/stale work

Default to serial handoffs.

If the package base revision differs from the user's current local/GitHub `main`, the human must not blindly extract it. The package should be rebased/re-generated or manually reconciled.

## Large data

Never require full source dumps to be committed merely so an agent can work.

Instead:

- create small source-shaped fixtures;
- make parsers/importers testable against those fixtures;
- give the human full-data commands for final validation.

## Completion quality

Before delivering:

- inspect the final diff;
- ensure no unintended files are included;
- ensure tests are aligned with changed behavior;
- ensure docs and state are aligned;
- ensure the delta package contains the complete changed files, not patch fragments;
- state anything that remains unvalidated.
