# Repository and Handoff Workflow

## Why this workflow

The project will be developed across many fresh ChatGPT coding conversations.

GitHub provides:

- the canonical validated tree;
- history and diffs;
- a stable handoff point.

Project docs provide:

- architectural memory;
- rationale;
- current progress;
- future plan.

The human remains the only writer/pusher to GitHub.

## Normal cycle

```text
1. Human pushes validated main
2. New conversation reads current GitHub main
3. Conversation reads project memory + task-relevant files
4. Conversation inspects public upstream sources when external-format knowledge is needed
5. Conversation implements one bounded task
6. Conversation runs sample/available tests
7. Conversation updates project memory
8. Conversation returns:
      changes.zip
        + optional delete_files.bat inside the ZIP
        + optional get_path.bat inside the ZIP
      MANIFEST.txt
9. Human extracts changes.zip over local repo
10. Human reviews MANIFEST.txt
11. Human runs delete_files.bat if present
12. Human runs get_path.bat if present
13. Human reviews git diff
14. Human runs local/full-data validation
15. Human fixes/reports failures as needed
16. Human commits and pushes
17. Next conversation starts from the new main
```

## Why a delta ZIP

The ZIP is a transport format, not project memory.

If only these files changed:

```text
src/octogamedb/importers/foo.py
tests/test_foo.py
docs/project/CURRENT_STATE.md
```

then only those project-relative paths belong in `changes.zip`, apart from required transient root-level handoff helpers.

Unchanged tracked files are intentionally absent.

## Transient handoff helpers

Two root-level BAT helpers may accompany a delta **inside `changes.zip`**:

### `delete_files.bat`

Generated only when stale tracked/untracked project files must be removed because of the task.

ZIP extraction cannot perform deletions, so the BAT carries explicit safe removal operations.

### `get_path.bat`

Generated only when the task or its Level 2 validation requires local source paths not already configured.

It follows `docs/project/LOCAL_PATHS.md`:

```text
reuse configured path
-> search/discover
-> ask only if unresolved/ambiguous
-> validate target
-> update config.local.toml
```

Both helpers are ignored by Git by default.

## Deletion/rename handling

Deletions are explicit in `MANIFEST.txt`.

When needed, `delete_files.bat` is included at the project root inside `changes.zip`.

The human reads the manifest/BAT before executing it.

## Local path/config handling

Personal absolute paths are never committed.

Stable machine-specific source locations belong in ignored:

```text
config.local.toml
```

External source locations normally live under:

```toml
[source_paths]
```

Public addon/source formats should be researched from their current primary repositories/docs rather than inferred from local paths or memory.

The local installed copy is used when version-specific/full-data validation requires it.

## Full-data testing

Large data remains local.

Agents work using:

- code;
- schemas;
- project docs;
- small fixtures;
- public primary source repositories/docs.

The human validates against:

- installed addons when relevant;
- full SQL dumps;
- actual Octo client DBC/WDB;
- full scraped/cached OctoDB data;
- generated full SQLite DB;
- other heavy local sources.

If the validation needs unknown local locations, the delta should contain `get_path.bat` so the user does not have to manually edit paths in source code.

## Audit-only conversations

Not every conversation should write code.

A global audit conversation may:

- inspect architecture vs implementation;
- assess technical debt;
- audit provenance/conflict semantics;
- inspect test coverage;
- reassess roadmap order;
- update project-memory docs.

If it changes project files, it uses the same delta-package delivery contract.

## Safe project evolution

A later insight may justify changing the plan.

That is allowed, but the change must be explicit:

```text
old decision -> problem discovered -> new decision -> consequences
```

The goal is continuity, not freezing an early design forever.
