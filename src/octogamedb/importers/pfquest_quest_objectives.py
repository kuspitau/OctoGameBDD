"""P3-T04 quest-objective and objective-geography reconciliation for pfQuest + Turtle.

The adapter keeps the six pfQuest objective subtypes source-shaped:

* ``obj.U`` -> creature objective targets;
* ``obj.O`` -> game-object objective targets;
* ``obj.I`` -> item/loot objective targets;
* ``obj.IR`` -> quest items used on/at targets described by ``quests-itemreq``;
* ``obj.A`` -> area-trigger objective targets;
* ``obj.Z`` -> direct zone/area objective context.

Creature/game-object geography is derived from the already-canonical P1 spawn model. Area-trigger
coordinates are imported as their own source-backed primitive geography; an AreaTrigger ID is never
reinterpreted as a Zone ID. No objective quantity is inferred because pfQuest exports membership-only
lists for these fields.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import (
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.pfquest_quest_overlay_reconcile import (
    PFQUEST_TURTLE_SOURCE_KEY,
    _load_effective_tables,
    _patch_table,
    compute_pfquest_turtle_quests_revision,
)
from octogamedb.importers.pfquest_quest_progression import (
    compute_pfquest_quest_progression_revision,
    compute_pfquest_turtle_quest_progression_revision,
)
from octogamedb.importers.pfquest_quests import compute_pfquest_quests_revision
from octogamedb.importers.pfquest_world import (
    PFQUEST_SOURCE_KEY,
    PfQuestParseError,
    parse_pfquest_assignment,
)
from octogamedb.importers.summary import ImportSummary

IMPORTER_VERSION = "pfquest-quest-objectives/1"
BASE_SELECTION_POLICY = "pfquest-base-effective-quest-objectives"
TURTLE_SELECTION_POLICY = "pfquest-turtle-effective-quest-objectives"

QUEST_SET_FACT = "quest_objective_set"
AREA_TRIGGER_SET_FACT = "area_trigger_location_set"
ITEM_USE_TARGET_SET_FACT = "item_use_target_set"

OBJECTIVE_FACTS = {
    "U": ("objective_creature", "creature", "quest_creature_objectives", "creature_id", "creatures"),
    "O": (
        "objective_gameobject",
        "gameobject",
        "quest_gameobject_objectives",
        "gameobject_id",
        "gameobjects",
    ),
    "I": ("objective_item_collect", "item", "quest_item_objectives", "item_id", "items"),
    "IR": ("objective_item_use", "item", "quest_item_use_objectives", "item_id", "items"),
    "A": (
        "objective_area_trigger",
        "area_trigger",
        "quest_area_trigger_objectives",
        "area_trigger_id",
        "area_triggers",
    ),
    "Z": ("objective_zone", "zone", "quest_zone_objectives", "zone_id", "zones"),
}
OBJECTIVE_SUBTYPES = tuple(OBJECTIVE_FACTS)

ITEM_USE_CREATURE_FACT = "item_use_creature_target"
ITEM_USE_GAMEOBJECT_FACT = "item_use_gameobject_target"
AREA_TRIGGER_ZONE_FACT = "area_trigger_zone_location"

_BASE_OBJECTIVE_FILES = (
    "db/quests.lua",
    "db/quests-itemreq.lua",
    "db/areatrigger.lua",
)
_TURTLE_OBJECTIVE_FILES = (
    "pfQuest-turtle.toc",
    "init/data-turtle.xml",
    "db/quests-turtle.lua",
    "db/quests-itemreq-turtle.lua",
    "db/areatrigger-turtle.lua",
    "overwrites.lua",
    "patchtable.lua",
)

_DEFAULT_BASE_POLICIES = frozenset({None, "first-observation", BASE_SELECTION_POLICY})


@dataclass(frozen=True)
class _Selection:
    observation_id: int
    source_key: str
    selection_policy: str | None
    value: Any


@dataclass(frozen=True)
class QuestObjectives:
    obj_present: bool
    source_lists: dict[str, tuple[int, ...] | None]
    members: dict[str, tuple[int, ...]]
    duplicates: dict[str, tuple[int, ...]]


@dataclass(frozen=True)
class ItemUseTarget:
    signed_target_id: int
    target_kind: str
    target_id: int
    spell_id: int
    source_spell: int | str


@dataclass(frozen=True)
class ItemUseTargets:
    entry_present: bool
    targets: tuple[ItemUseTarget, ...]


@dataclass(frozen=True)
class AreaTriggerLocation:
    source_index: int
    x: float
    y: float
    zone_id: int


@dataclass(frozen=True)
class AreaTriggerData:
    entry_present: bool
    coords_present: bool
    locations: tuple[AreaTriggerLocation, ...]


@dataclass(frozen=True)
class _MaterializeResult:
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    protected: int = 0
    unresolved: tuple[dict[str, Any], ...] = ()


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


def _hash_files(root: Path, relatives: tuple[str, ...], *, label: str) -> str:
    missing = [relative for relative in relatives if not (root / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"missing required {label} file: {root / missing[0]}")
    digest = hashlib.sha256()
    for relative in relatives:
        path = root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return f"sha256:{digest.hexdigest()}"


def compute_pfquest_quest_objectives_revision(source_root: str | Path) -> str:
    """Hash the exact base-pfQuest files consumed by P3-T04."""

    return _hash_files(Path(source_root), _BASE_OBJECTIVE_FILES, label="pfQuest P3-T04")


def _validate_turtle_objective_layout(source_root: str | Path) -> Path:
    root = Path(source_root)
    _hash_files(root, _TURTLE_OBJECTIVE_FILES, label="pfQuest-turtle P3-T04")
    data_xml = (root / "init" / "data-turtle.xml").read_text(encoding="utf-8")
    for marker in ("quests-turtle.lua", "quests-itemreq-turtle.lua", "areatrigger-turtle.lua"):
        if marker not in data_xml:
            raise PfQuestParseError(f"unsupported Turtle P3-T04 layout: {marker} is not loaded")
    patchtable = (root / "patchtable.lua").read_text(encoding="utf-8")
    for marker in (
        '"quests"',
        '"quests-itemreq"',
        '"areatrigger"',
        'pfDB[db]["data-turtle"]',
        'base[k] = nil',
        'base[k] = v',
    ):
        if marker not in patchtable:
            raise PfQuestParseError("unsupported pfQuest-turtle P3-T04 patchtable semantics")

    # Quest-table literal overwrites are handled by the validated P3-T02 compositor. The pinned
    # Turtle source currently has no auxiliary direct mutations. Refuse a future layout instead of
    # silently executing or mis-parsing arbitrary Lua.
    overwrite_text = (root / "overwrites.lua").read_text(encoding="utf-8")
    for domain in ("quests-itemreq", "areatrigger"):
        if f'pfDB["{domain}"]' in overwrite_text or f"pfDB['{domain}']" in overwrite_text:
            raise PfQuestParseError(
                f"unsupported direct {domain} mutation in Turtle overwrites.lua for P3-T04"
            )
    return root


def compute_pfquest_turtle_quest_objectives_revision(source_root: str | Path) -> str:
    """Hash the exact Turtle P3-T04 objective/auxiliary composition inputs."""

    root = _validate_turtle_objective_layout(source_root)
    return _hash_files(root, _TURTLE_OBJECTIVE_FILES, label="pfQuest-turtle P3-T04")


def _integer_id(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PfQuestParseError(f"{label} must be an integer native ID")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float) and value.is_integer():
        parsed = int(value)
    else:
        raise PfQuestParseError(f"{label} must be an integer native ID")
    if parsed <= 0:
        raise PfQuestParseError(f"{label} must be a positive native ID")
    return parsed


def _source_id_list(value: Any, *, label: str) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise PfQuestParseError(f"{label} must be a Lua array table when present")
    keys = list(value)
    if any(isinstance(key, bool) or not isinstance(key, int) for key in keys):
        raise PfQuestParseError(f"{label} must contain only positional integer keys")
    return tuple(_integer_id(value[key], label=f"{label}[{key}]") for key in sorted(keys))


def _duplicates(values: tuple[int, ...] | None) -> tuple[int, ...]:
    seen: set[int] = set()
    duplicate: set[int] = set()
    for value in values or ():
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return tuple(sorted(duplicate))


def parse_quest_objectives(record: Any, *, quest_id: int) -> QuestObjectives:
    """Parse ``obj.U/O/I/IR/A/Z`` while preserving absent-vs-empty source lists."""

    if record is None:
        record = {}
    if not isinstance(record, dict):
        raise PfQuestParseError(f"quest[{quest_id}] must be a Lua table")
    obj = record.get("obj")
    if obj is None:
        return QuestObjectives(
            obj_present=False,
            source_lists={subtype: None for subtype in OBJECTIVE_SUBTYPES},
            members={subtype: () for subtype in OBJECTIVE_SUBTYPES},
            duplicates={subtype: () for subtype in OBJECTIVE_SUBTYPES},
        )
    if not isinstance(obj, dict):
        raise PfQuestParseError(f"quest[{quest_id}].obj must be a Lua table")

    source_lists: dict[str, tuple[int, ...] | None] = {}
    members: dict[str, tuple[int, ...]] = {}
    duplicates: dict[str, tuple[int, ...]] = {}
    for subtype in OBJECTIVE_SUBTYPES:
        raw = _source_id_list(obj.get(subtype), label=f"quest[{quest_id}].obj.{subtype}")
        source_lists[subtype] = raw
        members[subtype] = tuple(sorted(set(raw or ())))
        duplicates[subtype] = _duplicates(raw)
    return QuestObjectives(True, source_lists, members, duplicates)


def _spell_id(value: Any, *, label: str) -> tuple[int, int | str]:
    if isinstance(value, bool):
        raise PfQuestParseError(f"{label} must be a non-negative integer spell ID")
    source: int | str
    if isinstance(value, int):
        parsed = value
        source = value
    elif isinstance(value, float) and value.is_integer():
        parsed = int(value)
        source = parsed
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        source = value
    else:
        raise PfQuestParseError(f"{label} must be a non-negative integer spell ID")
    if parsed < 0:
        raise PfQuestParseError(f"{label} must be a non-negative integer spell ID")
    return parsed, source


def parse_item_use_targets(record: Any, *, item_id: int) -> ItemUseTargets:
    """Parse one ``quests-itemreq`` entry: signed target ID -> spell ID."""

    if record is None:
        return ItemUseTargets(False, ())
    if not isinstance(record, dict):
        raise PfQuestParseError(f"quests-itemreq[{item_id}] must be a Lua table")
    targets: list[ItemUseTarget] = []
    for signed_target in sorted(record):
        if isinstance(signed_target, bool) or not isinstance(signed_target, int) or signed_target == 0:
            raise PfQuestParseError(
                f"quests-itemreq[{item_id}] target keys must be non-zero signed integer IDs"
            )
        spell_id, source_spell = _spell_id(
            record[signed_target], label=f"quests-itemreq[{item_id}][{signed_target}]"
        )
        target_kind = "creature" if signed_target > 0 else "gameobject"
        targets.append(
            ItemUseTarget(
                signed_target_id=signed_target,
                target_kind=target_kind,
                target_id=abs(signed_target),
                spell_id=spell_id,
                source_spell=source_spell,
            )
        )
    return ItemUseTargets(True, tuple(targets))


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PfQuestParseError(f"{label} must be numeric")
    return float(value)


def parse_area_trigger(record: Any, *, area_trigger_id: int) -> AreaTriggerData:
    """Parse one area-trigger entry and its source-indexed zone-percent coordinates."""

    if record is None:
        return AreaTriggerData(False, False, ())
    if not isinstance(record, dict):
        raise PfQuestParseError(f"areatrigger[{area_trigger_id}] must be a Lua table")
    coords = record.get("coords")
    if coords is None:
        return AreaTriggerData(True, False, ())
    if not isinstance(coords, dict):
        raise PfQuestParseError(f"areatrigger[{area_trigger_id}].coords must be a Lua array table")
    if any(isinstance(key, bool) or not isinstance(key, int) for key in coords):
        raise PfQuestParseError(
            f"areatrigger[{area_trigger_id}].coords must use positional integer keys"
        )
    locations: list[AreaTriggerLocation] = []
    for index in sorted(coords):
        row = coords[index]
        if not isinstance(row, dict):
            raise PfQuestParseError(
                f"areatrigger[{area_trigger_id}].coords[{index}] must be a Lua array table"
            )
        if not all(position in row for position in (1, 2, 3)):
            raise PfQuestParseError(
                f"areatrigger[{area_trigger_id}].coords[{index}] must contain x, y and zone ID"
            )
        x = _number(row[1], label=f"areatrigger[{area_trigger_id}].coords[{index}][1]")
        y = _number(row[2], label=f"areatrigger[{area_trigger_id}].coords[{index}][2]")
        if not 0.0 <= x <= 100.0 or not 0.0 <= y <= 100.0:
            raise PfQuestParseError(
                f"areatrigger[{area_trigger_id}].coords[{index}] is outside zone-percent bounds"
            )
        zone_id = _integer_id(
            row[3], label=f"areatrigger[{area_trigger_id}].coords[{index}][3]"
        )
        locations.append(AreaTriggerLocation(int(index), x, y, zone_id))
    return AreaTriggerData(True, True, tuple(locations))


def _read_assignment(root: Path, relative: str, domain: str, table_name: str) -> dict[Any, Any]:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(f"missing required pfQuest P3-T04 file: {path}")
    return parse_pfquest_assignment(
        path.read_text(encoding="utf-8"), domain=domain, table_name=table_name
    )


def _load_auxiliary_tables(
    pfquest_root: str | Path, pfquest_turtle_root: str | Path
) -> tuple[
    dict[Any, Any],
    dict[Any, Any],
    dict[Any, Any],
    dict[Any, Any],
    dict[Any, Any],
    dict[Any, Any],
]:
    base_root = Path(pfquest_root)
    turtle_root = _validate_turtle_objective_layout(pfquest_turtle_root)
    base_itemreq = _read_assignment(
        base_root, "db/quests-itemreq.lua", "quests-itemreq", "data"
    )
    base_area = _read_assignment(base_root, "db/areatrigger.lua", "areatrigger", "data")
    patch_itemreq = _read_assignment(
        turtle_root, "db/quests-itemreq-turtle.lua", "quests-itemreq", "data-turtle"
    )
    patch_area = _read_assignment(
        turtle_root, "db/areatrigger-turtle.lua", "areatrigger", "data-turtle"
    )
    return (
        base_itemreq,
        patch_itemreq,
        _patch_table(base_itemreq, patch_itemreq),
        base_area,
        patch_area,
        _patch_table(base_area, patch_area),
    )


def _source_id(connection: sqlite3.Connection, source_key: str) -> int:
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (source_key,)
    ).fetchone()
    if row is None:
        raise ValueError(f"required source has not been imported: {source_key}")
    return int(row["id"])


def _require_successful_import(
    connection: sqlite3.Connection,
    *,
    source_key: str,
    source_revision: str,
    importer_prefix: str,
    task_label: str,
) -> int:
    source_id = _source_id(connection, source_key)
    row = connection.execute(
        """
        SELECT id
        FROM import_batches
        WHERE source_id = ?
          AND COALESCE(source_revision, '') = ?
          AND status = 'succeeded'
          AND importer_version LIKE ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (source_id, source_revision, f"{importer_prefix}%"),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"P3-T04 requires {task_label} to succeed first at revision {source_revision}"
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
        INSERT INTO import_batches(source_id, source_revision, status, importer_version, rows_read)
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
    warning_count: int,
    details: dict[str, Any],
) -> None:
    connection.execute(
        """
        UPDATE import_batches
        SET status = 'succeeded',
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            rows_read = ?, rows_accepted = ?, rows_skipped = 0,
            rows_inserted = ?, rows_updated = ?, warning_count = ?, details_json = ?
        WHERE id = ?
        """,
        (
            rows_read,
            rows_read,
            rows_inserted,
            rows_updated,
            warning_count,
            json.dumps(details, sort_keys=True, separators=(",", ":")),
            batch_id,
        ),
    )


