from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pytest

from octogamedb.audit_spawn_raw_semantics import (
    RawSemanticAuditError,
    _analyze_parent_entry,
    _classify_parent_transform,
    _collapse_payloads,
    _cross_overlay_summary,
    _filter_members,
    _payload_digest,
    _source_side,
)


@dataclass(frozen=True)
class _Spawn:
    x: float
    y: float
    zone_id: int
    respawn_seconds: int | None = None


def _install_spawn_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    world = types.ModuleType("octogamedb.importers.pfquest_world")
    reconcile = types.ModuleType("octogamedb.importers.pfquest_overlay_reconcile")

    def parse_spawn_table(coords, *, label):
        del label
        if coords is None:
            return ()
        rows = []
        for index in sorted(key for key in coords if isinstance(key, int)):
            raw = coords[index]
            rows.append(_Spawn(float(raw[1]), float(raw[2]), int(raw[3])))
        return tuple(rows)

    def spawn_set(kind, entity_id, spawns):
        return sorted(
            [
                {
                    "spawn_key": (
                        f"{kind}:{entity_id}:zone_percent:{spawn.zone_id}:"
                        f"{spawn.x:.6f}:{spawn.y:.6f}"
                    ),
                    "coordinate_space": "zone_percent",
                    "zone_id": spawn.zone_id,
                    "x": spawn.x,
                    "y": spawn.y,
                    "respawn_seconds": spawn.respawn_seconds,
                }
                for spawn in spawns
            ],
            key=lambda row: row["spawn_key"],
        )

    world._parse_spawn_table = parse_spawn_table
    reconcile._spawn_set = spawn_set
    monkeypatch.setitem(sys.modules, "octogamedb.importers.pfquest_world", world)
    monkeypatch.setitem(sys.modules, "octogamedb.importers.pfquest_overlay_reconcile", reconcile)


def _entry(*rows: tuple[float, float, int]):
    return {
        "coords": {
            index: {1: x, 2: y, 3: zone_id}
            for index, (x, y, zone_id) in enumerate(rows, start=1)
        }
    }


def test_classify_parent_transform_covers_source_native_top_entry_cases():
    from octogamedb.audit_spawn_raw_semantics import _MISSING

    assert (
        _classify_parent_transform(base_present=True, patch_value=_MISSING)
        == "overlay_entry_inherited"
    )
    assert (
        _classify_parent_transform(base_present=False, patch_value={"coords": {}})
        == "overlay_parent_added"
    )
    assert (
        _classify_parent_transform(base_present=True, patch_value={"coords": {}})
        == "overlay_whole_entry_replaced"
    )
    assert (
        _classify_parent_transform(base_present=True, patch_value="_")
        == "overlay_parent_removed"
    )
    with pytest.raises(RawSemanticAuditError):
        _classify_parent_transform(base_present=True, patch_value=42)


def test_inherited_parent_member_counts(monkeypatch):
    from octogamedb.audit_spawn_raw_semantics import _MISSING

    _install_spawn_stubs(monkeypatch)
    base = _entry((10.0, 20.0, 406), (30.0, 40.0, 406))
    view = _analyze_parent_entry(
        parent_kind="creature",
        parent_key=100,
        base_entry=base,
        patch_value=_MISSING,
    )
    assert view["raw_transformation_class"] == "overlay_entry_inherited"
    assert view["member_class_counts"] == {
        "member_inherited_from_base": 2,
        "member_added_by_overlay": 0,
        "member_removed_by_overlay": 0,
        "member_present_only_in_comparison": 0,
    }
    assert view["raw_source_relative_paths"] == ["db/units.lua"]


def test_overlay_added_parent_and_whole_replacement_are_distinct(monkeypatch):
    from octogamedb.audit_spawn_raw_semantics import _MISSING

    _install_spawn_stubs(monkeypatch)
    added = _analyze_parent_entry(
        parent_kind="gameobject",
        parent_key=200,
        base_entry=_MISSING,
        patch_value=_entry((1.0, 2.0, 5602)),
    )
    replaced = _analyze_parent_entry(
        parent_kind="gameobject",
        parent_key=201,
        base_entry=_entry((1.0, 2.0, 5602), (3.0, 4.0, 5602)),
        patch_value=_entry((3.0, 4.0, 5602), (5.0, 6.0, 5602)),
        overwrite_touched=True,
    )
    assert added["raw_transformation_class"] == "overlay_parent_added"
    assert added["member_class_counts"]["member_added_by_overlay"] == 1
    assert replaced["raw_transformation_class"] == "overlay_whole_entry_replaced"
    assert replaced["member_class_counts"]["member_inherited_from_base"] == 1
    assert replaced["member_class_counts"]["member_added_by_overlay"] == 1
    assert replaced["member_class_counts"]["member_removed_by_overlay"] == 1
    assert replaced["raw_source_relative_paths"] == ["db/objects-turtle.lua", "overwrites.lua"]


