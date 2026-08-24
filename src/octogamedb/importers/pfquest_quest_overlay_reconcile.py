"""Reconcile P3 quest identity/endpoints against the effective pfQuest + Turtle view.

The bounded P3-T02 adapter reproduces pfQuest-turtle top-entry patch semantics for
quest data and enUS localization without executing Lua. It records effective-view
presence/endpoint-set evidence while keeping primitive quest names and endpoints
attributed to the source that actually supplied them.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import (
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.pfquest_quests import (
    PfQuestEndpoint,
    _endpoint_ids,
    _quest_title,
)
from octogamedb.importers.pfquest_world import (
    PFQUEST_SOURCE_KEY,
    PfQuestParseError,
    _LuaLiteralParser,
    parse_pfquest_assignment,
)
from octogamedb.importers.summary import ImportSummary

IMPORTER_VERSION = "pfquest-quest-overlay-reconcile/1"
BASE_IMPORTER_PREFIX = "pfquest-quests/"
PFQUEST_TURTLE_SOURCE_KEY = "pfquest-turtle"
PFQUEST_TURTLE_SOURCE_URL = "https://github.com/KameleonUK/pfQuest-turtle"
TURTLE_SELECTION_POLICY = "pfquest-turtle-effective-quests"
BASE_SET_SELECTION_POLICY = "pfquest-base-effective-quests"
QUEST_PRESENCE_FACT = "quest_presence"
QUEST_ENDPOINT_SET_FACT = "quest_endpoint_set"

_DEFAULT_BASE_POLICIES = frozenset({None, "first-observation", BASE_SET_SELECTION_POLICY})

_BASE_FILES = {
    ("quests", "data"): "db/quests.lua",
    ("quests", "enUS"): "db/enUS/quests.lua",
}
_OVERLAY_FILES = {
    ("quests", "data-turtle"): "db/quests-turtle.lua",
    ("quests", "enUS-turtle"): "db/enUS/quests-turtle.lua",
}
_OVERLAY_REVISION_FILES = (
    "pfQuest-turtle.toc",
    "init/data-turtle.xml",
    "init/enUS-turtle.xml",
    "db/quests-turtle.lua",
    "db/enUS/quests-turtle.lua",
    "overwrites.lua",
    "patchtable.lua",
)
_ENDPOINT_MAP = (
    ("start", "U", "giver", "creature"),
    ("start", "O", "giver", "gameobject"),
    ("end", "U", "finisher", "creature"),
    ("end", "O", "finisher", "gameobject"),
)


@dataclass(frozen=True)
class _Selection:
    observation_id: int
    source_key: str
    selection_policy: str | None
    value: Any


@dataclass(frozen=True)
class _EffectiveQuestTables:
    base_data: dict[Any, Any]
    base_names: dict[Any, Any]
    patch_data: dict[Any, Any]
    patch_names: dict[Any, Any]
    effective_data: dict[Any, Any]
    effective_names: dict[Any, Any]


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


def _read_assignment(path: Path, domain: str, table_name: str) -> dict[Any, Any]:
    return parse_pfquest_assignment(
        path.read_text(encoding="utf-8"), domain=domain, table_name=table_name
    )


def _patch_table(base: dict[Any, Any], patch: dict[Any, Any]) -> dict[Any, Any]:
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, str) and value == "_":
            result.pop(key, None)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _direct_prefix(domain: str, table_name: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?m)^[ \t]*pfDB\s*\[\s*['\"]{re.escape(domain)}['\"]\s*\]\s*"
        rf"\[\s*['\"]{re.escape(table_name)}['\"]\s*\]"
    )


def _apply_nested_assignment(
    root: dict[Any, Any], *, keys: list[Any], value: Any, label: str
) -> dict[Any, Any]:
    if not keys:
        if not isinstance(value, dict):
            raise PfQuestParseError(f"{label} root overwrite must assign a Lua table")
        return copy.deepcopy(value)

    cursor = root
    for key in keys[:-1]:
        child = cursor.get(key)
        if not isinstance(child, dict):
            raise PfQuestParseError(
                f"{label} overwrite cannot index missing/non-table key {key!r}"
            )
        cursor = child

    final_key = keys[-1]
    if value is None:
        cursor.pop(final_key, None)
    else:
        cursor[final_key] = copy.deepcopy(value)
    return root


def _apply_direct_overwrites(
    patches: dict[tuple[str, str], dict[Any, Any]], text: str
) -> None:
    for (domain, table_name), initial_patch in tuple(patches.items()):
        patch = initial_patch
        prefix = _direct_prefix(domain, table_name)
        for match in prefix.finditer(text):
            parser = _LuaLiteralParser(text, match.end())
            keys: list[Any] = []
            while parser._peek() == "[":
                parser.position += 1
                key = parser.parse_value()
                if not isinstance(key, (str, int)) or isinstance(key, bool):
                    raise PfQuestParseError(
                        f"{domain}.{table_name} overwrite key must be string/int"
                    )
                parser._consume("]")
                keys.append(key)
            try:
                parser._consume("=")
            except PfQuestParseError as exc:
                raise PfQuestParseError(
                    f"unsupported indirect P3 quest-table mutation for {domain}.{table_name}"
                ) from exc
            value = parser.parse_value()
            patch = _apply_nested_assignment(
                patch,
                keys=keys,
                value=value,
                label=f"{domain}.{table_name}",
            )
            patches[(domain, table_name)] = patch


def _validate_no_unhandled_quest_mutations(text: str) -> None:
    direct = tuple(_direct_prefix(domain, table) for domain, table in _OVERLAY_FILES)
    references = tuple(
        re.compile(
            rf"pfDB\s*\[\s*['\"]{re.escape(domain)}['\"]\s*\]\s*"
            rf"\[\s*['\"]{re.escape(table)}['\"]\s*\]"
        )
        for domain, table in _OVERLAY_FILES
    )
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("--"):
            continue
        if not any(pattern.search(line) for pattern in references):
            continue
        if any(pattern.match(line) for pattern in direct):
            continue
        raise PfQuestParseError(
            "unsupported indirect P3 quest overlay mutation on "
            f"overwrites.lua line {line_number}"
        )


def _require_order(text: str, markers: tuple[str, ...], label: str) -> None:
    positions = [text.find(marker) for marker in markers]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise PfQuestParseError(f"unsupported {label} load order/layout")


def _validate_turtle_layout(source_root: str | Path) -> Path:
    root = Path(source_root)
    if not root.is_dir():
        raise FileNotFoundError(f"pfQuest-turtle directory not found: {root}")
    missing = [relative for relative in _OVERLAY_REVISION_FILES if not (root / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"missing required pfQuest-turtle P3 file: {root / missing[0]}")

    toc = (root / "pfQuest-turtle.toc").read_text(encoding="utf-8").replace("/", "\\")
    _require_order(
        toc,
        ("init\\data-turtle.xml", "init\\enUS-turtle.xml", "overwrites.lua", "patchtable.lua"),
        "pfQuest-turtle toc",
    )
    data_xml = (root / "init" / "data-turtle.xml").read_text(encoding="utf-8")
    if "quests-turtle.lua" not in data_xml:
        raise PfQuestParseError(
            "unsupported Turtle P3 data layout: quests-turtle.lua is not loaded"
        )
    enus_xml = (root / "init" / "enUS-turtle.xml").read_text(encoding="utf-8")
    if "quests-turtle.lua" not in enus_xml:
        raise PfQuestParseError(
            "unsupported Turtle P3 enUS layout: quests-turtle.lua is not loaded"
        )

    patchtable = (root / "patchtable.lua").read_text(encoding="utf-8")
    required_markers = (
        '"quests"',
        'pfDB[db]["data-turtle"]',
        'loc.."-turtle"',
        'base[k] = nil',
        'base[k] = v',
    )
    if any(marker not in patchtable for marker in required_markers):
        raise PfQuestParseError("unsupported pfQuest-turtle quest patchtable semantics")
    return root


def compute_pfquest_turtle_quests_revision(source_root: str | Path) -> str:
    """Hash the exact supported Turtle P3 identity/endpoint composition inputs."""

    root = _validate_turtle_layout(source_root)
    digest = hashlib.sha256()
    for relative in _OVERLAY_REVISION_FILES:
        path = root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return f"sha256:{digest.hexdigest()}"


def _load_effective_tables(
    pfquest_root: str | Path, pfquest_turtle_root: str | Path
) -> _EffectiveQuestTables:
    base_root = Path(pfquest_root)
    overlay_root = _validate_turtle_layout(pfquest_turtle_root)

    base: dict[tuple[str, str], dict[Any, Any]] = {}
    for (domain, table_name), relative in _BASE_FILES.items():
        path = base_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"missing required pfQuest P3 file: {path}")
        base[(domain, table_name)] = _read_assignment(path, domain, table_name)

    patch: dict[tuple[str, str], dict[Any, Any]] = {}
    for (domain, table_name), relative in _OVERLAY_FILES.items():
        path = overlay_root / relative
        patch[(domain, table_name)] = _read_assignment(path, domain, table_name)

    overwrite_text = (overlay_root / "overwrites.lua").read_text(encoding="utf-8")
    _apply_direct_overwrites(patch, overwrite_text)
    _validate_no_unhandled_quest_mutations(overwrite_text)

    base_data = base[("quests", "data")]
    base_names = base[("quests", "enUS")]
    patch_data = patch[("quests", "data-turtle")]
    patch_names = patch[("quests", "enUS-turtle")]
    return _EffectiveQuestTables(
        base_data=base_data,
        base_names=base_names,
        patch_data=patch_data,
        patch_names=patch_names,
        effective_data=_patch_table(base_data, patch_data),
        effective_names=_patch_table(base_names, patch_names),
    )


def _endpoints_for_record(record: Any, *, quest_id: int) -> tuple[PfQuestEndpoint, ...]:
    if record is None:
        return ()
    if not isinstance(record, dict):
        raise PfQuestParseError(f"quest[{quest_id}] must be a Lua table")

    endpoints: list[PfQuestEndpoint] = []
    for phase, source_key, endpoint_kind, target_kind in _ENDPOINT_MAP:
        phase_row = record.get(phase)
        if phase_row is None:
            continue
        if not isinstance(phase_row, dict):
            raise PfQuestParseError(f"quest[{quest_id}].{phase} must be a Lua table")
        for target_id in _endpoint_ids(
            phase_row.get(source_key), label=f"quest[{quest_id}].{phase}.{source_key}"
        ):
            endpoints.append(PfQuestEndpoint(endpoint_kind, target_kind, target_id))
    endpoints.sort(key=lambda item: (item.endpoint_kind, item.target_kind, item.target_id))
    return tuple(endpoints)


def _endpoint_payload(endpoints: tuple[PfQuestEndpoint, ...]) -> list[dict[str, Any]]:
    return [
        {
            "endpoint_kind": endpoint.endpoint_kind,
            "target_kind": endpoint.target_kind,
            "target_id": endpoint.target_id,
        }
        for endpoint in endpoints
    ]


def _payload_endpoints(value: Any) -> tuple[PfQuestEndpoint, ...]:
    if not isinstance(value, list):
        raise TypeError("selected quest endpoint set must be a list")
    endpoints: list[PfQuestEndpoint] = []
    for row in value:
        if not isinstance(row, dict):
            raise TypeError("selected quest endpoint-set member must be an object")
        endpoint_kind = row.get("endpoint_kind")
        target_kind = row.get("target_kind")
        target_id = row.get("target_id")
        if endpoint_kind not in {"giver", "finisher"}:
            raise ValueError("selected quest endpoint set has invalid endpoint_kind")
        if target_kind not in {"creature", "gameobject"}:
            raise ValueError("selected quest endpoint set has invalid target_kind")
        if isinstance(target_id, bool) or not isinstance(target_id, int):
            raise TypeError("selected quest endpoint set has invalid target_id")
        endpoints.append(PfQuestEndpoint(endpoint_kind, target_kind, target_id))
    endpoints.sort(key=lambda item: (item.endpoint_kind, item.target_kind, item.target_id))
    return tuple(endpoints)


def _source_id(connection: sqlite3.Connection, source_key: str) -> int:
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (source_key,)
    ).fetchone()
    if row is None:
        raise ValueError(f"required source has not been imported: {source_key}")
    return int(row["id"])


def _require_base_quest_import(connection: sqlite3.Connection, revision: str) -> int:
    source_id = _source_id(connection, PFQUEST_SOURCE_KEY)
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
        (source_id, revision, f"{BASE_IMPORTER_PREFIX}%"),
    ).fetchone()
    if row is None:
        raise ValueError(
            "P3-T02 requires import-pfquest-quests to succeed first with the same pfQuest "
            f"revision ({revision})"
        )
    return source_id


def _ensure_turtle_source(connection: sqlite3.Connection, source_path: str) -> int:
    connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind, source_url, source_path)
        VALUES (?, 'pfQuest Turtle', 'lua-addon-overlay', ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            display_name = excluded.display_name,
            source_kind = excluded.source_kind,
            source_url = excluded.source_url,
            source_path = excluded.source_path,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (PFQUEST_TURTLE_SOURCE_KEY, PFQUEST_TURTLE_SOURCE_URL, source_path),
    )
    return _source_id(connection, PFQUEST_TURTLE_SOURCE_KEY)


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


def _selection_is_managed(selection: _Selection | None) -> bool:
    if selection is None:
        return False
    if selection.source_key == PFQUEST_SOURCE_KEY:
        return selection.selection_policy in _DEFAULT_BASE_POLICIES
    return (
        selection.source_key == PFQUEST_TURTLE_SOURCE_KEY
        and selection.selection_policy == TURTLE_SELECTION_POLICY
    )


def _has_protected_selected_support(
    connection: sqlite3.Connection, *, quest_id: int
) -> bool:
    rows = connection.execute(
        """
        SELECT cs.observation_id, cs.selection_policy, ds.source_key, so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = 'quest' AND og.subject_key = ?
        """,
        (str(quest_id),),
    ).fetchall()
    for row in rows:
        selection = _Selection(
            observation_id=int(row["observation_id"]),
            source_key=str(row["source_key"]),
            selection_policy=(
                None if row["selection_policy"] is None else str(row["selection_policy"])
            ),
            value=json.loads(str(row["value_json"])),
        )
        if not _selection_is_managed(selection):
            return True
    return False


def _select_base_if_missing(connection: sqlite3.Connection, observation_id: int) -> None:
    group_id = _group_for_observation(connection, observation_id)
    if _selection_for_group(connection, group_id) is None:
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy=BASE_SET_SELECTION_POLICY,
            selection_reason=(
                "Base pfQuest complete P3 quest fact is the initial managed source-view selection."
            ),
        )


def _select_turtle_if_managed(
    connection: sqlite3.Connection,
    *,
    observation_id: int,
    quest_id: int,
    negative_presence: bool = False,
) -> None:
    group_id = _group_for_observation(connection, observation_id)
    current = _selection_for_group(connection, group_id)
    if negative_presence and _has_protected_selected_support(connection, quest_id=quest_id):
        return
    if current is not None and not _selection_is_managed(current):
        return
    select_canonical_observation(
        connection,
        observation_group_id=group_id,
        observation_id=observation_id,
        selection_policy=TURTLE_SELECTION_POLICY,
        selection_reason=(
            "The installed pfQuest-turtle effective P3 view supersedes default/base pfQuest "
            "evidence for this bounded quest identity/endpoint fact while preserving competitors."
        ),
    )


def _record_base_scalar(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    quest_id: int,
    fact_key: str,
    value: Any,
    record_type: str,
) -> int:
    observation_id = record_scalar_observation(
        connection,
        subject_kind="quest",
        subject_key=quest_id,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type=record_type,
        raw_identifier=quest_id,
    )
    _select_base_if_missing(connection, observation_id)
    return observation_id


def _record_turtle_scalar(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    quest_id: int,
    fact_key: str,
    value: Any,
    record_type: str,
    negative_presence: bool = False,
) -> int:
    observation_id = record_scalar_observation(
        connection,
        subject_kind="quest",
        subject_key=quest_id,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type=record_type,
        raw_identifier=quest_id,
    )
    _select_turtle_if_managed(
        connection,
        observation_id=observation_id,
        quest_id=quest_id,
        negative_presence=negative_presence,
    )
    return observation_id


def _selected_scalar(
    connection: sqlite3.Connection, *, quest_id: int, fact_key: str
) -> _Selection | None:
    row = connection.execute(
        """
        SELECT id
        FROM observation_groups
        WHERE subject_kind = 'quest' AND subject_key = ? AND fact_key = ?
          AND fact_kind = 'scalar' AND fact_instance_key = ''
        """,
        (str(quest_id), fact_key),
    ).fetchone()
    return None if row is None else _selection_for_group(connection, int(row["id"]))


def _record_name(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    quest_id: int,
    name: str,
    source_key: str,
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
    group_id = _group_for_observation(connection, observation_id)
    if source_key == PFQUEST_TURTLE_SOURCE_KEY:
        _select_turtle_if_managed(
            connection, observation_id=observation_id, quest_id=quest_id
        )
    elif _selection_for_group(connection, group_id) is None:
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy="first-observation",
            selection_reason="Base pfQuest quest name had no prior canonical selection.",
        )
    selection = _selection_for_group(connection, group_id)
    return name if selection is None else str(selection.value)


def _record_endpoint_relation(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    quest_id: int,
    endpoint: PfQuestEndpoint,
    source_key: str,
) -> _Selection:
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
    group_id = _group_for_observation(connection, observation_id)
    if source_key == PFQUEST_TURTLE_SOURCE_KEY:
        _select_turtle_if_managed(
            connection, observation_id=observation_id, quest_id=quest_id
        )
    elif _selection_for_group(connection, group_id) is None:
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy="first-observation",
            selection_reason="Base pfQuest quest endpoint had no prior canonical selection.",
        )
    selection = _selection_for_group(connection, group_id)
    if selection is None:
        raise RuntimeError("quest endpoint relation has no canonical selection")
    return selection


def _selected_relation(
    connection: sqlite3.Connection, *, quest_id: int, endpoint: PfQuestEndpoint
) -> _Selection | None:
    instance_key = f"{endpoint.endpoint_kind}:{endpoint.target_kind}:{endpoint.target_id}"
    row = connection.execute(
        """
        SELECT id
        FROM observation_groups
        WHERE subject_kind = 'quest' AND subject_key = ? AND fact_key = 'endpoint'
          AND fact_kind = 'relation' AND fact_instance_key = ?
        """,
        (str(quest_id), instance_key),
    ).fetchone()
    return None if row is None else _selection_for_group(connection, int(row["id"]))


def _selection_endpoint(selection: _Selection, expected: PfQuestEndpoint) -> PfQuestEndpoint:
    if not isinstance(selection.value, dict):
        raise TypeError("selected quest endpoint relation must be an object")
    target = selection.value.get("target", {})
    attributes = selection.value.get("attributes", {})
    if not isinstance(target, dict) or not isinstance(attributes, dict):
        raise TypeError("selected quest endpoint relation has invalid payload")
    if target.get("kind") != expected.target_kind or str(target.get("key")) != str(
        expected.target_id
    ):
        raise RuntimeError("selected quest endpoint target does not match relation instance")
    if attributes.get("endpoint_kind") != expected.endpoint_kind:
        raise RuntimeError("selected quest endpoint kind does not match relation instance")
    return expected


def _materialize_name(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    effective_name: str,
    source_key: str,
    batch_id: int,
) -> tuple[int, int]:
    canonical_name = _record_name(
        connection,
        batch_id=batch_id,
        quest_id=quest_id,
        name=effective_name,
        source_key=source_key,
    )
    existing = connection.execute(
        "SELECT name FROM quests WHERE quest_id = ?", (quest_id,)
    ).fetchone()
    inserted = int(existing is None)
    updated = int(existing is not None and str(existing["name"]) != canonical_name)
    connection.execute(
        """
        INSERT INTO quests(quest_id, name) VALUES (?, ?)
        ON CONFLICT(quest_id) DO UPDATE SET name = excluded.name
        """,
        (quest_id, canonical_name),
    )
    return inserted, updated


def _delete_quest_if_managed(
    connection: sqlite3.Connection, *, quest_id: int
) -> tuple[int, int]:
    existing = connection.execute(
        "SELECT 1 FROM quests WHERE quest_id = ?", (quest_id,)
    ).fetchone()
    if existing is None or _has_protected_selected_support(connection, quest_id=quest_id):
        return 0, int(existing is not None)
    endpoint_count = int(
        connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM quest_creature_endpoints WHERE quest_id = ?)
              + (SELECT COUNT(*) FROM quest_gameobject_endpoints WHERE quest_id = ?)
            """,
            (quest_id, quest_id),
        ).fetchone()[0]
    )
    connection.execute("DELETE FROM quests WHERE quest_id = ?", (quest_id,))
    return 1 + endpoint_count, 0


