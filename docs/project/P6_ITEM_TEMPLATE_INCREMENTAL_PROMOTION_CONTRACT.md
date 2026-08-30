# P6 migration-14 incremental item-template promotion contract

Status: `VALIDATED`

This contract extends D-036/D-037 and the validated P6-T04 D-029 procedure without changing source
authority or freshness semantics. It defines the reusable migration-14 acquisition/promotion behavior
first exercised by P6-T05.

## 1. Baseline model

Tracked implementation base for the first validated exercise:

```text
GitHub main
ae1ce41e7c155a2f1327157c2b132682cb1d09ae
Validate P6-T04 migration-14 canonical promotion and route P6-T05
```

Named baselines:

```text
ACCEPTED_CANONICAL_BASELINE
migration = 14
SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23

P6_T05_INPUT_BASELINE
migration = 14
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b

P6_T04_INPUT_BASELINE
migration = 13
SHA-256 = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

`octogamedb.canonical_baseline` is the shared fail-closed contract. Active P6 tooling defaults to
`ACCEPTED_CANONICAL_BASELINE`. Historical baselines are selected only explicitly for evidence
validation/replay.

## 2. Bounded acquisition tranche

Active acquisition runner:

```text
scripts/validate_p6_t05_acquisition.py
```

It reuses the validated P6-T03 acquisition engine as an implementation dependency. The historical
`scripts/validate_p6_t03.py` remains unchanged and retains its migration-13 assumptions; callers must
not use it directly as current migration-14 tooling.

Default active artifacts:

```text
data/generated/p6_itemcache_campaign.json
```

Historical P6-T05 replay is explicit:

```powershell
python scripts\validate_p6_t05_acquisition.py report --baseline p6-t05-input
```

and uses:

```text
data/generated/p6_t05_campaign.json
```

Acquisition rules:

- candidate IDs come only from known canonical `items` missing from the current cache;
- no arbitrary numeric/native-ID scanning;
- default batch size is 10;
- one session contains at most 20 IDs;
- batch size is configurable only within `1..20`;
- at most 100 previously unattempted unique IDs may be reserved for one bounded validation tranche;
- retries of already-attempted retryable IDs do not consume another unique-ID slot;
- timeout/missing remains `unknown`, never negative item evidence;
- repeated completed-session import must remain an evidence-preserving duplicate no-op;
- canonical DB remains byte-identical throughout acquisition.

A promotion tranche requires at least 10 current `refresh_proven_direct_observation` items unless a
future task explicitly adopts a different stricter contract. External instability is reported rather
than handled by weakening freshness rules.

## 3. Evidence carried forward

The workflow may consume:

1. retained P6-T02 refresh reports anchored to a named accepted/historical P6 baseline;
2. the historical validated P6-T03 campaign ledger anchored to migration 13, when still present;
3. the current tranche campaign ledger anchored exactly to the selected migration-14 baseline.

Historical evidence remains evidence only. It becomes automatically eligible only when its proven
raw-record SHA exactly matches the raw record in the **current** WDB. Historical/session-only/unknown
classes never gain currentness merely because they are old or still present in a cache.

## 4. Deterministic incremental plan

Implementation:

```text
src/octogamedb/itemcache_incremental_promotion.py
```

Default active plan:

```text
data/generated/p6_itemcache_promotion_plan.json
```

Historical P6-T05 replay plan:

```text
data/generated/p6_t05_promotion_plan.json
```

A refresh-proven item is eligible only when:

- its native ID already exists in canonical `items`;
- its current WDB raw-record SHA equals at least one accepted refresh proof SHA;
- it is not already the effective current direct-Octo canonical projection.

A record whose migration-14 template/stat projection already equals the current WDB and whose relevant
canonical selections already use `octo-itemcache` under `p6-item-template/octo-itemcache` is recorded as
`already_current_direct_projection` and excluded as a no-op.

No cache-only identity can be fabricated.

## 5. Migration-14 -> migration-14 rehearsal

Runner:

```text
scripts/validate_p6_t05.py
```

Default active validation:

```powershell
python scripts\validate_p6_t05.py validate
```

uses the current accepted baseline and current `p6_itemcache_*` artifacts. Historical P6-T05 replay is
explicit:

```powershell
python scripts\validate_p6_t05.py validate --baseline p6-t05-input
```

The rehearsal must:

1. verify the exact selected migration-14 SHA and reject SQLite sidecars;
2. verify the current campaign is anchored to that same baseline;
3. enforce the bounded attempt/refresh-proven gates;
4. build the current-hash incremental plan and identify already-current no-ops;
5. copy canonical byte-for-byte to the selected disposable validation DB;
6. require migration 14 on the copy and require `apply_migrations()` to return no migration;
7. import only newly eligible records;
8. preserve manual/custom/protected selections and competing observations;
9. replay the same import and require zero domain inserts/updates and no new source observations;
10. exercise the migration-14 item query/provenance surface;
11. require clean foreign-key/integrity checks;
12. verify the real canonical DB stayed byte-identical.

The active disposable DB defaults to:

```text
data/generated/p6_itemcache_validation.sqlite3
```

Historical P6-T05 replay uses:

```text
data/generated/p6_t05_validation.sqlite3
```

## 6. Guarded D-029 promotion

Only after a shadow/rehearsal gate succeeds may the selected tranche run `promote`.

The Windows-safe copy-before-lock protocol remains:

1. verify exact selected migration-14 input SHA and no sidecars;
2. remove/replace the prior `_bak` file;
3. open a live connection and record `PRAGMA data_version` + source size/mtime;
4. copy canonical to `data/generated/octogamedb_bak.sqlite3` **before** acquiring the write lock;
5. SHA-verify the backup equals the selected input baseline;
6. reject data-version/file-metadata/sidecar drift during the copy window;
7. acquire `BEGIN IMMEDIATE` and re-check drift before the first write;
8. run the exact incremental import/idempotence/query/integrity gates;
9. commit and require schema migration to remain 14;
10. keep `_bak` byte-identical to the immediate pre-promotion migration-14 canonical.

If any post-backup gate fails, close the SQLite connection, remove failed-write sidecars, restore
canonical from `_bak`, and verify the exact selected input SHA.

Historical P6-T05 `promote --baseline p6-t05-input` is a reproduction path and must only be used on a
dedicated copy of the historical `d57e...` input baseline, not on the already-promoted current DB.

## 7. Read-only baseline verification

Current canonical:

```powershell
python scripts\validate_p6_t05.py verify-baseline
```

Expected:

```text
P6_CANONICAL_BASELINE_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
canonical_migration=14
foreign_key_check=[]
integrity_check=ok
```

Immediate P6-T05 rollback:

```powershell
python scripts\validate_p6_t05.py verify-baseline `
  --baseline p6-t05-input `
  --db data\generated\octogamedb_bak.sqlite3
