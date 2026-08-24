# Repository and Handoff Workflow

## Why this workflow

The project will be developed across many fresh ChatGPT coding conversations.

GitHub provides:

- the canonical validated tracked tree;
- history and diffs;
- a stable handoff point.

Project docs provide:

- architectural memory;
- rationale;
- current progress;
- future plan.

The human remains the only writer/pusher to GitHub.

Large generated data has a separate local lifecycle. In particular,
`data/generated/octogamedb.sqlite3` can be the validated cumulative local DB while remaining absent
from GitHub. See `docs/project/CANONICAL_DB.md`.

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
16. If canonical local DB must advance, follow the backup/evolution rules below
17. Human commits and pushes
18. Next conversation starts from the new main
```

## Why a delta ZIP

The ZIP is a transport format, not project memory.

If only these files changed:

```text
src/octogamedb/importers/foo.py
tests/test_foo.py
docs/project/CURRENT_STATE.md
```

then only those project-relative paths belong in `changes.zip`, apart from required transient
root-level handoff helpers.

Unchanged tracked files are intentionally absent. Generated local SQLite databases are never part of
the delta ZIP.

## Transient handoff helpers

Two root-level BAT helpers may accompany a delta **inside `changes.zip`**:

### `delete_files.bat`

Generated only when stale tracked/untracked project files must be removed because of the task.

ZIP extraction cannot perform deletions, so the BAT carries explicit safe removal operations.

### `get_path.bat`

Generated only when the task or its Level 2 validation requires local source paths not already
configured.

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

Public addon/source formats should be researched from their current primary repositories/docs rather
than inferred from local paths or memory.

The local installed copy is used when version-specific/full-data validation requires it.

## Canonical local DB workflow

The validated cumulative data baseline is normally:

```text
data/generated/octogamedb.sqlite3
```

when `CURRENT_STATE.md` states that it has been built and validated through the required project
stage.

Do not confuse this with GitHub source of truth: GitHub owns the tracked implementation and durable
rules; the SQLite file is their local full-data materialization.

### Read-only/full-data checks

A task that only needs to inspect/query cumulative real data should use the canonical local DB rather
than rebuilding P1/P2/P3 from zero or guessing which historical validation DB is complete.

### Before a canonical mutation

Before the first write:

```text
data/generated/octogamedb.sqlite3
-> copy/replace -> data/generated/octogamedb_bak.sqlite3
-> then mutate canonical DB
```

If `_bak` exists, replace it. It is a one-step rollback snapshot, not a growing backup history.

For first-run or destructive validation, prefer a separate temporary/dedicated DB copy. Once an
implementation is accepted, evolve the canonical DB under the backup rule and run its final integrity
checks.

### Failure

If a canonical evolution fails after writes occurred, restore from `_bak` before the canonical DB is
considered valid again. Preserve diagnostics separately when useful.

### Success

After successful Level 2 closure, `CURRENT_STATE.md` and the task document record that the canonical
local DB now includes the new task. Neither canonical nor backup DB is committed.

The project must remain capable of a clean rebuild from tracked migrations/importers plus configured
local source inputs. See `docs/project/CANONICAL_DB.md` for the complete contract.

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
- the generated canonical SQLite DB or safe copies of it;
- other heavy local sources.

If validation needs unknown local locations, the delta should contain `get_path.bat` so the user does
not have to manually edit paths in source code.

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