def _target_exists(
    connection: sqlite3.Connection, *, target_kind: str, target_id: int
) -> bool:
    table = "creatures" if target_kind == "creature" else "gameobjects"
    column = "creature_id" if target_kind == "creature" else "gameobject_id"
    return (
        connection.execute(
            f"SELECT 1 FROM {table} WHERE {column} = ?", (target_id,)
        ).fetchone()
        is not None
    )


def _materialize_endpoint(
    connection: sqlite3.Connection, *, quest_id: int, endpoint: PfQuestEndpoint
) -> int:
    table = (
        "quest_creature_endpoints"
        if endpoint.target_kind == "creature"
        else "quest_gameobject_endpoints"
    )
    column = "creature_id" if endpoint.target_kind == "creature" else "gameobject_id"
    existing = connection.execute(
        f"SELECT 1 FROM {table} WHERE quest_id = ? AND endpoint_kind = ? AND {column} = ?",
        (quest_id, endpoint.endpoint_kind, endpoint.target_id),
    ).fetchone()
    connection.execute(
        f"INSERT OR IGNORE INTO {table}(quest_id, endpoint_kind, {column}) VALUES (?, ?, ?)",
        (quest_id, endpoint.endpoint_kind, endpoint.target_id),
    )
    return int(existing is None)


