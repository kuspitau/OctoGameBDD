# Roadmap

The roadmap is staged to keep source semantics, provenance, and canonical selection auditable before
large-scale ingestion or UI work.

## P0 — foundation and provenance

Status: `VALIDATED`.

Delivered:

- project/package skeleton;
- migration runner and schema versioning;
- import metadata and provenance primitives;
- source observations and canonical selections;
- audit/query primitives for source disagreements.

## P1 — world foundation

Status: `VALIDATED` through P1-T04.

Delivered:

- maps, zones, creatures, gameobjects and separate spawn rows;
- pfQuest base world import;
- direct Octo client DBC map/area hierarchy;
- Turtle/Octo overlay source inspection and effective-view reconstruction;
- D-026 complete-set `spawn_set` and source-view deletion semantics;
- Turtle active effective-view reconciliation while preserving comparison evidence.

## P2 — items and acquisition sources

Status: `VALIDATED` through P2-T04.

Delivered:

- item identity;
- direct creature/gameobject loot;
- reference-loot expansion;
- vendor relations;
- Turtle item/acquisition effective-view reconciliation;
- geography derived through P1 source identities/spawns rather than duplicated onto item relations.

## P3 — quests

Status: `VALIDATED` through P3-T05B.

Delivered:

- quest identity and creature/gameobject endpoints;
- Turtle quest effective-view reconciliation;
- progression/prerequisite relations;
- structured objectives;
- quest item requirements/provided/reward facts;
- direct Octo live quest-query and structured Turtle-lineage evidence paths with conservative
  source-specific authority.

## P4 — spells, recipes, reagents and acquisition

Status: `VALIDATED` through P4-T04.

Delivered:

- source semantics for spells/recipes;
- direct Octo DBC recipe identity/output;
- canonical reagent relations;
- trainer and recipe-item acquisition sources;
- migration 13 canonical schema baseline.

Canonical database SHA-256 after P4-T04 remains:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

## P5 — coverage, provenance and conflict auditing

### P5-T01 — first post-P4 coverage audit

Status: `VALIDATED`.

Established the bounded audit layer and identified world-source comparison as the next highest-value
coverage question.

### P5-T02 — comparison-source readiness

Status: `VALIDATED`.

Established that `pfquest-octo` could be persisted and compared without changing D-026 authority.

### P5-T03 — selected world vs pfquest-octo comparison

Status: `VALIDATED`.

Validated fixed baseline:

```text
audited records               = 450659
same_value                    = 394970
different_value               =   2759
active_only                   =  32078
comparison_only               =  12600
not_directly_comparable       =   8252
```

Spawn membership one-sided baseline:

```text
creature active-only / comparison-only   = 10255 / 3928
gameobject active-only / comparison-only =  5750 / 2362
```

### P5-T04 — spawn membership divergence geometry/topology

Status: `VALIDATED`.

Validated unique membership baseline:

```text
shared total          = 145447
active-only total     =  16005
comparison-only total =   6290
one-sided total       =  22295
```

Validated directly comparable parent topology:

```text
shared_only             = 22428
active_only_members     =  1274
comparison_only_members =   154
mixed_one_sided_members =  1136
```

Validated coordinate-compatible candidate cardinality:

```text
zero     = 12103
one      =  1539
multiple =  8653
```

The result rejected a global automatic relocation/identity explanation and routed source-side
attribution before any authority decision.

### P5-T05 — three-way base/Turtle/Octo spawn divergence attribution

Status: `VALIDATED`.

Validated attribution:

```text
base_active_not_comparison     =    17
active_only_vs_base            = 15988
base_comparison_not_active     =  1571
comparison_only_vs_base        =  4719
one-sided total                = 22295
```

The result shows that 20,707 / 22,295 one-sided memberships (92.88%) are overlay additions relative
to base. Source-local replacement evidence is sparse, while divergence is geographically
concentrated. No D-025/D-026, authority, selection or identity change was made.

### P5-T06 — overlay-addition coverage by base-parent and zone provenance

Status: `VALIDATED`.

Validated Level-2 result:

```text
parent_absent_from_base            =  7984
spawn_added_to_base_present_parent = 12723
included additions                 = 20707
```

Cross-overlay grouping coverage:

```text
same parent, both overlays add = 10917 members
same zone/map, both add        = 10760 members
```

The top four zones account for 15,607 / 20,707 additions (75.37%):

```text
Stonetalon Mountains = 5145
Grim Reaches         = 5062
Northwind            = 2872
Blackrock Depths     = 2528
```

The result shows a mixed source-completeness picture: base-present-parent extra membership is the
larger global class, both overlays contribute large distinct sets in the same parent/zone contexts,
and geographic concentration is strong. No source authority, D-025/D-026, selection or spawn
identity change was made.

### P5-T07 — concentrated spawn-addition raw-source semantic audit

Status: `READY_FOR_IMPLEMENTATION`.

Bounded purpose:

- inspect the exact raw-source/composition semantics behind the four dominant P5-T06 zones;
- distinguish inherited base content, overlay-added parents, whole-entry replacement and added spawn
  membership without inventing cross-source spawn identity;
- trace representative high-contribution parents and source files for both active/Turtle and
  pfquest-octo comparison sides;
- verify exact local source revisions before drawing conclusions;
- keep the task read-only and defer any authority/policy change until the source mechanics are
  demonstrated.

The result should determine whether a later P5 task should review field/relation-specific source
authority for spawn membership, isolate source-family coverage differences, or treat some
concentrations as expected custom-content overlays.

## P6 — broader source ingestion and remaining domains

Status: `PLANNED`.

Potential work after P5 evidence is sufficient:

- expand source coverage beyond validated vertical slices;
- ingest additional item/world/quest/spell facts where consumers require them;
- add remaining gameobject/creature/item metadata and unresolved source families;
- keep field/relation-specific source policy explicit rather than introducing a universal priority.

## P7 — query/exploration layer

Status: `PLANNED`.

Build richer cross-domain exploration once coverage and conflict semantics are stable:

- item acquisition/source exploration;
- quest chains/objectives/rewards;
- creature/gameobject geographic views;
- recipe/reagent/acquisition traversal;
- filtering/sorting by canonical and provenance-aware fields.

## P8 — UI/application workflow

Status: `PLANNED`.

Add user-facing interfaces only after the underlying data semantics and audit behavior are reliable.
