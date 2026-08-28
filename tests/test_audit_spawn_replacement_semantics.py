from __future__ import annotations

import sys
import types

import pytest

from octogamedb.audit_spawn_replacement_semantics import (
    ReplacementSemanticAuditError,
    _aggregate_counts,
    _bulk_persistence_contexts,
    _changed_top_entry_fields,
    _filter_parents,
    _representative_examples,
    _routed_parent_contexts,
    _set_cardinalities,
    _zone_stratification,
    classify_raw_payload_difference,
    classify_set_relation,
)


def test_exact_set_relation_classes_cover_partition():
    assert classify_set_relation({"a", "b"}, {"a", "b"}) == "active_equals_comparison"
    assert classify_set_relation({"a", "b"}, {"a"}) == "active_strict_superset"
    assert classify_set_relation({"a"}, {"a", "b"}) == "comparison_strict_superset"
    assert classify_set_relation({"a", "b"}, {"b", "c"}) == "partial_overlap"
    assert classify_set_relation({"a"}, {"b"}) == "disjoint"
    assert classify_set_relation(set(), {"b"}) == "comparison_strict_superset"


def test_required_set_cardinalities_reconcile():
    values = _set_cardinalities(
        {"base", "gone"},
        {"base", "active", "shared"},
        {"base", "comparison", "shared"},
    )
    assert values == {
        "base": 2,
        "active": 3,
        "comparison": 3,
        "active_intersection_comparison": 2,
        "active_minus_comparison": 1,
        "comparison_minus_active": 1,
        "active_minus_base": 2,
        "comparison_minus_base": 2,
        "base_minus_active": 1,
        "base_minus_comparison": 1,
    }


@pytest.mark.parametrize(
    ("spawn", "name", "other", "expected"),
    [
        (True, False, False, "spawn_membership_only"),
        (False, True, False, "localization_name_only"),
        (False, False, True, "other_top_entry_fields_only"),
        (False, True, True, "other_top_entry_fields_only"),
        (True, True, False, "spawn_plus_other_fields"),
        (True, False, True, "spawn_plus_other_fields"),
        (False, False, False, "unsupported_unclassified"),
    ],
)
def test_raw_payload_difference_classifier(spawn, name, other, expected):
    assert (
        classify_raw_payload_difference(
            spawn_membership_differs=spawn,
            localization_differs=name,
            other_top_entry_fields_differ=other,
        )
        == expected
    )
    assert (
        classify_raw_payload_difference(
            spawn_membership_differs=spawn,
            localization_differs=name,
            other_top_entry_fields_differ=other,
            unsupported_reasons=["unknown"],
        )
        == "unsupported_unclassified"
    )


def test_changed_other_fields_is_structural_and_deterministic(monkeypatch):
    module = types.ModuleType("octogamedb.audit_spawn_raw_semantics")

    def digest(value):
        import json

        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)

    module._payload_digest = digest
    monkeypatch.setitem(sys.modules, "octogamedb.audit_spawn_raw_semantics", module)
    active = {"lvl": {1: 10, 2: 20}, "fac": 1, "same": [1, 2]}
    comparison = {"lvl": {2: 20, 1: 11}, "new": 4, "same": [1, 2]}
    assert _changed_top_entry_fields(active, comparison) == ["fac", "lvl", "new"]


def test_routed_parent_context_distinguishes_both_source_zones():
    rows = [
        {
            "parent_subject_kind": "creature",
            "parent_subject_key": "10",
            "addition_parent_class": "spawn_added_to_base_present_parent",
            "three_way_pattern": "active_only_vs_base",
            "zone_id": 406,
            "zone_name": "Stonetalon Mountains",
            "map_id": 1,
            "map_name": "Kalimdor",
        },
        {
            "parent_subject_kind": "creature",
            "parent_subject_key": "10",
            "addition_parent_class": "spawn_added_to_base_present_parent",
            "three_way_pattern": "comparison_only_vs_base",
            "zone_id": 406,
            "zone_name": "Stonetalon Mountains",
            "map_id": 1,
            "map_name": "Kalimdor",
        },
        {
            "parent_subject_kind": "creature",
            "parent_subject_key": "10",
            "addition_parent_class": "spawn_added_to_base_present_parent",
            "three_way_pattern": "active_only_vs_base",
            "zone_id": 5602,
            "zone_name": "Grim Reaches",
            "map_id": 1,
            "map_name": "Kalimdor",
        },
    ]
    context = _routed_parent_contexts(rows)[("creature", "10")]
    assert context["source_contribution_class"] == "both_sources"
    assert [row["source_contribution_class"] for row in context["routed_zones"]] == [
        "both_sources",
        "active_only",
    ]


