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

Status: `IN_PROGRESS`; locally validated through P7-T05. P7-T06 is routed after integration.

P7 builds richer provenance-aware cross-domain exploration:

- item acquisition/source exploration;
- arbitrary item stat filtering/sorting and later weighted scores;
- quest chains/objectives/rewards;
- creature/gameobject geography and semantic roles;
- recipe/reagent/acquisition traversal;
- configurable columns, saved searches and comparisons.

The query layer must expose partial/unknown coverage explicitly rather than presenting absent
projections as negative game facts.

### P7-T01 — provenance-aware item query/filter contract

Status: `VALIDATED`.

Delivered the first stable item identity/template/stat consumer contract over migration 14 with
explicit three-state evaluation, selected provenance, deterministic bounded output and strict
read-only validation.

Contract:

```text
docs/project/P7_ITEM_QUERY_CONTRACT.md
```

### P7-T02 — provenance-aware item acquisition/source exploration

Status: `VALIDATED`.

Composes P7-T01 item predicates with validated P2 direct/reference/vendor acquisition and P1 derived
geography. Path-level chance and vendor metadata remain distinct; absent known acquisition geography
remains conservative `unknown`.

Contract:

```text
docs/project/P7_ITEM_ACQUISITION_QUERY_CONTRACT.md
```

### P7-T03 — provenance-aware quest exploration and progression/geography query

Status: `VALIDATED`.

Delivered bounded quest search/exploration while keeping giver, finisher and objective geography
role-specific; preserving unresolved/unlocated evidence; retaining `any_of` prerequisite semantics;
and keeping close sets distinct from progression.

Human Level 2 completed with `P7_T03_LOCAL_VALIDATION_OK` and byte-identical preservation of the
accepted canonical SHA.

Contract:

```text
docs/project/P7_QUEST_QUERY_CONTRACT.md
```

### P7-T04 — provenance-aware recipe/reagent/acquisition exploration

Status: `VALIDATED`.

Composes P4 recipe identity/skill/output/reagent/learning-source semantics with P7-T02 item
acquisition, P1 trainer geography and P7-T03 quest exploration. Teaching-item, direct/template trainer
and quest-reward-spell paths remain separate and no simplified primary recipe availability relation
was introduced.

Human repository and accepted-canonical Level 2 completed on 2026-08-31:

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

Contract:

```text
docs/project/P7_RECIPE_QUERY_CONTRACT.md
```

### P7-T05 — provenance-aware creature/gameobject exploration and role/geography query

Status: `VALIDATED` locally on 2026-08-31; commit/push pending this closeout.

Implementation base:

```text
e7a25cc84df122bf2f3675a0acba262c99c8e43f
```

P7-T05 adds the first bounded first-class creature/gameobject consumer surface while keeping template
identity, spawn instances and semantic roles separate. It composes P1 world geography, P2
direct/reference/vendor acquisition, P3 quest roles/objectives and P4 trainer evidence without
materializing a universal `entity -> zone` truth.

The real-data Level-2 run exposed a selected D-026 `spawn_set` containing duplicate source membership
for one canonical `spawn_key`. The final contract preserves the raw multiplicity as diagnostics while
comparing complete-set membership by distinct canonical spawn identity. This does not alter D-026 or
source priority.

Human closure:

```text
346 passed in 14.51s
All checks passed!
P7_T05_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
creature_identities=13842
gameobject_identities=20967
duplicate_spawn_set_sample_id=1852
duplicate_spawn_set_member_count=1
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

Contract/task:

```text
docs/project/P7_WORLD_ENTITY_QUERY_CONTRACT.md
docs/project/tasks/P7-T05.md
```

### P7-T06 — provenance-aware zone-centric exploration

Status: `READY_FOR_IMPLEMENTATION` after the validated P7-T05 tree is committed/pushed and GitHub
`main` is freshly resolved.

Build the missing first-class zone consumer surface over existing validated contracts. The bounded
first slice should search canonical zones/maps and compose concrete known geography for world
entities, quest roles, item acquisition paths and recipe-learning sources while retaining each role
and source path independently. Missing/unresolved geography remains explicit `unknown`; do not persist
a simplified universal `zone -> everything` or `entity -> zone` truth.

General dungeon classification, instance grouping and dungeon-specific quest-chain UX are explicitly
deferred from this first zone slice. P7-T06 establishes the zone-centered substrate they can later
consume.

Task:

```text
docs/project/tasks/P7-T06.md
```

### Later P7 tasks

Do not start P7-T06 until the validated P7-T05 tree and this closeout are committed/pushed and GitHub
`main` is re-resolved. After P7-T06, later bounded tasks may add dungeon/instance views, richer item
field families, weighted scoring, saved queries/comparisons, ownership/inventory integration, craft
economics, recursive BOM analysis and other consumer capabilities as concrete needs emerge. Coverage
gaps should drive explicit P6 work rather than silent fallback logic.

## P8 — UI/application workflow

Status: `PLANNED`.

Add the user-facing local/browser UI after the query/data semantics and required real-data coverage are
reliable.
