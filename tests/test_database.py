from __future__ import annotations

import sqlite3

import pytest

import octogamedb.db.migrations as migration_module
from octogamedb.db import Migration, apply_migrations, connect_database, get_applied_migrations

CURRENT_MIGRATIONS = (
    (1, "0001_import_metadata.sql"),
    (2, "0002_provenance_primitives.sql"),
    (3, "0003_world_foundation.sql"),
    (4, "0004_items_acquisition.sql"),
    (5, "0005_reference_loot.sql"),
    (6, "0006_vendor_items.sql"),
    (7, "0007_quests.sql"),
    (8, "0008_quest_progression.sql"),
    (9, "0009_quest_objectives.sql"),
    (10, "0010_quest_item_facts.sql"),
    (11, "0011_recipe_identity.sql"),
    (12, "0012_recipe_reagents.sql"),
    (13, "0013_recipe_acquisition_sources.sql"),
)
CURRENT_MIGRATION_VERSIONS = [version for version, _ in CURRENT_MIGRATIONS]

OBJECTIVE_TABLES = (
    "quest_objective_sets",
    "quest_creature_objectives",
    "quest_gameobject_objectives",
    "quest_item_objectives",
    "quest_item_use_objectives",
    "area_triggers",
    "area_trigger_locations",
    "quest_area_trigger_objectives",
    "quest_zone_objectives",
    "item_use_target_sets",
    "item_use_creature_targets",
    "item_use_gameobject_targets",
)

QUEST_ITEM_FACT_TABLES = (
    "quest_required_items",
    "quest_required_sources",
    "quest_provided_items",
    "quest_reward_items",
    "quest_choice_reward_sets",
    "quest_choice_reward_items",
)

RECIPE_ACQUISITION_TABLES = (
    "recipe_teaching_items",
    "recipe_trainer_sources",
    "recipe_quest_learning_sources",
)


def test_fresh_initialization_creates_foundation_schema(tmp_path):
    db_path = tmp_path / "nested" / "octogamedb.sqlite3"
    with connect_database(db_path) as connection:
        applied = apply_migrations(connection)
        assert [migration.version for migration in applied] == CURRENT_MIGRATION_VERSIONS
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert db_path.exists()
    assert {
        "schema_migrations",
        "data_sources",
        "import_batches",
        "observation_groups",
        "source_observations",
        "observation_import_batches",
        "canonical_selections",
        "maps",
        "zones",
        "creatures",
        "creature_spawns",
        "gameobjects",
        "gameobject_spawns",
        "items",
        "creature_loot",
        "gameobject_loot",
        "loot_references",
        "item_reference_loot",
        "reference_loot_creatures",
        "reference_loot_gameobjects",
        "vendor_items",
        "quests",
        "quest_creature_endpoints",
        "quest_gameobject_endpoints",
        "quest_prerequisite_sets",
        "quest_prerequisite_set_members",
        "quest_close_sets",
        "quest_close_set_members",
        "recipe_reagents",
        *RECIPE_ACQUISITION_TABLES,
        *OBJECTIVE_TABLES,
        *QUEST_ITEM_FACT_TABLES,
    } <= tables


def test_repeat_initialization_is_idempotent(tmp_path):
    db_path = tmp_path / "octogamedb.sqlite3"
    with connect_database(db_path) as connection:
        assert len(apply_migrations(connection)) == len(CURRENT_MIGRATIONS)
        assert apply_migrations(connection) == ()
        assert get_applied_migrations(connection) == CURRENT_MIGRATIONS


