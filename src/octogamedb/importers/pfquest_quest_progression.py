"""P3-T03 quest restrictions/dependency reconciliation for pfQuest + Turtle.

This bounded adapter intentionally runs after the validated P3-T01/P3-T02 identity/endpoints
pipeline.  It preserves pfQuest source semantics for lvl/min/race/class/pre/close without
reinterpreting objectives, rewards, skill requirements, or item-start behavior.
"""

from __future__ import annotations

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
    compute_pfquest_turtle_quests_revision,
)
from octogamedb.importers.pfquest_quests import compute_pfquest_quests_revision
from octogamedb.importers.pfquest_world import PFQUEST_SOURCE_KEY, PfQuestParseError
from octogamedb.importers.summary import ImportSummary

IMPORTER_VERSION = "pfquest-quest-progression/1"
BASE_SELECTION_POLICY = "pfquest-base-effective-quest-progression"
TURTLE_SELECTION_POLICY = "pfquest-turtle-effective-quest-progression"

QUEST_LEVEL_FACT = "quest_level"
MINIMUM_LEVEL_FACT = "minimum_level"
RACE_MASK_FACT = "race_mask"
CLASS_MASK_FACT = "class_mask"
PREREQUISITE_RAW_FACT = "quest_prerequisite_source_list"
PREREQUISITE_SET_FACT = "quest_prerequisite_set"
CLOSE_RAW_FACT = "quest_close_source_list"
CLOSE_SET_FACT = "quest_close_set"
PREREQUISITE_RELATION_FACT = "prerequisite"
CLOSE_MEMBER_RELATION_FACT = "close_group_member"

SCALAR_FIELDS = (
    ("lvl", QUEST_LEVEL_FACT, "quest_level"),
    ("min", MINIMUM_LEVEL_FACT, "minimum_level"),
    ("race", RACE_MASK_FACT, "race_mask"),
    ("class", CLASS_MASK_FACT, "class_mask"),
)

_DEFAULT_BASE_POLICIES = frozenset({None, "first-observation", BASE_SELECTION_POLICY})


@dataclass(frozen=True)
class QuestProgression:
    """Source-shaped P3-T03 fields plus conservative normalized member sets."""

    quest_level: int | None
    minimum_level: int | None
    race_mask: int | None
    class_mask: int | None
    prerequisite_source_ids: tuple[int, ...] | None
    prerequisite_ids: tuple[int, ...]
    close_source_ids: tuple[int, ...] | None
    close_member_ids: tuple[int, ...]
    duplicate_prerequisite_ids: tuple[int, ...]
    duplicate_close_ids: tuple[int, ...]


@dataclass(frozen=True)
class _Selection:
    observation_id: int
    source_key: str
    selection_policy: str | None
    value: Any


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


def compute_pfquest_quest_progression_revision(source_root: str | Path) -> str:
    """Use the exact validated P3 quest-composition revision for the base source view."""

    return compute_pfquest_quests_revision(source_root)


def compute_pfquest_turtle_quest_progression_revision(source_root: str | Path) -> str:
    """Use the exact validated P3 Turtle compositor revision for the effective source view."""

    return compute_pfquest_turtle_quests_revision(source_root)


