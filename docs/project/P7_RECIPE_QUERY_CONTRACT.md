# P7 recipe query contract

Status: `VALIDATED`

Task: `P7-T04`

This contract defines the first bounded consumer-facing recipe/reagent/learning-source exploration
surface over the already-validated P4 recipe model. It composes P7 item-acquisition, P1 world and P7
quest views at query time. It adds no migration, source authority, acquisition source or canonical
fact. All operations are read-only.

## Public surfaces

```text
src/octogamedb/recipe_search.py
  query_recipes()
  recipe_query_page_to_dict()

src/octogamedb/recipe_cli.py
  python -m octogamedb.recipe_cli ...
```

The CLI opens SQLite with `mode=ro`.

## Search universe and complete P4 predicates

The query universe is the canonical `recipes` table joined to its crafting spell. Recipe identity
remains the native crafting-spell ID under D-034:

```text
recipe_id = crafting_spell_id
```

Supported bounded predicates are:

- exact recipe/crafting-spell ID;
- case-insensitive crafting-spell name substring;
- skill-line ID and/or case-insensitive skill-line name substring;
- minimum/maximum recipe `required_skill_value`;
- native output item ID;
- native reagent item ID;
- one or more known learning-source kinds;
- role-specific derived geography for teaching-item acquisition, trainer locations and quest context.

Skill-line ID/name/required-skill constraints are evaluated against one concrete
`recipe_skill_lines` row. A recipe cannot satisfy the skill-line name on one membership and the
required-skill range on another.

P4 recipe/skill/output/reagent rows come from validated complete source-family semantics for the
selected revision. Within that bounded family they may prove `known_match` or `known_non_match`.
Output and reagent predicates match the preserved native item ID; canonical item resolution is shown
separately and is not required for the native relation to remain true.

## Three-state evaluation

The query surface uses:

```text
known_match
known_non_match
unknown
```

A known-false complete P4 predicate dominates a conjunction and produces `known_non_match`.
Derived acquisition/geography and learning-source absence are conservative: known positive evidence
can prove a match, but lack of currently materialized evidence remains `unknown` unless the validated
source contract explicitly proves a negative.

In particular:

- no known teaching-item acquisition path does not prove that the item cannot be acquired;
- no known trainer spawn does not prove that the recipe is unavailable from that trainer elsewhere;
- no matching quest endpoint/objective geography does not prove that the learning quest has no such
  context;
- no known learning source of a requested kind does not prove that no such source exists universally.

## Recipe detail

Every returned recipe preserves the P4 distinctions rather than flattening them.

### Identity and skill lines

The detail exposes:

- recipe ID / crafting spell ID;
- spell name and rank text;
- recipe-presence and spell-name selected provenance when available;
- every skill-line membership independently;
- native `skill_line_ability_id`;
- skill-line ID/name;
- exact `required_skill_value`;
- selected relation provenance.

### Outputs

Every materialized `CREATE_ITEM` output slot remains separate:

- `effect_index`;
- `native_item_id`;
- nullable canonical `item_id` and item name;
- explicit resolved/unresolved state;
- selected `crafted_output` provenance.

No fixed output quantity is inferred by P7-T04. P4-T02's calculated spell-effect semantics remain
authoritative.

### Reagents

Every materialized reagent slot remains separate:

- `reagent_index`;
- `native_item_id`;
- nullable canonical `item_id` and item name;
- exact validated `required_quantity`;
- explicit resolved/unresolved state;
- selected `reagent` provenance.

Slots are not aggregated and unresolved native item IDs are never replaced by placeholders.

## Learning paths

Learning paths remain three independent P4 relation kinds:

```text
teaching_item
trainer
quest_reward_spell
```

They are not collapsed into a generic `recipe source` relation.

Every path retains its selected P4 provenance plus:

- acquisition wrapper spell ID/name;
- `learning_proof_kind`;
- `learn_effect_index` when applicable;
- `server_learn_active` when applicable.

### Teaching item

The primary fact remains:

```text
recipe -> teaching item
```

The detail preserves the item spell slot, trigger/charges and unresolved native item ID. When the
teaching item resolves to a canonical item, P7-T04 composes the existing P7-T02 item-acquisition view.
Direct loot, reference loot and vendor paths therefore remain item acquisition paths, not newly
persisted recipe-learning rows.

