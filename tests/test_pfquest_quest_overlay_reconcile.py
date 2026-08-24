from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.pfquest_quest_overlay_reconcile import (
    QUEST_ENDPOINT_SET_FACT,
    QUEST_PRESENCE_FACT,
    compute_pfquest_turtle_quests_revision,
    reconcile_pfquest_turtle_quests,
)
from octogamedb.importers.pfquest_quests import (
    compute_pfquest_quests_revision,
    import_pfquest_quests,
)
from octogamedb.importers.pfquest_world import PfQuestParseError

ROOT = Path(__file__).parent / "fixtures"
BASE = ROOT / "pfquest" / "quests_slice"
TURTLE = ROOT / "pfquest_turtle" / "quests_slice"


def _seed_world(connection) -> None:
    for creature_id in (10, 11, 12):
        connection.execute(
            "INSERT INTO creatures(creature_id, name) VALUES (?, ?)",
            (creature_id, f"Creature {creature_id}"),
        )
    for gameobject_id in (20, 21):
        connection.execute(
            "INSERT INTO gameobjects(gameobject_id, name) VALUES (?, ?)",
            (gameobject_id, f"Object {gameobject_id}"),
        )


def _prepare(connection) -> tuple[str, str]:
    apply_migrations(connection)
    _seed_world(connection)
    base_revision = compute_pfquest_quests_revision(BASE)
    turtle_revision = compute_pfquest_turtle_quests_revision(TURTLE)
    import_pfquest_quests(connection, source_root=BASE, source_revision=base_revision)
    return base_revision, turtle_revision


def _endpoint_keys(connection, quest_id: int) -> set[tuple[str, str, int]]:
    rows = connection.execute(
        """
        SELECT endpoint_kind, 'creature', creature_id FROM quest_creature_endpoints
        WHERE quest_id = ?
        UNION ALL
        SELECT endpoint_kind, 'gameobject', gameobject_id FROM quest_gameobject_endpoints
        WHERE quest_id = ?
        """,
        (quest_id, quest_id),
    ).fetchall()
    return {(str(row[0]), str(row[1]), int(row[2])) for row in rows}


def test_revision_is_content_derived_and_layout_is_validated(tmp_path):
    first = compute_pfquest_turtle_quests_revision(TURTLE)
    assert first == compute_pfquest_turtle_quests_revision(TURTLE)
    assert first.startswith("sha256:")

    copied = tmp_path / "turtle"
    shutil.copytree(TURTLE, copied)
    path = copied / "db" / "enUS" / "quests-turtle.lua"
    path.write_text(path.read_text().replace("Turtle New Quest", "Changed"))
    assert compute_pfquest_turtle_quests_revision(copied) != first

    overwrite = copied / "overwrites.lua"
    overwrite.write_text(
        'local q = pfDB["quests"]["data-turtle"]\nq[102]["start"]["O"] = { 20 }\n'
    )
    with pytest.raises(PfQuestParseError, match="unsupported indirect P3 quest overlay mutation"):
        compute_pfquest_turtle_quests_revision(copied)
        # Revision validation does not parse overwrites; reconciliation does.
        with connect_database(tmp_path / "invalid.sqlite3") as connection:
            base_revision = compute_pfquest_quests_revision(BASE)
            apply_migrations(connection)
            _seed_world(connection)
            import_pfquest_quests(connection, source_root=BASE, source_revision=base_revision)
            reconcile_pfquest_turtle_quests(
                connection,
                pfquest_root=BASE,
                pfquest_turtle_root=copied,
                pfquest_revision=base_revision,
                turtle_revision=compute_pfquest_turtle_quests_revision(copied),
            )