def test_routed_parent_context_fails_on_mixed_base_parent_class():
    rows = [
        {
            "parent_subject_kind": "creature",
            "parent_subject_key": "10",
            "addition_parent_class": "parent_absent_from_base",
            "three_way_pattern": "active_only_vs_base",
            "zone_id": 406,
        },
        {
            "parent_subject_kind": "creature",
            "parent_subject_key": "10",
            "addition_parent_class": "spawn_added_to_base_present_parent",
            "three_way_pattern": "comparison_only_vs_base",
            "zone_id": 406,
        },
    ]
    with pytest.raises(ReplacementSemanticAuditError, match="conflicting base-parent classes"):
        _routed_parent_contexts(rows)


def test_bulk_persistence_architecture_is_exactly_one_load_per_source(monkeypatch):
    raw = types.ModuleType("octogamedb.audit_spawn_raw_semantics")
    raw.EXPECTED_BASE_REVISION = "base-rev"
    raw.EXPECTED_ACTIVE_REVISION = "active-rev"
    raw.EXPECTED_COMPARISON_REVISION = "comparison-rev"
    calls = []

    def persisted(_connection, *, source_key, source_revision, parents):
        calls.append((source_key, source_revision, frozenset(parents)))
        return {key: {"member_keys": set()} for key in parents}

    raw._persisted_spawn_set_contexts = persisted
    attribution = types.ModuleType("octogamedb.audit_spawn_attribution")

    def base(_connection, *, source_key, source_revision, parents):
        calls.append((source_key, source_revision, frozenset(parents)))
        return source_revision, [], {key: {"member_keys": set()} for key in parents}

    attribution._base_membership_contexts = base
    monkeypatch.setitem(sys.modules, "octogamedb.audit_spawn_raw_semantics", raw)
    monkeypatch.setitem(sys.modules, "octogamedb.audit_spawn_attribution", attribution)
    parents = {("creature", "1"), ("gameobject", "2")}
    result = _bulk_persistence_contexts(object(), parents=parents)
    assert result.base_revision == "base-rev"
    assert [call[0] for call in calls] == ["pfquest", "pfquest-turtle", "pfquest-octo"]
    assert all(call[2] == frozenset(parents) for call in calls)
    assert len(calls) == 3


def _parent(
    key: str,
    *,
    kind: str = "creature",
    base_class: str = "spawn_added_to_base_present_parent",
    contribution: str = "both_sources",
    relation: str = "partial_overlap",
    raw_class: str = "spawn_membership_only",
    zone_id: int = 406,
):
    evidence = {
        "raw_source_relative_paths": ["db/units-turtle.lua"],
        "raw_top_entry_key": key,
        "patch_payload_sha256": "abc",
        "persisted_spawn_set": {
            "source_key": "pfquest-turtle",
            "source_revision": "r",
            "import_batches": [{"batch_id": 1, "status": "succeeded"}],
            "raw_matches_persisted": True,
        },
    }
    return {
        "parent_subject_kind": kind,
        "parent_subject_key": key,
        "base_parent_class": base_class,
        "source_contribution_class": contribution,
        "set_relation_class": relation,
        "set_cardinalities": {
            "base": 1,
            "active": 2,
            "comparison": 2,
            "active_intersection_comparison": 1,
            "active_minus_comparison": 1,
            "comparison_minus_active": 1,
            "active_minus_base": 1,
            "comparison_minus_base": 1,
            "base_minus_active": 0,
            "base_minus_comparison": 0,
        },
        "raw_payload_difference": {
            "difference_class": raw_class,
            "spawn_membership_differs": True,
            "localization_name_differs": False,
            "other_top_entry_fields_differ": False,
            "other_changed_field_keys": [],
        },
        "base_provenance": {
            "source_key": "pfquest",
            "source_revision": "b",
            "import_batches": [{"batch_id": 2, "status": "succeeded"}],
            "unique_member_count": 1,
        },
        "active_evidence": evidence,
        "comparison_evidence": {**evidence, "patch_payload_sha256": "def"},
        "routed_contribution": {
            "base_parent_class": base_class,
            "source_contribution_class": contribution,
            "active_one_sided_member_count": 1,
            "comparison_one_sided_member_count": 1,
            "total_one_sided_member_count": 2,
            "routed_zones": [
                {
                    "zone_id": zone_id,
                    "zone_name": "Zone",
                    "map_id": 1,
                    "map_name": "Map",
                    "source_contribution_class": contribution,
                    "active_one_sided_member_count": 1,
                    "comparison_one_sided_member_count": 1,
                    "total_one_sided_member_count": 2,
                }
            ],
        },
    }


