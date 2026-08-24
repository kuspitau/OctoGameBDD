"""Persist P1 pfQuest overlay evidence and reconcile the active Turtle world view.

P1-T03 builds deterministic effective views in memory.  This module turns the
bounded world-view differences into durable provenance without treating source
absence as universal game non-existence.

Two facts are important here:

* ``world_presence`` means that an entity is present in one effective source
  view.  A false observation is negative source evidence, not a global delete.
* ``spawn_set`` is a complete-set observation for one template in one effective
  source view.  Selecting a new complete set lets the canonical materialization
  drop stale pfQuest-managed spawn rows while retaining their historical source
  observations.

The installed Turtle view is the active pfQuest-family view and may supersede
only default/base pfQuest selections.  Optional pfQuest-octo imports are
comparison evidence only and do not automatically change canonical rows.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import record_scalar_observation, select_canonical_observation
from octogamedb.importers.pfquest_overlay_world import (
    PFQUEST_OCTO_SOURCE_URL,
    PFQUEST_TURTLE_SOURCE_URL,
    load_pfquest_octo_world_slice,
    load_pfquest_turtle_world_slice,
)
from octogamedb.importers.pfquest_world import (
    PFQUEST_SOURCE_KEY,
    PfQuestCreature,
    PfQuestGameObject,
    PfQuestSpawn,
    PfQuestWorldSlice,
    PfQuestZone,
    load_pfquest_world_slice,
)
from octogamedb.importers.summary import ImportSummary

PFQUEST_TURTLE_SOURCE_KEY = "pfquest-turtle"
PFQUEST_OCTO_SOURCE_KEY = "pfquest-octo"
IMPORTER_VERSION = "pfquest-overlay-reconcile/1"
TURTLE_SELECTION_POLICY = "pfquest-turtle-effective-world"
BASE_SET_SELECTION_POLICY = "pfquest-base-effective-world"
WORLD_PRESENCE_FACT = "world_presence"
SPAWN_SET_FACT = "spawn_set"

_MANAGED_SOURCE_KEYS = frozenset({PFQUEST_SOURCE_KEY, PFQUEST_TURTLE_SOURCE_KEY})
_DEFAULT_BASE_POLICIES = frozenset({None, "first-observation", BASE_SET_SELECTION_POLICY})
_BASE_WORLD_FILES = (
    "db/zones.lua",
    "db/enUS/zones.lua",
    "db/units.lua",
    "db/enUS/units.lua",
    "db/objects.lua",
    "db/enUS/objects.lua",
)
_OVERLAY_WORLD_FILES = (
    "db/zones-turtle.lua",
    "db/enUS/zones-turtle.lua",
    "db/units-turtle.lua",
    "db/enUS/units-turtle.lua",
    "db/objects-turtle.lua",
    "db/enUS/objects-turtle.lua",
    "overwrites.lua",
)


@dataclass(frozen=True)
class _Selection:
    observation_id: int
    source_key: str
    selection_policy: str | None
    value: Any


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


def _content_revision(root: str | Path, relative_paths: Iterable[str]) -> str:
    """Hash an exact source-view input set, including explicitly missing files."""

    source_root = Path(root)
    digest = hashlib.sha256()
    for relative in relative_paths:
        path = source_root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(b"present\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        else:
            digest.update(b"missing\0")
    return f"sha256:{digest.hexdigest()}"


def compute_pfquest_world_revision(source_root: str | Path) -> str:
    """Return a deterministic revision for the six P1 pfQuest world files."""

    root = Path(source_root)
    missing = [relative for relative in _BASE_WORLD_FILES if not (root / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"missing required pfQuest world file: {root / missing[0]}")
    return _content_revision(root, _BASE_WORLD_FILES)


def _validate_overlay_root(source_root: str | Path) -> Path:
    root = Path(source_root)
    if not root.is_dir():
        raise FileNotFoundError(f"overlay directory not found: {root}")
    data_files = _OVERLAY_WORLD_FILES[:-1]
    if not any((root / relative).is_file() for relative in data_files):
        raise FileNotFoundError(
            f"overlay directory has no supported P1 Turtle-style data files: {root}"
        )
    return root


def compute_pfquest_overlay_revision(source_root: str | Path) -> str:
    """Return a deterministic revision for the P1 Turtle-style overlay inputs."""

    root = _validate_overlay_root(source_root)
    return _content_revision(root, _OVERLAY_WORLD_FILES)


def _ensure_source(
    connection: sqlite3.Connection,
    *,
    source_key: str,
    display_name: str,
    source_url: str,
    source_path: str,
) -> int:
    connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind, source_url, source_path)
        VALUES (?, ?, 'lua-addon-overlay', ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            display_name = excluded.display_name,
            source_kind = excluded.source_kind,
            source_url = excluded.source_url,
            source_path = excluded.source_path,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (source_key, display_name, source_url, source_path),
    )
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (source_key,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"source registration failed: {source_key}")
    return int(row["id"])


def _source_id(connection: sqlite3.Connection, source_key: str) -> int:
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (source_key,)
    ).fetchone()
    if row is None:
        raise ValueError(f"required source has not been imported: {source_key}")
    return int(row["id"])


def _require_pfquest_base_import(connection: sqlite3.Connection, revision: str) -> int:
    source_id = _source_id(connection, PFQUEST_SOURCE_KEY)
    row = connection.execute(
        """
        SELECT id
        FROM import_batches
        WHERE source_id = ?
          AND COALESCE(source_revision, '') = ?
          AND status = 'succeeded'
        ORDER BY id DESC
        LIMIT 1
        """,
        (source_id, revision),
    ).fetchone()
    if row is None:
        raise ValueError(
            "P1-T04 requires the base pfQuest world slice to be imported first "
            f"with the same revision ({revision})"
        )
    return source_id


def _create_batch(
    connection: sqlite3.Connection,
    *,
    source_id: int,
    revision: str,
    rows_read: int,
    importer_version: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO import_batches(
            source_id, source_revision, status, importer_version, rows_read
        )
        VALUES (?, ?, 'running', ?, ?)
        """,
        (source_id, revision, importer_version, rows_read),
    )
    return int(cursor.lastrowid)


