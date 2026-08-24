# Current State

## Repository state

GitHub `main` is the source-of-truth base for this validated local handoff:

- branch: `main`
- implementation base commit: `3dcc55369f821dcdc12cafa0a9ab2b2ebc7afa54`
- base commit message: `Implement and validate P2-T01 item acquisition`

The P2-T02 implementation delta has now passed both Level-1 and full local Level-2 validation.
It must be committed and pushed before the next coding conversation starts.

**P2-T02 status:** `VALIDATED`

## Current milestone

**P2 — Items and acquisition**

## Current task after the P2-T02 push

**P2-T03 — pfQuest vendor acquisition (`V`)**

Detailed task specification:

- `docs/project/tasks/P2-T03.md`

The next conversation must first confirm that the validated P2-T02 commit is present on GitHub
`main`, then implement P2-T03 from that task file. It must not redo P2-T02 and must not jump to
full P6 ingestion.

## P2-T02 validated result

Primary-source inspection remains pinned to pfQuest revision:

```text
104f35678ca39ab1fb78b655f815cc7016f5e0c8
```

Established reference-loot contract:

```text
items[item_id]["R"][reference_loot_id] = chance_percent
refloot[reference_loot_id]["U"][creature_id] = membership_marker
refloot[reference_loot_id]["O"][gameobject_id] = membership_marker
```

P2-T02 adds explicit reference identity/relations, preserves item-side chance and two-stage
provenance, and derives effective acquisition sources without flattening them into direct loot
truth.

Full local validation on 2026-08-24 confirmed:

- full repository test suite passed with the user's configured environment;
- `python -m ruff check src tests` -> `All checks passed!`;
- `python -m compileall -q src tests` -> success;
- real pfQuest `R` relations imported: `10,209`;
- resolved reference-loot links: `8,793`;
- unresolved definitions are explicitly reported as `missing_refloot_definition` with native IDs;
- same-revision second import: `rows_inserted = 0`, `rows_updated = 0`;
- `PRAGMA foreign_key_check` -> `[]`;
- a fresh P1 + Turtle + P2-T02 validation database successfully resolved a real located reference
  acquisition;
- validation item: `647`;
- validation reference-loot ID: `30082`;
- returned reference acquisition paths: `9,578`;
- located reference paths: `9,543`;
- example located member: creature `12048` (`Alliance Sentinel`) in Alterac Valley;
- item -> reference provenance groups: `3`, all with pfQuest observations;
- reference -> source-member provenance groups for reference `30082`: `336`, all with pfQuest
  observations;
- automated final check ended with `P2-T02 FINAL CHECKS PASSED`.

The example path's source-listed chance is `0.0`; P2-T02 preserves that source value verbatim and
does not reinterpret it or combine it mathematically with other paths.

## Important validation correction

The initially suggested reuse of `data/generated/octogamedb.sqlite3` was not valid on the user's
machine because that file was not the previously validated complete P1 database and did not even
contain the `maps` table.

The successful Level-2 validation therefore rebuilt a fresh validation database in the intended
order:

1. apply current migrations;
2. import the base pfQuest P1 world;
3. reconcile the configured pfQuest-turtle effective world;
4. import P2-T02 items/reference loot;
5. repeat the exact item import for idempotence;
6. validate foreign keys, real located reference acquisition, and both provenance layers.

Future validation instructions should prefer rebuilding the required bounded dependency chain when
the provenance/state of a cached generated DB is not guaranteed.

## Known limitations carried forward

- vendor (`V`) acquisition is not yet materialized and is the next bounded P2 task;
- item stats/effects/requirements and richer item identity are not yet imported;
- specialized loot and item/container loot remain deferred;
- item/Turtle/Octo overlay reconciliation is not implemented;
- reference-loot expansion follows the pinned pfQuest one-level contract and deliberately rejects a
  nested `R` inside `refloot` rather than inventing recursion semantics;
- item geography exists only where canonical P1 source spawns exist;
- relation-only source templates legitimately have null geography until another source supplies a
  canonical spawn.

## Next handoff rule

1. Apply the P2-T02 implementation delta and this validation-closeout documentation over the local
   worktree based on `3dcc55369f821dcdc12cafa0a9ab2b2ebc7afa54`.
2. Review `MANIFEST.txt`, `git diff` and `git status`.
3. The Level-2 validation is complete; do not rerun it solely to change status unless the tree is
   modified after this point.
4. Commit the full P2-T02 implementation plus validation-closeout docs and push `main`.
5. Start the next conversation from the pushed `main`.
6. That conversation confirms P2-T02 is present and `VALIDATED`, then reads
   `docs/project/tasks/P2-T03.md` and proceeds.
