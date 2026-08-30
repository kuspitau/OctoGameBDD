# Local Canonical Database

## Purpose

OctoGameDB has two distinct sources of truth:

- GitHub `main` is the validated source of truth for tracked code, schema migrations, importers, tests,
  architecture decisions and project memory.
- `data/generated/octogamedb.sqlite3` is the validated cumulative **local canonical data database**.

The SQLite file is intentionally generated/local, ignored by Git, and must remain rebuildable from
tracked code plus configured local sources.

## Canonical paths

```text
data/generated/octogamedb.sqlite3
data/generated/octogamedb_bak.sqlite3
```

`octogamedb_bak.sqlite3` is the one-step D-029 rollback state immediately preceding the latest accepted
canonical mutation. Neither SQLite file may be committed or included in `changes.zip`.

## Current accepted baseline — P6-T04 — 2026-08-30

The human validated the cumulative local database through **P6-T04 / migration 14**.

Latest applied migration:

```text
0014_item_template_facts.sql
```

Accepted canonical state:

```text
schema_version = 14
SHA-256        = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

Immediate D-029 rollback:

```text
rollback schema_version = 13
rollback SHA-256        = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The rollback file is an exact byte-for-byte copy of the accepted migration-13 canonical immediately
before the P6-T04 write.

### P6-T04 promoted data

P6-T04 used the documented P6 item-template promotion policy and admitted only
`refresh_proven_direct_observation` evidence whose raw-record SHA exactly matched the record currently
present in `itemcache.wdb`.

Accepted eligible/promoted IDs:

```text
7886
15784
41278
```

Observed promotion counts:

```text
item_templates_promoted       = 3
item_stat_modifiers_promoted  = 2
protected_selection_count     = 0
foreign_key_check             = []
integrity_check               = ok
```

Source revision:

```text
octo-itemcache
sha256:982e7f4cd6ecc075669bdda5c21b4dc7711ef4e1d51806feb8edc721978f9445
```

Plan revision:

```text
sha256:7852a2cfd54bbd139420d99e0f42f27c05a54c87611dde1174375da3dacbabc2
```

First import accepted all three requested items and inserted five rows across the adopted template/stat
projection:

```text
rows_read      = 3
rows_accepted  = 3
rows_inserted  = 5
rows_updated   = 0
rows_skipped   = 0
```

The immediate second import proved idempotence:

```text
rows_read      = 3
rows_accepted  = 3
rows_inserted  = 0
rows_updated   = 0
rows_skipped   = 0
```

### Freshness/coverage interpretation

The final promotion plan observed:

```text
historical_cache_only                 =    85
refresh_proven_direct_observation     =    14
unknown                               = 15693
```

Only three records satisfied the current-WDB exact-hash condition at promotion time. Eleven older
refresh-proven records were conservatively excluded because their current records were missing or no
longer matched the proof hash after loss/replacement of the earlier WDB.

This is expected partial-positive coverage, not whole-population item-template coverage.

## D-029 protocol

Before any future canonical write:

1. verify the current accepted canonical migration and SHA;
2. reject unexpected SQLite sidecars or concurrent/drifting writers;
3. create/replace `data/generated/octogamedb_bak.sqlite3` as an exact copy of the current canonical;
4. SHA-verify the backup before mutation;
5. acquire the required SQLite write lock;
6. perform only the validated migration/import/reconciliation;
7. run all task-required FK, integrity, idempotence and domain checks;
8. restore from `_bak` if any required post-mutation validation fails.

### Windows note validated by P6-T04

On Windows, a sequential raw read of the multi-gigabyte SQLite file can fail when performed after
SQLite byte-range locks are already held. The validated P6-T04 approach therefore:

- verifies the accepted source baseline;
- copies and SHA-verifies the raw backup **before** acquiring the write lock;
- uses a live SQLite connection plus `PRAGMA data_version`, file size and mtime checks to detect drift
  around the copy window;
- rejects forbidden sidecars;
- acquires `BEGIN IMMEDIATE` before the first canonical write.

Future promotion tooling must preserve equivalent fail-closed guarantees rather than reintroducing the
raw-read-under-lock failure mode.

## Validation databases and experiments

Prefer a dedicated disposable copy for:

- exploratory imports;
- first-run Level-2 validation of a new importer/reconciliation path;
- destructive or rollback tests;
- promotion rehearsals.

Normal safe sequence:

```text
accepted canonical
-> dedicated validation copy
-> validate complete evolution
-> create/verify D-029 backup
-> acquire guarded write access
-> evolve real canonical
-> final FK/integrity/domain/idempotence checks
-> record new accepted SHA
```

A shadow/rehearsal SQLite file may have a different byte-level SHA from the real promoted canonical.
Only the observed real canonical hash becomes the acceptance constant.

## Failure and rollback

If a canonical evolution fails after mutation:

- stop further writes;
- preserve diagnostics separately;
- restore `octogamedb.sqlite3` from `octogamedb_bak.sqlite3`;
- reverify the restored migration/hash/integrity;
- do not report the canonical DB as advanced.

## Historical accepted baseline — P4-T04 / migration 13

Before P6-T04 the accepted canonical baseline was:

```text
schema_version = 13 / 0013_recipe_acquisition_sources.sql
SHA-256        = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

That exact file is now the P6-T04 D-029 rollback backup. Detailed P4 recipe/acquisition counts and
source revisions remain in the P4 task closeouts and Git history.

Earlier accepted hashes retained for audit/history include:

```text
P4-T03 / migration 12:
6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261

P4-T02 / migration 11:
3e2a1b03dd688fc1b944665fcfa79cde68aacb537790f0c580480049a19ad8e7

P3-T05 / migration 10:
9c637ab40c2c5e3c2843e6c7d52fb5c75bbe05f57d05e2ea4d48ae7bd03b127d
```

## Rebuildability

The canonical local DB is a validated working baseline, not an irreplaceable source artifact. The
project must retain the ability to rebuild it from a fresh SQLite file using:

- tracked migrations/importers;
- `config.local.toml` source paths;
- corresponding local/public source revisions;
- documented ordered import/reconciliation pipelines.

A clean rebuild is appropriate for integrity audits, uncertain provenance or schema/source transitions
that require it. It is not the default cost of every new task.

## Agent rule

When cumulative real data is required, the expected local canonical path is:

```text
data/generated/octogamedb.sqlite3
```

The expected current accepted baseline is migration 14 with SHA-256:

```text
d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

Do not ask for the generated SQLite files to be committed or packaged. If a future task needs to write
the canonical DB, it must follow this document and the task-specific D-029 validation protocol.
