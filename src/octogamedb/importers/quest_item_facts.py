"""P3-T05 canonical reconciliation for quest item requirements and rewards.

This importer consumes the bounded, source-shaped snapshots established by P3-T05B. It deliberately
keeps source completeness separate from primitive item/count evidence: direct Octo and OctoDB are
positive/partial evidence, while a structurally complete Tortoise quest_template row may govern
managed fallback membership for the fixed-slot families.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from octogamedb.db.provenance import (
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.quest_source_evidence import (
    CLASSICAPI_REPOSITORY,
    SOURCE_CMANGOS,
    SOURCE_LIVE,
    SOURCE_OCTODB,
    SOURCE_TORTOISE,
    TORTOISE_REPOSITORY,
    compare_source_snapshots,
)
from octogamedb.importers.summary import ImportSummary
from octogamedb.quest_items import (
    FAMILY_FACT_KEYS,
    FAMILY_SET_FACT_KEYS,
    PARTIAL_POSITIVE_SOURCES,
    POLICY_PREFIX,
    is_managed_policy,
    selected_relation_is_active,
)

IMPORTER_VERSION = "quest-item-facts/1"

SET_FAMILIES = (
    "required_item",
    "required_source",
    "source_item_id",
    "reward_item",
    "choice_reward_item",
)
RELATION_FAMILIES = (
    "required_item",
    "required_source",
    "source_item_id",
    "source_item_count",
    "reward_item",
    "choice_reward_item",
)

_EXPECTED_TORTOISE_SLOTS = {
    "required_item": ("required_items", 4),
    "required_source": ("required_sources", 4),
    "reward_item": ("reward_items", 4),
    "choice_reward_item": ("choice_reward_items", 6),
}

_SOURCE_METADATA = {
    SOURCE_LIVE: (
        "Octo live quest query",
        "runtime_capture",
        CLASSICAPI_REPOSITORY,
    ),
    SOURCE_OCTODB: (
        "OctoDB reviewed quest evidence",
        "reviewed_snapshot",
        None,
    ),
    SOURCE_TORTOISE: (
        "Tortoise world SQL",
        "world_sql",
        TORTOISE_REPOSITORY,
    ),
    SOURCE_CMANGOS: (
        "CMaNGOS Vanilla reviewed quest evidence",
        "reviewed_snapshot",
        None,
    ),
}


_CANONICAL_RELATION_TABLES = {
    "required_item": "quest_required_items",
    "required_source": "quest_required_sources",
    "reward_item": "quest_reward_items",
    "choice_reward_item": "quest_choice_reward_items",
}


@dataclass(frozen=True)
class _Selection:
    observation_group_id: int
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
    anomalies: tuple[dict[str, Any], ...] = ()


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _snapshot_revision(snapshot: Mapping[str, Any]) -> str:
    source_key = _required_text(snapshot.get("source_key"), "snapshot source_key")
    if source_key == SOURCE_LIVE:
        semantic = _required_text(
            snapshot.get("semantic_reference_revision"), "live semantic_reference_revision"
        )
        capture_hash = _required_text(snapshot.get("capture_hash"), "live capture_hash")
        return f"{semantic}|capture:{capture_hash}"
    revision = _required_text(snapshot.get("source_revision"), f"{source_key} source_revision")
    if source_key == SOURCE_TORTOISE:
        content_hash = _required_text(snapshot.get("content_hash"), "Tortoise content_hash")
        return f"{revision}|content:{content_hash}"
    return revision


def _snapshot_quests(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    quests = snapshot.get("quests")
    if not isinstance(quests, Mapping):
        raise TypeError("snapshot quests must be an object")
    return quests


def _ensure_source(connection: sqlite3.Connection, source_key: str) -> int:
    try:
        display_name, source_kind, source_url = _SOURCE_METADATA[source_key]
    except KeyError as exc:
        raise ValueError(f"unsupported P3-T05 source: {source_key}") from exc
    connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind, source_url)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            display_name = excluded.display_name,
            source_kind = excluded.source_kind,
            source_url = COALESCE(excluded.source_url, data_sources.source_url),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (source_key, display_name, source_kind, source_url),
    )
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (source_key,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"data source registration failed: {source_key}")
    return int(row["id"])


def _create_batch(
    connection: sqlite3.Connection,
    *,
    source_id: int,
    revision: str,
    rows_read: int,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO import_batches(source_id, source_revision, status, importer_version, rows_read)
        VALUES (?, ?, 'running', ?, ?)
        """,
        (source_id, revision, IMPORTER_VERSION, rows_read),
    )
    return int(cursor.lastrowid)


