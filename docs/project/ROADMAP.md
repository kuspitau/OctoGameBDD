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

Status: `VALIDATED` through P6-T04; P6-T05 is `READY_FOR_IMPLEMENTATION`.

Current accepted canonical DB:

```text
migration 14 / 0014_item_template_facts.sql
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

Immediate D-029 rollback is the exact migration-13 baseline:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
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

Status: `READY_FOR_IMPLEMENTATION`.

Use the now-accepted migration-14 canonical as the baseline for one bounded additional acquisition
tranche and a safe incremental promotion. The task should remove obsolete migration-13 assumptions
from P6 acquisition validators, preserve old evidence without treating it as current, and prove that
new current records can be added to the migration-14 canonical without reapplying migration 14.

P6-T05 is driven by a concrete consumer need: P7 item/stat search should not begin against a canonical
real-data slice containing only three promoted templates.

P6-T05 does **not** require exhaustive acquisition of every remaining candidate. After its bounded
tranche, measured coverage should determine whether P7-T01 can start or whether another explicitly
justified P6 coverage tranche is needed.

Potential later field-specific P6 work remains consumer-driven, including weapon damage/speed/block,
item effects/spells/tooltips, and explicit fallback adapters where direct Octo evidence is insufficient.
No universal source priority is introduced.

## P7 — query/exploration layer

Status: `PLANNED`; blocked pending the P6-T05 coverage reassessment.

Build richer provenance-aware cross-domain exploration:

- item acquisition/source exploration;
- arbitrary item stat filtering/sorting and weighted scores;
- quest chains/objectives/rewards;
- creature/gameobject geography;
- recipe/reagent/acquisition traversal;
- configurable columns, saved searches and comparisons.

The existing small P6 `item_search.py` surface is a useful vertical slice, not yet the final P7 query
contract.

## P8 — UI/application workflow

Status: `PLANNED`.

Add the user-facing local browser UI after the query/data semantics and required real-data coverage are
reliable.
