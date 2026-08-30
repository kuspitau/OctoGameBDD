# Local Canonical Database

## Purpose

OctoGameDB has two distinct sources of truth:

- GitHub `main` is the validated source of truth for tracked code, schema migrations, importers, tests,
  architecture decisions and project memory.
- `data/generated/octogamedb.sqlite3` is the validated cumulative **local canonical data database**.

The SQLite file is generated/local, ignored by Git, and must remain rebuildable from tracked code plus
configured local sources.

## Canonical paths

```text
data/generated/octogamedb.sqlite3
data/generated/octogamedb_bak.sqlite3
```

`octogamedb_bak.sqlite3` is the one-step D-029 rollback state immediately preceding the latest accepted
canonical mutation. Neither SQLite file may be committed or included in `changes.zip`.

## Current accepted baseline — P6-T05 — 2026-08-30

Latest applied migration:

```text
0014_item_template_facts.sql
```

Accepted canonical state:

```text
schema_version = 14
SHA-256        = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Immediate D-029 rollback:

```text
rollback schema_version = 14
rollback SHA-256        = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

The rollback file is the exact byte-for-byte accepted P6-T04 migration-14 canonical immediately before
the P6-T05 incremental write.

### P6-T05 measured promotion

P6-T05 admitted only `refresh_proven_direct_observation` evidence with an exact current WDB raw-record
hash match and did not reapply migration 14.

```text
attempted_unique = 19
refresh_proven = 15
retryable = 3
eligible_item_count = 15
already_current_noop_count = 3
plan_revision = sha256:685f02faa83af9d0c7c7135e244e55702ec867c76670dc8b71bf2ce4ca59b952
```

Coverage measured by the final plan:

```text
canonical_items = 23336
cache_records = 6400
cache_records_with_canonical_identity = 5995
canonical_cache_coverage_ratio = 0.25689921
canonical_item_ids_missing_from_cache_unknown = 17341
cache_only_native_ids = 405
records_with_armor = 2924
records_with_max_durability = 3413
records_with_nonempty_stat_slots = 3438
records_with_nonzero_resistance = 803
```

Shadow validation passed first with `canonical_db_unchanged=true`. The guarded real promotion then
created/verified the exact D-029 backup, committed successfully, kept schema migration 14 and reported
`rollback_available=true`. The full validation runner exited 0.

Measured domain result:

```text
item_templates_promoted = 15
item_templates_new_rows = 15
item_stat_modifiers_promoted = 12
item_stat_modifiers_net_new_rows = 12
source_observations_added_first_pass = 330
first_import rows_inserted / rows_updated = 27 / 0
second_import rows_inserted / rows_updated = 0 / 0
protected_selection_count = 0
foreign_key_check = []
integrity_check = ok
```

Authoritative retained local promotion report:

```text
data/generated/validation_logs/P6-T05_promote_20260830T173826Z.json
```

Current fail-closed tooling defaults to the accepted `60ae...` baseline. Historical P6-T05 replay is
explicit with `--baseline p6-t05-input`; the `d57e...` state remains the immediate rollback and a
historical replay baseline, not the active default.

### P6-T04 historical accepted baseline

The P6-T04 accepted migration-14 state was:

```text
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
item_templates_promoted = 3
item_stat_modifiers_promoted = 2
promoted IDs = 7886, 15784, 41278
foreign_key_check = []
integrity_check = ok
```

Its direct-Octo source and deterministic plan revisions were:

```text
octo-itemcache source revision = sha256:982e7f4cd6ecc075669bdda5c21b4dc7711ef4e1d51806feb8edc721978f9445
plan revision = sha256:7852a2cfd54bbd139420d99e0f42f27c05a54c87611dde1174375da3dacbabc2
```

The first import read/accepted 3 items and inserted five rows across the adopted template/stat
projection; the immediate replay inserted/updated `0 / 0`, proving canonical idempotence. The P6-T04
promotion plan observed 85 `historical_cache_only`, 14 `refresh_proven_direct_observation` and 15,693
`unknown` evidence records; only the three IDs above still had a current WDB record matching a proven
raw-record hash.

It is now the immediate P6-T05 rollback state.

### Earlier migration-13 baseline

Before P6-T04, the accepted migration-13 canonical was:

```text
SHA-256 = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

It remains historical evidence but is no longer the immediate rollback file.

## D-029 protocol

Before any future canonical write:

1. verify the current accepted canonical migration and SHA;
2. reject unexpected SQLite sidecars or concurrent/drifting writers;
3. create/replace `data/generated/octogamedb_bak.sqlite3` as an exact copy of current canonical;
4. SHA-verify the backup before mutation;
5. acquire the required SQLite write lock;
6. perform only the validated migration/import/reconciliation;
7. run all task-required FK, integrity, idempotence and domain checks;
8. restore from `_bak` if any required post-mutation validation fails.

On Windows, preserve the P6-T04/P6-T05 copy-before-lock protocol: raw-copy and SHA verification happen
before the write lock, with `PRAGMA data_version`, size/mtime and sidecar drift checks around the copy
window, followed by `BEGIN IMMEDIATE` before the first write.

## Validation databases and experiments

Prefer a dedicated disposable copy for exploratory imports, first-run Level-2 validation, destructive
rollback tests and promotion rehearsals. A shadow DB may have a different byte-level SHA; only the
observed real canonical hash becomes the accepted baseline.

## Failure and rollback

If a canonical evolution fails after mutation:

- stop further writes;
- preserve diagnostics separately;
- restore `octogamedb.sqlite3` from `octogamedb_bak.sqlite3`;
- reverify the restored migration/hash/integrity;
- do not report the canonical DB as advanced.

## Earlier accepted hashes retained for audit

```text
P4-T03 / migration 12:
6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261

P4-T02 / migration 11:
3e2a1b03dd688fc1b944665fcfa79cde68aacb537790f0c580480049a19ad8e7

P3-T05 / migration 10:
9c637ab40c2c5e3c2843e6c7d52fb5c75bbe05f57d05e2ea4d48ae7bd03b127d
```

## Rebuildability

The canonical local DB is a validated working baseline, not an irreplaceable source artifact. It must
remain rebuildable from tracked migrations/importers, configured local sources, source revisions and
documented ordered import/reconciliation pipelines.

## Agent rule

Expected current local canonical:

```text
data/generated/octogamedb.sqlite3
migration 14
SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Do not ask for generated SQLite files to be committed or packaged. Any future canonical write must
follow this document and its task-specific D-029 protocol.
