# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth; every new
coding conversation must still verify the actual current head before editing.

## Recently completed

### P2-T04 — pfQuest-turtle effective item/acquisition reconciliation

**Status: VALIDATED**

P2-T04 was implemented and validated from GitHub `main` base commit
`9991e60732e30f746ef5f6f95272fc349a0b7ac3` (`Validate P2-T03 vendor acquisition`). The human
Level-2/full-data battery was reported successful on 2026-08-24.

Uploaded reconciliation evidence for the configured local pfQuest/pfQuest-turtle inputs:

- Turtle item source revision:
  `sha256:a3d484195f5eb56dbfc0d12a289e5b37bfbce2582899437c702c40704902ae47`;
- first reconciliation:
  - `status = succeeded`, `error_count = 0`;
  - `rows_read = rows_accepted = 11,599`, `rows_skipped = 0`;
  - `rows_inserted = 148,477`, `rows_updated = 3,980`;
  - `canonical_relations_or_identities_deleted = 2,594`;
  - `relation_only_templates_inserted = 2,143`, `relation_only_templates_updated = 1`;
- second same-revision reconciliation:
  - `status = succeeded`, `error_count = 0`;
  - `rows_inserted = 0`, `rows_updated = 0`;
  - `canonical_relations_or_identities_deleted = 0`;
  - `relation_only_templates_inserted = 0`, `relation_only_templates_updated = 0`;
- warning set is stable across both passes: `163` warnings total:
  - `98` unresolved acquisition targets (`97` involving creature `62229`, `1` involving creature
    `92301`);
  - `65` unresolved reference-loot diagnostics (`55` missing refloot definitions, `10` missing source
    identities);
- dangling acquisition/source IDs remain explicit provenance/diagnostics and are not fabricated into
  canonical creature/game-object identities.

The human also reported that the complete prescribed test battery passed, including the repository
test suite, Ruff, Python compilation and foreign-key validation.

## Active task

### P3-T01 — first quest identity/endpoints vertical slice

**Status: READY**

Goal: establish the first bounded quest-domain vertical slice on top of the validated P0-P2 and P1
world foundations.

The next coding conversation must begin by reading `docs/project/tasks/P3-T01.md`, then inspect the
actual pfQuest quest schema and relevant upstream behavior before committing to field semantics.

Initial bounded intent:

- canonical quest identity;
- explicit quest giver and finisher relations where the source supports them;
- creature/game-object endpoint identities linked to existing P1 world templates;
- quest geography derived through P1 spawns/zones/maps rather than duplicated as primary truth;
- native IDs, provenance, conflicts and same-revision idempotence preserved.

Prerequisites/follow-ups, objectives, required items and rewards remain later P3 work unless primary
source inspection proves that a smaller coherent first slice requires part of them.

## Routing guard

Do not skip directly to broad quest ingestion, item stats/effects, economics, P6 scaling or UI work.
P3-T01 should remain a small source-shaped vertical slice with deterministic fixtures and explicit
provenance, following the same expansion discipline used in P1 and P2.
