"""pfQuest item/loot/vendor importer for the bounded P2 acquisition slice."""

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

IMPORTER_VERSION = "pfquest-items/4"
_ITEM_FILES = (
    "db/items.lua",
    "db/refloot.lua",
    "db/enUS/items.lua",
    "db/enUS/units.lua",
    "db/enUS/objects.lua",
)


class PfQuestItemImportError(RuntimeError):
    """Raised when item acquisition evidence lacks a materializable source identity."""


@dataclass(frozen=True)
class PfQuestReferenceLoot:
    reference_loot_id: int
    creature_memberships: tuple[tuple[int, float], ...]
    gameobject_memberships: tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class PfQuestItem:
    item_id: int
    name: str
    creature_loot: tuple[tuple[int, float], ...]
    gameobject_loot: tuple[tuple[int, float], ...]
    reference_loot: tuple[tuple[int, float], ...]
    vendors: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class PfQuestItemSlice:
    items: tuple[PfQuestItem, ...]
    reference_loot: tuple[PfQuestReferenceLoot, ...]
    rows_read: int
    rows_skipped: int
    creature_names: tuple[tuple[int, str], ...]
    gameobject_names: tuple[tuple[int, str], ...]
    missing_reference_ids: tuple[int, ...]


def compute_pfquest_items_revision(source_root: str | Path) -> str:
    """Return a deterministic revision for item/reference data plus source identity inputs."""

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
    """Parse ``native_id -> percentage`` relations."""

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


def _numeric_vendor_links(value: Any, *, label: str) -> tuple[tuple[int, int], ...]:
    """Parse pfQuest ``V`` as ``vendor creature ID -> source maxcount``.

    At the pinned pfQuest revision the extractor copies ``npc_vendor.maxcount`` (and vendor-template
    ``maxcount``) directly into ``V``. The value is preserved without interpreting zero or positive
    values as a project-level stock/restock policy.
    """

    if value is None:
        return ()
    if not isinstance(value, dict):
        raise PfQuestParseError(f"{label} must be a Lua table")

    links: list[tuple[int, int]] = []
    for vendor_id in sorted(key for key in value if isinstance(key, int)):
        max_count = value[vendor_id]
        if isinstance(max_count, bool):
            raise PfQuestParseError(f"{label}[{vendor_id}] maxcount must be an integer")
        if isinstance(max_count, float) and max_count.is_integer():
            max_count = int(max_count)
        if not isinstance(max_count, int):
            raise PfQuestParseError(f"{label}[{vendor_id}] maxcount must be an integer")
        if max_count < 0:
            raise PfQuestParseError(f"{label}[{vendor_id}] maxcount must be non-negative")
        links.append((int(vendor_id), int(max_count)))
    return tuple(links)


def _numeric_memberships(value: Any, *, label: str) -> tuple[tuple[int, float], ...]:
    """Parse a pfQuest refloot U/O membership map.

    The numeric value is preserved for provenance only. At the pinned pfQuest revision the client
    code iterates the keys and does not use this value as a probability or weight.
    """

    if value is None:
        return ()
    if not isinstance(value, dict):
        raise PfQuestParseError(f"{label} must be a Lua table")

    members: list[tuple[int, float]] = []
    for source_id in sorted(key for key in value if isinstance(key, int)):
        marker = value[source_id]
        if isinstance(marker, bool) or not isinstance(marker, (int, float)):
            raise PfQuestParseError(f"{label}[{source_id}] membership value must be numeric")
        members.append((int(source_id), float(marker)))
    return tuple(members)


def _parse_reference_definition(reference_id: int, value: Any) -> PfQuestReferenceLoot:
    if not isinstance(value, dict):
        raise PfQuestParseError(f"refloot[{reference_id}] must be a Lua table")

    # The pinned pfQuest SearchItemID implementation performs exactly one expansion from item.R
    # into refloot.U/refloot.O. A nested R is therefore unsupported source shape, not a recursive
    # reference graph to guess at.
    if "R" in value:
        raise PfQuestParseError(
            f"refloot[{reference_id}].R is unsupported: pinned pfQuest reference loot is one-level"
        )

    return PfQuestReferenceLoot(
        reference_loot_id=reference_id,
        creature_memberships=_numeric_memberships(
            value.get("U"), label=f"refloot[{reference_id}].U"
        ),
        gameobject_memberships=_numeric_memberships(
            value.get("O"), label=f"refloot[{reference_id}].O"
        ),
    )