def _fail_batch(connection: sqlite3.Connection, batch_id: int, exc: Exception) -> None:
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


def _group_for_observation(connection: sqlite3.Connection, observation_id: int) -> int:
    row = connection.execute(
        "SELECT observation_group_id FROM source_observations WHERE id = ?", (observation_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"observation {observation_id} disappeared")
    return int(row["observation_group_id"])


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
        selection_policy=None if row["selection_policy"] is None else str(row["selection_policy"]),
        value=json.loads(str(row["value_json"])),
    )


def _selection_for(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    fact_instance_key: str = "",
) -> _Selection | None:
    row = connection.execute(
        """
        SELECT id FROM observation_groups
        WHERE subject_kind = ? AND subject_key = ? AND fact_key = ? AND fact_instance_key = ?
        """,
        (subject_kind, str(subject_key), fact_key, fact_instance_key),
    ).fetchone()
    return None if row is None else _selection_for_group(connection, int(row["id"]))


def _selection_is_managed(selection: _Selection | None) -> bool:
    if selection is None:
        return False
    if selection.source_key == PFQUEST_SOURCE_KEY:
        return selection.selection_policy in _DEFAULT_BASE_POLICIES
    return (
        selection.source_key == PFQUEST_TURTLE_SOURCE_KEY
        and selection.selection_policy == TURTLE_SELECTION_POLICY
    )


