# Current State

## Repository state

GitHub `main` is the source-of-truth base for this validated local handoff:

- branch: `main`
- implementation base commit: `f7af9689f726faaf62ea1035bf50984740557a71`
- base commit message: `Validate P2-T02 reference loot`

The P2-T03 implementation delta has now passed both Level-1 and full local Level-2 validation.
It must be committed and pushed before the next coding conversation starts.

**P2-T03 status:** `VALIDATED`

## Current milestone

**P2 — Items and acquisition**

## Current task after the P2-T03 push

**P2-T04 — pfQuest-turtle effective item/acquisition reconciliation**

Detailed task specification:

- `docs/project/tasks/P2-T04.md`

The next conversation must first confirm that the validated P2-T03 commit is present on GitHub
`main`, then implement P2-T04 from that task file. It must not redo P2-T03 and must not jump to
full P6 ingestion or unrelated item-stat breadth.

## P2-T03 validated result

Primary-source inspection remains pinned to pfQuest revision:

```text
104f35678ca39ab1fb78b655f815cc7016f5e0c8
```

Established vendor source contract:

```text
items[item_id]["V"][vendor_creature_id] = npc_vendor.maxcount
```

The same shape is produced for `npc_vendor_template` rows after expansion to concrete creature IDs.
pfQuest browser code consumes it as a `Sold by` relation and displays the non-zero numeric value as
a count annotation. P2-T03 therefore preserves the exact value as provenance attribute `max_count`
without interpreting it as price, drop chance, restock time, or a generalized stock policy.

Migration 6 adds the explicit canonical relation:

```text
vendor_items(vendor_creature_id, item_id)
```

Vendor provenance is separate from loot/reference provenance:

```text
subject_kind      = item
fact_key          = vendor_source
fact_instance_key = creature:<vendor_creature_id>
target             = creature:<vendor_creature_id>
attributes          = {max_count: <pfQuest V value>}
```

`find_item_sources()` / `item-sources` expose `vendor` acquisition paths with
`vendor_max_count`, no drop chance, and P1-derived creature spawn/zone/map geography. A named
relation-only vendor remains valid with null geography; unidentified vendor targets fail closed.

Full local validation on 2026-08-24 confirmed:

- editable dev install completed successfully: `python -m pip install -e ".[dev]"`;
- full repository suite passed: `pytest --basetemp=.pytest_tmp` -> `67 passed`;
- `python -m ruff check src tests` -> success / no findings;
- `python -m compileall -q src tests` -> success;
- fresh bounded P1 base + active Turtle reconciliation + P2-T03 import completed successfully;
- exact pfQuest item-source revision used by the validation:
  `sha256:698789b81001aeb68206d050c66acf9dd12f601dd02817081a33207d0f213b43`;
- canonical vendor relations: `13,860`;
- importer-reported vendor links: `13,860`;
- independent pfQuest `vendor_source` provenance observations: `13,860`;
- same-revision second item import: `rows_inserted = 0`, `rows_updated = 0`;
- `PRAGMA foreign_key_check` produced `0` violations;
- real located vendor acquisition selected item `85` / vendor creature `2113`;
- returned path kind was `vendor` with `vendor_max_count = 0`, `chance_percent = null`, and selected
  pfQuest relation provenance at the exact validated item-source revision;
- automated final check ended with `P2-T03 FINAL CHECKS PASSED`.

The `max_count = 0` example is preserved verbatim and is not reinterpreted by P2-T03.

## P2-T04 routing rationale

The remaining correctness gap before widening P2 item fields is that the current P2 importer reads
the base pfQuest item view while the user's active environment also has `pfQuest-turtle`. The
reviewed Turtle addon includes item patch data and uses top-entry replacement semantics in its patch
system.

P2-T04 is therefore bounded to reconciling the **already-supported** P2 item/acquisition fact family
against the active Turtle effective item view:

- item identity/name where supplied by the relevant effective item/localization inputs;
- direct creature/game-object acquisition (`U` / `O`);
- one-level reference-loot acquisition (`R`);
- vendor acquisition (`V`).

It must not silently generalize P1 deletion/replacement policy to items. If item effective-view
replacement needs a new durable provenance/reconciliation rule, the next conversation must record an
explicit architecture decision before mutating canonical behavior.

## Known limitations carried forward

- vendor price, restock timing, faction availability and generalized economics remain deferred;
- item stats/effects/requirements and richer item identity remain deferred until after the effective
  item-view correctness problem is handled;
- item/container and specialized loot remain deferred;
- broad Octo-specific item overlay/reconciliation beyond the bounded P2-T04 source contract remains
  deferred;
- reference-loot behavior remains the pinned one-level pfQuest contract;
- acquisition geography exists only where canonical P1 source spawns exist;
- relation-only acquisition templates legitimately have null geography until another source supplies
  canonical spawn evidence.

## Next handoff rule

1. Apply this validation-closeout delta over the already-applied P2-T03 local tree.
2. Review `MANIFEST.txt`, `git diff` and `git status`.
3. The Level-2 validation is complete; do not rerun it solely to change status unless the tree is
   modified after this point.
4. Commit the full P2-T03 implementation plus validation-closeout docs and push `main`.
5. Start the next conversation from the pushed `main`.
6. That conversation confirms P2-T03 is present and `VALIDATED`, then reads
   `docs/project/tasks/P2-T04.md` and proceeds.