def _finish_batch(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    rows_read: int,
    rows_inserted: int,
    rows_updated: int,
    details: dict[str, Any],
) -> None:
    connection.execute(
        """
        UPDATE import_batches
        SET status = 'succeeded',
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            rows_read = ?,
            rows_accepted = ?,
            rows_inserted = ?,
            rows_updated = ?,
            details_json = ?
        WHERE id = ?
        """,
        (
            rows_read,
            rows_read,
            rows_inserted,
            rows_updated,
            json.dumps(details, sort_keys=True, separators=(",", ":")),
            batch_id,
        ),
    )


def _fail_batch(connection: sqlite3.Connection, batch_id: int, exc: Exception) -> None:
    connection.execute(
        """
        UPDATE import_batches
        SET status = 'failed',
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            error_count = 1,
            details_json = ?
        WHERE id = ?
        """,
        (
            json.dumps(
                {"error": str(exc), "exception_type": type(exc).__name__},
                sort_keys=True,
                separators=(",", ":"),
            ),
            batch_id,
        ),
    )


def _selection_for_group(connection: sqlite3.Connection, group_id: int) -> _Selection | None:
    row = connection.execute(
        """
        SELECT cs.observation_id, cs.selection_policy, ds.source_key, so.value_json
        FROM canonical_selections AS cs
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE cs.observation_group_id = ?
        """,
        (group_id,),
    ).fetchone()
    if row is None:
        return None
    return _Selection(
        observation_id=int(row["observation_id"]),
        source_key=str(row["source_key"]),
        selection_policy=(
            None if row["selection_policy"] is None else str(row["selection_policy"])
        ),
        value=json.loads(str(row["value_json"])),
    )