def _select_if_missing_or_managed(
    connection: sqlite3.Connection,
    *,
    observation_id: int,
    source_key: str,
) -> None:
    group_id = _group_for_observation(connection, observation_id)
    current = _selection_for_group(connection, group_id)
    if source_key == PFQUEST_SOURCE_KEY:
        if current is not None:
            return
        policy = BASE_SELECTION_POLICY
        reason = "Base pfQuest establishes the initial selected P3-T04 source view."
    else:
        if current is not None and not _selection_is_managed(current):
            return
        policy = TURTLE_SELECTION_POLICY
        reason = (
            "The active Turtle whole-entry P3-T04 view supersedes managed/base objective evidence."
        )
    select_canonical_observation(
        connection,
        observation_group_id=group_id,
        observation_id=observation_id,
        selection_policy=policy,
        selection_reason=reason,
    )


def _record_scalar(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    value: Any,
    source_key: str,
    raw_identifier: str,
    source_record_type: str,
) -> None:
    observation_id = record_scalar_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type=source_record_type,
        raw_identifier=raw_identifier,
    )
    _select_if_missing_or_managed(
        connection, observation_id=observation_id, source_key=source_key
    )


def _record_relation(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    target_kind: str,
    target_id: int,
    instance_key: str,
    attributes: dict[str, Any],
    source_key: str,
    raw_identifier: str,
    source_record_type: str,
) -> None:
    observation_id = record_relation_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        target_kind=target_kind,
        target_key=target_id,
        relation_instance_key=instance_key,
        attributes=attributes,
        source_record_type=source_record_type,
        raw_identifier=raw_identifier,
    )
    _select_if_missing_or_managed(
        connection, observation_id=observation_id, source_key=source_key
    )


def _objective_set_payload(parsed: QuestObjectives) -> dict[str, Any]:
    return {
        "obj_present": parsed.obj_present,
        "subtype_presence": {
            subtype: parsed.source_lists[subtype] is not None for subtype in OBJECTIVE_SUBTYPES
        },
        "subtypes": {
            subtype: (
                None
                if parsed.source_lists[subtype] is None
                else list(parsed.source_lists[subtype] or ())
            )
            for subtype in OBJECTIVE_SUBTYPES
        },
    }


def _record_quest_objectives(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    quest_id: int,
    parsed: QuestObjectives,
    source_key: str,
) -> None:
    _record_scalar(
        connection,
        batch_id=batch_id,
        subject_kind="quest",
        subject_key=quest_id,
        fact_key=QUEST_SET_FACT,
        value=_objective_set_payload(parsed),
        source_key=source_key,
        raw_identifier=f"{quest_id}:obj",
        source_record_type="quest_objective_set",
    )
    for subtype in OBJECTIVE_SUBTYPES:
        fact_key, target_kind, *_ = OBJECTIVE_FACTS[subtype]
        for target_id in parsed.members[subtype]:
            _record_relation(
                connection,
                batch_id=batch_id,
                subject_kind="quest",
                subject_key=quest_id,
                fact_key=fact_key,
                target_kind=target_kind,
                target_id=target_id,
                instance_key=str(target_id),
                attributes={"source_subtype": subtype},
                source_key=source_key,
                raw_identifier=f"{quest_id}:obj:{subtype}:{target_id}",
                source_record_type="quest_objective_relation",
            )


def _item_target_set_payload(parsed: ItemUseTargets) -> dict[str, Any]:
    return {
        "entry_present": parsed.entry_present,
        "targets": [
            {
                "signed_target_id": target.signed_target_id,
                "target_kind": target.target_kind,
                "target_id": target.target_id,
                "spell_id": target.spell_id,
                "source_spell": target.source_spell,
            }
            for target in parsed.targets
        ],
    }


