# Local Source Paths and `get_path.bat`

This document defines how coding conversations handle files/directories that exist only on the user's machine.

Examples include:

- the local OctoWoW installation root;
- installed addons such as pfQuest, pfQuest-turtle and optional pfQuest-octo;
- local public-source checkouts such as `Penqle/tortoise-wow`;
- WDB caches;
- extracted DBC directories;
- SavedVariables;
- large SQL dumps;
- other source datasets intentionally kept out of Git.

## Core rule

User-specific absolute paths are **configuration**, not source code.

Do not:

- hard-code paths such as `C:\Games\...` in project code;
- write personal absolute paths into tracked `config.example.toml`;
- assume a standard World of Warcraft installation path is correct;
- require the user to repeatedly paste the same paths into future conversations.

Machine-specific paths belong in the ignored:

```text
config.local.toml
```

External source paths use the section:

```toml
[source_paths]
```

Add stable keys only when a real task needs them.

## Public source first

When the task needs to understand the structure/format/semantics of a public addon or external project:

1. inspect its primary repository/source;
2. inspect current docs/code;
3. inspect relevant issues/discussions/history when ambiguity materially affects implementation;
4. use small tracked fixtures for deterministic parser tests;
5. use the user's installed copy only when local/version-specific validation is actually needed.

Do not ask the user to upload an entire public addon merely to learn a format that can be inspected from its authoritative source.

## When `get_path.bat` is required

A coding conversation must create a task-specific `get_path.bat` when its implementation or required local validation needs one or more paths that are not already safely available through tracked configuration or existing project discovery code.

`get_path.bat` is a transient handoff helper:

- place it at the **project root** inside `changes.zip`;
- it is ignored by Git;
- do not treat it as a permanent tracked project file unless a later explicit decision changes that policy.

If the task does not need local path acquisition, do not create it.

## Required behavior of `get_path.bat`

For each required target, use this order:

1. **Reuse** an existing configured value if it exists and validates.
2. **Discover** likely locations when discovery can be done safely and cheaply.
3. If exactly one valid match is found, use it.
4. If zero or multiple ambiguous matches remain, **ask the user**.
5. Validate the selected target before saving it.
6. Update only the intended key(s) in `config.local.toml`.
7. Print a final summary of resolved/unresolved keys.
8. Exit non-zero if a path required for the task remains unresolved.

Optional comparison/enrichment sources may be reused or discovered without prompting and must not make a helper fail when they are absent.

The user should be able to paste or drag/drop a Windows path into the prompt. Strip surrounding quotes safely.

## Validation

Do not validate only with "directory exists".

Validate source identity with task-relevant markers when practical.

Examples:

```text
pfQuest directory
  -> expected addon files/subdirectories are present

pfQuest-turtle directory
  -> expected addon metadata/data/patch files are present

pfQuest-octo directory
  -> expected addon metadata/data/patch files are present

WDB directory
  -> expected .wdb files or known cache structure are present

SQL dump
  -> expected file extension/content marker as appropriate
```

A future task should define the exact markers it needs.

### P1-T03 path contract

Required:

```toml
[source_paths]
pfquest = "..."
pfquest_turtle = "..."
```

Optional comparison source:

```toml
pfquest_octo = "..."
```

P1-T03 `get_path.bat` resolves and validates the required pfQuest + pfQuest-turtle pair. An existing `pfquest_octo` entry is unrelated configuration and must be preserved; its absence must not make the helper fail.

### P3-T05B path contract

Required for Level-2 validation:

```toml
[source_paths]
wow_root = "..."
tortoise_repo = "..."
```

Validation markers:

```text
wow_root
  -> WoW.exe/Wow.exe exists
  -> Interface/AddOns exists

tortoise_repo
  -> sql/base/tw_world_quest_template.sql exists
  -> sql/database_updates/world exists
```

The P3-T05B `get_path.bat` delegates to:

```text
python scripts/validate_p3_t05b.py configure-paths
```

That command reuses valid configured values, tries bounded common-location discovery, asks only for unresolved/ambiguous targets, and updates only `wow_root` / `tortoise_repo` in the ignored `config.local.toml`.

The Tortoise validation command independently verifies the actual Git revision. Normal P3-T05B validation requires:

```text
61a8269151721f6467eddb05e7bed37704d0fc0b
```

The live probe SavedVariables path is deliberately **not** persisted as a stable config key. The normalizer discovers `WTF/Account/*/SavedVariables/OctoGameBDD_QuestProbe.lua` below the configured `wow_root` when exactly one match exists; with multiple account files, the user passes `--saved-variables` explicitly for that run.

## Updating `config.local.toml`

`get_path.bat` must be idempotent and preserve unrelated settings.

Preferred order:

1. use an existing project-owned Python configuration helper if one exists;
2. otherwise the BAT may invoke built-in PowerShell for safe targeted editing;
3. avoid brittle whole-file rewrites with shell text substitution.

If `config.local.toml` does not exist, initialize it from `config.example.toml` or create the minimum valid structure needed by the current task.

Do not write secrets into this file unless a later explicit project decision establishes a secret-management policy.

## Handoff manifest requirements

When `get_path.bat` is included, `MANIFEST.txt` must state:

- that `get_path.bat` is present inside `changes.zip`;
- why it is needed;
- which config keys it may create/update;
- which paths/files it searches for;
- when the user should run it;
- what successful resolution should look like.

## Anticipating upcoming requirements

A task may prepare generic path/config infrastructure required by the immediately following task when doing so is low-risk and avoids a known blocker.

Do not use "anticipation" as permission to implement unrelated future importers or broad milestones early.