The detail reports whether known item acquisition paths were found. Absence is explicitly
`unknown`/not-proven.

### Trainer

The primary fact remains the P4 recipe-learning trainer creature relation. The detail retains:

- `direct` vs `template` source semantics;
- native trainer entry and nullable canonical creature ID;
- trainer template ID for template-expanded rows;
- spell cost;
- trainer required skill-line ID/name;
- trainer required skill value;
- required character level;
- learning proof fields.

For resolved trainer creatures, geography is derived through the existing P1 world-location view.
No spawn means unknown geography, not a negative recipe-availability fact.

### Quest reward spell

The primary fact remains the P4 quest reward spell that teaches the recipe. The detail preserves the
native quest ID even when unresolved, reward spell field, wrapper/proof data and relation provenance.

When the quest resolves, P7-T04 composes the P7-T03 quest detail. Giver, finisher, objective and
progression semantics remain exactly those of P7-T03; P7-T04 does not define a single quest or recipe
zone.

## Geography filters are role-specific

P7-T04 deliberately exposes separate derived filters:

```text
teaching_zone / teaching_map
trainer_zone / trainer_map
quest_giver_zone / quest_giver_map
quest_finisher_zone / quest_finisher_map
quest_objective_zone / quest_objective_map
```

Within each role, zone and map must be satisfied by the same known location/path as required by the
underlying P7 surface. Evidence from different roles is never mixed into one universal recipe zone.

A matching known derived path/location proves `known_match`. No currently known match remains
`unknown` with a role-specific reason.

## Provenance

P7-T04 creates no selection policy. It reads existing selected evidence from the generic provenance
layer and returns, where present:

- source key and revision;
- source record type and raw identifier;
- authority tier;
- observation ID;
- canonical selection policy and reason;
- selected JSON value.

Competing observations remain in the provenance layer and are neither removed nor re-resolved by the
query surface.

## Determinism and bounds

For a fixed database and argument set, output ordering is deterministic. Supported sort keys are:

```text
recipe_id
name
```

Null spell names sort after known names. Search `limit` is bounded to `1..1000`.
JSON conversion emits only dictionaries/lists/scalars.

## CLI examples

```text
python -m octogamedb.recipe_cli --recipe-id 2259 --json
python -m octogamedb.recipe_cli --name-contains "elixir" --skill-line-name Alchemy --json
python -m octogamedb.recipe_cli --skill-line-id 171 --min-required-skill 200 --json
python -m octogamedb.recipe_cli --output-item-id 13442 --json
python -m octogamedb.recipe_cli --reagent-item-id 13463 --json
python -m octogamedb.recipe_cli --learning-kind trainer --trainer-zone 1519 --include-unknown --json
python -m octogamedb.recipe_cli --learning-kind teaching_item --teaching-map 0 --json
python -m octogamedb.recipe_cli --learning-kind quest_reward_spell --quest-giver-zone 12 --json
```

The IDs above are usage examples only; validation discovers representative real IDs dynamically.

## Non-goals

P7-T04 does not add:

- a persisted `recipe -> vendor`, `recipe -> loot source`, `recipe -> quest zone` or `recipe -> zone`
  relation;
- a combined drop-probability model;
- output-quantity inference;
- recursive bill-of-materials optimization;
- craft cost/profit or auction-house integration;
- ownership/inventory/bank/known-recipe state;
- new source ingestion or source-priority rules;
- saved searches, weighted scores or graphical UI.

Those remain later bounded tasks after this validated contract.

## Validation closure — 2026-08-31

P7-T04 completed the human repository and accepted-canonical gates. Observed closure:

```text
pytest: 336 passed in 13.90s
ruff src/tests: All checks passed
compileall src/tests: PASS
P7_T04_LOCAL_VALIDATION_OK
recipe_identities=1739
foreign_key_check=[]
integrity_check=ok
canonical_db_unchanged=true
canonical_sha256=60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23
```

Representative recipe/item/trainer/quest IDs printed by the validator are observations only and do
not narrow this contract. The accepted migration-14 canonical was not modified.