def _integer_or_none(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise PfQuestParseError(f"{label} must be an integer when present")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise PfQuestParseError(f"{label} must be an integer when present")


def _source_id_list(value: Any, *, label: str) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise PfQuestParseError(f"{label} must be a Lua array table when present")
    non_integer_keys = [key for key in value if isinstance(key, bool) or not isinstance(key, int)]
    if non_integer_keys:
        raise PfQuestParseError(f"{label} must contain only positional integer keys")
    ids: list[int] = []
    for key in sorted(value):
        parsed = _integer_or_none(value[key], label=f"{label}[{key}]")
        if parsed is None:
            raise PfQuestParseError(f"{label}[{key}] must be an integer quest ID")
        ids.append(parsed)
    return tuple(ids)


def _duplicates(values: tuple[int, ...] | None) -> tuple[int, ...]:
    if not values:
        return ()
    seen: set[int] = set()
    duplicate: set[int] = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return tuple(sorted(duplicate))


def parse_quest_progression(record: Any, *, quest_id: int) -> QuestProgression:
    """Parse the six P3-T03 source fields without assigning extra game semantics."""

    if record is None:
        record = {}
    if not isinstance(record, dict):
        raise PfQuestParseError(f"quest[{quest_id}] must be a Lua table")

    pre_raw = _source_id_list(record.get("pre"), label=f"quest[{quest_id}].pre")
    close_raw = _source_id_list(record.get("close"), label=f"quest[{quest_id}].close")
    return QuestProgression(
        quest_level=_integer_or_none(record.get("lvl"), label=f"quest[{quest_id}].lvl"),
        minimum_level=_integer_or_none(record.get("min"), label=f"quest[{quest_id}].min"),
        race_mask=_integer_or_none(record.get("race"), label=f"quest[{quest_id}].race"),
        class_mask=_integer_or_none(record.get("class"), label=f"quest[{quest_id}].class"),
        prerequisite_source_ids=pre_raw,
        prerequisite_ids=tuple(sorted(set(pre_raw or ()))),
        close_source_ids=close_raw,
        close_member_ids=tuple(sorted(set(close_raw or ()))),
        duplicate_prerequisite_ids=_duplicates(pre_raw),
        duplicate_close_ids=_duplicates(close_raw),
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
            f"P3-T03 requires {task_label} to succeed first at revision {source_revision}"
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


def _selection_for_scalar(
    connection: sqlite3.Connection, *, quest_id: int, fact_key: str
) -> _Selection | None:
    row = connection.execute(
        """
        SELECT id FROM observation_groups
        WHERE subject_kind = 'quest' AND subject_key = ?
          AND fact_key = ? AND fact_kind = 'scalar' AND fact_instance_key = ''
        """,
        (str(quest_id), fact_key),
    ).fetchone()
    return None if row is None else _selection_for_group(connection, int(row["id"]))


def _selection_for_relation(
    connection: sqlite3.Connection, *, quest_id: int, fact_key: str, target_id: int
) -> _Selection | None:
    row = connection.execute(
        """
        SELECT id FROM observation_groups
        WHERE subject_kind = 'quest' AND subject_key = ?
          AND fact_key = ? AND fact_kind = 'relation' AND fact_instance_key = ?
        """,
        (str(quest_id), fact_key, str(target_id)),
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
    reason: str,
) -> None:
    group_id = _group_for_observation(connection, observation_id)
    current = _selection_for_group(connection, group_id)
    if source_key == PFQUEST_SOURCE_KEY:
        if current is not None:
            return
        policy = BASE_SELECTION_POLICY
    else:
        if current is not None and not _selection_is_managed(current):
            return
        policy = TURTLE_SELECTION_POLICY
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
    quest_id: int,
    fact_key: str,
    value: Any,
    source_key: str,
    raw_identifier: str,
) -> None:
    observation_id = record_scalar_observation(
        connection,
        subject_kind="quest",
        subject_key=quest_id,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type="quest_progression",
        raw_identifier=raw_identifier,
    )
    _select_if_missing_or_managed(
        connection,
        observation_id=observation_id,
        source_key=source_key,
        reason=(
            "Base pfQuest establishes the initial selected P3-T03 effective field."
            if source_key == PFQUEST_SOURCE_KEY
            else "The active Turtle whole-entry quest view supersedes managed/base P3-T03 evidence."
        ),
    )


def _record_relation(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    quest_id: int,
    fact_key: str,
    target_id: int,
    source_key: str,
    attributes: dict[str, Any],
) -> None:
    observation_id = record_relation_observation(
        connection,
        subject_kind="quest",
        subject_key=quest_id,
        fact_key=fact_key,
        import_batch_id=batch_id,
        target_kind="quest",
        target_key=target_id,
        relation_instance_key=str(target_id),
        attributes=attributes,
        source_record_type="quest_progression_relation",
        raw_identifier=f"{quest_id}:{fact_key}:{target_id}",
    )
    _select_if_missing_or_managed(
        connection,
        observation_id=observation_id,
        source_key=source_key,
        reason=(
            "Base pfQuest establishes the initial selected P3-T03 primitive relation."
            if source_key == PFQUEST_SOURCE_KEY
            else "The active Turtle whole-entry quest view supersedes managed/base P3-T03 relation evidence."
        ),
    )


def _record_progression(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    quest_id: int,
    progression: QuestProgression,
    source_key: str,
) -> None:
    for source_field, fact_key, attr_name in SCALAR_FIELDS:
        _record_scalar(
            connection,
            batch_id=batch_id,
            quest_id=quest_id,
            fact_key=fact_key,
            value=getattr(progression, attr_name),
            source_key=source_key,
            raw_identifier=f"{quest_id}:{source_field}",
        )

    _record_scalar(
        connection,
        batch_id=batch_id,
        quest_id=quest_id,
        fact_key=PREREQUISITE_RAW_FACT,
        value=(
            None
            if progression.prerequisite_source_ids is None
            else list(progression.prerequisite_source_ids)
        ),
        source_key=source_key,
        raw_identifier=f"{quest_id}:pre",
    )
    _record_scalar(
        connection,
        batch_id=batch_id,
        quest_id=quest_id,
        fact_key=PREREQUISITE_SET_FACT,
        value=list(progression.prerequisite_ids),
        source_key=source_key,
        raw_identifier=f"{quest_id}:pre:set",
    )
    _record_scalar(
        connection,
        batch_id=batch_id,
        quest_id=quest_id,
        fact_key=CLOSE_RAW_FACT,
        value=None if progression.close_source_ids is None else list(progression.close_source_ids),
        source_key=source_key,
        raw_identifier=f"{quest_id}:close",
    )
    _record_scalar(
        connection,
        batch_id=batch_id,
        quest_id=quest_id,
        fact_key=CLOSE_SET_FACT,
        value=list(progression.close_member_ids),
        source_key=source_key,
        raw_identifier=f"{quest_id}:close:set",
    )

    for target_id in progression.prerequisite_ids:
        _record_relation(
            connection,
            batch_id=batch_id,
            quest_id=quest_id,
            fact_key=PREREQUISITE_RELATION_FACT,
            target_id=target_id,
            source_key=source_key,
            attributes={"requirement_mode": "any_of"},
        )
    for target_id in progression.close_member_ids:
        _record_relation(
            connection,
            batch_id=batch_id,
            quest_id=quest_id,
            fact_key=CLOSE_MEMBER_RELATION_FACT,
            target_id=target_id,
            source_key=source_key,
            attributes={"semantics": "exclusive_group_member_set"},
        )


def _selected_integer_or_none(
    connection: sqlite3.Connection, *, quest_id: int, fact_key: str
) -> int | None:
    selection = _selection_for_scalar(connection, quest_id=quest_id, fact_key=fact_key)
    if selection is None or selection.value is None:
        return None
    value = selection.value
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"selected {fact_key} for quest {quest_id} must be integer or null")
    return value


