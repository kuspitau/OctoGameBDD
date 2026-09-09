from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from octogamedb.ui_read import (
    ZoneSearchRequest,
    ZoneUiConfig,
    ZoneUiService,
    open_readonly_database,
    project_zone_detail,
    project_zone_list,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_readonly_database_does_not_create_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "octogamedb.sqlite3"

    with pytest.raises(FileNotFoundError, match="database not found"), open_readonly_database(
        missing
    ):
        pass

    assert not missing.exists()
    assert not missing.parent.exists()


def test_readonly_database_rejects_unreadable_sqlite_file(tmp_path: Path) -> None:
    invalid = tmp_path / "not-a-database.sqlite3"
    invalid.write_text("not sqlite", encoding="utf-8")
    before = invalid.read_bytes()

    with pytest.raises(sqlite3.DatabaseError), open_readonly_database(invalid):
        pass

    assert invalid.read_bytes() == before


def test_readonly_database_blocks_writes_and_preserves_bytes(tmp_path: Path) -> None:
    db_path = tmp_path / "fixture.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE fixture(value INTEGER)")
    connection.execute("INSERT INTO fixture(value) VALUES (1)")
    connection.commit()
    connection.close()
    before = _sha256(db_path)

    with open_readonly_database(db_path) as readonly:
        assert readonly.execute("PRAGMA query_only").fetchone()[0] == 1
        assert readonly.execute("SELECT value FROM fixture").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            readonly.execute("INSERT INTO fixture(value) VALUES (2)")

    assert _sha256(db_path) == before


def test_service_delegates_zone_search_to_p7_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from octogamedb import ui_read

    db_path = tmp_path / "fixture.sqlite3"
    sqlite3.connect(db_path).close()
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_query(connection: sqlite3.Connection, **kwargs: object) -> object:
        captured.update(kwargs)
        captured["query_only"] = connection.execute("PRAGMA query_only").fetchone()[0]
        return sentinel

    monkeypatch.setattr(ui_read, "query_zones", fake_query)
    monkeypatch.setattr(
        ui_read,
        "zone_query_page_to_dict",
        lambda page: {
            "summary": {"returned_count": 1, "known_match_count": 1, "unknown_count": 0},
            "results": [
                {
                    "match_state": "known_match",
                    "zone": {
                        "zone_id": 10,
                        "name": "Elwynn Forest",
                        "map": {"map_id": 0, "name": "Azeroth"},
                        "parent_zone": None,
                    },
                }
            ],
        }
        if page is sentinel
        else {},
    )

    service = ZoneUiService(ZoneUiConfig(db_path=db_path))
    view = service.search_zones(
        ZoneSearchRequest(
            name_contains="elwynn",
            map_id=0,
            include_unknown=True,
            sort_by="name",
            descending=True,
            limit=25,
        )
    )

    assert captured == {
        "zone_id": None,
        "name_contains": "elwynn",
        "map_id": 0,
        "map_name_contains": None,
        "include_states": ("known_match", "unknown"),
        "sort_by": "name",
        "descending": True,
        "limit": 25,
        "query_only": 1,
    }
    assert view["rows"][0]["zone_id"] == 10
    assert view["rows"][0]["map_name"] == "Azeroth"


def test_zone_list_projection_is_deterministic_for_equivalent_payloads() -> None:
    result = {
        "match_state": "known_match",
        "zone": {
            "zone_id": 10,
            "name": "Elwynn Forest",
            "map": {"map_id": 0, "name": "Azeroth"},
            "parent_zone": None,
        },
    }
    payload_a = {
        "summary": {"returned_count": 1, "known_match_count": 1},
        "results": [result],
    }
    payload_b = {
        "results": [dict(result)],
        "summary": {"known_match_count": 1, "returned_count": 1},
    }

    assert project_zone_list(payload_a) == project_zone_list(payload_b)


def test_zone_detail_projection_preserves_unknown_and_truncation_semantics() -> None:
    detail = {
        "zone": {
            "zone_id": 10,
            "name": "Elwynn Forest",
            "map": {"map_id": 0, "name": "Azeroth"},
            "parent_zone": None,
        },
        "world_entities": {
            "summary": {
                "known_match_count": 1001,
                "known_non_match_count": 5,
                "unknown_count": 12,
                "returned_count": 1000,
            },
            "truncated_known_matches": True,
            "results": [
                {
                    "entity_kind": "creature",
                    "entity_id": 42,
                    "name": "Known Creature",
                    "matching_spawns": [{"spawn_id": 1}],
                    "all_materialized_spawn_count": 3,
                    "spawn_set": {"is_complete_for_canonical_view": False},
                }
            ],
        },
        "items": {
            "results": [
                {
                    "item_id": 100,
                    "item_name": "Example Item",
                    "paths": [
                        {
                            "path_kind": "direct",
                            "source": {
                                "entity_kind": "creature",
                                "entity_id": 42,
                                "name": "Known Creature",
                            },
                        }
                    ],
                }
            ]
        },
        "quests": {
            "given": [],
            "finished": [],
            "objectives": [],
        },
        "vendors": [],
        "trainers": {
            "known": [],
            "unknown_relations": [
                {
                    "recipe_id": 301,
                    "recipe_name": "Unresolved Recipe",
                    "trainer_kind": "template",
                    "native_trainer_entry": 42,
                    "resolved": False,
                    "source": {
                        "entity_kind": "creature",
                        "entity_id": 42,
                        "name": "Known Creature",
                    },
                }
            ],
        },
        "recipes": {
            "included": True,
            "teaching_item": {
                "summary": {
                    "known_match_count": 2,
                    "unknown_count": 98,
                    "returned_count": 1,
                },
                "truncated_known_matches": True,
                "results": [
                    {
                        "match_state": "known_match",
                        "recipe": {
                            "recipe_id": 500,
                            "name": "Recipe A",
                            "rank_text": "Journeyman",
                        },
                    }
                ],
            },
            "trainer": {"summary": {}, "results": []},
            "quest_reward_spell": {
                "giver": {"summary": {}, "results": []},
                "finisher": {"summary": {}, "results": []},
                "objective": {"summary": {}, "results": []},
            },
        },
        "coverage": {
            "state": "unknown",
            "negative_claim_authorized": False,
            "world_entity_unknown_geography_count": 12,
            "world_entity_known_non_match_count": 5,
            "world_entity_projection_truncated": True,
            "recipe_unknown_geography_counts": {"teaching_item": 98},
            "unresolved_trainer_relation_count": 1,
            "semantics": "positive evidence only",
        },
    }

    view = project_zone_detail(detail)

    assert view["coverage"]["state"] == "unknown"
    assert view["coverage"]["negative_claim_authorized"] is False
    assert view["world_truncated"] is True
    assert view["entities"][0]["spawn_set_complete"] is False
    assert view["trainers"]["unknown_relations"][0]["resolved"] is False
    teaching = view["recipes"]["sections"][0]
    assert teaching["truncated_known_matches"] is True
    assert teaching["summary"]["unknown_count"] == 98


def test_ui_adapter_contains_no_canonical_write_sql() -> None:
    source = Path(__file__).parents[1] / "src" / "octogamedb" / "ui_read.py"
    text = source.read_text(encoding="utf-8").upper()
    forbidden = (
        "INSERT INTO ",
        "UPDATE ",
        "DELETE FROM ",
        "REPLACE INTO ",
        "CREATE TABLE ",
        "ALTER TABLE ",
        "DROP TABLE ",
    )
    assert not any(statement in text for statement in forbidden)