def _group_for_observation(connection: sqlite3.Connection, observation_id: int) -> int:
    row = connection.execute(
        "SELECT observation_group_id FROM source_observations WHERE id = ?",
        (observation_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"observation {observation_id} disappeared")
    return int(row["observation_group_id"])


def _has_non_pfquest_selected_support(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str | int,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = ?
          AND og.subject_key = ?
          AND ds.source_key NOT IN (?, ?)
        LIMIT 1
        """,
        (
            subject_kind,
            str(subject_key),
            PFQUEST_SOURCE_KEY,
            PFQUEST_TURTLE_SOURCE_KEY,
        ),
    ).fetchone()
    return row is not None


def _select_if_missing(
    connection: sqlite3.Connection,
    observation_id: int,
    *,
    policy: str,
    reason: str,
) -> None:
    group_id = _group_for_observation(connection, observation_id)
    if _selection_for_group(connection, group_id) is None:
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy=policy,
            selection_reason=reason,
        )


def _record_base_scalar(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    value: Any,
    record_type: str,
) -> int:
    observation_id = record_scalar_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type=record_type,
        raw_identifier=subject_key,
    )
    _select_if_missing(
        connection,
        observation_id,
        policy=BASE_SET_SELECTION_POLICY,
        reason="Base pfQuest complete-view evidence is the initial P1 source-view selection.",
    )
    return observation_id


def _should_select_turtle(
    connection: sqlite3.Connection,
    *,
    observation_id: int,
    subject_kind: str,
    subject_key: str | int,
    negative_presence: bool,
) -> bool:
    group_id = _group_for_observation(connection, observation_id)
    current = _selection_for_group(connection, group_id)

    if negative_presence and _has_non_pfquest_selected_support(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
    ):
        return False
    if current is None:
        return True
    if current.source_key == PFQUEST_SOURCE_KEY:
        return current.selection_policy in _DEFAULT_BASE_POLICIES
    return (
        current.source_key == PFQUEST_TURTLE_SOURCE_KEY
        and current.selection_policy == TURTLE_SELECTION_POLICY
    )


def _record_overlay_scalar(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    overlay_kind: str,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    value: Any,
    record_type: str,
    raw_identifier: str | int | None = None,
    negative_presence: bool = False,
) -> int:
    observation_id = record_scalar_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type=record_type,
        raw_identifier=subject_key if raw_identifier is None else raw_identifier,
    )
    if overlay_kind != "turtle":
        return observation_id
    if _should_select_turtle(
        connection,
        observation_id=observation_id,
        subject_kind=subject_kind,
        subject_key=subject_key,
        negative_presence=negative_presence,
    ):
        group_id = _group_for_observation(connection, observation_id)
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy=TURTLE_SELECTION_POLICY,
            selection_reason=(
                "The installed pfQuest-turtle effective view supersedes default/base pfQuest "
                "evidence for this P1 world fact while preserving competing observations."
            ),
        )
    return observation_id


def _canonical_value(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    fallback: Any,
) -> Any:
    row = connection.execute(
        """
        SELECT so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        WHERE og.subject_kind = ?
          AND og.subject_key = ?
          AND og.fact_key = ?
          AND og.fact_instance_key = ''
        """,
        (subject_kind, str(subject_key), fact_key),
    ).fetchone()
    return fallback if row is None else json.loads(str(row["value_json"]))


def _spawn_key(kind: str, entity_id: int, spawn: PfQuestSpawn) -> str:
    return (
        f"{kind}:{entity_id}:zone_percent:{spawn.zone_id}:"
        f"{spawn.x:.6f}:{spawn.y:.6f}"
    )


def _spawn_payload(kind: str, entity_id: int, spawn: PfQuestSpawn) -> dict[str, Any]:
    return {
        "spawn_key": _spawn_key(kind, entity_id, spawn),
        "coordinate_space": "zone_percent",
        "zone_id": spawn.zone_id,
        "x": spawn.x,
        "y": spawn.y,
        "respawn_seconds": spawn.respawn_seconds,
    }


def _spawn_set(kind: str, entity_id: int, spawns: tuple[PfQuestSpawn, ...]) -> list[dict[str, Any]]:
    payloads = [_spawn_payload(kind, entity_id, spawn) for spawn in spawns]
    return sorted(payloads, key=lambda item: str(item["spawn_key"]))


def _record_spawn_evidence(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    overlay_kind: str,
    kind: str,
    entity_id: int,
    spawns: tuple[PfQuestSpawn, ...],
) -> None:
    subject_kind = f"{kind}_spawn"
    for index, spawn in enumerate(spawns, start=1):
        key = _spawn_key(kind, entity_id, spawn)
        raw_identifier = f"{entity_id}:coords:{index}"
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind=subject_kind,
            subject_key=key,
            fact_key="position",
            value={
                "coordinate_space": "zone_percent",
                "zone_id": spawn.zone_id,
                "x": spawn.x,
                "y": spawn.y,
            },
            record_type=f"{kind}_spawn",
            raw_identifier=raw_identifier,
        )
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind=subject_kind,
            subject_key=key,
            fact_key="respawn_seconds",
            value=spawn.respawn_seconds,
            record_type=f"{kind}_spawn",
            raw_identifier=raw_identifier,
        )


def _record_base_complete_sets(
    connection: sqlite3.Connection,
    *,
    world: PfQuestWorldSlice,
    source_id: int,
    revision: str,
) -> None:
    rows_read = len(world.zones) + len(world.creatures) + len(world.gameobjects)
    batch_id = _create_batch(
        connection,
        source_id=source_id,
        revision=revision,
        rows_read=rows_read,
        importer_version=f"{IMPORTER_VERSION}-base-evidence",
    )
    try:
        for zone in world.zones:
            _record_base_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="zone",
                subject_key=zone.zone_id,
                fact_key=WORLD_PRESENCE_FACT,
                value=True,
                record_type="zone_effective_view",
            )
        for creature in world.creatures:
            _record_base_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="creature",
                subject_key=creature.creature_id,
                fact_key=WORLD_PRESENCE_FACT,
                value=True,
                record_type="unit_effective_view",
            )
            _record_base_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="creature",
                subject_key=creature.creature_id,
                fact_key=SPAWN_SET_FACT,
                value=_spawn_set("creature", creature.creature_id, creature.spawns),
                record_type="unit_spawn_set",
            )
        for gameobject in world.gameobjects:
            _record_base_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="gameobject",
                subject_key=gameobject.gameobject_id,
                fact_key=WORLD_PRESENCE_FACT,
                value=True,
                record_type="object_effective_view",
            )
            _record_base_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="gameobject",
                subject_key=gameobject.gameobject_id,
                fact_key=SPAWN_SET_FACT,
                value=_spawn_set("gameobject", gameobject.gameobject_id, gameobject.spawns),
                record_type="object_spawn_set",
            )
        _finish_batch(
            connection,
            batch_id=batch_id,
            rows_read=rows_read,
            rows_inserted=0,
            rows_updated=0,
            details={"purpose": "P1-T04 base complete-view provenance"},
        )
    except Exception as exc:
        _fail_batch(connection, batch_id, exc)
        raise


def _as_maps(world: PfQuestWorldSlice) -> tuple[dict[int, Any], dict[int, Any], dict[int, Any]]:
    return (
        {row.zone_id: row for row in world.zones},
        {row.creature_id: row for row in world.creatures},
        {row.gameobject_id: row for row in world.gameobjects},
    )


def _changed_ids(left: dict[int, Any], right: dict[int, Any]) -> set[int]:
    return {key for key in left.keys() & right.keys() if left[key] != right[key]}


def _row_changed(row: sqlite3.Row | None, expected: dict[str, Any]) -> bool:
    return row is not None and any(row[key] != value for key, value in expected.items())


def _upsert_zone(connection: sqlite3.Connection, zone: PfQuestZone) -> tuple[int, int]:
    name = str(
        _canonical_value(
            connection,
            subject_kind="zone",
            subject_key=zone.zone_id,
            fact_key="name",
            fallback=zone.name,
        )
    )
    existing = connection.execute(
        "SELECT name FROM zones WHERE zone_id = ?", (zone.zone_id,)
    ).fetchone()
    inserted = int(existing is None)
    updated = int(_row_changed(existing, {"name": name}))
    connection.execute(
        """
        INSERT INTO zones(zone_id, name)
        VALUES (?, ?)
        ON CONFLICT(zone_id) DO UPDATE SET name = excluded.name
        """,
        (zone.zone_id, name),
    )
    return inserted, updated


def _upsert_creature(connection: sqlite3.Connection, creature: PfQuestCreature) -> tuple[int, int]:
    name = str(
        _canonical_value(
            connection,
            subject_kind="creature",
            subject_key=creature.creature_id,
            fact_key="name",
            fallback=creature.name,
        )
    )
    level_min = _canonical_value(
        connection,
        subject_kind="creature",
        subject_key=creature.creature_id,
        fact_key="level_min",
        fallback=creature.level_min,
    )
    level_max = _canonical_value(
        connection,
        subject_kind="creature",
        subject_key=creature.creature_id,
        fact_key="level_max",
        fallback=creature.level_max,
    )
    faction = _canonical_value(
        connection,
        subject_kind="creature",
        subject_key=creature.creature_id,
        fact_key="faction",
        fallback=creature.faction,
    )
    existing = connection.execute(
        """
        SELECT name, level_min, level_max, faction
        FROM creatures WHERE creature_id = ?
        """,
        (creature.creature_id,),
    ).fetchone()
    expected = {
        "name": name,
        "level_min": level_min,
        "level_max": level_max,
        "faction": faction,
    }
    inserted = int(existing is None)
    updated = int(_row_changed(existing, expected))
    connection.execute(
        """
        INSERT INTO creatures(creature_id, name, level_min, level_max, faction)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(creature_id) DO UPDATE SET
            name = excluded.name,
            level_min = excluded.level_min,
            level_max = excluded.level_max,
            faction = excluded.faction
        """,
        (creature.creature_id, name, level_min, level_max, faction),
    )
    return inserted, updated


def _upsert_gameobject(
    connection: sqlite3.Connection, gameobject: PfQuestGameObject
) -> tuple[int, int]:
    name = str(
        _canonical_value(
            connection,
            subject_kind="gameobject",
            subject_key=gameobject.gameobject_id,
            fact_key="name",
            fallback=gameobject.name,
        )
    )
    existing = connection.execute(
        "SELECT name FROM gameobjects WHERE gameobject_id = ?", (gameobject.gameobject_id,)
    ).fetchone()
    inserted = int(existing is None)
    updated = int(_row_changed(existing, {"name": name}))
    connection.execute(
        """
        INSERT INTO gameobjects(gameobject_id, name)
        VALUES (?, ?)
        ON CONFLICT(gameobject_id) DO UPDATE SET name = excluded.name
        """,
        (gameobject.gameobject_id, name),
    )
    return inserted, updated


def _selected_position_source(
    connection: sqlite3.Connection, subject_kind: str, spawn_key: str
) -> str | None:
    row = connection.execute(
        """
        SELECT ds.source_key
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = ?
          AND og.subject_key = ?
          AND og.fact_key = 'position'
          AND og.fact_instance_key = ''
        """,
        (subject_kind, spawn_key),
    ).fetchone()
    return None if row is None else str(row["source_key"])


def _sync_spawns(
    connection: sqlite3.Connection,
    *,
    kind: str,
    entity_id: int,
    desired_spawns: tuple[PfQuestSpawn, ...],
) -> tuple[int, int, int]:
    if kind == "creature":
        table = "creature_spawns"
        id_column = "creature_id"
        subject_kind = "creature_spawn"
    elif kind == "gameobject":
        table = "gameobject_spawns"
        id_column = "gameobject_id"
        subject_kind = "gameobject_spawn"
    else:
        raise ValueError(f"unsupported spawn kind: {kind}")

    desired = {_spawn_key(kind, entity_id, spawn): spawn for spawn in desired_spawns}
    existing_rows = connection.execute(
        f"SELECT spawn_key FROM {table} WHERE {id_column} = ?", (entity_id,)
    ).fetchall()

    deleted = 0
    for row in existing_rows:
        key = str(row["spawn_key"])
        if key in desired:
            continue
        source_key = _selected_position_source(connection, subject_kind, key)
        if source_key in _MANAGED_SOURCE_KEYS:
            connection.execute(f"DELETE FROM {table} WHERE spawn_key = ?", (key,))
            deleted += 1

    inserted = 0
    updated = 0
    for key, spawn in desired.items():
        position = _canonical_value(
            connection,
            subject_kind=subject_kind,
            subject_key=key,
            fact_key="position",
            fallback={
                "coordinate_space": "zone_percent",
                "zone_id": spawn.zone_id,
                "x": spawn.x,
                "y": spawn.y,
            },
        )
        respawn = _canonical_value(
            connection,
            subject_kind=subject_kind,
            subject_key=key,
            fact_key="respawn_seconds",
            fallback=spawn.respawn_seconds,
        )
        existing = connection.execute(
            f"""
            SELECT {id_column}, zone_id, coordinate_space, x, y, respawn_seconds
            FROM {table} WHERE spawn_key = ?
            """,
            (key,),
        ).fetchone()
        expected = {
            id_column: entity_id,
            "zone_id": int(position["zone_id"]),
            "coordinate_space": str(position["coordinate_space"]),
            "x": float(position["x"]),
            "y": float(position["y"]),
            "respawn_seconds": respawn,
        }
        inserted += int(existing is None)
        updated += int(_row_changed(existing, expected))
        connection.execute(
            f"""
            INSERT INTO {table}(
                spawn_key, {id_column}, zone_id, coordinate_space, x, y, respawn_seconds
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(spawn_key) DO UPDATE SET
                {id_column} = excluded.{id_column},
                zone_id = excluded.zone_id,
                coordinate_space = excluded.coordinate_space,
                x = excluded.x,
                y = excluded.y,
                respawn_seconds = excluded.respawn_seconds
            """,
            (
                key,
                entity_id,
                expected["zone_id"],
                expected["coordinate_space"],
                expected["x"],
                expected["y"],
                respawn,
            ),
        )
    return inserted, updated, deleted


def _delete_template_if_unowned(
    connection: sqlite3.Connection,
    *,
    kind: str,
    entity_id: int,
) -> bool:
    if _has_non_pfquest_selected_support(
        connection, subject_kind=kind, subject_key=entity_id
    ):
        return False
    if kind == "creature":
        dependency = connection.execute(
            "SELECT 1 FROM creature_spawns WHERE creature_id = ? LIMIT 1", (entity_id,)
        ).fetchone()
        if dependency is not None:
            return False
        cursor = connection.execute("DELETE FROM creatures WHERE creature_id = ?", (entity_id,))
    elif kind == "gameobject":
        dependency = connection.execute(
            "SELECT 1 FROM gameobject_spawns WHERE gameobject_id = ? LIMIT 1", (entity_id,)
        ).fetchone()
        if dependency is not None:
            return False
        cursor = connection.execute(
            "DELETE FROM gameobjects WHERE gameobject_id = ?", (entity_id,)
        )
    else:
        raise ValueError(f"unsupported template kind: {kind}")
    return cursor.rowcount > 0


def _delete_zone_if_unowned(connection: sqlite3.Connection, zone_id: int) -> bool:
    if _has_non_pfquest_selected_support(
        connection, subject_kind="zone", subject_key=zone_id
    ):
        return False
    dependency = connection.execute(
        """
        SELECT 1 FROM creature_spawns WHERE zone_id = ?
        UNION ALL
        SELECT 1 FROM gameobject_spawns WHERE zone_id = ?
        UNION ALL
        SELECT 1 FROM zones WHERE parent_zone_id = ?
        LIMIT 1
        """,
        (zone_id, zone_id, zone_id),
    ).fetchone()
    if dependency is not None:
        return False
    cursor = connection.execute("DELETE FROM zones WHERE zone_id = ?", (zone_id,))
    return cursor.rowcount > 0


def _record_zone_change(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    overlay_kind: str,
    base: PfQuestZone | None,
    effective: PfQuestZone | None,
    zone_id: int,
) -> None:
    present = effective is not None
    _record_overlay_scalar(
        connection,
        batch_id=batch_id,
        overlay_kind=overlay_kind,
        subject_kind="zone",
        subject_key=zone_id,
        fact_key=WORLD_PRESENCE_FACT,
        value=present,
        record_type="zone_effective_view",
        negative_presence=not present,
    )
    if effective is None:
        return
    if base is None or base.name != effective.name:
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind="zone",
            subject_key=zone_id,
            fact_key="name",
            value=effective.name,
            record_type="zone",
        )
    if base is None or base.coordinate_frame != effective.coordinate_frame:
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind="zone",
            subject_key=zone_id,
            fact_key="pfquest.coordinate_frame",
            value=effective.coordinate_frame,
            record_type="zone",
        )


def _record_creature_change(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    overlay_kind: str,
    base: PfQuestCreature | None,
    effective: PfQuestCreature | None,
    creature_id: int,
) -> bool:
    present = effective is not None
    _record_overlay_scalar(
        connection,
        batch_id=batch_id,
        overlay_kind=overlay_kind,
        subject_kind="creature",
        subject_key=creature_id,
        fact_key=WORLD_PRESENCE_FACT,
        value=present,
        record_type="unit_effective_view",
        negative_presence=not present,
    )
    if effective is None:
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind="creature",
            subject_key=creature_id,
            fact_key=SPAWN_SET_FACT,
            value=[],
            record_type="unit_spawn_set",
        )
        return True

    if base is None or base.name != effective.name:
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind="creature",
            subject_key=creature_id,
            fact_key="name",
            value=effective.name,
            record_type="unit",
        )

    data_changed = base is None or (
        base.level_min,
        base.level_max,
        base.faction,
        base.spawns,
    ) != (
        effective.level_min,
        effective.level_max,
        effective.faction,
        effective.spawns,
    )
    if data_changed:
        for fact_key, value in (
            ("level_min", effective.level_min),
            ("level_max", effective.level_max),
            ("faction", effective.faction),
        ):
            _record_overlay_scalar(
                connection,
                batch_id=batch_id,
                overlay_kind=overlay_kind,
                subject_kind="creature",
                subject_key=creature_id,
                fact_key=fact_key,
                value=value,
                record_type="unit",
            )
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind="creature",
            subject_key=creature_id,
            fact_key=SPAWN_SET_FACT,
            value=_spawn_set("creature", creature_id, effective.spawns),
            record_type="unit_spawn_set",
        )
        _record_spawn_evidence(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            kind="creature",
            entity_id=creature_id,
            spawns=effective.spawns,
        )
    return data_changed


def _record_gameobject_change(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    overlay_kind: str,
    base: PfQuestGameObject | None,
    effective: PfQuestGameObject | None,
    gameobject_id: int,
) -> bool:
    present = effective is not None
    _record_overlay_scalar(
        connection,
        batch_id=batch_id,
        overlay_kind=overlay_kind,
        subject_kind="gameobject",
        subject_key=gameobject_id,
        fact_key=WORLD_PRESENCE_FACT,
        value=present,
        record_type="object_effective_view",
        negative_presence=not present,
    )
    if effective is None:
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind="gameobject",
            subject_key=gameobject_id,
            fact_key=SPAWN_SET_FACT,
            value=[],
            record_type="object_spawn_set",
        )
        return True

    if base is None or base.name != effective.name:
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind="gameobject",
            subject_key=gameobject_id,
            fact_key="name",
            value=effective.name,
            record_type="object",
        )

    data_changed = base is None or (base.faction, base.spawns) != (
        effective.faction,
        effective.spawns,
    )
    if data_changed:
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind="gameobject",
            subject_key=gameobject_id,
            fact_key="faction",
            value=effective.faction,
            record_type="object",
        )
        _record_overlay_scalar(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            subject_kind="gameobject",
            subject_key=gameobject_id,
            fact_key=SPAWN_SET_FACT,
            value=_spawn_set("gameobject", gameobject_id, effective.spawns),
            record_type="object_spawn_set",
        )
        _record_spawn_evidence(
            connection,
            batch_id=batch_id,
            overlay_kind=overlay_kind,
            kind="gameobject",
            entity_id=gameobject_id,
            spawns=effective.spawns,
        )
    return data_changed


def reconcile_pfquest_world_slices(
    connection: sqlite3.Connection,
    *,
    base_world: PfQuestWorldSlice,
    overlay_world: PfQuestWorldSlice,
    pfquest_revision: str,
    overlay_revision: str,
    overlay_kind: str,
    overlay_source_path: str | Path,
) -> ImportSummary:
    """Record overlay evidence and reconcile Turtle canonical world materialization.

    ``overlay_kind='turtle'`` is the active pfQuest-family view.  ``'octo'`` is
    evidence-only comparison input and never automatically changes canonical rows.
    """

    if overlay_kind not in {"turtle", "octo"}:
        raise ValueError("overlay_kind must be 'turtle' or 'octo'")
    pfquest_revision = _required_text(pfquest_revision, "pfquest_revision")
    overlay_revision = _required_text(overlay_revision, "overlay_revision")
    base_source_id = _require_pfquest_base_import(connection, pfquest_revision)

    source_key = (
        PFQUEST_TURTLE_SOURCE_KEY if overlay_kind == "turtle" else PFQUEST_OCTO_SOURCE_KEY
    )
    source_id = _ensure_source(
        connection,
        source_key=source_key,
        display_name="pfQuest Turtle" if overlay_kind == "turtle" else "pfQuest Octo",
        source_url=(
            PFQUEST_TURTLE_SOURCE_URL if overlay_kind == "turtle" else PFQUEST_OCTO_SOURCE_URL
        ),
        source_path=str(Path(overlay_source_path)),
    )

    _record_base_complete_sets(
        connection,
        world=base_world,
        source_id=base_source_id,
        revision=pfquest_revision,
    )

    base_zones, base_creatures, base_objects = _as_maps(base_world)
    zones, creatures, objects = _as_maps(overlay_world)
    zone_ids = set(base_zones) ^ set(zones) | _changed_ids(base_zones, zones)
    creature_ids = set(base_creatures) ^ set(creatures) | _changed_ids(base_creatures, creatures)
    object_ids = set(base_objects) ^ set(objects) | _changed_ids(base_objects, objects)
    rows_read = len(zone_ids) + len(creature_ids) + len(object_ids)

    batch_id = _create_batch(
        connection,
        source_id=source_id,
        revision=overlay_revision,
        rows_read=rows_read,
        importer_version=IMPORTER_VERSION,
    )
    inserted = 0
    updated = 0
    stale_creature_spawns_deleted = 0
    stale_gameobject_spawns_deleted = 0
    canonical_templates_deleted = 0
    canonical_zones_deleted = 0
    creature_spawn_sets_reconciled = 0
    object_spawn_sets_reconciled = 0

    try:
        for zone_id in sorted(zone_ids):
            _record_zone_change(
                connection,
                batch_id=batch_id,
                overlay_kind=overlay_kind,
                base=base_zones.get(zone_id),
                effective=zones.get(zone_id),
                zone_id=zone_id,
            )

        creature_data_changed: dict[int, bool] = {}
        for creature_id in sorted(creature_ids):
            creature_data_changed[creature_id] = _record_creature_change(
                connection,
                batch_id=batch_id,
                overlay_kind=overlay_kind,
                base=base_creatures.get(creature_id),
                effective=creatures.get(creature_id),
                creature_id=creature_id,
            )

        object_data_changed: dict[int, bool] = {}
        for gameobject_id in sorted(object_ids):
            object_data_changed[gameobject_id] = _record_gameobject_change(
                connection,
                batch_id=batch_id,
                overlay_kind=overlay_kind,
                base=base_objects.get(gameobject_id),
                effective=objects.get(gameobject_id),
                gameobject_id=gameobject_id,
            )

        if overlay_kind == "turtle":
            for zone_id in sorted(zone_ids):
                effective = zones.get(zone_id)
                if effective is None:
                    continue
                row_inserted, row_updated = _upsert_zone(connection, effective)
                inserted += row_inserted
                updated += row_updated

            for creature_id in sorted(creature_ids):
                effective = creatures.get(creature_id)
                if effective is not None:
                    row_inserted, row_updated = _upsert_creature(connection, effective)
                    inserted += row_inserted
                    updated += row_updated
                if creature_data_changed[creature_id]:
                    desired = () if effective is None else effective.spawns
                    spawn_inserted, spawn_updated, spawn_deleted = _sync_spawns(
                        connection,
                        kind="creature",
                        entity_id=creature_id,
                        desired_spawns=desired,
                    )
                    inserted += spawn_inserted
                    updated += spawn_updated
                    stale_creature_spawns_deleted += spawn_deleted
                    creature_spawn_sets_reconciled += 1

            for gameobject_id in sorted(object_ids):
                effective = objects.get(gameobject_id)
                if effective is not None:
                    row_inserted, row_updated = _upsert_gameobject(connection, effective)
                    inserted += row_inserted
                    updated += row_updated
                if object_data_changed[gameobject_id]:
                    desired = () if effective is None else effective.spawns
                    spawn_inserted, spawn_updated, spawn_deleted = _sync_spawns(
                        connection,
                        kind="gameobject",
                        entity_id=gameobject_id,
                        desired_spawns=desired,
                    )
                    inserted += spawn_inserted
                    updated += spawn_updated
                    stale_gameobject_spawns_deleted += spawn_deleted
                    object_spawn_sets_reconciled += 1

            for creature_id in sorted(set(base_creatures) - set(creatures)):
                canonical_templates_deleted += int(
                    _delete_template_if_unowned(
                        connection, kind="creature", entity_id=creature_id
                    )
                )
            for gameobject_id in sorted(set(base_objects) - set(objects)):
                canonical_templates_deleted += int(
                    _delete_template_if_unowned(
                        connection, kind="gameobject", entity_id=gameobject_id
                    )
                )
            for zone_id in sorted(set(base_zones) - set(zones)):
                canonical_zones_deleted += int(_delete_zone_if_unowned(connection, zone_id))

        details = {
            "comparison_only": overlay_kind == "octo",
            "zones_changed": len(zone_ids),
            "creatures_changed": len(creature_ids),
            "gameobjects_changed": len(object_ids),
            "creature_spawn_sets_reconciled": creature_spawn_sets_reconciled,
            "gameobject_spawn_sets_reconciled": object_spawn_sets_reconciled,
            "stale_creature_spawns_deleted": stale_creature_spawns_deleted,
            "stale_gameobject_spawns_deleted": stale_gameobject_spawns_deleted,
            "canonical_templates_deleted": canonical_templates_deleted,
            "canonical_zones_deleted": canonical_zones_deleted,
        }
        _finish_batch(
            connection,
            batch_id=batch_id,
            rows_read=rows_read,
            rows_inserted=inserted,
            rows_updated=updated,
            details=details,
        )
    except Exception as exc:
        _fail_batch(connection, batch_id, exc)
        raise

    return ImportSummary(
        source_key=source_key,
        source_revision=overlay_revision,
        status="succeeded",
        rows_read=rows_read,
        rows_accepted=rows_read,
        rows_skipped=0,
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=0,
        error_count=0,
        details=details,
    )


def import_pfquest_overlay_world(
    connection: sqlite3.Connection,
    *,
    pfquest_root: str | Path,
    overlay_root: str | Path,
    pfquest_revision: str,
    overlay_kind: str,
    overlay_revision: str | None = None,
) -> ImportSummary:
    """Load a P1 effective overlay view from disk and reconcile/record it."""

    base_world = load_pfquest_world_slice(pfquest_root)
    _validate_overlay_root(overlay_root)
    if overlay_kind == "turtle":
        overlay_world = load_pfquest_turtle_world_slice(pfquest_root, overlay_root)
    elif overlay_kind == "octo":
        overlay_world = load_pfquest_octo_world_slice(pfquest_root, overlay_root)
    else:
        raise ValueError("overlay_kind must be 'turtle' or 'octo'")
    revision = (
        compute_pfquest_overlay_revision(overlay_root)
        if overlay_revision is None
        else _required_text(overlay_revision, "overlay_revision")
    )
    return reconcile_pfquest_world_slices(
        connection,
        base_world=base_world,
        overlay_world=overlay_world,
        pfquest_revision=pfquest_revision,
        overlay_revision=revision,
        overlay_kind=overlay_kind,
        overlay_source_path=overlay_root,
    )
