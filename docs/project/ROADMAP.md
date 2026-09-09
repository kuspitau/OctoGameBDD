# Roadmap

The roadmap is staged to keep source semantics, provenance and canonical selection auditable before
large-scale ingestion or UI work.

## P0 — foundation and provenance

Status: `VALIDATED`.

Delivered project/package skeleton, migration/versioning, provenance primitives, source observations,
canonical selections and audit/query primitives.

## P1 — world foundation

Status: `VALIDATED` through P1-T04.

Delivered maps/zones, creature/gameobject identities and separate spawns, direct Octo DBC geography,
pfQuest base world import, Turtle/Octo overlay composition, complete-set spawn evidence and managed
effective-view reconciliation.

## P2 — items and acquisition sources

Status: `VALIDATED` through P2-T04.

Delivered item identity plus direct/reference loot and vendor relations with bounded Turtle
effective-view reconciliation.

## P3 — quests

Status: `VALIDATED` through P3-T05.

Delivered quest identity/endpoints, restrictions/progression, structured objectives, item
requirements/rewards and conservative Octo/Turtle source-specific evidence.

## P4 — spells, recipes, reagents and acquisition

Status: `VALIDATED` through P4-T04.

Delivered recipe/spell identity, outputs, reagents and teaching-item/trainer/quest-reward-spell
learning sources while keeping acquisition wrappers and derived availability distinct.

## P5 — coverage, provenance and conflict auditing

Status: `VALIDATED` through P5-T08.

The bounded world-source conflict audit established that pfQuest/Turtle/Octo spawn disagreement is
predominantly source-specific complete spawn-membership divergence. No global merge/source-promotion
rule was justified; D-025/D-026 remain unchanged.

## P6 — broader source ingestion and remaining domains

Status: `VALIDATED` through P6-T05.

Current accepted canonical DB:

```text
migration 14 / 0014_item_template_facts.sql
SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Immediate D-029 rollback is the exact pre-P6-T05 migration-14 canonical:

```text
d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

### P6-T01 — item template/stat source contract and bounded ingestion slice

Status: `VALIDATED`.

Accepted D-036's bounded direct-Octo `itemcache.wdb` evidence contract for the supported item-template
and ten-slot stat family. Migration 14 provided the validated projection capability.

### P6-T02 — direct Octo item-cache freshness, coverage and bounded refresh probe

Status: `VALIDATED`.

Measured partial cache coverage and established D-037's freshness-aware direct query path.

### P6-T03 — resumable direct-Octo acquisition campaign

Status: `VALIDATED`.

Scaled P6-T02 into a durable, deterministic, interruption-safe bounded campaign over known canonical
cache misses with conservative retry/unknown semantics and duplicate/no-op replay handling.

### P6-T04 — bounded migration-14 canonical promotion

Status: `VALIDATED`.

Completed the first explicit D-029 promotion cycle for migration 14. Automatic selection was limited
to `refresh_proven_direct_observation` evidence with exact current raw-record hash match.

### P6-T05 — migration-14 coverage expansion and incremental promotion

Status: `VALIDATED`.

Validated the reusable migration-14 -> migration-14 acquisition/promotion workflow without schema
reapplication or freshness weakening. The accepted canonical contains 23,336 item identities, 18
materialized item templates and 14 materialized non-empty stat modifiers while remaining explicitly
partial in template/stat coverage.

Later P6 ingestion remains consumer-driven; another acquisition tranche is not automatic.

## P7 — query/exploration layer

Status: `VALIDATED` through P7-T07. Later P7 feature tasks are consumer-driven and deferred until a
concrete need emerges.

P7 builds provenance-aware cross-domain exploration while exposing partial/unknown coverage instead of
presenting absent projections as negative game facts.

### P7-T01 — provenance-aware item query/filter contract

Status: `VALIDATED`.

Delivered stable item identity/template/stat predicates with explicit three-state evaluation,
provenance, deterministic sorting and bounded results.

Contract: `docs/project/P7_ITEM_QUERY_CONTRACT.md`.

### P7-T02 — provenance-aware item acquisition/source exploration

Status: `VALIDATED`.

Composes P7-T01 item predicates with validated P2 direct/reference/vendor acquisition and P1 derived
geography while keeping path semantics and unknown coverage independent.

Contract: `docs/project/P7_ITEM_ACQUISITION_QUERY_CONTRACT.md`.

### P7-T03 — provenance-aware quest exploration and progression/geography query