def _selected_id_set(
    connection: sqlite3.Connection, *, quest_id: int, fact_key: str
) -> tuple[int, ...]:
    selection = _selection_for_scalar(connection, quest_id=quest_id, fact_key=fact_key)
    if selection is None:
        return ()
    if not isinstance(selection.value, list):
        raise TypeError(f"selected {fact_key} for quest {quest_id} must be an ID list")
    ids: list[int] = []
    for value in selection.value:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"selected {fact_key} for quest {quest_id} contains a non-integer ID")
        ids.append(value)
    return tuple(sorted(set(ids)))


def _selected_source_list(
    connection: sqlite3.Connection, *, quest_id: int, fact_key: str
) -> tuple[int, ...] | None:
    selection = _selection_for_scalar(connection, quest_id=quest_id, fact_key=fact_key)
    if selection is None or selection.value is None:
        return None
    if not isinstance(selection.value, list):
        raise TypeError(f"selected {fact_key} for quest {quest_id} must be an ID list or null")
    values: list[int] = []
    for value in selection.value:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"selected {fact_key} for quest {quest_id} contains a non-integer ID")
        values.append(value)
    return tuple(values)


def _quest_exists(connection: sqlite3.Connection, quest_id: int) -> bool:
    return (
        connection.execute("SELECT 1 FROM quests WHERE quest_id = ?", (quest_id,)).fetchone()
        is not None
    )


