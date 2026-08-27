"""Generic provenance/audit reports available before gameplay-domain schemas exist."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from octogamedb.importers.summary import import_summary_for_batch

_UNSELECTED_CLASSIFICATIONS = (
    {
        "label": "expected_non_canonical_evidence",
        "description": (
            "Evidence intentionally retained for provenance but not canonical selection."
        ),
    },
    {
        "label": "effective_view_exclusion",
        "description": "Evidence exists but the selected effective source view excludes the fact.",
    },
    {
        "label": "coverage_reconciliation_gap",
        "description": "An existing policy should cover the fact, but reconciliation missed it.",
    },
    {
        "label": "policy_gap",
        "description": "Valid evidence appears selectable, but no current policy covers the case.",
    },
    {
        "label": "unresolved",
        "description": "Available generic provenance is insufficient to assign a safer class.",
    },
)


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


def _unselected_filters(
    *,
    subject_kind: str | None,
    subject_key: str | int | None,
    fact_key: str | None,
    source_key: str | None,
) -> tuple[str, tuple[Any, ...]]:
    filters = ["cs.observation_group_id IS NULL"]
    params: list[Any] = []
    if subject_kind is not None:
        filters.append("og.subject_kind = ?")
        params.append(subject_kind)
    if subject_key is not None:
        filters.append("og.subject_key = ?")
        params.append(str(subject_key))
    if fact_key is not None:
        filters.append("og.fact_key = ?")
        params.append(fact_key)
    if source_key is not None:
        filters.append(
            """
            EXISTS (
                SELECT 1
                FROM source_observations AS source_filter_observation
                JOIN data_sources AS source_filter_source
                    ON source_filter_source.id = source_filter_observation.source_id
                WHERE source_filter_observation.observation_group_id = og.id
                  AND source_filter_source.source_key = ?
            )
            """
        )
        params.append(source_key)
    return "WHERE " + " AND ".join(filters), tuple(params)


def _unselected_candidate_cte(where: str) -> str:
    return f"""
        WITH candidate_groups AS (
            SELECT
                og.id,
                og.subject_kind,
                og.subject_key,
                og.fact_key,
                og.fact_kind,
                og.fact_instance_key,
                COUNT(so.id) AS observation_count,
                COUNT(DISTINCT so.value_json) AS distinct_value_count
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            LEFT JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            {where}
            GROUP BY og.id
            HAVING COUNT(so.id) > 0 AND COUNT(DISTINCT so.value_json) = 1
        )
    """


def _sibling_summaries(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            og.id,
            og.fact_key,
            og.fact_kind,
            og.fact_instance_key,
            COUNT(so.id) AS observation_count,
            COUNT(DISTINCT so.value_json) AS distinct_value_count,
            cs.observation_id AS selected_observation_id,
            cs.selection_policy,
            selected_source.source_key AS selected_source_key
        FROM observation_groups AS og
        LEFT JOIN source_observations AS so ON so.observation_group_id = og.id
        LEFT JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        LEFT JOIN source_observations AS selected_observation
            ON selected_observation.id = cs.observation_id
        LEFT JOIN data_sources AS selected_source
            ON selected_source.id = selected_observation.source_id
        WHERE og.subject_kind = ? AND og.subject_key = ?
        GROUP BY og.id
        ORDER BY og.fact_key, og.fact_instance_key, og.id
        """,
        (subject_kind, subject_key),
    ).fetchall()

    siblings: list[dict[str, Any]] = []
    for row in rows:
        observation_count = int(row["observation_count"])
        distinct_value_count = int(row["distinct_value_count"])
        selected = row["selected_observation_id"] is not None
        if selected:
            state = "selected"
        elif observation_count == 0:
            state = "empty_unselected"
        elif distinct_value_count > 1:
            state = "conflict_unselected"
        else:
            state = "single_value_unselected"
        siblings.append(
            {
                "group_id": int(row["id"]),
                "fact_key": str(row["fact_key"]),
                "fact_kind": str(row["fact_kind"]),
                "fact_instance_key": str(row["fact_instance_key"]),
                "observation_count": observation_count,
                "distinct_value_count": distinct_value_count,
                "state": state,
                "selected_observation_id": None
                if row["selected_observation_id"] is None
                else int(row["selected_observation_id"]),
                "selection_policy": row["selection_policy"],
                "selected_source_key": row["selected_source_key"],
            }
        )
    return siblings