def load_pfquest_item_slice(source_root: str | Path) -> PfQuestItemSlice:
    """Load item names plus direct, reference-loot, and vendor acquisition relations."""

    root = Path(source_root)
    item_data = parse_pfquest_assignment(
        (root / "db" / "items.lua").read_text(encoding="utf-8"),
        domain="items",
        table_name="data",
    )
    reference_data = parse_pfquest_assignment(
        (root / "db" / "refloot.lua").read_text(encoding="utf-8"),
        domain="refloot",
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
                reference_loot=_numeric_links(record.get("R"), label=f"item[{item_id}].R"),
                vendors=_numeric_vendor_links(record.get("V"), label=f"item[{item_id}].V"),
            )
        )

    referenced_reference_ids = sorted(
        {reference_id for item in items for reference_id, _ in item.reference_loot}
    )
    reference_loot: list[PfQuestReferenceLoot] = []
    missing_reference_ids: list[int] = []
    for reference_id in referenced_reference_ids:
        raw = reference_data.get(reference_id)
        if raw is None:
            missing_reference_ids.append(reference_id)
            continue
        reference_loot.append(_parse_reference_definition(reference_id, raw))

    reference_by_id = {entry.reference_loot_id: entry for entry in reference_loot}
    direct_creatures = {source_id for item in items for source_id, _ in item.creature_loot}
    direct_gameobjects = {source_id for item in items for source_id, _ in item.gameobject_loot}
    vendor_creatures = {vendor_id for item in items for vendor_id, _ in item.vendors}
    referenced_creatures = {
        source_id
        for reference_id in referenced_reference_ids
        if (definition := reference_by_id.get(reference_id)) is not None
        for source_id, _ in definition.creature_memberships
    }
    referenced_gameobjects = {
        source_id
        for reference_id in referenced_reference_ids
        if (definition := reference_by_id.get(reference_id)) is not None
        for source_id, _ in definition.gameobject_memberships
    }

    all_creature_ids = sorted(direct_creatures | referenced_creatures | vendor_creatures)
    all_gameobject_ids = sorted(direct_gameobjects | referenced_gameobjects)
    creature_names = tuple(
        (source_id, name.strip())
        for source_id in all_creature_ids
        if isinstance((name := unit_names.get(source_id)), str) and name.strip()
    )
    gameobject_names = tuple(
        (source_id, name.strip())
        for source_id in all_gameobject_ids
        if isinstance((name := object_names.get(source_id)), str) and name.strip()
    )

    return PfQuestItemSlice(
        items=tuple(items),
        reference_loot=tuple(reference_loot),
        rows_read=len(item_ids),
        rows_skipped=skipped,
        creature_names=creature_names,
        gameobject_names=gameobject_names,
        missing_reference_ids=tuple(missing_reference_ids),
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


def _observe_reference_relation(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    item_id: int,
    reference_loot_id: int,
    chance_percent: float,
) -> float:
    observation_id = record_relation_observation(
        connection,
        subject_kind="item",
        subject_key=item_id,
        fact_key="loot_reference",
        import_batch_id=batch_id,
        target_kind="loot_reference",
        target_key=reference_loot_id,
        relation_instance_key=f"reference:{reference_loot_id}",
        attributes={"chance_percent": chance_percent},
        source_record_type="item_reference_loot",
        raw_identifier=f"{item_id}:R:{reference_loot_id}",
    )
    payload = _selected_value(
        connection,
        observation_id=observation_id,
        selection_reason=(
            "Selected automatically because this item reference-loot relation had no prior "
            "selection."
        ),
    )
    target = payload.get("target", {})
    if target.get("kind") != "loot_reference" or str(target.get("key")) != str(
        reference_loot_id
    ):
        raise RuntimeError("selected reference-loot relation target does not match its instance")
    chance = payload.get("attributes", {}).get("chance_percent")
    if isinstance(chance, bool) or not isinstance(chance, (int, float)):
        raise TypeError("selected reference-loot relation has no numeric chance_percent")
    return float(chance)


def _observe_vendor_relation(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    item_id: int,
    vendor_id: int,
    max_count: int,
) -> int:
    observation_id = record_relation_observation(
        connection,
        subject_kind="item",
        subject_key=item_id,
        fact_key="vendor_source",
        import_batch_id=batch_id,
        target_kind="creature",
        target_key=vendor_id,
        relation_instance_key=f"creature:{vendor_id}",
        attributes={"max_count": max_count},
        source_record_type="item_vendor",
        raw_identifier=f"{item_id}:V:{vendor_id}",
    )
    payload = _selected_value(
        connection,
        observation_id=observation_id,
        selection_reason=(
            "Selected automatically because this item/vendor relation had no prior selection."
        ),
    )
    target = payload.get("target", {})
    if target.get("kind") != "creature" or str(target.get("key")) != str(vendor_id):
        raise RuntimeError("selected vendor relation target does not match its relation instance")
    selected_max_count = payload.get("attributes", {}).get("max_count")
    if (
        isinstance(selected_max_count, bool)
        or not isinstance(selected_max_count, int)
        or selected_max_count < 0
    ):
        raise TypeError("selected vendor relation has no non-negative integer max_count")
    return selected_max_count


def _observe_reference_membership(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    reference_loot_id: int,
    source_kind: str,
    source_id: int,
    membership_value: float,
) -> None:
    observation_id = record_relation_observation(
        connection,
        subject_kind="loot_reference",
        subject_key=reference_loot_id,
        fact_key="loot_source_member",
        import_batch_id=batch_id,
        target_kind=source_kind,
        target_key=source_id,
        relation_instance_key=f"{source_kind}:{source_id}",
        attributes={"membership_value": membership_value},
        source_record_type="refloot",
        raw_identifier=f"{reference_loot_id}:{source_kind}:{source_id}",
    )
    payload = _selected_value(
        connection,
        observation_id=observation_id,
        selection_reason=(
            "Selected automatically because this reference-loot membership had no prior selection."
        ),
    )
    target = payload.get("target", {})
    if target.get("kind") != source_kind or str(target.get("key")) != str(source_id):
        raise RuntimeError("selected reference-loot membership target does not match its instance")


def _direct_target_ids(slice_data: PfQuestItemSlice) -> tuple[set[int], set[int]]:
    return (
        {source_id for item in slice_data.items for source_id, _ in item.creature_loot},
        {source_id for item in slice_data.items for source_id, _ in item.gameobject_loot},
    )


def _vendor_target_ids(slice_data: PfQuestItemSlice) -> set[int]:
    return {vendor_id for item in slice_data.items for vendor_id, _ in item.vendors}


def _reference_target_ids(slice_data: PfQuestItemSlice) -> tuple[set[int], set[int]]:
    return (
        {
            source_id
            for definition in slice_data.reference_loot
            for source_id, _ in definition.creature_memberships
        },
        {
            source_id
            for definition in slice_data.reference_loot
            for source_id, _ in definition.gameobject_memberships
        },
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
                "Selected automatically because this acquisition-source template name had no "
                "prior canonical selection."
            ),
        )
    )


