# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must verify the actual current head before editing.

## Integration baseline for this handoff

P4-T02 was implemented from GitHub `main` commit:

```text
c4265d3a75599371976c453d189e258f1af858ee
```

Commit title:

```text
Validate P4-T01 spell/recipe source contract and advance to P4-T02
```

That commit contains the validated P4-T01 implementation/closeout. This P4-T02 delta must be applied
on top of that exact-or-descendant `main` state.

## Validated cumulative state

P0 through P4-T02 are `VALIDATED` in tracked project state.

The cumulative local canonical database is:

```text
data/generated/octogamedb.sqlite3
```

validated through:

```text
P4-T02 / migration 11 / 0011_recipe_identity.sql
```

The D-029 one-step rollback path remains:

```text
data/generated/octogamedb_bak.sqlite3
```

P4-T02 canonical promotion was completed and independently post-checked on 2026-08-26.

Current closeout hashes:

```text
data/generated/octogamedb.sqlite3
sha256:3e2a1b03dd688fc1b944665fcfa79cde68aacb537790f0c580480049a19ad8e7

data/generated/octogamedb_bak.sqlite3
sha256:9c637ab40c2c5e3c2843e6c7d52fb5c75bbe05f57d05e2ea4d48ae7bd03b127d
```

The `_bak` is the byte-identical migration-10 canonical immediately before P4-T02 promotion. It is
the D-029 one-step rollback state until the next validated canonical mutation cycle replaces it.

## P4-T01 — validated source/identity contract

### Status

```text
VALIDATED
```

Detailed closeout:

```text
docs/project/tasks/P4-T01.md
```

Durable D-034 rules remain:

- native `Spell.Id` is spell identity and ranks are never merged by display name;
- recipe identity remains a separate entity anchored to a proven crafting spell ID;
- recipe qualification requires both `SkillLineAbility` membership and `CREATE_ITEM` evidence;
- `SkillLineAbility.req_skill_value` is the recipe/trade-skill requirement;
- teaching items/trainers are acquisition sources and are not recipe identity;
- output effects preserve slot/order and may be multiple/variable;
- recipe items are optional acquisition sources, not recipe identity.

Primary parser/semantic reference remains:

```text
Penqle/tortoise-wow
61a8269151721f6467eddb05e7bed37704d0fc0b
```

## Active task

### P4-T02 — canonical spell / skill-line / recipe identity slice

**Status: VALIDATED**

Detailed implementation and validation procedure:

```text
docs/project/tasks/P4-T02.md
```

Implemented tracked slice:

```text
src/octogamedb/db/migrations/0011_recipe_identity.sql
src/octogamedb/importers/octo_dbc_recipes.py
scripts/validate_p4_t02.py
tests/test_octodbc_recipes.py
tests/fixtures/octo_dbc/recipe_slice/Spell.dbc
tests/fixtures/octo_dbc/recipe_slice/SkillLine.dbc
tests/fixtures/octo_dbc/recipe_slice/SkillLineAbility.dbc
```

Transient handoff helper:

```text
get_path.bat
```

The helper is not tracked project source. It only resolves/validates and, when needed, updates the
existing ignored `[source_paths].octo_dbc` key in `config.local.toml`.

### Implemented schema/semantics

Migration 11 adds:

```text
spells
skill_lines
recipes
recipe_skill_lines
recipe_outputs
```

Key boundaries:

- `recipes.recipe_id == recipes.crafting_spell_id`, but `recipes` remains a separate entity/table;
- `recipe_skill_lines` preserves native `SkillLineAbility.id` and `req_skill_value`;
- `recipe_outputs` preserves each `CREATE_ITEM` `effect_index` independently;
- every output keeps `native_item_id`; nullable `item_id` is set only when a canonical `items` row
  already exists;
- no fixed output quantity is materialized in this task; raw spell-effect quantity inputs remain
  provenance attributes;
- exact reviewed DBC shapes are required: Spell `176/704` (Tortoise reference) or `173/692`
  (standard Vanilla 1.12 and observed current Octo client), SkillLine `22/88`, SkillLineAbility
  `15/60`; every other shape fails closed;
