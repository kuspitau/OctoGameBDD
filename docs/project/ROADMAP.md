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

Status: `VALIDATED` through P3-T05B.

Delivered quest identity/endpoints, restrictions/progression, structured objectives, item
requirements/rewards and conservative Octo/Turtle source-specific evidence.

## P4 — spells, recipes, reagents and acquisition

Status: `VALIDATED` through P4-T04.

Delivered recipe/spell identity, outputs, reagents and trainer/recipe-item acquisition sources.

## P5 — coverage, provenance and conflict auditing

Status: `VALIDATED` through P5-T08.

The bounded world-source conflict audit established that pfQuest/Turtle/Octo spawn disagreement is
predominantly source-specific complete spawn-membership divergence. No global merge/source-promotion
rule was justified; D-025/D-026 remained unchanged.

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

Final real promotion:

```text
eligible/promoted item IDs      = 7886, 15784, 41278
item_templates_promoted         = 3
item_stat_modifiers_promoted    = 2
second import inserts/updates   = 0 / 0
foreign_key_check               = []
integrity_check                 = ok
canonical SHA-256               = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

Eleven older refresh-proven records were correctly excluded because the current WDB no longer
contained a record matching the original proof hash.

### P6-T05 — migration-14 coverage expansion and incremental promotion

Status: `VALIDATED`.

Completed the bounded migration-14 -> migration-14 acquisition/promotion path without schema
reapplication or freshness weakening. Final measured tranche:

```text
attempted_unique = 19
refresh_proven = 15
retryable = 3
eligible_item_count = 15
already_current_noop_count = 3
canonical item population = 23336
current matching WDB identity coverage = 5995 / 23336 (0.25689921)
plan revision = sha256:685f02faa83af9d0c7c7135e244e55702ec867c76670dc8b71bf2ce4ca59b952
canonical SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Shadow validation and the guarded real promotion passed; D-029 now contains the exact pre-P6-T05
`d57e...` migration-14 bytes and rollback remains available. The real promotion added 15 new template
rows and 12 net new stat-modifier rows; the immediate replay inserted/updated `0 / 0` and FK/integrity
checks remained clean.

Active migration-14 acquisition/promotion tooling defaults to the accepted `60ae...` baseline and
separate `p6_itemcache_*` generated artifacts. Historical P6-T05 replay remains explicit through
`--baseline p6-t05-input`; the original P6-T03 validator stays historical migration-13 tooling.

This proves the incremental path and provides a larger real item/stat slice, but it does not claim
whole-population template/stat completeness. Later P6 work remains consumer-driven, including weapon
damage/speed/block, item effects/spells/tooltips, explicit fallback adapters, or another acquisition
tranche only when a P7 requirement justifies it.

## P7 — query/exploration layer

Status: `READY_FOR_IMPLEMENTATION`; next task is P7-T01.

Build richer provenance-aware cross-domain exploration:

- item acquisition/source exploration;
- arbitrary item stat filtering/sorting and weighted scores;
- quest chains/objectives/rewards;
- creature/gameobject geography;
- recipe/reagent/acquisition traversal;
- configurable columns, saved searches and comparisons.

The existing small P6 `item_search.py` surface is a useful vertical slice, not yet the final P7 query
contract. P7 must expose partial/unknown coverage explicitly rather than presenting absent projections
as negative game facts.

### P7-T01 — provenance-aware item query/filter contract

Status: `READY_FOR_IMPLEMENTATION`.

Define the first stable consumer-facing item-template/stat query contract over the validated
migration-14 surface: filters, sorting, provenance/coverage trace and deterministic CLI/library output.
No canonical mutation or new source-authority rule belongs in this task.

## P8 — UI/application workflow

Status: `PLANNED`.

Add the user-facing local browser UI after the query/data semantics and required real-data coverage are
reliable.