def _relation_selection_matches(
    selection: _Selection | None, *, expected_target: int, attribute_key: str, attribute_value: str
) -> bool:
    if selection is None or not isinstance(selection.value, dict):
        return False
    target = selection.value.get("target")
    attributes = selection.value.get("attributes")
    if not isinstance(target, dict) or not isinstance(attributes, dict):
        return False
    return (
        target.get("kind") == "quest"
        and str(target.get("key")) == str(expected_target)
        and attributes.get(attribute_key) == attribute_value
    )


def _current_member_ids(
    connection: sqlite3.Connection, *, table: str, quest_id: int
) -> set[int]:
    rows = connection.execute(
        f"SELECT member_quest_id FROM {table} WHERE quest_id = ?", (quest_id,)
    ).fetchall()
    return {int(row[0]) for row in rows}


def _sync_grouped_set(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    desired_ids: tuple[int, ...],
    set_table: str,
    member_table: str,
    count_column: str,
    mode_column: str,
    mode_value: str,
    relation_fact: str,
    attribute_key: str,
    unresolved_kind: str,
    selected_set_present: bool,
) -> _MaterializeResult:
    existing_parent = connection.execute(
        f"SELECT {count_column}, {mode_column}, selected_set_present FROM {set_table} WHERE quest_id = ?",
        (quest_id,),
    ).fetchone()
    inserted = 0
    updated = 0
    deleted = 0
    protected = 0
    unresolved: list[dict[str, Any]] = []

    current_ids = _current_member_ids(connection, table=member_table, quest_id=quest_id)
    desired = set(desired_ids)

    # Remove stale managed members. Explicit/custom primitive selections remain materialized.
    for target_id in sorted(current_ids - desired):
        selection = _selection_for_relation(
            connection, quest_id=quest_id, fact_key=relation_fact, target_id=target_id
        )
        if not _selection_is_managed(selection):
            protected += 1
            continue
        connection.execute(
            f"DELETE FROM {member_table} WHERE quest_id = ? AND member_quest_id = ?",
            (quest_id, target_id),
        )
        deleted += 1

    retained_ids = _current_member_ids(connection, table=member_table, quest_id=quest_id)
    should_have_parent = bool(selected_set_present or desired_ids or retained_ids)
    if should_have_parent:
        if existing_parent is None:
            connection.execute(
                f"INSERT INTO {set_table}(quest_id, {mode_column}, selected_set_present, {count_column}) "
                "VALUES (?, ?, ?, ?)",
                (quest_id, mode_value, int(selected_set_present), len(desired_ids)),
            )
            inserted += 1
        elif (
            str(existing_parent[mode_column]) != mode_value
            or int(existing_parent["selected_set_present"]) != int(selected_set_present)
            or int(existing_parent[count_column]) != len(desired_ids)
        ):
            connection.execute(
                f"UPDATE {set_table} SET {mode_column} = ?, selected_set_present = ?, "
                f"{count_column} = ? WHERE quest_id = ?",
                (mode_value, int(selected_set_present), len(desired_ids), quest_id),
            )
            updated += 1
    elif existing_parent is not None:
        connection.execute(f"DELETE FROM {set_table} WHERE quest_id = ?", (quest_id,))
        deleted += 1

    # Materialize selected members only when both primitive selection and target identity exist.
    # The parent set is created first so member foreign keys remain valid even for a new set.
    for target_id in desired_ids:
        selection = _selection_for_relation(
            connection, quest_id=quest_id, fact_key=relation_fact, target_id=target_id
        )
        if not _relation_selection_matches(
            selection,
            expected_target=target_id,
            attribute_key=attribute_key,
            attribute_value=mode_value,
        ):
            unresolved.append(
                {
                    "quest_id": quest_id,
                    "relation": unresolved_kind,
                    "target_quest_id": target_id,
                    "reason": "missing_selected_primitive_relation",
                }
            )
            continue
        if not _quest_exists(connection, target_id):
            unresolved.append(
                {
                    "quest_id": quest_id,
                    "relation": unresolved_kind,
                    "target_quest_id": target_id,
                    "reason": "missing_quest_identity",
                }
            )
            continue
        existing = connection.execute(
            f"SELECT 1 FROM {member_table} WHERE quest_id = ? AND member_quest_id = ?",
            (quest_id, target_id),
        ).fetchone()
        if existing is None:
            connection.execute(
                f"INSERT INTO {member_table}(quest_id, member_quest_id) VALUES (?, ?)",
                (quest_id, target_id),
            )
            inserted += 1

    return _MaterializeResult(
        inserted=inserted,
        updated=updated,
        deleted=deleted,
        protected=protected,
        unresolved=tuple(unresolved),
    )


