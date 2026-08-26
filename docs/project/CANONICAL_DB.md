# Local Canonical Database

## Purpose

OctoGameDB has two different kinds of project truth that must not be confused.

- GitHub `main` is the validated source of truth for tracked code, schema migrations, importers,
  tests, configuration examples, architecture decisions and project memory.
- `data/generated/octogamedb.sqlite3` is the **canonical local data database**: the complete local
  materialization of all gameplay-data stages that have been fully validated up to the current
  project state.

The SQLite file is intentionally not committed. It is local/generated, depends on machine-local
source inputs, and must remain rebuildable from tracked code plus configured local sources.

## Canonical paths

```text
data/generated/octogamedb.sqlite3
```

is the canonical local database. The one-step D-029 rollback is:

```text
data/generated/octogamedb_bak.sqlite3
```

Both remain ignored by Git and must never be included in `changes.zip`.

## Current baseline

As of the P4-T03 closeout on 2026-08-26, the human has validated the cumulative local database
through **P4-T03 / migration 12**.

Latest applied migration:

```text
0012_recipe_reagents.sql
```

P4-T03 extends the validated recipe identity slice with:

```text
recipe_reagents
```

Each row preserves the native reagent item ID, native Spell reagent slot/index and exact matching
`Spell.ReagentCount` quantity. Canonical `item_id` remains nullable when the item identity is not yet
materialized; unresolved native IDs are retained as evidence rather than replaced by placeholders.

The real canonical database was promoted only after successful disposable Level-2 validation and a
non-destructive shadow promotion using the real local data/source files. Final post-promotion checks
are:

```text
schema_version                      = 12
recipe_count                        = 1739
recipe_reagent_count                = 5801
recipes_with_reagents               = 1721
unresolved_reagent_count            = 85
zero_quantity_reagent_count         = 0
ignored_negative_reagent_slot_count = 0
protected_selection_count           = 0
matching_successful_import_batches  = 2
foreign_key_check                   = []
integrity_check                     = ok
```

The second import during guarded promotion was canonically idempotent:

```text
rows_inserted = 0
rows_updated  = 0
```

Validated P4-T03 Octo DBC source revision:

```text
sha256:f82d41ddbb77f5958d36b2483786c819de512128ef736142c758469718f7274d
```

Validated source layouts/counts:

```text
Spell.dbc             173 fields / 692 bytes / 28001 records
SkillLine.dbc          22 fields /  88 bytes /   136 records
SkillLineAbility.dbc   15 fields /  60 bytes /  6795 records
```

The `85` unresolved reagent targets preserve exact native item IDs, reagent slots and required
quantities with nullable canonical `item_id`. They are warnings/provenance evidence, not fabricated
item identities or import failures.

### Current rollback/canonical hashes

```text
migration-11 rollback backup:
3e2a1b03dd688fc1b944665fcfa79cde68aacb537790f0c580480049a19ad8e7

validated migration-12 canonical:
6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261
```

The `_bak` is the exact byte-for-byte canonical database immediately before P4-T03 promotion. It may
remain until the next validated canonical mutation cycle replaces it.

## Historical P4-T02 baseline

P4-T02 validated migration 11 / `0011_recipe_identity.sql`. Its canonical hash was:

```text
3e2a1b03dd688fc1b944665fcfa79cde68aacb537790f0c580480049a19ad8e7
```

That exact file is now the current D-029 rollback backup after P4-T03 promotion. P4-T02 validated
1,739 recipes, 15 represented skill lines, 1,739 outputs, 114 unresolved output targets and the same
Octo DBC source revision used by P4-T03.

## Historical P3-T05 baseline

P3-T05 had previously validated migration 10 / `0010_quest_item_facts.sql`. Its canonical hash was:

```text
9c637ab40c2c5e3c2843e6c7d52fb5c75bbe05f57d05e2ea4d48ae7bd03b127d
```

Earlier P3 counts, source revisions and D-033 evidence remain documented in the corresponding P3 task
closeouts rather than duplicated here.

## Before mutating the canonical DB

Any future task that writes to `data/generated/octogamedb.sqlite3` must create an exact backup before
the first mutation:

1. close any process/connection that may be writing the canonical DB;
2. replace `data/generated/octogamedb_bak.sqlite3` with an exact copy of the current canonical DB;
3. verify the copy when the task's validation protocol requires it;
4. only then begin migrations/import/reconciliation.

The `_bak` file is intentionally a one-step rollback snapshot, not historical version storage.

## Validation databases and experiments

Prefer a dedicated copy for:

- exploratory imports;
- potentially destructive reconciliation tests;
- first-run Level-2 validation of an unvalidated importer;
- experiments whose outcome should not immediately become the new canonical state.

Normal safe sequence:

```text
canonical DB
-> dedicated validation copy
-> validate importer/reconciliation and invariants
-> create/replace canonical _bak
-> apply the validated evolution to canonical DB
-> final FK/integrity/domain checks
```

## Failure and rollback

If a canonical evolution fails after mutation:

- stop further writes;
- preserve diagnostics separately if needed;
- restore `octogamedb.sqlite3` from `octogamedb_bak.sqlite3` before treating the local canonical
  state as valid again.

Do not report the canonical DB as advanced until the task's required Level-2 checks pass.

## Successful evolution

After a task is fully validated:

- `octogamedb.sqlite3` becomes the canonical local database through that task;
- update `CURRENT_STATE.md`, `CANONICAL_DB.md` and the task closeout with real evidence/hashes;
- `_bak` may remain as the immediately previous rollback state until the next mutation cycle;
- never add either SQLite file to Git or a delta ZIP.

## Rebuildability

The canonical local DB is a validated working baseline, not an irreplaceable source artifact. The
project must retain the ability to rebuild it from a fresh SQLite file using:

- tracked migrations/importers;
- `config.local.toml` source paths;
- corresponding local source revisions;
- the documented ordered import/reconciliation pipeline.

A clean rebuild is appropriate for integrity audits, source changes, uncertain provenance or schema
transitions that require it. It should not be the default cost for every new task when a known-good
canonical DB already exists.

## Agent rule

When a coding conversation needs cumulative real data, it must not assume the database is absent
merely because GitHub cannot expose it. The expected local path is:

```text
data/generated/octogamedb.sqlite3
```

The expected current validated baseline is migration 12 with SHA-256:

```text
6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261
```

If local validation needs that file and the conversation cannot inspect the user's filesystem, give
the human exact validation commands/scripts against that path. Do not ask for the generated DB to be
committed or packaged.
