"""Reconcile P2 item acquisition against the effective pfQuest + Turtle view.

pfQuest-turtle patches the same tables used by the P2 pfQuest item importer at
*top-entry* granularity: ``"_"`` removes an entry and every other patch value
replaces the corresponding base entry wholesale.  This module reproduces that
bounded composition without executing Lua, records the Turtle evidence under a
separate source identity, and reconciles only the P2 facts currently supported
by OctoGameDB: item names, direct U/O loot, one-level R reference loot, and V
vendor acquisition.

The complete-set facts introduced here are deliberately P2-specific.  They do
not generalize the P1 world ``spawn_set`` policy to arbitrary future domains.
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
from octogamedb.importers.pfquest_items import (
    PfQuestItemImportError,
    _numeric_links,
    _numeric_memberships,
    _numeric_vendor_links,
    _parse_reference_definition,
)
from octogamedb.importers.pfquest_world import (
    PFQUEST_SOURCE_KEY,
    PfQuestParseError,
    _LuaLiteralParser,
    parse_pfquest_assignment,
)
from octogamedb.importers.summary import ImportSummary

IMPORTER_VERSION = "pfquest-item-overlay-reconcile/1"
PFQUEST_TURTLE_SOURCE_KEY = "pfquest-turtle"
PFQUEST_TURTLE_SOURCE_URL = "https://github.com/KameleonUK/pfQuest-turtle"
TURTLE_SELECTION_POLICY = "pfquest-turtle-effective-items"
BASE_SET_SELECTION_POLICY = "pfquest-base-effective-items"
ITEM_PRESENCE_FACT = "item_presence"
ITEM_ACQUISITION_SET_FACT = "item_acquisition_set"
REFERENCE_PRESENCE_FACT = "loot_reference_presence"
REFERENCE_MEMBER_SET_FACT = "loot_reference_member_set"

_MANAGED_SOURCE_KEYS = frozenset({PFQUEST_SOURCE_KEY, PFQUEST_TURTLE_SOURCE_KEY})
_DEFAULT_BASE_POLICIES = frozenset({None, "first-observation", BASE_SET_SELECTION_POLICY})

_BASE_FILES = {
    ("items", "data"): "db/items.lua",
    ("refloot", "data"): "db/refloot.lua",
    ("items", "enUS"): "db/enUS/items.lua",
    ("units", "enUS"): "db/enUS/units.lua",
    ("objects", "enUS"): "db/enUS/objects.lua",
}
_OVERLAY_FILES = {
    ("items", "data-turtle"): "db/items-turtle.lua",
    ("refloot", "data-turtle"): "db/refloot-turtle.lua",
    ("items", "enUS-turtle"): "db/enUS/items-turtle.lua",
    ("units", "enUS-turtle"): "db/enUS/units-turtle.lua",
    ("objects", "enUS-turtle"): "db/enUS/objects-turtle.lua",
}
_OVERLAY_REVISION_FILES = (
    "pfQuest-turtle.toc",
    "init/data-turtle.xml",
    "init/enUS-turtle.xml",
    "db/items-turtle.lua",
    "db/refloot-turtle.lua",
    "db/enUS/items-turtle.lua",
    "db/enUS/units-turtle.lua",
    "db/enUS/objects-turtle.lua",
    "overwrites.lua",
    "patchtable.lua",
)


@dataclass(frozen=True)
class _Selection:
    observation_id: int
    source_key: str
    selection_policy: str | None
    value: Any


@dataclass(frozen=True)
class _EffectiveTables:
    base: dict[tuple[str, str], dict[Any, Any]]
    patch: dict[tuple[str, str], dict[Any, Any]]
    effective: dict[tuple[str, str], dict[Any, Any]]


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


def _read_assignment(path: Path, domain: str, table_name: str) -> dict[Any, Any]:
    return parse_pfquest_assignment(
        path.read_text(encoding="utf-8"),
        domain=domain,
        table_name=table_name,
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
    root: dict[Any, Any],
    *,
    keys: list[Any],
    value: Any,
    label: str,
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
    for (domain, table_name), patch in tuple(patches.items()):
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
                    f"unsupported indirect P2 table mutation for {domain}.{table_name}"
                ) from exc
            value = parser.parse_value()
            patches[(domain, table_name)] = _apply_nested_assignment(
                patch,
                keys=keys,
                value=value,
                label=f"{domain}.{table_name}",
            )
            patch = patches[(domain, table_name)]


def _validate_no_unhandled_item_mutations(text: str) -> None:
    """Fail closed for indirect mutations of any bounded P2 overlay input table."""

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
        # Mentions of unrelated world/quest tables are deliberately outside this bounded adapter.
        # A runtime alias/loop/function mutation of a P2 input would require Lua semantics we do
        # not infer.
        raise PfQuestParseError(
            f"unsupported indirect P2 overlay mutation on overwrites.lua line {line_number}"
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
        raise FileNotFoundError(f"missing required pfQuest-turtle P2 file: {root / missing[0]}")

    toc = (root / "pfQuest-turtle.toc").read_text(encoding="utf-8")
    _require_order(
        toc.replace("/", "\\"),
        ("init\\data-turtle.xml", "init\\enUS-turtle.xml", "overwrites.lua", "patchtable.lua"),
        "pfQuest-turtle toc",
    )
    data_xml = (root / "init" / "data-turtle.xml").read_text(encoding="utf-8")
    for marker in ("items-turtle.lua", "refloot-turtle.lua"):
        if marker not in data_xml:
            raise PfQuestParseError(f"unsupported Turtle P2 data layout: {marker} is not loaded")
    enus_xml = (root / "init" / "enUS-turtle.xml").read_text(encoding="utf-8")
    for marker in ("items-turtle.lua", "units-turtle.lua", "objects-turtle.lua"):
        if marker not in enus_xml:
            raise PfQuestParseError(f"unsupported Turtle P2 enUS layout: {marker} is not loaded")

    patchtable = (root / "patchtable.lua").read_text(encoding="utf-8")
    required_markers = (
        '"items"',
        '"refloot"',
        'pfDB[db]["data-turtle"]',
        'base[k] = nil',
        'base[k] = v',
    )
    if any(marker not in patchtable for marker in required_markers):
        raise PfQuestParseError("unsupported pfQuest-turtle patchtable semantics")
    return root


def compute_pfquest_turtle_items_revision(source_root: str | Path) -> str:
    """Hash the exact supported Turtle P2 composition inputs."""

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
) -> _EffectiveTables:
    base_root = Path(pfquest_root)
    overlay_root = _validate_turtle_layout(pfquest_turtle_root)

    base: dict[tuple[str, str], dict[Any, Any]] = {}
    for (domain, table_name), relative in _BASE_FILES.items():
        path = base_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"missing required pfQuest P2 file: {path}")
        base[(domain, table_name)] = _read_assignment(path, domain, table_name)

    patch: dict[tuple[str, str], dict[Any, Any]] = {}
    for (domain, table_name), relative in _OVERLAY_FILES.items():
        path = overlay_root / relative
        patch[(domain, table_name)] = _read_assignment(path, domain, table_name)

    overwrite_text = (overlay_root / "overwrites.lua").read_text(encoding="utf-8")
    _apply_direct_overwrites(patch, overwrite_text)
    _validate_no_unhandled_item_mutations(overwrite_text)

    effective = {
        ("items", "data"): _patch_table(
            base[("items", "data")], patch[("items", "data-turtle")]
        ),
        ("refloot", "data"): _patch_table(
            base[("refloot", "data")], patch[("refloot", "data-turtle")]
        ),
        ("items", "enUS"): _patch_table(
            base[("items", "enUS")], patch[("items", "enUS-turtle")]
        ),
        ("units", "enUS"): _patch_table(
            base[("units", "enUS")], patch[("units", "enUS-turtle")]
        ),
        ("objects", "enUS"): _patch_table(
            base[("objects", "enUS")], patch[("objects", "enUS-turtle")]
        ),
    }
    return _EffectiveTables(base=base, patch=patch, effective=effective)


def _valid_name(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _item_acquisition_payload(record: Any, *, label: str) -> list[dict[str, Any]]:
    if record is None:
        return []
    if not isinstance(record, dict):
        raise PfQuestParseError(f"{label} must be a Lua table")

    payload: list[dict[str, Any]] = []
    for source_id, chance in _numeric_links(record.get("U"), label=f"{label}.U"):
        payload.append(
            {
                "path_kind": "direct",
                "source_kind": "creature",
                "source_id": source_id,
                "chance_percent": chance,
            }
        )
    for source_id, chance in _numeric_links(record.get("O"), label=f"{label}.O"):
        payload.append(
            {
                "path_kind": "direct",
                "source_kind": "gameobject",
                "source_id": source_id,
                "chance_percent": chance,
            }
        )
    for reference_id, chance in _numeric_links(record.get("R"), label=f"{label}.R"):
        payload.append(
            {
                "path_kind": "reference",
                "reference_loot_id": reference_id,
                "chance_percent": chance,
            }
        )
    for vendor_id, max_count in _numeric_vendor_links(record.get("V"), label=f"{label}.V"):
        payload.append(
            {
                "path_kind": "vendor",
                "source_kind": "creature",
                "source_id": vendor_id,
                "max_count": max_count,
            }
        )
    return sorted(payload, key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))


def _reference_member_payload(record: Any, *, reference_id: int) -> list[dict[str, Any]]:
    if record is None:
        return []
    definition = _parse_reference_definition(reference_id, record)
    payload = [
        {
            "source_kind": "creature",
            "source_id": source_id,
            "membership_value": marker,
        }
        for source_id, marker in definition.creature_memberships
    ]
    payload.extend(
        {
            "source_kind": "gameobject",
            "source_id": source_id,
            "membership_value": marker,
        }
        for source_id, marker in definition.gameobject_memberships
    )
    return sorted(payload, key=lambda row: (str(row["source_kind"]), int(row["source_id"])))


def _supported_counts(tables: dict[tuple[str, str], dict[Any, Any]]) -> dict[str, int]:
    item_data = tables[("items", "data")]
    item_names = tables[("items", "enUS")]
    refloot = tables[("refloot", "data")]
    counts = {
        "named_items": sum(1 for key, value in item_names.items() if isinstance(key, int) and _valid_name(value)),
        "creature_loot_links": 0,
        "gameobject_loot_links": 0,
        "reference_loot_links": 0,
        "vendor_links": 0,
        "reference_definitions": 0,
        "reference_creature_memberships": 0,
        "reference_gameobject_memberships": 0,
    }
    for item_id, record in item_data.items():
        if not isinstance(item_id, int) or not isinstance(record, dict):
            continue
        counts["creature_loot_links"] += len(_numeric_links(record.get("U"), label=f"item[{item_id}].U"))
        counts["gameobject_loot_links"] += len(_numeric_links(record.get("O"), label=f"item[{item_id}].O"))
        counts["reference_loot_links"] += len(_numeric_links(record.get("R"), label=f"item[{item_id}].R"))
        counts["vendor_links"] += len(_numeric_vendor_links(record.get("V"), label=f"item[{item_id}].V"))
    for reference_id, record in refloot.items():
        if not isinstance(reference_id, int) or not isinstance(record, dict):
            continue
        counts["reference_definitions"] += 1
        counts["reference_creature_memberships"] += len(
            _numeric_memberships(record.get("U"), label=f"refloot[{reference_id}].U")
        )
        counts["reference_gameobject_memberships"] += len(
            _numeric_memberships(record.get("O"), label=f"refloot[{reference_id}].O")
        )
    return counts


def _source_id(connection: sqlite3.Connection, source_key: str) -> int:
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (source_key,)
    ).fetchone()
    if row is None:
        raise ValueError(f"required source has not been imported: {source_key}")
    return int(row["id"])


def _require_base_item_import(connection: sqlite3.Connection, revision: str) -> int:
    source_id = _source_id(connection, PFQUEST_SOURCE_KEY)
    row = connection.execute(
        """
        SELECT id
        FROM import_batches
        WHERE source_id = ?
          AND COALESCE(source_revision, '') = ?
          AND status = 'succeeded'
          AND importer_version LIKE 'pfquest-items/%'
        ORDER BY id DESC
        LIMIT 1
        """,
        (source_id, revision),
    ).fetchone()
    if row is None:
        raise ValueError(
            "P2-T04 requires import-pfquest-items to succeed first with the same pfQuest "
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
            rows_read = ?, rows_accepted = ?, rows_inserted = ?, rows_updated = ?,
            warning_count = ?, details_json = ?
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


def _has_protected_selected_support(
    connection: sqlite3.Connection, *, subject_kind: str, subject_key: int | str
) -> bool:
    """Return whether any selected fact on the identity uses a non-managed policy/source.

    Protection is policy-aware, not only source-key-aware. A deliberate/custom selection recorded
    under the ``pfquest`` source key is still external to the replaceable managed base policy and
    must retain the identity just like a selection from another source.
    """

    rows = connection.execute(
        """
        SELECT cs.observation_id, cs.selection_policy, ds.source_key, so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = ? AND og.subject_key = ?
        """,
        (subject_kind, str(subject_key)),
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
            selection_reason="Base pfQuest complete P2 set is the initial managed source-view selection.",
        )


def _selection_is_managed(selection: _Selection | None) -> bool:
    """Return whether a selection belongs to the replaceable pfQuest-family policy."""

    if selection is None:
        return False
    if selection.source_key == PFQUEST_SOURCE_KEY:
        return selection.selection_policy in _DEFAULT_BASE_POLICIES
    return (
        selection.source_key == PFQUEST_TURTLE_SOURCE_KEY
        and selection.selection_policy == TURTLE_SELECTION_POLICY
    )


def _selected_scalar(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: int | str,
    fact_key: str,
) -> _Selection | None:
    row = connection.execute(
        """
        SELECT og.id
        FROM observation_groups AS og
        WHERE og.subject_kind = ? AND og.subject_key = ? AND og.fact_key = ?
          AND og.fact_kind = 'scalar' AND og.fact_instance_key = ''
        """,
        (subject_kind, str(subject_key), fact_key),
    ).fetchone()
    return None if row is None else _selection_for_group(connection, int(row["id"]))


def _should_select_turtle(
    connection: sqlite3.Connection,
    *,
    observation_id: int,
    subject_kind: str,
    subject_key: int | str,
    negative_presence: bool = False,
) -> bool:
    group_id = _group_for_observation(connection, observation_id)
    current = _selection_for_group(connection, group_id)
    if negative_presence and _has_protected_selected_support(
        connection, subject_kind=subject_kind, subject_key=subject_key
    ):
        return False
    if current is None:
        return True
    return _selection_is_managed(current)


def _select_turtle_if_managed(
    connection: sqlite3.Connection,
    *,
    observation_id: int,
    subject_kind: str,
    subject_key: int | str,
    negative_presence: bool = False,
) -> None:
    if not _should_select_turtle(
        connection,
        observation_id=observation_id,
        subject_kind=subject_kind,
        subject_key=subject_key,
        negative_presence=negative_presence,
    ):
        return
    select_canonical_observation(
        connection,
        observation_group_id=_group_for_observation(connection, observation_id),
        observation_id=observation_id,
        selection_policy=TURTLE_SELECTION_POLICY,
        selection_reason=(
            "The installed pfQuest-turtle effective P2 view supersedes default/base pfQuest "
            "evidence for this bounded item/acquisition fact while preserving competitors."
        ),
    )


def _record_base_scalar(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: int | str,
    fact_key: str,
    value: Any,
    record_type: str,
) -> int:
    observation_id = record_scalar_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type=record_type,
        raw_identifier=subject_key,
    )
    _select_base_if_missing(connection, observation_id)
    return observation_id


def _record_turtle_scalar(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: int | str,
    fact_key: str,
    value: Any,
    record_type: str,
    negative_presence: bool = False,
) -> int:
    observation_id = record_scalar_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type=record_type,
        raw_identifier=subject_key,
    )
    _select_turtle_if_managed(
        connection,
        observation_id=observation_id,
        subject_kind=subject_kind,
        subject_key=subject_key,
        negative_presence=negative_presence,
    )
    return observation_id


def _record_source_name(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    source_key: str,
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
        raw_identifier=subject_id,
    )
    if source_key == PFQUEST_TURTLE_SOURCE_KEY:
        _select_turtle_if_managed(
            connection,
            observation_id=observation_id,
            subject_kind=subject_kind,
            subject_key=subject_id,
        )
    else:
        group_id = _group_for_observation(connection, observation_id)
        if _selection_for_group(connection, group_id) is None:
            select_canonical_observation(
                connection,
                observation_group_id=group_id,
                observation_id=observation_id,
                selection_policy="first-observation",
                selection_reason="Source identity had no prior canonical selection.",
            )
    selection = _selection_for_group(connection, _group_for_observation(connection, observation_id))
    if selection is None:
        return name
    return str(selection.value)


def _record_turtle_relation(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    target_kind: str,
    target_key: int,
    relation_instance_key: str,
    attributes: dict[str, Any],
    record_type: str,
    raw_identifier: str,
) -> _Selection:
    observation_id = record_relation_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        target_kind=target_kind,
        target_key=target_key,
        relation_instance_key=relation_instance_key,
        attributes=attributes,
        source_record_type=record_type,
        raw_identifier=raw_identifier,
    )
    _select_turtle_if_managed(
        connection,
        observation_id=observation_id,
        subject_kind=subject_kind,
        subject_key=subject_key,
    )
    selection = _selection_for_group(connection, _group_for_observation(connection, observation_id))
    if selection is None:
        raise RuntimeError("relation observation has no canonical selection after reconciliation")
    return selection


def _record_base_relation(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    target_kind: str,
    target_key: int,
    relation_instance_key: str,
    attributes: dict[str, Any],
    record_type: str,
    raw_identifier: str,
) -> _Selection:
    observation_id = record_relation_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        target_kind=target_kind,
        target_key=target_key,
        relation_instance_key=relation_instance_key,
        attributes=attributes,
        source_record_type=record_type,
        raw_identifier=raw_identifier,
    )
    group_id = _group_for_observation(connection, observation_id)
    if _selection_for_group(connection, group_id) is None:
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy="first-observation",
            selection_reason="Base pfQuest relation had no prior canonical selection.",
        )
    selection = _selection_for_group(connection, group_id)
    if selection is None:
        raise RuntimeError("base relation observation has no canonical selection")
    return selection


def _selected_relation(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    instance_key: str,
) -> _Selection | None:
    row = connection.execute(
        """
        SELECT og.id
        FROM observation_groups AS og
        WHERE og.subject_kind = ? AND og.subject_key = ? AND og.fact_key = ?
          AND og.fact_kind = 'relation' AND og.fact_instance_key = ?
        """,
        (subject_kind, str(subject_key), fact_key, instance_key),
    ).fetchone()
    return None if row is None else _selection_for_group(connection, int(row["id"]))


def _selected_relation_is_managed(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    instance_key: str,
) -> bool:
    return _selection_is_managed(
        _selected_relation(
            connection,
            subject_kind=subject_kind,
            subject_key=subject_key,
            fact_key=fact_key,
            instance_key=instance_key,
        )
    )


def _selection_attributes(selection: _Selection, expected_kind: str, expected_key: int) -> dict[str, Any]:
    if not isinstance(selection.value, dict):
        raise TypeError("selected relation payload must be an object")
    target = selection.value.get("target", {})
    if target.get("kind") != expected_kind or str(target.get("key")) != str(expected_key):
        raise RuntimeError("selected relation target does not match its relation instance")
    attributes = selection.value.get("attributes", {})
    if not isinstance(attributes, dict):
        raise TypeError("selected relation attributes must be an object")
    return attributes


def _row_changed(row: sqlite3.Row | None, expected: dict[str, Any]) -> bool:
    return row is not None and any(row[key] != value for key, value in expected.items())


def _ensure_target_identity(
    connection: sqlite3.Connection,
    *,
    source_kind: str,
    source_id: int,
    effective_names: dict[Any, Any],
    turtle_name_patch: dict[Any, Any],
    base_batch_id: int,
    turtle_batch_id: int,
    fatal: bool,
) -> tuple[bool, bool]:
    table = "creatures" if source_kind == "creature" else "gameobjects"
    id_column = "creature_id" if source_kind == "creature" else "gameobject_id"
    existing = connection.execute(
        f"SELECT name FROM {table} WHERE {id_column} = ?", (source_id,)
    ).fetchone()
    name = _valid_name(effective_names.get(source_id))
    if existing is None and name is None:
        if fatal:
            raise PfQuestItemImportError(
                f"effective Turtle acquisition target {source_kind}:{source_id} has no canonical "
                "P1 identity and no effective enUS identity"
            )
        return False, False

    inserted = False
    updated = False
    if name is not None and (existing is None or source_id in turtle_name_patch):
        name_source = (
            PFQUEST_TURTLE_SOURCE_KEY if source_id in turtle_name_patch else PFQUEST_SOURCE_KEY
        )
        canonical_name = _record_source_name(
            connection,
            batch_id=turtle_batch_id if name_source == PFQUEST_TURTLE_SOURCE_KEY else base_batch_id,
            source_key=name_source,
            subject_kind=source_kind,
            subject_id=source_id,
            name=name,
        )
        if existing is None:
            connection.execute(
                f"INSERT INTO {table}({id_column}, name) VALUES (?, ?)",
                (source_id, canonical_name),
            )
            inserted = True
        elif str(existing["name"]) != canonical_name:
            connection.execute(
                f"UPDATE {table} SET name = ? WHERE {id_column} = ?",
                (canonical_name, source_id),
            )
            updated = True
    return inserted, updated


def _upsert_item_name(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    name: str,
    turtle_batch_id: int,
) -> tuple[int, int]:
    observation_id = record_scalar_observation(
        connection,
        subject_kind="item",
        subject_key=item_id,
        fact_key="name",
        import_batch_id=turtle_batch_id,
        value=name,
        source_record_type="item",
        raw_identifier=item_id,
    )
    _select_turtle_if_managed(
        connection,
        observation_id=observation_id,
        subject_kind="item",
        subject_key=item_id,
    )
    selection = _selection_for_group(connection, _group_for_observation(connection, observation_id))
    canonical_name = name if selection is None else str(selection.value)
    existing = connection.execute("SELECT name FROM items WHERE item_id = ?", (item_id,)).fetchone()
    inserted = int(existing is None)
    updated = int(existing is not None and str(existing["name"]) != canonical_name)
    connection.execute(
        """
        INSERT INTO items(item_id, name) VALUES (?, ?)
        ON CONFLICT(item_id) DO UPDATE SET name = excluded.name
        """,
        (item_id, canonical_name),
    )
    return inserted, updated


def _sync_item_relations(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    desired: list[dict[str, Any]],
    turtle_batch_id: int,
    use_turtle_evidence: bool,
) -> tuple[int, int, int, int]:
    inserted = updated = deleted = protected = 0
    desired_keys: set[tuple[str, int]] = set()

    for row in desired:
        path_kind = str(row["path_kind"])
        if path_kind == "direct":
            source_kind = str(row["source_kind"])
            source_id = int(row["source_id"])
            key = (f"direct:{source_kind}", source_id)
            desired_keys.add(key)
            if use_turtle_evidence:
                selection = _record_turtle_relation(
                    connection,
                    batch_id=turtle_batch_id,
                    subject_kind="item",
                    subject_key=item_id,
                    fact_key="loot_source",
                    target_kind=source_kind,
                    target_key=source_id,
                    relation_instance_key=f"{source_kind}:{source_id}",
                    attributes={"chance_percent": float(row["chance_percent"])},
                    record_type="item",
                    raw_identifier=f"{item_id}:{source_kind}:{source_id}",
                )
            else:
                selection = _selected_relation(
                    connection,
                    subject_kind="item",
                    subject_key=item_id,
                    fact_key="loot_source",
                    instance_key=f"{source_kind}:{source_id}",
                )
                if selection is None:
                    raise RuntimeError(
                        "protected item acquisition set requires selected primitive relation "
                        f"item:{item_id} loot_source[{source_kind}:{source_id}]"
                    )
            attrs = _selection_attributes(selection, source_kind, source_id)
            chance = attrs.get("chance_percent")
            if isinstance(chance, bool) or not isinstance(chance, (int, float)):
                raise TypeError("selected direct loot relation has no numeric chance_percent")
            table = "creature_loot" if source_kind == "creature" else "gameobject_loot"
            source_column = "creature_id" if source_kind == "creature" else "gameobject_id"
            existing = connection.execute(
                f"SELECT chance_percent FROM {table} WHERE {source_column} = ? AND item_id = ?",
                (source_id, item_id),
            ).fetchone()
            inserted += int(existing is None)
            updated += int(_row_changed(existing, {"chance_percent": float(chance)}))
            connection.execute(
                f"""
                INSERT INTO {table}({source_column}, item_id, chance_percent) VALUES (?, ?, ?)
                ON CONFLICT({source_column}, item_id) DO UPDATE SET chance_percent=excluded.chance_percent
                """,
                (source_id, item_id, float(chance)),
            )
        elif path_kind == "reference":
            reference_id = int(row["reference_loot_id"])
            desired_keys.add(("reference", reference_id))
            connection.execute(
                "INSERT OR IGNORE INTO loot_references(reference_loot_id) VALUES (?)", (reference_id,)
            )
            if use_turtle_evidence:
                selection = _record_turtle_relation(
                    connection,
                    batch_id=turtle_batch_id,
                    subject_kind="item",
                    subject_key=item_id,
                    fact_key="loot_reference",
                    target_kind="loot_reference",
                    target_key=reference_id,
                    relation_instance_key=f"reference:{reference_id}",
                    attributes={"chance_percent": float(row["chance_percent"])},
                    record_type="item_reference_loot",
                    raw_identifier=f"{item_id}:R:{reference_id}",
                )
            else:
                selection = _selected_relation(
                    connection,
                    subject_kind="item",
                    subject_key=item_id,
                    fact_key="loot_reference",
                    instance_key=f"reference:{reference_id}",
                )
                if selection is None:
                    raise RuntimeError(
                        "protected item acquisition set requires selected primitive relation "
                        f"item:{item_id} loot_reference[reference:{reference_id}]"
                    )
            attrs = _selection_attributes(selection, "loot_reference", reference_id)
            chance = attrs.get("chance_percent")
            if isinstance(chance, bool) or not isinstance(chance, (int, float)):
                raise TypeError("selected reference relation has no numeric chance_percent")
            existing = connection.execute(
                "SELECT chance_percent FROM item_reference_loot WHERE item_id = ? AND reference_loot_id = ?",
                (item_id, reference_id),
            ).fetchone()
            inserted += int(existing is None)
            updated += int(_row_changed(existing, {"chance_percent": float(chance)}))
            connection.execute(
                """
                INSERT INTO item_reference_loot(item_id, reference_loot_id, chance_percent)
                VALUES (?, ?, ?)
                ON CONFLICT(item_id, reference_loot_id) DO UPDATE SET chance_percent=excluded.chance_percent
                """,
                (item_id, reference_id, float(chance)),
            )
        elif path_kind == "vendor":
            vendor_id = int(row["source_id"])
            desired_keys.add(("vendor", vendor_id))
            if use_turtle_evidence:
                _record_turtle_relation(
                    connection,
                    batch_id=turtle_batch_id,
                    subject_kind="item",
                    subject_key=item_id,
                    fact_key="vendor_source",
                    target_kind="creature",
                    target_key=vendor_id,
                    relation_instance_key=f"creature:{vendor_id}",
                    attributes={"max_count": int(row["max_count"])},
                    record_type="item_vendor",
                    raw_identifier=f"{item_id}:V:{vendor_id}",
                )
            elif _selected_relation(
                connection,
                subject_kind="item",
                subject_key=item_id,
                fact_key="vendor_source",
                instance_key=f"creature:{vendor_id}",
            ) is None:
                raise RuntimeError(
                    "protected item acquisition set requires selected primitive relation "
                    f"item:{item_id} vendor_source[creature:{vendor_id}]"
                )
            existing = connection.execute(
                "SELECT 1 FROM vendor_items WHERE vendor_creature_id = ? AND item_id = ?",
                (vendor_id, item_id),
            ).fetchone()
            connection.execute(
                "INSERT OR IGNORE INTO vendor_items(vendor_creature_id, item_id) VALUES (?, ?)",
                (vendor_id, item_id),
            )
            inserted += int(existing is None)
        else:
            raise RuntimeError(f"unsupported acquisition path kind: {path_kind}")

    stale: list[tuple[str, int, str, str, str]] = []
    for row in connection.execute(
        "SELECT creature_id FROM creature_loot WHERE item_id = ?", (item_id,)
    ).fetchall():
        source_id = int(row["creature_id"])
        if ("direct:creature", source_id) not in desired_keys:
            stale.append(("creature_loot", source_id, "loot_source", f"creature:{source_id}", "creature_id"))
    for row in connection.execute(
        "SELECT gameobject_id FROM gameobject_loot WHERE item_id = ?", (item_id,)
    ).fetchall():
        source_id = int(row["gameobject_id"])
        if ("direct:gameobject", source_id) not in desired_keys:
            stale.append(("gameobject_loot", source_id, "loot_source", f"gameobject:{source_id}", "gameobject_id"))
    for row in connection.execute(
        "SELECT reference_loot_id FROM item_reference_loot WHERE item_id = ?", (item_id,)
    ).fetchall():
        reference_id = int(row["reference_loot_id"])
        if ("reference", reference_id) not in desired_keys:
            stale.append(("item_reference_loot", reference_id, "loot_reference", f"reference:{reference_id}", "reference_loot_id"))
    for row in connection.execute(
        "SELECT vendor_creature_id FROM vendor_items WHERE item_id = ?", (item_id,)
    ).fetchall():
        vendor_id = int(row["vendor_creature_id"])
        if ("vendor", vendor_id) not in desired_keys:
            stale.append(("vendor_items", vendor_id, "vendor_source", f"creature:{vendor_id}", "vendor_creature_id"))

    for table, target_id, fact_key, instance_key, target_column in stale:
        if not _selected_relation_is_managed(
            connection,
            subject_kind="item",
            subject_key=item_id,
            fact_key=fact_key,
            instance_key=instance_key,
        ):
            protected += 1
            continue
        connection.execute(
            f"DELETE FROM {table} WHERE item_id = ? AND {target_column} = ?", (item_id, target_id)
        )
        deleted += 1
    return inserted, updated, deleted, protected


def _sync_reference_members(
    connection: sqlite3.Connection,
    *,
    reference_id: int,
    desired: list[dict[str, Any]],
    source_key: str,
    batch_id: int,
    record_turtle_evidence: bool,
) -> tuple[int, int, int]:
    inserted = deleted = protected = 0
    desired_keys = {(str(row["source_kind"]), int(row["source_id"])) for row in desired}

    for row in desired:
        kind = str(row["source_kind"])
        source_id = int(row["source_id"])
        marker = float(row["membership_value"])
        if source_key == PFQUEST_TURTLE_SOURCE_KEY and record_turtle_evidence:
            _record_turtle_relation(
                connection,
                batch_id=batch_id,
                subject_kind="loot_reference",
                subject_key=reference_id,
                fact_key="loot_source_member",
                target_kind=kind,
                target_key=source_id,
                relation_instance_key=f"{kind}:{source_id}",
                attributes={"membership_value": marker},
                record_type="refloot",
                raw_identifier=f"{reference_id}:{kind}:{source_id}",
            )
        elif source_key == PFQUEST_TURTLE_SOURCE_KEY:
            if _selected_relation(
                connection,
                subject_kind="loot_reference",
                subject_key=reference_id,
                fact_key="loot_source_member",
                instance_key=f"{kind}:{source_id}",
            ) is None:
                raise RuntimeError(
                    "protected reference member set requires selected primitive relation "
                    f"loot_reference:{reference_id} member[{kind}:{source_id}]"
                )
        else:
            _record_base_relation(
                connection,
                batch_id=batch_id,
                subject_kind="loot_reference",
                subject_key=reference_id,
                fact_key="loot_source_member",
                target_kind=kind,
                target_key=source_id,
                relation_instance_key=f"{kind}:{source_id}",
                attributes={"membership_value": marker},
                record_type="refloot",
                raw_identifier=f"{reference_id}:{kind}:{source_id}",
            )
        table = "reference_loot_creatures" if kind == "creature" else "reference_loot_gameobjects"
        id_column = "creature_id" if kind == "creature" else "gameobject_id"
        existing = connection.execute(
            f"SELECT 1 FROM {table} WHERE reference_loot_id = ? AND {id_column} = ?",
            (reference_id, source_id),
        ).fetchone()
        connection.execute(
            f"INSERT OR IGNORE INTO {table}(reference_loot_id, {id_column}) VALUES (?, ?)",
            (reference_id, source_id),
        )
        inserted += int(existing is None)

    if source_key != PFQUEST_TURTLE_SOURCE_KEY:
        return inserted, deleted, protected

    stale: list[tuple[str, int, str, str]] = []
    for row in connection.execute(
        "SELECT creature_id FROM reference_loot_creatures WHERE reference_loot_id = ?",
        (reference_id,),
    ).fetchall():
        source_id = int(row["creature_id"])
        if ("creature", source_id) not in desired_keys:
            stale.append(("reference_loot_creatures", source_id, "creature", "creature_id"))
    for row in connection.execute(
        "SELECT gameobject_id FROM reference_loot_gameobjects WHERE reference_loot_id = ?",
        (reference_id,),
    ).fetchall():
        source_id = int(row["gameobject_id"])
        if ("gameobject", source_id) not in desired_keys:
            stale.append(("reference_loot_gameobjects", source_id, "gameobject", "gameobject_id"))

    for table, source_id, kind, id_column in stale:
        if not _selected_relation_is_managed(
            connection,
            subject_kind="loot_reference",
            subject_key=reference_id,
            fact_key="loot_source_member",
            instance_key=f"{kind}:{source_id}",
        ):
            protected += 1
            continue
        connection.execute(
            f"DELETE FROM {table} WHERE reference_loot_id = ? AND {id_column} = ?",
            (reference_id, source_id),
        )
        deleted += 1
    return inserted, deleted, protected


def reconcile_pfquest_turtle_items(
    connection: sqlite3.Connection,
    *,
    pfquest_root: str | Path,
    pfquest_turtle_root: str | Path,
    pfquest_revision: str,
    turtle_revision: str,
) -> ImportSummary:
    """Persist Turtle P2 evidence and reconcile the canonical effective item view."""

    pfquest_revision = _required_text(pfquest_revision, "pfquest_revision")
    turtle_revision = _required_text(turtle_revision, "turtle_revision")
    base_source_id = _require_base_item_import(connection, pfquest_revision)
    turtle_source_id = _ensure_turtle_source(connection, str(Path(pfquest_turtle_root)))
    tables = _load_effective_tables(pfquest_root, pfquest_turtle_root)

    item_data_patch = tables.patch[("items", "data-turtle")]
    item_name_patch = tables.patch[("items", "enUS-turtle")]
    ref_patch = tables.patch[("refloot", "data-turtle")]
    changed_item_ids = sorted(
        {key for key in item_data_patch if isinstance(key, int)}
        | {key for key in item_name_patch if isinstance(key, int)}
    )
    changed_reference_ids = {key for key in ref_patch if isinstance(key, int)}
    rows_read = len(changed_item_ids) + len(changed_reference_ids)

    base_batch_id = _create_batch(
        connection,
        source_id=base_source_id,
        revision=pfquest_revision,
        rows_read=rows_read,
        importer_version=f"{IMPORTER_VERSION}-base-evidence",
    )
    turtle_batch_id = _create_batch(
        connection,
        source_id=turtle_source_id,
        revision=turtle_revision,
        rows_read=rows_read,
        importer_version=IMPORTER_VERSION,
    )

    inserted = updated = deleted = protected = 0
    template_inserted = template_updated = 0
    unresolved: list[dict[str, Any]] = []
    unresolved_acquisitions: list[dict[str, Any]] = []

    try:
        base_item_data = tables.base[("items", "data")]
        effective_item_data = tables.effective[("items", "data")]
        base_item_names = tables.base[("items", "enUS")]
        effective_item_names = tables.effective[("items", "enUS")]
        effective_unit_names = tables.effective[("units", "enUS")]
        effective_object_names = tables.effective[("objects", "enUS")]
        turtle_unit_names = tables.patch[("units", "enUS-turtle")]
        turtle_object_names = tables.patch[("objects", "enUS-turtle")]

        # Record the explicit complete source-view facts only where Turtle actually patches a
        # top-level item entry.  Unchanged base entries remain base-selected.
        for item_id in changed_item_ids:
            if item_id in item_name_patch:
                base_name = _valid_name(base_item_names.get(item_id))
                effective_name = _valid_name(effective_item_names.get(item_id))
                _record_base_scalar(
                    connection,
                    batch_id=base_batch_id,
                    subject_kind="item",
                    subject_key=item_id,
                    fact_key=ITEM_PRESENCE_FACT,
                    value=base_name is not None,
                    record_type="item_effective_view",
                )
                _record_turtle_scalar(
                    connection,
                    batch_id=turtle_batch_id,
                    subject_kind="item",
                    subject_key=item_id,
                    fact_key=ITEM_PRESENCE_FACT,
                    value=effective_name is not None,
                    record_type="item_effective_view",
                    negative_presence=effective_name is None,
                )
                if effective_name is None:
                    remaining = _item_acquisition_payload(
                        effective_item_data.get(item_id), label=f"effective item[{item_id}]"
                    )
                    if remaining:
                        raise PfQuestItemImportError(
                            f"Turtle removes the effective enUS name for item {item_id} while "
                            "supported acquisition data remains; this source shape is ambiguous "
                            "for the current non-null item identity model"
                        )
                if effective_name is not None:
                    row_inserted, row_updated = _upsert_item_name(
                        connection,
                        item_id=item_id,
                        name=effective_name,
                        turtle_batch_id=turtle_batch_id,
                    )
                    inserted += row_inserted
                    updated += row_updated

            if item_id in item_data_patch:
                base_set = _item_acquisition_payload(
                    base_item_data.get(item_id), label=f"base item[{item_id}]"
                )
                effective_set = _item_acquisition_payload(
                    effective_item_data.get(item_id), label=f"effective item[{item_id}]"
                )
                _record_base_scalar(
                    connection,
                    batch_id=base_batch_id,
                    subject_kind="item",
                    subject_key=item_id,
                    fact_key=ITEM_ACQUISITION_SET_FACT,
                    value=base_set,
                    record_type="item_acquisition_set",
                )
                set_observation = _record_turtle_scalar(
                    connection,
                    batch_id=turtle_batch_id,
                    subject_kind="item",
                    subject_key=item_id,
                    fact_key=ITEM_ACQUISITION_SET_FACT,
                    value=effective_set,
                    record_type="item_acquisition_set",
                )
                selected_set = _selection_for_group(
                    connection, _group_for_observation(connection, set_observation)
                )
                # Any complete-set selection outside the replaceable managed policy is protected
                # wholesale, including an explicit/custom selection whose source key is pfquest.
                desired = effective_set
                use_turtle_relation_evidence = True
                if selected_set is not None and not _selection_is_managed(selected_set):
                    if not isinstance(selected_set.value, list):
                        raise TypeError("selected item acquisition set must be an array")
                    desired = selected_set.value
                    use_turtle_relation_evidence = False

                effective_name = _valid_name(effective_item_names.get(item_id))
                if effective_name is None and desired:
                    raise PfQuestItemImportError(
                        f"effective item {item_id} has supported acquisitions but no effective enUS name"
                    )
                if effective_name is not None and connection.execute(
                    "SELECT 1 FROM items WHERE item_id = ?", (item_id,)
                ).fetchone() is None:
                    # This occurs when Turtle adds data but the usable name comes from an otherwise
                    # unmaterialized base localization row.
                    base_name = _valid_name(base_item_names.get(item_id))
                    name_source_batch = turtle_batch_id if item_id in item_name_patch else base_batch_id
                    source_key = (
                        PFQUEST_TURTLE_SOURCE_KEY if item_id in item_name_patch else PFQUEST_SOURCE_KEY
                    )
                    observation_id = record_scalar_observation(
                        connection,
                        subject_kind="item",
                        subject_key=item_id,
                        fact_key="name",
                        import_batch_id=name_source_batch,
                        value=effective_name,
                        source_record_type="item",
                        raw_identifier=item_id,
                    )
                    if source_key == PFQUEST_TURTLE_SOURCE_KEY:
                        _select_turtle_if_managed(
                            connection,
                            observation_id=observation_id,
                            subject_kind="item",
                            subject_key=item_id,
                        )
                    else:
                        group_id = _group_for_observation(connection, observation_id)
                        if _selection_for_group(connection, group_id) is None:
                            select_canonical_observation(
                                connection,
                                observation_group_id=group_id,
                                observation_id=observation_id,
                                selection_policy="first-observation",
                                selection_reason="Base item name had no prior canonical selection.",
                            )
                    name_selection = _selection_for_group(
                        connection, _group_for_observation(connection, observation_id)
                    )
                    canonical_name = effective_name if name_selection is None else str(name_selection.value)
                    connection.execute(
                        "INSERT INTO items(item_id, name) VALUES (?, ?)", (item_id, canonical_name)
                    )
                    inserted += 1
                    _ = base_name  # Documents that base/effective origin was deliberately considered.

                # Ensure FK target identities before materializing relations.  Real Turtle data
                # can contain acquisition IDs that have no matching effective enUS identity.
                # Preserve those source relations as provenance, but do not invent a canonical
                # creature/gameobject merely to satisfy the materialized FK.
                materializable_desired: list[dict[str, Any]] = []
                for relation in desired:
                    path_kind = relation.get("path_kind")
                    if path_kind not in {"direct", "vendor"}:
                        materializable_desired.append(relation)
                        continue

                    kind = (
                        str(relation["source_kind"]) if path_kind == "direct" else "creature"
                    )
                    source_id = int(relation["source_id"])
                    row_inserted, row_updated = _ensure_target_identity(
                        connection,
                        source_kind=kind,
                        source_id=source_id,
                        effective_names=(
                            effective_unit_names if kind == "creature" else effective_object_names
                        ),
                        turtle_name_patch=(
                            turtle_unit_names if kind == "creature" else turtle_object_names
                        ),
                        base_batch_id=base_batch_id,
                        turtle_batch_id=turtle_batch_id,
                        fatal=False,
                    )
                    template_inserted += int(row_inserted)
                    template_updated += int(row_updated)

                    table = "creatures" if kind == "creature" else "gameobjects"
                    id_column = "creature_id" if kind == "creature" else "gameobject_id"
                    identity_exists = connection.execute(
                        f"SELECT 1 FROM {table} WHERE {id_column} = ?", (source_id,)
                    ).fetchone() is not None
                    if identity_exists:
                        materializable_desired.append(relation)
                        continue

                    unresolved_acquisitions.append(
                        {
                            "item_id": item_id,
                            "path_kind": str(path_kind),
                            "source_kind": kind,
                            "source_id": source_id,
                            "reason": "missing_source_identity",
                        }
                    )

                    fact_key = "loot_source" if path_kind == "direct" else "vendor_source"
                    instance_key = f"{kind}:{source_id}"
                    if use_turtle_relation_evidence:
                        attributes = (
                            {"chance_percent": float(relation["chance_percent"])}
                            if path_kind == "direct"
                            else {"max_count": int(relation["max_count"])}
                        )
                        _record_turtle_relation(
                            connection,
                            batch_id=turtle_batch_id,
                            subject_kind="item",
                            subject_key=item_id,
                            fact_key=fact_key,
                            target_kind=kind,
                            target_key=source_id,
                            relation_instance_key=instance_key,
                            attributes=attributes,
                            record_type="item" if path_kind == "direct" else "item_vendor",
                            raw_identifier=(
                                f"{item_id}:{kind}:{source_id}"
                                if path_kind == "direct"
                                else f"{item_id}:V:{source_id}"
                            ),
                        )
                    elif _selected_relation(
                        connection,
                        subject_kind="item",
                        subject_key=item_id,
                        fact_key=fact_key,
                        instance_key=instance_key,
                    ) is None:
                        raise RuntimeError(
                            "protected item acquisition set requires selected primitive relation "
                            f"item:{item_id} {fact_key}[{instance_key}]"
                        )

                row_inserted, row_updated, row_deleted, row_protected = _sync_item_relations(
                    connection,
                    item_id=item_id,
                    desired=materializable_desired,
                    turtle_batch_id=turtle_batch_id,
                    use_turtle_evidence=use_turtle_relation_evidence,
                )
                inserted += row_inserted
                updated += row_updated
                deleted += row_deleted
                protected += row_protected

        # References needed by Turtle-changed items may themselves be unchanged base definitions.
        needed_reference_ids = set(changed_reference_ids)
        for item_id in changed_item_ids:
            record = effective_item_data.get(item_id)
            if isinstance(record, dict):
                needed_reference_ids.update(
                    reference_id
                    for reference_id, _ in _numeric_links(
                        record.get("R"), label=f"effective item[{item_id}].R"
                    )
                )

        base_refloot = tables.base[("refloot", "data")]
        effective_refloot = tables.effective[("refloot", "data")]
        for reference_id in sorted(needed_reference_ids):
            is_turtle_definition = reference_id in ref_patch
            source_key = PFQUEST_TURTLE_SOURCE_KEY if is_turtle_definition else PFQUEST_SOURCE_KEY
            batch_id = turtle_batch_id if is_turtle_definition else base_batch_id
            base_record = base_refloot.get(reference_id)
            effective_record = effective_refloot.get(reference_id)
            base_members = _reference_member_payload(base_record, reference_id=reference_id)
            effective_members = _reference_member_payload(
                effective_record, reference_id=reference_id
            )

            if is_turtle_definition:
                _record_base_scalar(
                    connection,
                    batch_id=base_batch_id,
                    subject_kind="loot_reference",
                    subject_key=reference_id,
                    fact_key=REFERENCE_PRESENCE_FACT,
                    value=base_record is not None,
                    record_type="refloot_effective_view",
                )
                _record_base_scalar(
                    connection,
                    batch_id=base_batch_id,
                    subject_kind="loot_reference",
                    subject_key=reference_id,
                    fact_key=REFERENCE_MEMBER_SET_FACT,
                    value=base_members,
                    record_type="refloot_member_set",
                )
                _record_turtle_scalar(
                    connection,
                    batch_id=turtle_batch_id,
                    subject_kind="loot_reference",
                    subject_key=reference_id,
                    fact_key=REFERENCE_PRESENCE_FACT,
                    value=effective_record is not None,
                    record_type="refloot_effective_view",
                    negative_presence=effective_record is None,
                )
                member_observation = _record_turtle_scalar(
                    connection,
                    batch_id=turtle_batch_id,
                    subject_kind="loot_reference",
                    subject_key=reference_id,
                    fact_key=REFERENCE_MEMBER_SET_FACT,
                    value=effective_members,
                    record_type="refloot_member_set",
                )
                selected_members = _selection_for_group(
                    connection, _group_for_observation(connection, member_observation)
                )
                desired_members = effective_members
                use_turtle_member_evidence = True
                if selected_members is not None and not _selection_is_managed(selected_members):
                    if not isinstance(selected_members.value, list):
                        raise TypeError("selected reference member set must be an array")
                    desired_members = selected_members.value
                    use_turtle_member_evidence = False
            else:
                desired_members = effective_members
                use_turtle_member_evidence = False

            if effective_record is None:
                # Keep the native reference anchor if item_reference_loot still points to it.
                if connection.execute(
                    "SELECT 1 FROM item_reference_loot WHERE reference_loot_id = ? LIMIT 1",
                    (reference_id,),
                ).fetchone() is not None:
                    connection.execute(
                        "INSERT OR IGNORE INTO loot_references(reference_loot_id) VALUES (?)",
                        (reference_id,),
                    )
                    unresolved.append(
                        {
                            "reference_loot_id": reference_id,
                            "reason": "missing_refloot_definition",
                        }
                    )
            else:
                connection.execute(
                    "INSERT OR IGNORE INTO loot_references(reference_loot_id) VALUES (?)",
                    (reference_id,),
                )

            materializable_members: list[dict[str, Any]] = []
            for member in desired_members:
                kind = str(member["source_kind"])
                source_id = int(member["source_id"])
                row_inserted, row_updated = _ensure_target_identity(
                    connection,
                    source_kind=kind,
                    source_id=source_id,
                    effective_names=(effective_unit_names if kind == "creature" else effective_object_names),
                    turtle_name_patch=(turtle_unit_names if kind == "creature" else turtle_object_names),
                    base_batch_id=base_batch_id,
                    turtle_batch_id=turtle_batch_id,
                    fatal=False,
                )
                template_inserted += int(row_inserted)
                template_updated += int(row_updated)
                table = "creatures" if kind == "creature" else "gameobjects"
                id_column = "creature_id" if kind == "creature" else "gameobject_id"
                if connection.execute(
                    f"SELECT 1 FROM {table} WHERE {id_column} = ?", (source_id,)
                ).fetchone() is None:
                    # Preserve the relation observation below only when there is source identity;
                    # otherwise report exactly as P2-T02 does rather than invent a template.
                    unresolved.append(
                        {
                            "reference_loot_id": reference_id,
                            "source_kind": kind,
                            "source_id": source_id,
                            "reason": "missing_source_identity",
                        }
                    )
                    if source_key == PFQUEST_TURTLE_SOURCE_KEY and use_turtle_member_evidence:
                        _record_turtle_relation(
                            connection,
                            batch_id=batch_id,
                            subject_kind="loot_reference",
                            subject_key=reference_id,
                            fact_key="loot_source_member",
                            target_kind=kind,
                            target_key=source_id,
                            relation_instance_key=f"{kind}:{source_id}",
                            attributes={"membership_value": float(member["membership_value"])},
                            record_type="refloot",
                            raw_identifier=f"{reference_id}:{kind}:{source_id}",
                        )
                    elif source_key == PFQUEST_TURTLE_SOURCE_KEY:
                        if _selected_relation(
                            connection,
                            subject_kind="loot_reference",
                            subject_key=reference_id,
                            fact_key="loot_source_member",
                            instance_key=f"{kind}:{source_id}",
                        ) is None:
                            raise RuntimeError(
                                "protected reference member set requires selected primitive "
                                f"relation loot_reference:{reference_id} member[{kind}:{source_id}]"
                            )
                    else:
                        _record_base_relation(
                            connection,
                            batch_id=batch_id,
                            subject_kind="loot_reference",
                            subject_key=reference_id,
                            fact_key="loot_source_member",
                            target_kind=kind,
                            target_key=source_id,
                            relation_instance_key=f"{kind}:{source_id}",
                            attributes={"membership_value": float(member["membership_value"])},
                            record_type="refloot",
                            raw_identifier=f"{reference_id}:{kind}:{source_id}",
                        )
                    continue
                materializable_members.append(member)

            row_inserted, row_deleted, row_protected = _sync_reference_members(
                connection,
                reference_id=reference_id,
                desired=materializable_members,
                source_key=source_key,
                batch_id=batch_id,
                record_turtle_evidence=use_turtle_member_evidence,
            )
            inserted += row_inserted
            deleted += row_deleted
            protected += row_protected

        # A Turtle localization deletion can remove the canonical item identity only when the
        # selected complete source-view fact is specifically Turtle ``item_presence = false``.
        # This protects explicit/custom selections even when they reuse the ``pfquest`` source key.
        item_identities_deleted = 0
        for item_id in sorted(key for key in item_name_patch if isinstance(key, int)):
            if _valid_name(effective_item_names.get(item_id)) is not None:
                continue
            presence_selection = _selected_scalar(
                connection,
                subject_kind="item",
                subject_key=item_id,
                fact_key=ITEM_PRESENCE_FACT,
            )
            if not (
                presence_selection is not None
                and presence_selection.source_key == PFQUEST_TURTLE_SOURCE_KEY
                and presence_selection.selection_policy == TURTLE_SELECTION_POLICY
                and presence_selection.value is False
            ):
                continue
            dependency = connection.execute(
                """
                SELECT 1 FROM creature_loot WHERE item_id = ?
                UNION ALL SELECT 1 FROM gameobject_loot WHERE item_id = ?
                UNION ALL SELECT 1 FROM item_reference_loot WHERE item_id = ?
                UNION ALL SELECT 1 FROM vendor_items WHERE item_id = ?
                LIMIT 1
                """,
                (item_id, item_id, item_id, item_id),
            ).fetchone()
            if dependency is None:
                cursor = connection.execute("DELETE FROM items WHERE item_id = ?", (item_id,))
                item_identities_deleted += int(cursor.rowcount > 0)
        deleted += item_identities_deleted

        unresolved.sort(
            key=lambda issue: (
                int(issue["reference_loot_id"]),
                str(issue.get("source_kind", "")),
                int(issue.get("source_id", -1)),
                str(issue["reason"]),
            )
        )
        unresolved_acquisitions.sort(
            key=lambda issue: (
                int(issue["item_id"]),
                str(issue["path_kind"]),
                str(issue["source_kind"]),
                int(issue["source_id"]),
                str(issue["reason"]),
            )
        )
        details = {
            "item_data_patch_entries": sum(1 for key in item_data_patch if isinstance(key, int)),
            "item_name_patch_entries": sum(1 for key in item_name_patch if isinstance(key, int)),
            "reference_patch_entries": len(changed_reference_ids),
            "base_supported_counts": _supported_counts(tables.base),
            "effective_supported_counts": _supported_counts(tables.effective),
            "canonical_relations_or_identities_deleted": deleted,
            "protected_stale_relations": protected,
            "relation_only_templates_inserted": template_inserted,
            "relation_only_templates_updated": template_updated,
            "unresolved_acquisition_targets": unresolved_acquisitions,
            "unresolved_reference_loot": unresolved,
        }
        warning_count = len(unresolved_acquisitions) + len(unresolved) + protected
        _finish_batch(
            connection,
            batch_id=base_batch_id,
            rows_read=rows_read,
            rows_inserted=0,
            rows_updated=0,
            warning_count=0,
            details={"purpose": "P2-T04 base complete-set/identity evidence for patched entries"},
        )
        _finish_batch(
            connection,
            batch_id=turtle_batch_id,
            rows_read=rows_read,
            rows_inserted=inserted + template_inserted,
            rows_updated=updated + template_updated,
            warning_count=warning_count,
            details=details,
        )
    except Exception as exc:
        _fail_batch(connection, base_batch_id, exc)
        _fail_batch(connection, turtle_batch_id, exc)
        raise

    return ImportSummary(
        source_key=PFQUEST_TURTLE_SOURCE_KEY,
        source_revision=turtle_revision,
        status="succeeded",
        rows_read=rows_read,
        rows_accepted=rows_read,
        rows_skipped=0,
        rows_inserted=inserted + template_inserted,
        rows_updated=updated + template_updated,
        warning_count=warning_count,
        error_count=0,
        details=details,
    )
