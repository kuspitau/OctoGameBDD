# Current Project State

This file is the permanent task router. Read `AGENTS.md` first, then this file, then only the
additional task-specific context it points to.

## Source of truth and integration state

GitHub source of truth was re-resolved during P7-T04 closeout and still pointed to:

```text
GitHub repository: kuspitau/OctoGameBDD
branch: main
tracked head: e9edbd30afa852f27a422f826271d3ba7e58dde1
commit: Validate P7-T03 quest exploration and route P7-T04
```

The human working tree already contains the P7-T04 implementation handoff validated below. This
closeout is therefore intentionally **stacked on that local P7-T04 delta**; it is not a standalone
patch against `e9edbd30...`.

Commit and push the complete validated P7-T04 working tree plus this closeout before starting P7-T05.
A fresh conversation must resolve the actual current GitHub `main` again and must not implement P7-T05
if `main` still lacks the P7-T04 validated closure.

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

P7-T04 was a read-only consumer task. Its validated closure did not mutate either SQLite file,
replace the rollback, alter source priority or authorize another P6 acquisition tranche.

## Phase state

```text
P0  foundation/provenance                         VALIDATED
P1  world foundation                              VALIDATED through P1-T04
P2  items/acquisition                             VALIDATED through P2-T04
P3  quests                                        VALIDATED through P3-T05
P4  spells/recipes/reagents/acquisition           VALIDATED through P4-T04
P5  provenance/coverage/conflict audit            VALIDATED through P5-T08
P6  broader item-template acquisition/promotion   VALIDATED through P6-T05
P7  query/exploration                             VALIDATED through P7-T04;
                                                    P7-T05 READY_FOR_IMPLEMENTATION
P8  UI/application workflow                       PLANNED
```

P7-T01 remains the authoritative item identity/template/stat predicate layer. P7-T02 composes that
with item acquisition/source geography. P7-T03 remains the authoritative bounded quest exploration,
relation-specific geography and prerequisite/follow-up traversal layer. P7-T04 adds a validated bounded
recipe consumer surface on top of those layers without changing their source semantics.

Missing materialization or derived geography remains unknown/not-proven unless the underlying
validated source contract explicitly proves a negative.

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

Validated semantics to preserve include relation-specific giver/finisher/objective geography,
`any_of` prerequisites, derived follow-ups, separate close sets, explicit unresolved evidence and
strict read-only SQLite access.

Human local gates and accepted-canonical Level 2 passed with:

```text
P7_T03_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
quest_identities=6498
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

P7-T03 is `VALIDATED` and is not the active implementation task.

## P7-T04 validated closure — 2026-08-31

Task/validation record:

```text
docs/project/tasks/P7-T04.md
```

Durable query contract:

```text
docs/project/P7_RECIPE_QUERY_CONTRACT.md
```

Validated implementation surfaces:

```text
src/octogamedb/recipe_search.py
src/octogamedb/recipe_cli.py
tests/test_recipe_search.py
scripts/validate_p7_t04.py
```

Validated semantics include:

- recipe ID/crafting-spell name search;
- same-membership skill-line ID/name and required-skill filtering;
- native output/reagent item filtering while keeping canonical resolution separate;
- all output/reagent slots retained independently, including unresolved native IDs;
- exact validated reagent quantities;
- teaching-item, direct/template trainer and quest-reward-spell learning paths kept separate;
- learning proof kind, acquisition wrapper spell and selected provenance exposed;
- teaching-item acquisition composed through P7-T02;
- trainer geography composed through P1 world locations;
- quest-learning context composed through P7-T03;
- teaching/trainer/quest geography roles kept distinct;
- derived acquisition/geography filters use positive evidence or `unknown`;
- deterministic bounded JSON-friendly output and strict read-only CLI.

Human repository gates passed:

```text
pytest --basetemp="$env:TEMP\OctoGameDB_pytest"
336 passed in 13.90s

python -m ruff check src tests
All checks passed!

python -m compileall -q src tests
PASS
```

Accepted-canonical Level 2 passed:

```text
P7_T04_LOCAL_VALIDATION_OK
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
schema_version=14
recipe_identities=1739
identity_skill_output_sample_recipe_id=37
multi_reagent_sample_recipe_id=37
teaching_item_sample_recipe_id=37
teaching_item_sample_native_item_id=16
located_teaching_item_sample_recipe_id=37
located_teaching_item_sample_item_id=16
located_direct_trainer_sample_recipe_id=587
located_direct_trainer_sample_entry=198
template_trainer_sample_recipe_id=41001
template_trainer_sample_entry=61906
quest_learning_sample_recipe_id=9972
quest_learning_sample_quest_id=2773
unresolved_learning_sample_recipe_id=597
unresolved_learning_sample_kind=teaching_item
unresolved_learning_sample_native_id=1099
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
```

The sample IDs are observations only. The canonical remained byte-identical. P7-T04 is `VALIDATED`.

## Active task / next action

```text
P7-T05 — provenance-aware creature/gameobject exploration and role/geography query
status: READY_FOR_IMPLEMENTATION
```

Task contract:

```text
docs/project/tasks/P7-T05.md
```

P7-T05 should provide the missing first-class creature/gameobject consumer surface by composing the
validated P1 world identities/spawns with relevant P2 acquisition/vendor, P3 quest-role/objective and
P4 trainer evidence. Template entities and spawn instances remain distinct; geography remains derived
from spawn evidence; unresolved/unlocated relations remain explicit.

Do not begin P7-T05 against the currently observed GitHub head `e9edbd30...`. First commit/push the
validated P7-T04 implementation plus closeout, then resolve the new `main` and use that as the task
base.

## Routing constraints that remain active

Further P6 acquisition remains consumer-driven. Weapon damage/speed/block, item effects/tooltips,
weighted scores, saved searches, ownership/inventory integration, generalized dungeon classification,
economics/profit modeling and graphical UI remain later bounded tasks unless a future task demonstrates
a concrete prerequisite.
