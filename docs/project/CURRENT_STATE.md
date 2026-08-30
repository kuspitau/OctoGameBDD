# Current Project State

This file is the permanent task router. Read `AGENTS.md` first, then this file, then only the
additional task-specific context it points to.

## Source of truth and integration state

Tracked project source of truth:

```text
GitHub repository: kuspitau/OctoGameBDD
branch: main
```

The visible GitHub base at the time of the P7-T01 implementation/validation handoff was:

```text
35c8a9da803c35348eb5602b7c203972d4a17d36
Validate P6-T05 reusable migration-14 promotion workflow and route P7-T01
```

P7-T01 was then implemented and fully validated locally as a stacked delta before this closeout. This
closeout is therefore also stacked on that complete local P7-T01 state. Do not apply this closeout to a
bare `35c8a9d...` checkout without first reconciling the P7-T01 implementation files.

After the human commits and pushes the complete P7-T01 implementation + closeout, the actual new
GitHub `main` head supersedes `35c8a9d...`; every fresh conversation must resolve that current head
again before editing.

## Accepted cumulative canonical database

The validated local canonical data baseline remains unchanged by P7-T01:

```text
data/generated/octogamedb.sqlite3
schema_version = 14
latest migration = 0014_item_template_facts.sql
SHA-256 = 60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Immediate D-029 rollback:

```text
data/generated/octogamedb_bak.sqlite3
schema_version = 14
SHA-256 = d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b
```

P7-T01 was a read-only consumer task. It did not mutate the canonical DB, replace D-029, apply a
migration, or authorize another P6 acquisition tranche.

## Validated phase state

```text
P0  foundation/provenance                         VALIDATED
P1  world foundation                              VALIDATED through P1-T04
P2  items/acquisition                             VALIDATED through P2-T04
P3  quests                                        VALIDATED through P3-T05B
P4  spells/recipes/reagents/acquisition           VALIDATED through P4-T04
P5  provenance/coverage/conflict audit            VALIDATED through P5-T08
P6  broader item-template acquisition/promotion   VALIDATED through P6-T05
P7  query/exploration                             VALIDATED through P7-T01; P7-T02 READY
P8  UI/application workflow                       PLANNED
```

P6-T05 accepted state relevant to current P7 work:

```text
canonical item identities = 23336
materialized item_templates = 18
item_stat_modifiers = 14
current matching WDB identity coverage measured during P6-T05 = 5995 / 23336
```

The migration-14 projection remains intentionally partial. D-036/D-037 remain authoritative: cache or
projection absence is unknown, never universal negative item evidence.

## P7-T01 validated closure — 2026-08-30

Task:

```text
docs/project/tasks/P7-T01.md
```

Durable query contract:

```text
docs/project/P7_ITEM_QUERY_CONTRACT.md
```

Validated code/test surfaces introduced by the P7-T01 implementation stack:

```text
src/octogamedb/item_search.py
src/octogamedb/item_query_cli.py
tests/test_item_search.py
scripts/validate_p7_t01.py
```

P7-T01 semantics to preserve:

- query universe is canonical `items`, not only materialized `item_templates`;
- template/stat predicates distinguish `known_match`, `known_non_match`, and `unknown`;
- missing `item_templates` means unknown template/stat coverage;
- for a materialized P6 template, the ten raw stat slots are complete, so a missing requested raw
  stat type is a known non-match;
- combined predicates use conservative conjunction: known false -> non-match; otherwise unknown ->
  unknown; otherwise match;
- no fallback/default fact may be manufactured;
- selected `template.*` provenance is returned for materialized results;
- sorting is deterministic and unknown sort values are last;
- result pages are bounded to `1..1000`, while summary state counts are exhaustive over canonical
  item identities;
- the original P6 `query_item_templates()` compatibility helper remains available;
- the P7 CLI opens SQLite read-only and performs no migration/acquisition.

Agent Level-1 focused result:

```text
9 passed
```

Human standard local checks passed:

```text
python -m pip install -e ".[dev]"
pytest --basetemp="$env:TEMP\OctoGameDB_pytest"
python -m ruff check src tests
python -m compileall -q src tests
```

The remaining autonomous Level-2 validation ran on a TEMP byte-identical copy of the accepted
canonical DB and returned:

```text
P7_T01_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
item_identities=23336
materialized_templates=18
unknown_templates=23318
match_sample_item_id=3565
nonmatch_sample_item_id=3565
unknown_sample_item_id=1
stat_sample=3565:type4>=3
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

The canonical DB remained byte-identical throughout. P7-T01 is `VALIDATED` and must not be re-run as
the active task merely because a future conversation is fresh.

## Active task

```text
P7-T02 — provenance-aware item acquisition/source exploration
status: READY_FOR_IMPLEMENTATION
```

Task contract:

```text
docs/project/tasks/P7-T02.md
```

P7-T02 composes the validated P7-T01 item predicate surface with the existing P2 acquisition graph and
P1 geography. It should expose/filter known direct/reference/vendor acquisition paths, known drop
chance and derived zone/map context while preserving path provenance and conservative unknown
semantics.

### P7-T02 constraints to preserve

- read-only consumer task; no canonical DB mutation;
- no schema migration unless a concrete blocker is first demonstrated and routed separately;
- no automatic P6 acquisition/promotion tranche;
- no new global source-priority rule;
- reuse existing `find_item_sources()` / P2 acquisition semantics rather than duplicating them;
- direct/reference paths remain separate and their probabilities are never combined without an
  explicit validated model;
- vendor `max_count` is not drop chance;
- acquisition geography remains derived through source template -> spawn -> zone/map; do not persist
  arbitrary `item -> zone` truth;
- unlocated sources remain valid known acquisition evidence with unknown geography;
- absence of a path/geography must not become a negative item fact unless exact completeness is proven
  from the relevant P2/P1 source-view evidence.

## Routing

Implement **P7-T02** next after confirming the complete P7-T01 implementation/closeout has been
committed to the actual current GitHub `main`.

Further P6 acquisition remains consumer-driven. Weapon damage/speed/block, item effects/tooltips,
weighted scores, saved searches, ownership, broad recipe/quest traversal and graphical UI remain later
bounded tasks.
