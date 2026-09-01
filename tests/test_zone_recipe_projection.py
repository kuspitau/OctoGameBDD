from __future__ import annotations

import sqlite3

from octogamedb.zone_recipe_projection import project_zone_recipes


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE spells (
            spell_id INTEGER PRIMARY KEY,
            name TEXT,
            rank_text TEXT
        );
        CREATE TABLE recipes (
            recipe_id INTEGER PRIMARY KEY,
            crafting_spell_id INTEGER NOT NULL
        );
        CREATE TABLE recipe_teaching_items (
            recipe_id INTEGER NOT NULL,
            native_item_id INTEGER NOT NULL,
            item_id INTEGER,
            item_spell_slot INTEGER NOT NULL,
            acquisition_spell_id INTEGER NOT NULL,
            learning_proof_kind TEXT NOT NULL,
            learn_effect_index INTEGER,
            server_learn_active INTEGER
        );
        CREATE TABLE recipe_quest_learning_sources (
            recipe_id INTEGER NOT NULL,
            native_quest_id INTEGER NOT NULL,
            quest_id INTEGER,
            reward_spell_field TEXT NOT NULL,
            acquisition_spell_id INTEGER NOT NULL,
            learning_proof_kind TEXT NOT NULL,
            learn_effect_index INTEGER,
            server_learn_active INTEGER
        );
        """
    )
    connection.executemany(
        "INSERT INTO spells(spell_id, name, rank_text) VALUES (?, ?, ?)",
        [
            (101, "Recipe One", None),
            (102, "Recipe Two", None),
            (103, "Recipe Three", None),
            (104, "Recipe Four", None),
        ],
    )
    connection.executemany(
        "INSERT INTO recipes(recipe_id, crafting_spell_id) VALUES (?, ?)",
        [(1, 101), (2, 102), (3, 103), (4, 104)],
    )
    connection.execute(
        """
        INSERT INTO recipe_teaching_items(
            recipe_id, native_item_id, item_id, item_spell_slot,
            acquisition_spell_id, learning_proof_kind,
            learn_effect_index, server_learn_active
        ) VALUES (1, 100, 100, 0, 501, 'learn_spell_effect', 0, 1)
        """
    )
    connection.execute(
        """
        INSERT INTO recipe_quest_learning_sources(
            recipe_id, native_quest_id, quest_id, reward_spell_field,
            acquisition_spell_id, learning_proof_kind,
            learn_effect_index, server_learn_active
        ) VALUES (3, 200, 200, 'reward_spell', 503, 'reward_spell', NULL, 1)
        """
    )
    connection.commit()
    return connection


def test_fast_zone_recipe_projection_uses_existing_zone_evidence() -> None:
    connection = _connection()
    items = [
        {
            "item_id": 100,
            "item_name": "Teaching Item",
            "paths": [
                {
                    "path_kind": "vendor",
                    "vendor_max_count": 1,
                    "chance_percent": None,
                    "source": {"entity_kind": "creature", "entity_id": 10},
                }
            ],
        }
    ]
    quests = {
        "given": [
            {
                "quest_id": 200,
                "quest_name": "Quest Here",
                "role": "giver",
                "source": {"entity_kind": "creature", "entity_id": 10},
            }
        ],
        "finished": [],
        "objectives": [],
    }
    trainers = {
        "known": [
            {
                "recipe_id": 2,
                "recipe_name": "Recipe Two",
                "trainer_kind": "direct",
                "native_trainer_entry": 10,
                "creature_id": 10,
                "resolved": True,
            }
        ],
        "unknown_relations": [],
    }

    payload = project_zone_recipes(
        connection,
        zone_id=42,
        items=items,
        quests=quests,
        trainers=trainers,
        limit=100,
    )

    assert payload["teaching_item"]["summary"]["known_match_count"] == 1
    assert payload["teaching_item"]["results"][0]["recipe"]["recipe_id"] == 1
    assert payload["trainer"]["summary"]["known_match_count"] == 1
    assert payload["trainer"]["results"][0]["recipe"]["recipe_id"] == 2
    giver = payload["quest_reward_spell"]["giver"]
    assert giver["summary"]["known_match_count"] == 1
    assert giver["results"][0]["recipe"]["recipe_id"] == 3
    assert giver["summary"]["unknown_count"] == 3

    assert payload["quest_reward_spell"]["finisher"]["summary"]["known_match_count"] == 0
    assert payload["quest_reward_spell"]["objective"]["summary"]["known_match_count"] == 0


def test_fast_zone_recipe_projection_limit_reports_truncation() -> None:
    connection = _connection()
    connection.execute(
        """
        INSERT INTO recipe_teaching_items(
            recipe_id, native_item_id, item_id, item_spell_slot,
            acquisition_spell_id, learning_proof_kind,
            learn_effect_index, server_learn_active
        ) VALUES (4, 100, 100, 1, 504, 'learn_spell_effect', 0, 1)
        """
    )
    connection.commit()

    payload = project_zone_recipes(
        connection,
        zone_id=42,
        items=[{"item_id": 100, "item_name": "Teaching Item", "paths": []}],
        quests={"given": [], "finished": [], "objectives": []},
        trainers={"known": [], "unknown_relations": []},
        limit=1,
    )

    teaching = payload["teaching_item"]
    assert teaching["summary"]["known_match_count"] == 2
    assert teaching["summary"]["returned_count"] == 1
    assert teaching["truncated_known_matches"] is True
