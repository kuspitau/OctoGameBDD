# OctoGameDB

**Working project name.**

OctoGameDB is an external local tool for building, auditing, querying, and later visually exploring an interconnected database of OctoWoW game data.

The data model is **not item-centric**. Items, quests, creatures, game objects, recipes, spells, zones, and maps are first-class entities connected by explicit relations. The UI may present an item-centric view, a zone-centric view, a creature-centric view, etc., without changing the underlying model.

## Core goals

- Build a canonical SQLite database from multiple Octo / Turtle / Vanilla sources.
- Preserve the provenance of imported facts and conflicting source values.
- Keep raw/staging data separate from canonical data and derived relations.
- Support rich cross-domain queries:
  - item → acquisition sources → locations;
  - zone → creatures / quests / recipes / obtainable items;
  - quest → giver / finisher / objectives / prerequisites / rewards;
  - recipe → result / reagents / learning source / availability;
  - creature / game object → spawns / loot / quest relations.
- Provide strong audit and coverage tooling before investing in the graphical UI.
- Eventually provide a local web UI with sortable/filterable grids, WoW-like item tooltips, maps, saved searches, comparisons, and weighted stat scores.

## Start here

Humans and coding agents should read, in this order:

1. [`AGENTS.md`](AGENTS.md)
2. [`docs/project/CURRENT_STATE.md`](docs/project/CURRENT_STATE.md)
3. [`docs/project/AI_GUIDELINES.md`](docs/project/AI_GUIDELINES.md)
4. The task-specific architecture/data documents referenced there.

The current/next task is always identified by:

- [`docs/project/CURRENT_STATE.md`](docs/project/CURRENT_STATE.md)

When a task needs a detailed specification, `CURRENT_STATE.md` links to its stable task file under `docs/project/tasks/`.

## Repository policy

GitHub `main` is the **validated source of truth**. Coding conversations are expected to have read-only access to GitHub, make changes in their own workspace, and return a **delta package** for human review and local full-data validation.

Large source dumps, extracted client data, generated databases, caches, and other heavy artifacts must not be committed. Only small representative fixtures belong in Git.

See [`docs/project/WORKFLOW.md`](docs/project/WORKFLOW.md).
