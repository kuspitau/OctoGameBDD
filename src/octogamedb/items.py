"""Canonical item acquisition queries for the P2 item foundation."""

from __future__ import annotations

import sqlite3
from typing import Any


def _selected_source(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str,
    fact_key: str,
    fact_instance_key: str = "",
) -> dict[str, str] | None:
    row = connection.execute(
        """
        SELECT ds.source_key, so.source_revision
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = ?
          AND og.subject_key = ?
          AND og.fact_key = ?
          AND og.fact_instance_key = ?
        """,
        (subject_kind, subject_key, fact_key, fact_instance_key),
    ).fetchone()
    if row is None:
        return None
    return {
        "source_key": str(row["source_key"]),
        "source_revision": str(row["source_revision"]),
    }


def _location_payload(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    source_kind = str(row["source_kind"])
    spawn_key = None if row["spawn_key"] is None else str(row["spawn_key"])
    return {
        "source_kind": source_kind,
        "source_id": int(row["source_id"]),
        "source_name": str(row["source_name"]),
        "spawn_key": spawn_key,
        "coordinate_space": (
            None if row["coordinate_space"] is None else str(row["coordinate_space"])
        ),
        "x": None if row["x"] is None else float(row["x"]),
        "y": None if row["y"] is None else float(row["y"]),
        "z": None if row["z"] is None else float(row["z"]),
        "orientation": None if row["orientation"] is None else float(row["orientation"]),
        "respawn_seconds": (
            None if row["respawn_seconds"] is None else int(row["respawn_seconds"])
        ),
        "zone_id": None if row["zone_id"] is None else int(row["zone_id"]),
        "zone_name": None if row["zone_name"] is None else str(row["zone_name"]),
        "map_id": None if row["map_id"] is None else int(row["map_id"]),
        "map_name": None if row["map_name"] is None else str(row["map_name"]),
        "location_source": (
            None
            if spawn_key is None
            else _selected_source(
                connection,
                subject_kind=f"{source_kind}_spawn",
                subject_key=spawn_key,
                fact_key="position",
            )
        ),
    }


def _acquisition_path(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    item_id = int(row["item_id"])
    source_kind = str(row["source_kind"])
    source_id = int(row["source_id"])
    path_kind = str(row["path_kind"])
    reference_loot_id = (
        None if row["reference_loot_id"] is None else int(row["reference_loot_id"])
    )

    if path_kind == "direct":
        relation_source = _selected_source(
            connection,
            subject_kind="item",
            subject_key=str(item_id),
            fact_key="loot_source",
            fact_instance_key=f"{source_kind}:{source_id}",
        )
        membership_source = None
    elif path_kind == "reference" and reference_loot_id is not None:
        relation_source = _selected_source(
            connection,
            subject_kind="item",
            subject_key=str(item_id),
            fact_key="loot_reference",
            fact_instance_key=f"reference:{reference_loot_id}",
        )
        membership_source = _selected_source(
            connection,
            subject_kind="loot_reference",
            subject_key=str(reference_loot_id),
            fact_key="loot_source_member",
            fact_instance_key=f"{source_kind}:{source_id}",
        )
    else:
        raise RuntimeError("invalid item acquisition path row")

    return {
        "path_kind": path_kind,
        "chance_percent": float(row["chance_percent"]),
        "reference_loot_id": reference_loot_id,
        "relation_source": relation_source,
        "reference_membership_source": membership_source,
    }


def _query_source_rows(connection: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
            i.item_id,
            'direct' AS path_kind,
            NULL AS reference_loot_id,
            'creature' AS source_kind,
            c.creature_id AS source_id,
            c.name AS source_name,
            cl.chance_percent,
            cs.spawn_key,
            cs.coordinate_space,
            cs.x,
            cs.y,
            cs.z,
            cs.orientation,
            cs.respawn_seconds,
            z.zone_id,
            z.name AS zone_name,
            COALESCE(cs.map_id, z.map_id) AS map_id,
            m.name AS map_name
        FROM items AS i
        JOIN creature_loot AS cl ON cl.item_id = i.item_id
        JOIN creatures AS c ON c.creature_id = cl.creature_id
        LEFT JOIN creature_spawns AS cs ON cs.creature_id = c.creature_id
        LEFT JOIN zones AS z ON z.zone_id = cs.zone_id
        LEFT JOIN maps AS m ON m.map_id = COALESCE(cs.map_id, z.map_id)
        WHERE i.item_id = ?

        UNION ALL

        SELECT
            i.item_id,
            'direct' AS path_kind,
            NULL AS reference_loot_id,
            'gameobject' AS source_kind,
            g.gameobject_id AS source_id,
            g.name AS source_name,
            gl.chance_percent,
            gs.spawn_key,
            gs.coordinate_space,
            gs.x,
            gs.y,
            gs.z,
            gs.orientation,
            gs.respawn_seconds,
            z.zone_id,
            z.name AS zone_name,
            COALESCE(gs.map_id, z.map_id) AS map_id,
            m.name AS map_name
        FROM items AS i
        JOIN gameobject_loot AS gl ON gl.item_id = i.item_id
        JOIN gameobjects AS g ON g.gameobject_id = gl.gameobject_id
        LEFT JOIN gameobject_spawns AS gs ON gs.gameobject_id = g.gameobject_id
        LEFT JOIN zones AS z ON z.zone_id = gs.zone_id
        LEFT JOIN maps AS m ON m.map_id = COALESCE(gs.map_id, z.map_id)
        WHERE i.item_id = ?

        UNION ALL

        SELECT
            i.item_id,
            'reference' AS path_kind,
            irl.reference_loot_id,
            'creature' AS source_kind,
            c.creature_id AS source_id,
            c.name AS source_name,
            irl.chance_percent,
            cs.spawn_key,
            cs.coordinate_space,
            cs.x,
            cs.y,
            cs.z,
            cs.orientation,
            cs.respawn_seconds,
            z.zone_id,
            z.name AS zone_name,
            COALESCE(cs.map_id, z.map_id) AS map_id,
            m.name AS map_name
        FROM items AS i
        JOIN item_reference_loot AS irl ON irl.item_id = i.item_id
        JOIN reference_loot_creatures AS rlc
          ON rlc.reference_loot_id = irl.reference_loot_id
        JOIN creatures AS c ON c.creature_id = rlc.creature_id
        LEFT JOIN creature_spawns AS cs ON cs.creature_id = c.creature_id
        LEFT JOIN zones AS z ON z.zone_id = cs.zone_id
        LEFT JOIN maps AS m ON m.map_id = COALESCE(cs.map_id, z.map_id)
        WHERE i.item_id = ?

        UNION ALL

        SELECT
            i.item_id,
            'reference' AS path_kind,
            irl.reference_loot_id,
            'gameobject' AS source_kind,
            g.gameobject_id AS source_id,
            g.name AS source_name,
            irl.chance_percent,
            gs.spawn_key,
            gs.coordinate_space,
            gs.x,
            gs.y,
            gs.z,
            gs.orientation,
            gs.respawn_seconds,
            z.zone_id,
            z.name AS zone_name,
            COALESCE(gs.map_id, z.map_id) AS map_id,
            m.name AS map_name
        FROM items AS i
        JOIN item_reference_loot AS irl ON irl.item_id = i.item_id
        JOIN reference_loot_gameobjects AS rlg
          ON rlg.reference_loot_id = irl.reference_loot_id
        JOIN gameobjects AS g ON g.gameobject_id = rlg.gameobject_id
        LEFT JOIN gameobject_spawns AS gs ON gs.gameobject_id = g.gameobject_id
        LEFT JOIN zones AS z ON z.zone_id = gs.zone_id
        LEFT JOIN maps AS m ON m.map_id = COALESCE(gs.map_id, z.map_id)
        WHERE i.item_id = ?
        """,
        (item_id, item_id, item_id, item_id),
    ).fetchall()


def find_item_sources(
    connection: sqlite3.Connection,
    item_id: int,
) -> list[dict[str, Any]]:
    """Return one item and its direct/reference creature/game-object acquisition sources.

    Reference expansion is a derived query over explicit ``item -> reference -> source`` canonical
    relations. Direct and reference paths that reach the same source/spawn are folded into one source
    row with multiple ``acquisition_paths`` so callers do not double-count locations. No probability
    is mathematically combined: if overlapping paths carry different source-listed chances, the
    source-level ``chance_percent`` is ``None`` and each path retains its own chance.

    Geography remains derived from P1 spawn/zone/map relations. A source without a canonical spawn
    remains visible with null location fields.
    """

    item = connection.execute(
        "SELECT item_id, name FROM items WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    if item is None:
        return []

    grouped: dict[tuple[str, int, str | None], dict[str, Any]] = {}
    seen_paths: dict[tuple[str, int, str | None], set[tuple[str, int | None, float]]] = {}

    for row in _query_source_rows(connection, item_id):
        source_kind = str(row["source_kind"])
        source_id = int(row["source_id"])
        spawn_key = None if row["spawn_key"] is None else str(row["spawn_key"])
        key = (source_kind, source_id, spawn_key)
        if key not in grouped:
            grouped[key] = _location_payload(connection, row)
            grouped[key]["acquisition_paths"] = []
            seen_paths[key] = set()

        path = _acquisition_path(connection, row)
        path_identity = (
            str(path["path_kind"]),
            path["reference_loot_id"],
            float(path["chance_percent"]),
        )
        if path_identity not in seen_paths[key]:
            grouped[key]["acquisition_paths"].append(path)
            seen_paths[key].add(path_identity)

    sources = list(grouped.values())
    for source in sources:
        source["acquisition_paths"].sort(
            key=lambda path: (
                0 if path["path_kind"] == "direct" else 1,
                -1 if path["reference_loot_id"] is None else int(path["reference_loot_id"]),
                float(path["chance_percent"]),
            )
        )
        distinct_chances = sorted(
            {float(path["chance_percent"]) for path in source["acquisition_paths"]}
        )
        source["chance_percent"] = distinct_chances[0] if len(distinct_chances) == 1 else None
        source["relation_source"] = (
            None
            if not source["acquisition_paths"]
            else source["acquisition_paths"][0]["relation_source"]
        )

    sources.sort(
        key=lambda source: (
            str(source["source_kind"]),
            str(source["source_name"]).casefold(),
            int(source["source_id"]),
            "" if source["spawn_key"] is None else str(source["spawn_key"]),
        )
    )
    return [
        {
            "item_id": int(item["item_id"]),
            "item_name": str(item["name"]),
            "sources": sources,
        }
    ]
