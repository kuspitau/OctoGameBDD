# Current State

This file is the permanent task router. GitHub `main` is the tracked source of truth. Every new coding
conversation must verify the actual current head before editing and account explicitly for any local
validated delta not yet pushed.

## Integration baseline for this handoff

GitHub `main` remained at the P6-T04 closeout while P6-T05 was implemented and validated locally:

```text
ae1ce41e7c155a2f1327157c2b132682cb1d09ae
Validate P6-T04 migration-14 canonical promotion and route P6-T05
```

This closeout is therefore stacked on the complete local P6-T05 implementation/hotfix/validation
state. It must not be applied to a bare `ae1ce41e...` checkout without that stack.

## Validated cumulative state

P0 through **P6-T05** are `VALIDATED`.

P6-T01 established direct-Octo item-template/stat semantics and migration-14 projection capability.
P6-T02 established cache coverage/current-session freshness proof. P6-T03 established durable bounded
acquisition. P6-T04 completed the first guarded migration-14 promotion. P6-T05 proved bounded
migration-14 -> migration-14 incremental acquisition/promotion without weakening D-036/D-037.

## Current accepted canonical DB

```text
schema migration = 14 / 0014_item_template_facts.sql
SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Immediate D-029 rollback is now the exact pre-P6-T05 migration-14 canonical:

```text
data/generated/octogamedb_bak.sqlite3
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

The previous migration-13 baseline `623e29d8...a7613d7` remains historical P6-T04 input evidence, not
the current rollback file.

SQLite DB files remain local/generated and must never enter Git or `changes.zip`.

## P6-T05 validated closure — 2026-08-30

The successful v5 run used two bounded real-client sessions and reached the required threshold before
the 100-new-ID ceiling:

```text
attempted_unique = 19
refresh_proven = 15
retryable = 3
remaining_new_unique_capacity = 81
```

The final deterministic promotion plan recorded:

```text
plan_revision = sha256:685f02faa83af9d0c7c7135e244e55702ec867c76670dc8b71bf2ce4ca59b952
canonical_items = 23336
cache_records = 6400
cache_records_with_canonical_identity = 5995
canonical_cache_coverage_ratio = 0.25689921
canonical_item_ids_missing_from_cache_unknown = 17341
cache_only_native_ids = 405
eligible_item_count = 15
already_current_noop_count = 3
```

Shadow validation passed with the real canonical byte-identical. The guarded real promotion then
succeeded, replaced D-029 with the exact pre-promotion migration-14 bytes, kept migration 14, and left
rollback available. The complete validation runner finished with exit code 0.

Measured canonical promotion:

```text
item_templates_promoted = 15
item_templates_new_rows = 15
item_stat_modifiers_promoted = 12
item_stat_modifiers_net_new_rows = 12
source_observations_added_first_pass = 330
protected_selection_count = 0
first_import rows_inserted / rows_updated = 27 / 0
second_import rows_inserted / rows_updated = 0 / 0
foreign_key_check = []
integrity_check = ok
```

The authoritative retained local report is:

```text
data/generated/validation_logs/P6-T05_promote_20260830T173826Z.json
```

Active migration-14 acquisition/promotion tooling now defaults to
`ACCEPTED_CANONICAL_BASELINE` (`60ae...`) and separate current generated artifacts
(`p6_itemcache_*`). Historical P6-T05 replay is explicit with `--baseline p6-t05-input`, preserving
`P6_T05_INPUT_BASELINE` (`d57e...`) without making it current again. The original
`scripts/validate_p6_t03.py` remains historical migration-13 tooling and is reused only through the
migration-14 adapter.

Read-only current baseline verification:

```powershell
python scripts\validate_p6_t05.py verify-baseline
```

Expected: SHA `60ae...`, migration `14`, `foreign_key_check=[]`, `integrity_check=ok`.

## Evidence semantics retained

Automatic selection remains limited to `refresh_proven_direct_observation` with an exact current
raw-record hash match. `historical_cache_only`, `session_observed_freshness_limited` and `unknown`
remain ineligible. Cache-only IDs cannot fabricate canonical identity and manual/custom/protected
selections remain protected.

The Windows-safe D-029 protocol remains copy-before-lock: verify baseline and sidecars, copy and
SHA-verify the backup, detect drift around the copy window, acquire `BEGIN IMMEDIATE`, mutate only the
validated slice, then run idempotence/domain/FK/integrity checks and restore on failure.

## Active task

### P7-T01 — provenance-aware item query/filter contract

**Status: `READY_FOR_IMPLEMENTATION`.**

Task contract:

```text
docs/project/tasks/P7-T01.md
```

P7-T01 starts the query/exploration layer over the validated migration-14 item-template/stat surface.
It must explicitly expose incomplete coverage rather than treating the current slice as exhaustive.
No new canonical mutation, schema migration, or source-authority rule belongs in P7-T01.

## Routing

Implement **P7-T01** next. Further P6 acquisition remains consumer-driven and may be added later when
P7 reveals a concrete coverage or field-family requirement.