def _finish_batch(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    rows_read: int,
    details: Mapping[str, Any],
) -> None:
    connection.execute(
        """
        UPDATE import_batches
        SET status = 'succeeded',
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            rows_read = ?, rows_accepted = ?, rows_skipped = 0,
            rows_inserted = 0, rows_updated = 0,
            warning_count = 0, error_count = 0, details_json = ?
        WHERE id = ?
        """,
        (
            rows_read,
            rows_read,
            json.dumps(dict(details), sort_keys=True, separators=(",", ":")),
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


def _group_id_for_observation(connection: sqlite3.Connection, observation_id: int) -> int:
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
        observation_group_id=group_id,
        observation_id=int(row["observation_id"]),
        source_key=str(row["source_key"]),
        selection_policy=None if row["selection_policy"] is None else str(row["selection_policy"]),
        value=json.loads(str(row["value_json"])),
    )


def _selection_for(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    fact_key: str,
    fact_instance_key: str,
) -> _Selection | None:
    row = connection.execute(
        """
        SELECT id FROM observation_groups
        WHERE subject_kind = 'quest' AND subject_key = ?
          AND fact_key = ? AND fact_instance_key = ?
        """,
        (str(quest_id), fact_key, fact_instance_key),
    ).fetchone()
    return None if row is None else _selection_for_group(connection, int(row["id"]))


def _priority_contract(comparison: Mapping[str, Any]) -> Mapping[str, Sequence[str]]:
    contract = comparison.get("priority_contract")
    if not isinstance(contract, Mapping):
        raise TypeError("P3-T05B comparison is missing priority_contract")
    return contract  # type: ignore[return-value]


def _priority_for(
    comparison: Mapping[str, Any], *, family: str, source_key: str
) -> int | None:
    raw = _priority_contract(comparison).get(family)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return None
    ordered = [str(value) for value in raw]
    try:
        index = ordered.index(source_key)
    except ValueError:
        return None
    return len(ordered) - index


def _select_candidate(
    connection: sqlite3.Connection,
    *,
    observation_id: int,
    family: str,
    source_key: str,
    comparison: Mapping[str, Any],
    protected: list[dict[str, Any]],
) -> None:
    group_id = _group_id_for_observation(connection, observation_id)
    current = _selection_for_group(connection, group_id)
    if current is not None and not is_managed_policy(current.selection_policy):
        protected.append(
            {
                "observation_group_id": group_id,
                "family": family,
                "current_source_key": current.source_key,
                "reason": "protected_custom_selection",
            }
        )
        return
    if current is not None:
        desired_priority = _priority_for(comparison, family=family, source_key=source_key)
        current_priority = _priority_for(comparison, family=family, source_key=current.source_key)
        if current_priority is not None and desired_priority is not None:
            if desired_priority < current_priority:
                return
            if desired_priority == current_priority and current.source_key != source_key:
                # Equal-priority disagreement is not silently resolved. Current source contracts
                # presently have unique ranks, but keep this guard explicit.
                return
        if current.observation_id == observation_id:
            return
    select_canonical_observation(
        connection,
        observation_group_id=group_id,
        observation_id=observation_id,
        selection_policy=f"{POLICY_PREFIX}{family}",
        selection_reason=(
            "D-033 selects the highest-priority positive P3-T05 observation without treating "
            "partial-source absence as negative evidence."
        ),
    )


def _clear_managed_selection_for_ambiguity(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    family: str,
    item_id: int,
    protected: list[dict[str, Any]],
) -> int:
    """Clear only a replaceable P3-T05 winner when the best current evidence is ambiguous."""

    instance_key = _relation_instance_key(family, item_id)
    selection = _selection_for(
        connection,
        quest_id=quest_id,
        fact_key=FAMILY_FACT_KEYS[family],
        fact_instance_key=instance_key,
    )
    if selection is None:
        return 0
    if not is_managed_policy(selection.selection_policy):
        protected.append(
            {
                "observation_group_id": selection.observation_group_id,
                "family": family,
                "current_source_key": selection.source_key,
                "reason": "protected_custom_selection_during_ambiguity",
            }
        )
        return 0

    connection.execute(
        "DELETE FROM canonical_selections WHERE observation_group_id = ?",
        (selection.observation_group_id,),
    )
    if family == "source_item_id":
        cursor = connection.execute(
            "DELETE FROM quest_provided_items WHERE quest_id = ?",
            (quest_id,),
        )
        return int(cursor.rowcount)
    table = _CANONICAL_RELATION_TABLES.get(family)
    if table is None:
        # source_item_count is an attribute of quest_provided_items. With its managed selection
        # removed, normal materialization will conservatively set the quantity back to unknown.
        return 0
    cursor = connection.execute(
        f"DELETE FROM {table} WHERE quest_id = ? AND item_id = ?",
        (quest_id, item_id),
    )
    return int(cursor.rowcount)


def _select_complete_set(
    connection: sqlite3.Connection,
    *,
    observation_id: int,
    family: str,
    protected: list[dict[str, Any]],
) -> None:
    group_id = _group_id_for_observation(connection, observation_id)
    current = _selection_for_group(connection, group_id)
    if current is not None and not is_managed_policy(current.selection_policy):
        protected.append(
            {
                "observation_group_id": group_id,
                "family": family,
                "current_source_key": current.source_key,
                "reason": "protected_custom_complete_set",
            }
        )
        return
    if current is not None and current.observation_id == observation_id:
        return
    select_canonical_observation(
        connection,
        observation_group_id=group_id,
        observation_id=observation_id,
        selection_policy=f"{POLICY_PREFIX}complete-set-{family}",
        selection_reason=(
            "The structurally complete Tortoise fixed-slot row governs managed fallback membership; "
            "higher-priority Octo/OctoDB positive observations may still add or override facts."
        ),
    )


def _normalize_slot(slot: Any) -> int | None:
    if slot is None:
        return None
    if isinstance(slot, bool) or not isinstance(slot, int) or slot <= 0:
        raise ValueError(f"invalid source slot: {slot!r}")
    return slot


def _normalize_evidence_item(item: Mapping[str, Any]) -> dict[str, Any]:
    family = _required_text(item.get("fact_family"), "fact_family")
    if family not in RELATION_FAMILIES:
        raise ValueError(f"unsupported P3-T05 fact family: {family}")
    item_id = item.get("item_id")
    if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
        raise ValueError(f"{family} requires a positive item_id")
    value = item.get("value")
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError(f"{family} value must be an integer or null")
    return {
        "fact_family": family,
        "item_id": item_id,
        "value": value,
        "slot": _normalize_slot(item.get("slot")),
    }


def _quest_evidence(quest: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = quest.get("evidence", [])
    if not isinstance(raw, list):
        raise TypeError("quest evidence must be a list")
    return [_normalize_evidence_item(item) for item in raw if isinstance(item, Mapping)]


def _family_set_payload(
    source_key: str,
    quest: Mapping[str, Any],
    family: str,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    family_evidence = [
        {
            "item_id": int(item["item_id"]),
            "value": item.get("value"),
            "slot": item.get("slot"),
        }
        for item in evidence
        if item.get("fact_family") == family
    ]
    family_evidence.sort(
        key=lambda item: (
            -1 if item["slot"] is None else int(item["slot"]),
            int(item["item_id"]),
            -1 if item["value"] is None else int(item["value"]),
        )
    )

    completeness = "partial_positive"
    status = None
    if source_key == SOURCE_TORTOISE:
        if family == "source_item_id":
            source_item = quest.get("source_item")
            complete = isinstance(source_item, Mapping) and source_item.get("id_present") is True
        else:
            source_field, expected_slots = _EXPECTED_TORTOISE_SLOTS[family]
            raw_slots = quest.get(source_field)
            complete = isinstance(raw_slots, list) and len(raw_slots) == expected_slots
        completeness = "complete" if complete else "unknown"
    elif source_key == SOURCE_LIVE:
        status_field = {
            "required_item": "required_items",
            "required_source": "required_sources",
            "source_item_id": "source_item",
            "reward_item": "reward_items",
            "choice_reward_item": "choice_reward_items",
        }[family]
        raw_status = quest.get(status_field)
        if family == "source_item_id" and isinstance(raw_status, Mapping):
            status = raw_status.get("id_status")
        elif isinstance(raw_status, Mapping):
            status = raw_status.get("status")
        completeness = "partial_positive" if status == "observed_positive" else "unknown"
    elif source_key in {SOURCE_OCTODB, SOURCE_CMANGOS}:
        completeness = "partial_positive" if family_evidence else "unknown"

    return {
        "completeness": completeness,
        "source_status": status,
        "members": family_evidence,
    }


def _relation_instance_key(family: str, item_id: int) -> str:
    return "provided" if family == "source_item_id" else str(item_id)


def _relation_attributes(family: str, value: Any) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    if family == "required_source":
        attributes["raw_source_count"] = value
    elif family != "source_item_id":
        attributes["quantity"] = value
    return attributes


def _record_source_quest(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    source_key: str,
    quest_id: int,
    quest: Mapping[str, Any],
    protected: list[dict[str, Any]],
) -> dict[tuple[str, int, Any, int | None], int]:
    evidence = _quest_evidence(quest)
    primitive_ids: dict[tuple[str, int, Any, int | None], int] = {}

    for family in SET_FAMILIES:
        payload = _family_set_payload(source_key, quest, family, evidence)
        observation_id = record_scalar_observation(
            connection,
            subject_kind="quest",
            subject_key=quest_id,
            fact_key=FAMILY_SET_FACT_KEYS[family],
            import_batch_id=batch_id,
            value=payload,
            source_record_type="quest_item_family_set",
            raw_identifier=f"{quest_id}:{family}:set",
        )
        if source_key == SOURCE_TORTOISE and payload["completeness"] == "complete":
            _select_complete_set(
                connection,
                observation_id=observation_id,
                family=family,
                protected=protected,
            )

    ordered_evidence = sorted(
        evidence,
        key=lambda item: (
            RELATION_FAMILIES.index(str(item["fact_family"])),
            int(item["item_id"]),
            -1 if item.get("slot") is None else int(item["slot"]),
            -1 if item.get("value") is None else int(item["value"]),
        ),
    )
    for item in ordered_evidence:
        family = str(item["fact_family"])
        item_id = int(item["item_id"])
        value = item.get("value")
        slot = item.get("slot")
        normalized_slot = int(slot) if isinstance(slot, int) else None
        raw_slot = "noslot" if normalized_slot is None else f"slot:{normalized_slot}"
        observation_id = record_relation_observation(
            connection,
            subject_kind="quest",
            subject_key=quest_id,
            fact_key=FAMILY_FACT_KEYS[family],
            import_batch_id=batch_id,
            target_kind="item",
            target_key=item_id,
            relation_instance_key=_relation_instance_key(family, item_id),
            attributes=_relation_attributes(family, value),
            source_record_type=f"quest_{family}",
            raw_identifier=f"{quest_id}:{family}:{item_id}:{raw_slot}",
        )
        primitive_ids[(family, item_id, value, normalized_slot)] = observation_id
    return primitive_ids


def _selected_target(selection: _Selection | None) -> tuple[int, dict[str, Any]] | None:
    if selection is None or not isinstance(selection.value, dict):
        return None
    target = selection.value.get("target")
    attributes = selection.value.get("attributes", {})
    if not isinstance(target, dict) or not isinstance(attributes, dict):
        return None
    if target.get("kind") != "item":
        return None
    key = target.get("key")
    if not isinstance(key, str) or not key.isdigit() or int(key) <= 0:
        return None
    return int(key), attributes


def _selected_complete_ids(
    connection: sqlite3.Connection, *, quest_id: int, family: str
) -> set[int] | None:
    selection = _selection_for(
        connection,
        quest_id=quest_id,
        fact_key=FAMILY_SET_FACT_KEYS[family],
        fact_instance_key="",
    )
    if selection is None or not isinstance(selection.value, dict):
        return None
    if selection.value.get("completeness") != "complete":
        return None
    members = selection.value.get("members")
    if not isinstance(members, list):
        return set()
    result: set[int] = set()
    for member in members:
        if not isinstance(member, dict):
            continue
        item_id = member.get("item_id")
        if isinstance(item_id, int) and not isinstance(item_id, bool) and item_id > 0:
            result.add(item_id)
    return result


def _selected_relation_rows(
    connection: sqlite3.Connection, *, quest_id: int, family: str
) -> list[_Selection]:
    rows = connection.execute(
        """
        SELECT og.id
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        WHERE og.subject_kind = 'quest' AND og.subject_key = ? AND og.fact_key = ?
        ORDER BY og.fact_instance_key
        """,
        (str(quest_id), FAMILY_FACT_KEYS[family]),
    ).fetchall()
    return [
        selection
        for row in rows
        if (selection := _selection_for_group(connection, int(row["id"]))) is not None
    ]


def _identity_exists(connection: sqlite3.Connection, *, table: str, column: str, value: int) -> bool:
    return connection.execute(
        f"SELECT 1 FROM {table} WHERE {column} = ?", (value,)
    ).fetchone() is not None


def _value_is_valid(family: str, value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    if family == "required_source":
        return value >= 0
    return value > 0


def _desired_relation_map(
    connection: sqlite3.Connection, *, quest_id: int, family: str
) -> tuple[dict[int, tuple[Any, _Selection]], set[int] | None, list[dict[str, Any]]]:
    complete_ids = _selected_complete_ids(connection, quest_id=quest_id, family=family)
    desired: dict[int, tuple[Any, _Selection]] = {}
    anomalies: list[dict[str, Any]] = []
    for selection in _selected_relation_rows(connection, quest_id=quest_id, family=family):
        parsed = _selected_target(selection)
        if parsed is None:
            anomalies.append(
                {"quest_id": quest_id, "family": family, "reason": "invalid_selected_relation_shape"}
            )
            continue
        item_id, attributes = parsed
        public_selection = {
            "selection_policy": selection.selection_policy,
            "source_key": selection.source_key,
        }
        if not selected_relation_is_active(
            public_selection, item_id=item_id, complete_member_ids=complete_ids
        ):
            continue
        value_key = "raw_source_count" if family == "required_source" else "quantity"
        value = attributes.get(value_key)
        if not _value_is_valid(family, value):
            anomalies.append(
                {
                    "quest_id": quest_id,
                    "family": family,
                    "item_id": item_id,
                    "value": value,
                    "source_key": selection.source_key,
                    "reason": "nonzero_item_with_invalid_count",
                }
            )
            continue
        desired[item_id] = (value, selection)
    return desired, complete_ids, anomalies


def _sync_relation_table(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    family: str,
    table: str,
    value_column: str,
) -> _MaterializeResult:
    desired, complete_ids, anomalies = _desired_relation_map(
        connection, quest_id=quest_id, family=family
    )
    rows = connection.execute(
        f"SELECT item_id, {value_column} FROM {table} WHERE quest_id = ?", (quest_id,)
    ).fetchall()
    current = {int(row["item_id"]): row[value_column] for row in rows}
    inserted = updated = deleted = protected = 0
    unresolved: list[dict[str, Any]] = []

    for item_id in sorted(set(current) - set(desired)):
        selection = _selection_for(
            connection,
            quest_id=quest_id,
            fact_key=FAMILY_FACT_KEYS[family],
            fact_instance_key=str(item_id),
        )
        if selection is not None and not is_managed_policy(selection.selection_policy):
            protected += 1
            continue
        # Without a complete set, absence from currently materializable selected facts can mean a
        # partial source simply did not observe the member this run. Only delete on explicit invalid
        # selected evidence or when a complete fallback set safely governs managed membership.
        parsed = _selected_target(selection)
        explicit_invalid = False
        if parsed is not None:
            value_key = "raw_source_count" if family == "required_source" else "quantity"
            explicit_invalid = not _value_is_valid(family, parsed[1].get(value_key))
        if complete_ids is None and not explicit_invalid:
            continue
        if selection is not None and selection.source_key in PARTIAL_POSITIVE_SOURCES and not explicit_invalid:
            continue
        connection.execute(
            f"DELETE FROM {table} WHERE quest_id = ? AND item_id = ?", (quest_id, item_id)
        )
        deleted += 1

    for item_id, (value, selection) in sorted(desired.items()):
        if not _identity_exists(connection, table="items", column="item_id", value=item_id):
            unresolved.append(
                {
                    "quest_id": quest_id,
                    "family": family,
                    "item_id": item_id,
                    "source_key": selection.source_key,
                    "reason": "missing_item_identity",
                }
            )
            continue
        if item_id not in current:
            connection.execute(
                f"INSERT INTO {table}(quest_id, item_id, {value_column}) VALUES (?, ?, ?)",
                (quest_id, item_id, value),
            )
            inserted += 1
        elif current[item_id] != value:
            connection.execute(
                f"UPDATE {table} SET {value_column} = ? WHERE quest_id = ? AND item_id = ?",
                (value, quest_id, item_id),
            )
            updated += 1
    return _MaterializeResult(
        inserted, updated, deleted, protected, tuple(unresolved), tuple(anomalies)
    )


def _sync_provided_item(connection: sqlite3.Connection, *, quest_id: int) -> _MaterializeResult:
    complete_ids = _selected_complete_ids(connection, quest_id=quest_id, family="source_item_id")
    selection = _selection_for(
        connection,
        quest_id=quest_id,
        fact_key=FAMILY_FACT_KEYS["source_item_id"],
        fact_instance_key="provided",
    )
    parsed = _selected_target(selection)
    desired_item_id: int | None = None
    desired_quantity: int | None = None
    anomalies: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    active = False
    if selection is not None and parsed is not None:
        item_id, _ = parsed
        active = selected_relation_is_active(
            {"selection_policy": selection.selection_policy, "source_key": selection.source_key},
            item_id=item_id,
            complete_member_ids=complete_ids,
        )
        if active:
            desired_item_id = item_id
            count_selection = _selection_for(
                connection,
                quest_id=quest_id,
                fact_key=FAMILY_FACT_KEYS["source_item_count"],
                fact_instance_key=str(item_id),
            )
            count_parsed = _selected_target(count_selection)
            if count_parsed is not None and count_parsed[0] == item_id:
                count = count_parsed[1].get("quantity")
                if _value_is_valid("source_item_count", count):
                    desired_quantity = int(count)
                else:
                    anomalies.append(
                        {
                            "quest_id": quest_id,
                            "family": "source_item_count",
                            "item_id": item_id,
                            "value": count,
                            "source_key": count_selection.source_key if count_selection else None,
                            "reason": "invalid_provided_item_count",
                        }
                    )
    elif selection is not None:
        anomalies.append(
            {
                "quest_id": quest_id,
                "family": "source_item_id",
                "reason": "invalid_selected_relation_shape",
            }
        )

    row = connection.execute(
        "SELECT item_id, quantity FROM quest_provided_items WHERE quest_id = ?", (quest_id,)
    ).fetchone()
    inserted = updated = deleted = protected = 0
    if desired_item_id is None:
        if row is not None:
            if selection is not None and not is_managed_policy(selection.selection_policy):
                protected += 1
            elif complete_ids is not None or (selection is not None and not active):
                connection.execute("DELETE FROM quest_provided_items WHERE quest_id = ?", (quest_id,))
                deleted += 1
        return _MaterializeResult(
            inserted, updated, deleted, protected, tuple(unresolved), tuple(anomalies)
        )

    if not _identity_exists(connection, table="items", column="item_id", value=desired_item_id):
        unresolved.append(
            {
                "quest_id": quest_id,
                "family": "source_item_id",
                "item_id": desired_item_id,
                "source_key": selection.source_key if selection else None,
                "reason": "missing_item_identity",
            }
        )
        if row is not None and selection is not None and is_managed_policy(selection.selection_policy):
            connection.execute("DELETE FROM quest_provided_items WHERE quest_id = ?", (quest_id,))
            deleted += 1
        return _MaterializeResult(
            inserted, updated, deleted, protected, tuple(unresolved), tuple(anomalies)
        )

    desired = (desired_item_id, desired_quantity)
    if row is None:
        connection.execute(
            "INSERT INTO quest_provided_items(quest_id, item_id, quantity) VALUES (?, ?, ?)",
            (quest_id, *desired),
        )
        inserted += 1
    elif (int(row["item_id"]), row["quantity"]) != desired:
        connection.execute(
            "UPDATE quest_provided_items SET item_id = ?, quantity = ? WHERE quest_id = ?",
            (desired_item_id, desired_quantity, quest_id),
        )
        updated += 1
    return _MaterializeResult(
        inserted, updated, deleted, protected, tuple(unresolved), tuple(anomalies)
    )


def _sync_choice_parent(
    connection: sqlite3.Connection, quest_id: int, *, selected_member_count: int
) -> _MaterializeResult:
    row = connection.execute(
        "SELECT selected_member_count FROM quest_choice_reward_sets WHERE quest_id = ?",
        (quest_id,),
    ).fetchone()
    if selected_member_count == 0:
        if row is not None:
            connection.execute(
                "DELETE FROM quest_choice_reward_sets WHERE quest_id = ?", (quest_id,)
            )
            return _MaterializeResult(deleted=1)
        return _MaterializeResult()
    if row is None:
        connection.execute(
            "INSERT INTO quest_choice_reward_sets(quest_id, choice_semantics, selected_member_count) "
            "VALUES (?, 'choose_one', ?)",
            (quest_id, selected_member_count),
        )
        return _MaterializeResult(inserted=1)
    if int(row["selected_member_count"]) != selected_member_count:
        connection.execute(
            "UPDATE quest_choice_reward_sets SET selected_member_count = ? WHERE quest_id = ?",
            (selected_member_count, quest_id),
        )
        return _MaterializeResult(updated=1)
    return _MaterializeResult()


def _combine_results(results: Sequence[_MaterializeResult]) -> _MaterializeResult:
    return _MaterializeResult(
        inserted=sum(result.inserted for result in results),
        updated=sum(result.updated for result in results),
        deleted=sum(result.deleted for result in results),
        protected=sum(result.protected for result in results),
        unresolved=tuple(item for result in results for item in result.unresolved),
        anomalies=tuple(item for result in results for item in result.anomalies),
    )


def _sync_choice_relation(connection: sqlite3.Connection, quest_id: int) -> _MaterializeResult:
    desired, complete_ids, anomalies = _desired_relation_map(
        connection, quest_id=quest_id, family="choice_reward_item"
    )
    valid_desired_ids = [
        item_id
        for item_id in sorted(desired)
        if _identity_exists(connection, table="items", column="item_id", value=item_id)
    ]
    parent = connection.execute(
        "SELECT selected_member_count FROM quest_choice_reward_sets WHERE quest_id = ?", (quest_id,)
    ).fetchone()
    inserted = updated = deleted = protected = 0
    unresolved = [
        {
            "quest_id": quest_id,
            "family": "choice_reward_item",
            "item_id": item_id,
            "source_key": desired[item_id][1].source_key,
            "reason": "missing_item_identity",
        }
        for item_id in sorted(desired)
        if item_id not in valid_desired_ids
    ]
    if desired and parent is None:
        connection.execute(
            "INSERT INTO quest_choice_reward_sets(quest_id, choice_semantics, selected_member_count) "
            "VALUES (?, 'choose_one', 0)",
            (quest_id,),
        )
        inserted += 1

    rows = connection.execute(
        "SELECT item_id, quantity FROM quest_choice_reward_items WHERE quest_id = ?", (quest_id,)
    ).fetchall()
    current = {int(row["item_id"]): int(row["quantity"]) for row in rows}
    for item_id in sorted(set(current) - set(desired)):
        selection = _selection_for(
            connection,
            quest_id=quest_id,
            fact_key=FAMILY_FACT_KEYS["choice_reward_item"],
            fact_instance_key=str(item_id),
        )
        if selection is not None and not is_managed_policy(selection.selection_policy):
            protected += 1
            continue
        parsed = _selected_target(selection)
        explicit_invalid = parsed is not None and not _value_is_valid(
            "choice_reward_item", parsed[1].get("quantity")
        )
        if complete_ids is None and not explicit_invalid:
            continue
        if selection is not None and selection.source_key in PARTIAL_POSITIVE_SOURCES and not explicit_invalid:
            continue
        connection.execute(
            "DELETE FROM quest_choice_reward_items WHERE quest_id = ? AND item_id = ?",
            (quest_id, item_id),
        )
        deleted += 1

    for item_id in valid_desired_ids:
        quantity = int(desired[item_id][0])
        if item_id not in current:
            connection.execute(
                "INSERT INTO quest_choice_reward_items(quest_id, item_id, quantity) VALUES (?, ?, ?)",
                (quest_id, item_id, quantity),
            )
            inserted += 1
        elif current[item_id] != quantity:
            connection.execute(
                "UPDATE quest_choice_reward_items SET quantity = ? WHERE quest_id = ? AND item_id = ?",
                (quantity, quest_id, item_id),
            )
            updated += 1

    parent_result = _sync_choice_parent(
        connection, quest_id, selected_member_count=len(desired)
    )
    return _combine_results(
        [
            _MaterializeResult(
                inserted, updated, deleted, protected, tuple(unresolved), tuple(anomalies)
            ),
            parent_result,
        ]
    )


def _materialize_quest_fixed(connection: sqlite3.Connection, quest_id: int) -> _MaterializeResult:
    if not _identity_exists(connection, table="quests", column="quest_id", value=quest_id):
        return _MaterializeResult(
            unresolved=(
                {"quest_id": quest_id, "family": "quest", "reason": "missing_quest_identity"},
            )
        )
    return _combine_results(
        [
            _sync_relation_table(
                connection,
                quest_id=quest_id,
                family="required_item",
                table="quest_required_items",
                value_column="quantity",
            ),
            _sync_relation_table(
                connection,
                quest_id=quest_id,
                family="required_source",
                table="quest_required_sources",
                value_column="raw_source_count",
            ),
            _sync_provided_item(connection, quest_id=quest_id),
            _sync_relation_table(
                connection,
                quest_id=quest_id,
                family="reward_item",
                table="quest_reward_items",
                value_column="quantity",
            ),
            _sync_choice_relation(connection, quest_id),
        ]
    )


def _canonical_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "required_item": int(connection.execute("SELECT COUNT(*) FROM quest_required_items").fetchone()[0]),
        "required_source": int(
            connection.execute("SELECT COUNT(*) FROM quest_required_sources").fetchone()[0]
        ),
        "provided_item": int(
            connection.execute("SELECT COUNT(*) FROM quest_provided_items").fetchone()[0]
        ),
        "reward_item": int(connection.execute("SELECT COUNT(*) FROM quest_reward_items").fetchone()[0]),
        "choice_reward_item": int(
            connection.execute("SELECT COUNT(*) FROM quest_choice_reward_items").fetchone()[0]
        ),
    }


def _sort_diagnostics(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))


def reconcile_quest_item_facts(
    connection: sqlite3.Connection,
    *,
    snapshots: Sequence[Mapping[str, Any]],
) -> ImportSummary:
    """Record P3-T05 source evidence, apply D-033 selection, and materialize resolved facts."""

    if not snapshots:
        raise ValueError("P3-T05 requires at least one source snapshot")
    source_keys = [_required_text(snapshot.get("source_key"), "snapshot source_key") for snapshot in snapshots]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("P3-T05 accepts at most one snapshot per source_key per reconciliation run")
    unsupported = sorted(set(source_keys) - set(_SOURCE_METADATA))
    if unsupported:
        raise ValueError(f"unsupported P3-T05 source(s): {', '.join(unsupported)}")

    comparison = compare_source_snapshots(snapshots)
    batch_ids: dict[str, int] = {}
    revisions: dict[str, str] = {}
    protected: list[dict[str, Any]] = []
    recorded_ids: dict[tuple[int, str, int, Any, int | None, str], int] = {}
    observed_quest_ids: set[int] = set()

    try:
        for snapshot in snapshots:
            source_key = str(snapshot["source_key"])
            quests = _snapshot_quests(snapshot)
            revision = _snapshot_revision(snapshot)
            revisions[source_key] = revision
            source_id = _ensure_source(connection, source_key)
            batch_ids[source_key] = _create_batch(
                connection,
                source_id=source_id,
                revision=revision,
                rows_read=len(quests),
            )
            for raw_quest_id in quests:
                observed_quest_ids.add(int(raw_quest_id))

        for snapshot in snapshots:
            source_key = str(snapshot["source_key"])
            quests = _snapshot_quests(snapshot)
            for raw_quest_id in sorted(quests, key=lambda value: int(value)):
                quest_id = int(raw_quest_id)
                quest = quests[raw_quest_id]
                if not isinstance(quest, Mapping):
                    raise TypeError(f"quest {quest_id} in {source_key} must be an object")
                ids = _record_source_quest(
                    connection,
                    batch_id=batch_ids[source_key],
                    source_key=source_key,
                    quest_id=quest_id,
                    quest=quest,
                    protected=protected,
                )
                for (family, item_id, value, slot), observation_id in ids.items():
                    recorded_ids[(quest_id, family, item_id, value, slot, source_key)] = observation_id

        ambiguous: list[dict[str, Any]] = []
        ambiguity_deleted = 0
        compared_quests = comparison.get("quests")
        if not isinstance(compared_quests, Mapping):
            raise TypeError("P3-T05B comparison quests must be an object")
        for raw_quest_id in sorted(compared_quests, key=lambda value: int(value)):
            quest_id = int(raw_quest_id)
            compared = compared_quests[raw_quest_id]
            if not isinstance(compared, Mapping):
                continue
            facts = compared.get("facts", {})
            if not isinstance(facts, Mapping):
                continue
            for fact_key in sorted(facts):
                fact = facts[fact_key]
                if not isinstance(fact, Mapping):
                    continue
                family = str(fact.get("fact_family", ""))
                if family not in RELATION_FAMILIES:
                    continue
                if fact.get("selection_status") != "selected":
                    evidence_rows = fact.get("evidence", [])
                    ambiguous_item_ids = sorted(
                        {
                            int(evidence["item_id"])
                            for evidence in evidence_rows
                            if isinstance(evidence, Mapping)
                            and isinstance(evidence.get("item_id"), int)
                            and not isinstance(evidence.get("item_id"), bool)
                            and int(evidence["item_id"]) > 0
                        }
                    ) if isinstance(evidence_rows, list) else []
                    for ambiguous_item_id in ambiguous_item_ids:
                        ambiguity_deleted += _clear_managed_selection_for_ambiguity(
                            connection,
                            quest_id=quest_id,
                            family=family,
                            item_id=ambiguous_item_id,
                            protected=protected,
                        )
                    ambiguous.append(
                        {
                            "quest_id": quest_id,
                            "fact_key": str(fact_key),
                            "family": family,
                            "item_ids": ambiguous_item_ids,
                            "reason": "ambiguous_same_priority",
                        }
                    )
                    continue
                selected = fact.get("selected")
                if not isinstance(selected, Mapping):
                    continue
                source_key = str(selected.get("source_key", ""))
                value = selected.get("value")
                evidence_rows = fact.get("evidence", [])
                selected_item_id = None
                selected_slot: int | None = None
                if isinstance(evidence_rows, list):
                    for evidence in evidence_rows:
                        if not isinstance(evidence, Mapping):
                            continue
                        if str(evidence.get("source_key")) != source_key:
                            continue
                        if evidence.get("value") != value:
                            continue
                        raw_item_id = evidence.get("item_id")
                        if isinstance(raw_item_id, int) and not isinstance(raw_item_id, bool):
                            selected_item_id = raw_item_id
                            raw_slot = evidence.get("slot")
                            selected_slot = (
                                int(raw_slot)
                                if isinstance(raw_slot, int) and not isinstance(raw_slot, bool)
                                else None
                            )
                            break
                if selected_item_id is None:
                    raise ValueError(
                        f"comparison selected {quest_id}:{fact_key} without matching item evidence"
                    )
                observation_id = recorded_ids.get(
                    (quest_id, family, selected_item_id, value, selected_slot, source_key)
                )
                if observation_id is None:
                    raise ValueError(
                        f"missing recorded observation for selected {quest_id}:{fact_key}:{source_key}"
                    )
                _select_candidate(
                    connection,
                    observation_id=observation_id,
                    family=family,
                    source_key=source_key,
                    comparison=comparison,
                    protected=protected,
                )

        inserted = updated = materialize_protected = 0
        deleted = ambiguity_deleted
        unresolved: list[dict[str, Any]] = []
        anomalies: list[dict[str, Any]] = []
        # Include quests with pre-existing managed P3-T05 facts so a new complete Tortoise set can
        # remove stale fallback materialization even when a row disappeared from that source family.
        existing_subjects = {
            int(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT CAST(og.subject_key AS INTEGER)
                FROM observation_groups AS og
                WHERE og.subject_kind = 'quest' AND (
                    og.fact_key LIKE 'quest_required_%'
                    OR og.fact_key LIKE 'quest_provided_%'
                    OR og.fact_key LIKE 'quest_reward_%'
                    OR og.fact_key LIKE 'quest_choice_reward_%'
                )
                """
            ).fetchall()
        }
        for quest_id in sorted(observed_quest_ids | existing_subjects):
            result = _materialize_quest_fixed(connection, quest_id)
            inserted += result.inserted
            updated += result.updated
            deleted += result.deleted
            materialize_protected += result.protected
            unresolved.extend(result.unresolved)
            anomalies.extend(result.anomalies)

        unresolved_sorted = _sort_diagnostics(unresolved)
        anomalies_sorted = _sort_diagnostics(anomalies)
        protected_sorted = _sort_diagnostics(protected)
        ambiguous_sorted = _sort_diagnostics(ambiguous)
        conflicts = [
            {
                "quest_id": int(raw_quest_id),
                "fact_key": str(fact_key),
                "family": str(fact.get("fact_family")),
            }
            for raw_quest_id, quest in compared_quests.items()
            if isinstance(quest, Mapping)
            for fact_key, fact in (quest.get("facts", {}) or {}).items()
            if isinstance(fact, Mapping) and fact.get("conflict") is True
        ]
        conflicts = _sort_diagnostics(conflicts)
        details = {
            "source_revisions": dict(sorted(revisions.items())),
            "comparison_hash": comparison.get("comparison_hash"),
            "priority_contract": comparison.get("priority_contract"),
            "canonical_counts": _canonical_counts(connection),
            "canonical_rows_deleted": deleted,
            "protected_selection_events": protected_sorted,
            "protected_canonical_rows_retained": materialize_protected,
            "unresolved_item_or_quest_targets": unresolved_sorted,
            "anomalies": anomalies_sorted,
            "ambiguous_same_priority": ambiguous_sorted,
            "cross_source_conflicts": conflicts,
        }
        for snapshot in snapshots:
            source_key = str(snapshot["source_key"])
            _finish_batch(
                connection,
                batch_id=batch_ids[source_key],
                rows_read=len(_snapshot_quests(snapshot)),
                details={
                    "role": "p3-t05-source-evidence",
                    "source_key": source_key,
                    "comparison_hash": comparison.get("comparison_hash"),
                },
            )
    except Exception as exc:
        for batch_id in batch_ids.values():
            _fail_batch(connection, batch_id, exc)
        raise

    warning_count = (
        len(unresolved_sorted)
        + len(anomalies_sorted)
        + len(ambiguous_sorted)
        + len(protected_sorted)
        + materialize_protected
    )
    return ImportSummary(
        source_key="p3-t05-d033",
        source_revision=str(comparison.get("comparison_hash") or ""),
        status="succeeded",
        rows_read=sum(len(_snapshot_quests(snapshot)) for snapshot in snapshots),
        rows_accepted=sum(len(_snapshot_quests(snapshot)) for snapshot in snapshots),
        rows_skipped=0,
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=warning_count,
        error_count=0,
        details=details,
    )