def test_overlay_removal_has_removed_members_and_empty_effective_set(monkeypatch):
    _install_spawn_stubs(monkeypatch)
    view = _analyze_parent_entry(
        parent_kind="creature",
        parent_key=300,
        base_entry=_entry((1.0, 2.0, 1584), (3.0, 4.0, 1584)),
        patch_value="_",
    )
    assert view["raw_transformation_class"] == "overlay_parent_removed"
    assert view["effective_unique_member_count"] == 0
    assert view["member_class_counts"]["member_removed_by_overlay"] == 2


def test_duplicate_raw_rows_collapse_to_deterministic_membership(monkeypatch):
    _install_spawn_stubs(monkeypatch)
    view = _analyze_parent_entry(
        parent_kind="creature",
        parent_key=400,
        base_entry=_entry((1.0, 2.0, 406)),
        patch_value=_entry((1.0, 2.0, 406), (5.0, 6.0, 406), (5.0, 6.0, 406)),
    )
    assert view["patch_raw_member_count"] == 3
    assert view["patch_unique_member_count"] == 2
    assert view["patch_duplicate_member_count"] == 1
    assert len(view["patch_duplicate_spawn_keys"]) == 1
    assert view["member_class_counts"]["member_added_by_overlay"] == 1


def test_collapse_payloads_keeps_first_payload_for_duplicate_key():
    collapsed = _collapse_payloads(
        [
            {"spawn_key": "k", "x": 1},
            {"spawn_key": "k", "x": 2},
            {"spawn_key": "z", "x": 3},
        ]
    )
    assert collapsed.raw_count == 3
    assert list(collapsed.unique) == ["k", "z"]
    assert collapsed.unique["k"]["x"] == 1
    assert collapsed.duplicate_keys == ("k",)


def test_payload_digest_is_order_independent_for_lua_table_keys():
    left = {"coords": {2: {1: 3.0}, 1: {1: 2.0}}, "lvl": {1: 10, 2: 11}}
    right = {"lvl": {2: 11, 1: 10}, "coords": {1: {1: 2.0}, 2: {1: 3.0}}}
    assert _payload_digest(left) == _payload_digest(right)


def test_source_side_and_filtering_keep_comparison_only_distinct():
    rows = [
        {
            "parent_subject_key": "10",
            "subject_kind": "creature_spawn",
            "source_side": "active",
            "addition_parent_class": "spawn_added_to_base_present_parent",
            "raw_transformation_class": "overlay_whole_entry_replaced",
        },
        {
            "parent_subject_key": "11",
            "subject_kind": "gameobject_spawn",
            "source_side": "comparison",
            "addition_parent_class": "parent_absent_from_base",
            "raw_transformation_class": "overlay_parent_added",
        },
    ]
    assert _source_side("active_only_vs_base") == "active"
    assert _source_side("comparison_only_vs_base") == "comparison"
    with pytest.raises(RawSemanticAuditError):
        _source_side("shared")
    filtered = _filter_members(
        rows,
        parent_key=None,
        subject_kind=None,
        source_side="comparison",
        addition_parent_class=None,
        raw_transformation_class="overlay_parent_added",
    )
    assert filtered == [rows[1]]


def test_cross_overlay_summary_counts_shared_members_and_distinct_replacements():
    parent_audits = {
        ("creature", "1"): {
            "cross_overlay": {
                "both_overlays_add": True,
                "shared_exact_added_member_count_in_audited_zones": 2,
                "both_whole_entry_replacements": True,
                "replacement_payloads_equal": False,
            }
        },
        ("gameobject", "2"): {
            "cross_overlay": {
                "both_overlays_add": False,
                "shared_exact_added_member_count_in_audited_zones": 0,
                "both_whole_entry_replacements": False,
                "replacement_payloads_equal": None,
            }
        },
    }
    assert _cross_overlay_summary(parent_audits) == {
        "both_overlays_add_parent_count": 1,
        "shared_exact_added_member_count_in_audited_zones": 2,
        "both_whole_entry_replacement_parent_count": 1,
        "different_whole_entry_replacement_payload_parent_count": 1,
    }


