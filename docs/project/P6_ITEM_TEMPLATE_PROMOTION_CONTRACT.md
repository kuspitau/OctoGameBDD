# P6 migration-14 item-template promotion contract

Status: `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`

This document defines the bounded P6-T04 policy for the first D-029 promotion of migration 14 into the
cumulative canonical local database. It reuses D-036 and D-037 without introducing a new source
priority or freshness decision.

## 1. Baseline and scope

Tracked implementation base:

```text
GitHub main
8e4dd342e9ceaec171b00d0ffab49bc47f52101a
Validate P6-T03 direct-Octo acquisition campaign and route P6-T04
```

Accepted canonical local database before P6-T04 remains:

```text
migration = 13 / 0013_recipe_acquisition_sources.sql
SHA-256 = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

P6-T04 does not broaden the P6-T01 field family. Migration 14 still covers only the already accepted
item-template scalar fields and ordered ten-slot raw stat payload described by
`P6_ITEM_TEMPLATE_SOURCE_CONTRACT.md`.

## 2. Canonical-promotion eligibility

D-036 establishes that a supported `itemcache.wdb` record is direct Octo positive evidence. D-037
separately defines currentness. P6-T04 therefore uses the following canonical-selection policy:

| Freshness class | Automatic P6-T04 canonical selection | Reason |
| --- | --- | --- |
| `refresh_proven_direct_observation` | eligible only with exact current raw-record hash match | persisted field bytes have explicit current-session refresh proof |
| `session_observed_freshness_limited` | excluded | current session succeeded, but no persisted source-shaped field bytes were proven |
| `historical_cache_only` | excluded from this promotion | positive direct evidence, but current-server freshness is not established |
| `unknown` | excluded | insufficient evidence; never negative evidence or selection authority |

A refresh-proven item is not eligible merely because its native ID still exists in the cache. The raw
record SHA-256 in the current `itemcache.wdb` must equal at least one previously validated
refresh-proven post-record SHA-256. If the cache record is missing or its bytes drift, that old proof is
retained as evidence but is excluded from the current promotion plan.

This is intentionally narrower than importing every historical cache record. It creates a first
trustworthy migration-14 canonical slice without claiming whole-population current coverage.

No new architecture decision is required: D-036 already defines field-specific direct-Octo authority,
and D-037 explicitly authorizes later ingestion of `refresh_proven_direct_observation` records while
keeping the other classes distinct.

## 3. Accepted evidence artifacts

The promotion planner combines only already established P6 evidence artifacts anchored to the exact
migration-13 canonical SHA:

1. successful P6-T02 refresh reports under
   `data/generated/validation_logs/P6-T02_refresh_probe_*.json`;
2. the validated P6-T03 durable campaign ledger at
   `data/generated/p6_t03_campaign.json`.

The planner hashes each artifact and records deterministic proof revisions. P6-T03 ledger validation
is reused before its contents are accepted. A P6-T02 report with another canonical baseline is
rejected.

The current cache itself is not allowed to invent freshness. It supplies only the raw bytes against
which an existing refresh proof is matched.

## 4. Deterministic promotion plan

`octogamedb.itemcache_promotion` builds a deterministic ignored plan at:

```text
data/generated/p6_t04_promotion_plan.json
```

The plan records:

- canonical baseline SHA and migration;
- exact current WDB SHA, locale and client version;
- hashed P6-T02/P6-T03 evidence artifacts;
- counts by D-037 freshness class;
- exact eligible item IDs and current raw-record hashes;
- matching proof revisions and proof kinds;
- refresh-proven items excluded because the current cache record is missing or changed;
- unique item counts for the other noneligible classes;
- a deterministic `plan_revision`.

Every eligible item ID must already exist in canonical `items`. A cache-only native ID is a hard
failure for promotion planning rather than authorization to fabricate canonical identity.

## 5. Provenance and selection behavior

P6-T04 reuses `import_octo_itemcache_slice()` and migration 14 rather than creating a parallel item
model.

For every eligible raw record:

- the original `octo-itemcache` observation remains source evidence;
- the deterministic itemcache slice revision remains the source revision;
- `observation_import_batches` keeps repeated observation/import links idempotently;
- the P6-T04 import batch adds the promotion plan revision, exact eligible record hashes and matching
  freshness-proof revisions/kinds to `details_json`;
- known managed P6 selections may be refreshed under the existing
  `p6-item-template/octo-itemcache` policy;
- manual/custom/unknown selection policies are snapshotted before import and must remain byte-for-byte
  equivalent at the selection level afterward;
- competing observations remain stored.

Historical/session-only/unknown evidence is not imported by this promotion cycle, so it cannot be
silently relabelled as fresh or used to replace another selection.

## 6. Shadow validation before canonical mutation

The default command is deliberately non-mutating:

```text
python scripts\validate_p6_t04.py validate
```

It must:

1. verify the exact migration-13 canonical SHA and reject SQLite sidecars;
2. build the freshness-bound plan;
3. copy the canonical DB byte-for-byte to
   `data/generated/p6_t04_validation.sqlite3`;
4. apply exactly migration 14 to that copy;
5. import only eligible records;
6. verify protected selections;
7. rerun the same import and require zero domain inserts/updates and no new source observations;
8. exercise migration-14 query/provenance paths and representative promoted items;
9. require clean `PRAGMA foreign_key_check` and `PRAGMA integrity_check`;
10. verify the canonical migration-13 file stayed byte-identical.

A successful shadow run emits:

```text
P6_T04_SHADOW_VALIDATION_OK
canonical_db_unchanged=true
P6_T04_LOCAL_VALIDATION_READY_FOR_PROMOTION
```

## 7. Guarded D-029 promotion

Only after shadow validation succeeds should the human run:

```text
python scripts\validate_p6_t04.py promote
```

`promote` rebuilds the current plan and repeats shadow validation first. It then:

1. re-verifies migration 13 and the exact accepted SHA;
2. rejects existing canonical SQLite sidecars;
3. acquires an exclusive SQLite lock;
4. creates/replaces `data/generated/octogamedb_bak.sqlite3` as an exact byte copy;
5. verifies the backup SHA equals the accepted migration-13 SHA **before the first canonical write**;
6. applies exactly migration 14 and the same bounded import/reconciliation to the canonical DB;
7. repeats idempotence, protected-selection, query, FK and integrity gates;
8. closes SQLite and verifies no sidecars remain;
9. verifies the canonical file evolved and the backup remained byte-identical.

Successful promotion emits:

```text
P6_T04_CANONICAL_PROMOTION_OK
backup_sha256=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
canonical_migration=14
rollback_available=true
P6_T04_LOCAL_VALIDATION_COMPLETE
```

The new migration-14 canonical SHA is intentionally not predicted or committed in this implementation
delta. It must be copied from the successful real promotion output into `CURRENT_STATE.md` and
`CANONICAL_DB.md` during the P6-T04 closeout.

## 8. Failure and rollback

If a canonical validation gate fails after the verified backup exists, the validator closes its SQLite
connection, removes failed-write sidecars, restores the canonical file from `_bak`, and verifies the
exact migration-13 SHA. It emits:

```text
P6_T04_ROLLBACK_COMPLETE
```

If failure occurs before the verified backup exists, no canonical write is permitted and the validator
re-verifies the original migration-13 baseline.

Do not mark P6-T04 `VALIDATED` after a failed promotion, even if rollback succeeds.

## 9. Full Level-2 closure

Before canonical promotion, run the classical gates against the integrated checkout:

```text
python -m pip install -e ".[dev]"
pytest --basetemp="$env:TEMP\OctoGameDB_pytest"
python -m ruff check src tests scripts\validate_p6_t04.py
python -m compileall -q src tests scripts\validate_p6_t04.py
python scripts\validate_p6_t04.py validate
```

The project baseline was 258 passing tests before P6-T04; this implementation adds eight focused P6-T04 tests, so the expected integrated total is 266 passing tests unless another concurrent
tracked change legitimately changes the suite count.

After reviewing the shadow report, run:

```text
python scripts\validate_p6_t04.py promote
```

Only a successful promotion with all markers above authorizes the final closeout to record migration
14 as the accepted canonical baseline.

## 10. Non-goals retained

P6-T04 still does not:

- import every historical cache record;
- acquire all remaining campaign candidates;
- convert unknown/cache absence into item non-existence;
- add placeholder item identities;
- solve weapon damage/speed/block, item spells/effects/tooltips or unaccepted field families;
- introduce fallback-source authority across unrelated domains;
- claim whole-population freshness or coverage.
