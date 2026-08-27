"""Read-only selected-vs-source comparison audits for bounded P1 world evidence."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

P1_WORLD_COMPARISON_SCOPE = "p1-world-selected-vs-comparison-source"
P1_WORLD_COMPARISON_SOURCE_KEY = "pfquest-octo"
P1_WORLD_SUBJECT_KINDS = (
    "creature",
    "creature_spawn",
    "gameobject",
    "gameobject_spawn",
)
P1_WORLD_FACTS: dict[str, frozenset[str]] = {
    "creature": frozenset(
        {"name", "faction", "level_min", "level_max", "world_presence", "spawn_set"}
    ),
    "creature_spawn": frozenset({"position", "respawn_seconds"}),
    "gameobject": frozenset({"name", "faction", "world_presence", "spawn_set"}),
    "gameobject_spawn": frozenset({"position", "respawn_seconds"}),
}
COMPARISON_STATES = (
    "comparison_only",
    "active_only",
    "same_value",
    "different_value",
    "not_directly_comparable",
)

_GroupKey = tuple[str, str, str, str]


def _json_value(value_json: str) -> Any:
    return json.loads(value_json)


def _batched(values: Iterable[str], size: int = 400) -> Iterable[list[str]]:
    batch: list[str] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _resolve_source_revision(
    connection: sqlite3.Connection,
    *,
    source_key: str,
    source_revision: str | None,
) -> tuple[int, str, list[dict[str, Any]]]:
    source = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?",
        (source_key,),
    ).fetchone()
    if source is None:
        raise ValueError(f"unknown comparison source: {source_key}")
    source_id = int(source["id"])

    if source_revision is None:
        row = connection.execute(
            """
            SELECT source_revision
            FROM import_batches
            WHERE source_id = ? AND status = 'succeeded'
            ORDER BY id DESC
            LIMIT 1
            """,
            (source_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"comparison source has no succeeded import batch: {source_key}")
        revision = "" if row["source_revision"] is None else str(row["source_revision"])
    else:
        revision = source_revision.strip()
        if not revision:
            raise ValueError("source_revision must not be blank")
        row = connection.execute(
            """
            SELECT 1
            FROM import_batches
            WHERE source_id = ?
              AND COALESCE(source_revision, '') = ?
              AND status = 'succeeded'
            LIMIT 1
            """,
            (source_id, revision),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"comparison source revision has no succeeded import batch: {source_key}@{revision}"
            )

    batch_rows = connection.execute(
        """
        SELECT
            id,
            status,
            importer_version,
            rows_read,
            rows_accepted,
            rows_skipped,
            rows_inserted,
            rows_updated,
            warning_count,
            error_count
        FROM import_batches
        WHERE source_id = ? AND COALESCE(source_revision, '') = ?
        ORDER BY id
        """,
        (source_id, revision),
    ).fetchall()
    batches = [
        {
            "batch_id": int(row["id"]),
            "status": str(row["status"]),
            "importer_version": row["importer_version"],
            "rows_read": int(row["rows_read"]),
            "rows_accepted": int(row["rows_accepted"]),
            "rows_skipped": int(row["rows_skipped"]),
            "rows_inserted": int(row["rows_inserted"]),
            "rows_updated": int(row["rows_updated"]),
            "warning_count": int(row["warning_count"]),
            "error_count": int(row["error_count"]),
        }
        for row in batch_rows
    ]
    return source_id, revision, batches


def _source_groups(
    connection: sqlite3.Connection,
    *,
    source_id: int,
    revision: str,
) -> tuple[dict[_GroupKey, dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    placeholders = ",".join("?" for _ in P1_WORLD_SUBJECT_KINDS)
    rows = connection.execute(
        f"""
        SELECT
            og.id AS group_id,
            og.subject_kind,
            og.subject_key,
            og.fact_key,
            og.fact_kind,
            og.fact_instance_key,
            so.id AS observation_id,
            so.source_record_type,
            so.raw_identifier,
            so.value_json,
            so.confidence,
            so.authority_tier,
            cs.observation_id AS selected_observation_id,
            cs.selection_policy,
            cs.selection_reason,
            selected_source.source_key AS selected_source_key,
            selected_observation.source_revision AS selected_source_revision,
            selected_observation.value_json AS selected_value_json
        FROM source_observations AS so
        JOIN observation_groups AS og ON og.id = so.observation_group_id
        LEFT JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        LEFT JOIN source_observations AS selected_observation
            ON selected_observation.id = cs.observation_id
        LEFT JOIN data_sources AS selected_source
            ON selected_source.id = selected_observation.source_id
        WHERE so.source_id = ?
          AND so.source_revision = ?
          AND og.subject_kind IN ({placeholders})
        ORDER BY
            og.subject_kind, og.subject_key, og.fact_key, og.fact_instance_key, og.id, so.id
        """,
        (source_id, revision, *P1_WORLD_SUBJECT_KINDS),
    ).fetchall()

    groups: dict[_GroupKey, dict[str, Any]] = {}
    observation_ids: list[int] = []
    for row in rows:
        kind = str(row["subject_kind"])
        fact_key = str(row["fact_key"])
        if fact_key not in P1_WORLD_FACTS[kind]:
            continue
        key: _GroupKey = (
            kind,
            str(row["subject_key"]),
            fact_key,
            str(row["fact_instance_key"]),
        )
        group = groups.setdefault(
            key,
            {
                "group_id": int(row["group_id"]),
                "subject_kind": kind,
                "subject_key": str(row["subject_key"]),
                "fact_key": fact_key,
                "fact_kind": str(row["fact_kind"]),
                "fact_instance_key": str(row["fact_instance_key"]),
                "comparison_observations": [],
                "active": None,
            },
        )
        observation_id = int(row["observation_id"])
        observation_ids.append(observation_id)
        group["comparison_observations"].append(
            {
                "observation_id": observation_id,
                "value_json": str(row["value_json"]),
                "value": _json_value(str(row["value_json"])),
                "source_record_type": row["source_record_type"],
                "raw_identifier": row["raw_identifier"],
                "confidence": row["confidence"],
                "authority_tier": row["authority_tier"],
            }
        )
        if row["selected_observation_id"] is not None:
            group["active"] = {
                "observation_id": int(row["selected_observation_id"]),
                "source_key": str(row["selected_source_key"]),
                "source_revision": str(row["selected_source_revision"]),
                "selection_policy": row["selection_policy"],
                "selection_reason": str(row["selection_reason"]),
                "value_json": str(row["selected_value_json"]),
                "value": _json_value(str(row["selected_value_json"])),
            }

    batch_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for batch in _batched([str(item) for item in sorted(set(observation_ids))]):
        placeholders = ",".join("?" for _ in batch)
        batch_rows = connection.execute(
            f"""
            SELECT oib.observation_id, ib.id, ib.status
            FROM observation_import_batches AS oib
            JOIN import_batches AS ib ON ib.id = oib.import_batch_id
            WHERE oib.observation_id IN ({placeholders})
            ORDER BY oib.observation_id, ib.id
            """,
            tuple(int(item) for item in batch),
        ).fetchall()
        for row in batch_rows:
            batch_map[int(row["observation_id"])].append(
                {"batch_id": int(row["id"]), "status": str(row["status"])}
            )
    return groups, batch_map


def _selected_groups_for_subjects(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_keys: set[str],
) -> dict[_GroupKey, dict[str, Any]]:
    if not subject_keys:
        return {}
    selected: dict[_GroupKey, dict[str, Any]] = {}
    for keys in _batched(sorted(subject_keys)):
        placeholders = ",".join("?" for _ in keys)
        rows = connection.execute(
            f"""
            SELECT
                og.id AS group_id,
                og.subject_kind,
                og.subject_key,
                og.fact_key,
                og.fact_kind,
                og.fact_instance_key,
                cs.observation_id,
                cs.selection_policy,
                cs.selection_reason,
                ds.source_key,
                so.source_revision,
                so.value_json
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            JOIN source_observations AS so ON so.id = cs.observation_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = ?
              AND og.subject_key IN ({placeholders})
            ORDER BY og.subject_key, og.fact_key, og.fact_instance_key, og.id
            """,
            (subject_kind, *keys),
        ).fetchall()
        for row in rows:
            fact_key = str(row["fact_key"])
            if fact_key not in P1_WORLD_FACTS[subject_kind]:
                continue
            key: _GroupKey = (
                subject_kind,
                str(row["subject_key"]),
                fact_key,
                str(row["fact_instance_key"]),
            )
            selected[key] = {
                "group_id": int(row["group_id"]),
                "observation_id": int(row["observation_id"]),
                "source_key": str(row["source_key"]),
                "source_revision": str(row["source_revision"]),
                "selection_policy": row["selection_policy"],
                "selection_reason": str(row["selection_reason"]),
                "value_json": str(row["value_json"]),
                "value": _json_value(str(row["value_json"])),
            }
    return selected


def _spawn_parent(subject_kind: str, subject_key: str) -> tuple[str, str] | None:
    if subject_kind == "creature_spawn":
        prefix = "creature:"
        parent_kind = "creature"
    elif subject_kind == "gameobject_spawn":
        prefix = "gameobject:"
        parent_kind = "gameobject"
    else:
        return None
    if not subject_key.startswith(prefix):
        return None
    remainder = subject_key[len(prefix) :]
    parent_key, separator, _tail = remainder.partition(":")
    if not separator or not parent_key:
        return None
    return parent_kind, parent_key


def _spawn_keys(value: Any) -> set[str] | None:
    if not isinstance(value, list):
        return None
    keys: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        spawn_key = item.get("spawn_key")
        if not isinstance(spawn_key, str) or not spawn_key:
            return None
        keys.add(spawn_key)
    return keys


def _unique_comparison_value(group: dict[str, Any] | None) -> tuple[str | None, Any | None]:
    if group is None:
        return None, None
    values = {str(item["value_json"]): item["value"] for item in group["comparison_observations"]}
    if len(values) != 1:
        return None, None
    value_json, value = next(iter(values.items()))
    return value_json, value


def _presence_contexts(
    source_groups: dict[_GroupKey, dict[str, Any]],
    selected_groups: dict[_GroupKey, dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    for template_kind in ("creature", "gameobject"):
        subject_keys = sorted(
            {
                key[1]
                for key in source_groups
                if key[0] == template_kind and key[2] == "world_presence"
            }
        )
        for subject_key in subject_keys:
            group_key = (template_kind, subject_key, "world_presence", "")
            comparison_group = source_groups.get(group_key)
            active_group = selected_groups.get(group_key)
            _comparison_json, comparison_value = _unique_comparison_value(comparison_group)
            comparison_present = comparison_value if isinstance(comparison_value, bool) else None
            active_value = None if active_group is None else active_group["value"]
            active_present = active_value if isinstance(active_value, bool) else None
            directly_comparable = comparison_present is not None and active_present is not None
            if not directly_comparable:
                membership_state = "unknown"
            elif comparison_present and active_present:
                membership_state = "shared"
            elif comparison_present:
                membership_state = "comparison_only"
            elif active_present:
                membership_state = "active_only"
            else:
                membership_state = "absent_both"
            contexts[(template_kind, subject_key)] = {
                "parent_subject_kind": template_kind,
                "parent_subject_key": subject_key,
                "directly_comparable": directly_comparable,
                "membership_state": membership_state,
                "comparison_present": comparison_present,
                "active_present": active_present,
                "comparison_group_id": None
                if comparison_group is None
                else comparison_group["group_id"],
                "active_group": active_group,
            }
    return contexts


def _record_presence_context(
    subject_kind: str,
    subject_key: str,
    contexts: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    if subject_kind in {"creature", "gameobject"}:
        parent = (subject_kind, subject_key)
    else:
        parent = _spawn_parent(subject_kind, subject_key)
        if parent is None:
            return None
    context = contexts.get(parent)
    if context is None:
        return None
    return {
        "parent_subject_kind": parent[0],
        "parent_subject_key": parent[1],
        "directly_comparable": bool(context["directly_comparable"]),
        "membership_state": context["membership_state"],
        "comparison_present": context["comparison_present"],
        "active_present": context["active_present"],
        "comparison_group_id": context["comparison_group_id"],
        "active_group_id": None
        if context["active_group"] is None
        else context["active_group"]["group_id"],
    }


def _membership_contexts(
    source_groups: dict[_GroupKey, dict[str, Any]],
    selected_groups: dict[_GroupKey, dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    for template_kind in ("creature", "gameobject"):
        subject_keys = sorted(
            {
                key[1]
                for key in source_groups
                if key[0] == template_kind and key[2] == "spawn_set"
            }
        )
        for subject_key in subject_keys:
            group_key = (template_kind, subject_key, "spawn_set", "")
            comparison_group = source_groups.get(group_key)
            active_group = selected_groups.get(group_key)
            _comparison_json, comparison_value = _unique_comparison_value(comparison_group)
            comparison_keys = _spawn_keys(comparison_value)
            active_keys = None if active_group is None else _spawn_keys(active_group["value"])
            directly_comparable = comparison_keys is not None and active_keys is not None
            contexts[(template_kind, subject_key)] = {
                "parent_subject_kind": template_kind,
                "parent_subject_key": subject_key,
                "directly_comparable": directly_comparable,
                "comparison_member_count": None
                if comparison_keys is None
                else len(comparison_keys),
                "active_member_count": None if active_keys is None else len(active_keys),
                "shared_member_count": None
                if not directly_comparable
                else len(comparison_keys & active_keys),
                "comparison_only_member_count": None
                if not directly_comparable
                else len(comparison_keys - active_keys),
                "active_only_member_count": None
                if not directly_comparable
                else len(active_keys - comparison_keys),
                "comparison_keys": comparison_keys,
                "active_keys": active_keys,
                "comparison_group_id": None
                if comparison_group is None
                else comparison_group["group_id"],
                "active_group": active_group,
            }
    return contexts


def _record_complete_set_context(
    subject_kind: str,
    subject_key: str,
    contexts: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    parent = _spawn_parent(subject_kind, subject_key)
    if parent is None:
        return None
    context = contexts.get(parent)
    if context is None:
        return {
            "parent_subject_kind": parent[0],
            "parent_subject_key": parent[1],
            "directly_comparable": False,
            "membership_state": "unknown",
            "reason": "No comparison-source spawn_set was persisted for this parent template.",
        }
    comparison_keys = context["comparison_keys"]
    active_keys = context["active_keys"]
    if comparison_keys is None or active_keys is None:
        state = "unknown"
    else:
        in_comparison = subject_key in comparison_keys
        in_active = subject_key in active_keys
        if in_comparison and in_active:
            state = "shared"
        elif in_comparison:
            state = "comparison_only"
        elif in_active:
            state = "active_only"
        else:
            state = "absent_both"
    return {
        "parent_subject_kind": parent[0],
        "parent_subject_key": parent[1],
        "directly_comparable": bool(context["directly_comparable"]),
        "membership_state": state,
        "comparison_member_count": context["comparison_member_count"],
        "active_member_count": context["active_member_count"],
        "shared_member_count": context["shared_member_count"],
        "comparison_only_member_count": context["comparison_only_member_count"],
        "active_only_member_count": context["active_only_member_count"],
        "comparison_contains_subject": None
        if comparison_keys is None
        else subject_key in comparison_keys,
        "active_contains_subject": None if active_keys is None else subject_key in active_keys,
    }


def _classify_direct_group(
    group: dict[str, Any],
    active: dict[str, Any] | None,
    complete_set_context: dict[str, Any] | None,
    world_presence_context: dict[str, Any] | None,
) -> tuple[str, str]:
    values = {str(item["value_json"]) for item in group["comparison_observations"]}
    if len(values) != 1:
        return (
            "not_directly_comparable",
            ("The comparison source has multiple distinct values for this group at the "
            "chosen revision."),
        )

    if (
        world_presence_context is not None
        and group["fact_key"] not in {"world_presence", "spawn_set"}
        and world_presence_context["membership_state"] == "comparison_only"
    ):
        return (
            "comparison_only",
            ("The comparison effective view contains this template while the active selected "
            "world_presence excludes it; any selected scalar sibling is historical, not active."),
        )

    if complete_set_context is not None:
        membership = complete_set_context["membership_state"]
        if membership == "comparison_only":
            return (
                "comparison_only",
                ("The comparison complete spawn set contains this spawn while the active selected "
                "set does not."),
            )
        if membership == "shared" and active is None:
            return (
                "not_directly_comparable",
                ("Both complete spawn sets contain the spawn, but no selected primitive active "
                "evidence exists for this fact."),
            )
        if membership in {"unknown", "absent_both"} and active is None:
            return (
                "not_directly_comparable",
                ("Spawn membership cannot establish a safe active counterpart for this primitive "
                "fact."),
            )

    if active is None:
        return (
            "comparison_only",
            ("The comparison source provides evidence for a group with no active canonical "
            "selection."),
        )
    comparison_value_json = next(iter(values))
    if comparison_value_json == active["value_json"]:
        return (
            "same_value",
            "Comparison and active selected evidence have identical canonical JSON values.",
        )
    return (
        "different_value",
        ("Comparison and active selected evidence both exist and have different canonical JSON "
        "values."),
    )


def _base_record(
    *,
    key: _GroupKey,
    group_id: int,
    state: str,
    reason: str,
    active: dict[str, Any] | None,
    comparison_observation_count: int,
    complete_set_context: dict[str, Any] | None,
    world_presence_context: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "group_id": group_id,
        "subject_kind": key[0],
        "subject_key": key[1],
        "fact_key": key[2],
        "fact_instance_key": key[3],
        "state": state,
        "reason": reason,
        "comparison_observation_count": comparison_observation_count,
        "active_selected": active is not None,
        "active_source_key": None if active is None else active["source_key"],
        "active_source_revision": None if active is None else active["source_revision"],
        "selection_policy": None if active is None else active["selection_policy"],
        "complete_set_context": complete_set_context,
        "world_presence_context": world_presence_context,
    }


def _observation_batches(
    connection: sqlite3.Connection, observation_id: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT ib.id, ib.status
        FROM observation_import_batches AS oib
        JOIN import_batches AS ib ON ib.id = oib.import_batch_id
        WHERE oib.observation_id = ?
        ORDER BY ib.id
        """,
        (observation_id,),
    ).fetchall()
    return [{"batch_id": int(row["id"]), "status": str(row["status"])} for row in rows]


