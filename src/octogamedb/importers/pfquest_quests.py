"""pfQuest quest identity and giver/finisher importer for the bounded P3-T01 slice."""

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

IMPORTER_VERSION = "pfquest-quests/1"
_QUEST_FILES = ("db/quests.lua", "db/enUS/quests.lua")
_ENDPOINT_MAP = (
    ("start", "U", "giver", "creature"),
    ("start", "O", "giver", "gameobject"),
    ("end", "U", "finisher", "creature"),
    ("end", "O", "finisher", "gameobject"),
)


@dataclass(frozen=True)
class PfQuestEndpoint:
    endpoint_kind: str
    target_kind: str
    target_id: int


@dataclass(frozen=True)
class PfQuestQuest:
    quest_id: int
    name: str
    endpoints: tuple[PfQuestEndpoint, ...]


@dataclass(frozen=True)
class PfQuestQuestSlice:
    quests: tuple[PfQuestQuest, ...]
    rows_read: int
    rows_skipped: int
    missing_enus_name_ids: tuple[int, ...]


def compute_pfquest_quests_revision(source_root: str | Path) -> str:
    """Return a deterministic revision for the exact base-pfQuest P3-T01 inputs."""

    root = Path(source_root)
    missing = [relative for relative in _QUEST_FILES if not (root / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"missing required pfQuest quest file: {root / missing[0]}")

    digest = hashlib.sha256()
    for relative in _QUEST_FILES:
        path = root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return f"sha256:{digest.hexdigest()}"


def _integer_id(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PfQuestParseError(f"{label} must be an integer native ID")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise PfQuestParseError(f"{label} must be an integer native ID")


def _endpoint_ids(value: Any, *, label: str) -> tuple[int, ...]:
    """Parse source-shaped pfQuest endpoint arrays while preserving native IDs."""

    if value is None:
        return ()
    if not isinstance(value, dict):
        raise PfQuestParseError(f"{label} must be a Lua table")

    ids: list[int] = []
    for key in sorted(key for key in value if isinstance(key, int)):
        ids.append(_integer_id(value[key], label=f"{label}[{key}]"))
    return tuple(dict.fromkeys(ids))


def _quest_title(locale_row: Any) -> str | None:
    if not isinstance(locale_row, dict):
        return None
    title = locale_row.get("T")
    if not isinstance(title, str) or not title.strip():
        return None
    return title.strip()


def load_pfquest_quest_slice(source_root: str | Path) -> PfQuestQuestSlice:
    """Load base pfQuest quest identity plus creature/game-object giver/finisher relations."""

    root = Path(source_root)
    quest_data = parse_pfquest_assignment(
        (root / "db" / "quests.lua").read_text(encoding="utf-8"),
        domain="quests",
        table_name="data",
    )
    quest_locales = parse_pfquest_assignment(
        (root / "db" / "enUS" / "quests.lua").read_text(encoding="utf-8"),
        domain="quests",
        table_name="enUS",
    )

    quest_ids = sorted(
        {key for key in quest_data if isinstance(key, int)}
        | {key for key in quest_locales if isinstance(key, int)}
    )
    quests: list[PfQuestQuest] = []
    missing_names: list[int] = []

    for quest_id in quest_ids:
        record = quest_data.get(quest_id, {})
        if not isinstance(record, dict):
            raise PfQuestParseError(f"quest[{quest_id}] must be a Lua table")

        name = _quest_title(quest_locales.get(quest_id))
        if name is None:
            missing_names.append(int(quest_id))
            continue

        endpoints: list[PfQuestEndpoint] = []
        for phase, source_key, endpoint_kind, target_kind in _ENDPOINT_MAP:
            phase_row = record.get(phase)
            if phase_row is None:
                continue
            if not isinstance(phase_row, dict):
                raise PfQuestParseError(f"quest[{quest_id}].{phase} must be a Lua table")
            for target_id in _endpoint_ids(
                phase_row.get(source_key),
                label=f"quest[{quest_id}].{phase}.{source_key}",
            ):
                endpoints.append(PfQuestEndpoint(endpoint_kind, target_kind, target_id))

        endpoints.sort(key=lambda item: (item.endpoint_kind, item.target_kind, item.target_id))
        quests.append(PfQuestQuest(int(quest_id), name, tuple(endpoints)))

    return PfQuestQuestSlice(
        quests=tuple(quests),
        rows_read=len(quest_ids),
        rows_skipped=len(missing_names),
        missing_enus_name_ids=tuple(missing_names),
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
        "SELECT id FROM data_sources WHERE source_key = ?", (PFQUEST_SOURCE_KEY,)
    ).fetchone()
    if row is None:
        raise RuntimeError("pfQuest source registration failed")
    return int(row["id"])


def _selected_value(
    connection: sqlite3.Connection, *, observation_id: int, selection_reason: str
) -> Any:
    row = connection.execute(
        """
        SELECT so.observation_group_id, selected.value_json AS selected_value_json
        FROM source_observations AS so
        LEFT JOIN canonical_selections AS cs
            ON cs.observation_group_id = so.observation_group_id
        LEFT JOIN source_observations AS selected ON selected.id = cs.observation_id
        WHERE so.id = ?
        """,
        (observation_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"observation {observation_id} disappeared")

    selected_json = row["selected_value_json"]
    if selected_json is None:
        select_canonical_observation(
            connection,
            observation_group_id=int(row["observation_group_id"]),
            observation_id=observation_id,
            selection_policy="first-observation",
            selection_reason=selection_reason,
        )
        selected_json = connection.execute(
            "SELECT value_json FROM source_observations WHERE id = ?", (observation_id,)
        ).fetchone()["value_json"]
    return json.loads(str(selected_json))


def _observe_name(
    connection: sqlite3.Connection, *, batch_id: int, quest_id: int, name: str
) -> str:
    observation_id = record_scalar_observation(
        connection,
        subject_kind="quest",
        subject_key=quest_id,
        fact_key="name",
        import_batch_id=batch_id,
        value=name,
        source_record_type="quest_locale",
        raw_identifier=f"{quest_id}:T",
    )
    return str(
        _selected_value(
            connection,
            observation_id=observation_id,
            selection_reason=(
                "Selected automatically because this quest name had no prior selection."
            ),
        )
    )


def _observe_endpoint(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    quest_id: int,
    endpoint: PfQuestEndpoint,
) -> None:
    instance_key = f"{endpoint.endpoint_kind}:{endpoint.target_kind}:{endpoint.target_id}"
    observation_id = record_relation_observation(
        connection,
        subject_kind="quest",
        subject_key=quest_id,
        fact_key="endpoint",
        import_batch_id=batch_id,
        target_kind=endpoint.target_kind,
        target_key=endpoint.target_id,
        relation_instance_key=instance_key,
        attributes={"endpoint_kind": endpoint.endpoint_kind},
        source_record_type="quest_endpoint",
        raw_identifier=instance_key,
    )
    payload = _selected_value(
        connection,
        observation_id=observation_id,
        selection_reason=(
            "Selected automatically because this quest endpoint had no prior selection."
        ),
    )
    target = payload.get("target", {})
    attributes = payload.get("attributes", {})
    if (
        target.get("kind") != endpoint.target_kind
        or str(target.get("key")) != str(endpoint.target_id)
        or attributes.get("endpoint_kind") != endpoint.endpoint_kind
    ):
        raise RuntimeError("selected quest endpoint does not match its relation instance")


def import_pfquest_quests(
    connection: sqlite3.Connection,
    *,
    source_root: str | Path,
    source_revision: str,
) -> ImportSummary:
    """Import the bounded base-pfQuest P3-T01 quest slice into canonical storage."""

    revision = source_revision.strip()
    if not revision:
        raise ValueError("source_revision must not be blank")

    slice_data = load_pfquest_quest_slice(source_root)
    source_id = _ensure_source(connection, str(Path(source_root)))
    cursor = connection.execute(
        """
        INSERT INTO import_batches(source_id, source_revision, status, importer_version, rows_read)
        VALUES (?, ?, 'running', ?, ?)
        """,
        (source_id, revision, IMPORTER_VERSION, slice_data.rows_read),
    )
    batch_id = int(cursor.lastrowid)
    inserted = 0
    updated = 0
    unresolved: list[dict[str, Any]] = []
    creature_endpoints = 0
    gameobject_endpoints = 0

    try:
        creature_ids = {
            int(row[0])
            for row in connection.execute("SELECT creature_id FROM creatures").fetchall()
        }
        gameobject_ids = {
            int(row[0])
            for row in connection.execute("SELECT gameobject_id FROM gameobjects").fetchall()
        }

        for quest in slice_data.quests:
            canonical_name = _observe_name(
                connection, batch_id=batch_id, quest_id=quest.quest_id, name=quest.name
            )
            existing = connection.execute(
                "SELECT name FROM quests WHERE quest_id = ?", (quest.quest_id,)
            ).fetchone()
            if existing is None:
                inserted += 1
            elif existing["name"] != canonical_name:
                updated += 1
            connection.execute(
                """
                INSERT INTO quests(quest_id, name) VALUES (?, ?)
                ON CONFLICT(quest_id) DO UPDATE SET name = excluded.name
                """,
                (quest.quest_id, canonical_name),
            )

            for endpoint in quest.endpoints:
                _observe_endpoint(
                    connection, batch_id=batch_id, quest_id=quest.quest_id, endpoint=endpoint
                )
                target_exists = (
                    endpoint.target_id in creature_ids
                    if endpoint.target_kind == "creature"
                    else endpoint.target_id in gameobject_ids
                )
                if not target_exists:
                    unresolved.append(
                        {
                            "quest_id": quest.quest_id,
                            "endpoint_kind": endpoint.endpoint_kind,
                            "target_kind": endpoint.target_kind,
                            "target_id": endpoint.target_id,
                            "reason": "missing_p1_target",
                        }
                    )
                    continue

                if endpoint.target_kind == "creature":
                    table = "quest_creature_endpoints"
                    id_column = "creature_id"
                    creature_endpoints += 1
                else:
                    table = "quest_gameobject_endpoints"
                    id_column = "gameobject_id"
                    gameobject_endpoints += 1

                existing_relation = connection.execute(
                    f"SELECT 1 FROM {table} WHERE quest_id = ? AND endpoint_kind = ? "
                    f"AND {id_column} = ?",
                    (quest.quest_id, endpoint.endpoint_kind, endpoint.target_id),
                ).fetchone()
                connection.execute(
                    f"INSERT OR IGNORE INTO {table}(quest_id, endpoint_kind, {id_column}) "
                    "VALUES (?, ?, ?)",
                    (quest.quest_id, endpoint.endpoint_kind, endpoint.target_id),
                )
                if existing_relation is None:
                    inserted += 1

        unresolved.sort(
            key=lambda issue: (
                int(issue["quest_id"]),
                str(issue["endpoint_kind"]),
                str(issue["target_kind"]),
                int(issue["target_id"]),
            )
        )
        details = {
            "quests": len(slice_data.quests),
            "creature_endpoints": creature_endpoints,
            "gameobject_endpoints": gameobject_endpoints,
            "missing_enus_name_ids": list(slice_data.missing_enus_name_ids),
            "unresolved_endpoints": unresolved,
            "turtle_effective_view": "deferred_after_mandatory_source_inspection",
        }
        warning_count = len(slice_data.missing_enus_name_ids) + len(unresolved)
        connection.execute(
            """
            UPDATE import_batches
            SET status = 'succeeded',
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                rows_read = ?, rows_accepted = ?, rows_skipped = ?,
                rows_inserted = ?, rows_updated = ?, warning_count = ?, details_json = ?
            WHERE id = ?
            """,
            (
                slice_data.rows_read,
                len(slice_data.quests),
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
        source_revision=revision,
        status="succeeded",
        rows_read=slice_data.rows_read,
        rows_accepted=len(slice_data.quests),
        rows_skipped=slice_data.rows_skipped,
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=warning_count,
        error_count=0,
        details=details,
    )
