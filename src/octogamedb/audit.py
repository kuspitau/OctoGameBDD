"""Generic provenance/audit reports available before gameplay-domain schemas exist."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from octogamedb.importers.summary import import_summary_for_batch


def _json_value(value_json: str) -> Any:
    return json.loads(value_json)


def _group_observations(connection: sqlite3.Connection, group_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            so.id,
            ds.source_key,
            so.source_revision,
            so.source_record_type,
            so.raw_identifier,
            so.value_json,
            so.confidence,
            so.authority_tier
        FROM source_observations AS so
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE so.observation_group_id = ?
        ORDER BY ds.source_key, so.source_revision, so.id
        """,
        (group_id,),
    ).fetchall()

    observations: list[dict[str, Any]] = []
    for row in rows:
        batch_rows = connection.execute(
            """
            SELECT ib.id, ib.status
            FROM observation_import_batches AS oib
            JOIN import_batches AS ib ON ib.id = oib.import_batch_id
            WHERE oib.observation_id = ?
            ORDER BY ib.id
            """,
            (row["id"],),
        ).fetchall()
        observations.append(
            {
                "observation_id": int(row["id"]),
                "source_key": str(row["source_key"]),
                "source_revision": str(row["source_revision"]),
                "source_record_type": row["source_record_type"],
                "raw_identifier": row["raw_identifier"],
                "value": _json_value(str(row["value_json"])),
                "confidence": row["confidence"],
                "authority_tier": row["authority_tier"],
                "import_batches": [
                    {"batch_id": int(batch["id"]), "status": str(batch["status"])}
                    for batch in batch_rows
                ],
            }
        )
    return observations


