from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

import pytest

from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_relation_observation,
    select_canonical_observation,
)
from octogamedb.importers.octo_dbc_recipe_reagents import (
    IDENTITY_IMPORTER_VERSION,
    IMPORTER_VERSION,
    RecipeReagentDbcError,
    compute_octodbc_recipe_reagent_revision,
    import_octodbc_recipe_reagents,
    load_octodbc_recipe_reagents,
)


def _write_table(path: Path, field_count: int, records: list[list[int]]) -> None:
    record_size = field_count * 4
    payload = bytearray()
    for record in records:
        assert len(record) == field_count
        for value in record:
            payload.extend(struct.pack("<I", value & 0xFFFFFFFF))
    strings = b"\0"
    path.write_bytes(
        struct.pack("<4sIIII", b"WDBC", len(records), field_count, record_size, len(strings))
        + payload
        + strings
    )


def _spell_record(
    field_count: int, spell_id: int, reagents: dict[int, tuple[int, int]]
) -> list[int]:
    record = [0] * field_count
    record[0] = spell_id
    for reagent_index, (item_id, quantity) in reagents.items():
        record[42 + reagent_index] = item_id
        record[50 + reagent_index] = quantity
    return record


def _write_source(root: Path, *, spell_fields: int = 176) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _write_table(
        root / "Spell.dbc",
        spell_fields,
        [
            _spell_record(
                spell_fields,
                1000,
                {
                    0: (2000, 2),
                    2: (2999, 3),
                    4: (2100, 0),
                },
            ),
            _spell_record(spell_fields, 1100, {}),
            _spell_record(spell_fields, 1200, {0: (2200, 5)}),
        ],
    )
    _write_table(root / "SkillLine.dbc", 22, [[0] * 22])
    _write_table(root / "SkillLineAbility.dbc", 15, [[0] * 15])