def _current_endpoint_keys(
    connection: sqlite3.Connection, quest_id: int
) -> set[tuple[str, str, int]]:
    rows = connection.execute(
        """
        SELECT endpoint_kind, 'creature' AS target_kind, creature_id AS target_id
        FROM quest_creature_endpoints WHERE quest_id = ?
        UNION ALL
        SELECT endpoint_kind, 'gameobject' AS target_kind, gameobject_id AS target_id
        FROM quest_gameobject_endpoints WHERE quest_id = ?
        """,
        (quest_id, quest_id),
    ).fetchall()
    return {
        (str(row["endpoint_kind"]), str(row["target_kind"]), int(row["target_id"]))
        for row in rows
    }


def _delete_stale_endpoints(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    desired: tuple[PfQuestEndpoint, ...],
) -> tuple[int, int]:
    desired_keys = {
        (endpoint.endpoint_kind, endpoint.target_kind, endpoint.target_id) for endpoint in desired
    }
    deleted = 0
    protected = 0
    for endpoint_kind, target_kind, target_id in sorted(
        _current_endpoint_keys(connection, quest_id) - desired_keys
    ):
        endpoint = PfQuestEndpoint(endpoint_kind, target_kind, target_id)
        selection = _selected_relation(connection, quest_id=quest_id, endpoint=endpoint)
        if not _selection_is_managed(selection):
            protected += 1
            continue
        table = (
            "quest_creature_endpoints"
            if target_kind == "creature"
            else "quest_gameobject_endpoints"
        )
        column = "creature_id" if target_kind == "creature" else "gameobject_id"
        connection.execute(
            f"DELETE FROM {table} WHERE quest_id = ? AND endpoint_kind = ? AND {column} = ?",
            (quest_id, endpoint_kind, target_id),
        )
        deleted += 1
    return deleted, protected


