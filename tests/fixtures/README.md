# Test fixtures

Keep only **small, representative, legally redistributable** source-format samples here.

Preferred fixture properties:

- preserve the original source shape;
- contain a few known IDs and relations;
- include edge cases and conflicts;
- be small enough for coding agents to inspect quickly;
- contain no credentials or private user data.

Large dumps belong under ignored local paths such as `data/raw/`.

As importers are added, create fixtures such as:

- `pfquest/`
- `pfquest_octo/`
- `octodb/`
- `tortoise_sql/`
- `cmangos_sql/`
- `dbc/`
- `wdb/`

Each importer should have deterministic expected-output tests.