def _protected_selected_fact_count(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    prerequisites: tuple[int, ...],
    closes: tuple[int, ...],
) -> int:
    protected = 0
    scalar_facts = (
        QUEST_LEVEL_FACT,
        MINIMUM_LEVEL_FACT,
        RACE_MASK_FACT,
        CLASS_MASK_FACT,
        PREREQUISITE_RAW_FACT,
        PREREQUISITE_SET_FACT,
        CLOSE_RAW_FACT,
        CLOSE_SET_FACT,
    )
    for fact_key in scalar_facts:
        selection = _selection_for_scalar(connection, quest_id=quest_id, fact_key=fact_key)
        if selection is not None and not _selection_is_managed(selection):
            protected += 1

    relation_sets = (
        (
            PREREQUISITE_RELATION_FACT,
            prerequisites,
            "requirement_mode",
            "any_of",
        ),
        (
            CLOSE_MEMBER_RELATION_FACT,
            closes,
            "semantics",
            "exclusive_group_member_set",
        ),
    )
    for fact_key, target_ids, attribute_key, attribute_value in relation_sets:
        for target_id in target_ids:
            selection = _selection_for_relation(
                connection, quest_id=quest_id, fact_key=fact_key, target_id=target_id
            )
            if (
                selection is not None
                and not _selection_is_managed(selection)
                and _relation_selection_matches(
                    selection,
                    expected_target=target_id,
                    attribute_key=attribute_key,
                    attribute_value=attribute_value,
                )
                and _quest_exists(connection, target_id)
            ):
                protected += 1
    return protected