def _unselected_group_payload(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    payload = _group_payload(connection, row)
    siblings = _sibling_summaries(
        connection,
        subject_kind=str(row["subject_kind"]),
        subject_key=str(row["subject_key"]),
    )
    observations = payload["observations"]
    selected_siblings = [item for item in siblings if item["state"] == "selected"]
    single_value_siblings = [
        item for item in siblings if item["state"] == "single_value_unselected"
    ]
    conflict_siblings = [item for item in siblings if item["state"] == "conflict_unselected"]
    source_revisions = sorted(
        {
            (observation["source_key"], observation["source_revision"])
            for observation in observations
        }
    )
    batch_statuses = sorted(
        {
            batch["status"]
            for observation in observations
            for batch in observation["import_batches"]
        }
    )

    payload["sole_value"] = observations[0]["value"] if observations else None
    payload["classification"] = {
        "label": "unresolved",
        "reason": (
            "Generic provenance alone does not establish whether the missing selection is "
            "intentional, an effective-view exclusion, a reconciliation gap, or a policy gap."
        ),
    }
    payload["classification_evidence"] = {
        "source_keys": sorted({observation["source_key"] for observation in observations}),
        "source_revisions": [
            {"source_key": source_key, "source_revision": source_revision}
            for source_key, source_revision in source_revisions
        ],
        "batch_statuses": batch_statuses,
        "selected_sibling_count": len(selected_siblings),
        "single_value_unselected_sibling_count": len(single_value_siblings),
        "conflict_unselected_sibling_count": len(conflict_siblings),
        "selected_sibling_policies": sorted(
            {
                sibling["selection_policy"]
                for sibling in selected_siblings
                if sibling["selection_policy"] is not None
            }
        ),
        "selected_sibling_sources": sorted(
            {
                sibling["selected_source_key"]
                for sibling in selected_siblings
                if sibling["selected_source_key"] is not None
            }
        ),
    }
    payload["siblings"] = siblings
    return payload


def unselected_report(
    connection: sqlite3.Connection,
    *,
    subject_kind: str | None = None,
    subject_key: str | int | None = None,
    fact_key: str | None = None,
    source_key: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Audit unselected single-value evidence groups without choosing canonical winners."""

    if limit < 0:
        raise ValueError("limit must be non-negative")

    where, params = _unselected_filters(
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        source_key=source_key,
    )
    cte = _unselected_candidate_cte(where)
    evidence_rows = connection.execute(
        cte
        + """
        SELECT
            cg.*,
            ds.source_key,
            so.source_revision,
            so.id AS source_observation_id,
            ib.id AS import_batch_id,
            ib.status AS import_batch_status
        FROM candidate_groups AS cg
        JOIN source_observations AS so ON so.observation_group_id = cg.id
        JOIN data_sources AS ds ON ds.id = so.source_id
        LEFT JOIN observation_import_batches AS oib ON oib.observation_id = so.id
        LEFT JOIN import_batches AS ib ON ib.id = oib.import_batch_id
        ORDER BY
            cg.subject_kind, cg.subject_key, cg.fact_key, cg.fact_instance_key, cg.id,
            ds.source_key, so.source_revision, so.id, ib.id
        """,
        params,
    ).fetchall()

    candidate_rows: list[sqlite3.Row] = []
    seen_group_ids: set[int] = set()
    source_sets: dict[str, dict[str, set[int]]] = {}
    revision_sets: dict[tuple[str, str], dict[str, set[int]]] = {}
    fact_source_sets: dict[tuple[str, str, str, str], dict[str, set[int]]] = {}
    batch_sets: dict[tuple[str, str, str], dict[str, set[int]]] = {}

    for row in evidence_rows:
        group_id = int(row["id"])
        observation_id = int(row["source_observation_id"])
        current_source = str(row["source_key"])
        revision = str(row["source_revision"])
        if group_id not in seen_group_ids:
            seen_group_ids.add(group_id)
            candidate_rows.append(row)

        source_counter = source_sets.setdefault(
            current_source, {"groups": set(), "observations": set()}
        )
        source_counter["groups"].add(group_id)
        source_counter["observations"].add(observation_id)

        revision_counter = revision_sets.setdefault(
            (current_source, revision), {"groups": set(), "observations": set()}
        )
        revision_counter["groups"].add(group_id)
        revision_counter["observations"].add(observation_id)

        fact_source_key = (
            str(row["subject_kind"]),
            str(row["fact_key"]),
            str(row["fact_kind"]),
            current_source,
        )
        fact_source_counter = fact_source_sets.setdefault(
            fact_source_key, {"groups": set(), "observations": set()}
        )
        fact_source_counter["groups"].add(group_id)
        fact_source_counter["observations"].add(observation_id)

        if row["import_batch_id"] is not None:
            status = str(row["import_batch_status"])
            batch_key = (current_source, revision, status)
            batch_counter = batch_sets.setdefault(
                batch_key,
                {"groups": set(), "observations": set(), "batches": set()},
            )
            batch_counter["groups"].add(group_id)
            batch_counter["observations"].add(observation_id)
            batch_counter["batches"].add(int(row["import_batch_id"]))

    family_counts: dict[tuple[str, str, str], int] = {}
    subject_rows: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in candidate_rows:
        family_key = (str(row["subject_kind"]), str(row["fact_key"]), str(row["fact_kind"]))
        family_counts[family_key] = family_counts.get(family_key, 0) + 1
        subject_key_pair = (str(row["subject_kind"]), str(row["subject_key"]))
        subject_rows.setdefault(subject_key_pair, []).append(row)

    subject_kind_counts: dict[str, dict[str, int]] = {}
    for (kind, _key), rows in subject_rows.items():
        counts = subject_kind_counts.setdefault(kind, {"subject_count": 0, "group_count": 0})
        counts["subject_count"] += 1
        counts["group_count"] += len(rows)

    pattern_counts: dict[tuple[str, tuple[str, ...]], dict[str, int]] = {}
    for (kind, _key), rows in subject_rows.items():
        fact_keys = tuple(sorted({str(row["fact_key"]) for row in rows}))
        counts = pattern_counts.setdefault(
            (kind, fact_keys),
            {"subject_count": 0, "group_count": 0},
        )
        counts["subject_count"] += 1
        counts["group_count"] += len(rows)

    detailed_rows = candidate_rows[:limit] if limit else []
    groups = [_unselected_group_payload(connection, row) for row in detailed_rows]

    return {
        "scope": "unselected-single-value",
        "filters": {
            "subject_kind": subject_kind,
            "subject_key": None if subject_key is None else str(subject_key),
            "fact_key": fact_key,
            "source_key": source_key,
        },
        "classification_classes": list(_UNSELECTED_CLASSIFICATIONS),
        "classification_counts": {"unresolved": len(candidate_rows)},
        "group_count": len(candidate_rows),
        "returned_group_count": len(groups),
        "detail_limit": limit,
        "details_truncated": len(groups) < len(candidate_rows),
        "subject_kinds": [
            {
                "subject_kind": kind,
                "subject_count": subject_kind_counts[kind]["subject_count"],
                "group_count": subject_kind_counts[kind]["group_count"],
            }
            for kind in sorted(subject_kind_counts)
        ],
        "fact_families": [
            {
                "subject_kind": key[0],
                "fact_key": key[1],
                "fact_kind": key[2],
                "group_count": family_counts[key],
            }
            for key in sorted(family_counts)
        ],
        "sources": [
            {
                "source_key": key,
                "group_count": len(source_sets[key]["groups"]),
                "observation_count": len(source_sets[key]["observations"]),
            }
            for key in sorted(source_sets)
        ],
        "source_revisions": [
            {
                "source_key": key[0],
                "source_revision": key[1],
                "group_count": len(revision_sets[key]["groups"]),
                "observation_count": len(revision_sets[key]["observations"]),
            }
            for key in sorted(revision_sets)
        ],
        "fact_sources": [
            {
                "subject_kind": key[0],
                "fact_key": key[1],
                "fact_kind": key[2],
                "source_key": key[3],
                "group_count": len(fact_source_sets[key]["groups"]),
                "observation_count": len(fact_source_sets[key]["observations"]),
            }
            for key in sorted(fact_source_sets)
        ],
        "import_batch_statuses": [
            {
                "source_key": key[0],
                "source_revision": key[1],
                "status": key[2],
                "group_count": len(batch_sets[key]["groups"]),
                "observation_count": len(batch_sets[key]["observations"]),
                "import_batch_count": len(batch_sets[key]["batches"]),
            }
            for key in sorted(batch_sets)
        ],
        "subject_fact_patterns": [
            {
                "subject_kind": key[0],
                "fact_keys": list(key[1]),
                "subject_count": pattern_counts[key]["subject_count"],
                "group_count": pattern_counts[key]["group_count"],
            }
            for key in sorted(pattern_counts)
        ],
        "groups": groups,
    }


def resolution_report(
    connection: sqlite3.Connection,
    *,
    subject_kind: str | None = None,
    fact_key: str | None = None,
) -> dict[str, Any]:
    """Summarize canonical selection coverage without changing resolution policy."""

    filters: list[str] = []
    params: list[Any] = []
    if subject_kind is not None:
        filters.append("og.subject_kind = ?")
        params.append(subject_kind)
    if fact_key is not None:
        filters.append("og.fact_key = ?")
        params.append(fact_key)
    where = ""
    if filters:
        where = "WHERE " + " AND ".join(filters)

    rows = connection.execute(
        f"""
        SELECT
            og.id,
            og.subject_kind,
            og.fact_key,
            og.fact_kind,
            COUNT(so.id) AS observation_count,
            COUNT(DISTINCT so.value_json) AS distinct_value_count,
            cs.observation_id AS selected_observation_id,
            cs.selection_policy,
            selected_source.source_key AS selected_source_key
        FROM observation_groups AS og
        LEFT JOIN source_observations AS so ON so.observation_group_id = og.id
        LEFT JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        LEFT JOIN source_observations AS selected_observation
            ON selected_observation.id = cs.observation_id
        LEFT JOIN data_sources AS selected_source
            ON selected_source.id = selected_observation.source_id
        {where}
        GROUP BY og.id
        ORDER BY og.subject_kind, og.fact_key, og.fact_kind, og.id
        """,
        tuple(params),
    ).fetchall()

    totals = {
        "observation_group_count": 0,
        "selected_group_count": 0,
        "unselected_group_count": 0,
        "empty_observation_group_count": 0,
        "conflict_group_count": 0,
        "resolved_conflict_group_count": 0,
        "unresolved_conflict_group_count": 0,
        "unselected_single_value_group_count": 0,
    }
    policy_counts: dict[str | None, dict[str, int]] = {}
    source_counts: dict[str, dict[str, int]] = {}
    family_counts: dict[tuple[str, str, str], dict[str, int | str]] = {}

    for row in rows:
        selected = row["selected_observation_id"] is not None
        distinct_value_count = int(row["distinct_value_count"])
        conflict = distinct_value_count > 1
        empty = int(row["observation_count"]) == 0
        unselected_single_value = not selected and distinct_value_count == 1

        totals["observation_group_count"] += 1
        totals["selected_group_count" if selected else "unselected_group_count"] += 1
        if empty:
            totals["empty_observation_group_count"] += 1
        if conflict:
            totals["conflict_group_count"] += 1
            totals[
                "resolved_conflict_group_count" if selected else "unresolved_conflict_group_count"
            ] += 1
        if unselected_single_value:
            totals["unselected_single_value_group_count"] += 1

        family_key = (str(row["subject_kind"]), str(row["fact_key"]), str(row["fact_kind"]))
        family = family_counts.setdefault(
            family_key,
            {
                "subject_kind": family_key[0],
                "fact_key": family_key[1],
                "fact_kind": family_key[2],
                "observation_group_count": 0,
                "selected_group_count": 0,
                "unselected_group_count": 0,
                "empty_observation_group_count": 0,
                "conflict_group_count": 0,
                "resolved_conflict_group_count": 0,
                "unresolved_conflict_group_count": 0,
                "unselected_single_value_group_count": 0,
            },
        )
        family["observation_group_count"] = int(family["observation_group_count"]) + 1
        selected_key = "selected_group_count" if selected else "unselected_group_count"
        family[selected_key] = int(family[selected_key]) + 1
        if empty:
            family["empty_observation_group_count"] = (
                int(family["empty_observation_group_count"]) + 1
            )
        if conflict:
            family["conflict_group_count"] = int(family["conflict_group_count"]) + 1
            conflict_key = (
                "resolved_conflict_group_count" if selected else "unresolved_conflict_group_count"
            )
            family[conflict_key] = int(family[conflict_key]) + 1
        if unselected_single_value:
            family["unselected_single_value_group_count"] = (
                int(family["unselected_single_value_group_count"]) + 1
            )

        if selected:
            policy = row["selection_policy"]
            policy_counter = policy_counts.setdefault(
                policy,
                {"selected_group_count": 0, "conflict_group_count": 0},
            )
            policy_counter["selected_group_count"] += 1
            if conflict:
                policy_counter["conflict_group_count"] += 1

            source_key = str(row["selected_source_key"])
            source_counter = source_counts.setdefault(
                source_key,
                {"selected_group_count": 0, "conflict_group_count": 0},
            )
            source_counter["selected_group_count"] += 1
            if conflict:
                source_counter["conflict_group_count"] += 1

    selection_policies = [
        {
            "selection_policy": policy,
            "selected_group_count": counts["selected_group_count"],
            "conflict_group_count": counts["conflict_group_count"],
        }
        for policy, counts in sorted(
            policy_counts.items(), key=lambda item: "" if item[0] is None else item[0]
        )
    ]
    selected_sources = [
        {
            "source_key": source_key,
            "selected_group_count": counts["selected_group_count"],
            "conflict_group_count": counts["conflict_group_count"],
        }
        for source_key, counts in sorted(source_counts.items())
    ]

    return {
        "scope": "provenance-resolution",
        "subject_kind": subject_kind,
        "fact_key": fact_key,
        **totals,
        "selection_policies": selection_policies,
        "selected_sources": selected_sources,
        "fact_families": [family_counts[key] for key in sorted(family_counts)],
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
