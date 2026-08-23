CREATE TABLE observation_groups (
    id INTEGER PRIMARY KEY,
    subject_kind TEXT NOT NULL CHECK (length(trim(subject_kind)) > 0),
    subject_key TEXT NOT NULL CHECK (length(trim(subject_key)) > 0),
    fact_key TEXT NOT NULL CHECK (length(trim(fact_key)) > 0),
    fact_kind TEXT NOT NULL CHECK (fact_kind IN ('scalar', 'relation')),
    fact_instance_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (fact_kind = 'scalar' AND fact_instance_key = '')
        OR (fact_kind = 'relation' AND length(trim(fact_instance_key)) > 0)
    ),
    UNIQUE (subject_kind, subject_key, fact_key, fact_instance_key)
);

CREATE TRIGGER trg_observation_groups_fact_kind_consistency
BEFORE INSERT ON observation_groups
WHEN EXISTS (
    SELECT 1
    FROM observation_groups
    WHERE subject_kind = NEW.subject_kind
      AND subject_key = NEW.subject_key
      AND fact_key = NEW.fact_key
      AND fact_kind <> NEW.fact_kind
)
BEGIN
    SELECT RAISE(ABORT, 'observation fact kind mismatch');
END;

CREATE TABLE source_observations (
    id INTEGER PRIMARY KEY,
    observation_group_id INTEGER NOT NULL
        REFERENCES observation_groups(id) ON DELETE RESTRICT,
    source_id INTEGER NOT NULL
        REFERENCES data_sources(id) ON DELETE RESTRICT,
    source_revision TEXT NOT NULL DEFAULT '',
    source_record_type TEXT,
    raw_identifier TEXT,
    value_json TEXT NOT NULL CHECK (length(trim(value_json)) > 0),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    authority_tier INTEGER CHECK (authority_tier IS NULL OR authority_tier >= 0),
    first_observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, observation_group_id)
);

CREATE UNIQUE INDEX uq_source_observations_identity
ON source_observations(
    observation_group_id,
    source_id,
    source_revision,
    COALESCE(source_record_type, ''),
    COALESCE(raw_identifier, ''),
    value_json
);

CREATE INDEX idx_source_observations_group_id
ON source_observations(observation_group_id);

CREATE INDEX idx_source_observations_source_id_revision
ON source_observations(source_id, source_revision);

CREATE TABLE observation_import_batches (
    observation_id INTEGER NOT NULL
        REFERENCES source_observations(id) ON DELETE RESTRICT,
    import_batch_id INTEGER NOT NULL
        REFERENCES import_batches(id) ON DELETE RESTRICT,
    linked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (observation_id, import_batch_id)
);

CREATE INDEX idx_observation_import_batches_batch_id
ON observation_import_batches(import_batch_id);

CREATE TRIGGER trg_observation_import_batch_provenance_match
BEFORE INSERT ON observation_import_batches
WHEN NOT EXISTS (
    SELECT 1
    FROM source_observations AS so
    JOIN import_batches AS ib ON ib.id = NEW.import_batch_id
    WHERE so.id = NEW.observation_id
      AND so.source_id = ib.source_id
      AND so.source_revision = COALESCE(ib.source_revision, '')
)
BEGIN
    SELECT RAISE(ABORT, 'observation/import batch provenance mismatch');
END;

CREATE TABLE canonical_selections (
    observation_group_id INTEGER PRIMARY KEY
        REFERENCES observation_groups(id) ON DELETE RESTRICT,
    observation_id INTEGER NOT NULL,
    selection_policy TEXT,
    selection_reason TEXT NOT NULL CHECK (length(trim(selection_reason)) > 0),
    selected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (observation_id, observation_group_id)
        REFERENCES source_observations(id, observation_group_id) ON DELETE RESTRICT
);

CREATE INDEX idx_canonical_selections_observation_id
ON canonical_selections(observation_id);