def test_stratification_and_examples_are_deterministic_and_cover_combinations():
    parents = [
        _parent("2", relation="disjoint", raw_class="spawn_plus_other_fields"),
        _parent("1"),
        _parent("3", kind="gameobject", zone_id=1584, contribution="active_only"),
    ]
    aggregate = _aggregate_counts(
        parents, ("parent_subject_kind", "set_relation_class", "raw_payload_difference_class")
    )
    assert sum(row["parent_count"] for row in aggregate) == 3
    zones = _zone_stratification(parents)
    assert sum(row["parent_count"] for row in zones) == 3
    revisions = {
        "base": {"source_key": "pfquest", "source_revision": "b"},
        "active": {"source_key": "pfquest-turtle", "source_revision": "a"},
        "comparison": {"source_key": "pfquest-octo", "source_revision": "c"},
    }
    first = _representative_examples(parents, source_revisions=revisions)
    second = _representative_examples(list(reversed(parents)), source_revisions=revisions)
    assert first == second
    assert len(first) == 3
    assert all(
        not path.startswith(("C:\\", "/"))
        for row in first
        for path in row["active_evidence"]["raw_source_relative_paths"]
    )


def test_parent_filters_are_exact():
    parents = [_parent("1"), _parent("2", relation="disjoint", zone_id=1584)]
    filtered = _filter_parents(
        parents,
        parent_key="2",
        parent_kind="creature",
        set_relation_class="disjoint",
        raw_payload_difference_class="spawn_membership_only",
        source_contribution_class="both_sources",
        zone_id=1584,
    )
    assert filtered == [parents[1]]


def test_semantic_payload_difference_fails_closed_when_only_raw_coords_representation_differs(
    monkeypatch,
):
    import octogamedb.audit_spawn_replacement_semantics as audit

    raw = types.ModuleType("octogamedb.audit_spawn_raw_semantics")
    raw._MISSING = object()
    raw._payload_digest = lambda value: repr(value)
    raw._composed_top_entry = lambda base, patch: base if patch is raw._MISSING else patch
    monkeypatch.setitem(sys.modules, "octogamedb.audit_spawn_raw_semantics", raw)

    class Inputs:
        pass

    active = Inputs()
    comparison = Inputs()
    active.base_tables = {("units", "enUS"): {1: "Name"}}
    comparison.base_tables = {("units", "enUS"): {1: "Name"}}
    active.patch_tables = {
        ("units", "data-turtle"): {1: {"coords": {1: {1: 10, 2: 20, 3: 406}}}},
        ("units", "enUS-turtle"): {},
    }
    comparison.patch_tables = {
        ("units", "data-turtle"): {
            1: {"coords": {1: {1: 10, 2: 20, 3: 406}, 2: {1: 10, 2: 20, 3: 406}}}
        },
        ("units", "enUS-turtle"): {},
    }
    view = {"effective_member_keys": ["same"]}
    with pytest.raises(ReplacementSemanticAuditError, match="unsupported/unclassified"):
        audit._semantic_payload_difference(
            parent_kind="creature",
            parent_key=1,
            active_inputs=active,
            comparison_inputs=comparison,
            active_view=view,
            comparison_view=view,
        )


