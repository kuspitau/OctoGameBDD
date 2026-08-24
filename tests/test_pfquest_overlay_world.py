from __future__ import annotations

from pathlib import Path

import pytest

from octogamedb.importers.pfquest_overlay_world import (
    compare_pfquest_world_slices,
    load_pfquest_octo_world_slice,
    load_pfquest_turtle_world_slice,
)
from octogamedb.importers.pfquest_world import PfQuestParseError

_BASE = Path(__file__).parent / "fixtures" / "pfquest" / "world_slice"


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_overlay(root: Path, *, overwrites: str = "") -> None:
    _write(
        root,
        "db/zones-turtle.lua",
        'pfDB["zones"]["data-turtle"] = { [5600] = { 12, 1, 1, 1, 1 } }',
    )
    _write(
        root,
        "db/enUS/zones-turtle.lua",
        'pfDB["zones"]["enUS-turtle"] = { [9] = "_", [12] = "Elwynn Overlay", '
        '[5600] = "Dragonmaw Retreat" }',
    )
    _write(
        root,
        "db/units-turtle.lua",
        'pfDB["units"]["data-turtle"] = { '
        '[6] = { ["lvl"] = "2-3", ["fac"] = "A", '
        '["coords"] = { [1] = { 55, 56, 12, 120 } } }, '
        '[7] = { ["lvl"] = "4", ["fac"] = "A", '
        '["coords"] = { [1] = { 40, 41, 12, 60 } } } }',
    )
    _write(
        root,
        "db/enUS/units-turtle.lua",
        'pfDB["units"]["enUS-turtle"] = { [6] = "Kobold Worker", [7] = "Overlay Scout" }',
    )
    _write(
        root,
        "db/objects-turtle.lua",
        'pfDB["objects"]["data-turtle"] = { [32] = "_", '
        '[33] = { ["fac"] = "A", ["coords"] = { [1] = { 30, 31, 12, 90 } } } }',
    )
    _write(
        root,
        "db/enUS/objects-turtle.lua",
        'pfDB["objects"]["enUS-turtle"] = { [32] = "_", [33] = "Overlay Cache" }',
    )
    _write(root, "overwrites.lua", overwrites)


def test_turtle_overlay_applies_patchtable_and_phantom_cleanup(tmp_path):
    turtle = tmp_path / "pfQuest-turtle"
    _make_overlay(
        turtle,
        overwrites='''
        do -- zones
          local phantom_zones = { 5600 }
          local zone_locales = { "enUS" }
          for _, locale in pairs(zone_locales) do
            local tbl = pfDB["zones"][locale .. "-turtle"]
            if tbl then
              for _, zid in pairs(phantom_zones) do
                tbl[zid] = nil
              end
            end
          end
        end
        ''',
    )

    world = load_pfquest_turtle_world_slice(_BASE, turtle)

    assert [(zone.zone_id, zone.name) for zone in world.zones] == [(12, "Elwynn Overlay")]
    assert [(row.creature_id, row.name) for row in world.creatures] == [
        (6, "Kobold Worker"),
        (7, "Overlay Scout"),
    ]
    assert world.creatures[0].faction == "A"
    assert [(row.gameobject_id, row.name) for row in world.gameobjects] == [
        (33, "Overlay Cache")
    ]


def test_turtle_overlay_does_not_invent_absent_phantom_cleanup(tmp_path):
    turtle = tmp_path / "pfQuest-turtle"
    _make_overlay(turtle)

    world = load_pfquest_turtle_world_slice(_BASE, turtle)
    zones = {zone.zone_id: zone.name for zone in world.zones}

    assert zones[5600] == "Dragonmaw Retreat"


def test_octo_overlay_applies_direct_literal_overwrites(tmp_path):
    octo = tmp_path / "pfQuest-octo"
    _make_overlay(
        octo,
        overwrites='''
        pfDB["units"]["data-turtle"][6]["fac"] = "H"
        pfDB["units"]["enUS-turtle"][7] = "Octo Scout"
        pfDB["units"]["data-turtle"][7]["coords"] = { [1] = { 44, 45, 12, 30 } }
        ''',
    )

    world = load_pfquest_octo_world_slice(_BASE, octo)

    assert world.creatures[0].faction == "H"
    assert world.creatures[1].name == "Octo Scout"
    assert [(s.x, s.y, s.zone_id, s.respawn_seconds) for s in world.creatures[1].spawns] == [
        (44.0, 45.0, 12, 30)
    ]


def test_world_comparison_reports_differences_without_winner(tmp_path):
    turtle = tmp_path / "turtle"
    octo = tmp_path / "octo"
    _make_overlay(turtle)
    _make_overlay(
        octo,
        overwrites='pfDB["units"]["enUS-turtle"][7] = "Octo Scout"',
    )

    left = load_pfquest_turtle_world_slice(_BASE, turtle)
    right = load_pfquest_octo_world_slice(_BASE, octo)
    comparison = compare_pfquest_world_slices(left, right)

    assert comparison.creatures.added == ()
    assert comparison.creatures.removed == ()
    assert comparison.creatures.changed == (7,)


def test_unhandled_indirect_world_mutation_fails_closed(tmp_path):
    octo = tmp_path / "pfQuest-octo"
    _make_overlay(
        octo,
        overwrites='''
        table.insert(
          pfDB["units"]["data-turtle"][6]["coords"],
          { 50, 50, 12, 30 }
        )
        ''',
    )

    with pytest.raises(PfQuestParseError, match="unsupported indirect world-table mutation"):
        load_pfquest_octo_world_slice(_BASE, octo)
