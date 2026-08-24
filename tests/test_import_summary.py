from __future__ import annotations

import json

import pytest

from octogamedb.db import connect_database
from octogamedb.importers.summary import import_summary_for_batch


def test_import_summary_json_is_deterministic_and_writable(golden_audit_case, tmp_path):
    with connect_database(golden_audit_case["db_path"]) as connection:
        batch_id = int(
            connection.execute(
                """
                SELECT ib.id
                FROM import_batches AS ib
                JOIN data_sources AS ds ON ds.id = ib.source_id
                WHERE ds.source_key = 'source-a'
                """
            ).fetchone()[0]
        )
        summary = import_summary_for_batch(connection, batch_id)

    compact = summary.to_json(indent=None)
    assert json.loads(compact) == summary.to_dict()
    assert compact == summary.to_json(indent=None)

    output_path = tmp_path / "summaries" / "source-a.json"
    summary.write_json(output_path)
    assert json.loads(output_path.read_text(encoding="utf-8")) == summary.to_dict()


def test_unknown_import_batch_is_rejected(golden_audit_case):
    with (
        connect_database(golden_audit_case["db_path"]) as connection,
        pytest.raises(ValueError, match="unknown import batch"),
    ):
        import_summary_for_batch(connection, 9999)