def test_foreign_keys_are_enforced(tmp_path):
    db_path = tmp_path / "octogamedb.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO import_batches(source_id, status)
                VALUES (9999, 'running')
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO item_reference_loot(item_id, reference_loot_id, chance_percent)
                VALUES (1, 1, 10)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO vendor_items(vendor_creature_id, item_id)
                VALUES (1, 1)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO quest_creature_endpoints(quest_id, endpoint_kind, creature_id)
                VALUES (1, 'giver', 1)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO quest_gameobject_endpoints(quest_id, endpoint_kind, gameobject_id)
                VALUES (1, 'finisher', 1)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO quest_prerequisite_sets(
                    quest_id, requirement_mode, selected_set_present, selected_member_count
                ) VALUES (1, 'any_of', 1, 1)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO quest_close_sets(
                    quest_id, set_semantics, selected_set_present, selected_member_count
                ) VALUES (1, 'exclusive_group_member_set', 1, 1)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO quest_objective_sets(
                    quest_id, selected_set_present, selected_member_count
                ) VALUES (1, 1, 1)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO area_trigger_locations(
                    area_trigger_id, source_index, zone_id, coordinate_space, x, y
                ) VALUES (1, 1, 1, 'zone_percent', 1.0, 1.0)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO item_use_creature_targets(item_id, creature_id, spell_id)
                VALUES (1, 1, 1)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO quest_required_items(quest_id, item_id, quantity) VALUES (1, 1, 1)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO quest_choice_reward_sets(quest_id, selected_member_count) VALUES (1, 1)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO recipe_teaching_items(
                    recipe_id, native_item_id, item_spell_slot, acquisition_spell_id,
                    learning_proof_kind, learn_effect_index
                ) VALUES (1, 1, 0, 1, 'octo_dbc_learn_spell', 0)
                """
            )


def test_quest_endpoint_kind_constraint(tmp_path):
    db_path = tmp_path / "quest-constraint.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        connection.execute("INSERT INTO quests(quest_id, name) VALUES (1, 'Quest')")
        connection.execute("INSERT INTO creatures(creature_id, name) VALUES (2, 'Creature')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO quest_creature_endpoints(quest_id, endpoint_kind, creature_id)
                VALUES (1, 'objective', 2)
                """
            )


