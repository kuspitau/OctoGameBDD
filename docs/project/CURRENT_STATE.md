# Current project state

Updated for the validated P7-T06 closure on 2026-09-01.

## Source-of-truth and stacked handoff state

At closure-package time, GitHub `main` still resolves to:

```text
97625087922318bde253657856bae97d6383116c
Validate P7-T05 world entity exploration and route P7-T06
```

The human local working tree is intentionally ahead of that commit: it contains the complete P7-T06
implementation, its runtime/performance correction, the successful repository/full-data validation,
and this documentation closeout. The closeout delta is therefore **stacked on that local P7-T06
working state** and must not be applied to a bare `9762508...` checkout by itself.

The next conversation must resolve GitHub `main` fresh. If `main` contains the validated P7-T06 tree
and this closeout, continue from P7-T07 below. If it does not, stop and reconcile/push the validated
local tree first.

## Accepted canonical local database

The accepted cumulative local database remains:

```text
data/generated/octogamedb.sqlite3
schema_version = 14
latest migration = 0014_item_template_facts.sql
SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Immediate D-029 rollback snapshot remains:

```text
data/generated/octogamedb_bak.sqlite3
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

P7-T06 is read-only. Its successful Level-2 validation verified the canonical DB remained
byte-identical, so neither canonical file advanced or rotated.

## Phase status

```text
P0: VALIDATED
P1: VALIDATED through P1-T04
P2: VALIDATED through P2-T04
P3: VALIDATED through P3-T05
P4: VALIDATED through P4-T04
P5: VALIDATED through P5-T08
P6: VALIDATED through P6-T05
P7-T01: VALIDATED
P7-T02: VALIDATED
P7-T03: VALIDATED
P7-T04: VALIDATED
P7-T05: VALIDATED and integrated on GitHub main
P7-T06: VALIDATED locally; closure ready to commit/push
P7-T07: READY_FOR_IMPLEMENTATION after fresh-main confirmation of P7-T06 integration
```

Another P6 acquisition tranche is not automatic; later source work remains consumer-driven.

## P7-T06 validated closure

Task:

```text
docs/project/tasks/P7-T06.md
```

Contract:

```text
docs/project/P7_ZONE_QUERY_CONTRACT.md
```

Final implementation includes:

```text
src/octogamedb/zone_search.py
src/octogamedb/zone_cli.py
src/octogamedb/zone_recipe_projection.py
tests/test_zone_search.py
tests/test_zone_recipe_projection.py
scripts/validate_p7_t06.py
```

P7-T06 remains a derived/read-only composition layer. It searches canonical zones/maps and composes
world entities/spawns, item acquisition, quest roles, vendors, trainers and compact positive
recipe-learning evidence without persisting a universal `zone -> everything` relation.

The first human Level-2 attempt exposed a pathological recipe path that repeatedly traversed the full
P7-T04/P7-T02 query stack. The correction introduced `zone_recipe_projection.py`, which inverts the
zone-scoped item/trainer/quest evidence already computed by P7-T06. Full recipe hydration remains
owned by P7-T04.

The human then confirmed the complete repository pytest gate, Ruff and compileall all pass. The
accepted-canonical validator completed successfully with:

```text
P7_T06_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
zone_identities=1480
identity_sample_zone_id=1
multi_spawn_sample_zone_id=12
direct_item_sample_zone_id=1
reference_item_sample_zone_id=1
vendor_item_sample_zone_id=1
quest_giver_sample_zone_id=1
quest_finisher_sample_zone_id=1
quest_objective_sample_zone_id=1
teaching_recipe_sample_zone_id=1
trainer_recipe_sample_zone_id=1
quest_recipe_sample_zone_id=3
validated_zone_detail_count=5
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=True
```

Dynamic sample IDs are validation observations, not semantic constants.

## Measured P7-T06 performance debt

The recipe-specific explosion is fixed, but representative accepted-canonical timings show the
remaining zone path is still too slow for an interactive explorer:

```text
inspect_zone(12, include_recipes=False) = 27.60 s
inspect_zone(1,  include_recipes=False) = 31.44 s
inspect_zone(14, include_recipes=False) = 41.25 s
inspect_zone(1,  include_recipes=True)  = 32.31 s
inspect_zone(3,  include_recipes=True)  = 20.85 s
```

The small difference between recipe/no-recipe cases indicates the dominant residual cost is below the
new compact recipe projection, primarily in the P7-T05 world-entity/role/provenance path. This is now
measured performance debt rather than an unvalidated suspicion.

## Current/next task — P7-T07

Task router:

```text
docs/project/tasks/P7-T07.md
```

Status:

```text
READY_FOR_IMPLEMENTATION
```

P7-T07 is the bounded next task because P7-T06 exposed a concrete 20-40 second zone-query latency on
representative full data. It must profile and optimize the zone/world-entity read path while preserving
the already validated P7-T05/P7-T06 semantics and read-only canonical behavior.

Do not silently add a persistent materialized `zone -> everything` cache or schema migration merely
for speed. If profiling shows a persistent derived index/cache is required, record the evidence and
introduce/supersede architecture decisions explicitly before such a change.

## Next-conversation guard

Before implementing P7-T07:

1. resolve GitHub `main` fresh;
2. confirm the pushed tree contains P7-T06, `zone_recipe_projection.py`, the validated P7-T06 docs and
   `docs/project/tasks/P7-T07.md`;
3. read `AGENTS.md`, this file, `AI_GUIDELINES.md`, `PROJECT.md`, the P7-T07 task and only its relevant
   contracts/implementation/tests;
4. use the accepted schema-14 canonical DB only for read-only performance validation.

If P7-T06 closure is not yet on GitHub, do not implement P7-T07 on the old `9762508...` base.
Generalized dungeon/instance UX and P8 graphical UI remain deferred until this measured query hot path
is addressed or explicitly accepted.
