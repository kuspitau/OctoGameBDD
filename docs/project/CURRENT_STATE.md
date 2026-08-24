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

**Status: IMPLEMENTED_AWAITING_LOCAL_VALIDATION**

P3-T01 is implemented against GitHub `main` base commit
`a515ac68b80e3ebba9f600beeccddd760e160e27` and now requires Level-2 validation against the
configured full local pfQuest source and the validated P1/P2 database foundation before it can be
marked `VALIDATED`.

Implemented bounded scope:

- migration 7 adds canonical `quests` plus explicit creature/game-object giver/finisher endpoint
  tables;
- base pfQuest quest identity is read from `db/quests.lua` plus `db/enUS/quests.lua` field `T`;
- `start.U` / `start.O` are creature/game-object giver endpoints and `end.U` / `end.O` are
  creature/game-object finisher endpoints;
- item-started quests (`start.I`) and all prerequisites/objectives/rewards remain deferred rather than
  being coerced into endpoint semantics;
- quest names and each endpoint relation retain pfQuest provenance and preserve existing explicit
  canonical selections;
- endpoints whose P1 target identity is absent remain explicit provenance/diagnostics and are not
  fabricated into canonical templates;
- `quest_by_id()` derives endpoint geography from P1 template -> spawn -> zone/map relations and does
  not store `quest -> zone` primary truth;
- deterministic quest revisions hash exactly `db/quests.lua` and `db/enUS/quests.lua`;
- Turtle quest overlays were inspected and are known to affect quest data/localization, but effective
  Turtle quest reconciliation is deliberately deferred instead of silently generalizing P2 D-027.

Agent Level-1 focused validation: `15 passed`; Python compilation succeeds. Ruff was unavailable in
the agent runtime and remains required in Level 2.

## Routing guard

Do not advance P3-T01 to `VALIDATED` or route to the next P3 task until the prescribed full local
validation succeeds. After successful validation, record the observed counts/revision/idempotence,
foreign-key result and at least one located real quest endpoint with traceable provenance, then route
the next bounded P3 task.
