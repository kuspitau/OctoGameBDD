"""Compose pfQuest world data with Turtle/Octo overlay addons for P1-T03.

The supported overlays follow pfQuest's Turtle convention: matching ``*-turtle``
tables are loaded after pfQuest, optional overwrite logic mutates those patch
tables, then ``patchtable.lua`` applies each patch at the top-entry level.

No Lua code is executed here. Only the literal assignment subset already used by
the P1 pfQuest parser plus the reviewed Turtle phantom-zone cleanup pattern are
accepted. Unsupported world-table mutation fails closed.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.importers.pfquest_world import (
    PfQuestCreature,
    PfQuestGameObject,
    PfQuestParseError,
    PfQuestWorldSlice,
    PfQuestZone,
    _float,
    _integer,
    _level_range,
    _LuaLiteralParser,
    _numeric_sequence,
    _parse_spawn_table,
    parse_pfquest_assignment,
)

PFQUEST_TURTLE_SOURCE_URL = "https://github.com/KameleonUK/pfQuest-turtle"
PFQUEST_TURTLE_REVIEWED_REVISION = "5b8eeeeb4119be9d075087f0f0e08c187b35ad61"
PFQUEST_OCTO_SOURCE_URL = "https://github.com/paokkerkir/pfQuest-octo"
PFQUEST_OCTO_REVIEWED_REVISION = "dd3dc1fb80afe7a71e5c8ca8c31ca2a3ef57af67"

_WORLD_TABLES = (
    ("zones", "data", "zones.lua", "data-turtle", "zones-turtle.lua"),
    ("zones", "enUS", "enUS/zones.lua", "enUS-turtle", "enUS/zones-turtle.lua"),
    ("units", "data", "units.lua", "data-turtle", "units-turtle.lua"),
    ("units", "enUS", "enUS/units.lua", "enUS-turtle", "enUS/units-turtle.lua"),
    ("objects", "data", "objects.lua", "data-turtle", "objects-turtle.lua"),
    ("objects", "enUS", "enUS/objects.lua", "enUS-turtle", "enUS/objects-turtle.lua"),
)


@dataclass(frozen=True)
class EntityComparison:
    added: tuple[int, ...]
    removed: tuple[int, ...]
    changed: tuple[int, ...]


@dataclass(frozen=True)
class PfQuestWorldComparison:
    zones: EntityComparison
    creatures: EntityComparison
    gameobjects: EntityComparison


def _read_assignment(path: Path, domain: str, table_name: str) -> dict[Any, Any]:
    return parse_pfquest_assignment(
        path.read_text(encoding="utf-8"),
        domain=domain,
        table_name=table_name,
    )


def _read_optional_assignment(path: Path, domain: str, table_name: str) -> dict[Any, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    return parse_pfquest_assignment(text, domain=domain, table_name=table_name)


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
    patches: dict[tuple[str, str], dict[Any, Any]],
    text: str,
) -> None:
    for (domain, table_name), patch in patches.items():
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
                    f"unsupported indirect world-table mutation for {domain}.{table_name}"
                ) from exc
            value = parser.parse_value()
            patches[(domain, table_name)] = _apply_nested_assignment(
                patch,
                keys=keys,
                value=value,
                label=f"{domain}.{table_name}",
            )
            patch = patches[(domain, table_name)]


def _apply_turtle_phantom_zone_cleanup(
    patches: dict[tuple[str, str], dict[Any, Any]],
    text: str,
) -> bool:
    marker = re.search(r"local\s+phantom_zones\s*=\s*", text)
    dynamic_ref = 'pfDB["zones"][locale .. "-turtle"]'
    delete_marker = "tbl[zid] = nil"
    if marker is None:
        return False
    if dynamic_ref not in text or delete_marker not in text:
        raise PfQuestParseError("unrecognized Turtle phantom-zone overwrite pattern")

    parser = _LuaLiteralParser(text, marker.end())
    raw = parser.parse_value()
    if not isinstance(raw, dict):
        raise PfQuestParseError("phantom_zones must be a Lua table")
    zone_ids = [_integer(raw[key], "phantom zone id") for key in sorted(raw)]
    enus_patch = patches[("zones", "enUS-turtle")]
    for zone_id in zone_ids:
        enus_patch.pop(zone_id, None)
    return True


def _validate_no_unhandled_world_mutations(text: str, *, allow_turtle_loop: bool) -> None:
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("--"):
            continue
        if not any(f'pfDB["{domain}"]' in line for domain in ("zones", "units", "objects")):
            continue
        if stripped.startswith("pfDB["):
            continue
        if allow_turtle_loop and 'pfDB["zones"][locale .. "-turtle"]' in line:
            continue
        raise PfQuestParseError(
            f"unsupported indirect world-table mutation on line {line_number}"
        )


def _build_world_slice(
    *,
    zones_data: dict[Any, Any],
    zone_names: dict[Any, Any],
    unit_data: dict[Any, Any],
    unit_names: dict[Any, Any],
    object_data: dict[Any, Any],
    object_names: dict[Any, Any],
) -> PfQuestWorldSlice:
    referenced_zone_ids = {
        spawn.zone_id
        for records, label in ((unit_data, "unit"), (object_data, "object"))
        for entity_id, record in records.items()
        if isinstance(entity_id, int) and isinstance(record, dict)
        for spawn in _parse_spawn_table(record.get("coords"), label=f"{label}[{entity_id}]")
    }
    zone_ids = sorted(
        {int(zone_id) for zone_id in zone_names if isinstance(zone_id, int)}
        & (set(zones_data) | referenced_zone_ids)
    )

    zones: list[PfQuestZone] = []
    for zone_id in zone_ids:
        name = zone_names.get(zone_id)
        if not isinstance(name, str) or not name.strip():
            raise PfQuestParseError(f"missing enUS name for zone {zone_id}")
        frame = None
        if zone_id in zones_data:
            raw = _numeric_sequence(zones_data[zone_id], minimum=5, label=f"zone[{zone_id}]")
            frame = {
                "coordinate_context_id": _integer(raw[0], f"zone[{zone_id}][1]"),
                "width": _float(raw[1], f"zone[{zone_id}][2]"),
                "height": _float(raw[2], f"zone[{zone_id}][3]"),
                "origin_x": _float(raw[3], f"zone[{zone_id}][4]"),
                "origin_y": _float(raw[4], f"zone[{zone_id}][5]"),
            }
        zones.append(PfQuestZone(zone_id=zone_id, name=name.strip(), coordinate_frame=frame))

    creatures: list[PfQuestCreature] = []
    for creature_id in sorted(key for key in unit_data if isinstance(key, int)):
        record = unit_data[creature_id]
        if not isinstance(record, dict):
            raise PfQuestParseError(f"unit[{creature_id}] must be a Lua table")
        name = unit_names.get(creature_id)
        if not isinstance(name, str) or not name.strip():
            continue
        level_min, level_max = _level_range(record.get("lvl"))
        faction = record.get("fac")
        creatures.append(
            PfQuestCreature(
                creature_id=creature_id,
                name=name.strip(),
                level_min=level_min,
                level_max=level_max,
                faction=None if faction is None else str(faction),
                spawns=_parse_spawn_table(record.get("coords"), label=f"unit[{creature_id}]"),
            )
        )

    gameobjects: list[PfQuestGameObject] = []
    for gameobject_id in sorted(key for key in object_data if isinstance(key, int)):
        record = object_data[gameobject_id]
        if not isinstance(record, dict):
            raise PfQuestParseError(f"object[{gameobject_id}] must be a Lua table")
        name = object_names.get(gameobject_id)
        if not isinstance(name, str) or not name.strip():
            continue
        faction = record.get("fac")
        gameobjects.append(
            PfQuestGameObject(
                gameobject_id=gameobject_id,
                name=name.strip(),
                faction=None if faction is None else str(faction),
                spawns=_parse_spawn_table(record.get("coords"), label=f"object[{gameobject_id}]"),
            )
        )

    return PfQuestWorldSlice(
        zones=tuple(zones),
        creatures=tuple(creatures),
        gameobjects=tuple(gameobjects),
    )


def load_pfquest_overlay_world_slice(
    pfquest_root: str | Path,
    overlay_root: str | Path,
    *,
    overlay_kind: str,
) -> PfQuestWorldSlice:
    """Load pfQuest plus one reviewed Turtle-style overlay for the P1 world slice."""

    if overlay_kind not in {"turtle", "octo"}:
        raise ValueError("overlay_kind must be 'turtle' or 'octo'")

    base_root = Path(pfquest_root)
    patch_root = Path(overlay_root)
    patches: dict[tuple[str, str], dict[Any, Any]] = {}
    bases: dict[tuple[str, str], dict[Any, Any]] = {}

    for domain, base_table, base_relative, patch_table, patch_relative in _WORLD_TABLES:
        bases[(domain, base_table)] = _read_assignment(
            base_root / "db" / base_relative,
            domain,
            base_table,
        )
        patches[(domain, patch_table)] = _read_optional_assignment(
            patch_root / "db" / patch_relative,
            domain,
            patch_table,
        )

    overwrite_path = patch_root / "overwrites.lua"
    overwrite_text = overwrite_path.read_text(encoding="utf-8") if overwrite_path.is_file() else ""
    _apply_direct_overwrites(patches, overwrite_text)
    turtle_loop_handled = False
    if overlay_kind == "turtle":
        turtle_loop_handled = _apply_turtle_phantom_zone_cleanup(patches, overwrite_text)
    _validate_no_unhandled_world_mutations(
        overwrite_text,
        allow_turtle_loop=turtle_loop_handled,
    )

    effective: dict[tuple[str, str], dict[Any, Any]] = {}
    for domain, base_table, _base_relative, patch_table, _patch_relative in _WORLD_TABLES:
        effective[(domain, base_table)] = _patch_table(
            bases[(domain, base_table)],
            patches[(domain, patch_table)],
        )

    return _build_world_slice(
        zones_data=effective[("zones", "data")],
        zone_names=effective[("zones", "enUS")],
        unit_data=effective[("units", "data")],
        unit_names=effective[("units", "enUS")],
        object_data=effective[("objects", "data")],
        object_names=effective[("objects", "enUS")],
    )


def load_pfquest_turtle_world_slice(
    pfquest_root: str | Path,
    pfquest_turtle_root: str | Path,
) -> PfQuestWorldSlice:
    return load_pfquest_overlay_world_slice(
        pfquest_root,
        pfquest_turtle_root,
        overlay_kind="turtle",
    )


def load_pfquest_octo_world_slice(
    pfquest_root: str | Path,
    pfquest_octo_root: str | Path,
) -> PfQuestWorldSlice:
    return load_pfquest_overlay_world_slice(
        pfquest_root,
        pfquest_octo_root,
        overlay_kind="octo",
    )


def _compare_entities(left: dict[int, Any], right: dict[int, Any]) -> EntityComparison:
    left_ids = set(left)
    right_ids = set(right)
    return EntityComparison(
        added=tuple(sorted(right_ids - left_ids)),
        removed=tuple(sorted(left_ids - right_ids)),
        changed=tuple(sorted(key for key in left_ids & right_ids if left[key] != right[key])),
    )


def compare_pfquest_world_slices(
    left: PfQuestWorldSlice,
    right: PfQuestWorldSlice,
) -> PfQuestWorldComparison:
    """Compare two effective views without choosing a canonical winner."""

    return PfQuestWorldComparison(
        zones=_compare_entities(
            {row.zone_id: row for row in left.zones},
            {row.zone_id: row for row in right.zones},
        ),
        creatures=_compare_entities(
            {row.creature_id: row for row in left.creatures},
            {row.creature_id: row for row in right.creatures},
        ),
        gameobjects=_compare_entities(
            {row.gameobject_id: row for row in left.gameobjects},
            {row.gameobject_id: row for row in right.gameobjects},
        ),
    )
