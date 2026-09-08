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

Status: `VALIDATED` through P7-T07. Later P7 feature tasks are consumer-driven and deferred until a concrete need emerges.

P7 builds richer provenance-aware cross-domain exploration while exposing partial/unknown coverage
instead of presenting absent projections as negative game facts.

### P7-T01 — provenance-aware item query/filter contract

Status: `VALIDATED`.

Delivered the first stable item identity/template/stat consumer contract over migration 14 with
explicit three-state evaluation, selected provenance, deterministic bounded output and strict
read-only validation.

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

Human repository and accepted-canonical closure completed on 2026-08-31 with clean FK/integrity and
byte-identical preservation of the accepted schema-14 SHA.

Contract: `docs/project/P7_RECIPE_QUERY_CONTRACT.md`.

### P7-T05 — provenance-aware creature/gameobject exploration and role/geography query

Status: `VALIDATED` and integrated on GitHub `main` at:

```text
97625087922318bde253657856bae97d6383116c
Validate P7-T05 world entity exploration and route P7-T06
```

Keeps template/spawn identity separate and composes P2 item/vendor, P3 quest-role/objective and P4
trainer evidence. Its validated D-026 coverage logic preserves raw duplicate selected `spawn_set`
multiplicity while comparing canonical membership by distinct `spawn_key`.

Contract: `docs/project/P7_WORLD_ENTITY_QUERY_CONTRACT.md`.

### P7-T06 — provenance-aware zone-centric exploration

Status: `VALIDATED` on 2026-09-01; local closure ready to commit/push.

P7-T06 delivers the missing first-class zone consumer surface over existing validated contracts:

- canonical zone/map search with selected identity provenance;
- concrete creature/gameobject spawn projection;
- independent item direct/reference/vendor acquisition paths;
- giver/finisher/creature-gameobject objective quest roles;
- vendors and resolved/unresolved trainers;
- compact positive recipe-learning evidence for teaching item, trainer and independent quest roles;
- explicit unknown/truncation coverage with no universal `zone -> everything` truth.

The first Level-2 attempt exposed a pathological repeated full P7-T04 recipe scan. The final validated
implementation replaces it with `zone_recipe_projection.py`, which inverts the zone-scoped positive
item/trainer/quest evidence while leaving full recipe detail owned by P7-T04.

Human repository gates all passed. Accepted-canonical Level 2 completed with:

```text
P7_T06_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
zone_identities=1480
validated_zone_detail_count=5
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=True
```

Representative successful-run timings remain approximately 20-40 seconds per zone detail. Because
recipe/no-recipe timings are similar after the correction, the residual bottleneck is primarily in the
P7-T05 world-entity/role/provenance path.

Contract/task:

```text
docs/project/P7_ZONE_QUERY_CONTRACT.md
docs/project/tasks/P7-T06.md
```

### P7-T07 — profile and optimize zone-centric query latency

Status: `VALIDATED` on 2026-09-03.

Accepted-canonical profiling identified a retained-entity quest-relation N+1 responsible for roughly
75-78% of representative no-recipe zone latency. The request-local selected-quest-relation batch
removes it without schema change or persistent cache. Full-data reruns now pass: representative cold
latency is `5.45-7.84 s`, no-recipe median improves `4.37x`, recipe-sample median improves `3.57x`,
and P7-T06 semantic/integrity validation remains clean. The final human `ruff check src tests scripts` gate also passes.

Task:

```text
docs/project/tasks/P7-T07.md
```

### Later P7 tasks

After P7-T07, later bounded tasks may add dungeon/instance views, richer item field families, weighted
scoring, saved queries/comparisons, ownership/inventory integration, craft economics, recursive BOM
analysis and other consumer capabilities as concrete needs emerge. Coverage gaps should drive explicit
P6 work rather than silent fallback logic.

General dungeon/raid classification, instance grouping and dungeon-specific quest-chain UX remain
deferred. P8 graphical UI remains planned after the query/data semantics and the measured hot paths
are sufficiently reliable for interactive use.

## P8 — UI/application workflow

Status: `IN_PROGRESS`; P8-T01 is `READY_FOR_IMPLEMENTATION`.

The validated P7 query layer and P7-T07 latency correction are now sufficient to begin a bounded
user-facing local/browser vertical slice. P8 must remain a consumer of validated query semantics rather
than creating parallel SQL truth.

### P8-T01 — local/browser UI foundation and zone explorer vertical slice

Status: `READY_FOR_IMPLEMENTATION`.

Select the UI framework from current primary evidence, establish a local read-only application shell,
and expose a bounded zone search/detail flow backed by the validated P7-T06/P7-T07 query path.

Task:

```text
docs/project/tasks/P8-T01.md
```