- source revision is a deterministic SHA-256 over the exact three DBC files;
- real-Octo `SkillLineAbility` may contain cross-file skill-line references absent from
  `SkillLine.dbc`; non-recipe orphans are reported as source anomalies, while any recipe-qualified
  orphan remains fail-closed and no placeholder skill-line identity is fabricated;
- managed P4 selection policy does not overwrite a canonical selection carrying another policy;
- no destructive cross-revision absence reconciliation is performed in this first bounded slice.

### Coding-conversation Level-1 result

The original focused P4-T02 suite passed 7/7 before the real-Octo layout discovery. The revised
suite first added a standard-Vanilla `173/692` projection test. A subsequent local run exposed
`SkillLineAbility` row 5644 -> missing skill line 763, so two more focused tests now distinguish
non-recipe source orphans from fatal recipe-qualified orphans. The final focused suite contains 11 tests and passed locally on 2026-08-26.

Covered behaviors include explicit-layout fail-closed parsing, deterministic revision, fresh
migration 11, native rank identity, two skill lines, multi-output recipe slots, non-recipe rejection,
unresolved item output reporting, same-input canonical idempotence, FK/integrity and foreign/custom
selection protection.

Compilation passed for the changed Python/test/script files. A synthetic migration-10 validation DB
plus the tracked WDBC fixture also passed the task validator with:

```text
status=ok
schema_version=11
recipe_count=2
represented_skill_line_count=2
output_count=3
unresolved_output_count=1
second_import.rows_inserted=0
second_import.rows_updated=0
```

Human integration gates passed on 2026-08-26: editable dev install, full repository pytest after
migration-11 expectation alignment, `ruff check src tests`, `compileall src tests`, script Ruff/
compile checks, and the final focused P4-T02 suite (`11 passed`). Early Level-2 failures were
fail-closed source-contract discoveries and did not mutate the protected canonical DB.

- Local Level-2 source-shape evidence also showed `SkillLineAbility` rows can reference spell IDs absent from the same `Spell.dbc` revision (observed row 6090 -> spell 46530). P4-T02 reports such rows as non-recipe source anomalies and never fabricates a spell identity; only memberships backed by an actual loaded spell can participate in recipe qualification.

## P4-T02 closeout evidence

Human/full-data validation and guarded promotion completed successfully on 2026-08-26.

Validated Octo DBC source revision:

```text
sha256:f82d41ddbb77f5958d36b2483786c819de512128ef736142c758469718f7274d
```

Validated real-source layouts/counts:

```text
Spell.dbc             173 fields / 692 bytes / 28001 records
SkillLine.dbc          22 fields /  88 bytes /   136 records
SkillLineAbility.dbc   15 fields /  60 bytes /  6795 records
```

Canonical P4-T02 counts/invariants:

```text
schema_version                         = 11
recipe_count                           = 1739
represented_skill_line_count           = 15
output_count                           = 1739
unresolved_output_count                = 114
orphan_spell_skill_line_ability_count  = 1
orphan_skill_line_ability_count        = 5
second_import.rows_inserted             = 0
second_import.rows_updated              = 0
foreign_key_check                       = []
integrity_check                         = ok
```

Audited source anomalies remain explicit rather than fabricated:

```text
missing spell targets:      [46530]
missing skill-line targets: [549, 761, 763]
recipe-qualified missing skill-line memberships: 0
```

The non-destructive Level-2 run passed, including a promotion simulation, before the guarded real
canonical promotion. The final promotion then verified schema 11, the same source revision/counts,
idempotence, FK/integrity, and the byte-identical D-029 migration-10 rollback.

## Next bounded task

Route normal development to **P4-T03 — recipe reagents and quantities**. Keep recipe learning /
acquisition sources as a later separate bounded task rather than combining both dimensions. P4-T03
should begin by inspecting primary spell/reagent source semantics and current project decisions before
choosing schema/import authority.

## Next-conversation guard

Before starting P4-T03, verify GitHub `main` contains the complete P4-T02 implementation and closeout
delta based on commit `c4265d3a75599371976c453d189e258f1af858ee`. In particular, confirm
migration 11, the final `octo-dbc-recipes/4` importer, focused tests/fixtures, and this validated
project-memory state are present.

If GitHub still shows P4-T02 as awaiting validation or lacks any stacked hotfix applied during the
Level-2 loop, stop and reconcile/push the complete local P4-T02 working tree before beginning P4-T03.
