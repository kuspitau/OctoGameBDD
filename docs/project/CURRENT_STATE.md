# Current Project State

This file is the permanent task router. Read `AGENTS.md` first, then this file, then only the
additional task-specific context it points to.

## Source of truth and integration state

Tracked GitHub source of truth currently visible to this closeout:

```text
GitHub repository: kuspitau/OctoGameBDD
branch: main
visible head: 3944291a278cf682f6e49de03242e221d8081633
commit: Validate P7-T01 provenance-aware item query contract and route P7-T02
```

P7-T02 was implemented as a local delta on that base and has now passed the required human/full-data
validation. This closeout is therefore **stacked on the complete local P7-T02 implementation**. Do not
apply only this closeout to a bare `3944291...` checkout; the P7-T02 implementation files from the
preceding handoff must already be present in the working tree.

After the human commits and pushes the complete P7-T02 implementation + this closeout, the actual new
GitHub `main` head supersedes `3944291...`. Every fresh conversation must resolve that current head
again before editing. P7-T03 must not be implemented against bare `3944291...` while assuming P7-T02
exists.

## Accepted cumulative canonical database

The validated local canonical data baseline is unchanged by P7-T02:

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

P7-T02 is a read-only consumer task. It did not mutate either SQLite file, replace the backup, apply a
migration, or authorize another P6 acquisition tranche.

## Validated phase state

```text
P0  foundation/provenance                         VALIDATED
P1  world foundation                              VALIDATED through P1-T04
P2  items/acquisition                             VALIDATED through P2-T04
P3  quests                                        VALIDATED through P3-T05
P4  spells/recipes/reagents/acquisition           VALIDATED through P4-T04
P5  provenance/coverage/conflict audit            VALIDATED through P5-T08
P6  broader item-template acquisition/promotion   VALIDATED through P6-T05
P7  query/exploration                             VALIDATED through P7-T02; P7-T03 READY
P8  UI/application workflow                       PLANNED
```

The prior `P3 ... through P3-T05B` wording in some P7 summaries was stale. `P3-T05B` is the validated
source-contract gate; `docs/project/tasks/P3-T05.md` is also `VALIDATED` and materializes the canonical
quest item requirement/reward families used by later consumers.

P6/P7 item state relevant to current work:

```text
canonical item identities = 23336
materialized item_templates = 18
item_stat_modifiers = 14
materialized acquisition items = 13113
current matching WDB identity coverage measured during P6-T05 = 5995 / 23336
```

D-036/D-037 and the validated P7-T01 contract remain authoritative: missing migration-14 item-template
coverage is unknown, never universal negative item evidence.

## P7-T01 validated closure — 2026-08-30

Task:

```text
docs/project/tasks/P7-T01.md
```

Durable query contract:

```text
docs/project/P7_ITEM_QUERY_CONTRACT.md
```

P7-T01 remains the authoritative item identity/template/stat predicate layer. It preserves explicit
`known_match` / `known_non_match` / `unknown` states over the canonical item universe and keeps the
partial migration-14 projection conservative.

## P7-T02 validated closure — 2026-08-30

Task:

```text
docs/project/tasks/P7-T02.md
```

Durable query contract:

```text
docs/project/P7_ITEM_ACQUISITION_QUERY_CONTRACT.md
```

Validated implementation surfaces:

```text
src/octogamedb/item_acquisition_search.py
src/octogamedb/item_acquisition_cli.py
tests/test_item_acquisition_search.py
scripts/validate_p7_t02.py
```

Validated P7-T02 semantics to preserve:

- P7-T01 remains the item predicate evaluator; P7-T02 does not fork template/stat semantics;
- existing P2 `find_item_sources()` is reused for direct creature/gameobject loot, one-level reference
  expansion, vendors, per-path provenance and P1-derived spawn/zone/map context;
- acquisition filters are existential positive-evidence filters over one concrete known source/path;
- supported filters include path kind (`direct` / `reference` / `vendor`), source template kind
  (`creature` / `gameobject`), minimum known path drop chance, native zone ID and native map ID;
- all requested acquisition/geography conditions must be satisfied by the same concrete source/path;
- a known satisfying path yields acquisition `known_match`;
- lack of a known satisfying path remains `unknown` with
  `no_known_matching_path_negative_not_proven`; no universal acquisition `known_non_match` is
  manufactured from absence;
- a P7-T01 known-false item predicate still dominates conjunction and remains `known_non_match`;
- direct/reference paths remain separate and their probabilities are never combined;
- `vendor_max_count` remains vendor provenance and is never treated as drop chance;
- unlocated sources remain valid acquisition evidence with unknown geography;
- geography remains derived source template -> spawn -> zone/map; no `item -> zone` primary truth is
  persisted;
- output remains deterministic and bounded; summary state counts remain exhaustive;
- the dedicated CLI and validator open SQLite read-only.

Agent focused validation before handoff:

```text
11 passed
compileall PASS
py_compile PASS
CLI --help PASS
```

Human/full-data validation completed successfully on the accepted canonical DB:

```text
P7_T02_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
item_identities=23336
materialized_acquisition_items=13113
direct_sample_item_id=1
reference_sample_item_id=647
vendor_sample_item_id=16
located_sample_item_id=1
unknown_acquisition_sample_item_id=2
template_acquisition_sample_item_id=3799
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

The canonical SHA remained byte-identical. P7-T02 is `VALIDATED`.

## Active task

```text
P7-T03 — provenance-aware quest exploration and progression/geography query
status: READY_FOR_IMPLEMENTATION
```

Task contract:

```text
docs/project/tasks/P7-T03.md
```

P7-T03 should turn the already-validated P3 quest read models into a stable bounded search/exploration
surface. It should support quest identity/level filtering, giver/finisher/objective geography,
prerequisite/follow-up traversal, and the existing quantity-bearing required/reward item facts while
preserving source provenance, set semantics and unknown/unresolved evidence.

### P7-T03 constraints to preserve

- read-only consumer task; no canonical DB mutation;
- no schema migration unless a concrete blocker is first demonstrated and routed separately;
- reuse `quest_by_id()`, `quest_objectives_by_id()` and `quest_item_facts_by_id()` semantics rather
  than duplicating/reinterpreting P3 logic;
- prerequisite sets retain their validated `any_of` semantics; follow-ups remain derived reverse edges;
- close/exclusive-group sets are not generic prerequisite edges;
- objective target geography remains relation-specific and derived; do not assign one simplistic
  primary `quest.zone_id`;
- giver, finisher and objective geography must remain distinguishable;
- unresolved targets and missing geography remain explicit unknown/unresolved evidence;
- objective item membership is not equivalent to quantity-bearing required-item facts;
- guaranteed rewards remain distinct from choose-one rewards;
- no path/chain step number may be invented when the selected prerequisite graph is branching or
  otherwise not uniquely ordered; any derived depth/route must state its derivation and ambiguity;
- deterministic bounded output and provenance are required.

## Routing

Apply this closeout only on top of the already-applied P7-T02 implementation, then commit and push the
complete P7-T02 stack. A fresh implementation conversation may begin P7-T03 only after confirming that
complete state is present on the actual current GitHub `main`.

Further P6 acquisition remains consumer-driven. Weapon damage/speed/block, item effects/tooltips,
weighted scores, saved searches, ownership/inventory integration, generalized dungeon classification
and graphical UI remain later bounded tasks unless P7-T03 demonstrates a concrete prerequisite.
