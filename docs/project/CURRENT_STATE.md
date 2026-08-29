# Current State

This file is the permanent task router. GitHub `main` is the tracked source of truth. Every new coding
conversation must verify the actual current head before editing and must account explicitly for any
validated local delta not yet pushed.

## Integration baseline for this handoff

Visible GitHub `main` remains:

```text
8724019c53b89d6384fcb4bdec1bc5d7684a9b01
Validate P6-T02 item-cache freshness and route P6-T03
```

P6-T03 was implemented and fully validated locally on top of that commit through the complete local
P6-T03 delta stack, including the resume-wrapper and validation-state hotfixes. This final closeout is
therefore intentionally stacked on that complete local P6-T03 state.

Do not apply this closeout to a bare `8724019c...` checkout without first applying the complete P6-T03
implementation/hotfix stack already validated on the user's machine. Commit and push the complete
P6-T03 stack plus this closeout together before starting a new coding conversation, so GitHub `main`
again becomes the complete tracked source of truth.

## Validated cumulative state

P0 through **P6-T03** are `VALIDATED`.

P6-T01 established the bounded direct-Octo item-template/stat source and migration-14 projection
capability. P6-T02 established actual cache coverage and a reproducible bounded current-session
freshness proof. P6-T03 scaled that mechanism into a deterministic, resumable, interruption-safe
campaign over canonical cache misses.

## Canonical DB baseline

The accepted canonical local DB remains:

```text
schema migration = 13 / 0013_recipe_acquisition_sources.sql
SHA-256 = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

Migration 14 (`0014_item_template_facts.sql`) remains validated schema capability only. P6-T03 was
strictly read-only with respect to the canonical DB and repeatedly reverified the exact migration-13
SHA. No D-029 promotion cycle has occurred yet.

## P6-T03 — final validated result — 2026-08-29

Task contract:

```text
docs/project/tasks/P6-T03.md
```

Freshness decision retained unchanged:

```text
D-037 — P6 direct item-query freshness is query-scoped and cache coverage remains partial-positive
```

### Implemented campaign behavior

P6-T03 provides:

- canonical-ID-only candidate discovery from the validated cache-coverage difference;
- durable ignored JSON ledger with atomic checkpoint replacement;
- deterministic candidate/campaign/session revisions;
- bounded batches (default 10, hard maximum 20);
- one outstanding client query at a time through the validated P6-T02 addon path;
- explicit `queued`, `in_flight`, freshness-positive, historical, retryable-unknown and deferred states;
- bounded campaign retries without converting timeout/missing into negative evidence;
- deterministic next-batch selection with retry reservation;
- conservative pre-session reclassification to `historical_cache_only` when a candidate becomes cached
  before a later campaign session;
- interruption-safe merge/recovery behavior;
- duplicate/no-op detection for re-imported completed sessions;
- canonical SHA verification before/after processing;
- a resume-aware Windows entry point that preserves a durable `in_flight` batch across CMD restarts.

No WDB deletion/rotation, arbitrary numeric scan, migration-14 promotion or canonical DB mutation is
part of P6-T03.

### Classical validation

Final user-side gates after all P6-T03 hotfixes:

```text
pytest --basetemp="$env:TEMP\OctoGameDB_pytest"
258 passed

python -m ruff check src tests scripts\validate_p6_t03.py scripts\validate_p6_t03_resume.py
passed with no findings

python -m compileall -q src tests scripts\validate_p6_t03.py scripts\validate_p6_t03_resume.py
exit 0
```

The external `%TEMP%` pytest basetemp is the validated Windows test command for this machine. An
in-repository basetemp can make tiny P4 fixtures inherit the parent Git worktree; plain pytest also
encountered local temp-permission failures on this machine.

### Real-client validation

The first real campaign session occurred during OctoWoW DDoS/disconnection instability. It proved the
conservative failure path:

```text
attempted unique IDs              = 10
refresh_proven                    = 0
unknown_retryable                 = 10
newly materialized WDB records    = 6
canonical DB unchanged            = true
```

The interrupted CMD left the durable batch `in_flight`; manual post-validation successfully merged the
existing SavedVariables, and immediate replay produced `duplicate_noop=true`. This proved ledger
survival, interruption recovery semantics and idempotent evidence merge without inventing freshness.

A later stable automatic Level-2 run completed the full normal workflow and produced the missing
positive acquisition proof. Final cumulative campaign report:

```text
initial canonical population             = 23336
initial matching cache coverage          =  7554
current matching cache coverage          =  7654
campaign candidate count                 = 15782
attempted unique IDs                     =    19
campaign sessions                        =     2
campaign retries                         =     1
historical_cache_only                    =    85
refresh_proven_direct_observation        =     8
unknown_retryable                        =     5
queued                                   = 15684
newly materialized WDB records           =    93
refresh-proven rate over attempted IDs   = 42.105263%
duplicate/no-op session imports          =     2
canonical DB unchanged                   = true
```

Representative refresh-proven IDs include:

```text
3991, 11311, 20397, 41427, 60818
```

The normal validation flow also proved:

```text
P6_T03_PREFLIGHT_OK
P6_T03_LOCAL_VALIDATION_OK
first completed-session merge: duplicate_noop=false
immediate replay: duplicate_noop=true
P6_T03_REMAINING_LOCAL_VALIDATION_COMPLETE
```

The next-batch preview remained identical across the duplicate replay, proving that replay did not
mutate per-ID eligibility/evidence.

### Interpretation

P6-T03 now has real end-to-end positive and conservative-negative-path evidence:

- direct current acquisition works for automatically selected canonical cache misses;
- D-037 freshness is actually proven for eight campaign items;
- cache/timeout uncertainty remains unknown rather than being interpreted as item absence;
- pre-existing/newly pre-cached records remain positive historical evidence without false freshness;
- session replay is an evidence-preserving no-op;
- interrupted campaign state survives and can be recovered without selecting a replacement batch;
- the migration-13 canonical DB remains byte-identical.

One non-blocking residual coverage gap is explicitly accepted: after the resume-wrapper hotfix, the
wrapper's dedicated automatic `in_flight` restart branch was not deliberately replayed end-to-end a
second time. Its logic is covered by focused tests, and the underlying real interruption/recovery path
was already exercised successfully before the wrapper was added. This does not block P6-T03
validation.

## Active task

### P6-T04 — bounded migration-14 canonical promotion of validated item-template/stat evidence

**Status: `READY_FOR_IMPLEMENTATION`.**

Task contract:

```text
docs/project/tasks/P6-T04.md
```

P6-T04 should convert the already validated migration-14 capability into the first explicit D-029
canonical promotion cycle for the bounded P6 item-template/stat fact family. It must not treat the
P6-T03 campaign as proof of whole-population coverage and must preserve D-036/D-037 provenance and
freshness distinctions.

The canonical DB must remain migration 13 until P6-T04 itself completes its backup, migration/import,
validation and promotion protocol successfully.
