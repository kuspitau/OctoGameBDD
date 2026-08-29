# Current State

This file is the permanent task router. GitHub `main` is the tracked source of truth. Every new coding
conversation must verify the actual current head before editing and must account explicitly for any
validated local delta not yet pushed.

## Integration baseline for this handoff

GitHub `main` head verified for the P6-T01 implementation/validation cycle:

```text
d0f26f13b91dabd68b8403d65811447ab0abccca
Validate P5-T08 replacement semantics and route P6-T01
```

P6-T01 was implemented, corrected and fully validated locally on top of that commit. This closeout
is therefore **intentionally stacked on the complete validated local P6-T01 implementation delta**.
Do not apply this closeout to a bare `d0f26f...` checkout without first applying the P6-T01
implementation/correction delta.

Commit and push the complete P6-T01 implementation plus this closeout together before beginning a new
coding conversation, so the next conversation can again treat GitHub `main` as the complete tracked
source of truth.

## Validated cumulative state

P0 through **P6-T01** are `VALIDATED`.

P6-T01 accepted a bounded direct-Octo item-template/stat source contract and migration-14 schema
capability, but it deliberately did **not** promote the generated canonical DB.

## Canonical DB baseline

The accepted canonical local DB remains:

```text
schema migration = 13 / 0013_recipe_acquisition_sources.sql
SHA-256 = 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

Migration 14 (`0014_item_template_facts.sql`) is validated in code and on a disposable copy, but the
project has not performed a D-029 canonical mutation/promotion cycle for it. `CANONICAL_DB.md` therefore
remains unchanged. Do not describe migration 14 as the current canonical baseline.

## P6-T01 validated result — 2026-08-29

Classical local validation passed:

```text
python -m pip install -e ".[dev]"      passed
pytest --basetemp=...                  228 passed
python -m ruff check src tests         passed
python -m compileall -q src tests      passed
```

The real-client Level-2 validator then resolved the local Octo `itemcache.wdb` through existing project
configuration/derived addon paths and ran only against a dedicated validation DB copied from the
migration-13 canonical baseline.

Successful Level-2 markers and measurements:

```text
P6_T01_LOCAL_VALIDATION_OK
canonical_sha256=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
selected_item_count=25
selected_item_ids=4,8,10,25,16,24,26,27,28,31,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49
first_rows_inserted=28
first_rows_updated=0
item_templates=25
item_stat_modifiers=3
source_observations=2208906
canonical_db_unchanged=true
P6_T01_REMAINING_LOCAL_VALIDATION_COMPLETE
```

The validator also checked rerun idempotence, canonical selections, provenance, foreign keys and
SQLite integrity. The migration-13 canonical SHA remained byte-identical before and after validation.

The final local validation log is an ignored machine-local artifact under:

```text
data/generated/validation_logs/P6-T01_remaining_validation_20260829_003035.log
```

The v3 wrapper buffered the inner validator output until completion, so the run looked stalled while
it was working. That is a validation-helper UX defect, not a semantic failure; future long-running
validators should stream progress instead of capturing all output until the end.

## Accepted P6-T01 contract

Durable source/model contract:

```text
docs/project/P6_ITEM_TEMPLATE_SOURCE_CONTRACT.md
```

Decision:

```text
D-036 — P6 item-template/stat cache evidence is field-specific direct Octo positive evidence
```

Accepted bounded semantics:

- a successfully parsed `itemcache.wdb` record is direct Octo client/server-observed positive evidence
  for the supported item-query fields;
- cache absence is unknown, never negative evidence;
- a pre-existing cache record does not by itself prove freshness/current-server state;
- the ten ordered stat slots of a present record form a complete-set observation for that record;
- direct Octo observations may supersede only known managed P6 selections for the supported field
  family; manual/custom selections remain protected;
- competing observations remain preserved;
- cache-only native IDs do not create fabricated canonical item identities;
- migration 14 provides `item_templates` and `item_stat_modifiers` as rebuildable selected projections;
- the production P6-T01 importer remains explicitly bounded and has no unbounded default.

The real validation proves parser/import/query compatibility with the user's current cache shape. It
does **not** prove whole-cache completeness or freshness. The selected 25-item probe produced only 3
materialized non-empty stat modifiers, reinforcing the need to characterize coverage before broad
promotion.

## Active task

### P6-T02 — direct Octo item-cache freshness, coverage and bounded refresh probe

**Status: `READY_FOR_IMPLEMENTATION`.**

Task contract:

```text
docs/project/tasks/P6-T02.md
```

Primary goal:

> Measure what the current direct Octo item cache actually covers, establish whether/how bounded item
> records can be refreshed or directly queried reproducibly, and define a freshness-aware acquisition
> contract before full item-template/stat ingestion or canonical migration-14 promotion.

P6-T02 should remain read-only with respect to the canonical DB. It should use source/capture artifacts
and disposable validation outputs, not mutate the migration-13 baseline.

Do not begin a whole-cache canonical import merely because P6-T01's parser passed. The next task must
first distinguish parser correctness from source coverage/freshness.

## Next-conversation start

After the complete P6-T01 stack and this closeout are committed/pushed:

1. verify the new GitHub `main` HEAD;
2. read this file and `docs/project/tasks/P6-T02.md`;
3. inspect only the P6-T02 source/client/query paths needed to establish the freshness/coverage probe;
4. keep the canonical DB at migration 13 unless a later validated D-029 promotion explicitly advances
   it.