def _seed_identity(
    connection: sqlite3.Connection, root: Path, *, revision: str | None = None
) -> str:
    source_revision = revision or compute_octodbc_recipe_reagent_revision(root)
    connection.executemany(
        "INSERT INTO items(item_id, name) VALUES (?, ?)",
        ((2000, "Resolved A"), (2100, "Resolved B"), (2200, "Non-recipe reagent")),
    )
    connection.executemany(
        "INSERT INTO spells(spell_id, name) VALUES (?, ?)",
        ((1000, "Recipe A"), (1100, "Recipe B")),
    )
    connection.executemany(
        "INSERT INTO recipes(recipe_id, crafting_spell_id) VALUES (?, ?)",
        ((1000, 1000), (1100, 1100)),
    )
    connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind, source_path)
        VALUES ('octo-client-dbc', 'Octo client DBC', 'client-dbc', ?)
        """,
        (str(root),),
    )
    source_id = int(
        connection.execute(
            "SELECT id FROM data_sources WHERE source_key = 'octo-client-dbc'"
        ).fetchone()[0]
    )
    connection.execute(
        """
        INSERT INTO import_batches(
            source_id, source_revision, status, importer_version, rows_read,
            rows_accepted, finished_at
        )
        VALUES (?, ?, 'succeeded', ?, 3, 2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        """,
        (source_id, source_revision, IDENTITY_IMPORTER_VERSION),
    )
    return source_revision


def test_fresh_database_migrates_to_recipe_reagent_schema(tmp_path: Path) -> None:
    with connect_database(tmp_path / "fresh.sqlite3") as connection:
        applied = apply_migrations(connection)
        assert applied[-1].version == 12
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 12
        columns = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA table_info(recipe_reagents)").fetchall()
        }
    assert columns == {
        "recipe_id": "INTEGER",
        "reagent_index": "INTEGER",
        "native_item_id": "INTEGER",
        "item_id": "INTEGER",
        "required_quantity": "INTEGER",
    }


@pytest.mark.parametrize("spell_fields", [176, 173])
def test_parser_reads_same_reagent_slots_in_both_reviewed_spell_layouts(
    tmp_path: Path, spell_fields: int
) -> None:
    root = tmp_path / f"dbc-{spell_fields}"
    _write_source(root, spell_fields=spell_fields)

    source = load_octodbc_recipe_reagents(root)
    spell = next(row for row in source.spells if row.spell_id == 1000)
    assert [
        (row.reagent_index, row.native_item_id, row.required_quantity)
        for row in spell.reagents
    ] == [(0, 2000, 2), (2, 2999, 3), (4, 2100, 0)]


def test_import_preserves_slots_quantities_and_unresolved_native_items(tmp_path: Path) -> None:
    root = tmp_path / "dbc"
    _write_source(root)
    with connect_database(tmp_path / "reagents.sqlite3") as connection:
        apply_migrations(connection)
        revision = _seed_identity(connection, root)
        summary = import_octodbc_recipe_reagents(connection, source_root=root)

        assert summary.source_revision == revision
        assert summary.status == "succeeded"
        assert summary.details["recipe_reagent_count"] == 3
        assert summary.details["unresolved_reagent_count"] == 1
        assert summary.details["zero_quantity_reagent_count"] == 1
        assert summary.details["reagent_slots_scanned_independently"] is True
        assert summary.warning_count == 2
        assert [
            tuple(row)
            for row in connection.execute(
                """
                SELECT recipe_id, reagent_index, native_item_id, item_id, required_quantity
                FROM recipe_reagents
                ORDER BY recipe_id, reagent_index
                """
            ).fetchall()
        ] == [
            (1000, 0, 2000, 2000, 2),
            (1000, 2, 2999, None, 3),
            (1000, 4, 2100, 2100, 0),
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM recipe_reagents WHERE recipe_id = 1200"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_same_revision_rerun_is_canonically_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "dbc"
    _write_source(root)
    with connect_database(tmp_path / "idempotent.sqlite3") as connection:
        apply_migrations(connection)
        _seed_identity(connection, root)
        first = import_octodbc_recipe_reagents(connection, source_root=root)
        snapshot = [
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM recipe_reagents ORDER BY recipe_id, reagent_index"
            ).fetchall()
        ]
        second = import_octodbc_recipe_reagents(connection, source_root=root)

        assert first.source_revision == second.source_revision
        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM recipe_reagents ORDER BY recipe_id, reagent_index"
            ).fetchall()
        ] == snapshot
        assert connection.execute(
            "SELECT COUNT(*) FROM import_batches WHERE importer_version = ?",
            (IMPORTER_VERSION,),
        ).fetchone()[0] == 2



def test_explicit_source_revision_must_match_source_bytes(tmp_path: Path) -> None:
    root = tmp_path / "dbc"
    _write_source(root)
    with connect_database(tmp_path / "explicit-revision.sqlite3") as connection:
        apply_migrations(connection)
        _seed_identity(connection, root)
        with pytest.raises(RecipeReagentDbcError, match="does not match the configured DBC bytes"):
            import_octodbc_recipe_reagents(
                connection, source_root=root, source_revision="sha256:caller-lie"
            )
        assert connection.execute(
            "SELECT COUNT(*) FROM import_batches WHERE importer_version = ?",
            (IMPORTER_VERSION,),
        ).fetchone()[0] == 0

def test_identity_revision_mismatch_fails_before_reagent_batch(tmp_path: Path) -> None:
    root = tmp_path / "dbc"
    _write_source(root)
    with connect_database(tmp_path / "mismatch.sqlite3") as connection:
        apply_migrations(connection)
        _seed_identity(connection, root, revision="sha256:not-the-source")
        before = connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0]
        with pytest.raises(RecipeReagentDbcError, match="differs from the P4-T02"):
            import_octodbc_recipe_reagents(connection, source_root=root)
        assert connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0] == before
        assert connection.execute("SELECT COUNT(*) FROM recipe_reagents").fetchone()[0] == 0


def test_cross_revision_refresh_is_rejected_without_reconciliation_contract(tmp_path: Path) -> None:
    root = tmp_path / "dbc"
    _write_source(root)
    with connect_database(tmp_path / "refresh.sqlite3") as connection:
        apply_migrations(connection)
        _seed_identity(connection, root)
        import_octodbc_recipe_reagents(connection, source_root=root)

        spell_path = root / "Spell.dbc"
        data = bytearray(spell_path.read_bytes())
        # First record, reagent-count slot 0: field 50.
        struct.pack_into("<I", data, 20 + 50 * 4, 9)
        spell_path.write_bytes(data)
        new_revision = compute_octodbc_recipe_reagent_revision(root)
        source_id = int(
            connection.execute(
                "SELECT id FROM data_sources WHERE source_key = 'octo-client-dbc'"
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO import_batches(
                source_id, source_revision, status, importer_version, rows_read,
                rows_accepted, finished_at
            )
            VALUES (?, ?, 'succeeded', ?, 3, 2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (source_id, new_revision, IDENTITY_IMPORTER_VERSION),
        )

        with pytest.raises(RecipeReagentDbcError, match="cross-revision"):
            import_octodbc_recipe_reagents(connection, source_root=root)


def test_foreign_selection_policy_is_preserved(tmp_path: Path) -> None:
    root = tmp_path / "dbc"
    _write_source(root)
    with connect_database(tmp_path / "selection.sqlite3") as connection:
        apply_migrations(connection)
        _seed_identity(connection, root)
        import_octodbc_recipe_reagents(connection, source_root=root)

        connection.execute(
            "INSERT INTO data_sources(source_key, display_name, source_kind) "
            "VALUES ('manual-reagent', 'Manual reagent', 'test')"
        )
        source_id = int(
            connection.execute(
                "SELECT id FROM data_sources WHERE source_key = 'manual-reagent'"
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
        observation_id = record_relation_observation(
            connection,
            subject_kind="recipe",
            subject_key=1000,
            fact_key="reagent",
            import_batch_id=batch_id,
            target_kind="item",
            target_key=2100,
            relation_instance_key="slot:0",
            attributes={
                "reagent_index": 0,
                "required_quantity": 7,
                "quantity_semantics": "curated-test",
            },
            source_record_type="test",
            raw_identifier="manual:1000:0",
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
            selection_policy="manual-reagent-policy",
            selection_reason="Protect a curated reagent relation in the test.",
        )

        summary = import_octodbc_recipe_reagents(connection, source_root=root)
        assert summary.details["protected_selection_count"] >= 1
        assert tuple(
            connection.execute(
                """
                SELECT native_item_id, item_id, required_quantity
                FROM recipe_reagents
                WHERE recipe_id = 1000 AND reagent_index = 0
                """
            ).fetchone()
        ) == (2100, 2100, 7)
        selection = connection.execute(
            """
            SELECT cs.selection_policy
            FROM canonical_selections AS cs
            JOIN observation_groups AS og ON og.id = cs.observation_group_id
            WHERE og.subject_kind = 'recipe'
              AND og.subject_key = '1000'
              AND og.fact_key = 'reagent'
              AND og.fact_instance_key = 'slot:0'
            """
        ).fetchone()
        assert selection[0] == "manual-reagent-policy"