def _record_item_use_targets(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    item_id: int,
    parsed: ItemUseTargets,
    source_key: str,
) -> None:
    _record_scalar(
        connection,
        batch_id=batch_id,
        subject_kind="item",
        subject_key=item_id,
        fact_key=ITEM_USE_TARGET_SET_FACT,
        value=_item_target_set_payload(parsed),
        source_key=source_key,
        raw_identifier=f"{item_id}:quests-itemreq",
        source_record_type="quests_itemreq_set",
    )
    for target in parsed.targets:
        fact_key = (
            ITEM_USE_CREATURE_FACT
            if target.target_kind == "creature"
            else ITEM_USE_GAMEOBJECT_FACT
        )
        _record_relation(
            connection,
            batch_id=batch_id,
            subject_kind="item",
            subject_key=item_id,
            fact_key=fact_key,
            target_kind=target.target_kind,
            target_id=target.target_id,
            instance_key=str(target.target_id),
            attributes={
                "signed_target_id": target.signed_target_id,
                "spell_id": target.spell_id,
            },
            source_key=source_key,
            raw_identifier=f"{item_id}:{target.signed_target_id}",
            source_record_type="quests_itemreq_relation",
        )


def _area_set_payload(parsed: AreaTriggerData) -> dict[str, Any]:
    return {
        "entry_present": parsed.entry_present,
        "coords_present": parsed.coords_present,
        "locations": [
            {
                "source_index": location.source_index,
                "x": location.x,
                "y": location.y,
                "zone_id": location.zone_id,
            }
            for location in parsed.locations
        ],
    }


def _record_area_trigger(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    area_trigger_id: int,
    parsed: AreaTriggerData,
    source_key: str,
) -> None:
    _record_scalar(
        connection,
        batch_id=batch_id,
        subject_kind="area_trigger",
        subject_key=area_trigger_id,
        fact_key=AREA_TRIGGER_SET_FACT,
        value=_area_set_payload(parsed),
        source_key=source_key,
        raw_identifier=f"{area_trigger_id}:coords",
        source_record_type="area_trigger_location_set",
    )
    for location in parsed.locations:
        _record_relation(
            connection,
            batch_id=batch_id,
            subject_kind="area_trigger",
            subject_key=area_trigger_id,
            fact_key=AREA_TRIGGER_ZONE_FACT,
            target_kind="zone",
            target_id=location.zone_id,
            instance_key=str(location.source_index),
            attributes={
                "source_index": location.source_index,
                "coordinate_space": "zone_percent",
                "x": location.x,
                "y": location.y,
            },
            source_key=source_key,
            raw_identifier=f"{area_trigger_id}:coords:{location.source_index}",
            source_record_type="area_trigger_location_relation",
        )


def _relation_target(selection: _Selection | None) -> tuple[str, int, dict[str, Any]] | None:
    if selection is None or not isinstance(selection.value, dict):
        return None
    target = selection.value.get("target")
    attributes = selection.value.get("attributes", {})
    if not isinstance(target, dict) or not isinstance(attributes, dict):
        return None
    kind = target.get("kind")
    key = target.get("key")
    if not isinstance(kind, str) or not isinstance(key, str) or not key.isdigit():
        return None
    return kind, int(key), attributes


def _selected_objective_set(
    connection: sqlite3.Connection, quest_id: int
) -> tuple[bool, dict[str, tuple[int, ...]]]:
    selection = _selection_for(
        connection,
        subject_kind="quest",
        subject_key=quest_id,
        fact_key=QUEST_SET_FACT,
    )
    if selection is None:
        return False, {subtype: () for subtype in OBJECTIVE_SUBTYPES}
    value = selection.value
    if not isinstance(value, dict) or not isinstance(value.get("obj_present"), bool):
        raise TypeError(f"selected {QUEST_SET_FACT} for quest {quest_id} has invalid shape")
    subtypes = value.get("subtypes")
    if not isinstance(subtypes, dict):
        raise TypeError(f"selected {QUEST_SET_FACT} for quest {quest_id} has invalid subtypes")
    result: dict[str, tuple[int, ...]] = {}
    for subtype in OBJECTIVE_SUBTYPES:
        raw = subtypes.get(subtype)
        if raw is None:
            result[subtype] = ()
            continue
        if not isinstance(raw, list):
            raise TypeError(f"selected {QUEST_SET_FACT}.{subtype} for quest {quest_id} must be a list")
        ids: list[int] = []
        for target_id in raw:
            if isinstance(target_id, bool) or not isinstance(target_id, int) or target_id <= 0:
                raise TypeError(
                    f"selected {QUEST_SET_FACT}.{subtype} for quest {quest_id} contains invalid ID"
                )
            ids.append(target_id)
        result[subtype] = tuple(sorted(set(ids)))
    return bool(value["obj_present"]), result


def _identity_exists(connection: sqlite3.Connection, table: str, column: str, target_id: int) -> bool:
    return connection.execute(
        f"SELECT 1 FROM {table} WHERE {column} = ?", (target_id,)
    ).fetchone() is not None


def _sync_quest_objective_kind(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    subtype: str,
    desired_ids: tuple[int, ...],
) -> _MaterializeResult:
    fact_key, target_kind, table, column, identity_table = OBJECTIVE_FACTS[subtype]
    current = {
        int(row[0])
        for row in connection.execute(
            f"SELECT {column} FROM {table} WHERE quest_id = ?", (quest_id,)
        ).fetchall()
    }
    desired = set(desired_ids)
    inserted = deleted = protected = 0
    unresolved: list[dict[str, Any]] = []

    for target_id in sorted(current - desired):
        selection = _selection_for(
            connection,
            subject_kind="quest",
            subject_key=quest_id,
            fact_key=fact_key,
            fact_instance_key=str(target_id),
        )
        if selection is not None and not _selection_is_managed(selection):
            protected += 1
            continue
        connection.execute(
            f"DELETE FROM {table} WHERE quest_id = ? AND {column} = ?", (quest_id, target_id)
        )
        deleted += 1

    for target_id in desired_ids:
        selection = _selection_for(
            connection,
            subject_kind="quest",
            subject_key=quest_id,
            fact_key=fact_key,
            fact_instance_key=str(target_id),
        )
        selected_target = _relation_target(selection)
        if selected_target is None or selected_target[:2] != (target_kind, target_id):
            unresolved.append(
                {
                    "quest_id": quest_id,
                    "subtype": subtype,
                    "target_id": target_id,
                    "reason": "missing_selected_primitive_relation",
                }
            )
            continue
        if target_kind == "area_trigger":
            row = connection.execute(
                "SELECT selected_entry_present FROM area_triggers WHERE area_trigger_id = ?",
                (target_id,),
            ).fetchone()
            exists = row is not None and bool(row["selected_entry_present"])
        else:
            exists = _identity_exists(connection, identity_table, column, target_id)
        if not exists:
            unresolved.append(
                {
                    "quest_id": quest_id,
                    "subtype": subtype,
                    "target_id": target_id,
                    "reason": f"missing_{target_kind}_identity",
                }
            )
            continue
        present = connection.execute(
            f"SELECT 1 FROM {table} WHERE quest_id = ? AND {column} = ?",
            (quest_id, target_id),
        ).fetchone()
        if present is None:
            connection.execute(
                f"INSERT INTO {table}(quest_id, {column}) VALUES (?, ?)",
                (quest_id, target_id),
            )
            inserted += 1
    return _MaterializeResult(
        inserted=inserted,
        deleted=deleted,
        protected=protected,
        unresolved=tuple(unresolved),
    )


