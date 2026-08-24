"""Octo client DBC world hierarchy importer for P1-T02.

The importer intentionally reads only Map.dbc and AreaTable.dbc fields needed to
establish canonical map/zone identity and hierarchy. It validates the classic
WDBC container shape and keeps source evidence in the project provenance layer.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import record_scalar_observation, select_canonical_observation
from octogamedb.importers.summary import ImportSummary

OCTO_DBC_SOURCE_KEY = "octo-client-dbc"
IMPORTER_VERSION = "octo-dbc-world/1"
SELECTION_POLICY = "octo-client-dbc-geography"
_REQUIRED_FILES = ("Map.dbc", "AreaTable.dbc")
_HEADER = struct.Struct("<4sIIII")
_MAP_KIND = {
    0: "common",
    1: "dungeon",
    2: "raid",
    3: "battleground",
}


class DbcParseError(ValueError):
    """Raised when a required DBC file is missing or has an unsupported shape."""


@dataclass(frozen=True)
class OctoDbcMap:
    map_id: int
    name: str
    map_type: int
    map_kind: str
    linked_zone_id: int | None


@dataclass(frozen=True)
class OctoDbcArea:
    zone_id: int
    map_id: int
    parent_zone_id: int | None
    name: str
    explore_flag: int
    flags: int
    area_level: int
    faction_group_mask: int
    liquid_type_override: int


@dataclass(frozen=True)
class OctoDbcWorldSlice:
    maps: tuple[OctoDbcMap, ...]
    areas: tuple[OctoDbcArea, ...]


@dataclass(frozen=True)
class _DbcTable:
    path: Path
    record_count: int
    field_count: int
    record_size: int
    string_size: int
    records: bytes
    strings: bytes

    @classmethod
    def load(cls, path: str | Path, *, minimum_fields: int) -> _DbcTable:
        source = Path(path)
        try:
            data = source.read_bytes()
        except FileNotFoundError as exc:
            raise DbcParseError(f"required DBC file not found: {source}") from exc

        if len(data) < _HEADER.size:
            raise DbcParseError(f"{source.name}: file is shorter than the WDBC header")

        magic, record_count, field_count, record_size, string_size = _HEADER.unpack_from(data)
        if magic != b"WDBC":
            raise DbcParseError(f"{source.name}: expected WDBC magic, got {magic!r}")
        if field_count < minimum_fields:
            raise DbcParseError(
                f"{source.name}: expected at least {minimum_fields} fields, got {field_count}"
            )
        if record_size < field_count * 4 or record_size % 4:
            raise DbcParseError(
                f"{source.name}: unsupported record layout "
                f"(field_count={field_count}, record_size={record_size})"
            )

        records_size = record_count * record_size
        expected_size = _HEADER.size + records_size + string_size
        if len(data) != expected_size:
            raise DbcParseError(
                f"{source.name}: header declares {expected_size} bytes, file has {len(data)}"
            )

        records_start = _HEADER.size
        strings_start = records_start + records_size
        return cls(
            path=source,
            record_count=record_count,
            field_count=field_count,
            record_size=record_size,
            string_size=string_size,
            records=data[records_start:strings_start],
            strings=data[strings_start:],
        )

    def _field_offset(self, record_index: int, field_index: int) -> int:
        if not 0 <= record_index < self.record_count:
            raise IndexError(record_index)
        if not 0 <= field_index < self.field_count:
            raise DbcParseError(
                f"{self.path.name}: field {field_index} outside 0..{self.field_count - 1}"
            )
        return record_index * self.record_size + field_index * 4

    def uint32(self, record_index: int, field_index: int) -> int:
        offset = self._field_offset(record_index, field_index)
        return struct.unpack_from("<I", self.records, offset)[0]

    def int32(self, record_index: int, field_index: int) -> int:
        offset = self._field_offset(record_index, field_index)
        return struct.unpack_from("<i", self.records, offset)[0]

    def string(self, record_index: int, field_index: int) -> str:
        offset = self.uint32(record_index, field_index)
        if offset == 0:
            return ""
        if offset >= self.string_size:
            raise DbcParseError(
                f"{self.path.name}: string offset {offset} outside string block "
                f"({self.string_size} bytes)"
            )
        end = self.strings.find(b"\0", offset)
        if end < 0:
            raise DbcParseError(f"{self.path.name}: unterminated string at offset {offset}")
        raw = self.strings[offset:end]
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1252")

    def localized_string(self, record_index: int, first_field: int) -> str:
        for field_index in range(first_field, first_field + 8):
            value = self.string(record_index, field_index).strip()
            if value:
                return value
        return ""


def _normalize_map_kind(map_type: int) -> str:
    return _MAP_KIND.get(map_type, f"unknown:{map_type}")


def load_octodbc_world_slice(source_root: str | Path) -> OctoDbcWorldSlice:
    """Parse Map.dbc and AreaTable.dbc from a directory containing extracted DBCs."""

    root = Path(source_root)
    map_table = _DbcTable.load(root / "Map.dbc", minimum_fields=39)
    area_table = _DbcTable.load(root / "AreaTable.dbc", minimum_fields=25)

    maps: list[OctoDbcMap] = []
    seen_map_ids: set[int] = set()
    for index in range(map_table.record_count):
        map_id = map_table.uint32(index, 0)
        if map_id in seen_map_ids:
            raise DbcParseError(f"Map.dbc: duplicate map ID {map_id}")
        seen_map_ids.add(map_id)
        name = map_table.localized_string(index, 4)
        if not name:
            raise DbcParseError(f"Map.dbc: map {map_id} has no localized name")
        map_type = map_table.uint32(index, 2)
        linked_zone = map_table.uint32(index, 19)
        maps.append(
            OctoDbcMap(
                map_id=map_id,
                name=name,
                map_type=map_type,
                map_kind=_normalize_map_kind(map_type),
                linked_zone_id=None if linked_zone == 0 else linked_zone,
            )
        )

    areas: list[OctoDbcArea] = []
    seen_area_ids: set[int] = set()
    for index in range(area_table.record_count):
        zone_id = area_table.uint32(index, 0)
        if zone_id in seen_area_ids:
            raise DbcParseError(f"AreaTable.dbc: duplicate area ID {zone_id}")
        seen_area_ids.add(zone_id)
        name = area_table.localized_string(index, 11)
        parent_zone = area_table.uint32(index, 2)
        areas.append(
            OctoDbcArea(
                zone_id=zone_id,
                map_id=area_table.uint32(index, 1),
                parent_zone_id=None if parent_zone == 0 else parent_zone,
                name=name,
                explore_flag=area_table.uint32(index, 3),
                flags=area_table.uint32(index, 4),
                area_level=area_table.int32(index, 10),
                faction_group_mask=area_table.uint32(index, 20),
                liquid_type_override=area_table.uint32(index, 24),
            )
        )

    maps.sort(key=lambda record: record.map_id)
    areas.sort(key=lambda record: record.zone_id)
    return OctoDbcWorldSlice(maps=tuple(maps), areas=tuple(areas))


def compute_octodbc_world_revision(source_root: str | Path) -> str:
    """Return a deterministic revision for the exact Map/AreaTable DBC pair."""

    root = Path(source_root)
    digest = hashlib.sha256()
    for filename in _REQUIRED_FILES:
        path = root / filename
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise DbcParseError(f"required DBC file not found: {path}") from exc
        digest.update(filename.encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    return f"sha256:{digest.hexdigest()}"


def _ensure_source(connection: sqlite3.Connection, source_path: str) -> int:
    connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind, source_path)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            display_name = excluded.display_name,
            source_kind = excluded.source_kind,
            source_path = excluded.source_path,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (OCTO_DBC_SOURCE_KEY, "Octo client DBC", "client-dbc", source_path),
    )
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (OCTO_DBC_SOURCE_KEY,)
    ).fetchone()
    if row is None:
        raise RuntimeError("Octo DBC source registration failed")
    return int(row["id"])


def _select_octodbc_observation(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    value: Any,
    record_type: str,
    raw_identifier: str | int,
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
        authority_tier=1,
    )
    row = connection.execute(
        "SELECT observation_group_id, value_json FROM source_observations WHERE id = ?",
        (observation_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"observation {observation_id} disappeared")
    group_id = int(row["observation_group_id"])
    current = connection.execute(
        """
        SELECT observation_id, selection_policy
        FROM canonical_selections
        WHERE observation_group_id = ?
        """,
        (group_id,),
    ).fetchone()
    if (
        current is None
        or int(current["observation_id"]) != observation_id
        or current["selection_policy"] != SELECTION_POLICY
    ):
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy=SELECTION_POLICY,
            selection_reason=(
                "Octo client Map.dbc/AreaTable.dbc is authoritative for canonical "
                "map/area identity and hierarchy in P1-T02."
            ),
        )
    return json.loads(str(row["value_json"]))


def _row_changed(row: sqlite3.Row | None, expected: dict[str, Any]) -> bool:
    if row is None:
        return False
    return any(row[key] != value for key, value in expected.items())


def import_octodbc_world(
    connection: sqlite3.Connection,
    *,
    source_root: str | Path,
    source_revision: str | None = None,
) -> ImportSummary:
    """Import canonical map/zone hierarchy from Octo client Map.dbc/AreaTable.dbc."""

    root = Path(source_root)
    world = load_octodbc_world_slice(root)
    accepted_areas = tuple(record for record in world.areas if record.name)
    skipped_area_ids = tuple(record.zone_id for record in world.areas if not record.name)
    revision = (
        compute_octodbc_world_revision(root)
        if source_revision is None
        else source_revision.strip()
    )
    if not revision:
        raise ValueError("source_revision must not be blank")

    parsed_map_ids = {record.map_id for record in world.maps}
    parsed_zone_ids = {record.zone_id for record in accepted_areas}
    existing_map_ids = {
        int(row[0]) for row in connection.execute("SELECT map_id FROM maps").fetchall()
    }
    existing_zone_ids = {
        int(row[0]) for row in connection.execute("SELECT zone_id FROM zones").fetchall()
    }
    for area in accepted_areas:
        if area.map_id not in parsed_map_ids and area.map_id not in existing_map_ids:
            raise DbcParseError(
                f"AreaTable.dbc: area {area.zone_id} references missing map {area.map_id}"
            )
        if (
            area.parent_zone_id is not None
            and area.parent_zone_id not in parsed_zone_ids
            and area.parent_zone_id not in existing_zone_ids
        ):
            raise DbcParseError(
                f"AreaTable.dbc: area {area.zone_id} references missing parent "
                f"area {area.parent_zone_id}"
            )

    source_id = _ensure_source(connection, str(root))
    rows_read = len(world.maps) + len(world.areas)
    rows_skipped = len(skipped_area_ids)
    rows_accepted = rows_read - rows_skipped
    batch = connection.execute(
        """
        INSERT INTO import_batches(source_id, source_revision, status, importer_version, rows_read)
        VALUES (?, ?, 'running', ?, ?)
        """,
        (source_id, revision, IMPORTER_VERSION, rows_read),
    )
    batch_id = int(batch.lastrowid)
    inserted = 0
    updated = 0

    try:
        resolved_maps: list[tuple[OctoDbcMap, str, str]] = []
        for record in world.maps:
            name = str(
                _select_octodbc_observation(
                    connection,
                    batch_id=batch_id,
                    subject_kind="map",
                    subject_key=record.map_id,
                    fact_key="name",
                    value=record.name,
                    record_type="Map.dbc",
                    raw_identifier=record.map_id,
                )
            )
            map_kind = str(
                _select_octodbc_observation(
                    connection,
                    batch_id=batch_id,
                    subject_kind="map",
                    subject_key=record.map_id,
                    fact_key="map_kind",
                    value=record.map_kind,
                    record_type="Map.dbc",
                    raw_identifier=record.map_id,
                )
            )
            _select_octodbc_observation(
                connection,
                batch_id=batch_id,
                subject_kind="map",
                subject_key=record.map_id,
                fact_key="dbc.linked_zone_id",
                value=record.linked_zone_id,
                record_type="Map.dbc",
                raw_identifier=record.map_id,
            )
            resolved_maps.append((record, name, map_kind))

        for record, name, map_kind in resolved_maps:
            existing = connection.execute(
                "SELECT name, map_kind FROM maps WHERE map_id = ?", (record.map_id,)
            ).fetchone()
            expected = {"name": name, "map_kind": map_kind}
            if existing is None:
                inserted += 1
            elif _row_changed(existing, expected):
                updated += 1
            connection.execute(
                """
                INSERT INTO maps(map_id, name, map_kind)
                VALUES (?, ?, ?)
                ON CONFLICT(map_id) DO UPDATE SET
                    name = excluded.name,
                    map_kind = excluded.map_kind
                """,
                (record.map_id, name, map_kind),
            )

        resolved_areas: list[tuple[OctoDbcArea, str, int, int | None]] = []
        for record in accepted_areas:
            name = str(
                _select_octodbc_observation(
                    connection,
                    batch_id=batch_id,
                    subject_kind="zone",
                    subject_key=record.zone_id,
                    fact_key="name",
                    value=record.name,
                    record_type="AreaTable.dbc",
                    raw_identifier=record.zone_id,
                )
            )
            map_id = int(
                _select_octodbc_observation(
                    connection,
                    batch_id=batch_id,
                    subject_kind="zone",
                    subject_key=record.zone_id,
                    fact_key="map_id",
                    value=record.map_id,
                    record_type="AreaTable.dbc",
                    raw_identifier=record.zone_id,
                )
            )
            parent_value = _select_octodbc_observation(
                connection,
                batch_id=batch_id,
                subject_kind="zone",
                subject_key=record.zone_id,
                fact_key="parent_zone_id",
                value=record.parent_zone_id,
                record_type="AreaTable.dbc",
                raw_identifier=record.zone_id,
            )
            parent_zone_id = None if parent_value is None else int(parent_value)
            for fact_key, value in (
                ("dbc.explore_flag", record.explore_flag),
                ("dbc.flags", record.flags),
                ("dbc.area_level", record.area_level),
                ("dbc.faction_group_mask", record.faction_group_mask),
                ("dbc.liquid_type_override", record.liquid_type_override),
            ):
                _select_octodbc_observation(
                    connection,
                    batch_id=batch_id,
                    subject_kind="zone",
                    subject_key=record.zone_id,
                    fact_key=fact_key,
                    value=value,
                    record_type="AreaTable.dbc",
                    raw_identifier=record.zone_id,
                )
            resolved_areas.append((record, name, map_id, parent_zone_id))

        # Create all zone identities before assigning parent foreign keys.
        snapshots: dict[int, sqlite3.Row | None] = {}
        for record, name, map_id, _parent_zone_id in resolved_areas:
            snapshots[record.zone_id] = connection.execute(
                "SELECT name, map_id, parent_zone_id FROM zones WHERE zone_id = ?",
                (record.zone_id,),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO zones(zone_id, map_id, name)
                VALUES (?, ?, ?)
                ON CONFLICT(zone_id) DO NOTHING
                """,
                (record.zone_id, map_id, name),
            )

        hierarchy_links = 0
        for record, name, map_id, parent_zone_id in resolved_areas:
            existing = snapshots[record.zone_id]
            expected = {
                "name": name,
                "map_id": map_id,
                "parent_zone_id": parent_zone_id,
            }
            if existing is None:
                inserted += 1
            elif _row_changed(existing, expected):
                updated += 1
            connection.execute(
                """
                UPDATE zones
                SET name = ?, map_id = ?, parent_zone_id = ?
                WHERE zone_id = ?
                """,
                (name, map_id, parent_zone_id, record.zone_id),
            )
            if parent_zone_id is not None:
                hierarchy_links += 1

        details = {
            "canonical_rows_inserted_or_updated": inserted + updated,
            "maps": len(world.maps),
            "zones": len(accepted_areas),
            "hierarchy_links": hierarchy_links,
            "revision_method": (
                "sha256(Map.dbc,AreaTable.dbc)" if source_revision is None else "explicit"
            ),
        }
        if skipped_area_ids:
            details["skipped_unnamed_area_ids"] = list(skipped_area_ids)
        connection.execute(
            """
            UPDATE import_batches
            SET status = 'succeeded',
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                rows_read = ?, rows_accepted = ?, rows_skipped = ?,
                rows_inserted = ?, rows_updated = ?, warning_count = ?,
                details_json = ?
            WHERE id = ?
            """,
            (
                rows_read,
                rows_accepted,
                rows_skipped,
                inserted,
                updated,
                rows_skipped,
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
        source_key=OCTO_DBC_SOURCE_KEY,
        source_revision=revision,
        status="succeeded",
        rows_read=rows_read,
        rows_accepted=rows_accepted,
        rows_skipped=rows_skipped,
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=rows_skipped,
        error_count=0,
        details=details,
    )
