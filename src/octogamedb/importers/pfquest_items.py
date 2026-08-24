"""pfQuest item/direct-loot importer for the first P2 vertical slice."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import (
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.pfquest_world import (
    PFQUEST_SOURCE_KEY,
    PFQUEST_SOURCE_URL,
    PfQuestParseError,
    parse_pfquest_assignment,
)
from octogamedb.importers.summary import ImportSummary

IMPORTER_VERSION = "pfquest-items/2"
_ITEM_FILES = (
    "db/items.lua",
    "db/enUS/items.lua",
    "db/enUS/units.lua",
    "db/enUS/objects.lua",
)


class PfQuestItemImportError(RuntimeError):
    """Raised when item evidence cannot be materialized without inventing source identity."""


@dataclass(frozen=True)
class PfQuestItem:
    item_id: int
    name: str
    creature_loot: tuple[tuple[int, float], ...]
    gameobject_loot: tuple[tuple[int, float], ...]
    reference_loot_count: int
    vendor_count: int


@dataclass(frozen=True)
class PfQuestItemSlice:
    items: tuple[PfQuestItem, ...]
    rows_read: int
    rows_skipped: int
    creature_names: tuple[tuple[int, str], ...]
    gameobject_names: tuple[tuple[int, str], ...]


def compute_pfquest_items_revision(source_root: str | Path) -> str:
    """Return a deterministic revision for item data plus referenced-source name inputs."""

    root = Path(source_root)
    missing = [relative for relative in _ITEM_FILES if not (root / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"missing required pfQuest item file: {root / missing[0]}")

    digest = hashlib.sha256()
    for relative in _ITEM_FILES:
        path = root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return f"sha256:{digest.hexdigest()}"


def _numeric_links(value: Any, *, label: str) -> tuple[tuple[int, float], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise PfQuestParseError(f"{label} must be a Lua table")

    links: list[tuple[int, float]] = []
    for source_id in sorted(key for key in value if isinstance(key, int)):
        chance = value[source_id]
        if isinstance(chance, bool) or not isinstance(chance, (int, float)):
            raise PfQuestParseError(f"{label}[{source_id}] chance must be numeric")
        chance_percent = float(chance)
        if not 0.0 <= chance_percent <= 100.0:
            raise PfQuestParseError(
                f"{label}[{source_id}] chance must be between 0 and 100 percent"
            )
        links.append((int(source_id), chance_percent))
    return tuple(links)


def _count_numeric_members(value: Any, *, label: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, dict):
        raise PfQuestParseError(f"{label} must be a Lua table")
    return sum(1 for key in value if isinstance(key, int))


def load_pfquest_item_slice(source_root: str | Path) -> PfQuestItemSlice:
    """Load item names plus direct creature/game-object loot relations from pfQuest."""

    root = Path(source_root)
    item_data = parse_pfquest_assignment(
        (root / "db" / "items.lua").read_text(encoding="utf-8"),
        domain="items",
        table_name="data",
    )
    item_names = parse_pfquest_assignment(
        (root / "db" / "enUS" / "items.lua").read_text(encoding="utf-8"),
        domain="items",
        table_name="enUS",
    )
    unit_names = parse_pfquest_assignment(
        (root / "db" / "enUS" / "units.lua").read_text(encoding="utf-8"),
        domain="units",
        table_name="enUS",
    )
    object_names = parse_pfquest_assignment(
        (root / "db" / "enUS" / "objects.lua").read_text(encoding="utf-8"),
        domain="objects",
        table_name="enUS",
    )

    item_ids = sorted(
        {key for key in item_data if isinstance(key, int)}
        | {key for key in item_names if isinstance(key, int)}
    )
    items: list[PfQuestItem] = []
    skipped = 0
    for item_id in item_ids:
        name = item_names.get(item_id)
        if not isinstance(name, str) or not name.strip():
            skipped += 1
            continue
        record = item_data.get(item_id, {})
        if not isinstance(record, dict):
            raise PfQuestParseError(f"item[{item_id}] must be a Lua table")
        items.append(
            PfQuestItem(
                item_id=int(item_id),
                name=name.strip(),
                creature_loot=_numeric_links(record.get("U"), label=f"item[{item_id}].U"),
                gameobject_loot=_numeric_links(record.get("O"), label=f"item[{item_id}].O"),
                reference_loot_count=_count_numeric_members(
                    record.get("R"), label=f"item[{item_id}].R"
                ),
                vendor_count=_count_numeric_members(record.get("V"), label=f"item[{item_id}].V"),
            )
        )
    referenced_creature_ids = sorted(
        {source_id for item in items for source_id, _ in item.creature_loot}
    )
    referenced_gameobject_ids = sorted(
        {source_id for item in items for source_id, _ in item.gameobject_loot}
    )

    creature_names = tuple(
        (source_id, name.strip())
        for source_id in referenced_creature_ids
        if isinstance((name := unit_names.get(source_id)), str) and name.strip()
    )
    gameobject_names = tuple(
        (source_id, name.strip())
        for source_id in referenced_gameobject_ids
        if isinstance((name := object_names.get(source_id)), str) and name.strip()
    )
    return PfQuestItemSlice(
        items=tuple(items),
        rows_read=len(item_ids),
        rows_skipped=skipped,
        creature_names=creature_names,
        gameobject_names=gameobject_names,
    )


def _ensure_source(connection: sqlite3.Connection, source_path: str) -> int:
    connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind, source_url, source_path)
        VALUES (?, 'pfQuest', 'lua-addon', ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            display_name = excluded.display_name,
            source_kind = excluded.source_kind,
            source_url = excluded.source_url,
            source_path = excluded.source_path,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (PFQUEST_SOURCE_KEY, PFQUEST_SOURCE_URL, source_path),
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
    group = connection.execute(
        "SELECT observation_group_id FROM source_observations WHERE id = ?",
        (observation_id,),
    ).fetchone()
    if group is None:
        raise RuntimeError(f"observation {observation_id} disappeared")
    group_id = int(group["observation_group_id"])
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


def _observe_name(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    item: PfQuestItem,
) -> str:
    observation_id = record_scalar_observation(
        connection,
        subject_kind="item",
        subject_key=item.item_id,
        fact_key="name",
        import_batch_id=batch_id,
        value=item.name,
        source_record_type="item",
        raw_identifier=str(item.item_id),
    )
    return str(
        _selected_value(
            connection,
            observation_id=observation_id,
            selection_reason=(
                "Selected automatically because this item name had no prior selection."
            ),
        )
    )


def _observe_loot_relation(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    item_id: int,
    source_kind: str,
    source_id: int,
    chance_percent: float,
) -> float:
    observation_id = record_relation_observation(
        connection,
        subject_kind="item",
        subject_key=item_id,
        fact_key="loot_source",
        import_batch_id=batch_id,
        target_kind=source_kind,
        target_key=source_id,
        relation_instance_key=f"{source_kind}:{source_id}",
        attributes={"chance_percent": chance_percent},
        source_record_type="item",
        raw_identifier=f"{item_id}:{source_kind}:{source_id}",
    )
    payload = _selected_value(
        connection,
        observation_id=observation_id,
        selection_reason=(
            "Selected automatically because this direct loot relation had no prior selection."
        ),
    )
    target = payload.get("target", {})
    if target.get("kind") != source_kind or str(target.get("key")) != str(source_id):
        raise RuntimeError("selected loot relation target does not match its relation instance")
    attributes = payload.get("attributes", {})
    chance = attributes.get("chance_percent")
    if isinstance(chance, bool) or not isinstance(chance, (int, float)):
        raise TypeError("selected loot relation has no numeric chance_percent")
    return float(chance)


def _missing_world_templates(
    connection: sqlite3.Connection,
    slice_data: PfQuestItemSlice,
) -> tuple[list[int], list[int]]:
    creature_ids = sorted(
        {source_id for item in slice_data.items for source_id, _ in item.creature_loot}
    )
    gameobject_ids = sorted(
        {source_id for item in slice_data.items for source_id, _ in item.gameobject_loot}
    )
    existing_creatures = {
        int(row[0])
        for row in connection.execute("SELECT creature_id FROM creatures").fetchall()
    }
    existing_gameobjects = {
        int(row[0])
        for row in connection.execute("SELECT gameobject_id FROM gameobjects").fetchall()
    }
    return (
        [source_id for source_id in creature_ids if source_id not in existing_creatures],
        [source_id for source_id in gameobject_ids if source_id not in existing_gameobjects],
    )


def _observe_source_name(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_id: int,
    name: str,
) -> str:
    observation_id = record_scalar_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_id,
        fact_key="name",
        import_batch_id=batch_id,
        value=name,
        source_record_type=f"{subject_kind}_name",
        raw_identifier=str(subject_id),
    )
    return str(
        _selected_value(
            connection,
            observation_id=observation_id,
            selection_reason=(
                "Selected automatically because this loot-source template name had no prior "
                "canonical selection."
            ),
        )
    )


def _materialize_relation_only_templates(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    slice_data: PfQuestItemSlice,
) -> tuple[int, int]:
    """Create named source templates required by direct-loot relations, without inventing spawns."""

    missing_creatures, missing_gameobjects = _missing_world_templates(connection, slice_data)
    creature_names = dict(slice_data.creature_names)
    gameobject_names = dict(slice_data.gameobject_names)
    unresolved_creatures = [
        source_id for source_id in missing_creatures if source_id not in creature_names
    ]
    unresolved_gameobjects = [
        source_id for source_id in missing_gameobjects if source_id not in gameobject_names
    ]
    if unresolved_creatures or unresolved_gameobjects:
        raise PfQuestItemImportError(
            "pfQuest direct-loot targets are absent from the canonical P1 world and have no "
            "pfQuest enUS identity; "
            f"missing creature IDs={unresolved_creatures}, "
            f"missing gameobject IDs={unresolved_gameobjects}"
        )

    for creature_id in missing_creatures:
        canonical_name = _observe_source_name(
            connection,
            batch_id=batch_id,
            subject_kind="creature",
            subject_id=creature_id,
            name=creature_names[creature_id],
        )
        connection.execute(
            "INSERT INTO creatures(creature_id, name) VALUES (?, ?)",
            (creature_id, canonical_name),
        )

    for gameobject_id in missing_gameobjects:
        canonical_name = _observe_source_name(
            connection,
            batch_id=batch_id,
            subject_kind="gameobject",
            subject_id=gameobject_id,
            name=gameobject_names[gameobject_id],
        )
        connection.execute(
            "INSERT INTO gameobjects(gameobject_id, name) VALUES (?, ?)",
            (gameobject_id, canonical_name),
        )

    return len(missing_creatures), len(missing_gameobjects)


def _row_changed(row: sqlite3.Row | None, expected: dict[str, Any]) -> bool:
    if row is None:
        return False
    return any(row[key] != value for key, value in expected.items())


def import_pfquest_items(
    connection: sqlite3.Connection,
    *,
    source_root: str | Path,
    source_revision: str,
) -> ImportSummary:
    """Import pfQuest item identity and direct U/O loot relations with provenance."""

    source_revision = source_revision.strip()
    if not source_revision:
        raise ValueError("source_revision must not be blank")

    slice_data = load_pfquest_item_slice(source_root)
    source_id = _ensure_source(connection, str(Path(source_root)))
    cursor = connection.execute(
        """
        INSERT INTO import_batches(
            source_id, source_revision, status, importer_version, rows_read
        )
        VALUES (?, ?, 'running', ?, ?)
        """,
        (source_id, source_revision, IMPORTER_VERSION, slice_data.rows_read),
    )
    batch_id = int(cursor.lastrowid)
    inserted = 0
    updated = 0

    try:
        relation_only_creatures, relation_only_gameobjects = _materialize_relation_only_templates(
            connection,
            batch_id=batch_id,
            slice_data=slice_data,
        )
        inserted += relation_only_creatures + relation_only_gameobjects

        creature_links = 0
        gameobject_links = 0
        deferred_reference_links = 0
        deferred_vendor_links = 0
        for item in slice_data.items:
            name = _observe_name(connection, batch_id=batch_id, item=item)
            existing_item = connection.execute(
                "SELECT name FROM items WHERE item_id = ?",
                (item.item_id,),
            ).fetchone()
            if existing_item is None:
                inserted += 1
            elif _row_changed(existing_item, {"name": name}):
                updated += 1
            connection.execute(
                """
                INSERT INTO items(item_id, name)
                VALUES (?, ?)
                ON CONFLICT(item_id) DO UPDATE SET name = excluded.name
                """,
                (item.item_id, name),
            )

            for creature_id, chance_percent in item.creature_loot:
                chance = _observe_loot_relation(
                    connection,
                    batch_id=batch_id,
                    item_id=item.item_id,
                    source_kind="creature",
                    source_id=creature_id,
                    chance_percent=chance_percent,
                )
                existing = connection.execute(
                    """
                    SELECT chance_percent FROM creature_loot
                    WHERE creature_id = ? AND item_id = ?
                    """,
                    (creature_id, item.item_id),
                ).fetchone()
                if existing is None:
                    inserted += 1
                elif _row_changed(existing, {"chance_percent": chance}):
                    updated += 1
                connection.execute(
                    """
                    INSERT INTO creature_loot(creature_id, item_id, chance_percent)
                    VALUES (?, ?, ?)
                    ON CONFLICT(creature_id, item_id) DO UPDATE SET
                        chance_percent = excluded.chance_percent
                    """,
                    (creature_id, item.item_id, chance),
                )
                creature_links += 1

            for gameobject_id, chance_percent in item.gameobject_loot:
                chance = _observe_loot_relation(
                    connection,
                    batch_id=batch_id,
                    item_id=item.item_id,
                    source_kind="gameobject",
                    source_id=gameobject_id,
                    chance_percent=chance_percent,
                )
                existing = connection.execute(
                    """
                    SELECT chance_percent FROM gameobject_loot
                    WHERE gameobject_id = ? AND item_id = ?
                    """,
                    (gameobject_id, item.item_id),
                ).fetchone()
                if existing is None:
                    inserted += 1
                elif _row_changed(existing, {"chance_percent": chance}):
                    updated += 1
                connection.execute(
                    """
                    INSERT INTO gameobject_loot(gameobject_id, item_id, chance_percent)
                    VALUES (?, ?, ?)
                    ON CONFLICT(gameobject_id, item_id) DO UPDATE SET
                        chance_percent = excluded.chance_percent
                    """,
                    (gameobject_id, item.item_id, chance),
                )
                gameobject_links += 1

            deferred_reference_links += item.reference_loot_count
            deferred_vendor_links += item.vendor_count

        accepted = len(slice_data.items)
        details = {
            "items": accepted,
            "creature_loot_links": creature_links,
            "gameobject_loot_links": gameobject_links,
            "deferred_reference_loot_links": deferred_reference_links,
            "deferred_vendor_links": deferred_vendor_links,
            "items_without_enus_name": slice_data.rows_skipped,
            "relation_only_creature_templates": relation_only_creatures,
            "relation_only_gameobject_templates": relation_only_gameobjects,
        }
        connection.execute(
            """
            UPDATE import_batches
            SET status = 'succeeded',
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                rows_read = ?,
                rows_accepted = ?,
                rows_skipped = ?,
                rows_inserted = ?,
                rows_updated = ?,
                details_json = ?
            WHERE id = ?
            """,
            (
                slice_data.rows_read,
                accepted,
                slice_data.rows_skipped,
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
        rows_read=slice_data.rows_read,
        rows_accepted=len(slice_data.items),
        rows_skipped=slice_data.rows_skipped,
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=0,
        error_count=0,
        details=details,
    )