def _materialize_quest(connection: sqlite3.Connection, quest_id: int) -> _MaterializeResult:
    if not _identity_exists(connection, "quests", "quest_id", quest_id):
        return _MaterializeResult(
            unresolved=(
                {
                    "quest_id": quest_id,
                    "subtype": "set",
                    "target_id": quest_id,
                    "reason": "missing_quest_identity",
                },
            )
        )
    obj_present, desired_by_kind = _selected_objective_set(connection, quest_id)
    selected_count = sum(len(ids) for ids in desired_by_kind.values())
    parent = connection.execute(
        "SELECT selected_set_present, selected_member_count FROM quest_objective_sets WHERE quest_id = ?",
        (quest_id,),
    ).fetchone()
    inserted = updated = deleted = protected = 0
    unresolved: list[dict[str, Any]] = []
    if obj_present or selected_count:
        if parent is None:
            connection.execute(
                "INSERT INTO quest_objective_sets(quest_id, selected_set_present, selected_member_count) "
                "VALUES (?, ?, ?)",
                (quest_id, int(obj_present), selected_count),
            )
            inserted += 1
        elif (
            int(parent["selected_set_present"]) != int(obj_present)
            or int(parent["selected_member_count"]) != selected_count
        ):
            connection.execute(
                "UPDATE quest_objective_sets SET selected_set_present = ?, selected_member_count = ? "
                "WHERE quest_id = ?",
                (int(obj_present), selected_count, quest_id),
            )
            updated += 1
    elif parent is not None:
        connection.execute("DELETE FROM quest_objective_sets WHERE quest_id = ?", (quest_id,))
        deleted += 1

    for subtype in OBJECTIVE_SUBTYPES:
        result = _sync_quest_objective_kind(
            connection,
            quest_id=quest_id,
            subtype=subtype,
            desired_ids=desired_by_kind[subtype],
        )
        inserted += result.inserted
        updated += result.updated
        deleted += result.deleted
        protected += result.protected
        unresolved.extend(result.unresolved)
    return _MaterializeResult(inserted, updated, deleted, protected, tuple(unresolved))


def _selected_item_targets(connection: sqlite3.Connection, item_id: int) -> tuple[bool, tuple[ItemUseTarget, ...]]:
    selection = _selection_for(
        connection,
        subject_kind="item",
        subject_key=item_id,
        fact_key=ITEM_USE_TARGET_SET_FACT,
    )
    if selection is None:
        return False, ()
    value = selection.value
    if not isinstance(value, dict) or not isinstance(value.get("entry_present"), bool):
        raise TypeError(f"selected {ITEM_USE_TARGET_SET_FACT} for item {item_id} has invalid shape")
    raw_targets = value.get("targets")
    if not isinstance(raw_targets, list):
        raise TypeError(f"selected {ITEM_USE_TARGET_SET_FACT} for item {item_id} has invalid targets")
    targets: list[ItemUseTarget] = []
    for row in raw_targets:
        if not isinstance(row, dict):
            raise TypeError(f"selected {ITEM_USE_TARGET_SET_FACT} member must be an object")
        kind = row.get("target_kind")
        target_id = row.get("target_id")
        signed = row.get("signed_target_id")
        spell = row.get("spell_id")
        if kind not in {"creature", "gameobject"}:
            raise TypeError("selected item-use target has invalid target_kind")
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (target_id, signed, spell)):
            raise TypeError("selected item-use target has non-integer IDs")
        if target_id <= 0 or signed == 0 or spell < 0 or abs(signed) != target_id:
            raise ValueError("selected item-use target has inconsistent IDs")
        targets.append(ItemUseTarget(signed, kind, target_id, spell, row.get("source_spell", spell)))
    targets.sort(key=lambda target: (target.target_kind, target.target_id))
    return bool(value["entry_present"]), tuple(targets)


def _sync_item_target_kind(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    target_kind: str,
    desired: tuple[ItemUseTarget, ...],
) -> _MaterializeResult:
    if target_kind == "creature":
        fact_key, table, column, identity_table = (
            ITEM_USE_CREATURE_FACT,
            "item_use_creature_targets",
            "creature_id",
            "creatures",
        )
    else:
        fact_key, table, column, identity_table = (
            ITEM_USE_GAMEOBJECT_FACT,
            "item_use_gameobject_targets",
            "gameobject_id",
            "gameobjects",
        )
    desired_map = {target.target_id: target for target in desired if target.target_kind == target_kind}
    rows = connection.execute(
        f"SELECT {column}, spell_id FROM {table} WHERE item_id = ?", (item_id,)
    ).fetchall()
    current = {int(row[column]): int(row["spell_id"]) for row in rows}
    inserted = updated = deleted = protected = 0
    unresolved: list[dict[str, Any]] = []
    for target_id in sorted(set(current) - set(desired_map)):
        selection = _selection_for(
            connection,
            subject_kind="item",
            subject_key=item_id,
            fact_key=fact_key,
            fact_instance_key=str(target_id),
        )
        if selection is not None and not _selection_is_managed(selection):
            protected += 1
            continue
        connection.execute(
            f"DELETE FROM {table} WHERE item_id = ? AND {column} = ?", (item_id, target_id)
        )
        deleted += 1

    for target_id, expected in sorted(desired_map.items()):
        selection = _selection_for(
            connection,
            subject_kind="item",
            subject_key=item_id,
            fact_key=fact_key,
            fact_instance_key=str(target_id),
        )
        selected_target = _relation_target(selection)
        if selected_target is None or selected_target[:2] != (target_kind, target_id):
            unresolved.append(
                {
                    "item_id": item_id,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "reason": "missing_selected_primitive_relation",
                }
            )
            continue
        attributes = selected_target[2]
        spell_id = attributes.get("spell_id")
        if isinstance(spell_id, bool) or not isinstance(spell_id, int) or spell_id < 0:
            unresolved.append(
                {
                    "item_id": item_id,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "reason": "invalid_selected_spell_id",
                }
            )
            continue
        if not _identity_exists(connection, identity_table, column, target_id):
            unresolved.append(
                {
                    "item_id": item_id,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "reason": f"missing_{target_kind}_identity",
                }
            )
            continue
        if target_id not in current:
            connection.execute(
                f"INSERT INTO {table}(item_id, {column}, spell_id) VALUES (?, ?, ?)",
                (item_id, target_id, spell_id),
            )
            inserted += 1
        elif current[target_id] != spell_id:
            connection.execute(
                f"UPDATE {table} SET spell_id = ? WHERE item_id = ? AND {column} = ?",
                (spell_id, item_id, target_id),
            )
            updated += 1
    return _MaterializeResult(inserted, updated, deleted, protected, tuple(unresolved))