def _detail_payload(
    connection: sqlite3.Connection,
    record: dict[str, Any],
    source_group: dict[str, Any] | None,
    active: dict[str, Any] | None,
    *,
    comparison_source_key: str,
    comparison_revision: str,
    source_batch_map: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    comparison_observations = []
    if source_group is not None:
        for observation in source_group["comparison_observations"]:
            comparison_observations.append(
                {
                    "observation_id": observation["observation_id"],
                    "source_key": comparison_source_key,
                    "source_revision": comparison_revision,
                    "source_record_type": observation["source_record_type"],
                    "raw_identifier": observation["raw_identifier"],
                    "value": observation["value"],
                    "confidence": observation["confidence"],
                    "authority_tier": observation["authority_tier"],
                    "import_batches": source_batch_map.get(observation["observation_id"], []),
                }
            )
    active_payload = None
    if active is not None:
        active_payload = {
            "group_id": active["group_id"],
            "observation_id": active["observation_id"],
            "source_key": active["source_key"],
            "source_revision": active["source_revision"],
            "selection_policy": active["selection_policy"],
            "selection_reason": active["selection_reason"],
            "value": active["value"],
            "import_batches": _observation_batches(connection, active["observation_id"]),
        }
    return {
        **record,
        "comparison": {
            "source_key": comparison_source_key,
            "source_revision": comparison_revision,
            "observations": comparison_observations,
        },
        "active": active_payload,
    }


def comparison_report(
    connection: sqlite3.Connection,
    *,
    source_key: str,
    source_revision: str | None = None,
    subject_kind: str | None = None,
    subject_key: str | int | None = None,
    fact_key: str | None = None,
    state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Compare one persisted comparison-source revision with the active P1 selected world view.

    The comparison source is treated as a delta unless complete-set evidence proves membership
    absence. This is intentionally a read-only audit and never changes canonical selection.
    """

    if limit < 0:
        raise ValueError("limit must be non-negative")
    if source_key != P1_WORLD_COMPARISON_SOURCE_KEY:
        raise ValueError(
            "P5-T03 comparison semantics are currently bounded to source pfquest-octo"
        )
    if subject_kind is not None and subject_kind not in P1_WORLD_SUBJECT_KINDS:
        raise ValueError(f"unsupported P1 comparison subject_kind: {subject_kind}")
    if state is not None and state not in COMPARISON_STATES:
        raise ValueError(f"state must be one of {list(COMPARISON_STATES)!r}")

    source_id, revision, source_batches = _resolve_source_revision(
        connection,
        source_key=source_key,
        source_revision=source_revision,
    )
    source_groups, source_batch_map = _source_groups(
        connection,
        source_id=source_id,
        revision=revision,
    )

    touched_templates: dict[str, set[str]] = {"creature": set(), "gameobject": set()}
    touched_spawns: dict[str, set[str]] = {"creature_spawn": set(), "gameobject_spawn": set()}
    for key in source_groups:
        if key[0] in touched_templates:
            touched_templates[key[0]].add(key[1])
        elif key[0] in touched_spawns:
            touched_spawns[key[0]].add(key[1])
            parent = _spawn_parent(key[0], key[1])
            if parent is not None:
                touched_templates[parent[0]].add(parent[1])

    selected_groups: dict[_GroupKey, dict[str, Any]] = {}
    for kind, keys in touched_templates.items():
        selected_groups.update(
            _selected_groups_for_subjects(connection, subject_kind=kind, subject_keys=keys)
        )

    presence_contexts = _presence_contexts(source_groups, selected_groups)
    contexts = _membership_contexts(source_groups, selected_groups)
    active_only_spawn_keys: dict[str, set[str]] = {
        "creature_spawn": set(),
        "gameobject_spawn": set(),
    }
    for (template_kind, _template_key), context in contexts.items():
        if not context["directly_comparable"]:
            continue
        child_kind = f"{template_kind}_spawn"
        active_only_spawn_keys[child_kind].update(
            context["active_keys"] - context["comparison_keys"]
        )

    for kind in ("creature_spawn", "gameobject_spawn"):
        keys = touched_spawns[kind] | active_only_spawn_keys[kind]
        selected_groups.update(
            _selected_groups_for_subjects(connection, subject_kind=kind, subject_keys=keys)
        )

    records_by_key: dict[_GroupKey, dict[str, Any]] = {}
    for key, group in source_groups.items():
        active = selected_groups.get(key) or group.get("active")
        complete_set_context = _record_complete_set_context(key[0], key[1], contexts)
        world_presence_context = _record_presence_context(key[0], key[1], presence_contexts)
        state_label, reason = _classify_direct_group(
            group, active, complete_set_context, world_presence_context
        )
        records_by_key[key] = _base_record(
            key=key,
            group_id=int(group["group_id"]),
            state=state_label,
            reason=reason,
            active=active,
            comparison_observation_count=len(group["comparison_observations"]),
            complete_set_context=complete_set_context,
            world_presence_context=world_presence_context,
        )

    for key, active in selected_groups.items():
        if key in source_groups:
            continue
        complete_set_context = _record_complete_set_context(key[0], key[1], contexts)
        world_presence_context = _record_presence_context(key[0], key[1], presence_contexts)
        if key[0].endswith("_spawn"):
            if (
                complete_set_context is not None
                and complete_set_context["membership_state"] == "active_only"
            ):
                state_label = "active_only"
                reason = (
                    "The active selected complete spawn set contains this spawn while the "
                    "comparison complete set excludes it."
                )
            elif complete_set_context is not None and complete_set_context["membership_state"] in {
                "absent_both",
                "comparison_only",
            }:
                # A selected primitive can survive historically even when the active complete set
                # excludes the spawn. It is not part of the active effective view.
                continue
            elif (
                world_presence_context is not None
                and world_presence_context["membership_state"] == "active_only"
            ):
                state_label = "active_only"
                reason = (
                    "The active parent template is explicitly present while the comparison "
                    "world_presence excludes it."
                )
            elif world_presence_context is not None and world_presence_context[
                "membership_state"
            ] in {"absent_both", "comparison_only"}:
                # Parent world presence excludes this selected historical child primitive.
                continue
            else:
                state_label = "not_directly_comparable"
                reason = (
                    "The active selected fact has no comparison-source observation, and "
                    "delta-source absence does not prove fact absence."
                )
        elif (
            world_presence_context is not None
            and world_presence_context["membership_state"] == "active_only"
        ):
            state_label = "active_only"
            reason = (
                "The active selected world_presence contains this template while the comparison "
                "effective view explicitly excludes it."
            )
        elif world_presence_context is not None and world_presence_context["membership_state"] in {
            "absent_both",
            "comparison_only",
        }:
            # Selected scalar facts can survive historically after active world_presence becomes
            # false. They are not part of the active effective template view.
            continue
        else:
            state_label = "not_directly_comparable"
            reason = (
                "The active selected fact has no comparison-source observation; this comparison "
                "source is persisted as a delta rather than a complete template fact view."
            )
        records_by_key[key] = _base_record(
            key=key,
            group_id=int(active["group_id"]),
            state=state_label,
            reason=reason,
            active=active,
            comparison_observation_count=0,
            complete_set_context=complete_set_context,
            world_presence_context=world_presence_context,
        )

    records = [records_by_key[key] for key in sorted(records_by_key)]
    subject_key_filter = None if subject_key is None else str(subject_key)
    filtered_records = [
        record
        for record in records
        if (subject_kind is None or record["subject_kind"] == subject_kind)
        and (subject_key_filter is None or record["subject_key"] == subject_key_filter)
        and (fact_key is None or record["fact_key"] == fact_key)
        and (state is None or record["state"] == state)
    ]

    state_counts = {label: 0 for label in COMPARISON_STATES}
    subject_kind_counters: dict[str, dict[str, Any]] = {}
    fact_family_counters: dict[tuple[str, str], dict[str, Any]] = {}
    active_context_counters: dict[tuple[str, str, str | None], dict[str, int]] = {}
    subjects_by_kind: dict[str, set[str]] = defaultdict(set)

    for record in filtered_records:
        state_counts[record["state"]] += 1
        kind = str(record["subject_kind"])
        subjects_by_kind[kind].add(str(record["subject_key"]))
        kind_counter = subject_kind_counters.setdefault(
            kind,
            {
                "record_count": 0,
                "comparison_observation_count": 0,
                "state_counts": {label: 0 for label in COMPARISON_STATES},
            },
        )
        kind_counter["record_count"] += 1
        kind_counter["comparison_observation_count"] += int(record["comparison_observation_count"])
        kind_counter["state_counts"][record["state"]] += 1

        family_key = (kind, str(record["fact_key"]))
        family_counter = fact_family_counters.setdefault(
            family_key,
            {
                "record_count": 0,
                "comparison_observation_count": 0,
                "state_counts": {label: 0 for label in COMPARISON_STATES},
            },
        )
        family_counter["record_count"] += 1
        family_counter["comparison_observation_count"] += int(
            record["comparison_observation_count"]
        )
        family_counter["state_counts"][record["state"]] += 1

        if record["active_selected"]:
            active_key = (
                str(record["active_source_key"]),
                str(record["active_source_revision"]),
                record["selection_policy"],
            )
            counter = active_context_counters.setdefault(
                active_key,
                {"record_count": 0, **{label: 0 for label in COMPARISON_STATES}},
            )
            counter["record_count"] += 1
            counter[record["state"]] += 1

    source_group_keys = set(source_groups)
    source_group_count = len(source_group_keys)
    source_observation_count = sum(
        len(group["comparison_observations"]) for group in source_groups.values()
    )
    source_unselected_group_count = sum(
        1 for group in source_groups.values() if group.get("active") is None
    )

    presence_patterns: list[dict[str, Any]] = []
    for template_kind in ("creature", "gameobject"):
        relevant = [
            context
            for (kind, _), context in sorted(presence_contexts.items())
            if kind == template_kind
        ]
        if not relevant:
            continue
        counts = {
            label: sum(1 for item in relevant if item["membership_state"] == label)
            for label in ("shared", "comparison_only", "active_only", "absent_both", "unknown")
        }
        presence_patterns.append(
            {
                "template_kind": template_kind,
                "parent_count": len(relevant),
                "directly_comparable_parent_count": sum(
                    int(bool(item["directly_comparable"])) for item in relevant
                ),
                "shared_subject_count": counts["shared"],
                "comparison_only_subject_count": counts["comparison_only"],
                "active_only_subject_count": counts["active_only"],
                "absent_both_subject_count": counts["absent_both"],
                "unknown_subject_count": counts["unknown"],
            }
        )

    membership_patterns: list[dict[str, Any]] = []
    for template_kind in ("creature", "gameobject"):
        relevant = [
            context
            for (kind, _), context in sorted(contexts.items())
            if kind == template_kind and context["directly_comparable"]
        ]
        if not relevant:
            continue
        membership_patterns.append(
            {
                "template_kind": template_kind,
                "parent_count": len(relevant),
                "active_member_count": sum(int(item["active_member_count"]) for item in relevant),
                "comparison_member_count": sum(
                    int(item["comparison_member_count"]) for item in relevant
                ),
                "shared_member_count": sum(int(item["shared_member_count"]) for item in relevant),
                "comparison_only_member_count": sum(
                    int(item["comparison_only_member_count"]) for item in relevant
                ),
                "active_only_member_count": sum(
                    int(item["active_only_member_count"]) for item in relevant
                ),
            }
        )

    detailed_records = filtered_records[:limit] if limit else []
    details = []
    for record in detailed_records:
        key = (
            str(record["subject_kind"]),
            str(record["subject_key"]),
            str(record["fact_key"]),
            str(record["fact_instance_key"]),
        )
        details.append(
            _detail_payload(
                connection,
                record,
                source_groups.get(key),
                selected_groups.get(key) or (source_groups.get(key) or {}).get("active"),
                comparison_source_key=source_key,
                comparison_revision=revision,
                source_batch_map=source_batch_map,
            )
        )

    return {
        "scope": P1_WORLD_COMPARISON_SCOPE,
        "filters": {
            "subject_kind": subject_kind,
            "subject_key": subject_key_filter,
            "fact_key": fact_key,
            "state": state,
        },
        "comparison_states": list(COMPARISON_STATES),
        "comparison_source": {
            "source_key": source_key,
            "source_revision": revision,
            "import_batches": source_batches,
            "group_count": source_group_count,
            "observation_count": source_observation_count,
            "unselected_group_count": source_unselected_group_count,
        },
        "record_count": len(filtered_records),
        "compared_group_count": len(filtered_records),
        "returned_record_count": len(details),
        "detail_limit": limit,
        "details_truncated": len(details) < len(filtered_records),
        "compared_subject_count": len(
            {(record["subject_kind"], record["subject_key"]) for record in filtered_records}
        ),
        "comparison_observation_count": sum(
            int(record["comparison_observation_count"]) for record in filtered_records
        ),
        "active_selected_observation_count": sum(
            int(bool(record["active_selected"])) for record in filtered_records
        ),
        "state_counts": state_counts,
        "subject_kinds": [
            {
                "subject_kind": kind,
                "subject_count": len(subjects_by_kind[kind]),
                **subject_kind_counters[kind],
            }
            for kind in sorted(subject_kind_counters)
        ],
        "fact_families": [
            {
                "subject_kind": key[0],
                "fact_key": key[1],
                **fact_family_counters[key],
            }
            for key in sorted(fact_family_counters)
        ],
        "active_selected_contexts": [
            {
                "source_key": key[0],
                "source_revision": key[1],
                "selection_policy": key[2],
                **active_context_counters[key],
            }
            for key in sorted(
                active_context_counters,
                key=lambda item: (item[0], item[1], "" if item[2] is None else item[2]),
            )
        ],
        "template_presence_patterns": presence_patterns,
        "spawn_membership_patterns": membership_patterns,
        "records": details,
    }


def _nonnegative_int(value: str) -> int:
    import argparse

    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _open_read_only_database(path: str) -> sqlite3.Connection:
    from pathlib import Path

    db_path = Path(path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"database file not found: {db_path}")
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _print_human(payload: dict[str, Any]) -> None:
    print(f"Comparison scope: {payload['scope']}")
    source = payload["comparison_source"]
    print(f"Comparison source: {source['source_key']}@{source['source_revision']}")
    filters = payload["filters"]
    active_filters = [f"{key}={value}" for key, value in filters.items() if value is not None]
    if active_filters:
        print("Filters: " + ", ".join(active_filters))
    print(f"Matched records: {payload['record_count']}")
    print(f"Compared subjects: {payload['compared_subject_count']}")
    print(f"Comparison observations: {payload['comparison_observation_count']}")
    print(f"Active selected observations: {payload['active_selected_observation_count']}")
    print(f"Detailed records returned: {payload['returned_record_count']}")
    print(f"Details truncated: {'yes' if payload['details_truncated'] else 'no'}")
    print("States:")
    for label in COMPARISON_STATES:
        print(f"- {label}: {payload['state_counts'][label]}")
    if payload["template_presence_patterns"]:
        print("Template presence patterns:")
        for pattern in payload["template_presence_patterns"]:
            print(
                f"- {pattern['template_kind']}: parents={pattern['parent_count']}, "
                f"shared={pattern['shared_subject_count']}, "
                f"comparison-only={pattern['comparison_only_subject_count']}, "
                f"active-only={pattern['active_only_subject_count']}, "
                f"unknown={pattern['unknown_subject_count']}"
            )
    if payload["spawn_membership_patterns"]:
        print("Spawn membership patterns:")
        for pattern in payload["spawn_membership_patterns"]:
            print(
                f"- {pattern['template_kind']}: parents={pattern['parent_count']}, "
                f"shared={pattern['shared_member_count']}, "
                f"comparison-only={pattern['comparison_only_member_count']}, "
                f"active-only={pattern['active_only_member_count']}"
            )
    for record in payload["records"]:
        print(
            f"- {record['subject_kind']}:{record['subject_key']} {record['fact_key']}: "
            f"{record['state']}"
        )
        context = record.get("complete_set_context")
        if context is not None:
            print(
                "  complete-set context: "
                f"{context['parent_subject_kind']}:{context['parent_subject_key']} "
                f"membership={context['membership_state']}"
            )
        presence = record.get("world_presence_context")
        if presence is not None:
            print(f"  world-presence context: membership={presence['membership_state']}")


def main(argv: list[str] | None = None) -> int:
    """Run the bounded P1 comparison audit as a source-focused read-only CLI."""

    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="python -m octogamedb.audit_comparison",
        description=(
            "Compare one persisted comparison-source revision with the active selected P1 world "
            "view without changing canonical selection."
        ),
    )
    parser.add_argument("source_key", help="Comparison source key, normally pfquest-octo.")
    parser.add_argument(
        "--source-revision",
        help="Optional exact source revision; latest succeeded is default.",
    )
    parser.add_argument("--subject-kind", choices=P1_WORLD_SUBJECT_KINDS)
    parser.add_argument("--subject-key")
    parser.add_argument("--fact", dest="fact_key")
    parser.add_argument("--state", choices=COMPARISON_STATES)
    parser.add_argument(
        "--limit",
        type=_nonnegative_int,
        default=100,
        help="Maximum detailed records after exhaustive aggregates; 0 emits summary only.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/generated/octogamedb.sqlite3"),
        help="SQLite database path (opened mode=ro).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    connection = _open_read_only_database(str(args.db))
    try:
        payload = comparison_report(
            connection,
            source_key=args.source_key,
            source_revision=args.source_revision,
            subject_kind=args.subject_kind,
            subject_key=args.subject_key,
            fact_key=args.fact_key,
            state=args.state,
            limit=args.limit,
        )
    finally:
        connection.close()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
