# Local Canonical Database

## Purpose

OctoGameDB has two different kinds of project truth that must not be confused.

- GitHub `main` is the validated source of truth for tracked code, schema migrations, importers,
  tests, configuration examples, architecture decisions and project memory.
- `data/generated/octogamedb.sqlite3` is the **canonical local data database**: the complete local
  materialization of all gameplay-data stages that have been fully validated up to the current
  project state.

The SQLite file is intentionally not committed. It is large, depends on machine-local source inputs,
and can be rebuilt from tracked code plus configured local sources.

## Canonical paths

```text
data/generated/octogamedb.sqlite3
```

is the canonical local database.

When a task is going to mutate it, the single rollback copy is:

```text
data/generated/octogamedb_bak.sqlite3
```

Both files are generated/local artifacts and remain ignored by Git.

## Current baseline

As of the P3-T05 closeout on 2026-08-26, the human has validated the cumulative database through the
complete P1/P2 chain plus P3-T01 through P3-T05. The canonical local DB is therefore **validated
through P3-T05 / migration 10**.

P3-T05 applied:

```text
0010_quest_item_facts.sql
```

after successful disposable full-data validation and an isolated D-029 shadow exercise.

The real canonical database was verified with:

```text
schema_version                   = 10
foreign_key_check                = []
integrity_check                  = ["ok"]
failed_import_batches            = 0
invalid_required_quantity_count  = 0
```

P3-T05 canonical family counts are:

```text
quest_required_items       6100
quest_required_sources     2961
quest_provided_items       1320
quest_reward_items         2072
quest_choice_reward_items  2424
```

Validated P3-T05 source identities/revisions are:

```text
tortoise-world-sql
61a8269151721f6467eddb05e7bed37704d0fc0b
content:dce8653d8daf829e3b28f585ed4e200cc32f32819ffaa6f92aa4c4ce7bd14299

octo-live-quest-query
e793f80f6b45ed49a94dc8abdc9fcac4fe6b03dd
capture:71de2543b3b7e008dd229d82cb5372e163e08c117cc3b354229ff2b0ef71dedc

octodb
0f81f0908cc3b8082ae2897901b88c61f24c916c04bf3c4c6b627eb09f53e533

cmangos-vanilla
250a705a462c1acb457d3002359c7e0052c4dafe:0a77f5230a3d5d6db968678203dfe3b30c34b8a9
```

The accepted P3-T05 D-033 comparison hash is:

```text
ac376ec58584c59446eb6c6d448b6f6565fb3f14593c27b60c13e539e43cea50
```

The validation retains `268` unresolved item/quest targets as explicit warning/provenance evidence,
with no same-priority ambiguity or reconciliation anomaly. Four cross-source value conflicts remain
auditable. At least one real `ReqSourceCount = 0` observation is preserved as raw source semantics and
does not create a non-positive ordinary quest requirement.

Closeout SHA-256 values are:

```text
migration-9 rollback backup:
3dc2a49092d108a1274e55e3052b3ba74711b5ec0f675c9ff2a201c287617443

validated migration-10 canonical:
9c637ab40c2c5e3c2843e6c7d52fb5c75bbe05f57d05e2ea4d48ae7bd03b127d
```

The `_bak` file is the immediate pre-P3-T05 migration-9 rollback state. It may remain until the next
validated canonical mutation cycle replaces it.

Earlier phase-specific counts/revisions remain documented in their task closeouts; this file records
the current cumulative baseline rather than duplicating every historical metric.

The current task router (`docs/project/CURRENT_STATE.md`) records which next task may consume this
baseline.

## Before mutating the canonical DB

Any task that will write to `data/generated/octogamedb.sqlite3` must create an exact backup **before
the first mutation**:

1. close any process/connection that may be writing the canonical DB;
2. if `data/generated/octogamedb_bak.sqlite3` already exists, replace it;
3. copy `octogamedb.sqlite3` to `octogamedb_bak.sqlite3`;
4. only then begin migrations/import/reconciliation that may alter the canonical DB.

The `_bak` file is intentionally a one-step rollback snapshot, not historical version storage. Do
not accumulate timestamped canonical backups unless a task has a specific diagnostic reason.

## Validation databases and experiments

Prefer a dedicated copy for:

- exploratory imports;
- potentially destructive reconciliation tests;
- first-run Level-2 validation of an unvalidated importer;
- experiments whose outcome should not immediately become the new canonical state.

A typical safe sequence is:

```text
canonical DB
-> dedicated validation copy
-> validate importer/reconciliation and invariants
-> create/replace canonical _bak
-> apply the validated evolution to canonical DB
-> final FK/integrity/domain checks
```

A task may instead evolve the canonical DB directly after making `_bak` when its validation protocol
explicitly calls for that flow and rollback is safe.

## Failure and rollback

If a canonical evolution fails after the canonical DB has been modified:

- stop further writes;
- preserve useful diagnostics separately if needed;
- restore `octogamedb.sqlite3` from `octogamedb_bak.sqlite3` before treating the local canonical state
  as valid again.

Do not report the canonical DB as advanced until the task's required Level-2 checks have passed.

## Successful evolution

After a task is fully validated:

- `octogamedb.sqlite3` becomes the canonical local database through that newly validated task;
- update `CURRENT_STATE.md` and the task closeout to state that level explicitly;
- `_bak` may remain as the immediately previous rollback state, or be replaced on the next canonical
  mutation cycle;
- never add either SQLite file to the delta ZIP or Git.

## Rebuildability

The canonical local DB is a convenience, validated working baseline and test dependency. It is **not**
an irreplaceable source artifact.

The project must retain the ability to rebuild it from a fresh SQLite file using:

- tracked migrations/importers;
- `config.local.toml` source paths;
- the corresponding local source revisions;
- the documented ordered import/reconciliation pipeline.

A clean rebuild is appropriate for integrity audits, source changes, schema transitions that require
it, or when the provenance of an existing local DB is uncertain. It should not be the default cost
paid by every new task when a known-good canonical DB already exists.

## Agent rule

When a coding conversation needs cumulative real data, it must not assume the database is absent
merely because GitHub cannot expose it. The expected local path is
`data/generated/octogamedb.sqlite3`.

If local validation needs that file and the conversation cannot inspect the user's filesystem, give
the human exact validation commands/scripts against that path. Do not ask for the multi-gigabyte DB
to be committed or included in `changes.zip`.
