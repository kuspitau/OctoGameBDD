CREATE TABLE data_sources (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE CHECK (length(trim(source_key)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    source_kind TEXT NOT NULL CHECK (length(trim(source_kind)) > 0),
    source_url TEXT,
    source_path TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE import_batches (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
    source_revision TEXT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    importer_version TEXT,
    rows_read INTEGER NOT NULL DEFAULT 0 CHECK (rows_read >= 0),
    rows_accepted INTEGER NOT NULL DEFAULT 0 CHECK (rows_accepted >= 0),
    rows_skipped INTEGER NOT NULL DEFAULT 0 CHECK (rows_skipped >= 0),
    rows_inserted INTEGER NOT NULL DEFAULT 0 CHECK (rows_inserted >= 0),
    rows_updated INTEGER NOT NULL DEFAULT 0 CHECK (rows_updated >= 0),
    warning_count INTEGER NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
    error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    details_json TEXT,
    CHECK (rows_accepted + rows_skipped <= rows_read),
    CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status IN ('succeeded', 'failed') AND finished_at IS NOT NULL)
    )
);

CREATE INDEX idx_import_batches_source_id ON import_batches(source_id);
CREATE INDEX idx_import_batches_status ON import_batches(status);