def test_shared_exact_overlay_addition_is_not_one_sided_membership():
    from octogamedb.audit_spawn_raw_semantics import _cross_overlay_membership_sets

    def view(keys, added):
        payloads = {
            key: {"spawn_key": key, "zone_id": 406}
            for key in keys
        }
        return {
            "effective_member_keys": list(keys),
            "added_member_keys": list(added),
            "effective_payloads": payloads,
        }

    active = view({"base", "shared", "active"}, {"shared", "active"})
    comparison = view({"base", "shared", "comparison"}, {"shared", "comparison"})
    sets = _cross_overlay_membership_sets(active, comparison, audited_zone_ids={406})
    assert sets["shared_added_in_audited_zones"] == {"shared"}
    assert sets["active_one_sided_in_audited_zones"] == {"active"}
    assert sets["comparison_one_sided_in_audited_zones"] == {"comparison"}
    assert "shared" not in sets["active_one_sided"]
    assert "shared" not in sets["comparison_one_sided"]


def test_localization_can_activate_inherited_raw_data_as_overlay_added_parent(monkeypatch):
    _install_spawn_stubs(monkeypatch)
    base = _entry((10.0, 20.0, 406))
    view = _analyze_parent_entry(
        parent_kind="creature",
        parent_key=500,
        base_entry=base,
        patch_value=__import__(
            "octogamedb.audit_spawn_raw_semantics", fromlist=["_MISSING"]
        )._MISSING,
        base_effective_parent_present=False,
        effective_parent_present=True,
        composition_transform="overlay_parent_added",
        source_relative_paths=["db/units.lua", "db/enUS/units-turtle.lua"],
    )
    assert view["base_data_entry_present"] is True
    assert view["base_entry_present"] is False
    assert view["effective_parent_present"] is True
    assert view["raw_transformation_class"] == "overlay_parent_added"
    assert view["member_class_counts"]["member_added_by_overlay"] == 1


