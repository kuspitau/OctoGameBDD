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

As of the P3-T04 closeout on 2026-08-25, the human has validated the cumulative database through the
complete P1/P2 chain plus P3-T01, P3-T02, P3-T03 and P3-T04. The canonical local DB is therefore
**validated through P3-T04**.

P3-T04 applied migration 9 and successfully reconciled quest objective membership, item-use target
support and area-trigger location support from the configured pfQuest and pfQuest-turtle trees. The
final same-revision pass produced zero canonical inserts, updates or deletes; `PRAGMA
foreign_key_check` and `PRAGMA integrity_check` both passed.

Validated P3-T04 source revisions are:

```text
base pfQuest objectives
sha256:2acc862f732bc512482eaaec0b86a2a5d67c548d8cc50f7b6128f5ffba27a58c

pfQuest-turtle objectives
sha256:8e570cb4303e73fae03d6b4240b0122f0000f35dd441aca686feed039641f90f
```

P3-T04 validator-reported canonical counts are:

```text
quests                         6498
quest_objective_sets           4224
quest_creature_objectives      1484
quest_gameobject_objectives    99
quest_item_objectives          5064
quest_item_use_objectives      226
quest_area_trigger_objectives  50
quest_zone_objectives          0
area_triggers                  496
area_trigger_locations         558
item_use_target_sets           189
item_use_creature_targets      113
item_use_gameobject_targets    220
import_batches                 20
observation_groups             1182571
canonical_selections           1172691
source_observations            2083312
```

The task validator also reports `219` unresolved objective/support references as explicit warnings
(`188` missing quest identities, `30` missing creature identities and `1` missing item identity).
These are preserved audit evidence and do not represent FK or integrity failures.

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
