from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from octogamedb.item_search import MATCH_KNOWN, MATCH_UNKNOWN, NON_MATCH_KNOWN, QUERY_STATES
from octogamedb.recipe_cli import main as recipe_cli_main
from octogamedb.recipe_search import query_recipes, recipe_query_page_to_dict


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE items (item_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE creatures (creature_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE quests (quest_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE spells (
            spell_id INTEGER PRIMARY KEY,
            name TEXT,
            rank_text TEXT
        );
        CREATE TABLE skill_lines (skill_line_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE recipes (
            recipe_id INTEGER PRIMARY KEY,
            crafting_spell_id INTEGER NOT NULL UNIQUE
        );
        CREATE TABLE recipe_skill_lines (
            recipe_id INTEGER NOT NULL,
            skill_line_ability_id INTEGER NOT NULL,
            skill_line_id INTEGER NOT NULL,
            required_skill_value INTEGER NOT NULL,
            PRIMARY KEY (recipe_id, skill_line_ability_id)
        );
        CREATE TABLE recipe_outputs (
            recipe_id INTEGER NOT NULL,
            effect_index INTEGER NOT NULL,
            native_item_id INTEGER NOT NULL,
            item_id INTEGER,
            PRIMARY KEY (recipe_id, effect_index)
        );
        CREATE TABLE recipe_reagents (
            recipe_id INTEGER NOT NULL,
            reagent_index INTEGER NOT NULL,
            native_item_id INTEGER NOT NULL,
            item_id INTEGER,
            required_quantity INTEGER NOT NULL,
            PRIMARY KEY (recipe_id, reagent_index)
        );
        CREATE TABLE recipe_teaching_items (
            recipe_id INTEGER NOT NULL,
            native_item_id INTEGER NOT NULL,
            item_id INTEGER,
            item_spell_slot INTEGER NOT NULL,
            spell_trigger INTEGER,
            spell_charges INTEGER,
            acquisition_spell_id INTEGER NOT NULL,
            learning_proof_kind TEXT NOT NULL,
            learn_effect_index INTEGER,
            server_learn_active INTEGER,
            PRIMARY KEY (recipe_id, native_item_id, item_spell_slot, acquisition_spell_id)
        );
        CREATE TABLE recipe_trainer_sources (
            recipe_id INTEGER NOT NULL,
            trainer_kind TEXT NOT NULL,
            native_trainer_entry INTEGER NOT NULL,
            creature_id INTEGER,
            trainer_template_id INTEGER,
            acquisition_spell_id INTEGER NOT NULL,
            learning_proof_kind TEXT NOT NULL,
            learn_effect_index INTEGER,
            server_learn_active INTEGER,
            spell_cost INTEGER NOT NULL,
            required_skill_line_id INTEGER,
            required_skill_value INTEGER NOT NULL,
            required_character_level INTEGER NOT NULL,
            PRIMARY KEY (recipe_id, trainer_kind, native_trainer_entry, acquisition_spell_id)
        );
        CREATE TABLE recipe_quest_learning_sources (
            recipe_id INTEGER NOT NULL,
            native_quest_id INTEGER NOT NULL,
            quest_id INTEGER,
            reward_spell_field TEXT NOT NULL,
            acquisition_spell_id INTEGER NOT NULL,
            learning_proof_kind TEXT NOT NULL,
            learn_effect_index INTEGER,
            server_learn_active INTEGER,
            PRIMARY KEY (recipe_id, native_quest_id, reward_spell_field, acquisition_spell_id)
        );

        CREATE TABLE data_sources (
            id INTEGER PRIMARY KEY,
            source_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            source_kind TEXT NOT NULL
        );
        CREATE TABLE observation_groups (
            id INTEGER PRIMARY KEY,
            subject_kind TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            fact_instance_key TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE source_observations (
            id INTEGER PRIMARY KEY,
            observation_group_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            source_revision TEXT NOT NULL,
            source_record_type TEXT,
            raw_identifier TEXT,
            value_json TEXT NOT NULL,
            authority_tier INTEGER
        );
        CREATE TABLE canonical_selections (
            observation_group_id INTEGER PRIMARY KEY,
            observation_id INTEGER NOT NULL,
            selection_policy TEXT,
            selection_reason TEXT NOT NULL
        );
        """
    )


def _seed(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT INTO items(item_id, name) VALUES (?, ?)",
        (
            (500, "Forged Blade"),
            (501, "Iron Bar"),
            (510, "Plans: Forged Blade"),
            (600, "Mystery Flask"),
            (601, "Silverleaf"),
        ),
    )
    connection.executemany(
        "INSERT INTO creatures(creature_id, name) VALUES (?, ?)",
        ((700, "Trainer One"), (701, "Template Trainer")),
    )
    connection.execute("INSERT INTO quests(quest_id, name) VALUES (900, 'A Smithing Lesson')")
    connection.executemany(
        "INSERT INTO spells(spell_id, name, rank_text) VALUES (?, ?, ?)",
        (
            (1000, "Forge Blade", None),
            (1100, "Mystery Brew", None),
            (2000, "Teach Forge Blade", None),
            (2001, "Trainer Wrapper", None),
            (2002, "Quest Wrapper", None),
        ),
    )
    connection.executemany(
        "INSERT INTO skill_lines(skill_line_id, name) VALUES (?, ?)",
        ((164, "Blacksmithing"), (171, "Alchemy"), (999, None)),
    )
    connection.executemany(
        "INSERT INTO recipes(recipe_id, crafting_spell_id) VALUES (?, ?)",
        ((1000, 1000), (1100, 1100)),
    )
    connection.executemany(
        """
        INSERT INTO recipe_skill_lines(
            recipe_id, skill_line_ability_id, skill_line_id, required_skill_value
        ) VALUES (?, ?, ?, ?)
        """,
        (
            (1000, 1, 164, 75),
            (1100, 2, 171, 150),
            (1000, 3, 171, 200),
            (1100, 4, 999, 5),
        ),
    )
    connection.executemany(
        """
        INSERT INTO recipe_outputs(recipe_id, effect_index, native_item_id, item_id)
        VALUES (?, ?, ?, ?)
        """,
        ((1000, 0, 500, 500), (1000, 1, 599, None), (1100, 0, 600, 600)),
    )
    connection.executemany(
        """
        INSERT INTO recipe_reagents(
            recipe_id, reagent_index, native_item_id, item_id, required_quantity
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ((1000, 0, 501, 501, 2), (1000, 1, 599, None, 4), (1100, 0, 601, 601, 1)),
    )
    connection.executemany(
        """
        INSERT INTO recipe_teaching_items(
            recipe_id, native_item_id, item_id, item_spell_slot, spell_trigger, spell_charges,
            acquisition_spell_id, learning_proof_kind, learn_effect_index, server_learn_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (1000, 510, 510, 0, 0, 0, 2000, "octo_dbc_learn_spell", 1, None),
            (1100, 699, None, 1, 0, 0, 2000, "octo_dbc_learn_spell", 2, None),
        ),
    )
    connection.executemany(
        """
        INSERT INTO recipe_trainer_sources(
            recipe_id, trainer_kind, native_trainer_entry, creature_id, trainer_template_id,
            acquisition_spell_id, learning_proof_kind, learn_effect_index, server_learn_active,
            spell_cost, required_skill_line_id, required_skill_value, required_character_level
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                1000, "direct", 700, 700, None, 2001, "octo_dbc_learn_spell",
                0, None, 1234, 164, 50, 10,
            ),
            (
                1000, "template", 701, 701, 55, 2001, "octo_dbc_learn_spell",
                0, None, 2345, 164, 60, 12,
            ),
            (
                1100, "direct", 799, None, None, 2001, "octo_dbc_learn_spell",
                0, None, 3456, 171, 100, 20,
            ),
        ),
    )
    connection.executemany(
        """
        INSERT INTO recipe_quest_learning_sources(
            recipe_id, native_quest_id, quest_id, reward_spell_field, acquisition_spell_id,
            learning_proof_kind, learn_effect_index, server_learn_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (1000, 900, 900, "RewSpellCast", 2002, "octo_dbc_learn_spell", 2, None),
            (1000, 999, None, "RewSpell", 2002, "octo_dbc_learn_spell", 1, None),
        ),
    )

    connection.executemany(
        "INSERT INTO data_sources(id, source_key, display_name, source_kind) VALUES (?, ?, ?, ?)",
        (
            (1, "octo-client-dbc", "Octo DBC", "client"),
            (2, "tortoise-world", "Tortoise world", "server"),
        ),
    )
    next_id = 1

    def observe(
        subject_kind: str,
        subject_key: int,
        fact_key: str,
        instance_key: str,
        value: object,
        *,
        source_id: int = 1,
    ) -> None:
        nonlocal next_id
        group_id = next_id
        next_id += 1
        connection.execute(
            """
            INSERT INTO observation_groups(
                id, subject_kind, subject_key, fact_key, fact_instance_key
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (group_id, subject_kind, str(subject_key), fact_key, instance_key),
        )
        connection.execute(
            """
            INSERT INTO source_observations(
                id, observation_group_id, source_id, source_revision, source_record_type,
                raw_identifier, value_json, authority_tier
            ) VALUES (?, ?, ?, 'fixture-revision', 'fixture-row', ?, ?, 1)
            """,
            (
                group_id, group_id, source_id, f"fixture:{group_id}",
                json.dumps(value, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO canonical_selections(
                observation_group_id, observation_id, selection_policy, selection_reason
            ) VALUES (?, ?, 'fixture-policy', 'Fixture selected evidence.')
            """,
            (group_id, group_id),
        )

    for recipe_id in (1000, 1100):
        observe("recipe", recipe_id, "presence", "", True)
        observe("spell", recipe_id, "name", "", f"spell-{recipe_id}")
    observe(
        "recipe",
        1000,
        "skill_line_membership",
        "skill-line-ability:1",
        {"target": {"kind": "skill_line", "key": 164}, "attributes": {"required_skill_value": 75}},
    )
    observe(
        "recipe",
        1100,
        "skill_line_membership",
        "skill-line-ability:2",
        {"target": {"kind": "skill_line", "key": 171}, "attributes": {"required_skill_value": 150}},
    )
    observe(
        "recipe",
        1000,
        "skill_line_membership",
        "skill-line-ability:3",
        {
            "target": {"kind": "skill_line", "key": 171},
            "attributes": {"skill_line_ability_id": 3, "required_skill_value": 200},
        },
    )
    observe(
        "recipe",
        1100,
        "skill_line_membership",
        "skill-line-ability:4",
        {
            "target": {"kind": "skill_line", "key": 999},
            "attributes": {"skill_line_ability_id": 4, "required_skill_value": 5},
        },
    )
    for effect_index, native_item_id in ((0, 500), (1, 599)):
        observe(
            "recipe",
            1000,
            "crafted_output",
            f"effect:{effect_index}",
            {
                "target": {"kind": "item", "key": native_item_id},
                "attributes": {"effect_index": effect_index},
            },
        )
    observe(
        "recipe",
        1100,
        "crafted_output",
        "effect:0",
        {"target": {"kind": "item", "key": 600}, "attributes": {"effect_index": 0}},
    )
    for reagent_index, native_item_id, quantity in ((0, 501, 2), (1, 599, 4)):
        observe(
            "recipe",
            1000,
            "reagent",
            f"slot:{reagent_index}",
            {
                "target": {"kind": "item", "key": native_item_id},
                "attributes": {"reagent_index": reagent_index, "required_quantity": quantity},
            },
        )
    observe(
        "recipe",
        1100,
        "reagent",
        "slot:0",
        {
            "target": {"kind": "item", "key": 601},
            "attributes": {"reagent_index": 0, "required_quantity": 1},
        },
    )
    observe(
        "recipe",
        1000,
        "teaching_item",
        "item:510:slot:0:spell:2000",
        {
            "target": {"kind": "item", "key": 510},
            "attributes": {
                "acquisition_spell_id": 2000,
                "learning_proof_kind": "octo_dbc_learn_spell",
            },
        },
        source_id=2,
    )
    observe(
        "recipe",
        1100,
        "teaching_item",
        "item:699:slot:1:spell:2000",
        {
            "target": {"kind": "item", "key": 699},
            "attributes": {
                "acquisition_spell_id": 2000,
                "learning_proof_kind": "octo_dbc_learn_spell",
            },
        },
        source_id=2,
    )
    observe(
        "recipe",
        1000,
        "trainer_source",
        "direct:creature:700:template:0:spell:2001",
        {
            "target": {"kind": "creature", "key": 700},
            "attributes": {"trainer_kind": "direct", "spell_cost": 1234},
        },
        source_id=2,
    )
    observe(
        "recipe",
        1000,
        "trainer_source",
        "template:creature:701:template:55:spell:2001",
        {
            "target": {"kind": "creature", "key": 701},
            "attributes": {"trainer_kind": "template", "trainer_template_id": 55},
        },
        source_id=2,
    )
    observe(
        "recipe",
        1100,
        "trainer_source",
        "direct:creature:799:template:0:spell:2001",
        {"target": {"kind": "creature", "key": 799}, "attributes": {"trainer_kind": "direct"}},
        source_id=2,
    )
    observe(
        "recipe",
        1000,
        "quest_learning_source",
        "quest:900:RewSpellCast:spell:2002",
        {
            "target": {"kind": "quest", "key": 900},
            "attributes": {"reward_spell_field": "RewSpellCast", "acquisition_spell_id": 2002},
        },
        source_id=2,
    )
    observe(
        "recipe",
        1000,
        "quest_learning_source",
        "quest:999:RewSpell:spell:2002",
        {
            "target": {"kind": "quest", "key": 999},
            "attributes": {"reward_spell_field": "RewSpell", "acquisition_spell_id": 2002},
        },
        source_id=2,
    )
    connection.commit()


def _memory_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    _create_schema(connection)
    _seed(connection)
    return connection


def _file_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        _create_schema(connection)
        _seed(connection)
    finally:
        connection.close()


def _install_composition_stubs(monkeypatch) -> None:
    import octogamedb.recipe_search as module

    def fake_query_item_acquisitions(
        connection: sqlite3.Connection,
        *,
        item_id: int | None = None,
        zone_id: int | None = None,
        map_id: int | None = None,
        include_states=(MATCH_KNOWN,),
        limit: int = 100,
    ):
        del connection, include_states, limit
        sources = []
        state = MATCH_UNKNOWN
        if item_id == 510:
            sources = [
                {
                    "source_kind": "creature",
                    "source_id": 10,
                    "acquisition_paths": [
                        {"path_kind": "direct", "chance_percent": 15.0},
                        {"path_kind": "reference", "chance_percent": 5.0},
                    ],
                },
                {
                    "source_kind": "creature",
                    "source_id": 11,
                    "acquisition_paths": [{"path_kind": "vendor", "chance_percent": None}],
                },
            ]
            if zone_id is None and map_id is None or zone_id == 10 and map_id == 1:
                state = MATCH_KNOWN
        return {
            "results": [
                {
                    "combined_match_state": state,
                    "sources": sources,
                    "matching_sources": sources if state == MATCH_KNOWN else [],
                }
            ]
        }

    def fake_item_acquisition_page_to_dict(page):
        return page

    def fake_find_world_locations(connection: sqlite3.Connection, query: str):
        del connection
        if query == "Trainer One":
            return [
                {
                    "entity_kind": "creature",
                    "entity_id": 700,
                    "name": query,
                    "spawn_key": "trainer-700-a",
                    "zone_id": 20,
                    "map_id": 2,
                    "sources": [{"source_key": "world-fixture", "source_revision": "r1"}],
                }
            ]
        return []

    def fake_query_quests(
        connection: sqlite3.Connection,
        *,
        quest_id: int | None = None,
        giver_zone_id: int | None = None,
        giver_map_id: int | None = None,
        finisher_zone_id: int | None = None,
        finisher_map_id: int | None = None,
        objective_zone_id: int | None = None,
        objective_map_id: int | None = None,
        include_states=(MATCH_KNOWN,),
        limit: int = 100,
    ):
        del connection, include_states, limit
        if quest_id != 900:
            return SimpleNamespace(results=())
        requested = any(
            value is not None
            for value in (
                giver_zone_id,
                giver_map_id,
                finisher_zone_id,
                finisher_map_id,
                objective_zone_id,
                objective_map_id,
            )
        )
        state = MATCH_KNOWN
        if requested:
            known = (
                (giver_zone_id in (None, 30) and giver_map_id in (None, 3))
                and (finisher_zone_id in (None, 40) and finisher_map_id in (None, 4))
                and (objective_zone_id in (None, 50) and objective_map_id in (None, 5))
            )
            state = MATCH_KNOWN if known else MATCH_UNKNOWN
        quest = {
            "quest_id": 900,
            "name": "A Smithing Lesson",
            "endpoints": [{"endpoint_kind": "giver", "locations": [{"zone_id": 30, "map_id": 3}]}],
            "progression": {"prerequisite_set": {"semantics": "any_of"}, "follow_ups": []},
            "objectives": {"objectives": []},
        }
        return SimpleNamespace(results=(SimpleNamespace(match_state=state, quest=quest),))

    monkeypatch.setattr(module, "query_item_acquisitions", fake_query_item_acquisitions)
    monkeypatch.setattr(module, "item_acquisition_page_to_dict", fake_item_acquisition_page_to_dict)
    monkeypatch.setattr(module, "find_world_locations", fake_find_world_locations)
    monkeypatch.setattr(module, "query_quests", fake_query_quests)


def test_recipe_filters_and_slots_preserve_exact_p4_facts(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        page = query_recipes(
            connection,
            recipe_id=1000,
            name_contains="forge",
            skill_line_id=164,
            skill_line_name="smith",
            min_required_skill=75,
            max_required_skill=75,
            output_item_id=500,
            reagent_item_id=501,
        )
    finally:
        connection.close()

    assert page.summary.returned_count == 1
    result = page.results[0]
    assert result.match_state == MATCH_KNOWN
    recipe = result.recipe
    assert recipe["recipe_id"] == recipe["crafting_spell_id"] == 1000
    assert recipe["skill_lines"][0]["required_skill_value"] == 75
    assert [
        (row["effect_index"], row["native_item_id"], row["resolved"])
        for row in recipe["outputs"]
    ] == [
        (0, 500, True),
        (1, 599, False),
    ]
    assert [
        (row["reagent_index"], row["native_item_id"], row["required_quantity"], row["resolved"])
        for row in recipe["reagents"]
    ] == [(0, 501, 2, True), (1, 599, 4, False)]
    assert recipe["outputs"][1]["unresolved_reason"] == "missing_canonical_item_identity"
    assert recipe["reagents"][1]["provenance"]["source_key"] == "octo-client-dbc"


def test_complete_p4_predicates_can_prove_non_match(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        page = query_recipes(
            connection,
            skill_line_id=164,
            output_item_id=500,
            reagent_item_id=501,
            include_states=QUERY_STATES,
        )
    finally:
        connection.close()

    states = {result.recipe["recipe_id"]: result.match_state for result in page.results}
    assert states == {1000: MATCH_KNOWN, 1100: NON_MATCH_KNOWN}


def test_learning_paths_remain_separate_and_compose_existing_p7_views(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        page = query_recipes(connection, recipe_id=1000)
    finally:
        connection.close()

    learning = page.results[0].recipe["learning"]
    teaching = learning["teaching_items"][0]
    assert teaching["native_item_id"] == teaching["item_id"] == 510
    assert teaching["learning_proof_kind"] == "octo_dbc_learn_spell"
    assert teaching["acquisition_spell_id"] == 2000
    assert teaching["provenance"]["source_key"] == "tortoise-world"
    path_kinds = {
        path["path_kind"]
        for source in teaching["acquisition_composition"]["sources"]
        for path in source["acquisition_paths"]
    }
    assert path_kinds == {"direct", "reference", "vendor"}

    trainers = learning["trainers"]
    assert [row["trainer_kind"] for row in trainers] == ["direct", "template"]
    direct = trainers[0]
    assert direct["spell_cost"] == 1234
    assert direct["required_skill_line_id"] == 164
    assert direct["required_skill_value"] == 50
    assert direct["required_character_level"] == 10
    assert direct["geography_state"] == MATCH_KNOWN
    assert direct["locations"][0]["zone_id"] == 20
    template = trainers[1]
    assert template["trainer_template_id"] == 55
    assert template["geography_state"] == MATCH_UNKNOWN

    quest = learning["quest_reward_spells"][0]
    assert quest["reward_spell_field"] == "RewSpellCast"
    assert quest["quest_context"]["quest_id"] == 900
    assert quest["quest_context_state"] == MATCH_KNOWN


def test_derived_geography_filters_use_positive_evidence_and_unknown(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        known = query_recipes(
            connection,
            recipe_id=1000,
            learning_kinds=("teaching_item", "trainer", "quest_reward_spell"),
            teaching_zone_id=10,
            teaching_map_id=1,
            trainer_zone_id=20,
            trainer_map_id=2,
            quest_giver_zone_id=30,
            quest_giver_map_id=3,
            include_states=QUERY_STATES,
        )
        unknown = query_recipes(
            connection,
            recipe_id=1000,
            trainer_zone_id=99,
            trainer_map_id=9,
            include_states=QUERY_STATES,
        )
        missing_kind = query_recipes(
            connection,
            recipe_id=1100,
            learning_kinds=("quest_reward_spell",),
            include_states=QUERY_STATES,
        )
    finally:
        connection.close()

    assert known.results[0].match_state == MATCH_KNOWN
    assert unknown.results[0].match_state == MATCH_UNKNOWN
    assert any(
        predicate.reason == "no_known_matching_trainer_location_negative_not_proven"
        for predicate in unknown.results[0].predicates
    )
    missing_recipe = next(
        result for result in missing_kind.results if result.recipe["recipe_id"] == 1100
    )
    assert missing_recipe.match_state == MATCH_UNKNOWN
    assert any(
        predicate.reason == "no_known_matching_learning_source_negative_not_proven"
        for predicate in missing_recipe.predicates
    )


def test_unresolved_learning_targets_are_retained(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        page = query_recipes(connection, recipe_id=1100)
    finally:
        connection.close()

    recipe = page.results[0].recipe
    teaching = recipe["learning"]["teaching_items"][0]
    trainer = recipe["learning"]["trainers"][0]
    assert teaching["native_item_id"] == 699
    assert teaching["item_id"] is None
    assert teaching["resolved"] is False
    assert teaching["acquisition_coverage_state"] == MATCH_UNKNOWN
    assert trainer["native_trainer_entry"] == 799
    assert trainer["creature_id"] is None
    assert trainer["resolved"] is False
    assert trainer["geography_state"] == MATCH_UNKNOWN


def test_skill_constraints_must_match_the_same_membership(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        page = query_recipes(
            connection,
            recipe_id=1000,
            skill_line_name="smith",
            min_required_skill=200,
            include_states=QUERY_STATES,
        )
    finally:
        connection.close()

    recipe = next(result for result in page.results if result.recipe["recipe_id"] == 1000)
    assert recipe.match_state == NON_MATCH_KNOWN


def test_missing_skill_line_name_keeps_name_filter_unknown(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        page = query_recipes(
            connection,
            recipe_id=1100,
            skill_line_id=999,
            skill_line_name="unknown profession",
            include_states=QUERY_STATES,
        )
    finally:
        connection.close()

    recipe = next(result for result in page.results if result.recipe["recipe_id"] == 1100)
    assert recipe.match_state == MATCH_UNKNOWN
    assert any(
        predicate.reason == "matching_recipe_skill_row_name_not_materialized"
        for predicate in recipe.predicates
    )


def test_unresolved_quest_learning_target_is_retained(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        page = query_recipes(connection, recipe_id=1000)
    finally:
        connection.close()

    unresolved = next(
        row
        for row in page.results[0].recipe["learning"]["quest_reward_spells"]
        if row["native_quest_id"] == 999
    )
    assert unresolved["quest_id"] is None
    assert unresolved["resolved"] is False
    assert unresolved["quest_context"] is None
    assert unresolved["quest_context_state"] == MATCH_UNKNOWN
    assert unresolved["provenance"]["source_key"] == "tortoise-world"


def test_quest_geography_roles_do_not_cross_satisfy(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        giver = query_recipes(
            connection,
            recipe_id=1000,
            quest_giver_zone_id=30,
            quest_giver_map_id=3,
            include_states=QUERY_STATES,
        )
        finisher = query_recipes(
            connection,
            recipe_id=1000,
            quest_finisher_zone_id=30,
            quest_finisher_map_id=3,
            include_states=QUERY_STATES,
        )
    finally:
        connection.close()

    giver_result = next(r for r in giver.results if r.recipe["recipe_id"] == 1000)
    assert giver_result.match_state == MATCH_KNOWN
    assert (
        next(r for r in finisher.results if r.recipe["recipe_id"] == 1000).match_state
        == MATCH_UNKNOWN
    )


def test_ordering_limit_and_json_are_deterministic(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        first = recipe_query_page_to_dict(
            query_recipes(connection, include_states=QUERY_STATES, sort_by="name", limit=2)
        )
        second = recipe_query_page_to_dict(
            query_recipes(connection, include_states=QUERY_STATES, sort_by="name", limit=2)
        )
    finally:
        connection.close()

    assert first == second
    assert [row["recipe"]["recipe_id"] for row in first["results"]] == [1000, 1100]
    assert json.loads(json.dumps(first, sort_keys=True)) == first


def test_cli_json_opens_database_read_only(tmp_path: Path, capsys, monkeypatch):
    _install_composition_stubs(monkeypatch)
    db_path = tmp_path / "fixture.sqlite3"
    _file_database(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert recipe_cli_main(["--db", str(db_path), "--recipe-id", "1000", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["results"][0]["recipe"]["recipe_id"] == 1000
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_relation_provenance_falls_back_to_selected_value_when_instance_key_differs(monkeypatch):
    _install_composition_stubs(monkeypatch)
    connection = _memory_connection()
    try:
        connection.execute(
            """
            UPDATE observation_groups
            SET fact_instance_key = 'protected-custom-effect-key'
            WHERE subject_kind = 'recipe' AND subject_key = '1000'
              AND fact_key = 'crafted_output' AND fact_instance_key = 'effect:0'
            """
        )
        page = query_recipes(connection, recipe_id=1000)
    finally:
        connection.close()

    output = next(row for row in page.results[0].recipe["outputs"] if row["effect_index"] == 0)
    assert output["provenance"]["source_key"] == "octo-client-dbc"
    assert output["provenance"]["selected_value"]["target"]["key"] == 500