def _materialize_quest(connection: sqlite3.Connection, quest_id: int) -> _MaterializeResult:
    if not _quest_exists(connection, quest_id):
        return _MaterializeResult()

    desired_scalars = (
        _selected_integer_or_none(connection, quest_id=quest_id, fact_key=QUEST_LEVEL_FACT),
        _selected_integer_or_none(connection, quest_id=quest_id, fact_key=MINIMUM_LEVEL_FACT),
        _selected_integer_or_none(connection, quest_id=quest_id, fact_key=RACE_MASK_FACT),
        _selected_integer_or_none(connection, quest_id=quest_id, fact_key=CLASS_MASK_FACT),
    )
    current = connection.execute(
        """
        SELECT quest_level, minimum_level, race_mask, class_mask
        FROM quests WHERE quest_id = ?
        """,
        (quest_id,),
    ).fetchone()
    updated = 0
    if tuple(current) != desired_scalars:
        connection.execute(
            """
            UPDATE quests
            SET quest_level = ?, minimum_level = ?, race_mask = ?, class_mask = ?
            WHERE quest_id = ?
            """,
            (*desired_scalars, quest_id),
        )
        updated = 1

    prerequisites = _selected_id_set(
        connection, quest_id=quest_id, fact_key=PREREQUISITE_SET_FACT
    )
    prerequisite_source = _selected_source_list(
        connection, quest_id=quest_id, fact_key=PREREQUISITE_RAW_FACT
    )
    closes = _selected_id_set(connection, quest_id=quest_id, fact_key=CLOSE_SET_FACT)
    close_source = _selected_source_list(
        connection, quest_id=quest_id, fact_key=CLOSE_RAW_FACT
    )
    protected = _protected_selected_fact_count(
        connection, quest_id=quest_id, prerequisites=prerequisites, closes=closes
    )
    pre_result = _sync_grouped_set(
        connection,
        quest_id=quest_id,
        desired_ids=prerequisites,
        set_table="quest_prerequisite_sets",
        member_table="quest_prerequisite_set_members",
        count_column="selected_member_count",
        mode_column="requirement_mode",
        mode_value="any_of",
        relation_fact=PREREQUISITE_RELATION_FACT,
        attribute_key="requirement_mode",
        unresolved_kind="prerequisite",
        selected_set_present=prerequisite_source is not None or bool(prerequisites),
    )
    close_result = _sync_grouped_set(
        connection,
        quest_id=quest_id,
        desired_ids=closes,
        set_table="quest_close_sets",
        member_table="quest_close_set_members",
        count_column="selected_member_count",
        mode_column="set_semantics",
        mode_value="exclusive_group_member_set",
        relation_fact=CLOSE_MEMBER_RELATION_FACT,
        attribute_key="semantics",
        unresolved_kind="close_group_member",
        selected_set_present=close_source is not None or bool(closes),
    )
    return _MaterializeResult(
        inserted=pre_result.inserted + close_result.inserted,
        updated=updated + pre_result.updated + close_result.updated,
        deleted=pre_result.deleted + close_result.deleted,
        protected=protected + pre_result.protected + close_result.protected,
        unresolved=pre_result.unresolved + close_result.unresolved,
    )


def _duplicate_diagnostics(
    source_key: str, quest_id: int, progression: QuestProgression
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, duplicate_ids in (
        ("pre", progression.duplicate_prerequisite_ids),
        ("close", progression.duplicate_close_ids),
    ):
        for duplicate_id in duplicate_ids:
            rows.append(
                {
                    "source_key": source_key,
                    "quest_id": quest_id,
                    "field": field,
                    "duplicate_quest_id": duplicate_id,
                }
            )
    return rows


def _selected_prerequisite_graph(connection: sqlite3.Connection) -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {}
    rows = connection.execute(
        "SELECT quest_id, member_quest_id FROM quest_prerequisite_set_members ORDER BY quest_id, member_quest_id"
    ).fetchall()
    for row in rows:
        graph.setdefault(int(row[0]), set()).add(int(row[1]))
        graph.setdefault(int(row[1]), set())
    return graph


def _strongly_connected_components(graph: dict[int, set[int]]) -> list[list[int]]:
    index = 0
    stack: list[int] = []
    on_stack: set[int] = set()
    indexes: dict[int, int] = {}
    lowlinks: dict[int, int] = {}
    components: list[list[int]] = []

    def visit(node: int) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(graph.get(node, ())):
            if target not in indexes:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[target])
        if lowlinks[node] == indexes[node]:
            component: list[int] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indexes:
            visit(node)
    return sorted((component for component in components if len(component) > 1), key=lambda c: c)


