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


def _source_payload(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    source_kind = str(row["source_kind"])
    source_id = int(row["source_id"])
    spawn_key = None if row["spawn_key"] is None else str(row["spawn_key"])
    return {
        "source_kind": source_kind,
        "source_id": source_id,
        "source_name": str(row["source_name"]),
        "chance_percent": float(row["chance_percent"]),
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
        "relation_source": _selected_source(
            connection,
            subject_kind="item",
            subject_key=str(row["item_id"]),
            fact_key="loot_source",
            fact_instance_key=f"{source_kind}:{source_id}",
        ),
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


def find_item_sources(
    connection: sqlite3.Connection,
    item_id: int,
) -> list[dict[str, Any]]:
    """Return one item and its direct creature/game-object loot sources.

    Source geography is derived from the existing P1 spawn/zone/map relations. It is not copied
    into the loot tables. A source without a canonical spawn remains visible with null location
    fields so acquisition evidence is not confused with geographic coverage.
    """

    item = connection.execute(
        "SELECT item_id, name FROM items WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    if item is None:
        return []

    rows = connection.execute(
        """
        SELECT
            i.item_id,
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
        """,
        (item_id, item_id),
    ).fetchall()

    sources = [_source_payload(connection, row) for row in rows]
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
