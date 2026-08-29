# Current State

This file is the permanent task router. GitHub `main` is the tracked source of truth. Every new coding
conversation must verify the actual current head before editing and must account explicitly for any
validated local delta not yet pushed.

## Integration baseline for this handoff

Visible GitHub `main` while the P6-T02 closeout is prepared:

```text
72cb4e415b611938175addf7e9160872f2ab369b
Validate P6-T01 item template/stat slice and route P6-T02
```

P6-T02 was implemented, corrected and fully validated locally on top of that commit. This closeout is
therefore **intentionally stacked on the complete local P6-T02 implementation/correction state**,
including the clean-WDB support and the final Ruff/path-validation hotfixes. Do not apply this closeout
to a bare `72cb4e...` checkout without first applying the complete P6-T02 implementation stack already
validated on the user's machine.

Commit and push the complete P6-T02 implementation/corrections plus this closeout together before a
new coding conversation, so GitHub `main` again becomes the complete tracked source of truth.

## Validated cumulative state

P0 through **P6-T02** are `VALIDATED`.

P6-T01 established the bounded direct-Octo item-template/stat source and migration-14 projection
capability. P6-T02 established actual cache coverage and a reproducible bounded freshness proof for
cache-missing canonical item IDs.

## Canonical DB baseline

The accepted canonical local DB remains:

```text
schema migration = 13 / 0013_recipe_acquisition_sources.sql
SHA-256 = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

Migration 14 (`0014_item_template_facts.sql`) remains validated schema capability only. P6-T02 was
read-only with respect to the canonical DB and explicitly reverified the exact migration-13 hash after
the real-client probe. No D-029 promotion cycle has occurred.

## P6-T01 accepted contract

Durable source/model contract:

```text
docs/project/P6_ITEM_TEMPLATE_SOURCE_CONTRACT.md
```

Decision:

```text
D-036 — P6 item-template/stat cache evidence is field-specific direct Octo positive evidence
```

Core boundaries remain:

- present supported `itemcache.wdb` records are direct Octo positive evidence for the adopted field
  family;
- cache absence is unknown, never negative evidence;
- cache-only IDs do not fabricate canonical item identities;
- the ten stat slots are complete within a present supported record;
- managed P6 selections preserve manual/custom and competing observations;
- arbitrary pre-existing cache presence does not prove currentness;
- migration 14 remains unpromoted.

## P6-T02 validated result — 2026-08-29

Durable freshness/coverage contract:

```text
docs/project/P6_ITEMCACHE_FRESHNESS_CONTRACT.md
```

Decision:

```text
D-037 — P6 direct item-query freshness is query-scoped and cache coverage remains partial-positive
```

The user first completed the requested classical local gates successfully:

```text
python -m pip install -e ".[dev]"                          passed
pytest --basetemp=<local temp>                             passed
python -m ruff check src tests                            passed
python -m compileall -q src tests                         passed
```

The clean-WDB corrective path then passed its focused regressions:

```text
pytest tests/test_itemcache_coverage.py tests/test_p6_t02_validator.py   10 passed
python -m ruff check <P6-T02 corrective files>                          passed
python -m compileall -q <P6-T02 corrective Python files>                passed
```

Final real-client Level-2 evidence:

```text
P6_T02_PREFLIGHT_OK
canonical_sha256=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
cache_pre_exists=true
cache_records=7119
canonical_items=23336
matching_canonical_cache_records=6667
cache_only_native_ids=452
canonical_missing_unknown=16669
probe_item_ids=1,7646,15984,41360,93116

P6_T02_LOCAL_VALIDATION_OK
canonical_db_unchanged=true
itemcache_post_exists=true
freshness_refresh_proven_direct_observation=3
freshness_unknown=2
P6_T02_REMAINING_LOCAL_VALIDATION_COMPLETE
```

The final local validation log is an ignored machine-local artifact:

```text
data/generated/validation_logs/P6-T02_remaining_local_20260829_193935_323.log
```

Interpretation:

- the real cache is useful but incomplete: 6,667 / 23,336 canonical item identities were represented
  by the observed cache snapshot;
- 452 cache records have native IDs not currently represented by canonical item identity and remain
  source evidence only;
- 16,669 canonical item IDs were missing from that cache snapshot; all remain unknown, not absent;
- the bounded current-session query succeeded with post-WDB raw-record proof for 3 of 5 selected
  cache-missing canonical IDs;
- the other 2 outcomes remain unknown;
- therefore direct current acquisition is proven, but spontaneous whole-cache coverage is insufficient
  to justify an unqualified whole-cache import or migration-14 promotion.

The validated freshness classes are:

```text
refresh_proven_direct_observation
session_observed_freshness_limited
historical_cache_only
unknown
```

Only the first class combines pre-probe cache miss, current-session successful load and post-session
raw WDB record proof. Session-only success is useful acquisition evidence but not a persisted template
payload. Historical cache records remain positive evidence without a currentness claim. Unknown is
never negative evidence.

## Active task

### P6-T03 — resumable direct-Octo acquisition campaign for known canonical cache misses

**Status: `READY_FOR_IMPLEMENTATION`.**

Task contract:

```text
docs/project/tasks/P6-T03.md
```

Primary goal:

> Turn the P6-T02 five-ID proof into a conservative, resumable acquisition workflow over known
> canonical item IDs that are missing from the current cache, while preserving one-outstanding-query
> behavior, bounded batches, per-ID evidence state and the D-037 freshness classes.

P6-T03 remains an acquisition task. It must not brute-force arbitrary native IDs, must not reinterpret
timeouts as absence, and must not promote migration 14 or mutate the canonical migration-13 DB.

The first implementation should focus on a durable ignored acquisition ledger/checkpoint plus a
bounded client batch workflow. It should prove safe resume/retry behavior and measure how much direct
fresh coverage can be acquired without manual per-ID selection.

## Next-conversation start

After the complete P6-T02 stack and this closeout are committed/pushed:

1. verify the new GitHub `main` HEAD;
2. read this file and `docs/project/tasks/P6-T03.md`;
3. inspect the validated P6-T02 addon/validator/coverage code and only the dependencies needed for a
   resumable acquisition campaign;
4. read `LOCAL_PATHS.md` before changing WoW-root handling; use the established ignored local config
   contract instead of hard-coded paths;
5. keep the canonical DB at migration 13 and read-only throughout P6-T03;
6. do not begin migration-14 canonical promotion until a later explicitly routed D-029 cycle.
