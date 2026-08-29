"""Bounded Octo item-template/stat ingestion from the Vanilla client item cache.

P6-T01 deliberately treats itemcache.wdb as positive client/server observation evidence.
A missing cache record is unknown, never negative evidence authorizing canonical cleanup.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import record_scalar_observation, select_canonical_observation
from octogamedb.importers.summary import ImportSummary

SOURCE_KEY = "octo-itemcache"
SOURCE_DISPLAY_NAME = "Octo client itemcache.wdb"
SOURCE_KIND = "client-cache"
IMPORTER_VERSION = "octo-itemcache/1"
SELECTION_POLICY = "p6-item-template/octo-itemcache"
AUTHORITY_TIER = 0
MAX_ITEM_STATS = 10
MAX_ITEM_DAMAGES = 5
MAX_ITEM_SPELLS = 5
_MANAGED_SELECTION_POLICIES = frozenset(
    {
        SELECTION_POLICY,
        "p6-item-template/octodb",
        "p6-item-template/tortoise-fallback",
        "p6-item-template/cmangos-fallback",
    }
)

_SCALAR_FIELDS = (
    "class_id",
    "subclass_id",
    "quality",
    "inventory_type",
    "item_level",
    "required_level",
    "allowable_class_mask",
    "allowable_race_mask",
    "required_skill_id",
    "required_skill_rank",
    "required_spell_id",
    "required_reputation_faction_id",
    "required_reputation_rank",
    "armor",
    "holy_resistance",
    "fire_resistance",
    "nature_resistance",
    "frost_resistance",
    "shadow_resistance",
    "arcane_resistance",
    "max_durability",
)


class ItemCacheParseError(ValueError):
    """Raised when the cache is not the supported Vanilla 1.12 item-query shape."""


@dataclass(frozen=True)
class ItemCacheHeader:
    signature: str
    client_version: int
    locale: str
    record_size: int
    record_version: int


@dataclass(frozen=True)
class ItemStatSlot:
    slot_index: int
    stat_type: int
    stat_value: int

    def to_json(self) -> dict[str, int]:
        return {
            "slot_index": self.slot_index,
            "stat_type": self.stat_type,
            "stat_value": self.stat_value,
        }


@dataclass(frozen=True)
class ItemCacheRecord:
    item_id: int
    name: str
    class_id: int
    subclass_id: int
    quality: int
    inventory_type: int
    item_level: int
    required_level: int
    allowable_class_mask: int
    allowable_race_mask: int
    required_skill_id: int
    required_skill_rank: int
    required_spell_id: int
    required_reputation_faction_id: int
    required_reputation_rank: int
    armor: int
    holy_resistance: int
    fire_resistance: int
    nature_resistance: int
    frost_resistance: int
    shadow_resistance: int
    arcane_resistance: int
    max_durability: int
    stat_slots: tuple[ItemStatSlot, ...]
    raw_record: bytes

    def scalar_values(self) -> dict[str, int]:
        return {field: int(getattr(self, field)) for field in _SCALAR_FIELDS}


@dataclass(frozen=True)
class ItemCacheSnapshot:
    header: ItemCacheHeader
    records: tuple[ItemCacheRecord, ...]

    @property
    def by_id(self) -> dict[int, ItemCacheRecord]:
        return {record.item_id: record for record in self.records}


class _Reader:
    def __init__(self, payload: bytes, *, label: str):
        self.payload = payload
        self.offset = 0
        self.label = label

    def _take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.payload):
            raise ItemCacheParseError(
                f"{self.label}: truncated at offset {self.offset}; need {size} bytes"
            )
        value = self.payload[self.offset:end]
        self.offset = end
        return value

    def u32(self) -> int:
        return int(struct.unpack("<I", self._take(4))[0])

    def i32(self) -> int:
        return int(struct.unpack("<i", self._take(4))[0])

    def f32(self) -> float:
        return float(struct.unpack("<f", self._take(4))[0])

    def cstring(self) -> str:
        end = self.payload.find(b"\0", self.offset)
        if end < 0:
            raise ItemCacheParseError(f"{self.label}: unterminated string at {self.offset}")
        raw = self.payload[self.offset:end]
        self.offset = end + 1
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            # Vanilla cache strings are byte-oriented. Latin-1 is lossless and avoids guessing a
            # locale-specific Windows code page while preserving source bytes through raw_record.
            return raw.decode("latin-1")

    def finish(self) -> None:
        if self.offset != len(self.payload):
            raise ItemCacheParseError(
                f"{self.label}: unsupported layout; {len(self.payload) - self.offset} trailing bytes"
            )


def _signed_mask(value: int) -> int:
    return value - 0x100000000 if value & 0x80000000 else value


def _parse_record(item_id: int, payload: bytes, raw_record: bytes) -> ItemCacheRecord:
    reader = _Reader(payload, label=f"itemcache record {item_id}")

    class_id = reader.u32()
    subclass_id = reader.u32()
    names = tuple(reader.cstring() for _ in range(4))
    name = names[0]
    reader.u32()  # display info id
    quality = reader.u32()
    reader.u32()  # flags
    reader.u32()  # buy price
    reader.u32()  # sell price
    inventory_type = reader.u32()
    allowable_class_mask = _signed_mask(reader.u32())
    allowable_race_mask = _signed_mask(reader.u32())
    item_level = reader.u32()
    required_level = reader.u32()
    required_skill_id = reader.u32()
    required_skill_rank = reader.u32()
    required_spell_id = reader.u32()
    reader.u32()  # required honor rank
    reader.u32()  # required city rank
    required_reputation_faction_id = reader.u32()
    required_reputation_rank = reader.u32()
    reader.i32()  # max count
    reader.i32()  # stackable
    reader.u32()  # container slots

    stat_slots = tuple(
        ItemStatSlot(slot_index=index, stat_type=reader.u32(), stat_value=reader.i32())
        for index in range(MAX_ITEM_STATS)
    )

    for _ in range(MAX_ITEM_DAMAGES):
        reader.f32()
        reader.f32()
        reader.u32()

    armor = reader.u32()
    holy_resistance = reader.u32()
    fire_resistance = reader.u32()
    nature_resistance = reader.u32()
    frost_resistance = reader.u32()
    shadow_resistance = reader.u32()
    arcane_resistance = reader.u32()
    reader.u32()  # delay
    reader.u32()  # ammo type
    reader.f32()  # ranged mod range (present in 1.12)

    for _ in range(MAX_ITEM_SPELLS):
        reader.u32()  # spell id
        reader.u32()  # trigger
        reader.i32()  # charges
        reader.i32()  # cooldown
        reader.u32()  # category
        reader.i32()  # category cooldown

    reader.u32()  # bonding
    reader.cstring()  # description
    reader.u32()  # page text
    reader.u32()  # language
    reader.u32()  # page material
    reader.u32()  # start quest
    reader.u32()  # lock id
    reader.i32()  # material
    reader.u32()  # sheath
    reader.i32()  # random property
    reader.u32()  # block
    reader.u32()  # item set
    max_durability = reader.u32()
    reader.u32()  # area
    reader.u32()  # map
    reader.u32()  # bag family
    reader.finish()

    return ItemCacheRecord(
        item_id=item_id,
        name=name,
        class_id=class_id,
        subclass_id=subclass_id,
        quality=quality,
        inventory_type=inventory_type,
        item_level=item_level,
        required_level=required_level,
        allowable_class_mask=allowable_class_mask,
        allowable_race_mask=allowable_race_mask,
        required_skill_id=required_skill_id,
        required_skill_rank=required_skill_rank,
        required_spell_id=required_spell_id,
        required_reputation_faction_id=required_reputation_faction_id,
        required_reputation_rank=required_reputation_rank,
        armor=armor,
        holy_resistance=holy_resistance,
        fire_resistance=fire_resistance,
        nature_resistance=nature_resistance,
        frost_resistance=frost_resistance,
        shadow_resistance=shadow_resistance,
        arcane_resistance=arcane_resistance,
        max_durability=max_durability,
        stat_slots=stat_slots,
        raw_record=raw_record,
    )


def parse_itemcache_wdb(path: str | Path) -> ItemCacheSnapshot:
    """Parse a post-1.6 Vanilla itemcache.wdb using the 1.12 query-response layout."""

    cache_path = Path(path)
    data = cache_path.read_bytes()
    if len(data) < 20:
        raise ItemCacheParseError("itemcache.wdb is shorter than the 20-byte Vanilla header")

    signature_bytes = data[:4]
    if signature_bytes not in {b"BDIW", b"WIDB"}:
        raise ItemCacheParseError(
            f"unexpected item-cache signature {signature_bytes!r}; expected BDIW/WIDB"
        )
    client_version = struct.unpack_from("<I", data, 4)[0]
    locale_bytes = data[8:12]
    try:
        locale = locale_bytes[::-1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ItemCacheParseError("itemcache locale header is not ASCII") from exc
    record_size, record_version = struct.unpack_from("<II", data, 12)
    header = ItemCacheHeader(
        signature=signature_bytes.decode("ascii"),
        client_version=int(client_version),
        locale=locale,
        record_size=int(record_size),
        record_version=int(record_version),
    )

    offset = 20
    records: list[ItemCacheRecord] = []
    seen: set[int] = set()
    terminated = False
    while offset < len(data):
        if len(data) - offset < 8:
            raise ItemCacheParseError("truncated itemcache record prefix")
        item_id, length = struct.unpack_from("<II", data, offset)
        prefix_start = offset
        offset += 8
        if item_id == 0 and length == 0:
            terminated = True
            if any(data[offset:]):
                raise ItemCacheParseError("non-zero bytes after itemcache terminator")
            break
        if item_id == 0 or length == 0:
            raise ItemCacheParseError(
                f"invalid itemcache record prefix item_id={item_id}, length={length}"
            )
        end = offset + int(length)
        if end > len(data):
            raise ItemCacheParseError(f"itemcache record {item_id} exceeds file length")
        if int(item_id) in seen:
            raise ItemCacheParseError(f"duplicate itemcache record for item {item_id}")
        payload = data[offset:end]
        raw_record = data[prefix_start:end]
        records.append(_parse_record(int(item_id), payload, raw_record))
        seen.add(int(item_id))
        offset = end

    if not terminated and offset != len(data):
        raise ItemCacheParseError("itemcache parse did not terminate cleanly")

    return ItemCacheSnapshot(header=header, records=tuple(records))


def compute_itemcache_slice_revision(
    snapshot: ItemCacheSnapshot, item_ids: Iterable[int]
) -> str:
    """Hash only the selected records plus header semantics, not unrelated cache growth."""

    requested = tuple(sorted({int(item_id) for item_id in item_ids}))
    by_id = snapshot.by_id
    digest = hashlib.sha256()
    digest.update(b"octogamedb-itemcache-slice-v1\0")
    digest.update(snapshot.header.signature.encode("ascii"))
    digest.update(
        struct.pack(
            "<III",
            snapshot.header.client_version,
            snapshot.header.record_size,
            snapshot.header.record_version,
        )
    )
    digest.update(snapshot.header.locale.encode("ascii", errors="strict"))
    digest.update(b"\0")
    for item_id in requested:
        digest.update(struct.pack("<I", item_id))
        record = by_id.get(item_id)
        if record is None:
            digest.update(b"MISSING\0")
        else:
            digest.update(hashlib.sha256(record.raw_record).digest())
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
        (SOURCE_KEY, SOURCE_DISPLAY_NAME, SOURCE_KIND, source_path),
    )
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (SOURCE_KEY,)
    ).fetchone()
    if row is None:
        raise RuntimeError("Octo itemcache source registration failed")
    return int(row["id"])


def _selected_observation_value(
    connection: sqlite3.Connection, *, observation_id: int
) -> Any:
    row = connection.execute(
        """
        SELECT so.observation_group_id, so.authority_tier, ds.source_key
        FROM source_observations AS so
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE so.id = ?
        """,
        (observation_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"observation {observation_id} disappeared")
    group_id = int(row["observation_group_id"])
    new_tier = 1_000_000 if row["authority_tier"] is None else int(row["authority_tier"])
    new_source = str(row["source_key"])

    current = connection.execute(
        """
        SELECT cs.observation_id, cs.selection_policy, so.authority_tier, ds.source_key
        FROM canonical_selections AS cs
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE cs.observation_group_id = ?
        """,
        (group_id,),
    ).fetchone()

    should_select = current is None
    reason = "Selected because this P6 item-template fact had no prior canonical selection."
    if current is not None and int(current["observation_id"]) != observation_id:
        policy = None if current["selection_policy"] is None else str(current["selection_policy"])
        current_tier = (
            1_000_000 if current["authority_tier"] is None else int(current["authority_tier"])
        )
        current_source = str(current["source_key"])
        if policy in _MANAGED_SELECTION_POLICIES:
            if new_tier < current_tier:
                should_select = True
                reason = (
                    "Selected by the P6 field-specific authority policy because direct Octo "
                    "item-query evidence outranks the managed fallback observation."
                )
            elif new_tier == current_tier and new_source == current_source:
                should_select = True
                reason = (
                    "Refreshed the managed P6 selection from a newer deterministic snapshot of "
                    "the same source family."
                )
        # Unknown/custom selection policies are intentionally protected.

    if should_select:
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy=SELECTION_POLICY,
            selection_reason=reason,
        )

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
        raise RuntimeError("P6 item-template fact has no canonical selection")
    return json.loads(str(selected["value_json"]))


def _observe_scalar(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    item_id: int,
    field: str,
    value: int,
) -> int:
    observation_id = record_scalar_observation(
        connection,
        subject_kind="item",
        subject_key=item_id,
        fact_key=f"template.{field}",
        import_batch_id=batch_id,
        value=value,
        source_record_type="item_query_cache",
        raw_identifier=str(item_id),
        authority_tier=AUTHORITY_TIER,
    )
    selected = _selected_observation_value(connection, observation_id=observation_id)
    if isinstance(selected, bool) or not isinstance(selected, int):
        raise TypeError(f"selected template.{field} must be an integer")
    return int(selected)


def _observe_stat_slots(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    record: ItemCacheRecord,
) -> tuple[ItemStatSlot, ...]:
    payload = [slot.to_json() for slot in record.stat_slots]
    observation_id = record_scalar_observation(
        connection,
        subject_kind="item",
        subject_key=record.item_id,
        fact_key="template.stat_slots",
        import_batch_id=batch_id,
        value=payload,
        source_record_type="item_query_cache",
        raw_identifier=str(record.item_id),
        authority_tier=AUTHORITY_TIER,
    )
    selected = _selected_observation_value(connection, observation_id=observation_id)
    if not isinstance(selected, list) or len(selected) != MAX_ITEM_STATS:
        raise TypeError("selected template.stat_slots must be the complete 10-slot list")
    slots: list[ItemStatSlot] = []
    seen: set[int] = set()
    for entry in selected:
        if not isinstance(entry, dict):
            raise TypeError("selected stat slot must be an object")
        try:
            slot_index = entry["slot_index"]
            stat_type = entry["stat_type"]
            stat_value = entry["stat_value"]
        except KeyError as exc:
            raise TypeError("selected stat slot is missing a required key") from exc
        values = (slot_index, stat_type, stat_value)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("selected stat slot values must be integers")
        if not 0 <= slot_index < MAX_ITEM_STATS or slot_index in seen:
            raise ValueError("selected stat slots must contain unique indices 0..9")
        seen.add(slot_index)
        slots.append(ItemStatSlot(slot_index, stat_type, stat_value))
    if seen != set(range(MAX_ITEM_STATS)):
        raise ValueError("selected stat slots must cover every source slot 0..9")
    return tuple(sorted(slots, key=lambda slot: slot.slot_index))


def _materialized_stat_rows(slots: tuple[ItemStatSlot, ...]) -> tuple[tuple[int, int, int], ...]:
    # Preserve all ten slots in provenance. The query table stores only non-empty modifiers.
    return tuple(
        (slot.slot_index, slot.stat_type, slot.stat_value)
        for slot in slots
        if slot.stat_type != 0 or slot.stat_value != 0
    )


def import_octo_itemcache_slice(
    connection: sqlite3.Connection,
    *,
    source_path: str | Path,
    item_ids: Iterable[int],
) -> ImportSummary:
    """Import only explicitly requested item IDs from a local Octo itemcache.wdb snapshot."""

    requested = tuple(sorted({int(item_id) for item_id in item_ids}))
    if not requested:
        raise ValueError("item_ids must contain at least one native item ID")
    if any(item_id <= 0 for item_id in requested):
        raise ValueError("item_ids must be positive integers")

    source_path = Path(source_path)
    snapshot = parse_itemcache_wdb(source_path)
    revision = compute_itemcache_slice_revision(snapshot, requested)
    by_id = snapshot.by_id
    source_id = _ensure_source(connection, str(source_path))
    cursor = connection.execute(
        """
        INSERT INTO import_batches(source_id, source_revision, status, importer_version, rows_read)
        VALUES (?, ?, 'running', ?, ?)
        """,
        (source_id, revision, IMPORTER_VERSION, len(requested)),
    )
    batch_id = int(cursor.lastrowid)

    inserted = 0
    updated = 0
    missing_cache_ids = [item_id for item_id in requested if item_id not in by_id]
    unresolved_item_ids: list[int] = []
    accepted = 0

    try:
        for item_id in requested:
            record = by_id.get(item_id)
            if record is None:
                continue
            accepted += 1
            selected_scalars = {
                field: _observe_scalar(
                    connection,
                    batch_id=batch_id,
                    item_id=item_id,
                    field=field,
                    value=value,
                )
                for field, value in record.scalar_values().items()
            }
            selected_stats = _observe_stat_slots(connection, batch_id=batch_id, record=record)

            canonical_item = connection.execute(
                "SELECT 1 FROM items WHERE item_id = ?", (item_id,)
            ).fetchone()
            if canonical_item is None:
                unresolved_item_ids.append(item_id)
                continue

            existing = connection.execute(
                "SELECT * FROM item_templates WHERE item_id = ?", (item_id,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    f"""
                    INSERT INTO item_templates(item_id, {', '.join(_SCALAR_FIELDS)})
                    VALUES ({', '.join('?' for _ in range(len(_SCALAR_FIELDS) + 1))})
                    """,
                    (item_id, *(selected_scalars[field] for field in _SCALAR_FIELDS)),
                )
                inserted += 1
            else:
                changed = any(
                    existing[field] != selected_scalars[field] for field in _SCALAR_FIELDS
                )
                if changed:
                    assignments = ", ".join(f"{field} = ?" for field in _SCALAR_FIELDS)
                    connection.execute(
                        f"UPDATE item_templates SET {assignments} WHERE item_id = ?",
                        (*(selected_scalars[field] for field in _SCALAR_FIELDS), item_id),
                    )
                    updated += 1

            expected_stats = _materialized_stat_rows(selected_stats)
            current_stats = tuple(
                (int(row["slot_index"]), int(row["stat_type"]), int(row["stat_value"]))
                for row in connection.execute(
                    """
                    SELECT slot_index, stat_type, stat_value
                    FROM item_stat_modifiers
                    WHERE item_id = ?
                    ORDER BY slot_index
                    """,
                    (item_id,),
                ).fetchall()
            )
            if current_stats != expected_stats:
                connection.execute("DELETE FROM item_stat_modifiers WHERE item_id = ?", (item_id,))
                connection.executemany(
                    """
                    INSERT INTO item_stat_modifiers(item_id, slot_index, stat_type, stat_value)
                    VALUES (?, ?, ?, ?)
                    """,
                    ((item_id, *row) for row in expected_stats),
                )
                if current_stats:
                    updated += 1
                else:
                    inserted += len(expected_stats)

        details = {
            "client_version": snapshot.header.client_version,
            "locale": snapshot.header.locale,
            "record_version": snapshot.header.record_version,
            "requested_item_ids": list(requested),
            "missing_cache_item_ids": missing_cache_ids,
            "unresolved_canonical_item_ids": unresolved_item_ids,
            "partial_positive_source": True,
        }
        warning_count = len(missing_cache_ids) + len(unresolved_item_ids)
        connection.execute(
            """
            UPDATE import_batches
            SET status = 'succeeded',
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                rows_accepted = ?, rows_skipped = ?, rows_inserted = ?, rows_updated = ?,
                warning_count = ?, details_json = ?
            WHERE id = ?
            """,
            (
                accepted,
                len(missing_cache_ids),
                inserted,
                updated,
                warning_count,
                json.dumps(details, sort_keys=True, separators=(",", ":")),
                batch_id,
            ),
        )
    except Exception as exc:
        connection.execute(
            """
            UPDATE import_batches
            SET status = 'failed', finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                error_count = 1, details_json = ?
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
        source_key=SOURCE_KEY,
        source_revision=revision,
        status="succeeded",
        rows_read=len(requested),
        rows_accepted=accepted,
        rows_skipped=len(missing_cache_ids),
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=warning_count,
        error_count=0,
        details=details,
    )
