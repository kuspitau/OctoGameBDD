# Local data layout

Only this README and intentionally small samples are committed.

Recommended local layout:

```text
data/
  samples/       # tiny tracked or hand-curated samples
  raw/           # downloaded/extracted source data (ignored)
  staging/       # parsed source-shaped outputs (ignored)
  derived/       # generated derived datasets/caches (ignored)
  generated/     # canonical SQLite DB and other generated artifacts (ignored)
  downloads/     # temporary downloads (ignored)
  cache/         # HTTP/source caches (ignored)
```

Do not commit full SQL dumps, MPQ files, WDB caches, generated SQLite databases, or scraped page
archives.

## Canonical local SQLite database

The normal cumulative full-data database is:

```text
data/generated/octogamedb.sqlite3
```

It is the **canonical local data state** through the task currently recorded as validated in
`docs/project/CURRENT_STATE.md`. It is deliberately unavailable on GitHub: GitHub `main` remains the
source of truth for code/schema/docs, while this generated SQLite file is the validated local
materialization of those rules against the configured real data sources.

Before any task mutates the canonical DB, create or replace the single rollback copy:

```text
data/generated/octogamedb_bak.sqlite3
```

Exploratory/destructive validation should preferably use another dedicated copy rather than the
canonical DB. Both the canonical DB and `_bak` stay local and ignored by Git.

See `docs/project/CANONICAL_DB.md` for the complete lifecycle, rollback and rebuild rules.
