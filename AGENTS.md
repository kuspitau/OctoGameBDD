# Agent Instructions

This repository carries its own project memory. Do not rely on prior chat history.

Task routing rule:

- `docs/project/CURRENT_STATE.md` is the single permanent answer to "what should the next conversation do?".
- If it references a detailed task specification under `docs/project/tasks/`, read that task file.
- Do not use an old task file as the current task unless `CURRENT_STATE.md` explicitly points to it.

Before making changes:

1. Read `docs/project/CURRENT_STATE.md`.
2. Read `docs/project/AI_GUIDELINES.md`.
3. Read `docs/project/PROJECT.md`.
4. Read only the architecture/data/source documents relevant to the task.
5. Inspect the implementation, callers, tests, and docs affected by the task before editing.
6. Identify the GitHub base revision/commit when available.
7. If the task needs files/directories that exist only on the user's machine, read `docs/project/LOCAL_PATHS.md` before designing path handling.

Important rules:

- GitHub `main` is the validated source of truth.
- Preserve native game IDs.
- Keep raw/staging/canonical/derived layers distinct.
- Preserve provenance and source conflicts; do not silently overwrite competing facts.
- Keep template entities separate from spawn instances.
- Use explicit domain relation tables for important relations rather than one generic graph table.
- Treat derived relations as derived; do not make them primary truth without an explicit architecture decision.
- Importers must be idempotent.
- Large data stays local and out of Git.
- Never hard-code user-specific absolute paths into project code or tracked configuration.
- When an external source/addon is public, inspect the primary repository/docs and relevant issues/discussions as needed instead of guessing its format.
- When local paths are needed, generate a task-specific `get_path.bat` according to `LOCAL_PATHS.md`; include it at the root of `changes.zip`.
- When deletions/renames are needed, generate a safe `delete_files.bat`; include it at the root of `changes.zip`.
- Add/update tests with behavior changes.
- Update project-memory docs when the state, roadmap, architecture, or decisions change.
- Never silently redesign an accepted architecture decision. Record the issue and superseding decision in `docs/project/DECISIONS.md`.

Delivery protocol is defined in `docs/project/AI_GUIDELINES.md` and `docs/project/WORKFLOW.md`.