Status: `VALIDATED`.

Keeps giver, finisher and objective geography role-specific; preserves unresolved evidence and
prerequisite/close-set semantics.

Contract: `docs/project/P7_QUEST_QUERY_CONTRACT.md`.

### P7-T04 — provenance-aware recipe/reagent/acquisition exploration

Status: `VALIDATED`.

Composes P4 recipe semantics with item acquisition, trainer geography and quest exploration while
keeping teaching-item, trainer and quest-learning paths separate.

Contract: `docs/project/P7_RECIPE_QUERY_CONTRACT.md`.

### P7-T05 — provenance-aware creature/gameobject exploration and role/geography query

Status: `VALIDATED`.

Keeps template/spawn identity separate and composes item/vendor, quest-role/objective and trainer
evidence while preserving D-026 complete-set semantics.

Contract: `docs/project/P7_WORLD_ENTITY_QUERY_CONTRACT.md`.

### P7-T06 — provenance-aware zone-centric exploration

Status: `VALIDATED`.

Delivers canonical zone/map search and positive-evidence zone detail over world entities, item
acquisition, independent quest roles, vendors/trainers and compact recipe-learning evidence.

Contract: `docs/project/P7_ZONE_QUERY_CONTRACT.md`.

### P7-T07 — profile and optimize zone-centric query latency

Status: `VALIDATED` on 2026-09-03.

Removed the dominant retained-entity quest-relation N+1 with request-local batching and no persistent
cache/schema change. Representative cold zone detail is `5.45-7.84 s`; no-recipe median improves
`4.37x` and recipe-sample median improves `3.57x`.

Task: `docs/project/tasks/P7-T07.md`.

### Later P7 tasks

Later bounded tasks may add dungeon/instance views, richer item field families, weighted scoring,
saved queries/comparisons, ownership/inventory integration, craft economics, recursive BOM analysis
and other consumer capabilities as concrete needs emerge. Coverage gaps should drive explicit P6 work
rather than silent fallback logic.

## P8 — UI/application workflow

Status: `IN_PROGRESS`; P8-T01 and P8-T02 are `VALIDATED`; P8-T03 is
`READY_FOR_IMPLEMENTATION`.

P8 is a thin user-facing consumer of the validated P7 query layer. It must not create parallel
canonical SQL truth or hide unknown/truncated evidence.

### P8-T01 — local/browser UI foundation and zone explorer vertical slice

Status: `VALIDATED` on 2026-09-09.

Selected NiceGUI 3.x under D-038 and delivered the read-only zone explorer foundation with stable
startup paths, P7-owned zone query semantics, list/detail views, explicit coverage guards,
`run.io_bound()` for slow reads and strict `mode=ro` / `query_only=ON` SQLite access.

The canonical DB remained exactly:

```text
60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Task: `docs/project/tasks/P8-T01.md`.

### P8-T02 — zone explorer interaction polish

Status: `VALIDATED` on 2026-09-09.

Validated interaction improvements:

- Enter submits all zone/map search fields through one shared search action;
- sort/direction and inclusion-state controls apply automatically;
- table-native Open navigation replaces the separate link wall;
- stable markers make NiceGUI simulation deterministic;
- detail loading/coverage feedback remains explicit.

Validation closure:

```text
pytest: all 367 tests pass
Ruff: All checks passed!
compileall: passed
browser acceptance: passed
canonical DB before/after equality: True
canonical SHA-256: 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

No P7 contract, migration, canonical write, cache or new architecture decision was introduced.

Task: `docs/project/tasks/P8-T02.md`.

### P8-T03 — item explorer vertical slice

Status: `READY_FOR_IMPLEMENTATION`.

Expose the validated P7-T01/P7-T02 item and acquisition query contracts through the existing NiceGUI
application. The first slice should provide a bounded item search/list/detail workflow with explicit
partial-template/unknown semantics and direct/reference/vendor acquisition geography while retaining
strict read-only access.

Do not broaden P8-T03 into saved searches, weighted scores, item comparisons, tooltip/icon work,
inventory ownership, crafting economics, new P6 acquisition, schema changes or canonical writes.

Task: `docs/project/tasks/P8-T03.md`.

### Later P8 tasks

After P8-T03, route later graphical capabilities from observed consumer needs. Quest, world-entity,
recipe, dungeon/instance, maps/spawn overlays, saved searches/comparisons, ownership/inventory and
craft-economics UX remain separate bounded tasks unless explicitly routed.
