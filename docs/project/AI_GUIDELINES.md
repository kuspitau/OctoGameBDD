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
8. If local user-machine files/directories are needed, read `docs/project/LOCAL_PATHS.md`.
9. Confirm internally that the task is being implemented against the current `main`, not a stale snapshot.

Do not load/read the entire repository without need. Expand context deliberately as dependencies are discovered.

## External-source research

When implementation depends on the format/behavior of a public external addon, project, database, or library:

- inspect the primary/current source before guessing;
- consult relevant documentation, code paths, issues/discussions, or history when ambiguity matters;
- prefer authoritative upstream evidence over memory or assumptions;
- record relevant source revisions/versions when they affect parser behavior;
- create small source-shaped fixtures for deterministic tests;
- do not ask the user for their full installed copy merely to understand a publicly inspectable format.

The user's local installed copy remains important for Level 2/version-specific validation.

## Local paths

Never hard-code user-specific absolute paths in tracked code or configuration.

Machine-specific source locations belong in ignored `config.local.toml`, normally under `[source_paths]`.

If a task requires local paths that are not already configured/discoverable, generate a task-specific `get_path.bat` following `docs/project/LOCAL_PATHS.md`.

The helper must:

- search/reuse safe known candidates first;
- ask only for unresolved/ambiguous paths;
- validate the selected target;
- update only intended config keys;
- preserve unrelated configuration;
- be idempotent;
- be included at the root of `changes.zip`.

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

If Level 2 needs unresolved local source paths, include `get_path.bat` in `changes.zip` and instruct the user to run it before the relevant validation commands.

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
- `LOCAL_PATHS.md` — update when the local-path contract changes;
- `CHANGELOG.md` — record user-visible/project-significant changes.

Code and project memory must not drift apart.

## Delta-package delivery contract

The agent has read-only GitHub access. At the end of a coding task it must return:

1. `changes.zip`
2. `MANIFEST.txt`

`changes.zip` may also contain transient project-root handoff helpers:

- `delete_files.bat` **when deletions/renames are required**;
- `get_path.bat` **when local paths must be discovered/requested/configured**.

These BAT files are inside `changes.zip`, not separate delivery artifacts.

### `changes.zip`

Normally contains only:

- files newly added by the task;
- files whose content differs from the GitHub base revision.

Exception: the transient root-level handoff helpers `delete_files.bat` and `get_path.bat` may also be included when required. They are intentionally ignored by Git.

Paths inside the ZIP must be project-root relative.

Do **not** include:

- unchanged tracked files;
- full repository snapshots "just to be safe";
- large/raw/generated data;
- `MANIFEST.txt`.

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

Handoff helpers included:
- delete_files.bat: <yes/no; purpose>
- get_path.bat: <yes/no; purpose and config keys>

Agent/sample validation performed:
- command
- result

Required local path/config step:
- exact helper/command
- expected resolved keys/paths

Required human/full-data validation:
- exact command
- expected invariant/result

Known limitations / unresolved questions:
- ...
```

If the connector cannot expose an exact commit hash, say so explicitly and record the most precise ref available. Never invent a hash.

### `delete_files.bat`

Create only when files must be removed from the user's working tree.

Place it at the project root **inside `changes.zip`**.

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

### `get_path.bat`

Create only when the task needs local file/directory locations that are not already safely configured.

Place it at the project root **inside `changes.zip`**.

It must follow `docs/project/LOCAL_PATHS.md`, including search -> ask -> validate -> update `config.local.toml`.

It must not encode the user's eventual machine-specific paths into tracked project files.

## Human application loop

The expected user workflow is:

```text
GitHub main
-> coding conversation reads current state
-> conversation returns changes.zip + MANIFEST.txt
-> human extracts changes.zip over the local repo
-> human reviews MANIFEST.txt
-> human runs delete_files.bat if present
-> human runs get_path.bat if present
-> human reviews git diff
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
- use public primary sources to understand public formats;
- use `get_path.bat` only when the user's local source location is actually needed;
- give the human full-data commands for final validation.

## Completion quality

Before delivering:

- inspect the final diff;
- ensure no unintended files are included;
- ensure tests are aligned with changed behavior;
- ensure docs and state are aligned;
- ensure the delta package contains complete changed files, not patch fragments;
- ensure any required handoff BAT is inside `changes.zip`;
- state anything that remains unvalidated.
