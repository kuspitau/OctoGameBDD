from __future__ import annotations

from pathlib import Path

from nicegui.testing import user_simulation

from octogamedb.ui_app import register_pages
from octogamedb.ui_read import ZoneSearchRequest, ZoneUiConfig


class _FakeZoneService:
    def search_zones(self, request: ZoneSearchRequest) -> dict[str, object]:
        assert request.sort_by == "zone_id"
        return {
            "summary": {
                "returned_count": 1,
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


async def test_zone_list_navigation_opens_detail_and_exposes_unknown_coverage(
    tmp_path: Path,
) -> None:
    config = ZoneUiConfig(db_path=tmp_path / "not-used-by-fake.sqlite3")

    async with user_simulation() as user:
        register_pages(config, service=_FakeZoneService())  # type: ignore[arg-type]

        await user.open("/")
        await user.should_see("Open Elwynn Forest (10)")
        user.find(marker="open-zone-10").click()
        await user.should_see("Coverage state: unknown")
        await user.should_see("Negative claim authorized: False")
