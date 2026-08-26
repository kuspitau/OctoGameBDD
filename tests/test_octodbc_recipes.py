from __future__ import annotations

import shutil
import sqlite3
import struct
from pathlib import Path

import pytest

from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.octo_dbc_recipes import (
    RecipeDbcParseError,
    compute_octodbc_recipe_revision,
    import_octodbc_recipes,
    inspect_octodbc_recipe_layouts,
    load_octodbc_recipe_slice,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "octo_dbc" / "recipe_slice"


def _write_standard_vanilla_173_spell_variant(source: Path, target: Path) -> None:
    data = source.read_bytes()
    magic, record_count, field_count, record_size, string_size = struct.unpack_from(
        "<4sIIII", data
    )
    assert magic == b"WDBC"
    assert (field_count, record_size) == (176, 704)
    records_start = 20
    strings_start = records_start + record_count * record_size
    strings = data[strings_start:]
    assert len(strings) == string_size

    field_map = {
        0: 0,
        **{60 + i: 61 + i for i in range(3)},
        **{63 + i: 64 + i for i in range(3)},
        **{75 + i: 76 + i for i in range(3)},
        **{102 + i: 106 + i for i in range(3)},
        **{120 + i: 123 + i for i in range(8)},
        **{129 + i: 132 + i for i in range(8)},
    }
    out_records = bytearray(record_count * 692)
    for record_index in range(record_count):
        source_record = records_start + record_index * record_size
        target_record = record_index * 692
        for target_field, source_field in field_map.items():
            source_offset = source_record + source_field * 4
            target_offset = target_record + target_field * 4
            out_records[target_offset : target_offset + 4] = data[
                source_offset : source_offset + 4
            ]

    header = struct.pack("<4sIIII", b"WDBC", record_count, 173, 692, string_size)
    target.write_bytes(header + out_records + strings)




def _rewrite_skill_line_ability_skill_id(path: Path, record_id: int, skill_line_id: int) -> None:
    data = bytearray(path.read_bytes())
    magic, record_count, field_count, record_size, string_size = struct.unpack_from(
        "<4sIIII", data
    )
    assert magic == b"WDBC"
    assert (field_count, record_size) == (15, 60)
    records_start = 20
    found = False
    for record_index in range(record_count):
        record_start = records_start + record_index * record_size
        current_id = struct.unpack_from("<I", data, record_start)[0]
        if current_id != record_id:
            continue
        struct.pack_into("<I", data, record_start + 4, skill_line_id)
        found = True
        break
    assert found, f"SkillLineAbility record {record_id} not found"
    expected_size = 20 + record_count * record_size + string_size
    assert len(data) == expected_size
    path.write_bytes(data)


def _rewrite_skill_line_ability_spell_id(path: Path, record_id: int, spell_id: int) -> None:
    data = bytearray(path.read_bytes())
    magic, record_count, field_count, record_size, string_size = struct.unpack_from(
        "<4sIIII", data
    )
    assert magic == b"WDBC"
    assert (field_count, record_size) == (15, 60)
    records_start = 20
    found = False
    for record_index in range(record_count):
        record_start = records_start + record_index * record_size
        current_id = struct.unpack_from("<I", data, record_start)[0]
        if current_id != record_id:
            continue
        struct.pack_into("<I", data, record_start + 8, spell_id)
        found = True
        break
    assert found, f"SkillLineAbility record {record_id} not found"
    expected_size = 20 + record_count * record_size + string_size
    assert len(data) == expected_size
    path.write_bytes(data)

def _seed_items(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT INTO items(item_id, name) VALUES (?, ?)",
        ((2000, "Minor Healing Potion"), (2100, "Copper Bracers")),
    )


def _canonical_snapshot(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    statements = (
        "SELECT spell_id, name, rank_text FROM spells ORDER BY spell_id",
        "SELECT skill_line_id, name FROM skill_lines ORDER BY skill_line_id",
        "SELECT recipe_id, crafting_spell_id FROM recipes ORDER BY recipe_id",
        """
        SELECT recipe_id, skill_line_ability_id, skill_line_id, required_skill_value
        FROM recipe_skill_lines
        ORDER BY recipe_id, skill_line_ability_id
        """,
        """
        SELECT recipe_id, effect_index, native_item_id, item_id
        FROM recipe_outputs
        ORDER BY recipe_id, effect_index
        """,
    )
    flattened: list[tuple[object, ...]] = []
    for statement in statements:
        flattened.extend(tuple(row) for row in connection.execute(statement).fetchall())
        flattened.append(("--",))
    return tuple(flattened)


def test_tortoise_fixture_has_reviewed_layouts_and_distinct_rank_identity() -> None:
    source = load_octodbc_recipe_slice(FIXTURE_ROOT)
    layouts = {
        layout.filename: (layout.field_count, layout.record_size) for layout in source.layouts
    }
    assert layouts == {
        "Spell.dbc": (176, 704),
        "SkillLine.dbc": (22, 88),
        "SkillLineAbility.dbc": (15, 60),
    }
    potion_ids = [
        spell.spell_id for spell in source.spells if spell.name == "Minor Healing Potion"
    ]
    assert potion_ids == [1000, 1001]
    rank_two = next(spell for spell in source.spells if spell.spell_id == 1001)
    assert rank_two.rank_text == "Rank 2"


def test_standard_vanilla_173_spell_layout_preserves_recipe_fields(tmp_path: Path) -> None:
    root = tmp_path / "dbc"
    shutil.copytree(FIXTURE_ROOT, root)
    _write_standard_vanilla_173_spell_variant(
        FIXTURE_ROOT / "Spell.dbc", root / "Spell.dbc"
    )

    source = load_octodbc_recipe_slice(root)
    layouts = {
        layout.filename: (layout.field_count, layout.record_size) for layout in source.layouts
    }
    assert layouts["Spell.dbc"] == (173, 692)
    potion_ids = [
        spell.spell_id for spell in source.spells if spell.name == "Minor Healing Potion"
    ]
    assert potion_ids == [1000, 1001]
    rank_two = next(spell for spell in source.spells if spell.spell_id == 1001)
    assert rank_two.rank_text == "Rank 2"
    recipe_spell = next(spell for spell in source.spells if spell.spell_id == 1000)
    assert [
        (effect.effect_index, effect.effect_id, effect.item_type_id)
        for effect in recipe_spell.effects
        if effect.effect_id == 24
    ] == [(0, 24, 2000), (2, 24, 2999)]


def test_unsupported_spell_layout_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "dbc"
    shutil.copytree(FIXTURE_ROOT, root)
    spell_path = root / "Spell.dbc"
    data = bytearray(spell_path.read_bytes())
    magic, records, _fields, record_size, strings = struct.unpack_from("<4sIIII", data)
    struct.pack_into("<4sIIII", data, 0, magic, records, 175, record_size, strings)
    spell_path.write_bytes(data)

    with pytest.raises(RecipeDbcParseError, match="unsupported DBC layout"):
        inspect_octodbc_recipe_layouts(root)


def test_nonrecipe_orphan_skill_line_reference_is_reported_not_fatal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "dbc"
    shutil.copytree(FIXTURE_ROOT, root)
    _rewrite_skill_line_ability_skill_id(root / "SkillLineAbility.dbc", 5002, 763)

    source = load_octodbc_recipe_slice(root)
    assert any(
        ability.record_id == 5002 and ability.skill_line_id == 763
        for ability in source.skill_line_abilities
    )

    with connect_database(tmp_path / "orphan-nonrecipe.sqlite3") as connection:
        apply_migrations(connection)
        _seed_items(connection)
        summary = import_octodbc_recipes(connection, source_root=root)
        assert summary.status == "succeeded"
        assert summary.details["orphan_skill_line_ability_count"] == 1
        assert summary.details["orphan_skill_line_ids"] == [763]
        assert summary.details["orphan_recipe_skill_line_membership_count"] == 0
        assert summary.details["recipe_ids"] == [1000, 1100]
        assert connection.execute(
            "SELECT COUNT(*) FROM skill_lines WHERE skill_line_id = 763"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_recipe_orphan_skill_line_reference_fails_without_fabricating_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "dbc"
    shutil.copytree(FIXTURE_ROOT, root)
    _rewrite_skill_line_ability_skill_id(root / "SkillLineAbility.dbc", 5000, 763)

    with connect_database(tmp_path / "orphan-recipe.sqlite3") as connection:
        apply_migrations(connection)
        _seed_items(connection)
        with pytest.raises(RecipeDbcParseError, match="recipe-qualified SkillLineAbility"):
            import_octodbc_recipes(connection, source_root=root)
        assert connection.execute(
            "SELECT COUNT(*) FROM skill_lines WHERE skill_line_id = 763"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0] == 0


def test_missing_spell_skill_line_ability_is_reported_not_fatal(tmp_path: Path) -> None:
    root = tmp_path / "dbc"
    shutil.copytree(FIXTURE_ROOT, root)
    _rewrite_skill_line_ability_spell_id(root / "SkillLineAbility.dbc", 5002, 46530)

    source = load_octodbc_recipe_slice(root)
    assert any(
        ability.record_id == 5002 and ability.spell_id == 46530
        for ability in source.skill_line_abilities
    )

    with connect_database(tmp_path / "orphan-spell.sqlite3") as connection:
        apply_migrations(connection)
        _seed_items(connection)
        summary = import_octodbc_recipes(connection, source_root=root)
        assert summary.status == "succeeded"
        assert summary.details["orphan_spell_skill_line_ability_count"] == 1
        assert summary.details["orphan_spell_ids"] == [46530]
        assert summary.details["recipe_ids"] == [1000, 1100]
        assert connection.execute(
            "SELECT COUNT(*) FROM spells WHERE spell_id = 46530"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_revision_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    first = compute_octodbc_recipe_revision(FIXTURE_ROOT)
    second = compute_octodbc_recipe_revision(FIXTURE_ROOT)
    assert first == second
    assert first.startswith("sha256:")

    root = tmp_path / "dbc"
    shutil.copytree(FIXTURE_ROOT, root)
    path = root / "Spell.dbc"
    data = bytearray(path.read_bytes())
    data[-2] ^= 1
    path.write_bytes(data)
    assert compute_octodbc_recipe_revision(root) != first


def test_fresh_database_migrates_to_recipe_identity_schema(tmp_path: Path) -> None:
    with connect_database(tmp_path / "fresh.sqlite3") as connection:
        applied = apply_migrations(connection)
        assert applied[-1].version == 11
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 11
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    expected = {"spells", "skill_lines", "recipes", "recipe_skill_lines", "recipe_outputs"}
    assert expected <= table_names


def test_import_derives_bounded_recipes_preserves_slots_and_reports_unresolved(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "recipes.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_items(connection)
        summary = import_octodbc_recipes(connection, source_root=FIXTURE_ROOT)

        assert summary.status == "succeeded"
        assert summary.warning_count == 1
        assert summary.details["recipe_ids"] == [1000, 1100]
        assert summary.details["fixed_output_quantity_materialized"] is False
        assert summary.details["unresolved_outputs"] == [
            {"recipe_id": 1000, "effect_index": 2, "native_item_id": 2999}
        ]

        assert connection.execute("SELECT COUNT(*) FROM spells").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM skill_lines").fetchone()[0] == 2
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT recipe_id, crafting_spell_id FROM recipes ORDER BY recipe_id"
            ).fetchall()
        ] == [(1000, 1000), (1100, 1100)]
        assert [
            tuple(row)
            for row in connection.execute(
                """
                SELECT recipe_id, skill_line_id, required_skill_value
                FROM recipe_skill_lines
                ORDER BY recipe_id
                """
            ).fetchall()
        ] == [(1000, 171, 1), (1100, 164, 25)]
        assert [
            tuple(row)
            for row in connection.execute(
                """
                SELECT recipe_id, effect_index, native_item_id, item_id
                FROM recipe_outputs
                ORDER BY recipe_id, effect_index
                """
            ).fetchall()
        ] == [
            (1000, 0, 2000, 2000),
            (1000, 2, 2999, None),
            (1100, 1, 2100, 2100),
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM recipes WHERE recipe_id IN (1200, 1300)"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_rerun_is_canonically_idempotent(tmp_path: Path) -> None:
    with connect_database(tmp_path / "idempotent.sqlite3") as connection:
        apply_migrations(connection)
        _seed_items(connection)
        first = import_octodbc_recipes(connection, source_root=FIXTURE_ROOT)
        snapshot = _canonical_snapshot(connection)
        second = import_octodbc_recipes(connection, source_root=FIXTURE_ROOT)

        assert first.source_revision == second.source_revision
        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert _canonical_snapshot(connection) == snapshot
        assert connection.execute(
            "SELECT COUNT(*) FROM import_batches WHERE importer_version = 'octo-dbc-recipes/4'"
        ).fetchone()[0] == 2


def test_foreign_selection_policy_is_preserved(tmp_path: Path) -> None:
    with connect_database(tmp_path / "selection.sqlite3") as connection:
        apply_migrations(connection)
        _seed_items(connection)
        import_octodbc_recipes(connection, source_root=FIXTURE_ROOT)

        connection.execute(
            """
            INSERT INTO data_sources(source_key, display_name, source_kind)
            VALUES ('manual-test', 'Manual test', 'test')
            """
        )
        source_id = int(
            connection.execute(
                "SELECT id FROM data_sources WHERE source_key = 'manual-test'"
            ).fetchone()[0]
        )
        batch_id = int(
            connection.execute(
                """
                INSERT INTO import_batches(
                    source_id, source_revision, status, importer_version, rows_read,
                    rows_accepted, finished_at
                )
                VALUES (?, 'manual:1', 'succeeded', 'test', 1, 1,
                        strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (source_id,),
            ).lastrowid
        )
        observation_id = record_scalar_observation(
            connection,
            subject_kind="spell",
            subject_key=1000,
            fact_key="name",
            import_batch_id=batch_id,
            value="Curated Potion Name",
            source_record_type="test",
            raw_identifier=1000,
            authority_tier=0,
        )
        group_id = int(
            connection.execute(
                "SELECT observation_group_id FROM source_observations WHERE id = ?",
                (observation_id,),
            ).fetchone()[0]
        )
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy="manual-test-policy",
            selection_reason="Test a foreign/custom canonical policy.",
        )

        summary = import_octodbc_recipes(connection, source_root=FIXTURE_ROOT)
        assert summary.details["protected_selection_count"] >= 1
        assert connection.execute(
            "SELECT name FROM spells WHERE spell_id = 1000"
        ).fetchone()[0] == "Curated Potion Name"
        selection = connection.execute(
            """
            SELECT cs.selection_policy
            FROM canonical_selections AS cs
            JOIN observation_groups AS og ON og.id = cs.observation_group_id
            WHERE og.subject_kind = 'spell'
              AND og.subject_key = '1000'
              AND og.fact_key = 'name'
            """
        ).fetchone()
        assert selection[0] == "manual-test-policy"
