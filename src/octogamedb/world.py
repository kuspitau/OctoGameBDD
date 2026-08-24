"""Canonical world-location queries for the P1 world foundation."""

from __future__ import annotations

import sqlite3
from typing import Any


def _location_sources(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str,
) -> list[dict[str, str]]:
    rows = connection.execute(
        """
        SELECT ds.source_key, so.source_revision
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = ?
          AND og.subject_key = ?
          AND og.fact_key = 'position'
        ORDER BY ds.source_key, so.source_revision
        """,
        (subject_kind, subject_key),
    ).fetchall()
    return [
        {
            "source_key": str(row["source_key"]),
            "source_revision": str(row["source_revision"]),
        }
        for row in rows
    ]


def find_world_locations(
    connection: sqlite3.Connection,
    query: str,
) -> list[dict[str, Any]]:
    """Find canonical creature/game-object spawns by case-insensitive name substring.

    A spawn's directly sourced ``map_id`` takes precedence. When a zone-percent
    spawn has no direct map, the canonical map relationship of its zone is used
    as derived geographic context; the coordinate space remains unchanged.
    """

    needle = query.strip()
    if not needle:
        raise ValueError("query must not be blank")
    pattern = f"%{needle}%"

    locations: list[dict[str, Any]] = []

    creature_rows = connection.execute(
        """
        SELECT
            'creature' AS entity_kind,
            c.creature_id AS entity_id,
            c.name,
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
        FROM creatures AS c
        JOIN creature_spawns AS cs ON cs.creature_id = c.creature_id
        LEFT JOIN zones AS z ON z.zone_id = cs.zone_id
        LEFT JOIN maps AS m ON m.map_id = COALESCE(cs.map_id, z.map_id)
        WHERE c.name LIKE ? COLLATE NOCASE
        ORDER BY c.name COLLATE NOCASE, c.creature_id, cs.spawn_key
        """,
        (pattern,),
    ).fetchall()
    for row in creature_rows:
        locations.append(
            {
                "entity_kind": str(row["entity_kind"]),
                "entity_id": int(row["entity_id"]),
                "name": str(row["name"]),
                "spawn_key": str(row["spawn_key"]),
                "coordinate_space": str(row["coordinate_space"]),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "z": None if row["z"] is None else float(row["z"]),
                "orientation": (
                    None if row["orientation"] is None else float(row["orientation"])
                ),
                "respawn_seconds": (
                    None if row["respawn_seconds"] is None else int(row["respawn_seconds"])
                ),
                "zone_id": None if row["zone_id"] is None else int(row["zone_id"]),
                "zone_name": None if row["zone_name"] is None else str(row["zone_name"]),
                "map_id": None if row["map_id"] is None else int(row["map_id"]),
                "map_name": None if row["map_name"] is None else str(row["map_name"]),
                "sources": _location_sources(
                    connection,
                    subject_kind="creature_spawn",
                    subject_key=str(row["spawn_key"]),
                ),
            }
        )

    object_rows = connection.execute(
        """
        SELECT
            'gameobject' AS entity_kind,
            g.gameobject_id AS entity_id,
            g.name,
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
        FROM gameobjects AS g
        JOIN gameobject_spawns AS gs ON gs.gameobject_id = g.gameobject_id
        LEFT JOIN zones AS z ON z.zone_id = gs.zone_id
        LEFT JOIN maps AS m ON m.map_id = COALESCE(gs.map_id, z.map_id)
        WHERE g.name LIKE ? COLLATE NOCASE
        ORDER BY g.name COLLATE NOCASE, g.gameobject_id, gs.spawn_key
        """,
        (pattern,),
    ).fetchall()
    for row in object_rows:
        locations.append(
            {
                "entity_kind": str(row["entity_kind"]),
                "entity_id": int(row["entity_id"]),
                "name": str(row["name"]),
                "spawn_key": str(row["spawn_key"]),
                "coordinate_space": str(row["coordinate_space"]),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "z": None if row["z"] is None else float(row["z"]),
                "orientation": (
                    None if row["orientation"] is None else float(row["orientation"])
                ),
                "respawn_seconds": (
                    None if row["respawn_seconds"] is None else int(row["respawn_seconds"])
                ),
                "zone_id": None if row["zone_id"] is None else int(row["zone_id"]),
                "zone_name": None if row["zone_name"] is None else str(row["zone_name"]),
                "map_id": None if row["map_id"] is None else int(row["map_id"]),
                "map_name": None if row["map_name"] is None else str(row["map_name"]),
                "sources": _location_sources(
                    connection,
                    subject_kind="gameobject_spawn",
                    subject_key=str(row["spawn_key"]),
                ),
            }
        )

    locations.sort(
        key=lambda item: (
            str(item["name"]).casefold(),
            str(item["entity_kind"]),
            int(item["entity_id"]),
            str(item["spawn_key"]),
        )
    )
    return locations
