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

## Golden cases

`golden/` is reserved for small project-owned synthetic cases that verify normalized/provenance/audit semantics across sources. These are not substitutes for source-shaped parser fixtures.

Golden cases should:

- make the semantic purpose obvious from the filename/content;
- use stable native/project keys rather than depending on generated SQLite IDs in expected invariants;
- include both inputs and the invariants/results they are intended to prove;
- exercise important ambiguity/conflict cases deliberately;
- avoid timestamps or other nondeterministic values unless the behavior under test requires them.

The first case, `golden/provenance_audit_case.json`, covers a resolved scalar conflict, an unresolved relation conflict, legitimate multi-valued relations, source/batch summaries, and generic coverage counts.
