"""Small pfQuest world-slice parser/importer for P1-T01.

This module deliberately understands only literal table assignments used by the
pfQuest world data files needed by the first P1 vertical slice. It is not a
general Lua interpreter.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import (
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.summary import ImportSummary

PFQUEST_SOURCE_KEY = "pfquest"
PFQUEST_SOURCE_URL = "https://github.com/shagu/pfQuest"
IMPORTER_VERSION = "pfquest-world/1"

_NUMBER_RE = re.compile(r"[-+]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][-+]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class PfQuestParseError(ValueError):
    """Raised when the supported pfQuest Lua-literal subset cannot be parsed."""


class _LuaLiteralParser:
    def __init__(self, text: str, position: int = 0) -> None:
        self.text = text
        self.position = position

    def _skip(self) -> None:
        while self.position < len(self.text):
            if self.text[self.position].isspace():
                self.position += 1
                continue
            if self.text.startswith("--", self.position):
                newline = self.text.find("\n", self.position + 2)
                self.position = len(self.text) if newline < 0 else newline + 1
                continue
            break

    def _peek(self) -> str:
        self._skip()
        return "" if self.position >= len(self.text) else self.text[self.position]

    def _consume(self, expected: str) -> None:
        self._skip()
        if not self.text.startswith(expected, self.position):
            snippet = self.text[self.position : self.position + 40]
            raise PfQuestParseError(f"expected {expected!r} near {snippet!r}")
        self.position += len(expected)

    def _parse_string(self) -> str:
        self._skip()
        quote = self._peek()
        if quote not in {'"', "'"}:
            raise PfQuestParseError("expected quoted string")
        self.position += 1
        chars: list[str] = []
        escapes = {
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "\\": "\\",
            '"': '"',
            "'": "'",
        }
        while self.position < len(self.text):
            char = self.text[self.position]
            self.position += 1
            if char == quote:
                return "".join(chars)
            if char == "\\":
                if self.position >= len(self.text):
                    raise PfQuestParseError("unterminated string escape")
                escaped = self.text[self.position]
                self.position += 1
                chars.append(escapes.get(escaped, escaped))
            else:
                chars.append(char)
        raise PfQuestParseError("unterminated string")

    def _parse_number(self) -> int | float:
        self._skip()
        match = _NUMBER_RE.match(self.text, self.position)
        if match is None:
            raise PfQuestParseError("expected number")
        token = match.group(0)
        self.position = match.end()
        if "." not in token and "e" not in token.lower():
            return int(token)
        return float(token)

    def _parse_identifier(self) -> str:
        self._skip()
        match = _IDENT_RE.match(self.text, self.position)
        if match is None:
            raise PfQuestParseError("expected identifier")
        self.position = match.end()
        return match.group(0)

    def parse_value(self) -> Any:
        self._skip()
        char = self._peek()
        if char == "{":
            return self._parse_table()
        if char in {'"', "'"}:
            return self._parse_string()
        if char and (char.isdigit() or char in "+-."):
            return self._parse_number()

        identifier = self._parse_identifier()
        if identifier == "true":
            return True
        if identifier == "false":
            return False
        if identifier == "nil":
            return None
        raise PfQuestParseError(f"unsupported Lua value identifier: {identifier!r}")

    def _parse_table(self) -> dict[Any, Any]:
        self._consume("{")
        result: dict[Any, Any] = {}
        next_array_key = 1

        while True:
            self._skip()
            if self._peek() == "}":
                self.position += 1
                return result

            if self._peek() == "[":
                self.position += 1
                key = self.parse_value()
                self._consume("]")
                self._consume("=")
                value = self.parse_value()
            else:
                saved = self.position
                try:
                    key_candidate = self._parse_identifier()
                    self._skip()
                    if self._peek() == "=":
                        self.position += 1
                        key = key_candidate
                        value = self.parse_value()
                    else:
                        self.position = saved
                        key = next_array_key
                        next_array_key += 1
                        value = self.parse_value()
                except PfQuestParseError:
                    self.position = saved
                    key = next_array_key
                    next_array_key += 1
                    value = self.parse_value()

            if value is not None:
                result[key] = value

            self._skip()
            if self._peek() in {",", ";"}:
                self.position += 1


def _assignment_pattern(domain: str, table_name: str) -> re.Pattern[str]:
    return re.compile(
        rf'pfDB\s*\[\s*"{re.escape(domain)}"\s*\]\s*'
        rf'\[\s*"{re.escape(table_name)}"\s*\]\s*=\s*'
    )


def parse_pfquest_assignment(text: str, *, domain: str, table_name: str) -> dict[Any, Any]:
    """Parse one ``pfDB["domain"]["table"] = {...}`` literal assignment."""

    match = _assignment_pattern(domain, table_name).search(text)
    if match is None:
        raise PfQuestParseError(f"pfQuest assignment not found: {domain}.{table_name}")
    parser = _LuaLiteralParser(text, match.end())
    value = parser.parse_value()
    if not isinstance(value, dict):
        raise PfQuestParseError(f"{domain}.{table_name} must be a Lua table")
    return value


def _numeric_sequence(value: Any, *, minimum: int, label: str) -> list[Any]:
    if not isinstance(value, dict):
        raise PfQuestParseError(f"{label} must be a Lua table")
    sequence: list[Any] = []
    index = 1
    while index in value:
        sequence.append(value[index])
        index += 1
    if len(sequence) < minimum:
        raise PfQuestParseError(f"{label} must contain at least {minimum} positional values")
    return sequence


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise PfQuestParseError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        return int(value.strip())
    raise PfQuestParseError(f"{label} must be an integer")


def _float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise PfQuestParseError(f"{label} must be numeric")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError as exc:
        raise PfQuestParseError(f"{label} must be numeric") from exc


def _level_range(value: Any) -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        level = _integer(value, "unit level")
        return level, level

    text = str(value).strip()
    if text.isdigit():
        level = int(text)
        return level, level
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", text)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            raise PfQuestParseError(f"unit level range is reversed: {text!r}")
        return low, high
    raise PfQuestParseError(f"unsupported pfQuest unit level: {value!r}")


@dataclass(frozen=True)
class PfQuestZone:
    zone_id: int
    name: str
    coordinate_frame: dict[str, float | int] | None = None


@dataclass(frozen=True)
class PfQuestSpawn:
    x: float
    y: float
    zone_id: int
    respawn_seconds: int | None


@dataclass(frozen=True)
class PfQuestCreature:
    creature_id: int
    name: str
    level_min: int | None
    level_max: int | None
    faction: str | None
    spawns: tuple[PfQuestSpawn, ...]


@dataclass(frozen=True)
class PfQuestGameObject:
    gameobject_id: int
    name: str
    faction: str | None
    spawns: tuple[PfQuestSpawn, ...]


@dataclass(frozen=True)
class PfQuestWorldSlice:
    zones: tuple[PfQuestZone, ...]
    creatures: tuple[PfQuestCreature, ...]
    gameobjects: tuple[PfQuestGameObject, ...]


def _read_assignment(path: Path, domain: str, table_name: str) -> dict[Any, Any]:
    return parse_pfquest_assignment(
        path.read_text(encoding="utf-8"),
        domain=domain,
        table_name=table_name,
    )


def _parse_spawn_table(coords: Any, *, label: str) -> tuple[PfQuestSpawn, ...]:
    if coords is None:
        return ()
    if not isinstance(coords, dict):
        raise PfQuestParseError(f"{label}.coords must be a Lua table")

    spawns: list[PfQuestSpawn] = []
    for index in sorted(key for key in coords if isinstance(key, int)):
        raw = _numeric_sequence(coords[index], minimum=3, label=f"{label}.coords[{index}]")
        respawn = None
        if len(raw) >= 4 and raw[3] is not None:
            respawn = _integer(raw[3], f"{label}.coords[{index}].respawn")
            if respawn < 0:
                raise PfQuestParseError(f"{label}.coords[{index}].respawn must be non-negative")
        spawn = PfQuestSpawn(
            x=_float(raw[0], f"{label}.coords[{index}].x"),
            y=_float(raw[1], f"{label}.coords[{index}].y"),
            zone_id=_integer(raw[2], f"{label}.coords[{index}].zone"),
            respawn_seconds=respawn,
        )
        if not 0.0 <= spawn.x <= 100.0 or not 0.0 <= spawn.y <= 100.0:
            raise PfQuestParseError(f"{label}.coords[{index}] is outside zone-percent bounds")
        spawns.append(spawn)
    return tuple(spawns)


def load_pfquest_world_slice(source_root: str | Path) -> PfQuestWorldSlice:
    """Load the six pfQuest files used by the P1-T01 world fixture slice."""

    root = Path(source_root)
    zones_data = _read_assignment(root / "db" / "zones.lua", "zones", "data")
    zone_names = _read_assignment(root / "db" / "enUS" / "zones.lua", "zones", "enUS")
    unit_data = _read_assignment(root / "db" / "units.lua", "units", "data")
    unit_names = _read_assignment(root / "db" / "enUS" / "units.lua", "units", "enUS")
    object_data = _read_assignment(root / "db" / "objects.lua", "objects", "data")
    object_names = _read_assignment(root / "db" / "enUS" / "objects.lua", "objects", "enUS")

    referenced_zone_ids = {
        spawn.zone_id
        for records, label in ((unit_data, "unit"), (object_data, "object"))
        for entity_id, record in records.items()
        if isinstance(entity_id, int) and isinstance(record, dict)
        for spawn in _parse_spawn_table(record.get("coords"), label=f"{label}[{entity_id}]")
    }
    zone_ids = sorted(
        {
            int(zone_id)
            for zone_id in zone_names
            if isinstance(zone_id, int)
        }
        & (set(zones_data) | referenced_zone_ids)
    )

    zones: list[PfQuestZone] = []
    for zone_id in zone_ids:
        name = zone_names.get(zone_id)
        if not isinstance(name, str) or not name.strip():
            raise PfQuestParseError(f"missing enUS name for zone {zone_id}")
        frame = None
        if zone_id in zones_data:
            raw = _numeric_sequence(
                zones_data[zone_id],
                minimum=5,
                label=f"zone[{zone_id}]",
            )
            frame = {
                "coordinate_context_id": _integer(raw[0], f"zone[{zone_id}][1]"),
                "width": _float(raw[1], f"zone[{zone_id}][2]"),
                "height": _float(raw[2], f"zone[{zone_id}][3]"),
                "origin_x": _float(raw[3], f"zone[{zone_id}][4]"),
                "origin_y": _float(raw[4], f"zone[{zone_id}][5]"),
            }
        zones.append(PfQuestZone(zone_id=zone_id, name=name.strip(), coordinate_frame=frame))

    creatures: list[PfQuestCreature] = []
    for creature_id in sorted(key for key in unit_data if isinstance(key, int)):
        record = unit_data[creature_id]
        if not isinstance(record, dict):
            raise PfQuestParseError(f"unit[{creature_id}] must be a Lua table")
        name = unit_names.get(creature_id)
        if not isinstance(name, str) or not name.strip():
            continue
        level_min, level_max = _level_range(record.get("lvl"))
        faction = record.get("fac")
        creatures.append(
            PfQuestCreature(
                creature_id=creature_id,
                name=name.strip(),
                level_min=level_min,
                level_max=level_max,
                faction=None if faction is None else str(faction),
                spawns=_parse_spawn_table(record.get("coords"), label=f"unit[{creature_id}]"),
            )
        )

    gameobjects: list[PfQuestGameObject] = []
    for gameobject_id in sorted(key for key in object_data if isinstance(key, int)):
        record = object_data[gameobject_id]
        if not isinstance(record, dict):
            raise PfQuestParseError(f"object[{gameobject_id}] must be a Lua table")
        name = object_names.get(gameobject_id)
        if not isinstance(name, str) or not name.strip():
            continue
        faction = record.get("fac")
        gameobjects.append(
            PfQuestGameObject(
                gameobject_id=gameobject_id,
                name=name.strip(),
                faction=None if faction is None else str(faction),
                spawns=_parse_spawn_table(record.get("coords"), label=f"object[{gameobject_id}]"),
            )
        )

    return PfQuestWorldSlice(
        zones=tuple(zones),
        creatures=tuple(creatures),
        gameobjects=tuple(gameobjects),
    )


def _ensure_source(connection: sqlite3.Connection, source_path: str) -> int:
    connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind, source_url, source_path)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            display_name = excluded.display_name,
            source_kind = excluded.source_kind,
            source_url = excluded.source_url,
            source_path = excluded.source_path,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (PFQUEST_SOURCE_KEY, "pfQuest", "lua-addon", PFQUEST_SOURCE_URL, source_path),
    )
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?",
        (PFQUEST_SOURCE_KEY,),
    ).fetchone()
    if row is None:
        raise RuntimeError("pfQuest source registration failed")
    return int(row["id"])


def _selected_value(
    connection: sqlite3.Connection,
    *,
    observation_id: int,
    selection_reason: str,
) -> Any:
    group_row = connection.execute(
        "SELECT observation_group_id FROM source_observations WHERE id = ?",
        (observation_id,),
    ).fetchone()
    if group_row is None:
        raise RuntimeError(f"observation {observation_id} disappeared")
    group_id = int(group_row["observation_group_id"])

    selected = connection.execute(
        """
        SELECT so.value_json
        FROM canonical_selections AS cs
        JOIN source_observations AS so ON so.id = cs.observation_id
        WHERE cs.observation_group_id = ?
        """,
        (group_id,),
    ).fetchone()
    if selected is None:
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy="first-observation",
            selection_reason=selection_reason,
        )
        selected = connection.execute(
            "SELECT value_json FROM source_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    return json.loads(str(selected["value_json"]))


def _observe_scalar(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    value: Any,
    record_type: str,
    raw_identifier: str,
) -> Any:
    observation_id = record_scalar_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type=record_type,
        raw_identifier=raw_identifier,
    )
    return _selected_value(
        connection,
        observation_id=observation_id,
        selection_reason=(
            "Selected automatically because this fact had no prior canonical selection."
        ),
    )


def _spawn_key(
    *,
    kind: str,
    entity_id: int,
    zone_id: int,
    x: float,
    y: float,
) -> str:
    return f"{kind}:{entity_id}:zone_percent:{zone_id}:{x:.6f}:{y:.6f}"


def _row_changed(row: sqlite3.Row | None, expected: dict[str, Any]) -> bool:
    if row is None:
        return False
    return any(row[key] != value for key, value in expected.items())


def import_pfquest_world_slice(
    connection: sqlite3.Connection,
    *,
    source_root: str | Path,
    source_revision: str,
) -> ImportSummary:
    """Import a small pfQuest world slice with provenance and canonical materialization."""

    source_revision = source_revision.strip()
    if not source_revision:
        raise ValueError("source_revision must not be blank")

    slice_data = load_pfquest_world_slice(source_root)
    source_id = _ensure_source(connection, str(Path(source_root)))
    batch_cursor = connection.execute(
        """
        INSERT INTO import_batches(
            source_id, source_revision, status, importer_version, rows_read
        )
        VALUES (?, ?, 'running', ?, ?)
        """,
        (
            source_id,
            source_revision,
            IMPORTER_VERSION,
            len(slice_data.zones) + len(slice_data.creatures) + len(slice_data.gameobjects),
        ),
    )
    batch_id = int(batch_cursor.lastrowid)

    inserted = 0
    updated = 0
    spawn_counts = {"creature": 0, "gameobject": 0}

    try:
        for zone in slice_data.zones:
            canonical_name = _observe_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="zone",
                subject_key=zone.zone_id,
                fact_key="name",
                value=zone.name,
                record_type="zone",
                raw_identifier=str(zone.zone_id),
            )
            if zone.coordinate_frame is not None:
                _observe_scalar(
                    connection,
                    batch_id=batch_id,
                    subject_kind="zone",
                    subject_key=zone.zone_id,
                    fact_key="pfquest.coordinate_frame",
                    value=zone.coordinate_frame,
                    record_type="zone",
                    raw_identifier=str(zone.zone_id),
                )

            existing = connection.execute(
                "SELECT name FROM zones WHERE zone_id = ?",
                (zone.zone_id,),
            ).fetchone()
            expected = {"name": str(canonical_name)}
            if existing is None:
                inserted += 1
            elif _row_changed(existing, expected):
                updated += 1
            connection.execute(
                """
                INSERT INTO zones(zone_id, name)
                VALUES (?, ?)
                ON CONFLICT(zone_id) DO UPDATE SET
                    name = excluded.name
                """,
                (zone.zone_id, canonical_name),
            )

        for creature in slice_data.creatures:
            name = _observe_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="creature",
                subject_key=creature.creature_id,
                fact_key="name",
                value=creature.name,
                record_type="unit",
                raw_identifier=str(creature.creature_id),
            )
            level_min = (
                None
                if creature.level_min is None
                else _observe_scalar(
                    connection,
                    batch_id=batch_id,
                    subject_kind="creature",
                    subject_key=creature.creature_id,
                    fact_key="level_min",
                    value=creature.level_min,
                    record_type="unit",
                    raw_identifier=str(creature.creature_id),
                )
            )
            level_max = (
                None
                if creature.level_max is None
                else _observe_scalar(
                    connection,
                    batch_id=batch_id,
                    subject_kind="creature",
                    subject_key=creature.creature_id,
                    fact_key="level_max",
                    value=creature.level_max,
                    record_type="unit",
                    raw_identifier=str(creature.creature_id),
                )
            )
            faction = (
                None
                if creature.faction is None
                else _observe_scalar(
                    connection,
                    batch_id=batch_id,
                    subject_kind="creature",
                    subject_key=creature.creature_id,
                    fact_key="faction",
                    value=creature.faction,
                    record_type="unit",
                    raw_identifier=str(creature.creature_id),
                )
            )

            existing = connection.execute(
                """
                SELECT name, level_min, level_max, faction
                FROM creatures WHERE creature_id = ?
                """,
                (creature.creature_id,),
            ).fetchone()
            expected = {
                "name": str(name),
                "level_min": level_min,
                "level_max": level_max,
                "faction": faction,
            }
            if existing is None:
                inserted += 1
            elif _row_changed(existing, expected):
                updated += 1
            connection.execute(
                """
                INSERT INTO creatures(
                    creature_id, name, level_min, level_max, faction
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(creature_id) DO UPDATE SET
                    name = excluded.name,
                    level_min = excluded.level_min,
                    level_max = excluded.level_max,
                    faction = excluded.faction
                """,
                (
                    creature.creature_id,
                    name,
                    level_min,
                    level_max,
                    faction,
                ),
            )

            for index, spawn in enumerate(creature.spawns, start=1):
                spawn_key = _spawn_key(
                    kind="creature",
                    entity_id=creature.creature_id,
                    zone_id=spawn.zone_id,
                    x=spawn.x,
                    y=spawn.y,
                )
                position = _observe_scalar(
                    connection,
                    batch_id=batch_id,
                    subject_kind="creature_spawn",
                    subject_key=spawn_key,
                    fact_key="position",
                    value={
                        "coordinate_space": "zone_percent",
                        "zone_id": spawn.zone_id,
                        "x": spawn.x,
                        "y": spawn.y,
                    },
                    record_type="unit_spawn",
                    raw_identifier=f"{creature.creature_id}:coords:{index}",
                )
                respawn = (
                    None
                    if spawn.respawn_seconds is None
                    else _observe_scalar(
                        connection,
                        batch_id=batch_id,
                        subject_kind="creature_spawn",
                        subject_key=spawn_key,
                        fact_key="respawn_seconds",
                        value=spawn.respawn_seconds,
                        record_type="unit_spawn",
                        raw_identifier=f"{creature.creature_id}:coords:{index}",
                    )
                )
                existing_spawn = connection.execute(
                    """
                    SELECT creature_id, zone_id, coordinate_space, x, y, respawn_seconds
                    FROM creature_spawns WHERE spawn_key = ?
                    """,
                    (spawn_key,),
                ).fetchone()
                expected_spawn = {
                    "creature_id": creature.creature_id,
                    "zone_id": int(position["zone_id"]),
                    "coordinate_space": str(position["coordinate_space"]),
                    "x": float(position["x"]),
                    "y": float(position["y"]),
                    "respawn_seconds": respawn,
                }
                if existing_spawn is None:
                    inserted += 1
                elif _row_changed(existing_spawn, expected_spawn):
                    updated += 1
                connection.execute(
                    """
                    INSERT INTO creature_spawns(
                        spawn_key, creature_id, zone_id, coordinate_space, x, y,
                        respawn_seconds
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(spawn_key) DO UPDATE SET
                        creature_id = excluded.creature_id,
                        zone_id = excluded.zone_id,
                        coordinate_space = excluded.coordinate_space,
                        x = excluded.x,
                        y = excluded.y,
                        respawn_seconds = excluded.respawn_seconds
                    """,
                    (
                        spawn_key,
                        creature.creature_id,
                        position["zone_id"],
                        position["coordinate_space"],
                        position["x"],
                        position["y"],
                        respawn,
                    ),
                )
                spawn_counts["creature"] += 1

        for gameobject in slice_data.gameobjects:
            name = _observe_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="gameobject",
                subject_key=gameobject.gameobject_id,
                fact_key="name",
                value=gameobject.name,
                record_type="object",
                raw_identifier=str(gameobject.gameobject_id),
            )
            if gameobject.faction is not None:
                _observe_scalar(
                    connection,
                    batch_id=batch_id,
                    subject_kind="gameobject",
                    subject_key=gameobject.gameobject_id,
                    fact_key="faction",
                    value=gameobject.faction,
                    record_type="object",
                    raw_identifier=str(gameobject.gameobject_id),
                )
            existing = connection.execute(
                "SELECT name FROM gameobjects WHERE gameobject_id = ?",
                (gameobject.gameobject_id,),
            ).fetchone()
            expected = {"name": str(name)}
            if existing is None:
                inserted += 1
            elif _row_changed(existing, expected):
                updated += 1
            connection.execute(
                """
                INSERT INTO gameobjects(gameobject_id, name)
                VALUES (?, ?)
                ON CONFLICT(gameobject_id) DO UPDATE SET
                    name = excluded.name
                """,
                (gameobject.gameobject_id, name),
            )

            for index, spawn in enumerate(gameobject.spawns, start=1):
                spawn_key = _spawn_key(
                    kind="gameobject",
                    entity_id=gameobject.gameobject_id,
                    zone_id=spawn.zone_id,
                    x=spawn.x,
                    y=spawn.y,
                )
                position = _observe_scalar(
                    connection,
                    batch_id=batch_id,
                    subject_kind="gameobject_spawn",
                    subject_key=spawn_key,
                    fact_key="position",
                    value={
                        "coordinate_space": "zone_percent",
                        "zone_id": spawn.zone_id,
                        "x": spawn.x,
                        "y": spawn.y,
                    },
                    record_type="object_spawn",
                    raw_identifier=f"{gameobject.gameobject_id}:coords:{index}",
                )
                respawn = (
                    None
                    if spawn.respawn_seconds is None
                    else _observe_scalar(
                        connection,
                        batch_id=batch_id,
                        subject_kind="gameobject_spawn",
                        subject_key=spawn_key,
                        fact_key="respawn_seconds",
                        value=spawn.respawn_seconds,
                        record_type="object_spawn",
                        raw_identifier=f"{gameobject.gameobject_id}:coords:{index}",
                    )
                )
                existing_spawn = connection.execute(
                    """
                    SELECT gameobject_id, zone_id, coordinate_space, x, y,
                           respawn_seconds
                    FROM gameobject_spawns WHERE spawn_key = ?
                    """,
                    (spawn_key,),
                ).fetchone()
                expected_spawn = {
                    "gameobject_id": gameobject.gameobject_id,
                    "zone_id": int(position["zone_id"]),
                    "coordinate_space": str(position["coordinate_space"]),
                    "x": float(position["x"]),
                    "y": float(position["y"]),
                    "respawn_seconds": respawn,
                }
                if existing_spawn is None:
                    inserted += 1
                elif _row_changed(existing_spawn, expected_spawn):
                    updated += 1
                connection.execute(
                    """
                    INSERT INTO gameobject_spawns(
                        spawn_key, gameobject_id, zone_id, coordinate_space, x, y,
                        respawn_seconds
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(spawn_key) DO UPDATE SET
                        gameobject_id = excluded.gameobject_id,
                        zone_id = excluded.zone_id,
                        coordinate_space = excluded.coordinate_space,
                        x = excluded.x,
                        y = excluded.y,
                        respawn_seconds = excluded.respawn_seconds
                    """,
                    (
                        spawn_key,
                        gameobject.gameobject_id,
                        position["zone_id"],
                        position["coordinate_space"],
                        position["x"],
                        position["y"],
                        respawn,
                    ),
                )
                spawn_counts["gameobject"] += 1

        rows_read = len(slice_data.zones) + len(slice_data.creatures) + len(slice_data.gameobjects)
        details = {
            "canonical_rows_inserted_or_updated": inserted + updated,
            "creature_spawns": spawn_counts["creature"],
            "gameobject_spawns": spawn_counts["gameobject"],
            "zones": len(slice_data.zones),
            "creatures": len(slice_data.creatures),
            "gameobjects": len(slice_data.gameobjects),
        }
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
                inserted,
                updated,
                json.dumps(details, sort_keys=True, separators=(",", ":")),
                batch_id,
            ),
        )
    except Exception as exc:
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
        raise

    return ImportSummary(
        source_key=PFQUEST_SOURCE_KEY,
        source_revision=source_revision,
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
