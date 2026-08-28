# Local Source Paths and `get_path.bat`

This document defines how coding conversations handle files/directories that exist only on the user's
machine.

Examples include:

- the local OctoWoW installation root;
- installed addons such as pfQuest, pfQuest-turtle and pfQuest-octo;
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

External source paths use:

```toml
[source_paths]
```

Add stable keys only when a real task needs them.

## Public source first

When a task needs public addon/project semantics:

1. inspect the primary repository/source;
2. inspect current docs/code;
3. inspect relevant issues/discussions/history when ambiguity materially affects implementation;
4. use small tracked fixtures for deterministic parser tests;
5. use the user's installed copy only for local/version-specific validation.

Do not request a whole public addon merely to learn a format available from its authoritative source.

## When `get_path.bat` is required

A coding conversation creates a task-specific `get_path.bat` when implementation or required local
validation needs paths not already safely available through tracked configuration or existing project
discovery code.

`get_path.bat` is a transient handoff helper:

- place it at the **project root** inside `changes.zip`;
- it is ignored by Git;
- do not make it permanent tracked source unless a later decision explicitly changes that policy.

If the task does not need local path acquisition, do not create it.

## Required behavior of `get_path.bat`

For every required target:

1. reuse an existing configured value if it exists and validates;
2. discover likely locations when discovery is safe and cheap;
3. use exactly one valid discovered match automatically;
4. if zero or multiple ambiguous matches remain, ask the user;
5. validate the selected target before saving it;
6. update only the intended key(s) in `config.local.toml`;
7. print a final resolved/unresolved summary;
8. exit non-zero while any required path remains unresolved.

Optional comparison/enrichment sources may be reused/discovered without prompting and must not fail a
helper merely because they are absent, except when a task explicitly promotes such a source to a
required validation input.

The user should be able to paste or drag/drop a Windows path. Strip surrounding quotes safely.

## Validation

Do not validate only that a directory exists. Validate source identity with task-relevant markers or
content revisions when practical.

Examples:

```text
pfQuest directory
  -> expected addon data/localization files exist

pfQuest-turtle / pfQuest-octo directory
  -> supported Turtle-style world data files exist

WDB directory
  -> expected .wdb files or known cache structure exists

SQL dump
  -> expected file extension/content marker as appropriate
```

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

P1-T03 `get_path.bat` resolves and validates the required pfQuest + pfQuest-turtle pair. An existing
`pfquest_octo` entry is unrelated configuration and must be preserved; its absence must not make that
P1 helper fail.

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

The P3-T05B helper delegates to:

```text
python scripts/validate_p3_t05b.py configure-paths
```

It reuses valid configured values, tries bounded common-location discovery, asks only for
unresolved/ambiguous targets, and updates only `wow_root` / `tortoise_repo`.

The Tortoise validation command independently verifies revision:

```text
61a8269151721f6467eddb05e7bed37704d0fc0b
```

The live probe SavedVariables path is deliberately not persisted as a stable config key. The
normalizer discovers `WTF/Account/*/SavedVariables/OctoGameBDD_QuestProbe.lua` below `wow_root` when
exactly one match exists; with multiple account files the user passes `--saved-variables` explicitly.

### P5-T07 path contract

P5-T07 changes the P1 optionality for this bounded audit: **all three** raw pfQuest-family roots are
required because the task must reconstruct the exact comparison view as well as base and active view.

```toml
[source_paths]
pfquest = "..."
pfquest_turtle = "..."
pfquest_octo = "..."
```

Exact required content revisions:

```text
pfquest
sha256:5087d2d0a5b1c2706b7fc7ccb5ffd447c91aa24d91a23f102f2c7ac1d7440147

pfquest_turtle
sha256:7fd719cac7a7a26e80c6865fa62b6100ccfa2301dabe3b2a399c0f1551372d8c

pfquest_octo
sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db
```

The transient root helper:

```text
get_path.bat
```

delegates to tracked:

```text
python scripts/configure_p5_t07_paths.py
```

The configurator:

- reuses a configured path only if its exact existing P1 content revision matches;
- tries bounded environment/addon-sibling/project-sibling discovery;
- automatically accepts only one exact-revision match;
- prompts for unresolved paths;
- rejects a directory that has plausible addon markers but the wrong content revision;
- updates only `pfquest`, `pfquest_turtle`, and `pfquest_octo` under `[source_paths]`;
- preserves unrelated config sections/keys;
- is idempotent;
- exits non-zero unless all three exact roots are resolved.

For P5-T07, `pfquest_octo` must not be treated as optional merely because it was optional in P1-T03.

After successful path setup run:

```text
validate_P5_T07_full_local.bat
```

The semantic validator independently recomputes all three revisions before any raw-source conclusion,
so a later local source update fails closed instead of silently changing the audited evidence.

## Updating `config.local.toml`

`get_path.bat` must be idempotent and preserve unrelated settings.

Preferred order:

1. use an existing project-owned Python configuration helper if one exists;
2. otherwise the BAT may invoke built-in PowerShell for safe targeted editing;
3. avoid brittle whole-file rewrites with shell text substitution.

If `config.local.toml` does not exist, initialize it from `config.example.toml` or create the minimum
valid structure needed by the current task.

Do not write secrets into this file unless a later explicit project decision establishes a
secret-management policy.

## Handoff manifest requirements

When `get_path.bat` is included, `MANIFEST.txt` states:

- that `get_path.bat` is present inside `changes.zip`;
- why it is needed;
- which config keys it may create/update;
- which paths/files it searches for;
- when the user should run it;
- what successful resolution looks like.

## Anticipating upcoming requirements

A task may prepare generic path/config infrastructure required by the immediately following task when
low-risk and useful. This is not permission to implement unrelated future importers or broad
milestones early.
