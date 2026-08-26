# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must verify the actual current head before editing.

## Integration baseline for this handoff

P4-T04 was implemented from GitHub `main` commit:

```text
9061569db2e6862516dae268540dc83bf0a1d91a
```

Commit title:

```text
Validate P4-T03 recipe reagents import and canonical migration 12
```

That commit contains the complete validated P4-T03 closeout. The P4-T04 implementation/continuation
delta was applied locally on top of that baseline and has now passed Level-2 validation plus canonical
promotion. This closeout delta is intentionally stacked on that not-yet-pushed local P4-T04 state.

## Validated cumulative state

P0 through **P4-T04** are `VALIDATED`. P4 is closed.

The cumulative local canonical database is:

```text
data/generated/octogamedb.sqlite3
```

validated through:

```text
P4-T04 / migration 13 / 0013_recipe_acquisition_sources.sql
```

Current validated canonical SHA-256:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

The D-029 one-step rollback is now the exact migration-12 canonical:

```text
data/generated/octogamedb_bak.sqlite3
sha256:6f9d9c44593225a67576df3be8caa06cbf157fbfb19233b9a932a83612ae5261
```

P4-T04 Level-2 validation and guarded canonical promotion completed successfully on 2026-08-26.

## Durable P4 baseline

P4-T01 through P4-T03 remain documented in:

```text
docs/project/tasks/P4-T01.md
docs/project/tasks/P4-T02.md
docs/project/tasks/P4-T03.md
```

D-034 remains the recipe-identity contract:

- native `Spell.Id` remains spell identity;
- recipe identity is a separate entity anchored to a proven crafting spell;
- recipe qualification requires profession/skill-line membership plus `CREATE_ITEM` evidence;
- recipe outputs and reagent slots retain native slot/order and IDs;
- teaching items/trainers/quests are acquisition sources, not recipe identity;
- no recipe/item/spell identity may be fabricated from display-name or convenient-ID coincidence.

Validated P4-T02/P4-T03 Octo DBC revision:

```text
sha256:f82d41ddbb77f5958d36b2483786c819de512128ef736142c758469718f7274d
```

Validated layouts/counts:

```text
Spell.dbc             173 fields / 692 bytes / 28001 records
SkillLine.dbc          22 fields /  88 bytes /   136 records
SkillLineAbility.dbc   15 fields /  60 bytes /  6795 records
```

Validated migration-12 invariants remain:

```text
recipe_count                   = 1739
recipe_reagent_count           = 5801
recipes_with_reagents          = 1721
unresolved_reagent_count       = 85
zero_quantity_reagent_count    = 0
ignored_negative_reagent_slots = 0
second_import.rows_inserted    = 0
second_import.rows_updated     = 0
foreign_key_check              = []
integrity_check                = ok
```

## Active task

### P5 — resolution, auditing and coverage

**Status: READY_FOR_IMPLEMENTATION.**

P4-T04 is fully validated and P5 is now unblocked. Before implementing new scope, the next coding
conversation must inspect the current `main` after this closeout is committed/pushed and define the
first bounded P5 task from the roadmap rather than reopening P4-T04.

## P4-T04 closeout evidence

Validated source revisions:

```text
Octo DBC: sha256:f82d41ddbb77f5958d36b2483786c819de512128ef736142c758469718f7274d
Tortoise: 61a8269151721f6467eddb05e7bed37704d0fc0b
Tortoise bounded SQL manifest: 12b7c285b025d228768f0954a12a803a73cf6326d96a71e271308d3baac010b4
```

Validated migration-13 materialization:

```text
recipe_count                         = 1739
teaching_item_count                  = 1065
trainer_source_count                 = 6376
direct_trainer_source_count          = 5834
template_trainer_source_count        = 542
quest_learning_source_count          = 16
dbc_proven_acquisition_count         = 7457
server_fallback_acquisition_count     = 0
unresolved_teaching_item_count       = 28
unresolved_trainer_count             = 737
unresolved_quest_learning_count      = 0
second_import.rows_inserted           = 0
second_import.rows_updated            = 0
foreign_key_check                     = []
integrity_check                       = ok
```

The unresolved item/trainer identities remain explicit native-ID provenance with nullable canonical
foreign keys. They were reviewed as discovery/coverage diagnostics, not fabricated identities or
import failures. No trainer-template ID remained unmapped and no quest-learning source remained
unresolved. All 7,457 materialized acquisition relations selected exact Octo DBC `LEARN_SPELL` proof;
the D-035 Tortoise fallback remained available but was not needed for the validated data.

## Next action

Commit and push this P4-T04 closeout on top of the already-applied P4-T04 implementation delta. The
next conversation may then begin P5 planning/implementation from the updated `main`.

## Next-conversation guard

Do not treat GitHub `main` as containing P4-T04 until the human has committed and pushed the stacked
implementation plus this closeout delta. Once pushed, the expected validated local baseline is
migration 13 with SHA-256:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```
