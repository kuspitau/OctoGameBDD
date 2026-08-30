# Current Project State

This file is the permanent task router. Read `AGENTS.md` first, then this file, then only the
additional task-specific context it points to.

## Source of truth and integration state

Tracked GitHub source of truth currently visible to this closeout:

```text
GitHub repository: kuspitau/OctoGameBDD
branch: main
visible head: 0034abb9e2bb657b286515820690606f981fda32
commit: Validate P7-T02 provenance-aware item acquisition exploration and route P7-T03
```

P7-T03 was implemented and fully validated as a local delta on that base. This closeout is therefore
**stacked on the complete local P7-T03 implementation**. Do not apply only this closeout to a bare
`0034abb...` checkout; the P7-T03 implementation files from the preceding handoff must already be
present in the working tree.

After the human commits and pushes the complete P7-T03 implementation + this closeout, the actual new
GitHub `main` head supersedes `0034abb...`. Every fresh conversation must resolve that current head
again before editing. P7-T04 must not be implemented against bare `0034abb...` while assuming P7-T03
exists.

## Accepted cumulative canonical database

The accepted local canonical baseline remains unchanged:

```text
data/generated/octogamedb.sqlite3
schema_version = 14
latest migration = 0014_item_template_facts.sql
SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Immediate D-029 rollback remains:

```text
data/generated/octogamedb_bak.sqlite3
schema_version = 14
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

P7-T03 was a read-only consumer task. It did not mutate either SQLite file, replace the rollback,
apply a migration, alter source priority or authorize another P6 acquisition tranche.

## Validated phase state

```text
P0  foundation/provenance                         VALIDATED
P1  world foundation                              VALIDATED through P1-T04
P2  items/acquisition                             VALIDATED through P2-T04
P3  quests                                        VALIDATED through P3-T05
P4  spells/recipes/reagents/acquisition           VALIDATED through P4-T04
P5  provenance/coverage/conflict audit            VALIDATED through P5-T08
P6  broader item-template acquisition/promotion   VALIDATED through P6-T05
P7  query/exploration                             VALIDATED through P7-T03; P7-T04 READY
P8  UI/application workflow                       PLANNED
```

P7-T01 remains the authoritative item identity/template/stat predicate layer. P7-T02 composes that
with item acquisition/source geography. P7-T03 is now the authoritative bounded quest exploration,
relation-specific geography and prerequisite/follow-up traversal layer. Missing materialization or
geography remains unknown/not-proven unless the underlying validated source contract proves a negative.

## P7-T03 validated closure — 2026-08-30

Task:

```text
docs/project/tasks/P7-T03.md
```

Durable query contract:

```text
docs/project/P7_QUEST_QUERY_CONTRACT.md
```

Validated implementation surfaces:

```text
src/octogamedb/quest_search.py
src/octogamedb/quest_cli.py
tests/test_quest_search.py
scripts/validate_p7_t03.py
```

Validated semantics to preserve:

- canonical quest ID/title search and known quest/minimum-level filtering use explicit
  `known_match` / `known_non_match` / `unknown` states;
- raw race/class masks remain raw source-domain values;
- giver, finisher and objective geography are distinct positive-evidence roles rather than one
  fabricated `quest -> zone` truth;
- same-role zone+map predicates must be satisfied by the same concrete known location;
- known relations with missing geography remain known relations with unknown geography;
- selected-but-unmaterialized endpoint/prerequisite/close IDs are retained from existing provenance;
- prerequisites retain `any_of` semantics; follow-ups are derived reverse prerequisite membership;
- close/exclusive sets remain separate from progression;
- prerequisite/follow-up traversal is bounded, deterministic, cycle-safe and reports BFS depth only as
  a derived edge distance, never a canonical linear chain step;
- P3-T04 objective membership and P3-T05 required/provided/guaranteed/choice item facts remain distinct;
- SQLite access is strict read-only `mode=ro`;
- no migration, source-selection rule or canonical mutation was introduced.

Human local gates after the final Ruff/read-model correction all passed:

```text
python -m pytest -q                         PASS
python -m ruff check src tests              PASS
python -m compileall -q src tests scripts   PASS
```

Dedicated accepted-canonical Level-2 validation passed:

```text
P7_T03_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
quest_identities=6498
located_giver_sample_quest_id=5
located_finisher_sample_quest_id=2
located_objective_sample_quest_id=7
prerequisite_sample_quest_id=2
prerequisite_sample_member_id=6383
close_sample_quest_id=96
required_item_sample_quest_id=2
reward_item_sample_quest_id=16
turtle_selected_sample_quest_id=105
unlocated_endpoint_sample_quest_id=96
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

The canonical DB remained byte-identical. P7-T03 is `VALIDATED` and is no longer the active task.

## Active task

```text
P7-T04 — provenance-aware recipe/reagent/acquisition exploration
status: READY_FOR_IMPLEMENTATION
```

Task contract:

```text
docs/project/tasks/P7-T04.md
```

P7-T04 is the next bounded consumer task because P4-T01..T04 already validate recipe identity,
skill-line requirements, outputs, reagents and direct learning sources, while P7-T01..T03 now provide
reusable item acquisition and quest/geography exploration. The task should compose those existing
surfaces rather than introduce new source acquisition or schema.

Before implementation, a fresh conversation must resolve the actual current GitHub `main` head and
confirm that the complete P7-T03 implementation/closeout has been committed. Then inspect only the P4
recipe contracts/read paths and the P7 composition surfaces needed by `docs/project/tasks/P7-T04.md`.

## Routing constraints that remain active

Further P6 acquisition remains consumer-driven. Weapon damage/speed/block, item effects/tooltips,
weighted scores, saved searches, ownership/inventory integration, generalized dungeon classification
and graphical UI remain later bounded tasks unless a future task demonstrates a concrete prerequisite.
