# Current State

This file is the permanent task router. GitHub `main` is the validated source of truth for tracked
project state; every new coding conversation must verify the actual current head before editing.

## Integration baseline for this handoff

P4-T01 was prepared from GitHub `main` commit:

```text
7ed632296ffdfbb6ee677d1a10812579c6b90b1c
```

Commit title:

```text
Validate P3-T05 quest item facts and advance canonical DB to migration 10
```

The P4-T01 implementation handoff and this validation closeout both ultimately derive from that
commit. This closeout delta is intentionally small and assumes the P4-T01 implementation handoff is
already applied to the local worktree, as proven by the successful local validation run. Apply/push
the implementation handoff and this closeout together before starting P4-T02.

## Validated cumulative state

P0 through P4-T01 are `VALIDATED` in project state. The cumulative canonical database itself remains
at P3-T05 / migration 10 because P4-T01 is a source/identity-contract task with no migration. The
cumulative local canonical database remains:

```text
data/generated/octogamedb.sqlite3
```

validated through:

```text
0010_quest_item_facts.sql
```

The D-029 one-step rollback file remains:

```text
data/generated/octogamedb_bak.sqlite3
```

The migration-10 canonical state was previously validated with FK/integrity success. P4-T01 does not
add a migration and does not mutate either generated database.

Durable P3-T05 source/selection policy remains D-033. The detailed P3-T05 implementation, source
hashes, unresolved-target counts and validation record live in:

```text
docs/project/tasks/P3-T05.md
```

## P4-T01 — validated spell/recipe source and identity contract

### Status

```text
VALIDATED
```

Detailed closeout:

```text
docs/project/tasks/P4-T01.md
```

P4-T01 establishes D-034 and a tracked source-shaped proof without changing the canonical schema.
The durable contract is:

- native `Spell.Id` remains the spell identity; rank/name similarity does not merge spell rows;
- a recipe is a separate entity whose durable native key is anchored to a proven crafting spell ID;
- recipe qualification requires profession/skill-line membership plus `CREATE_ITEM` evidence;
- `SkillLineAbility.req_skill_value` is the recipe/trade-skill requirement and is distinct from
  trainer `reqskill`, `reqskillvalue`, `reqlevel`;
- teaching items and trainer rows are acquisition sources that may reference intermediary spells;
- only a proven `LEARN_SPELL` effect resolves an acquisition spell to the learned/crafting spell;
- effect and item-spell slot/order are provenance-bearing facts and must not be flattened;
- multiple outputs/variable effect quantities remain structurally possible;
- a recipe does not require a recipe item.

Primary semantic evidence is pinned Tortoise revision:

```text
Penqle/tortoise-wow
61a8269151721f6467eddb05e7bed37704d0fc0b
```

Tracked proof:

```text
tests/fixtures/p4_t01/source_contract.json
sha256:cf4661faa4e9f8f7ba7d4f38f2dea1175a02eb4f8236638b7b3704da9b59cf14
```

Level-1 focused tests passed 7/7 plus Python compilation in the coding workspace. Human local
integration validation then completed successfully on 2026-08-26:

```text
python -m pip install -e ".[dev]"                         PASS
pytest --basetemp=.pytest_tmp                            PASS
python -m ruff check src tests                           PASS
python -m compileall -q src tests                        PASS
python -m ruff check scripts                             PASS
python -m compileall -q scripts                          PASS
python scripts/validate_p4_t01_contract.py               PASS
```

The validator returned `status = ok`, recipe IDs `[1000, 1100]` and fixture hash
`sha256:cf4661faa4e9f8f7ba7d4f38f2dea1175a02eb4f8236638b7b3704da9b59cf14`.
The validation safety gate also proved both protected generated databases byte-identical before and
after validation:

```text
data/generated/octogamedb.sqlite3
sha256:9c637ab40c2c5e3c2843e6c7d52fb5c75bbe05f57d05e2ea4d48ae7bd03b127d

data/generated/octogamedb_bak.sqlite3
sha256:3dc2a49092d108a1274e55e3052b3ba74711b5ec0f675c9ff2a201c287617443
```

No new source path or source-specific/full-data validation was required. P4-T01 is therefore
`VALIDATED`; the canonical DB remains migration 10 and was not mutated by this task.

## Active task

### P4-T02 — canonical spell / skill-line / recipe identity slice

**Status: READY_FOR_IMPLEMENTATION**

Detailed task:

```text
docs/project/tasks/P4-T02.md
```

P4-T01 is `VALIDATED`. P4-T02 is now the next active bounded implementation task. It must implement
the first canonical P4 schema/import slice under D-034, starting from the validated migration-10
canonical baseline and following D-029 for any deliberate canonical evolution.

## Next-conversation guard

Verify GitHub `main` has advanced past
`7ed632296ffdfbb6ee677d1a10812579c6b90b1c` and contains both the P4-T01 implementation handoff and
this validation closeout. If so, take `docs/project/tasks/P4-T02.md` as the active task and proceed
without re-opening P4-T01. If `main` does not contain the closeout, stop and reconcile the missing
handoff before any P4 schema work.