def _dependency_diagnostics(connection: sqlite3.Connection) -> dict[str, Any]:
    graph = _selected_prerequisite_graph(connection)
    self_ids = sorted(node for node, targets in graph.items() if node in targets)
    cycles = _strongly_connected_components(graph)

    selected_close_sets: dict[int, tuple[int, ...]] = {}
    for row in connection.execute("SELECT quest_id FROM quests ORDER BY quest_id").fetchall():
        quest_id = int(row[0])
        selected_close_sets[quest_id] = _selected_id_set(
            connection, quest_id=quest_id, fact_key=CLOSE_SET_FACT
        )
    close_self_missing = sorted(
        quest_id
        for quest_id, members in selected_close_sets.items()
        if members and quest_id not in members
    )
    close_self_present = sorted(
        quest_id
        for quest_id, members in selected_close_sets.items()
        if quest_id in members
    )
    mismatches: set[tuple[int, int]] = set()
    for quest_id, members in selected_close_sets.items():
        if not members:
            continue
        member_set = set(members)
        for member in members:
            if member in selected_close_sets:
                peer = selected_close_sets[member]
                if set(peer) != member_set:
                    mismatches.add(tuple(sorted((quest_id, member))))

    return {
        "self_prerequisite_ids": self_ids,
        "prerequisite_cycles": cycles,
        "close_self_member_ids": close_self_present,
        "close_self_missing_ids": close_self_missing,
        "close_group_mismatch_pairs": [list(pair) for pair in sorted(mismatches)],
    }


def _sorted_unresolved(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            int(row["quest_id"]),
            str(row["relation"]),
            int(row["target_quest_id"]),
            str(row["reason"]),
        ),
    )


