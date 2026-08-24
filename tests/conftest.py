from __future__ import annotations

import json
from pathlib import Path

import pytest

from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "golden" / "provenance_audit_case.json"


@pytest.fixture
def golden_audit_case(tmp_path):
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    db_path = tmp_path / "golden-audit.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        source_ids: dict[str, int] = {}
        batch_ids: dict[str, int] = {}
        observation_ids: dict[str, int] = {}

        for source in fixture["sources"]:
            cursor = connection.execute(
                """
                INSERT INTO data_sources(source_key, display_name, source_kind)
                VALUES (?, ?, ?)
                """,
                (source["key"], source["display_name"], source["kind"]),
            )
            source_ids[source["key"]] = int(cursor.lastrowid)

        for batch in fixture["batches"]:
            cursor = connection.execute(
                """
                INSERT INTO import_batches(
                    source_id,
                    source_revision,
                    status,
                    finished_at,
                    rows_read,
                    rows_accepted,
                    rows_inserted,
                    details_json
                )
                VALUES (?, ?, 'succeeded', '2026-08-24T00:00:00Z', ?, ?, ?, ?)
                """,
                (
                    source_ids[batch["source"]],
                    batch["revision"],
                    batch["rows_read"],
                    batch["rows_accepted"],
                    batch["rows_inserted"],
                    json.dumps(batch["details"], sort_keys=True, separators=(",", ":")),
                ),
            )
            batch_ids[batch["key"]] = int(cursor.lastrowid)

        for observation in fixture["observations"]:
            common = {
                "connection": connection,
                "subject_kind": observation["subject_kind"],
                "subject_key": observation["subject_key"],
                "fact_key": observation["fact_key"],
                "import_batch_id": batch_ids[observation["batch"]],
            }
            if observation["kind"] == "scalar":
                observation_id = record_scalar_observation(
                    **common,
                    value=observation["value"],
                    source_record_type=observation.get("source_record_type"),
                    raw_identifier=observation.get("raw_identifier"),
                )
            else:
                observation_id = record_relation_observation(
                    **common,
                    target_kind=observation["target_kind"],
                    target_key=observation["target_key"],
                    relation_instance_key=observation.get("relation_instance_key"),
                    attributes=observation.get("attributes"),
                )
            observation_ids[observation["key"]] = observation_id

        for selection in fixture["canonical"]:
            observation_id = observation_ids[selection["observation"]]
            group_id = int(
                connection.execute(
                    "SELECT observation_group_id FROM source_observations WHERE id = ?",
                    (observation_id,),
                ).fetchone()[0]
            )
            select_canonical_observation(
                connection,
                observation_group_id=group_id,
                observation_id=observation_id,
                selection_policy=selection["selection_policy"],
                selection_reason=selection["selection_reason"],
            )

    return {"db_path": db_path, "fixture": fixture}
