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
4. Conversation implements one bounded task
5. Conversation runs sample/available tests
6. Conversation updates project memory
7. Conversation returns:
      changes.zip
      MANIFEST.txt
      optional delete_files.bat
8. Human extracts over local repo
9. Human reviews git diff
10. Human runs local/full-data validation
11. Human fixes/reports failures as needed
12. Human commits and pushes
13. Next conversation starts from the new main
```

## Why a delta ZIP

The ZIP is a transport format, not project memory.

If only these files changed:

```text
src/octogamedb/importers/foo.py
tests/test_foo.py
docs/project/CURRENT_STATE.md
```

then only those project-relative paths belong in `changes.zip`.

Unchanged files are intentionally absent.

## Deletion/rename handling

ZIP extraction cannot remove stale files.

Therefore deletions are explicit in `MANIFEST.txt` and, when needed, an accompanying safe `delete_files.bat` is provided.

The human reads the BAT before executing it.

## Full-data testing

Large data remains local.

Agents work using:

- code;
- schemas;
- project docs;
- small fixtures.

The human validates against:

- full SQL dumps;
- actual Octo client DBC/WDB;
- full scraped/cached OctoDB data;
- generated full SQLite DB;
- other heavy local sources.

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
