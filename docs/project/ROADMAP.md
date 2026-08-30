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

Status: `IN_PROGRESS`; validated through P7-T04. P7-T05 is `READY_FOR_IMPLEMENTATION`.

P7 builds richer provenance-aware cross-domain exploration:

- item acquisition/source exploration;
- arbitrary item stat filtering/sorting and later weighted scores;
- quest chains/objectives/rewards;
- creature/gameobject geography;
- recipe/reagent/acquisition traversal;
- configurable columns, saved searches and comparisons.

The query layer must expose partial/unknown coverage explicitly rather than presenting absent
projections as negative game facts.

### P7-T01 — provenance-aware item query/filter contract

Status: `VALIDATED`.

Delivered the first stable item identity/template/stat consumer contract over migration 14:

- canonical item identity/name universe;
- P6 scalar/stat filters;
- deterministic sort/limit;
- explicit `known_match` / `known_non_match` / `unknown` evaluation;
- materialized vs unknown template/stat coverage;
- selected `template.*` provenance trace;
- deterministic JSON-friendly library output;
- read-only `python -m octogamedb.item_query_cli` surface;
- read-only real-canonical validation with byte-level SHA preservation.

Human Level 2 completed on 2026-08-30. The accepted canonical remained byte-identical and the final
marker was:

```text
P7_T01_LOCAL_VALIDATION_OK
```

Contract:

```text
docs/project/P7_ITEM_QUERY_CONTRACT.md
```

### P7-T02 — provenance-aware item acquisition/source exploration

Status: `VALIDATED`.

Implemented the composition of P7-T01 item predicates with the validated P2 direct/reference/vendor
acquisition graph and P1 derived geography. The bounded surface exposes/filters known acquisition path
kind, source-template kind, path-level drop chance, derived zone/map context and primitive provenance.
Unlocated or absent known paths remain conservative `unknown`; vendor metadata is not interpreted as
drop chance.

Human Level 2 completed on 2026-08-30 and preserved the accepted canonical SHA byte-identically.

Contract:

```text
docs/project/P7_ITEM_ACQUISITION_QUERY_CONTRACT.md
```

Task/closeout:

```text
docs/project/tasks/P7-T02.md
```

### P7-T03 — provenance-aware quest exploration and progression/geography query

Status: `VALIDATED`.

Delivered a stable bounded read-only quest search/exploration surface over the validated P3 domain. It
keeps giver, finisher and objective geography role-specific; preserves unresolved/unlocated evidence;
retains `any_of` prerequisite semantics and derived follow-ups; isolates close sets from progression;
and exposes P3-T05 required/provided/guaranteed/choice item facts without reinterpretation.

Traversal is deterministic, bounded and cycle-safe. Breadth-first depth is explicitly derived edge
distance rather than a canonical chain-step number. No migration, source-selection rule, persisted
`quest -> zone` truth, dungeon classifier, route planner or graphical UI was introduced.

Human repository gates and accepted-canonical Level 2 completed on 2026-08-30. The validator observed
6,498 canonical quest identities, representative giver/finisher/objective/progression/item/Turtle and
unlocated-endpoint cases, FK/integrity success and byte-identical preservation of the accepted
canonical SHA. Final marker:

```text
P7_T03_LOCAL_VALIDATION_OK
```

Contract:

```text
docs/project/P7_QUEST_QUERY_CONTRACT.md
```

Task/closeout:

```text
docs/project/tasks/P7-T03.md
```

### P7-T04 — provenance-aware recipe/reagent/acquisition exploration

Status: `VALIDATED`.

P7-T04 composes the validated P4 recipe identity/skill-line/output/reagent/learning-source domain with
P7-T02 item acquisition, P1 world geography and P7-T03 quest exploration. The bounded consumer surface
provides recipe/skill/output/reagent filtering, exact reagent quantities, separate teaching-item /
direct-or-template-trainer / quest-reward-spell learning paths, selected provenance and conservative
derived geography/acquisition semantics.

Human repository gates and accepted-canonical Level 2 completed on 2026-08-31. Observed closure:

```text
336 passed in 13.90s
All checks passed!
P7_T04_LOCAL_VALIDATION_OK
recipe_identities=1739
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

No migration, source ingestion, source-priority rule, probability combination or simplified primary
`recipe -> vendor/loot/zone` relation was introduced.

Contract:

```text
docs/project/P7_RECIPE_QUERY_CONTRACT.md
```

Task/closeout:

```text
docs/project/tasks/P7-T04.md
```

### P7-T05 — provenance-aware creature/gameobject exploration and role/geography query

Status: `READY_FOR_IMPLEMENTATION`.

Build the missing bounded first-class creature/gameobject consumer surface. Compose P1 template/spawn
geography with already-validated relations from P2/P3/P4 while preserving the distinction between
template identity, spawn evidence and semantic roles. The first task should support practical entity
search plus inspection/filtering of known spawn geography and relevant loot/vendor/trainer/quest
relations without materializing a simplified universal `entity -> zone` truth.

Task contract:

```text
docs/project/tasks/P7-T05.md
```

P7-T05 must start only after the validated P7-T04 closeout is committed/pushed and the new GitHub
`main` is resolved.

### Later P7 tasks

After P7-T05, later bounded tasks may add zone/dungeon views, richer item field families, weighted
scoring, saved queries/comparisons, dungeon/zone quest views built on P7-T03, ownership/inventory integration,
craft economics, recursive BOM analysis and other consumer capabilities as concrete needs emerge.
Coverage gaps should drive explicit P6 work rather than silent fallback logic.

## P8 — UI/application workflow

Status: `PLANNED`.

Add the user-facing local/browser UI after the query/data semantics and required real-data coverage are
reliable.