def test_reconcile_effective_quest_identity_and_endpoints_is_idempotent(tmp_path):
    db_path = tmp_path / "quests-overlay.sqlite3"
    with connect_database(db_path) as connection:
        base_revision, turtle_revision = _prepare(connection)
        first = reconcile_pfquest_turtle_quests(
            connection,
            pfquest_root=BASE,
            pfquest_turtle_root=TURTLE,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )
        second = reconcile_pfquest_turtle_quests(
            connection,
            pfquest_root=BASE,
            pfquest_turtle_root=TURTLE,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )

        assert first.status == "succeeded"
        assert first.details["changed_name_ids"] == [100, 105, 106, 107, 108]
        assert first.details["changed_endpoint_ids"] == [100, 101, 102, 107, 108]
        assert first.details["added_quest_ids"] == [106, 107, 108]
        assert first.details["removed_quest_ids"] == [105]
        assert first.details["unresolved_endpoints"] == [
            {
                "quest_id": 108,
                "endpoint_kind": "giver",
                "target_kind": "creature",
                "target_id": 999,
                "reason": "missing_p1_target",
            }
        ]

        assert connection.execute("SELECT name FROM quests WHERE quest_id = 100").fetchone()[0] == (
            "A Turtle Multi Endpoint Quest"
        )
        assert _endpoint_keys(connection, 100) == {
            ("giver", "creature", 10),
            ("finisher", "gameobject", 21),
        }
        assert _endpoint_keys(connection, 101) == set()
        # overwrites.lua changed the Turtle top-entry before composition.
        assert _endpoint_keys(connection, 102) == {("giver", "gameobject", 21)}
        assert connection.execute("SELECT 1 FROM quests WHERE quest_id = 105").fetchone() is None
        # Quest 106 had base data but no base title, so P3-T01 skipped it. Turtle adds the title;
        # P3-T02 must recover the inherited base endpoint without attributing it to Turtle.
        assert connection.execute("SELECT name FROM quests WHERE quest_id = 106").fetchone()[0] == (
            "Recovered Base Data Quest"
        )
        assert _endpoint_keys(connection, 106) == {("giver", "creature", 10)}
        assert _endpoint_keys(connection, 107) == {("giver", "creature", 10)}
        assert _endpoint_keys(connection, 108) == set()
        assert (
            connection.execute("SELECT 1 FROM creatures WHERE creature_id = 999").fetchone()
            is None
        )

        source_for_106 = connection.execute(
            """
            SELECT ds.source_key
            FROM observation_groups og
            JOIN canonical_selections cs ON cs.observation_group_id = og.id
            JOIN source_observations so ON so.id = cs.observation_id
            JOIN data_sources ds ON ds.id = so.source_id
            WHERE og.subject_kind='quest' AND og.subject_key='106'
              AND og.fact_key='endpoint'
            """
        ).fetchone()[0]
        assert source_for_106 == "pfquest"

        for fact_key in (QUEST_PRESENCE_FACT, QUEST_ENDPOINT_SET_FACT):
            selected_source = connection.execute(
                """
                SELECT ds.source_key
                FROM observation_groups og
                JOIN canonical_selections cs ON cs.observation_group_id=og.id
                JOIN source_observations so ON so.id=cs.observation_id
                JOIN data_sources ds ON ds.id=so.source_id
                WHERE og.subject_kind='quest' AND og.subject_key='100' AND og.fact_key=?
                """,
                (fact_key,),
            ).fetchone()[0]
            assert selected_source == "pfquest-turtle"

        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert second.details["canonical_relations_or_identities_deleted"] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def _create_curated_batch(connection) -> int:
    source_id = connection.execute(
        "INSERT INTO data_sources(source_key, display_name, source_kind) "
        "VALUES ('curated', 'Curated', 'test')"
    ).lastrowid
    return connection.execute(
        """
        INSERT INTO import_batches(source_id,source_revision,status,importer_version,rows_read)
        VALUES (?, 'curated-v1', 'running', 'test/1', 1)
        """,
        (source_id,),
    ).lastrowid


def test_custom_name_and_endpoint_selections_are_protected(tmp_path):
    with connect_database(tmp_path / "protected.sqlite3") as connection:
        base_revision, turtle_revision = _prepare(connection)
        batch_id = _create_curated_batch(connection)

        name_observation = record_scalar_observation(
            connection,
            subject_kind="quest",
            subject_key=105,
            fact_key="name",
            import_batch_id=batch_id,
            value="Curated Locale Only",
            source_record_type="curated",
            raw_identifier=105,
        )
        name_group = connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id=?", (name_observation,)
        ).fetchone()[0]
        select_canonical_observation(
            connection,
            observation_group_id=name_group,
            observation_id=name_observation,
            selection_policy="manual-test",
            selection_reason="Protect a curated quest identity.",
        )
        connection.execute("UPDATE quests SET name='Curated Locale Only' WHERE quest_id=105")

        endpoint_observation = record_relation_observation(
            connection,
            subject_kind="quest",
            subject_key=100,
            fact_key="endpoint",
            import_batch_id=batch_id,
            target_kind="creature",
            target_key=11,
            relation_instance_key="giver:creature:11",
            attributes={"endpoint_kind": "giver"},
            source_record_type="curated",
            raw_identifier="giver:creature:11",
        )
        endpoint_group = connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id=?",
            (endpoint_observation,),
        ).fetchone()[0]
        select_canonical_observation(
            connection,
            observation_group_id=endpoint_group,
            observation_id=endpoint_observation,
            selection_policy="manual-test",
            selection_reason="Protect a curated quest endpoint.",
        )

        summary = reconcile_pfquest_turtle_quests(
            connection,
            pfquest_root=BASE,
            pfquest_turtle_root=TURTLE,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )

        assert connection.execute("SELECT name FROM quests WHERE quest_id=105").fetchone()[0] == (
            "Curated Locale Only"
        )
        assert ("giver", "creature", 11) in _endpoint_keys(connection, 100)
        assert summary.details["protected_canonical_rows_retained"] >= 1