def test_full_four_zone_report_reconciles_and_is_deterministic(tmp_path, monkeypatch):
    import json
    import sqlite3
    import types

    import octogamedb.audit_spawn_raw_semantics as audit

    roots = [tmp_path / name for name in ("pfquest", "turtle", "octo")]
    for root in roots:
        root.mkdir()

    zone_specs = [
        (406, "Stonetalon Mountains", 3780, 1365, "10"),
        (5602, "Grim Reaches", 5062, 0, "20"),
        (5581, "Northwind", 2872, 0, "30"),
        (1584, "Blackrock Depths", 1403, 1125, "40"),
    ]
    members = []
    for zone_id, zone_name, active_count, comparison_count, parent_key in zone_specs:
        for index in range(active_count):
            members.append(
                {
                    "subject_kind": "creature_spawn",
                    "parent_subject_kind": "creature",
                    "parent_subject_key": parent_key,
                    "spawn_key": f"a:{zone_id}:{index}",
                    "three_way_pattern": "active_only_vs_base",
                    "addition_parent_class": "spawn_added_to_base_present_parent",
                    "zone_id": zone_id,
                    "zone_name": zone_name,
                    "map_id": 1,
                    "map_name": "Map",
                }
            )
        for index in range(comparison_count):
            members.append(
                {
                    "subject_kind": "creature_spawn",
                    "parent_subject_kind": "creature",
                    "parent_subject_key": parent_key,
                    "spawn_key": f"c:{zone_id}:{index}",
                    "three_way_pattern": "comparison_only_vs_base",
                    "addition_parent_class": "spawn_added_to_base_present_parent",
                    "zone_id": zone_id,
                    "zone_name": zone_name,
                    "map_id": 1,
                    "map_name": "Map",
                }
            )
    for index in range(audit.EXPECTED_P5_T06_INCLUDED_TOTAL - len(members)):
        members.append(
            {
                "subject_kind": "creature_spawn",
                "parent_subject_kind": "creature",
                "parent_subject_key": "999",
                "spawn_key": f"outside:{index}",
                "three_way_pattern": "active_only_vs_base",
                "addition_parent_class": "spawn_added_to_base_present_parent",
                "zone_id": 9999,
                "zone_name": "Outside",
                "map_id": 1,
                "map_name": "Map",
            }
        )

    overlay_module = types.ModuleType("octogamedb.audit_overlay_additions")
    overlay_module._load_addition_population = lambda *_args, **_kwargs: {"members": members}
    attribution_module = types.ModuleType("octogamedb.audit_spawn_attribution")

    def base_contexts(_connection, *, source_key, source_revision, parents):
        assert source_key == "pfquest"
        return (
            source_revision,
            [],
            {
                key: {
                    "source_key": "pfquest",
                    "source_revision": source_revision,
                    "import_batches": [{"batch_id": 1, "status": "succeeded"}],
                    "member_keys": set(),
                }
                for key in parents
            },
        )

    attribution_module._base_membership_contexts = base_contexts
    monkeypatch.setitem(sys.modules, "octogamedb.audit_overlay_additions", overlay_module)
    monkeypatch.setitem(sys.modules, "octogamedb.audit_spawn_attribution", attribution_module)
    monkeypatch.setattr(
        audit,
        "_require_exact_source_revisions",
        lambda **_kwargs: {
            "base": {"source_key": "pfquest", "source_revision": audit.EXPECTED_BASE_REVISION},
            "active": {
                "source_key": "pfquest-turtle",
                "source_revision": audit.EXPECTED_ACTIVE_REVISION,
            },
            "comparison": {
                "source_key": "pfquest-octo",
                "source_revision": audit.EXPECTED_COMPARISON_REVISION,
            },
        },
    )
    monkeypatch.setattr(audit, "_load_composition_inputs", lambda *_args, **_kwargs: object())

    transforms = {
        "10": ("overlay_whole_entry_replaced", "overlay_whole_entry_replaced"),
        "20": ("overlay_parent_added", "overlay_entry_inherited"),
        "30": ("overlay_whole_entry_replaced", "overlay_entry_inherited"),
        "40": ("overlay_whole_entry_replaced", "overlay_whole_entry_replaced"),
    }

    def parent_audit(**kwargs):
        key = kwargs["parent_key"]
        rows = kwargs["parent_members"]
        active_transform, comparison_transform = transforms[key]
        active_count = sum(row["three_way_pattern"] == "active_only_vs_base" for row in rows)
        comparison_count = len(rows) - active_count

        def side(transform, count, side_name):
            return {
                "raw_transformation_class": transform,
                "raw_source_relative_paths": [
                    "db/units-turtle.lua"
                    if transform != "overlay_entry_inherited"
                    else "db/units.lua"
                ],
                "raw_top_entry_key": key,
                "patch_payload_sha256": "x" if transform != "overlay_entry_inherited" else None,
                "base_duplicate_member_count": 0,
                "patch_duplicate_member_count": 0,
                "patch_duplicate_spawn_keys": [],
                "effective_unique_member_count": count,
                "member_class_counts": {
                    "member_inherited_from_base": 0,
                    "member_added_by_overlay": count,
                    "member_removed_by_overlay": 0,
                    "member_present_only_in_comparison": count if side_name == "comparison" else 0,
                },
                "persisted_spawn_set": {"raw_matches_persisted": True},
            }

        return {
            "parent_subject_kind": "creature",
            "parent_subject_key": key,
            "base_entry_present": True,
            "addition_parent_class": "spawn_added_to_base_present_parent",
            "addition_member_count": len(rows),
            "active_addition_member_count": active_count,
            "comparison_addition_member_count": comparison_count,
            "active": side(active_transform, active_count, "active"),
            "comparison": side(comparison_transform, comparison_count, "comparison"),
            "cross_overlay": {
                "active_added_member_count_in_audited_zones": active_count,
                "comparison_added_member_count_in_audited_zones": comparison_count,
                "shared_exact_added_member_count_in_audited_zones": 0,
                "shared_exact_added_spawn_keys": [],
                "active_one_sided_member_count_in_audited_zones": active_count,
                "comparison_one_sided_member_count_in_audited_zones": comparison_count,
                "both_overlays_add": bool(active_count and comparison_count),
                "one_sided_additions_disjoint": True,
                "both_whole_entry_replacements": (
                    active_transform == comparison_transform == "overlay_whole_entry_replaced"
                ),
                "replacement_payloads_equal": False,
            },
        }

    monkeypatch.setattr(audit, "_build_parent_audit", parent_audit)
    connection = sqlite3.connect(":memory:")
    try:
        first = audit.raw_spawn_semantic_report(
            connection,
            pfquest_root=roots[0],
            pfquest_turtle_root=roots[1],
            pfquest_octo_root=roots[2],
            source_side="both",
            limit=0,
            top=20,
        )
        second = audit.raw_spawn_semantic_report(
            connection,
            pfquest_root=roots[0],
            pfquest_turtle_root=roots[1],
            pfquest_octo_root=roots[2],
            source_side="both",
            limit=0,
            top=20,
        )
    finally:
        connection.close()

    assert first["audited_zone_member_count"] == audit.EXPECTED_FOUR_ZONE_TOTAL
    assert first["p5_t06_global_included_member_count"] == audit.EXPECTED_P5_T06_INCLUDED_TOTAL
    assert {
        row["zone_id"]: row["addition_member_count"] for row in first["zone_summary"]
    } == audit.DEFAULT_ZONE_COUNTS
    assert set(first["reconciliation"].values()) == {audit.EXPECTED_FOUR_ZONE_TOTAL}
    assert first["filtered_member_count"] == audit.EXPECTED_FOUR_ZONE_TOTAL
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_persistence_fallback_accepts_raw_transform_without_spawn_set_change(monkeypatch):
    import octogamedb.audit_spawn_raw_semantics as audit

    monkeypatch.setattr(audit, "_persisted_spawn_set_context", lambda *_args, **_kwargs: None)
    view = {
        "raw_transformation_class": "overlay_whole_entry_replaced",
        "base_entry_present": True,
        "effective_parent_present": True,
        "effective_member_keys": ["spawn:a", "spawn:b"],
    }
    base_context = {
        "source_key": "pfquest",
        "source_revision": audit.EXPECTED_BASE_REVISION,
        "import_batches": [{"batch_id": 7, "status": "succeeded"}],
        "member_keys": {"spawn:a", "spawn:b"},
    }

    persisted = audit._verify_overlay_persistence(
        object(),
        parent_kind="creature",
        parent_key="123",
        side="comparison",
        view=view,
        base_context=base_context,
    )
    assert persisted["membership_evidence"] == "raw_transform_without_spawn_set_change"
    assert persisted["source_key"] == "pfquest"
    assert persisted["raw_matches_persisted"] is True


