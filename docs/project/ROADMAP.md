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
pfQuest base world import, Turtle/Octo overlay composition, D-026 complete `spawn_set` evidence and
managed Turtle effective-view reconciliation.

## P2 — items and acquisition sources

Status: `VALIDATED` through P2-T04.

Delivered item identity plus direct/reference loot and vendor relations, with Turtle effective-view
reconciliation for the bounded P2 fact family. Template/stat fields beyond that bounded family remain
for P6.

## P3 — quests

Status: `VALIDATED` through P3-T05B.

Delivered quest identity/endpoints, restrictions/progression, structured objectives, item
requirements/rewards and conservative Octo/Turtle source-specific evidence.

## P4 — spells, recipes, reagents and acquisition

Status: `VALIDATED` through P4-T04.

Delivered recipe/spell identity, outputs, reagents and trainer/recipe-item acquisition sources.
Canonical schema baseline remains migration 13.

Canonical SHA-256:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

## P5 — coverage, provenance and conflict auditing

Status: `VALIDATED` through P5-T08. The current world-spawn source-conflict audit thread is complete.

### P5-T01 — first post-P4 coverage audit

Status: `VALIDATED`.

Established the bounded audit layer and routed world-source comparison.

### P5-T02 — comparison-source readiness

Status: `VALIDATED`.

Established that `pfquest-octo` can be persisted/compared without changing D-026 authority.

### P5-T03 — selected world vs pfquest-octo comparison

Status: `VALIDATED`.

```text
audited records          = 450659
same_value               = 394970
different_value          =   2759
active_only              =  32078
comparison_only          =  12600
not_directly_comparable  =   8252
```

### P5-T04 — spawn membership divergence geometry/topology

Status: `VALIDATED`.

```text
shared total          = 145447
active-only total     =  16005
comparison-only total =   6290
one-sided total       =  22295
```

Rejected a global automatic relocation/identity explanation.

### P5-T05 — three-way base/Turtle/Octo spawn divergence attribution

Status: `VALIDATED`.

```text
base_active_not_comparison     =    17
active_only_vs_base            = 15988
base_comparison_not_active     =  1571
comparison_only_vs_base        =  4719
```

20,707 / 22,295 one-sided memberships are overlay additions relative to base.

### P5-T06 — overlay-addition coverage by base-parent and zone provenance

Status: `VALIDATED`.

```text
parent_absent_from_base            =  7984
spawn_added_to_base_present_parent = 12723
included additions                 = 20707
```

Top four routed zones contain 15,607 additions:

```text
Stonetalon Mountains = 5145
Grim Reaches         = 5062
Northwind            = 2872
Blackrock Depths     = 2528
```

### P5-T07 — concentrated spawn-addition raw-source semantic audit

Status: `VALIDATED`.

```text
both overlays add parents                         =  747
both whole-entry replacement parents              = 1085
different whole-entry replacement payload parents = 1085
shared exact added routed members                 =    3
```

Established that common replacement is widespread while exact added membership is almost entirely
source-specific.

### P5-T08 — shared-parent overlay replacement semantic divergence audit

Status: `VALIDATED`.

Human Level-2 validation passed on 2026-08-28 with 222 pytest tests, Ruff, compileall, exact canonical
SHA/source revisions and deterministic read-only semantic evidence.

Fixed common-replacement population:

```text
parents = 1085
creature = 439
gameobject = 646
```

Exact A/C set relations:

```text
active_equals_comparison      =   0
active_strict_superset         = 472
comparison_strict_superset     =   0
partial_overlap                = 164
disjoint                       = 449
```

Raw semantic difference classes:

```text
spawn_membership_only          = 1084
spawn_plus_other_fields        =    1
localization_name_only         =    0
other_top_entry_fields_only    =    0
unsupported_unclassified       =    0
```

Interpretation:

- disagreement is overwhelmingly isolated to complete spawn membership;
- no fixed parent has equal active/comparison spawn sets;
- active is a strict superset for 43.50%, while 56.50% are partial-overlap or disjoint;
- comparison is never a strict superset in this population, but partial/disjoint cases retain
  comparison-only evidence;
- no global merge, source promotion, source-interchangeability assumption or coordinate identity rule
  is justified;
- D-025/D-026 remain unchanged and `pfquest-octo` remains comparison evidence.

The current P5 world-source conflict question is therefore closed. Reopen it only for a concrete
consumer requirement or materially stronger direct Octo evidence.

## P6 — broader source ingestion and remaining domains

Status: `VALIDATED` through P6-T01; P6-T02 is `READY_FOR_IMPLEMENTATION`.

### P6-T01 — item template/stat source contract and bounded ingestion slice

Status: `VALIDATED`.

Accepted the bounded direct-Octo `itemcache.wdb` contract recorded by D-036 for class/subclass,
quality, inventory type, item/required levels, class/race masks, supported skill/spell/reputation
requirements, armor/resistances, durability and ten ordered raw stat slots. Cache absence remains
unknown and arbitrary cache presence does not itself prove freshness.

Migration 14 provides validated `item_templates` / `item_stat_modifiers` projection capability, but
P6-T01 deliberately validated it only on a disposable copy. The cumulative canonical DB remains
migration 13.

Human validation on 2026-08-29 passed the 228-test suite, Ruff, compileall and the real Octo
`itemcache.wdb` Level-2 probe. The bounded real slice selected 25 canonical item IDs, materialized 25
template rows and 3 non-empty stat modifiers, passed repeated-import idempotence/provenance/FK/SQLite
integrity checks and left the canonical SHA byte-identical.

### P6-T02 — direct Octo item-cache freshness, coverage and bounded refresh probe

Status: `READY_FOR_IMPLEMENTATION`.

Measure actual `itemcache.wdb` coverage against the known item population and establish whether/how a
bounded selected item set can be refreshed or directly queried with observable currentness evidence.
Keep cache absence unknown, avoid arbitrary ID brute force and keep the canonical DB read-only.

Use the measured freshness/coverage result to route one of:

- broader/full item template/stat ingestion;
- weapon damage/speed/block semantics;
- item effects/spell/tooltip semantics;
- a field-specific OctoDB/Tortoise/Vanilla fallback where direct coverage is insufficient;
- explicit migration-14 canonical promotion under D-029 after the intended cumulative data state is
  defined and validated.

Potential later P6 work remains consumer-driven and field-specific; no universal source priority is
introduced.

## P7 — query/exploration layer

Status: `PLANNED`.

Build richer provenance-aware cross-domain exploration after sufficient P6 coverage:

- item acquisition/source exploration;
- arbitrary item stat filtering/sorting and weighted scores;
- quest chains/objectives/rewards;
- creature/gameobject geography;
- recipe/reagent/acquisition traversal;
- configurable columns, saved searches and comparisons.

## P8 — UI/application workflow

Status: `PLANNED`.

Add the user-facing local browser UI only after the data/query semantics are reliable.