def test_quest_progression_set_constraints_and_cascade(tmp_path):
    db_path = tmp_path / "quest-progression-constraints.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        connection.execute("INSERT INTO quests(quest_id, name) VALUES (1, 'Quest 1')")
        connection.execute("INSERT INTO quests(quest_id, name) VALUES (2, 'Quest 2')")
        connection.execute(
            """
            INSERT INTO quest_prerequisite_sets(
                quest_id, requirement_mode, selected_set_present, selected_member_count
            ) VALUES (1, 'any_of', 1, 1)
            """
        )
        connection.execute(
            "INSERT INTO quest_prerequisite_set_members(quest_id, member_quest_id) VALUES (1, 2)"
        )
        connection.execute(
            """
            INSERT INTO quest_close_sets(
                quest_id, set_semantics, selected_set_present, selected_member_count
            ) VALUES (1, 'exclusive_group_member_set', 1, 2)
            """
        )
        connection.execute(
            "INSERT INTO quest_close_set_members(quest_id, member_quest_id) VALUES (1, 1)"
        )
        connection.execute(
            "INSERT INTO quest_close_set_members(quest_id, member_quest_id) VALUES (1, 2)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO quest_prerequisite_sets(
                    quest_id, requirement_mode, selected_set_present, selected_member_count
                ) VALUES (2, 'all_of', 1, 1)
                """
            )
        connection.execute("DELETE FROM quests WHERE quest_id = 2")
        assert connection.execute(
            "SELECT COUNT(*) FROM quest_prerequisite_set_members WHERE quest_id = 1"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM quest_close_set_members WHERE quest_id = 1"
        ).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_source_and_import_batch_constraints(tmp_path):
    db_path = tmp_path / "octogamedb.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        cursor = connection.execute(
            """
            INSERT INTO data_sources(source_key, display_name, source_kind)
            VALUES ('pfquest', 'pfQuest', 'lua')
            """
        )
        source_id = cursor.lastrowid
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO data_sources(source_key, display_name, source_kind)
                VALUES ('pfquest', 'Duplicate', 'lua')
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO import_batches(
                    source_id, status, rows_read, rows_accepted, rows_skipped
                )
                VALUES (?, 'running', 1, 1, 1)
                """,
                (source_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO import_batches(source_id, status, finished_at)
                VALUES (?, 'running', '2026-08-24T00:00:00Z')
                """,
                (source_id,),
            )
        connection.execute(
            """
            INSERT INTO import_batches(
                source_id,
                source_revision,
                status,
                importer_version,
                rows_read,
                rows_accepted
            )
            VALUES (?, 'rev-1', 'running', 'test-importer/1', 3, 3)
            """,
            (source_id,),
        )


def test_failed_transaction_is_rolled_back(tmp_path):
    db_path = tmp_path / "octogamedb.sqlite3"
    with pytest.raises(RuntimeError), connect_database(db_path) as connection:
        apply_migrations(connection)
        connection.execute(
            """
            INSERT INTO data_sources(source_key, display_name, source_kind)
            VALUES ('temp', 'Temporary', 'test')
            """
        )
        raise RuntimeError("force rollback")
    with connect_database(db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM data_sources WHERE source_key = 'temp'"
            ).fetchone()[0]
            == 0
        )


def test_failed_migration_is_not_recorded(tmp_path, monkeypatch):
    db_path = tmp_path / "failed-migration.sqlite3"
    bad_migration = Migration(
        version=1,
        name="0001_broken.sql",
        sql="CREATE TABLE partial_table(id INTEGER PRIMARY KEY); INVALID SQL;",
    )
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: (bad_migration,))
    with connect_database(db_path) as connection:
        with pytest.raises(sqlite3.OperationalError):
            apply_migrations(connection)
        recorded = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
        ).fetchone()[0]
        partial_table = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'partial_table'"
        ).fetchone()[0]
        assert recorded == 0
        assert partial_table == 0


def test_existing_version_one_database_upgrades_to_current_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "upgrade.sqlite3"
    all_migrations = migration_module.discover_migrations()
    assert [migration.version for migration in all_migrations] == CURRENT_MIGRATION_VERSIONS
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: (all_migrations[0],))
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == [1]
        assert get_applied_migrations(connection) == ((1, "0001_import_metadata.sql"),)
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations)
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == CURRENT_MIGRATION_VERSIONS[1:]
        assert get_applied_migrations(connection) == CURRENT_MIGRATIONS
        for table in (
            "source_observations",
            "creature_spawns",
            "creature_loot",
            "loot_references",
            "item_reference_loot",
            "vendor_items",
            "quests",
            "quest_creature_endpoints",
            "quest_gameobject_endpoints",
            "quest_prerequisite_sets",
            "quest_prerequisite_set_members",
            "quest_close_sets",
            "quest_close_set_members",
            "recipe_reagents",
            *RECIPE_ACQUISITION_TABLES,
            *OBJECTIVE_TABLES,
            *QUEST_ITEM_FACT_TABLES,
        ):
            assert connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()[0] == 1


def test_existing_version_four_database_upgrades_reference_vendor_quest_progression_and_objectives_schema(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "upgrade-v4.sqlite3"
    all_migrations = migration_module.discover_migrations()
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations[:4])
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == [1, 2, 3, 4]
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations)
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == CURRENT_MIGRATION_VERSIONS[4:]
        for table in (
            "reference_loot_creatures",
            "vendor_items",
            "quests",
            "quest_prerequisite_sets",
            "quest_close_sets",
            "quest_objective_sets",
            "area_triggers",
            "item_use_target_sets",
            "recipe_reagents",
            *RECIPE_ACQUISITION_TABLES,
            *QUEST_ITEM_FACT_TABLES,
        ):
            assert connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_existing_version_five_database_upgrades_vendor_quest_progression_and_objectives_schema(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "upgrade-v5.sqlite3"
    all_migrations = migration_module.discover_migrations()
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations[:5])
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == [1, 2, 3, 4, 5]
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'vendor_items'"
        ).fetchone()[0] == 0
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations)
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == CURRENT_MIGRATION_VERSIONS[5:]
        assert get_applied_migrations(connection)[-1] == CURRENT_MIGRATIONS[-1]
        for table in (
            "vendor_items",
            "quests",
            "quest_creature_endpoints",
            "quest_prerequisite_sets",
            "quest_objective_sets",
            "recipe_reagents",
            *RECIPE_ACQUISITION_TABLES,
            *QUEST_ITEM_FACT_TABLES,
        ):
            assert connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_existing_version_six_database_upgrades_quest_progression_and_objectives_schema(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "upgrade-v6.sqlite3"
    all_migrations = migration_module.discover_migrations()
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations[:6])
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == [
            1, 2, 3, 4, 5, 6
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'quests'"
        ).fetchone()[0] == 0
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations)
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == CURRENT_MIGRATION_VERSIONS[6:]
        assert get_applied_migrations(connection)[-1] == CURRENT_MIGRATIONS[-1]
        for table in (
            "quests",
            "quest_creature_endpoints",
            "quest_gameobject_endpoints",
            "quest_prerequisite_sets",
            "quest_close_sets",
            "quest_objective_sets",
            "recipe_reagents",
            *RECIPE_ACQUISITION_TABLES,
            *QUEST_ITEM_FACT_TABLES,
        ):
            assert connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_existing_version_seven_database_upgrades_progression_and_objectives_schema(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "upgrade-v7.sqlite3"
    all_migrations = migration_module.discover_migrations()
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations[:7])
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == list(range(1, 8))
        connection.execute("INSERT INTO quests(quest_id, name) VALUES (1, 'Existing quest')")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(quests)")}
        assert "quest_level" not in columns
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations)
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == CURRENT_MIGRATION_VERSIONS[7:]
        row = connection.execute(
            """
            SELECT name, quest_level, minimum_level, race_mask, class_mask
            FROM quests WHERE quest_id = 1
            """
        ).fetchone()
        assert tuple(row) == ("Existing quest", None, None, None, None)
        for table in (
            "quest_prerequisite_sets",
            "quest_prerequisite_set_members",
            "quest_close_sets",
            "quest_close_set_members",
            "recipe_reagents",
            *RECIPE_ACQUISITION_TABLES,
            *OBJECTIVE_TABLES,
            *QUEST_ITEM_FACT_TABLES,
        ):
            assert connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_existing_version_eight_database_upgrades_objective_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "upgrade-v8.sqlite3"
    all_migrations = migration_module.discover_migrations()
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations[:8])
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == list(range(1, 9))
        connection.execute("INSERT INTO quests(quest_id, name) VALUES (1, 'Existing quest')")
        connection.execute("INSERT INTO creatures(creature_id, name) VALUES (2, 'Creature')")
        connection.execute("INSERT INTO gameobjects(gameobject_id, name) VALUES (3, 'Object')")
        connection.execute("INSERT INTO items(item_id, name) VALUES (4, 'Item')")
        connection.execute("INSERT INTO maps(map_id, name) VALUES (5, 'Map')")
        connection.execute("INSERT INTO zones(zone_id, map_id, name) VALUES (6, 5, 'Zone')")
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='quest_objective_sets'"
        ).fetchone()[0] == 0
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations)
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == CURRENT_MIGRATION_VERSIONS[8:]
        assert get_applied_migrations(connection) == CURRENT_MIGRATIONS
        for table in (*OBJECTIVE_TABLES, *QUEST_ITEM_FACT_TABLES, *RECIPE_ACQUISITION_TABLES):
            assert connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'recipe_reagents'"
        ).fetchone()[0] == 1

        connection.execute("INSERT INTO quest_objective_sets VALUES (1, 1, 6)")
        connection.execute("INSERT INTO quest_creature_objectives VALUES (1, 2)")
        connection.execute("INSERT INTO quest_gameobject_objectives VALUES (1, 3)")
        connection.execute("INSERT INTO quest_item_objectives VALUES (1, 4)")
        connection.execute("INSERT INTO quest_item_use_objectives VALUES (1, 4)")
        connection.execute("INSERT INTO area_triggers VALUES (7, 1, 1, 1)")
        connection.execute(
            "INSERT INTO area_trigger_locations VALUES (7, 1, 6, 'zone_percent', 10.0, 20.0)"
        )
        connection.execute("INSERT INTO quest_area_trigger_objectives VALUES (1, 7)")
        connection.execute("INSERT INTO quest_zone_objectives VALUES (1, 6)")
        connection.execute("INSERT INTO item_use_target_sets VALUES (4, 1, 2)")
        connection.execute("INSERT INTO item_use_creature_targets VALUES (4, 2, 123)")
        connection.execute("INSERT INTO item_use_gameobject_targets VALUES (4, 3, 456)")

        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_existing_version_nine_database_upgrades_quest_item_facts_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "upgrade-v9.sqlite3"
    all_migrations = migration_module.discover_migrations()
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations[:9])
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == list(
            range(1, 10)
        )
        connection.execute("INSERT INTO quests(quest_id, name) VALUES (1, 'Existing quest')")
        connection.execute("INSERT INTO items(item_id, name) VALUES (2, 'Existing item')")
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='quest_required_items'"
        ).fetchone()[0] == 0
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: all_migrations)
    with connect_database(db_path) as connection:
        assert [migration.version for migration in apply_migrations(connection)] == CURRENT_MIGRATION_VERSIONS[9:]
        assert get_applied_migrations(connection) == CURRENT_MIGRATIONS
        for table in (*QUEST_ITEM_FACT_TABLES, *RECIPE_ACQUISITION_TABLES):
            assert connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'recipe_reagents'"
        ).fetchone()[0] == 1
        connection.execute(
            "INSERT INTO quest_required_items(quest_id, item_id, quantity) VALUES (1, 2, 3)"
        )
        connection.execute(
            "INSERT INTO quest_required_sources(quest_id, item_id, raw_source_count) "
            "VALUES (1, 2, 0)"
        )
        connection.execute(
            "INSERT INTO quest_provided_items(quest_id, item_id, quantity) VALUES (1, 2, NULL)"
        )
        connection.execute(
            "INSERT INTO quest_reward_items(quest_id, item_id, quantity) VALUES (1, 2, 1)"
        )
        connection.execute(
            "INSERT INTO quest_choice_reward_sets(quest_id, choice_semantics, "
            "selected_member_count) "
            "VALUES (1, 'choose_one', 1)"
        )
        connection.execute(
            "INSERT INTO quest_choice_reward_items(quest_id, item_id, quantity) VALUES (1, 2, 1)"
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