```

## 8. Required measured closure report

Every promoted tranche records at minimum:

```text
canonical item population
current matching WDB coverage
new attempted unique IDs
new refresh-proven count
new unknown/retryable count
eligible incremental IDs
already-current/no-op count
new item_template rows
net new item_stat_modifier rows
final canonical SHA-256
rollback SHA-256
migration after promotion (=14)
foreign_key_check
integrity_check
```

After a successful real promotion, the newly accepted SHA must be copied into `CURRENT_STATE.md`,
`CANONICAL_DB.md`, and `ACCEPTED_CANONICAL_BASELINE` before later active tooling treats the evolved DB
as current.

## 9. P6-T05 validated outcome — 2026-08-30

The first exercise of this contract succeeded against the real client/local canonical DB:

```text
attempted_unique = 19
refresh_proven = 15
unknown = 17447
retryable = 3
eligible_item_count = 15
already_current_noop_count = 3
item_templates_new_rows = 15
item_stat_modifiers_net_new_rows = 12
source_observations_added_first_pass = 330
first import inserts / updates = 27 / 0
second import inserts / updates = 0 / 0
protected_selection_count = 0
canonical migration = 14
canonical SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
rollback SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
rollback_available = true
foreign_key_check = []
integrity_check = ok
```

Authoritative retained local promotion report:

```text
data/generated/validation_logs/P6-T05_promote_20260830T173826Z.json
```

The full v5 runner completed with exit code `0` after successful shadow validation and guarded
canonical promotion.

## 10. Non-goals

This contract does not provide exhaustive item acquisition, does not reapply/create a migration, does
not promote historical/session-only/unknown evidence, does not create placeholder identities, and
does not broaden the P6-T01 field family. Weapon damage/speed/block, item effects/spells/tooltips and
fallback-source authority remain separate consumer-driven work.