def _materialize_item_targets(connection: sqlite3.Connection, item_id: int) -> _MaterializeResult:
    entry_present, desired = _selected_item_targets(connection, item_id)
    if not _identity_exists(connection, "items", "item_id", item_id):
        return _MaterializeResult(
            unresolved=(
                {
                    "item_id": item_id,
                    "target_kind": "set",
                    "target_id": item_id,
                    "reason": "missing_item_identity",
                },
            )
        )
    parent = connection.execute(
        "SELECT selected_set_present, selected_target_count FROM item_use_target_sets WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    inserted = updated = deleted = protected = 0
    unresolved: list[dict[str, Any]] = []

    # Parent must exist before child inserts. Keep it if protected stale children remain later.
    if entry_present or desired or parent is not None:
        if parent is None:
            connection.execute(
                "INSERT INTO item_use_target_sets(item_id, selected_set_present, selected_target_count) "
                "VALUES (?, ?, ?)",
                (item_id, int(entry_present), len(desired)),
            )
            inserted += 1
        elif (
            int(parent["selected_set_present"]) != int(entry_present)
            or int(parent["selected_target_count"]) != len(desired)
        ):
            connection.execute(
                "UPDATE item_use_target_sets SET selected_set_present = ?, selected_target_count = ? "
                "WHERE item_id = ?",
                (int(entry_present), len(desired), item_id),
            )
            updated += 1

    for kind in ("creature", "gameobject"):
        result = _sync_item_target_kind(
            connection, item_id=item_id, target_kind=kind, desired=desired
        )
        inserted += result.inserted
        updated += result.updated
        deleted += result.deleted
        protected += result.protected
        unresolved.extend(result.unresolved)

    child_count = int(
        connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM item_use_creature_targets WHERE item_id = ?) +
                (SELECT COUNT(*) FROM item_use_gameobject_targets WHERE item_id = ?)
            """,
            (item_id, item_id),
        ).fetchone()[0]
    )
    if not entry_present and not desired and child_count == 0 and parent is not None:
        connection.execute("DELETE FROM item_use_target_sets WHERE item_id = ?", (item_id,))
        deleted += 1
    return _MaterializeResult(inserted, updated, deleted, protected, tuple(unresolved))


def _selected_area_trigger(connection: sqlite3.Connection, area_trigger_id: int) -> AreaTriggerData:
    selection = _selection_for(
        connection,
        subject_kind="area_trigger",
        subject_key=area_trigger_id,
        fact_key=AREA_TRIGGER_SET_FACT,
    )
    if selection is None:
        return AreaTriggerData(False, False, ())
    value = selection.value
    if not isinstance(value, dict):
        raise TypeError(f"selected {AREA_TRIGGER_SET_FACT} has invalid shape")
    entry_present = value.get("entry_present")
    coords_present = value.get("coords_present")
    locations = value.get("locations")
    if not isinstance(entry_present, bool) or not isinstance(coords_present, bool):
        raise TypeError(f"selected {AREA_TRIGGER_SET_FACT} has invalid presence flags")
    if not isinstance(locations, list):
        raise TypeError(f"selected {AREA_TRIGGER_SET_FACT} has invalid locations")
    parsed: list[AreaTriggerLocation] = []
    for row in locations:
        if not isinstance(row, dict):
            raise TypeError("selected area-trigger location must be an object")
        index = row.get("source_index")
        zone_id = row.get("zone_id")
        x = row.get("x")
        y = row.get("y")
        if isinstance(index, bool) or not isinstance(index, int) or index <= 0:
            raise TypeError("selected area-trigger location has invalid source_index")
        if isinstance(zone_id, bool) or not isinstance(zone_id, int) or zone_id <= 0:
            raise TypeError("selected area-trigger location has invalid zone_id")
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise TypeError("selected area-trigger location has invalid x")
        if isinstance(y, bool) or not isinstance(y, (int, float)):
            raise TypeError("selected area-trigger location has invalid y")
        parsed.append(AreaTriggerLocation(index, float(x), float(y), zone_id))
    parsed.sort(key=lambda location: location.source_index)
    return AreaTriggerData(entry_present, coords_present, tuple(parsed))


def _materialize_area_trigger(connection: sqlite3.Connection, area_trigger_id: int) -> _MaterializeResult:
    selected = _selected_area_trigger(connection, area_trigger_id)
    parent = connection.execute(
        "SELECT selected_entry_present, selected_coords_present, selected_location_count "
        "FROM area_triggers WHERE area_trigger_id = ?",
        (area_trigger_id,),
    ).fetchone()
    inserted = updated = deleted = protected = 0
    unresolved: list[dict[str, Any]] = []
    if selected.entry_present:
        desired_parent = (1, int(selected.coords_present), len(selected.locations))
        if parent is None:
            connection.execute(
                "INSERT INTO area_triggers(area_trigger_id, selected_entry_present, "
                "selected_coords_present, selected_location_count) VALUES (?, ?, ?, ?)",
                (area_trigger_id, *desired_parent),
            )
            inserted += 1
        elif tuple(
            int(parent[key])
            for key in (
                "selected_entry_present",
                "selected_coords_present",
                "selected_location_count",
            )
        ) != desired_parent:
            connection.execute(
                "UPDATE area_triggers SET selected_entry_present = 1, selected_coords_present = ?, "
                "selected_location_count = ? WHERE area_trigger_id = ?",
                (int(selected.coords_present), len(selected.locations), area_trigger_id),
            )
            updated += 1
    elif parent is not None and int(parent["selected_entry_present"]) != 0:
        connection.execute(
            "UPDATE area_triggers SET selected_entry_present = 0, selected_coords_present = 0, "
            "selected_location_count = 0 WHERE area_trigger_id = ?",
            (area_trigger_id,),
        )
        updated += 1

    current_rows = connection.execute(
        "SELECT source_index, zone_id, x, y FROM area_trigger_locations WHERE area_trigger_id = ?",
        (area_trigger_id,),
    ).fetchall()
    current = {int(row["source_index"]): row for row in current_rows}
    desired = {location.source_index: location for location in selected.locations}
    for source_index in sorted(set(current) - set(desired)):
        selection = _selection_for(
            connection,
            subject_kind="area_trigger",
            subject_key=area_trigger_id,
            fact_key=AREA_TRIGGER_ZONE_FACT,
            fact_instance_key=str(source_index),
        )
        if selection is not None and not _selection_is_managed(selection):
            protected += 1
            continue
        connection.execute(
            "DELETE FROM area_trigger_locations WHERE area_trigger_id = ? AND source_index = ?",
            (area_trigger_id, source_index),
        )
        deleted += 1

    # A parent row is needed for locations. A source-selected location set on a previously unseen
    # trigger creates that source-backed identity; an absent entry never creates a placeholder.
    if selected.locations and parent is None and not selected.entry_present:
        unresolved.extend(
            {
                "area_trigger_id": area_trigger_id,
                "source_index": location.source_index,
                "zone_id": location.zone_id,
                "reason": "location_without_selected_area_trigger_identity",
            }
            for location in selected.locations
        )
        return _MaterializeResult(inserted, updated, deleted, protected, tuple(unresolved))

    for source_index, location in sorted(desired.items()):
        selection = _selection_for(
            connection,
            subject_kind="area_trigger",
            subject_key=area_trigger_id,
            fact_key=AREA_TRIGGER_ZONE_FACT,
            fact_instance_key=str(source_index),
        )
        selected_target = _relation_target(selection)
        if selected_target is None or selected_target[:2] != ("zone", location.zone_id):
            unresolved.append(
                {
                    "area_trigger_id": area_trigger_id,
                    "source_index": source_index,
                    "zone_id": location.zone_id,
                    "reason": "missing_selected_primitive_relation",
                }
            )
            continue
        attributes = selected_target[2]
        x = attributes.get("x")
        y = attributes.get("y")
        coordinate_space = attributes.get("coordinate_space")
        if (
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or isinstance(y, bool)
            or not isinstance(y, (int, float))
            or coordinate_space != "zone_percent"
        ):
            unresolved.append(
                {
                    "area_trigger_id": area_trigger_id,
                    "source_index": source_index,
                    "zone_id": location.zone_id,
                    "reason": "invalid_selected_location_attributes",
                }
            )
            continue
        if not _identity_exists(connection, "zones", "zone_id", location.zone_id):
            unresolved.append(
                {
                    "area_trigger_id": area_trigger_id,
                    "source_index": source_index,
                    "zone_id": location.zone_id,
                    "reason": "missing_zone_identity",
                }
            )
            continue
        row = current.get(source_index)
        desired_values = (location.zone_id, float(x), float(y))
        if row is None:
            connection.execute(
                "INSERT INTO area_trigger_locations(area_trigger_id, source_index, zone_id, "
                "coordinate_space, x, y) VALUES (?, ?, ?, 'zone_percent', ?, ?)",
                (area_trigger_id, source_index, *desired_values),
            )
            inserted += 1
        elif (int(row["zone_id"]), float(row["x"]), float(row["y"])) != desired_values:
            connection.execute(
                "UPDATE area_trigger_locations SET zone_id = ?, coordinate_space = 'zone_percent', "
                "x = ?, y = ? WHERE area_trigger_id = ? AND source_index = ?",
                (*desired_values, area_trigger_id, source_index),
            )
            updated += 1

    child_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM area_trigger_locations WHERE area_trigger_id = ?",
            (area_trigger_id,),
        ).fetchone()[0]
    )
    if not selected.entry_present and child_count == 0:
        current_parent = connection.execute(
            "SELECT 1 FROM area_triggers WHERE area_trigger_id = ?",
            (area_trigger_id,),
        ).fetchone()
        if current_parent is not None:
            connection.execute(
                "DELETE FROM area_triggers WHERE area_trigger_id = ?", (area_trigger_id,)
            )
            deleted += 1
    return _MaterializeResult(inserted, updated, deleted, protected, tuple(unresolved))


def _duplicate_diagnostics(
    source_key: str, quest_id: int, parsed: QuestObjectives
) -> list[dict[str, Any]]:
    return [
        {
            "source_key": source_key,
            "quest_id": quest_id,
            "subtype": subtype,
            "duplicate_target_id": target_id,
        }
        for subtype in OBJECTIVE_SUBTYPES
        for target_id in parsed.duplicates[subtype]
    ]


def _sorted_unresolved(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))


def _objective_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        subtype: int(connection.execute(f"SELECT COUNT(*) FROM {spec[2]}").fetchone()[0])
        for subtype, spec in OBJECTIVE_FACTS.items()
    }


def reconcile_pfquest_turtle_quest_objectives(
    connection: sqlite3.Connection,
    *,
    pfquest_root: str | Path,
    pfquest_turtle_root: str | Path,
    pfquest_revision: str | None = None,
    turtle_revision: str | None = None,
) -> ImportSummary:
    """Reconcile selected P3-T04 objective facts and materialized objective geography anchors."""

    base_root = Path(pfquest_root)
    turtle_root = Path(pfquest_turtle_root)
    base_revision = _required_text(
        pfquest_revision or compute_pfquest_quest_objectives_revision(base_root),
        "pfquest_revision",
    )
    turtle_objective_revision = _required_text(
        turtle_revision or compute_pfquest_turtle_quest_objectives_revision(turtle_root),
        "turtle_revision",
    )

    # P3-T04 consumes the canonical identities/restrictions baseline. Verify the actual supplied
    # source trees match the already-validated P3-T03 runs, independently from this wider revision.
    identity_base_revision = compute_pfquest_quests_revision(base_root)
    identity_turtle_revision = compute_pfquest_turtle_quests_revision(turtle_root)
    progression_base_revision = compute_pfquest_quest_progression_revision(base_root)
    progression_turtle_revision = compute_pfquest_turtle_quest_progression_revision(turtle_root)
    base_source_id = _require_successful_import(
        connection,
        source_key=PFQUEST_SOURCE_KEY,
        source_revision=progression_base_revision,
        importer_prefix="pfquest-quest-progression/",
        task_label="P3-T03 base quest progression import",
    )
    turtle_source_id = _require_successful_import(
        connection,
        source_key=PFQUEST_TURTLE_SOURCE_KEY,
        source_revision=progression_turtle_revision,
        importer_prefix="pfquest-quest-progression/",
        task_label="P3-T03 Turtle quest progression reconciliation",
    )

    quest_tables = _load_effective_tables(base_root, turtle_root)
    (
        base_itemreq,
        patch_itemreq,
        effective_itemreq,
        base_area,
        patch_area,
        effective_area,
    ) = _load_auxiliary_tables(base_root, turtle_root)

    canonical_quest_ids = {
        int(row[0]) for row in connection.execute("SELECT quest_id FROM quests").fetchall()
    }
    base_quest_ids = {
        int(key)
        for key in quest_tables.base_data
        if isinstance(key, int) and not isinstance(key, bool)
    }
    turtle_quest_ids = sorted(
        int(key)
        for key in quest_tables.patch_data
        if isinstance(key, int) and not isinstance(key, bool)
    )
    base_quest_candidates = sorted(canonical_quest_ids | base_quest_ids)
    all_quest_candidates = sorted(set(base_quest_candidates) | set(turtle_quest_ids))

    existing_item_target_ids = {
        int(row[0]) for row in connection.execute("SELECT item_id FROM item_use_target_sets").fetchall()
    }
    base_item_ids = {
        int(key) for key in base_itemreq if isinstance(key, int) and not isinstance(key, bool)
    }
    turtle_item_ids = sorted(
        int(key) for key in patch_itemreq if isinstance(key, int) and not isinstance(key, bool)
    )
    base_item_candidates = sorted(base_item_ids | existing_item_target_ids)
    all_item_candidates = sorted(set(base_item_candidates) | set(turtle_item_ids))

    existing_area_ids = {
        int(row[0]) for row in connection.execute("SELECT area_trigger_id FROM area_triggers").fetchall()
    }
    base_area_ids = {
        int(key) for key in base_area if isinstance(key, int) and not isinstance(key, bool)
    }
    turtle_area_ids = sorted(
        int(key) for key in patch_area if isinstance(key, int) and not isinstance(key, bool)
    )
    base_area_candidates = sorted(base_area_ids | existing_area_ids)
    all_area_candidates = sorted(set(base_area_candidates) | set(turtle_area_ids))

    base_rows_read = len(base_quest_candidates) + len(base_item_candidates) + len(base_area_candidates)
    turtle_rows_read = len(turtle_quest_ids) + len(turtle_item_ids) + len(turtle_area_ids)
    base_batch_id = _create_batch(
        connection,
        source_id=base_source_id,
        revision=base_revision,
        rows_read=base_rows_read,
        importer_version=f"{IMPORTER_VERSION}-base-evidence",
    )
    turtle_batch_id = _create_batch(
        connection,
        source_id=turtle_source_id,
        revision=turtle_objective_revision,
        rows_read=turtle_rows_read,
        importer_version=IMPORTER_VERSION,
    )

    inserted = updated = deleted = protected = 0
    unresolved: list[dict[str, Any]] = []
    duplicate_rows: list[dict[str, Any]] = []
    changed_quest_ids: list[int] = []
    changed_item_ids: list[int] = []
    changed_area_ids: list[int] = []

    try:
        base_parsed_quests: dict[int, QuestObjectives] = {}
        for quest_id in base_quest_candidates:
            parsed = parse_quest_objectives(quest_tables.base_data.get(quest_id), quest_id=quest_id)
            base_parsed_quests[quest_id] = parsed
            duplicate_rows.extend(_duplicate_diagnostics(PFQUEST_SOURCE_KEY, quest_id, parsed))
            _record_quest_objectives(
                connection,
                batch_id=base_batch_id,
                quest_id=quest_id,
                parsed=parsed,
                source_key=PFQUEST_SOURCE_KEY,
            )
        for quest_id in turtle_quest_ids:
            effective = parse_quest_objectives(
                quest_tables.effective_data.get(quest_id), quest_id=quest_id
            )
            base = base_parsed_quests.get(quest_id) or parse_quest_objectives(
                quest_tables.base_data.get(quest_id), quest_id=quest_id
            )
            if effective != base:
                changed_quest_ids.append(quest_id)
            duplicate_rows.extend(
                _duplicate_diagnostics(PFQUEST_TURTLE_SOURCE_KEY, quest_id, effective)
            )
            _record_quest_objectives(
                connection,
                batch_id=turtle_batch_id,
                quest_id=quest_id,
                parsed=effective,
                source_key=PFQUEST_TURTLE_SOURCE_KEY,
            )

        base_parsed_items: dict[int, ItemUseTargets] = {}
        for item_id in base_item_candidates:
            parsed = parse_item_use_targets(base_itemreq.get(item_id), item_id=item_id)
            base_parsed_items[item_id] = parsed
            _record_item_use_targets(
                connection,
                batch_id=base_batch_id,
                item_id=item_id,
                parsed=parsed,
                source_key=PFQUEST_SOURCE_KEY,
            )
        for item_id in turtle_item_ids:
            effective = parse_item_use_targets(effective_itemreq.get(item_id), item_id=item_id)
            base = base_parsed_items.get(item_id) or parse_item_use_targets(
                base_itemreq.get(item_id), item_id=item_id
            )
            if effective != base:
                changed_item_ids.append(item_id)
            _record_item_use_targets(
                connection,
                batch_id=turtle_batch_id,
                item_id=item_id,
                parsed=effective,
                source_key=PFQUEST_TURTLE_SOURCE_KEY,
            )

        base_parsed_areas: dict[int, AreaTriggerData] = {}
        for area_trigger_id in base_area_candidates:
            parsed = parse_area_trigger(base_area.get(area_trigger_id), area_trigger_id=area_trigger_id)
            base_parsed_areas[area_trigger_id] = parsed
            _record_area_trigger(
                connection,
                batch_id=base_batch_id,
                area_trigger_id=area_trigger_id,
                parsed=parsed,
                source_key=PFQUEST_SOURCE_KEY,
            )
        for area_trigger_id in turtle_area_ids:
            effective = parse_area_trigger(
                effective_area.get(area_trigger_id), area_trigger_id=area_trigger_id
            )
            base = base_parsed_areas.get(area_trigger_id) or parse_area_trigger(
                base_area.get(area_trigger_id), area_trigger_id=area_trigger_id
            )
            if effective != base:
                changed_area_ids.append(area_trigger_id)
            _record_area_trigger(
                connection,
                batch_id=turtle_batch_id,
                area_trigger_id=area_trigger_id,
                parsed=effective,
                source_key=PFQUEST_TURTLE_SOURCE_KEY,
            )

        # Materialize auxiliary identities/relations before quests that reference them.
        for area_trigger_id in all_area_candidates:
            result = _materialize_area_trigger(connection, area_trigger_id)
            inserted += result.inserted
            updated += result.updated
            deleted += result.deleted
            protected += result.protected
            unresolved.extend(result.unresolved)
        for item_id in all_item_candidates:
            result = _materialize_item_targets(connection, item_id)
            inserted += result.inserted
            updated += result.updated
            deleted += result.deleted
            protected += result.protected
            unresolved.extend(result.unresolved)
        for quest_id in all_quest_candidates:
            result = _materialize_quest(connection, quest_id)
            inserted += result.inserted
            updated += result.updated
            deleted += result.deleted
            protected += result.protected
            unresolved.extend(result.unresolved)

        duplicate_rows.sort(
            key=lambda row: (
                str(row["source_key"]),
                int(row["quest_id"]),
                str(row["subtype"]),
                int(row["duplicate_target_id"]),
            )
        )
        unresolved_sorted = _sorted_unresolved(unresolved)
        warning_count = len(duplicate_rows) + len(unresolved_sorted)
        details = {
            "identity_base_revision": identity_base_revision,
            "identity_turtle_revision": identity_turtle_revision,
            "progression_base_revision": progression_base_revision,
            "progression_turtle_revision": progression_turtle_revision,
            "base_objective_revision": base_revision,
            "turtle_objective_revision": turtle_objective_revision,
            "base_candidate_quest_count": len(base_quest_candidates),
            "turtle_touched_quest_count": len(turtle_quest_ids),
            "base_itemreq_entry_count": len(base_item_candidates),
            "turtle_touched_itemreq_count": len(turtle_item_ids),
            "base_area_trigger_count": len(base_area_candidates),
            "turtle_touched_area_trigger_count": len(turtle_area_ids),
            "changed_effective_objective_quest_ids": changed_quest_ids,
            "changed_effective_itemreq_ids": changed_item_ids,
            "changed_effective_area_trigger_ids": changed_area_ids,
            "duplicate_source_objective_members": duplicate_rows,
            "unresolved_objective_materialization": unresolved_sorted,
            "protected_canonical_rows_retained": protected,
            "canonical_objective_rows_deleted": deleted,
            "objective_counts_by_subtype": _objective_counts(connection),
            "area_trigger_count": int(
                connection.execute(
                    "SELECT COUNT(*) FROM area_triggers WHERE selected_entry_present = 1"
                ).fetchone()[0]
            ),
            "area_trigger_location_count": int(
                connection.execute("SELECT COUNT(*) FROM area_trigger_locations").fetchone()[0]
            ),
            "item_use_creature_target_count": int(
                connection.execute("SELECT COUNT(*) FROM item_use_creature_targets").fetchone()[0]
            ),
            "item_use_gameobject_target_count": int(
                connection.execute("SELECT COUNT(*) FROM item_use_gameobject_targets").fetchone()[0]
            ),
        }
        _finish_batch(
            connection,
            batch_id=base_batch_id,
            rows_read=base_rows_read,
            rows_inserted=0,
            rows_updated=0,
            warning_count=0,
            details={"role": "base-p3-t04-evidence", "objective_revision": base_revision},
        )
        _finish_batch(
            connection,
            batch_id=turtle_batch_id,
            rows_read=turtle_rows_read,
            rows_inserted=inserted,
            rows_updated=updated,
            warning_count=warning_count,
            details=details,
        )
    except Exception as exc:
        _fail_batch(connection, base_batch_id, exc)
        _fail_batch(connection, turtle_batch_id, exc)
        raise

    return ImportSummary(
        source_key=PFQUEST_TURTLE_SOURCE_KEY,
        source_revision=turtle_objective_revision,
        status="succeeded",
        rows_read=base_rows_read + turtle_rows_read,
        rows_accepted=base_rows_read + turtle_rows_read,
        rows_skipped=0,
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=warning_count,
        error_count=0,
        details=details,
    )
