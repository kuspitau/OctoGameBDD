# Current State

## Repository state

GitHub `main` is the source-of-truth base for the current local handoff:

- branch: `main`
- base commit before P2-T01 local changes: `582810dfe6ae41e4eec9af303d6f98a772830ef8`
- base commit message: `Implement P1-T04 overlay reconciliation and pfQuest compatibility fix`

P2-T01 has been implemented and validated against the user's full local pfQuest/Turtle data.
The local P2-T01 delta must be committed and pushed before a new coding conversation starts.

**P2-T01 status:** `VALIDATED`

## Current milestone

**P2 — Items and acquisition**

## Current task after the P2-T01 push

**P2-T02 — pfQuest reference-loot resolution**

Detailed task specification:

- `docs/project/tasks/P2-T02.md`

The next conversation must first confirm that the P2-T01 commit is present on GitHub `main`, then
implement P2-T02 from that task file. It must not redo P2-T01 and must not jump to full P6 ingestion.

## P2-T01 validated result

P2-T01 establishes the first end-to-end item/acquisition path:

- migration 4 adds canonical `items`, `creature_loot`, and `gameobject_loot`;
- pfQuest item identity and direct `U`/`O` loot relations are imported with provenance;
- direct drop chances are preserved as percentages;
- geography is derived through canonical P1 templates/spawns/zones/maps;
- direct-loot targets missing from the static P1 materialization may be retained as named
  relation-only templates when pfQuest supplies their identity, without inventing spawns;
- repeated same-revision import is idempotent;
- reference-loot (`R`) and vendor (`V`) relations remain intentionally deferred.

Full-data validation revisions:

```text
base_revision   sha256:5087d2d0a5b1c2706b7fc7ccb5ffd447c91aa24d91a23f102f2c7ac1d7440147
turtle_revision sha256:7fd719cac7a7a26e80c6865fa62b6100ccfa2301dabe3b2a399c0f1551372d8c
item_revision   sha256:e645f75f9c6fe8bca86b3ddb3c4dfde76a167f89f3d344d5937bf0e4b98dfd11
```

Observed full-data counts:

- pfQuest base world rows accepted: `19,899`;
- Turtle effective-world rows accepted: `26,637`;
- items accepted: `17,712`;
- direct creature-loot links: `198,811`;
- direct game-object-loot links: `8,298`;
- deferred reference-loot links: `10,209`;
- deferred vendor links: `13,860`;
- relation-only creature templates: `0`;
- relation-only game-object templates: `2` (`180523`, `180671`).

The second item import of the exact same revision returned:

```text
rows_inserted = 0
rows_updated = 0
```

A real derived query also resolved item `45` (`Squire's Shirt`) through creature `5623`
(`Wastewander Assassin`) to canonical Turtle-selected spawns in Tanaris, with separate pfQuest
loot-relation provenance and pfQuest-turtle location provenance.

No foreign-key assertion failed in the Level-2 validation flow.

## Local path/config state

No new local path key is needed for P2-T02 at task start. Existing configuration remains:

```toml
[source_paths]
pfquest = "<installed pfQuest directory>"
pfquest_turtle = "<installed pfQuest-turtle directory>"
```

P2-T02 should inspect public pfQuest reference-loot semantics before deciding whether any additional
local source path is required.

## Known limitations carried forward

- item stats/effects/requirements and richer item identity are not yet imported;
- pfQuest reference-loot (`R`) is counted but not resolved;
- vendor (`V`) relations are counted but not imported;
- specialized loot and item/container loot remain deferred;
- item/Turtle/Octo overlay reconciliation is not implemented;
- item geography exists only where canonical P1 source spawns exist;
- relation-only source templates legitimately have null geography until another source supplies a
  canonical spawn.

## Next handoff rule

1. Apply this documentation-only handoff on top of the completed P2-T01 local changes.
2. Review `git diff` / `git status`.
3. Commit the entire P2-T01 change set plus this handoff documentation.
4. Push `main`.
5. Start a new conversation against the pushed `main`.
6. That conversation confirms the new commit, reads `docs/project/tasks/P2-T02.md`, and proceeds.
