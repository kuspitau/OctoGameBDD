# Current State

This file is the permanent task router. GitHub `main` is the tracked source of truth. Every new coding
conversation must verify the actual current head before editing and must account explicitly for any
validated local delta not yet pushed.

## Integration baseline for this handoff

Visible GitHub `main` at the time of this closeout is:

```text
8e4dd342e9ceaec171b00d0ffab49bc47f52101a
Validate P6-T03 direct-Octo acquisition campaign and route P6-T04
```

P6-T04 was implemented and fully validated locally on top of that commit, including the final Windows
D-029 backup/locking corrections. This closeout is intentionally stacked on that complete local
P6-T04 implementation state.

Do not apply this closeout to a bare `8e4dd342...` checkout without first applying the complete local
P6-T04 implementation/hotfix stack already validated on the user's machine. Commit and push the
complete P6-T04 stack plus this closeout together so GitHub `main` again becomes the complete tracked
source of truth.

## Validated cumulative state

P0 through **P6-T04** are `VALIDATED`.

P6-T01 established the bounded direct-Octo item-template/stat source and migration-14 projection
capability. P6-T02 established cache coverage and current-session freshness proof. P6-T03 scaled that
proof mechanism into a deterministic resumable campaign. P6-T04 completed the first D-029 canonical
promotion of strictly eligible current item-template/stat evidence.

## Canonical DB baseline

The accepted canonical local DB is now:

```text
schema migration = 14 / 0014_item_template_facts.sql
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

The immediate D-029 rollback file is the exact previous migration-13 canonical:

```text
data/generated/octogamedb_bak.sqlite3
SHA-256 = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

Both SQLite files remain generated/local and must never be committed or included in `changes.zip`.

## P6-T04 — final validated result — 2026-08-30

Task contract:

```text
docs/project/tasks/P6-T04.md
```

Promotion/source contract implemented by the local P6-T04 stack:

```text
docs/project/P6_ITEM_TEMPLATE_PROMOTION_CONTRACT.md
```

### Accepted promotion policy

Automatic managed selection is restricted to:

```text
refresh_proven_direct_observation
```

and requires an exact raw-record SHA match between the current `itemcache.wdb` record and a persisted
freshness proof.

The following remain ineligible for automatic canonical selection:

```text
session_observed_freshness_limited
historical_cache_only
unknown
```

Cache-only IDs do not create canonical identities. Timeout/missing evidence is never negative item
evidence. Manual/custom or otherwise protected selections remain protected.

### Real evidence used by the accepted promotion

The final plan revision was:

```text
sha256:7852a2cfd54bbd139420d99e0f42f27c05a54c87611dde1174375da3dacbabc2
```

Final evidence-class totals observed by the plan:

```text
historical_cache_only                 =    85
refresh_proven_direct_observation     =    14
unknown                               = 15693
```

A previously used WDB was lost before final promotion. The conservative current-hash rule correctly
excluded eleven historical refresh-proven records whose proven raw records were no longer present with
matching current hashes.

A fresh bounded P6-T02 recovery probe established three new current proofs. The only eligible/promoted
item IDs were:

```text
7886
15784
41278
```

### Real canonical promotion

The accepted real promotion produced:

```text
backup_sha256                         = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
canonical_sha256                      = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
canonical_migration                   = 14
rollback_available                    = true

item_templates_promoted               = 3
item_stat_modifiers_promoted          = 2
protected_selection_count             = 0
foreign_key_check                     = []
integrity_check                       = ok
```

The import source revision was:

```text
sha256:982e7f4cd6ecc075669bdda5c21b4dc7711ef4e1d51806feb8edc721978f9445
```

First import:

```text
rows_read      = 3
rows_accepted  = 3
rows_inserted  = 5
rows_updated   = 0
rows_skipped   = 0
errors         = 0
warnings       = 0
```

Immediate second import proved canonical idempotence:

```text
rows_read      = 3
rows_accepted  = 3
rows_inserted  = 0
rows_updated   = 0
rows_skipped   = 0
errors         = 0
warnings       = 0
```

Representative promoted queries included item 15784 with template facts plus two raw stat modifiers
(`stat_type=6, value=13` and `stat_type=7, value=12`).

### D-029 Windows behavior

The final validated Windows-safe promotion protocol creates and SHA-verifies the exact backup before
the SQLite write lock, checks `PRAGMA data_version` plus file size/mtime around the copy window, rejects
sidecar/drift conditions, then acquires `BEGIN IMMEDIATE` before any canonical mutation.

This replaced the invalid Windows approach that attempted to sequentially raw-read the multi-gigabyte
SQLite file while SQLite byte-range locks were already held.

### Validation

The complete non-destructive Level-2 rehearsal passed on dedicated copies:

```text
shadow migration/import/query/idempotence/integrity = passed
guarded D-029 rehearsal promotion                   = passed
rehearsal migration                                 = 14
rehearsal foreign_key_check                         = []
rehearsal integrity_check                           = ok
real canonical remained migration 13 during rehearsal
```

The subsequent real promotion emitted:

```text
P6_T04_CANONICAL_PROMOTION_OK
P6_T04_LOCAL_VALIDATION_COMPLETE
```

After the final validator/hotfix state, the user also reran the complete requested pytest, Ruff and
compileall gates and reported all of them passing.

## Active task

### P6-T05 — migration-14 item-template coverage expansion and incremental promotion

**Status: `READY_FOR_IMPLEMENTATION`.**

Task contract:

```text
docs/project/tasks/P6-T05.md
```

Rationale: P6-T04 proves the canonical migration-14 path, but only three current item-template records
are promoted. P7's arbitrary stat/item exploration would therefore have misleadingly sparse real-data
coverage if started now.

P6-T05 should adapt the acquisition/promotion workflow to the new accepted migration-14 baseline,
perform one bounded additional current-session acquisition tranche over known canonical IDs, and
support one safe incremental D-029 promotion without reapplying migration 14.

After P6-T05 validation, reassess measured template/stat coverage before routing to P7-T01.
