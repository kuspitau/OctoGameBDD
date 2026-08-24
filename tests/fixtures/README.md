# Test fixtures

Keep only **small, representative, legally redistributable** samples here.

## Source-shaped fixtures

Importer fixtures should preserve the original source shape closely enough to exercise the real parser. Preferred properties:

- contain a few known native IDs and relations;
- include source-specific edge cases and conflicts;
- be small enough for coding agents to inspect quickly;
- contain no credentials or private user data;
- have deterministic expected-output tests.

As importers are added, use source directories such as:

- `pfquest/`
- `pfquest_octo/`
- `octodb/`
- `tortoise_sql/`
- `cmangos_sql/`
- `dbc/`
- `wdb/`

Large dumps belong under ignored local paths such as `data/raw/`.

### P1-T01 pfQuest world slice

`pfquest/world_slice/` mirrors the six-file world subset inspected in upstream pfQuest revision `104f35678ca39ab1fb78b655f815cc7016f5e0c8`:

```text
db/zones.lua
db/enUS/zones.lua
db/units.lua
db/enUS/units.lua
db/objects.lua
db/enUS/objects.lua
```

The fixture is intentionally reduced. It preserves assignment/table/field shape and representative coordinate semantics while using only the minimum records needed by deterministic tests; it is not a bundled copy of the full pfQuest database.

The P1-T01 parser supports the literal Lua table subset represented by these fixtures. Full-source ingestion requires separate compatibility validation before P6.

### P2-T01 pfQuest item/direct-loot slice

`pfquest/items_slice/` mirrors the four bounded pfQuest inputs used by P2-T01:

```text
db/items.lua
db/enUS/items.lua
db/enUS/units.lua
db/enUS/objects.lua
```

It contains project-selected synthetic IDs and only enough source-shaped structure to test:

- localized item identity;
- `U` creature-loot relations and percentage chance;
- `O` game-object-loot relations and percentage chance;
- detection/deferment of `R` reference-loot and `V` vendor memberships;
- a data row without an enUS name;
- an enUS item name without an explicit data row;
- unit/object names used to materialize relation-only loot-source templates without fake spawns.

The fixture is not a copy of the full pfQuest item database.

## Golden cases

`golden/` is reserved for small project-owned synthetic cases that verify normalized/provenance/audit semantics across sources. These are not substitutes for source-shaped parser fixtures.

Golden cases should:

- make the semantic purpose obvious from the filename/content;
- use stable native/project keys rather than depending on generated SQLite IDs in expected invariants;
- include both inputs and the invariants/results they are intended to prove;
- exercise important ambiguity/conflict cases deliberately;
- avoid timestamps or other nondeterministic values unless the behavior under test requires them.

The first case, `golden/provenance_audit_case.json`, covers a resolved scalar conflict, an unresolved relation conflict, legitimate multi-valued relations, source/batch summaries, and generic coverage counts.