def _materialize_relation_only_templates(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    slice_data: PfQuestItemSlice,
) -> tuple[int, int, set[int], set[int]]:
    """Create named acquisition-source templates without inventing spawns.

    Missing identity is fatal for direct P2-T01 loot and P2-T03 vendor relations. A reference-only
    member can instead stay as provenance evidence and is reported as unresolved, because flattening
    or inventing a name would lose source semantics.
    """

    direct_creatures, direct_gameobjects = _direct_target_ids(slice_data)
    vendor_creatures = _vendor_target_ids(slice_data)
    ref_creatures, ref_gameobjects = _reference_target_ids(slice_data)
    all_creatures = direct_creatures | vendor_creatures | ref_creatures
    all_gameobjects = direct_gameobjects | ref_gameobjects

    existing_creatures = {
        int(row[0]) for row in connection.execute("SELECT creature_id FROM creatures").fetchall()
    }
    existing_gameobjects = {
        int(row[0])
        for row in connection.execute("SELECT gameobject_id FROM gameobjects").fetchall()
    }
    missing_creatures = sorted(all_creatures - existing_creatures)
    missing_gameobjects = sorted(all_gameobjects - existing_gameobjects)
    creature_names = dict(slice_data.creature_names)
    gameobject_names = dict(slice_data.gameobject_names)

    unresolved_direct_creatures = [
        source_id
        for source_id in missing_creatures
        if source_id in direct_creatures and source_id not in creature_names
    ]
    unresolved_vendor_creatures = [
        source_id
        for source_id in missing_creatures
        if source_id in vendor_creatures and source_id not in creature_names
    ]
    unresolved_direct_gameobjects = [
        source_id
        for source_id in missing_gameobjects
        if source_id in direct_gameobjects and source_id not in gameobject_names
    ]
    if (
        unresolved_direct_creatures
        or unresolved_vendor_creatures
        or unresolved_direct_gameobjects
    ):
        raise PfQuestItemImportError(
            "pfQuest direct acquisition targets are absent from the canonical P1 world and have no "
            "pfQuest enUS identity; "
            f"missing loot creature IDs={unresolved_direct_creatures}, "
            f"missing vendor creature IDs={unresolved_vendor_creatures}, "
            f"missing gameobject IDs={unresolved_direct_gameobjects}"
        )

    unresolved_ref_creatures: set[int] = set()
    unresolved_ref_gameobjects: set[int] = set()
    inserted_creatures = 0
    inserted_gameobjects = 0

    for creature_id in missing_creatures:
        name = creature_names.get(creature_id)
        if name is None:
            unresolved_ref_creatures.add(creature_id)
            continue
        canonical_name = _observe_source_name(
            connection,
            batch_id=batch_id,
            subject_kind="creature",
            subject_id=creature_id,
            name=name,
        )
        connection.execute(
            "INSERT INTO creatures(creature_id, name) VALUES (?, ?)",
            (creature_id, canonical_name),
        )
        inserted_creatures += 1

    for gameobject_id in missing_gameobjects:
        name = gameobject_names.get(gameobject_id)
        if name is None:
            unresolved_ref_gameobjects.add(gameobject_id)
            continue
        canonical_name = _observe_source_name(
            connection,
            batch_id=batch_id,
            subject_kind="gameobject",
            subject_id=gameobject_id,
            name=name,
        )
        connection.execute(
            "INSERT INTO gameobjects(gameobject_id, name) VALUES (?, ?)",
            (gameobject_id, canonical_name),
        )
        inserted_gameobjects += 1

    return (
        inserted_creatures,
        inserted_gameobjects,
        unresolved_ref_creatures,
        unresolved_ref_gameobjects,
    )


