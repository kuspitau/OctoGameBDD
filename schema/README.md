# Schema assets

Versioned executable migrations are packaged under:

```text
src/octogamedb/db/migrations/
```

Naming convention:

```text
NNNN_descriptive_name.sql
```

where `NNNN` is a unique four-digit monotonically increasing version. The migration runner loads
these package resources in numeric order and records successful applications in
`schema_migrations`. Each migration and its recording are committed atomically.

This top-level `schema/` directory remains available for schema documentation and future
non-runtime schema assets.

The canonical schema must reflect the principles in:

- `docs/project/ARCHITECTURE.md`
- `docs/project/DATA_MODEL.md`
- `docs/project/DECISIONS.md`

Do not add gameplay tables ad hoc without updating the data model when semantics change.