def test_top_zero_returns_no_bounded_parent_or_source_examples():
    import octogamedb.audit_spawn_raw_semantics as audit

    zone_parent_rows = [
        {
            "zone_id": 406,
            "total_addition_member_count": 1,
            "parent_subject_kind": "creature",
            "parent_subject_key": "1",
        }
    ]
    parent_rows = [
        {
            "parent_subject_kind": "creature",
            "parent_subject_key": "1",
        }
    ]
    parent_audits = {
        ("creature", "1"): {
            "active": {
                "raw_transformation_class": "overlay_whole_entry_replaced",
                "raw_source_relative_paths": ["db/units-turtle.lua"],
                "raw_top_entry_key": "1",
                "patch_payload_sha256": "a",
            },
            "comparison": {
                "raw_transformation_class": "overlay_entry_inherited",
                "raw_source_relative_paths": ["db/units.lua"],
                "raw_top_entry_key": "1",
                "patch_payload_sha256": None,
            },
        }
    }

    assert audit._top_zone_parents(zone_parent_rows, top=0) == []
    assert audit._source_examples(parent_rows, parent_audits, top=0) == []


def test_load_composition_inputs_propagates_fail_closed_p1_mutation_rejection(
    tmp_path, monkeypatch
):
    import octogamedb.audit_spawn_raw_semantics as audit

    base_root = tmp_path / "base"
    overlay_root = tmp_path / "overlay"
    (base_root / "db").mkdir(parents=True)
    (overlay_root / "db").mkdir(parents=True)
    (overlay_root / "overwrites.lua").write_text(
        'local alias = pfDB["units"]["data-turtle"]\n', encoding="utf-8"
    )

    module = types.ModuleType("octogamedb.importers.pfquest_overlay_world")
    module._WORLD_TABLES = (
        ("units", "data", "units.lua", "data-turtle", "units-turtle.lua"),
    )
    module._read_assignment = lambda *_args, **_kwargs: {}
    module._read_optional_assignment = lambda *_args, **_kwargs: {}
    module._apply_direct_overwrites = lambda *_args, **_kwargs: None
    module._apply_turtle_phantom_zone_cleanup = lambda *_args, **_kwargs: False

    def reject(text, *, allow_turtle_loop):
        assert allow_turtle_loop is False
        if 'local alias = pfDB["units"]["data-turtle"]' in text:
            raise RawSemanticAuditError("unsupported indirect world-table mutation")

    module._validate_no_unhandled_world_mutations = reject
    monkeypatch.setitem(sys.modules, "octogamedb.importers.pfquest_overlay_world", module)
    monkeypatch.setattr(audit, "_overwrite_touch_map", lambda *_args, **_kwargs: {})

    with pytest.raises(RawSemanticAuditError, match="unsupported indirect world-table mutation"):
        audit._load_composition_inputs(base_root, overlay_root, overlay_kind="octo")