def _row_changed(row: sqlite3.Row | None, expected: dict[str, Any]) -> bool:
    if row is None:
        return False
    return any(row[key] != value for key, value in expected.items())


def _insert_reference_anchor(connection: sqlite3.Connection, reference_loot_id: int) -> bool:
    existing = connection.execute(
        "SELECT 1 FROM loot_references WHERE reference_loot_id = ?", (reference_loot_id,)
    ).fetchone()
    connection.execute(
        "INSERT OR IGNORE INTO loot_references(reference_loot_id) VALUES (?)",
        (reference_loot_id,),
    )
    return existing is None


def import_pfquest_items(
    connection: sqlite3.Connection,
    *,
    source_root: str | Path,
    source_revision: str,
) -> ImportSummary:
    """Import pfQuest item identity and bounded loot/reference/vendor acquisition evidence."""

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
        (
            relation_only_creatures,
            relation_only_gameobjects,
            unresolved_ref_creatures,
            unresolved_ref_gameobjects,
        ) = _materialize_relation_only_templates(
            connection,
            batch_id=batch_id,
            slice_data=slice_data,
        )
        inserted += relation_only_creatures + relation_only_gameobjects

        reference_by_id = {
            definition.reference_loot_id: definition for definition in slice_data.reference_loot
        }
        referenced_reference_ids = sorted(
            {reference_id for item in slice_data.items for reference_id, _ in item.reference_loot}
        )
        for reference_id in referenced_reference_ids:
            if _insert_reference_anchor(connection, reference_id):
                inserted += 1

        unresolved: list[dict[str, Any]] = [
            {
                "reference_loot_id": reference_id,
                "reason": "missing_refloot_definition",
            }
            for reference_id in slice_data.missing_reference_ids
        ]

        reference_creature_memberships = 0
        reference_gameobject_memberships = 0
        for definition in slice_data.reference_loot:
            if not definition.creature_memberships and not definition.gameobject_memberships:
                unresolved.append(
                    {
                        "reference_loot_id": definition.reference_loot_id,
                        "reason": "empty_refloot_definition",
                    }
                )

            for creature_id, marker in definition.creature_memberships:
                _observe_reference_membership(
                    connection,
                    batch_id=batch_id,
                    reference_loot_id=definition.reference_loot_id,
                    source_kind="creature",
                    source_id=creature_id,
                    membership_value=marker,
                )
                if creature_id in unresolved_ref_creatures:
                    unresolved.append(
                        {
                            "reference_loot_id": definition.reference_loot_id,
                            "source_kind": "creature",
                            "source_id": creature_id,
                            "reason": "missing_source_identity",
                        }
                    )
                    continue
                existing = connection.execute(
                    """
                    SELECT 1 FROM reference_loot_creatures
                    WHERE reference_loot_id = ? AND creature_id = ?
                    """,
                    (definition.reference_loot_id, creature_id),
                ).fetchone()
                connection.execute(
                    """
                    INSERT OR IGNORE INTO reference_loot_creatures(reference_loot_id, creature_id)
                    VALUES (?, ?)
                    """,
                    (definition.reference_loot_id, creature_id),
                )
                if existing is None:
                    inserted += 1
                reference_creature_memberships += 1

            for gameobject_id, marker in definition.gameobject_memberships:
                _observe_reference_membership(
                    connection,
                    batch_id=batch_id,
                    reference_loot_id=definition.reference_loot_id,
                    source_kind="gameobject",
                    source_id=gameobject_id,
                    membership_value=marker,
                )
                if gameobject_id in unresolved_ref_gameobjects:
                    unresolved.append(
                        {
                            "reference_loot_id": definition.reference_loot_id,
                            "source_kind": "gameobject",
                            "source_id": gameobject_id,
                            "reason": "missing_source_identity",
                        }
                    )
                    continue
                existing = connection.execute(
                    """
                    SELECT 1 FROM reference_loot_gameobjects
                    WHERE reference_loot_id = ? AND gameobject_id = ?
                    """,
                    (definition.reference_loot_id, gameobject_id),
                ).fetchone()
                connection.execute(
                    """
                    INSERT OR IGNORE INTO reference_loot_gameobjects(
                        reference_loot_id, gameobject_id
                    ) VALUES (?, ?)
                    """,
                    (definition.reference_loot_id, gameobject_id),
                )
                if existing is None:
                    inserted += 1
                reference_gameobject_memberships += 1

        creature_links = 0
        gameobject_links = 0
        reference_links = 0
        resolved_reference_links = 0
        vendor_links = 0

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

            for reference_id, chance_percent in item.reference_loot:
                chance = _observe_reference_relation(
                    connection,
                    batch_id=batch_id,
                    item_id=item.item_id,
                    reference_loot_id=reference_id,
                    chance_percent=chance_percent,
                )
                existing = connection.execute(
                    """
                    SELECT chance_percent FROM item_reference_loot
                    WHERE item_id = ? AND reference_loot_id = ?
                    """,
                    (item.item_id, reference_id),
                ).fetchone()
                if existing is None:
                    inserted += 1
                elif _row_changed(existing, {"chance_percent": chance}):
                    updated += 1
                connection.execute(
                    """
                    INSERT INTO item_reference_loot(item_id, reference_loot_id, chance_percent)
                    VALUES (?, ?, ?)
                    ON CONFLICT(item_id, reference_loot_id) DO UPDATE SET
                        chance_percent = excluded.chance_percent
                    """,
                    (item.item_id, reference_id, chance),
                )
                reference_links += 1
                definition = reference_by_id.get(reference_id)
                if definition and (
                    definition.creature_memberships or definition.gameobject_memberships
                ):
                    resolved_reference_links += 1

            for vendor_id, max_count in item.vendors:
                _observe_vendor_relation(
                    connection,
                    batch_id=batch_id,
                    item_id=item.item_id,
                    vendor_id=vendor_id,
                    max_count=max_count,
                )
                existing = connection.execute(
                    """
                    SELECT 1 FROM vendor_items
                    WHERE vendor_creature_id = ? AND item_id = ?
                    """,
                    (vendor_id, item.item_id),
                ).fetchone()
                connection.execute(
                    """
                    INSERT OR IGNORE INTO vendor_items(vendor_creature_id, item_id)
                    VALUES (?, ?)
                    """,
                    (vendor_id, item.item_id),
                )
                if existing is None:
                    inserted += 1
                vendor_links += 1

        unresolved.sort(
            key=lambda issue: (
                int(issue["reference_loot_id"]),
                str(issue.get("source_kind", "")),
                int(issue.get("source_id", -1)),
                str(issue["reason"]),
            )
        )
        accepted = len(slice_data.items)
        details = {
            "items": accepted,
            "creature_loot_links": creature_links,
            "gameobject_loot_links": gameobject_links,
            "reference_loot_links": reference_links,
            "resolved_reference_loot_links": resolved_reference_links,
            "reference_loot_definitions": len(slice_data.reference_loot),
            "reference_creature_memberships": reference_creature_memberships,
            "reference_gameobject_memberships": reference_gameobject_memberships,
            "unresolved_reference_loot": unresolved,
            "vendor_links": vendor_links,
            "deferred_vendor_links": 0,
            "items_without_enus_name": slice_data.rows_skipped,
            "relation_only_creature_templates": relation_only_creatures,
            "relation_only_gameobject_templates": relation_only_gameobjects,
        }
        warning_count = len(unresolved)
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
                warning_count = ?,
                details_json = ?
            WHERE id = ?
            """,
            (
                slice_data.rows_read,
                accepted,
                slice_data.rows_skipped,
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
        warning_count=warning_count,
        error_count=0,
        details=details,
    )
