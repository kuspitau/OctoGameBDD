from __future__ import annotations

from pathlib import Path

import pytest
from nicegui.testing import user_simulation

from octogamedb.ui_app import register_pages
from octogamedb.ui_read import ZoneSearchRequest, ZoneUiConfig


class _FakeZoneService:
    def __init__(self) -> None:
        self.requests: list[ZoneSearchRequest] = []

    def search_zones(self, request: ZoneSearchRequest) -> dict[str, object]:
        self.requests.append(request)
        return {
            "summary": {
                "returned_count": len(self.requests),
                "known_match_count": 1,
                "unknown_count": 0,
            },
            "rows": [
                {
                    "zone_id": 10,
                    "name": "Elwynn Forest",
                    "map_id": 0,
                    "map_name": "Azeroth",
                    "parent_zone_id": None,
                    "parent_zone_name": "",
                    "match_state": "known_match",
                }
            ],
        }

    def load_zone_detail(self, zone_id: int) -> dict[str, object]:
        assert zone_id == 10
        return {
            "zone": {
                "zone_id": 10,
                "name": "Elwynn Forest",
                "map": {"map_id": 0, "name": "Azeroth"},
                "parent_zone": None,
            },
            "coverage": {
                "state": "unknown",
                "negative_claim_authorized": False,
                "world_entity_unknown_geography_count": 3,
                "world_entity_known_non_match_count": 0,
                "world_entity_projection_truncated": False,
                "unresolved_trainer_relation_count": 0,
                "recipe_unknown_geography_counts": {"teaching_item": 4},
                "semantics": "positive evidence only; absence remains unknown",
            },
            "world_summary": {"returned_count": 0},
            "world_truncated": False,
            "entities": [],
            "items": [],
            "quests": {"given": [], "finished": [], "objectives": []},
            "vendors": [],
            "trainers": {"known": [], "unknown_relations": []},
            "recipes": {"included": True, "sections": []},
        }


@pytest.mark.parametrize(
    ("marker", "typed_value", "field_name", "expected"),
    (
        ("zone-id-input", "10", "zone_id", 10),
        ("zone-name-input", "elwynn", "name_contains", "elwynn"),
        ("map-id-input", "0", "map_id", 0),
        ("map-name-input", "azeroth", "map_name_contains", "azeroth"),
    ),
)
async def test_enter_submits_each_zone_search_field(
    tmp_path: Path,
    marker: str,
    typed_value: str,
    field_name: str,
    expected: object,
) -> None:
    config = ZoneUiConfig(db_path=tmp_path / "not-used-by-fake.sqlite3")
    service = _FakeZoneService()

    async with user_simulation() as user:
        register_pages(config, service=service)  # type: ignore[arg-type]

        await user.open("/")
        await user.should_see("Returned: 1")
        user.find(marker=marker).type(typed_value).trigger("keydown.enter")
        await user.should_see("Returned: 2")

    assert getattr(service.requests[-1], field_name) == expected


async def test_sort_direction_and_state_controls_apply_automatically(tmp_path: Path) -> None:
    config = ZoneUiConfig(db_path=tmp_path / "not-used-by-fake.sqlite3")
    service = _FakeZoneService()

    async with user_simulation() as user:
        register_pages(config, service=service)  # type: ignore[arg-type]

        await user.open("/")
        await user.should_see("Returned: 1")

        sort_control = next(iter(user.find(marker="sort-by-control").elements))
        sort_control.set_value("name")
        await user.should_see("Returned: 2")
        assert service.requests[-1].sort_by == "name"

        user.find(marker="descending-control").click()
        await user.should_see("Returned: 3")
        assert service.requests[-1].descending is True

        user.find(marker="include-unknown-control").click()
        await user.should_see("Returned: 4")
        assert service.requests[-1].include_unknown is True

        user.find(marker="include-non-matches-control").click()
        await user.should_see("Returned: 5")
        assert service.requests[-1].include_non_matches is True


async def test_table_action_opens_detail_and_exposes_unknown_coverage(tmp_path: Path) -> None:
    config = ZoneUiConfig(db_path=tmp_path / "not-used-by-fake.sqlite3")
    service = _FakeZoneService()

    async with user_simulation() as user:
        register_pages(config, service=service)  # type: ignore[arg-type]

        await user.open("/")
        user.find(marker="open-zone-action").trigger("click", args=10)
        await user.should_see("Coverage state: unknown")
        await user.should_see("Negative claim authorized: False")