def reconcile_pfquest_turtle_quest_progression(
    connection: sqlite3.Connection,
    *,
    pfquest_root: str | Path,
    pfquest_turtle_root: str | Path,
    pfquest_revision: str | None = None,
    turtle_revision: str | None = None,
) -> ImportSummary:
    """Reconcile the bounded P3-T03 fact family after P3-T01/P3-T02.

    ``pfquest_revision`` and ``turtle_revision`` refer to the P3-T03 bounded source inputs.  The
    function independently verifies that the matching P3-T01/P3-T02 identity pipeline already ran
    against the currently supplied source trees before it writes progression evidence.
    """

    base_root = Path(pfquest_root)
    turtle_root = Path(pfquest_turtle_root)
    base_progression_revision = _required_text(
        pfquest_revision or compute_pfquest_quest_progression_revision(base_root),
        "pfquest_revision",
    )
    turtle_progression_revision = _required_text(
        turtle_revision or compute_pfquest_turtle_quest_progression_revision(turtle_root),
        "turtle_revision",
    )

    identity_base_revision = compute_pfquest_quests_revision(base_root)
    identity_turtle_revision = compute_pfquest_turtle_quests_revision(turtle_root)
    base_source_id = _require_successful_import(
        connection,
        source_key=PFQUEST_SOURCE_KEY,
        source_revision=identity_base_revision,
        importer_prefix="pfquest-quests/",
        task_label="P3-T01 base quest import",
    )
    turtle_source_id = _require_successful_import(
        connection,
        source_key=PFQUEST_TURTLE_SOURCE_KEY,
        source_revision=identity_turtle_revision,
        importer_prefix="pfquest-quest-overlay-reconcile/",
        task_label="P3-T02 Turtle quest reconciliation",
    )

    tables = _load_effective_tables(base_root, turtle_root)
    canonical_ids = {
        int(row[0]) for row in connection.execute("SELECT quest_id FROM quests").fetchall()
    }
    base_data_ids = {
        int(key)
        for key in tables.base_data
        if isinstance(key, int) and not isinstance(key, bool)
    }
    turtle_touched_ids = sorted(
        int(key)
        for key in tables.patch_data
        if isinstance(key, int) and not isinstance(key, bool)
    )
    base_candidate_ids = sorted(base_data_ids | canonical_ids)
    all_candidate_ids = sorted(set(base_candidate_ids) | set(turtle_touched_ids))

    base_batch_id = _create_batch(
        connection,
        source_id=base_source_id,
        revision=base_progression_revision,
        rows_read=len(base_candidate_ids),
        importer_version=f"{IMPORTER_VERSION}-base-evidence",
    )
    turtle_batch_id = _create_batch(
        connection,
        source_id=turtle_source_id,
        revision=turtle_progression_revision,
        rows_read=len(turtle_touched_ids),
        importer_version=IMPORTER_VERSION,
    )

    duplicate_diagnostics: list[dict[str, Any]] = []
    changed_effective_ids: list[int] = []
    inserted = 0
    updated = 0
    deleted = 0
    protected = 0
    unresolved: list[dict[str, Any]] = []

    try:
        base_progression: dict[int, QuestProgression] = {}
        for quest_id in base_candidate_ids:
            parsed = parse_quest_progression(tables.base_data.get(quest_id), quest_id=quest_id)
            base_progression[quest_id] = parsed
            duplicate_diagnostics.extend(
                _duplicate_diagnostics(PFQUEST_SOURCE_KEY, quest_id, parsed)
            )
            _record_progression(
                connection,
                batch_id=base_batch_id,
                quest_id=quest_id,
                progression=parsed,
                source_key=PFQUEST_SOURCE_KEY,
            )

        for quest_id in turtle_touched_ids:
            effective = parse_quest_progression(
                tables.effective_data.get(quest_id), quest_id=quest_id
            )
            base = base_progression.get(quest_id) or parse_quest_progression(
                tables.base_data.get(quest_id), quest_id=quest_id
            )
            if effective != base:
                changed_effective_ids.append(quest_id)
            duplicate_diagnostics.extend(
                _duplicate_diagnostics(PFQUEST_TURTLE_SOURCE_KEY, quest_id, effective)
            )
            _record_progression(
                connection,
                batch_id=turtle_batch_id,
                quest_id=quest_id,
                progression=effective,
                source_key=PFQUEST_TURTLE_SOURCE_KEY,
            )

        for quest_id in all_candidate_ids:
            result = _materialize_quest(connection, quest_id)
            inserted += result.inserted
            updated += result.updated
            deleted += result.deleted
            protected += result.protected
            unresolved.extend(result.unresolved)

        unresolved_sorted = _sorted_unresolved(unresolved)
        duplicate_diagnostics.sort(
            key=lambda row: (
                str(row["source_key"]),
                int(row["quest_id"]),
                str(row["field"]),
                int(row["duplicate_quest_id"]),
            )
        )
        graph_diagnostics = _dependency_diagnostics(connection)
        warning_count = (
            len(unresolved_sorted)
            + len(duplicate_diagnostics)
            + len(graph_diagnostics["self_prerequisite_ids"])
            + len(graph_diagnostics["prerequisite_cycles"])
            + len(graph_diagnostics["close_self_missing_ids"])
            + len(graph_diagnostics["close_group_mismatch_pairs"])
        )

        details = {
            "identity_base_revision": identity_base_revision,
            "identity_turtle_revision": identity_turtle_revision,
            "base_progression_revision": base_progression_revision,
            "turtle_progression_revision": turtle_progression_revision,
            "base_candidate_quest_count": len(base_candidate_ids),
            "turtle_touched_quest_count": len(turtle_touched_ids),
            "changed_effective_progression_ids": changed_effective_ids,
            "unresolved_progression_relations": unresolved_sorted,
            "duplicate_source_members": duplicate_diagnostics,
            "protected_canonical_rows_retained": protected,
            "canonical_progression_rows_deleted": deleted,
            **graph_diagnostics,
        }
        _finish_batch(
            connection,
            batch_id=base_batch_id,
            rows_read=len(base_candidate_ids),
            rows_inserted=0,
            rows_updated=0,
            warning_count=0,
            details={
                "role": "base-p3-t03-evidence",
                "progression_revision": base_progression_revision,
            },
        )
        _finish_batch(
            connection,
            batch_id=turtle_batch_id,
            rows_read=len(turtle_touched_ids),
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
        source_revision=turtle_progression_revision,
        status="succeeded",
        rows_read=len(base_candidate_ids) + len(turtle_touched_ids),
        rows_accepted=len(base_candidate_ids) + len(turtle_touched_ids),
        rows_skipped=0,
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=warning_count,
        error_count=0,
        details=details,
    )