def _sync_endpoints(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    desired: tuple[PfQuestEndpoint, ...],
    primitive_source_key: str,
    primitive_batch_id: int,
    set_selection: _Selection,
) -> tuple[int, int, list[dict[str, Any]], int]:
    inserted = 0
    unresolved: list[dict[str, Any]] = []
    use_source_evidence = _selection_is_managed(set_selection)

    for endpoint in desired:
        if use_source_evidence:
            selection = _record_endpoint_relation(
                connection,
                batch_id=primitive_batch_id,
                quest_id=quest_id,
                endpoint=endpoint,
                source_key=primitive_source_key,
            )
        else:
            selection = _selected_relation(connection, quest_id=quest_id, endpoint=endpoint)
            if selection is None:
                raise RuntimeError(
                    "protected quest endpoint set requires selected primitive relation "
                    f"quest:{quest_id} endpoint[{endpoint.endpoint_kind}:"
                    f"{endpoint.target_kind}:{endpoint.target_id}]"
                )
        _selection_endpoint(selection, endpoint)
        if not _target_exists(
            connection, target_kind=endpoint.target_kind, target_id=endpoint.target_id
        ):
            unresolved.append(
                {
                    "quest_id": quest_id,
                    "endpoint_kind": endpoint.endpoint_kind,
                    "target_kind": endpoint.target_kind,
                    "target_id": endpoint.target_id,
                    "reason": "missing_p1_target",
                }
            )
            continue
        inserted += _materialize_endpoint(connection, quest_id=quest_id, endpoint=endpoint)

    deleted, protected = _delete_stale_endpoints(
        connection, quest_id=quest_id, desired=desired
    )
    return inserted, deleted, unresolved, protected


