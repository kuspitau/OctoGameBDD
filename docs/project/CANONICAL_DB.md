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

As of the P3-T03 closeout on 2026-08-24, the human has validated the cumulative database through the
complete P1/P2 chain plus P3-T01, P3-T02 and P3-T03. The canonical local DB is therefore
**validated through P3-T03**.

P3-T03 applied migration 8 and successfully reconciled quest progression/restriction facts from the
configured pfQuest and pfQuest-turtle trees. The final same-revision pass produced zero canonical
inserts, updates or deletes; `PRAGMA foreign_key_check` and `PRAGMA integrity_check` both passed.

Validated quest source revisions are:

```text
base pfQuest quests/progression
sha256:667303b5507015b4039508e6a8f8afc0f6c086f285d5dc56afd0addb79cbe8e3

pfQuest-turtle quests/progression
sha256:234f8062f8006d5dc17c526b81772cf50f8591170781ae5af8b72a86b237d25a
```

P3-T03 validator-reported canonical counts are:

```text
quests                          6498
quest_prerequisite_sets         3533
quest_prerequisite_set_members  3716
quest_close_sets                303
quest_close_set_members         1095
import_batches                  16
observation_groups              1167121
canonical_selections            1157241
source_observations             2059171
```

The current task router (`docs/project/CURRENT_STATE.md`) records the next task that may consume this
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