def _group_payload(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    selection = connection.execute(
        """
        SELECT observation_id, selection_policy, selection_reason
        FROM canonical_selections
        WHERE observation_group_id = ?
        """,
        (row["id"],),
    ).fetchone()
    observations = _group_observations(connection, int(row["id"]))
    return {
        "group_id": int(row["id"]),
        "subject_kind": str(row["subject_kind"]),
        "subject_key": str(row["subject_key"]),
        "fact_key": str(row["fact_key"]),
        "fact_kind": str(row["fact_kind"]),
        "fact_instance_key": str(row["fact_instance_key"]),
        "observation_count": len(observations),
        "distinct_value_count": len(
            {
                json.dumps(item["value"], sort_keys=True, separators=(",", ":"))
                for item in observations
            }
        ),
        "canonical_selection": None
        if selection is None
        else {
            "observation_id": int(selection["observation_id"]),
            "selection_policy": selection["selection_policy"],
            "selection_reason": str(selection["selection_reason"]),
        },
        "observations": observations,
    }


def source_report(connection: sqlite3.Connection, source_key: str | None = None) -> dict[str, Any]:
    """Report registered sources and their persisted import summaries."""

    params: tuple[Any, ...] = ()
    where = ""
    if source_key is not None:
        where = "WHERE ds.source_key = ?"
        params = (source_key,)

    source_rows = connection.execute(
        f"""
        SELECT ds.id, ds.source_key, ds.display_name, ds.source_kind, ds.source_url, ds.source_path
        FROM data_sources AS ds
        {where}
        ORDER BY ds.source_key
        """,
        params,
    ).fetchall()

    sources: list[dict[str, Any]] = []
    for source in source_rows:
        batch_rows = connection.execute(
            "SELECT id FROM import_batches WHERE source_id = ? ORDER BY id",
            (source["id"],),
        ).fetchall()
        summaries = [
            import_summary_for_batch(connection, int(batch["id"])).to_dict() for batch in batch_rows
        ]
        sources.append(
            {
                "source_key": str(source["source_key"]),
                "display_name": str(source["display_name"]),
                "source_kind": str(source["source_kind"]),
                "source_url": source["source_url"],
                "source_path": source["source_path"],
                "batch_count": len(summaries),
                "batches": summaries,
            }
        )

    return {"source_count": len(sources), "sources": sources}


def trace_report(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str | None = None,
) -> dict[str, Any]:
    """Trace source evidence and canonical selection for one subject."""

    params: list[Any] = [subject_kind, str(subject_key)]
    fact_filter = ""
    if fact_key is not None:
        fact_filter = "AND fact_key = ?"
        params.append(fact_key)

    rows = connection.execute(
        f"""
        SELECT id, subject_kind, subject_key, fact_key, fact_kind, fact_instance_key
        FROM observation_groups
        WHERE subject_kind = ? AND subject_key = ? {fact_filter}
        ORDER BY fact_key, fact_instance_key, id
        """,
        tuple(params),
    ).fetchall()
    groups = [_group_payload(connection, row) for row in rows]
    return {
        "subject_kind": subject_kind,
        "subject_key": str(subject_key),
        "fact_key": fact_key,
        "group_count": len(groups),
        "groups": groups,
    }


def conflict_report(
    connection: sqlite3.Connection,
    *,
    subject_kind: str | None = None,
    subject_key: str | int | None = None,
) -> dict[str, Any]:
    """List evidence groups that currently contain competing distinct values."""

    filters: list[str] = []
    params: list[Any] = []
    if subject_kind is not None:
        filters.append("og.subject_kind = ?")
        params.append(subject_kind)
    if subject_key is not None:
        filters.append("og.subject_key = ?")
        params.append(str(subject_key))
    where = ""
    if filters:
        where = "WHERE " + " AND ".join(filters)

    rows = connection.execute(
        f"""
        SELECT og.id, og.subject_kind, og.subject_key, og.fact_key, og.fact_kind,
               og.fact_instance_key
        FROM observation_groups AS og
        JOIN source_observations AS so ON so.observation_group_id = og.id
        {where}
        GROUP BY og.id
        HAVING COUNT(DISTINCT so.value_json) > 1
        ORDER BY og.subject_kind, og.subject_key, og.fact_key, og.fact_instance_key, og.id
        """,
        tuple(params),
    ).fetchall()
    conflicts = [_group_payload(connection, row) for row in rows]
    return {
        "conflict_count": len(conflicts),
        "unresolved_conflict_count": sum(
            1 for conflict in conflicts if conflict["canonical_selection"] is None
        ),
        "conflicts": conflicts,
    }


def coverage_report(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return generic evidence coverage until domain-specific P1+ metrics exist."""

    totals = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM data_sources) AS source_count,
            (SELECT COUNT(*) FROM import_batches) AS import_batch_count,
            (SELECT COUNT(*) FROM observation_groups) AS observation_group_count,
            (SELECT COUNT(*) FROM source_observations) AS observation_count,
            (SELECT COUNT(*) FROM canonical_selections) AS canonical_selection_count,
            (
                SELECT COUNT(*) FROM (
                    SELECT subject_kind, subject_key
                    FROM observation_groups
                    GROUP BY subject_kind, subject_key
                )
            ) AS subject_count
        """
    ).fetchone()
    conflict_counts = connection.execute(
        """
        SELECT
            COUNT(*) AS conflict_count,
            COALESCE(SUM(CASE WHEN cs.observation_group_id IS NULL THEN 1 ELSE 0 END), 0)
                AS unresolved_conflict_count
        FROM (
            SELECT observation_group_id
            FROM source_observations
            GROUP BY observation_group_id
            HAVING COUNT(DISTINCT value_json) > 1
        ) AS conflict
        LEFT JOIN canonical_selections AS cs
            ON cs.observation_group_id = conflict.observation_group_id
        """
    ).fetchone()
    kind_rows = connection.execute(
        """
        SELECT
            og.subject_kind,
            COUNT(DISTINCT og.subject_key) AS subject_count,
            COUNT(DISTINCT og.id) AS observation_group_count,
            COUNT(DISTINCT so.id) AS observation_count,
            COUNT(DISTINCT cs.observation_group_id) AS canonical_selection_count,
            COUNT(DISTINCT CASE WHEN conflict.group_id IS NOT NULL THEN og.id END) AS conflict_count
        FROM observation_groups AS og
        LEFT JOIN source_observations AS so ON so.observation_group_id = og.id
        LEFT JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        LEFT JOIN (
            SELECT observation_group_id AS group_id
            FROM source_observations
            GROUP BY observation_group_id
            HAVING COUNT(DISTINCT value_json) > 1
        ) AS conflict ON conflict.group_id = og.id
        GROUP BY og.subject_kind
        ORDER BY og.subject_kind
        """
    ).fetchall()

    return {
        "scope": "generic-provenance",
        "source_count": int(totals["source_count"]),
        "import_batch_count": int(totals["import_batch_count"]),
        "subject_count": int(totals["subject_count"]),
        "observation_group_count": int(totals["observation_group_count"]),
        "observation_count": int(totals["observation_count"]),
        "canonical_selection_count": int(totals["canonical_selection_count"]),
        "conflict_count": int(conflict_counts["conflict_count"]),
        "unresolved_conflict_count": int(conflict_counts["unresolved_conflict_count"]),
        "subject_kinds": [
            {
                "subject_kind": str(row["subject_kind"]),
                "subject_count": int(row["subject_count"]),
                "observation_group_count": int(row["observation_group_count"]),
                "observation_count": int(row["observation_count"]),
                "canonical_selection_count": int(row["canonical_selection_count"]),
                "conflict_count": int(row["conflict_count"]),
            }
            for row in kind_rows
        ],
    }