def reconcile_pfquest_turtle_quests(
    connection: sqlite3.Connection,
    *,
    pfquest_root: str | Path,
    pfquest_turtle_root: str | Path,
    pfquest_revision: str,
    turtle_revision: str,
) -> ImportSummary:
    """Reconcile only P3 quest identity and creature/game-object endpoints."""

    base_revision = _required_text(pfquest_revision, "pfquest_revision")
    overlay_revision = _required_text(turtle_revision, "turtle_revision")
    tables = _load_effective_tables(pfquest_root, pfquest_turtle_root)

    touched_ids = sorted(
        {
            int(key)
            for table in (tables.patch_data, tables.patch_names)
            for key in table
            if isinstance(key, int) and not isinstance(key, bool)
        }
    )
    base_source_id = _require_base_quest_import(connection, base_revision)
    turtle_source_id = _ensure_turtle_source(connection, str(Path(pfquest_turtle_root)))
    base_batch_id = _create_batch(
        connection,
        source_id=base_source_id,
        revision=base_revision,
        rows_read=len(touched_ids),
        importer_version=f"{IMPORTER_VERSION}-base-evidence",
    )
    turtle_batch_id = _create_batch(
        connection,
        source_id=turtle_source_id,
        revision=overlay_revision,
        rows_read=len(touched_ids),
        importer_version=IMPORTER_VERSION,
    )

    inserted = 0
    updated = 0
    deleted = 0
    protected = 0
    unresolved: list[dict[str, Any]] = []
    inactive_endpoint_ids: list[int] = []
    added_quest_ids: list[int] = []
    removed_quest_ids: list[int] = []
    changed_name_ids: list[int] = []
    changed_endpoint_ids: list[int] = []

    try:
        for quest_id in touched_ids:
            base_name = _quest_title(tables.base_names.get(quest_id))
            effective_name = _quest_title(tables.effective_names.get(quest_id))
            base_endpoints = _endpoints_for_record(
                tables.base_data.get(quest_id), quest_id=quest_id
            )
            effective_endpoints = _endpoints_for_record(
                tables.effective_data.get(quest_id), quest_id=quest_id
            )

            if base_name is None and effective_name is not None:
                added_quest_ids.append(quest_id)
            if base_name is not None and effective_name is None:
                removed_quest_ids.append(quest_id)
            if base_name != effective_name:
                changed_name_ids.append(quest_id)
            if base_endpoints != effective_endpoints:
                changed_endpoint_ids.append(quest_id)

            _record_base_scalar(
                connection,
                batch_id=base_batch_id,
                quest_id=quest_id,
                fact_key=QUEST_PRESENCE_FACT,
                value=base_name is not None,
                record_type="quest_effective_presence",
            )
            _record_base_scalar(
                connection,
                batch_id=base_batch_id,
                quest_id=quest_id,
                fact_key=QUEST_ENDPOINT_SET_FACT,
                value=_endpoint_payload(base_endpoints),
                record_type="quest_effective_endpoint_set",
            )
            _record_turtle_scalar(
                connection,
                batch_id=turtle_batch_id,
                quest_id=quest_id,
                fact_key=QUEST_PRESENCE_FACT,
                value=effective_name is not None,
                record_type="quest_effective_presence",
                negative_presence=effective_name is None,
            )
            _record_turtle_scalar(
                connection,
                batch_id=turtle_batch_id,
                quest_id=quest_id,
                fact_key=QUEST_ENDPOINT_SET_FACT,
                value=_endpoint_payload(effective_endpoints),
                record_type="quest_effective_endpoint_set",
            )

            presence_selection = _selected_scalar(
                connection, quest_id=quest_id, fact_key=QUEST_PRESENCE_FACT
            )
            endpoint_set_selection = _selected_scalar(
                connection, quest_id=quest_id, fact_key=QUEST_ENDPOINT_SET_FACT
            )
            if presence_selection is None or endpoint_set_selection is None:
                raise RuntimeError("quest effective-view fact has no canonical selection")
            selected_present = presence_selection.value
            if not isinstance(selected_present, bool):
                raise TypeError("selected quest_presence must be boolean")
            selected_endpoints = _payload_endpoints(endpoint_set_selection.value)

            if not selected_present:
                removed_count, protected_identity = _delete_quest_if_managed(
                    connection, quest_id=quest_id
                )
                deleted += removed_count
                protected += protected_identity
                if connection.execute(
                    "SELECT 1 FROM quests WHERE quest_id = ?", (quest_id,)
                ).fetchone() is None:
                    if selected_endpoints:
                        inactive_endpoint_ids.append(quest_id)
                    continue

            selected_name = _selected_scalar(connection, quest_id=quest_id, fact_key="name")
            if effective_name is not None:
                if quest_id in tables.patch_names and tables.patch_names.get(quest_id) != "_":
                    name_source_key = PFQUEST_TURTLE_SOURCE_KEY
                    name_batch_id = turtle_batch_id
                else:
                    name_source_key = PFQUEST_SOURCE_KEY
                    name_batch_id = base_batch_id
                name_inserted, name_updated = _materialize_name(
                    connection,
                    quest_id=quest_id,
                    effective_name=effective_name,
                    source_key=name_source_key,
                    batch_id=name_batch_id,
                )
                inserted += name_inserted
                updated += name_updated
            elif selected_name is None:
                # Protected presence may retain an existing quest, but cannot create a nameless one.
                if connection.execute(
                    "SELECT 1 FROM quests WHERE quest_id = ?", (quest_id,)
                ).fetchone() is None:
                    inactive_endpoint_ids.append(quest_id)
                    continue

            if connection.execute(
                "SELECT 1 FROM quests WHERE quest_id = ?", (quest_id,)
            ).fetchone() is None:
                inactive_endpoint_ids.append(quest_id)
                continue

            data_is_turtle = (
                quest_id in tables.patch_data and tables.patch_data.get(quest_id) != "_"
            )
            primitive_source_key = (
                PFQUEST_TURTLE_SOURCE_KEY if data_is_turtle else PFQUEST_SOURCE_KEY
            )
            primitive_batch_id = turtle_batch_id if data_is_turtle else base_batch_id
            relation_inserted, relation_deleted, relation_unresolved, relation_protected = (
                _sync_endpoints(
                    connection,
                    quest_id=quest_id,
                    desired=selected_endpoints,
                    primitive_source_key=primitive_source_key,
                    primitive_batch_id=primitive_batch_id,
                    set_selection=endpoint_set_selection,
                )
            )
            inserted += relation_inserted
            deleted += relation_deleted
            unresolved.extend(relation_unresolved)
            protected += relation_protected

        unresolved.sort(
            key=lambda issue: (
                int(issue["quest_id"]),
                str(issue["endpoint_kind"]),
                str(issue["target_kind"]),
                int(issue["target_id"]),
            )
        )
        details = {
            "base_revision": base_revision,
            "turtle_revision": overlay_revision,
            "touched_quest_ids": touched_ids,
            "added_quest_ids": added_quest_ids,
            "removed_quest_ids": removed_quest_ids,
            "changed_name_ids": changed_name_ids,
            "changed_endpoint_ids": changed_endpoint_ids,
            "inactive_endpoint_quest_ids": sorted(set(inactive_endpoint_ids)),
            "unresolved_endpoints": unresolved,
            "canonical_relations_or_identities_deleted": deleted,
            "protected_canonical_rows_retained": protected,
        }
        warning_count = len(unresolved) + len(set(inactive_endpoint_ids))
        _finish_batch(
            connection,
            batch_id=base_batch_id,
            rows_read=len(touched_ids),
            rows_inserted=0,
            rows_updated=0,
            warning_count=0,
            details={
                "role": "base-complete-set-evidence",
                "touched_quest_ids": touched_ids,
            },
        )
        _finish_batch(
            connection,
            batch_id=turtle_batch_id,
            rows_read=len(touched_ids),
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
        source_revision=overlay_revision,
        status="succeeded",
        rows_read=len(touched_ids),
        rows_accepted=len(touched_ids),
        rows_skipped=0,
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=warning_count,
        error_count=0,
        details=details,
    )