def test_report_reproduces_fixed_regressions_and_is_deterministic(tmp_path, monkeypatch):
    import json
    import sqlite3

    import octogamedb.audit_spawn_replacement_semantics as audit

    roots = [tmp_path / name for name in ("base", "active", "comparison")]
    for root in roots:
        root.mkdir()

    # Build the exact P5-T07 routed totals while keeping the reduced source semantics synthetic.
    routed = []
    parent_count = audit.EXPECTED_FIXED_PARENT_COUNT
    zone_names = {
        406: "Stonetalon Mountains",
        5602: "Grim Reaches",
        5581: "Northwind",
        1584: "Blackrock Depths",
    }
    serial = 0
    for zone_id, count in audit.DEFAULT_ZONE_COUNTS.items():
        for index in range(count):
            parent_id = (serial % parent_count) + 1
            kind = "creature" if parent_id % 2 else "gameobject"
            routed.append(
                {
                    "subject_kind": f"{kind}_spawn",
                    "parent_subject_kind": kind,
                    "parent_subject_key": str(parent_id),
                    "spawn_key": f"routed:{zone_id}:{index}",
                    "three_way_pattern": (
                        "comparison_only_vs_base" if serial % 5 == 0 else "active_only_vs_base"
                    ),
                    "addition_parent_class": (
                        "parent_absent_from_base"
                        if parent_id % 3 == 0
                        else "spawn_added_to_base_present_parent"
                    ),
                    "zone_id": zone_id,
                    "zone_name": zone_names[zone_id],
                    "map_id": 1,
                    "map_name": "Map",
                }
            )
            serial += 1
    members = list(routed)
    for index in range(audit.EXPECTED_P5_T06_INCLUDED_TOTAL - len(members)):
        members.append(
            {
                "subject_kind": "creature_spawn",
                "parent_subject_kind": "creature",
                "parent_subject_key": "99999",
                "spawn_key": f"outside:{index}",
                "three_way_pattern": "active_only_vs_base",
                "addition_parent_class": "spawn_added_to_base_present_parent",
                "zone_id": 9999,
                "zone_name": "Outside",
                "map_id": 1,
                "map_name": "Map",
            }
        )

    overlay = types.ModuleType("octogamedb.audit_overlay_additions")
    overlay._load_addition_population = lambda *_args, **_kwargs: {"members": members}
    monkeypatch.setitem(sys.modules, "octogamedb.audit_overlay_additions", overlay)

    class Inputs:
        pass

    def make_inputs(side):
        inputs = Inputs()
        inputs.base_tables = {
            ("units", "enUS"): {},
            ("objects", "enUS"): {},
        }
        inputs.patch_tables = {
            ("units", "data-turtle"): {},
            ("objects", "data-turtle"): {},
            ("units", "enUS-turtle"): {},
            ("objects", "enUS-turtle"): {},
        }
        for parent_id in range(1, parent_count + 1):
            kind = "units" if parent_id % 2 else "objects"
            inputs.base_tables[(kind, "enUS")][parent_id] = f"Name {parent_id}"
            inputs.patch_tables[(kind, "data-turtle")][parent_id] = {
                "coords": {1: {1: parent_id, 2: parent_id + 1, 3: 406}},
                "lvl": {1: 1, 2: 2},
            }
            if side == "comparison":
                # Keep non-spawn semantics equal; the synthetic raw view below supplies
                # different deterministic effective membership and a different payload hash.
                inputs.patch_tables[(kind, "data-turtle")][parent_id]["coords"] = {
                    1: {1: parent_id + 0.5, 2: parent_id + 1.5, 3: 406}
                }
        return inputs

    active_inputs = make_inputs("active")
    comparison_inputs = make_inputs("comparison")

    raw = types.ModuleType("octogamedb.audit_spawn_raw_semantics")
    raw.EXPECTED_BASE_REVISION = "base-rev"
    raw.EXPECTED_ACTIVE_REVISION = "active-rev"
    raw.EXPECTED_COMPARISON_REVISION = "comparison-rev"
    raw._MISSING = object()
    raw._composed_top_entry = lambda base, patch: base if patch is raw._MISSING else patch
    raw._payload_digest = lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=repr
    )
    raw._require_exact_source_revisions = lambda **_kwargs: {
        "base": {"source_key": "pfquest", "source_revision": "base-rev"},
        "active": {"source_key": "pfquest-turtle", "source_revision": "active-rev"},
        "comparison": {"source_key": "pfquest-octo", "source_revision": "comparison-rev"},
    }
    raw._load_composition_inputs = lambda _base, _overlay, *, overlay_kind: (
        active_inputs if overlay_kind == "turtle" else comparison_inputs
    )

    def parent_view(_inputs, *, parent_kind, parent_key):
        side = "active" if _inputs is active_inputs else "comparison"
        base_key = f"base:{parent_kind}:{parent_key}"
        own_key = f"{side}:{parent_kind}:{parent_key}"
        return {
            "raw_transformation_class": "overlay_whole_entry_replaced",
            "patch_payload_sha256": f"{side}:{parent_kind}:{parent_key}",
            "raw_source_relative_paths": [
                "db/units-turtle.lua" if parent_kind == "creature" else "db/objects-turtle.lua"
            ],
            "raw_top_entry_key": str(parent_key),
            "base_member_keys": [base_key],
            "effective_member_keys": [base_key, own_key],
        }

    raw._parent_raw_view = parent_view

    def cross(active, _comparison, *, audited_zone_ids):
        del audited_zone_ids
        parent_id = int(active["raw_top_entry_key"])
        shared = {f"shared:{i}" for i in range(3)} if parent_id == 1 else set()
        active_added = {"a"} if parent_id <= 747 else set()
        comparison_added = {"c"} if parent_id <= 747 else set()
        return {
            "active_added_in_audited_zones": active_added,
            "comparison_added_in_audited_zones": comparison_added,
            "shared_added_in_audited_zones": shared,
        }

    raw._cross_overlay_membership_sets = cross

    def persisted(_connection, *, source_key, source_revision, parents):
        side = "active" if source_key == "pfquest-turtle" else "comparison"
        result = {}
        for kind, key in parents:
            base_key = f"base:{kind}:{key}"
            own_key = f"{side}:{kind}:{key}"
            result[(kind, key)] = {
                "source_key": source_key,
                "source_revision": source_revision,
                "import_batches": [{"batch_id": 2, "status": "succeeded"}],
                "member_keys": {base_key, own_key},
            }
        return result

    raw._persisted_spawn_set_contexts = persisted

    def verify(*, parent_kind, parent_key, side, view, base_context, persisted_context):
        del parent_kind, parent_key, side, base_context
        assert persisted_context is not None
        assert set(view["effective_member_keys"]) == set(persisted_context["member_keys"])
        return {
            "source_key": persisted_context["source_key"],
            "source_revision": persisted_context["source_revision"],
            "import_batches": persisted_context["import_batches"],
            "membership_evidence": "overlay_spawn_set_observation",
            "unique_member_count": len(persisted_context["member_keys"]),
            "raw_matches_persisted": True,
        }

    raw._verify_overlay_persistence = verify
    monkeypatch.setitem(sys.modules, "octogamedb.audit_spawn_raw_semantics", raw)

    attribution = types.ModuleType("octogamedb.audit_spawn_attribution")

    def base_contexts(_connection, *, source_key, source_revision, parents):
        assert source_key == "pfquest"
        return (
            source_revision,
            [],
            {
                (kind, key): {
                    "source_key": "pfquest",
                    "source_revision": source_revision,
                    "import_batches": [{"batch_id": 1, "status": "succeeded"}],
                    "member_keys": {f"base:{kind}:{key}"},
                }
                for kind, key in parents
            },
        )

    attribution._base_membership_contexts = base_contexts
    monkeypatch.setitem(sys.modules, "octogamedb.audit_spawn_attribution", attribution)

    connection = sqlite3.connect(":memory:")
    try:
        first = audit.replacement_semantic_report(
            connection,
            pfquest_root=roots[0],
            pfquest_turtle_root=roots[1],
            pfquest_octo_root=roots[2],
            limit=0,
        )
        second = audit.replacement_semantic_report(
            connection,
            pfquest_root=roots[0],
            pfquest_turtle_root=roots[1],
            pfquest_octo_root=roots[2],
            limit=0,
        )
    finally:
        connection.close()

    assert first["fixed_parent_count"] == audit.EXPECTED_FIXED_PARENT_COUNT
    assert first["p5_t07_regression"]["routed_four_zone_member_count"] == 15_607
    assert first["p5_t07_regression"]["both_overlays_add_parent_count"] == 747
    assert first["p5_t07_regression"]["shared_exact_added_member_count_in_routed_zones"] == 3
    assert first["set_relation_counts"]["partial_overlap"] == audit.EXPECTED_FIXED_PARENT_COUNT
    assert (
        first["raw_payload_difference_counts"]["spawn_membership_only"]
        == audit.EXPECTED_FIXED_PARENT_COUNT
    )
    assert set(first["reconciliation"].values()) == {audit.EXPECTED_FIXED_PARENT_COUNT}
    assert first["returned_parent_count"] == 0
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
