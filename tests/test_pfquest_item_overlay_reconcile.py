from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from octogamedb.__main__ import main
from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.pfquest_item_overlay_reconcile import (
    compute_pfquest_turtle_items_revision,
    reconcile_pfquest_turtle_items,
)
from octogamedb.importers.pfquest_items import (
    compute_pfquest_items_revision,
    import_pfquest_items,
)
from octogamedb.importers.pfquest_world import PfQuestParseError
from octogamedb.items import find_item_sources

BASE_FIXTURE = Path(__file__).parent / "fixtures" / "pfquest" / "items_slice"


def _seed_templates(connection: sqlite3.Connection) -> None:
    for creature_id, name in (
        (2001, "Test Wolf"),
        (2002, "Test Boar"),
        (2003, "Test Bear"),
        (4001, "Test Vendor"),
    ):
        connection.execute(
            "INSERT INTO creatures(creature_id, name) VALUES (?, ?)",
            (creature_id, name),
        )
    connection.execute(
        "INSERT INTO gameobjects(gameobject_id, name) VALUES (3001, 'Test Chest')"
    )


def _write_turtle_overlay(root: Path) -> Path:
    (root / "init").mkdir(parents=True)
    (root / "db" / "enUS").mkdir(parents=True)
    (root / "pfQuest-turtle.toc").write_text(
        "## Dependencies: pfQuest\n"
        "init\\data-turtle.xml\n"
        "init\\enUS-turtle.xml\n"
        "overwrites.lua\n"
        "patchtable.lua\n",
        encoding="utf-8",
    )
    (root / "init" / "data-turtle.xml").write_text(
        '<Ui xmlns="http://www.blizzard.com/wow/ui/">\n'
        '  <Script file="..\\db\\items-turtle.lua"/>\n'
        '  <Script file="..\\db\\refloot-turtle.lua"/>\n'
        "</Ui>\n",
        encoding="utf-8",
    )
    (root / "init" / "enUS-turtle.xml").write_text(
        '<Ui xmlns="http://www.blizzard.com/wow/ui/">\n'
        '  <Script file="..\\db\\enUS\\items-turtle.lua"/>\n'
        '  <Script file="..\\db\\enUS\\units-turtle.lua"/>\n'
        '  <Script file="..\\db\\enUS\\objects-turtle.lua"/>\n'
        "</Ui>\n",
        encoding="utf-8",
    )
    (root / "patchtable.lua").write_text(
        'local dbs = { "items", "refloot" }\n'
        "local function patchtable(base, diff)\n"
        "  for k, v in pairs(diff) do\n"
        '    if type(v) == "string" and v == "_" then\n'
        "      base[k] = nil\n"
        "    else\n"
        "      base[k] = v\n"
        "    end\n"
        "  end\n"
        "end\n"
        "for _, db in pairs(dbs) do\n"
        '  if pfDB[db]["data-turtle"] then patchtable(pfDB[db]["data"], pfDB[db]["data-turtle"]) end\n'
        "end\n",
        encoding="utf-8",
    )
    (root / "db" / "items-turtle.lua").write_text(
        'pfDB["items"]["data-turtle"] = {\n'
        "  [1001] = {\n"
        '    ["U"] = { [2002] = 33 },\n'
        '    ["R"] = { [9001] = 5 },\n'
        '    ["V"] = { [4002] = 2 },\n'
        "  },\n"
        '  [1002] = "_",\n'
        '  [1005] = { ["O"] = { [3003] = 50 } },\n'
        "}\n",
        encoding="utf-8",
    )
    (root / "db" / "refloot-turtle.lua").write_text(
        'pfDB["refloot"]["data-turtle"] = {\n'
        '  [9001] = { ["U"] = { [2002] = 1 }, ["O"] = { [3003] = 1 } },\n'
        "}\n",
        encoding="utf-8",
    )
    (root / "db" / "enUS" / "items-turtle.lua").write_text(
        'pfDB["items"]["enUS-turtle"] = {\n'
        '  [1001] = "Turtle Relic",\n'
        '  [1005] = "Turtle Added",\n'
        "}\n",
        encoding="utf-8",
    )
    (root / "db" / "enUS" / "units-turtle.lua").write_text(
        'pfDB["units"]["enUS-turtle"] = { [4002] = "Turtle Vendor" }\n',
        encoding="utf-8",
    )
    (root / "db" / "enUS" / "objects-turtle.lua").write_text(
        'pfDB["objects"]["enUS-turtle"] = { [3003] = "Turtle Cache" }\n',
        encoding="utf-8",
    )
    # Applied before patchtable: this must replace the U member inside the Turtle item entry.
    (root / "overwrites.lua").write_text(
        'pfDB["items"]["data-turtle"][1001]["U"] = { [2003] = 44 }\n',
        encoding="utf-8",
    )
    return root


def _prepare(connection: sqlite3.Connection, turtle_root: Path) -> tuple[str, str]:
    _seed_templates(connection)
    base_revision = compute_pfquest_items_revision(BASE_FIXTURE)
    import_pfquest_items(
        connection,
        source_root=BASE_FIXTURE,
        source_revision=base_revision,
    )
    turtle_revision = compute_pfquest_turtle_items_revision(turtle_root)
    return base_revision, turtle_revision




def _select_custom_base_scalar(
    connection: sqlite3.Connection,
    *,
    base_revision: str,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    value: object,
) -> None:
    batch_id = connection.execute(
        """
        SELECT ib.id
        FROM import_batches AS ib
        JOIN data_sources AS ds ON ds.id = ib.source_id
        WHERE ds.source_key = 'pfquest' AND ib.source_revision = ?
          AND ib.status = 'succeeded' AND ib.importer_version LIKE 'pfquest-items/%'
        ORDER BY ib.id DESC LIMIT 1
        """,
        (base_revision,),
    ).fetchone()[0]
    observation_id = record_scalar_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type="explicit-base-complete-set",
        raw_identifier=subject_key,
    )
    group_id = connection.execute(
        "SELECT observation_group_id FROM source_observations WHERE id = ?",
        (observation_id,),
    ).fetchone()[0]
    select_canonical_observation(
        connection,
        observation_group_id=group_id,
        observation_id=observation_id,
        selection_policy="explicit-base-policy",
        selection_reason="Test custom selection using the pfquest source key.",
    )


def test_turtle_reconciliation_replaces_complete_item_and_reference_sets(tmp_path):
    turtle_root = _write_turtle_overlay(tmp_path / "pfQuest-turtle")
    db_path = tmp_path / "items.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        base_revision, turtle_revision = _prepare(connection, turtle_root)
        first = reconcile_pfquest_turtle_items(
            connection,
            pfquest_root=BASE_FIXTURE,
            pfquest_turtle_root=turtle_root,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )
        second = reconcile_pfquest_turtle_items(
            connection,
            pfquest_root=BASE_FIXTURE,
            pfquest_turtle_root=turtle_root,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )

        assert connection.execute("SELECT name FROM items WHERE item_id = 1001").fetchone()[0] == "Turtle Relic"
        assert connection.execute(
            "SELECT chance_percent FROM creature_loot WHERE item_id = 1001 AND creature_id = 2003"
        ).fetchone()[0] == 44
        assert connection.execute(
            "SELECT COUNT(*) FROM creature_loot WHERE item_id = 1001 AND creature_id = 2001"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM gameobject_loot WHERE item_id = 1001 AND gameobject_id = 3001"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT chance_percent FROM item_reference_loot WHERE item_id = 1001 AND reference_loot_id = 9001"
        ).fetchone()[0] == 5
        assert connection.execute(
            "SELECT COUNT(*) FROM vendor_items WHERE item_id = 1001 AND vendor_creature_id = 4002"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM creature_loot WHERE item_id = 1002"
        ).fetchone()[0] == 0
        # Item 1004 is outside the Turtle patch and therefore remains base-canonical.
        assert connection.execute("SELECT 1 FROM items WHERE item_id = 1004").fetchone() is not None
        assert connection.execute("SELECT name FROM items WHERE item_id = 1005").fetchone()[0] == "Turtle Added"
        assert connection.execute("SELECT name FROM creatures WHERE creature_id = 4002").fetchone()[0] == "Turtle Vendor"
        assert connection.execute("SELECT name FROM gameobjects WHERE gameobject_id = 3003").fetchone()[0] == "Turtle Cache"

        assert {
            int(row[0])
            for row in connection.execute(
                "SELECT creature_id FROM reference_loot_creatures WHERE reference_loot_id = 9001"
            ).fetchall()
        } == {2002}
        assert {
            int(row[0])
            for row in connection.execute(
                "SELECT gameobject_id FROM reference_loot_gameobjects WHERE reference_loot_id = 9001"
            ).fetchall()
        } == {3003}

        trace_sources = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT ds.source_key
                FROM observation_groups AS og
                JOIN source_observations AS so ON so.observation_group_id = og.id
                JOIN data_sources AS ds ON ds.id = so.source_id
                WHERE og.subject_kind = 'item' AND og.subject_key = '1001'
                  AND og.fact_key = 'item_acquisition_set'
                """
            ).fetchall()
        }
        assert trace_sources == {"pfquest", "pfquest-turtle"}
        assert first.details["canonical_relations_or_identities_deleted"] > 0
        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert second.details["canonical_relations_or_identities_deleted"] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    with connect_database(db_path) as connection:
        result = find_item_sources(connection, 1001)
    assert result[0]["item_name"] == "Turtle Relic"
    paths = [path for source in result[0]["sources"] for path in source["acquisition_paths"]]
    assert any(path["path_kind"] == "direct" and path["relation_source"]["source_key"] == "pfquest-turtle" for path in paths)
    assert any(path["path_kind"] == "vendor" and path["vendor_max_count"] == 2 for path in paths)


def test_turtle_item_revision_is_content_deterministic(tmp_path):
    turtle_root = _write_turtle_overlay(tmp_path / "pfQuest-turtle")
    first = compute_pfquest_turtle_items_revision(turtle_root)
    assert compute_pfquest_turtle_items_revision(turtle_root) == first

    overwrite_path = turtle_root / "overwrites.lua"
    overwrite_path.write_text(
        overwrite_path.read_text(encoding="utf-8") + "\n-- revision changed\n",
        encoding="utf-8",
    )
    assert compute_pfquest_turtle_items_revision(turtle_root) != first


def test_empty_turtle_item_entry_clears_base_acquisitions(tmp_path):
    turtle_root = _write_turtle_overlay(tmp_path / "pfQuest-turtle")
    items_path = turtle_root / "db" / "items-turtle.lua"
    items_path.write_text(
        items_path.read_text(encoding="utf-8").replace(
            '  [1002] = "_",\n',
            "  [1002] = {},\n",
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "empty-item.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        base_revision, turtle_revision = _prepare(connection, turtle_root)
        reconcile_pfquest_turtle_items(
            connection,
            pfquest_root=BASE_FIXTURE,
            pfquest_turtle_root=turtle_root,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM creature_loot WHERE item_id = 1002"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT name FROM items WHERE item_id = 1002"
        ).fetchone()[0] == "Second Item"



def test_turtle_complete_set_does_not_delete_explicit_non_pfquest_relation(tmp_path):
    turtle_root = _write_turtle_overlay(tmp_path / "pfQuest-turtle")
    db_path = tmp_path / "protected.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        base_revision, turtle_revision = _prepare(connection, turtle_root)
        connection.execute(
            "INSERT INTO data_sources(source_key, display_name, source_kind) VALUES ('explicit-test', 'Explicit', 'test')"
        )
        source_id = connection.execute(
            "SELECT id FROM data_sources WHERE source_key = 'explicit-test'"
        ).fetchone()[0]
        batch_id = connection.execute(
            """
            INSERT INTO import_batches(source_id, source_revision, status, finished_at)
            VALUES (?, 'explicit-1', 'succeeded', '2026-08-24T00:00:00Z')
            """,
            (source_id,),
        ).lastrowid
        observation_id = record_relation_observation(
            connection,
            subject_kind="item",
            subject_key=1001,
            fact_key="loot_source",
            import_batch_id=batch_id,
            target_kind="gameobject",
            target_key=3001,
            relation_instance_key="gameobject:3001",
            attributes={"chance_percent": 25.0},
            source_record_type="explicit",
            raw_identifier="1001:gameobject:3001",
        )
        group_id = connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id = ?", (observation_id,)
        ).fetchone()[0]
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy="explicit-test-policy",
            selection_reason="Test explicit override.",
        )

        summary = reconcile_pfquest_turtle_items(
            connection,
            pfquest_root=BASE_FIXTURE,
            pfquest_turtle_root=turtle_root,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM gameobject_loot WHERE item_id = 1001 AND gameobject_id = 3001"
        ).fetchone()[0] == 1
        assert summary.details["protected_stale_relations"] >= 1


def test_turtle_reconcile_rejects_indirect_bounded_identity_overwrite(tmp_path):
    turtle_root = _write_turtle_overlay(tmp_path / "pfQuest-turtle")
    (turtle_root / "overwrites.lua").write_text(
        'local names = pfDB["units"]["enUS-turtle"]\n'
        'names[4002] = "Indirect Vendor"\n',
        encoding="utf-8",
    )
    db_path = tmp_path / "unsupported-overwrite.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        base_revision, turtle_revision = _prepare(connection, turtle_root)
        with pytest.raises(PfQuestParseError, match="indirect P2 overlay mutation"):
            reconcile_pfquest_turtle_items(
                connection,
                pfquest_root=BASE_FIXTURE,
                pfquest_turtle_root=turtle_root,
                pfquest_revision=base_revision,
                turtle_revision=turtle_revision,
            )



def test_custom_pfquest_complete_set_selection_is_not_treated_as_replaceable(tmp_path):
    turtle_root = _write_turtle_overlay(tmp_path / "pfQuest-turtle")
    db_path = tmp_path / "custom-base-set.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        base_revision, turtle_revision = _prepare(connection, turtle_root)
        base_item_set = [
            {
                "path_kind": "direct",
                "source_kind": "creature",
                "source_id": 2001,
                "chance_percent": 12.5,
            },
            {
                "path_kind": "direct",
                "source_kind": "gameobject",
                "source_id": 3001,
                "chance_percent": 25.0,
            },
            {
                "path_kind": "reference",
                "reference_loot_id": 9001,
                "chance_percent": 7.5,
            },
            {
                "path_kind": "vendor",
                "source_kind": "creature",
                "source_id": 4001,
                "max_count": 0,
            },
        ]
        base_item_set.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))
        base_members = [
            {"source_kind": "creature", "source_id": 2001, "membership_value": 1.0},
            {"source_kind": "creature", "source_id": 2003, "membership_value": 1.0},
            {"source_kind": "gameobject", "source_id": 3002, "membership_value": 1.0},
        ]
        _select_custom_base_scalar(
            connection,
            base_revision=base_revision,
            subject_kind="item",
            subject_key=1001,
            fact_key="item_acquisition_set",
            value=base_item_set,
        )
        _select_custom_base_scalar(
            connection,
            base_revision=base_revision,
            subject_kind="loot_reference",
            subject_key=9001,
            fact_key="loot_reference_member_set",
            value=base_members,
        )

        summary = reconcile_pfquest_turtle_items(
            connection,
            pfquest_root=BASE_FIXTURE,
            pfquest_turtle_root=turtle_root,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )

        assert {
            int(row[0])
            for row in connection.execute(
                "SELECT creature_id FROM creature_loot WHERE item_id = 1001"
            ).fetchall()
        } == {2001}
        assert {
            int(row[0])
            for row in connection.execute(
                "SELECT gameobject_id FROM gameobject_loot WHERE item_id = 1001"
            ).fetchall()
        } == {3001}
        assert {
            int(row[0])
            for row in connection.execute(
                "SELECT vendor_creature_id FROM vendor_items WHERE item_id = 1001"
            ).fetchall()
        } == {4001}
        assert {
            int(row[0])
            for row in connection.execute(
                "SELECT creature_id FROM reference_loot_creatures WHERE reference_loot_id = 9001"
            ).fetchall()
        } == {2001, 2003}
        assert {
            int(row[0])
            for row in connection.execute(
                "SELECT gameobject_id FROM reference_loot_gameobjects WHERE reference_loot_id = 9001"
            ).fetchall()
        } == {3002}
        turtle_primitive_observations = connection.execute(
            """
            SELECT COUNT(*)
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE ds.source_key = 'pfquest-turtle'
              AND ((og.subject_kind = 'item' AND og.subject_key = '1001'
                    AND og.fact_key IN ('loot_source', 'loot_reference', 'vendor_source'))
                OR (og.subject_kind = 'loot_reference' AND og.subject_key = '9001'
                    AND og.fact_key = 'loot_source_member'))
            """
        ).fetchone()[0]
        assert turtle_primitive_observations == 0
        assert summary.details["protected_stale_relations"] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_custom_pfquest_item_presence_selection_blocks_turtle_identity_delete(tmp_path):
    turtle_root = _write_turtle_overlay(tmp_path / "pfQuest-turtle")
    names_path = turtle_root / "db" / "enUS" / "items-turtle.lua"
    names_path.write_text(
        names_path.read_text(encoding="utf-8").replace(
            '  [1001] = "Turtle Relic",\n',
            '  [1001] = "Turtle Relic",\n  [1002] = "_",\n',
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "custom-presence.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        base_revision, turtle_revision = _prepare(connection, turtle_root)
        _select_custom_base_scalar(
            connection,
            base_revision=base_revision,
            subject_kind="item",
            subject_key=1002,
            fact_key="item_presence",
            value=True,
        )

        reconcile_pfquest_turtle_items(
            connection,
            pfquest_root=BASE_FIXTURE,
            pfquest_turtle_root=turtle_root,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )

        assert connection.execute(
            "SELECT name FROM items WHERE item_id = 1002"
        ).fetchone()[0] == "Second Item"
        assert connection.execute(
            "SELECT COUNT(*) FROM creature_loot WHERE item_id = 1002"
        ).fetchone()[0] == 0
        selection = connection.execute(
            """
            SELECT ds.source_key, cs.selection_policy, so.value_json
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            JOIN source_observations AS so ON so.id = cs.observation_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'item' AND og.subject_key = '1002'
              AND og.fact_key = 'item_presence'
            """
        ).fetchone()
        assert tuple(selection) == ("pfquest", "explicit-base-policy", "true")


def test_custom_pfquest_name_selection_blocks_turtle_identity_delete(tmp_path):
    turtle_root = _write_turtle_overlay(tmp_path / "pfQuest-turtle")
    names_path = turtle_root / "db" / "enUS" / "items-turtle.lua"
    names_path.write_text(
        names_path.read_text(encoding="utf-8").replace(
            '  [1001] = "Turtle Relic",\n',
            '  [1001] = "Turtle Relic",\n  [1002] = "_",\n',
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "custom-name.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        base_revision, turtle_revision = _prepare(connection, turtle_root)
        _select_custom_base_scalar(
            connection,
            base_revision=base_revision,
            subject_kind="item",
            subject_key=1002,
            fact_key="name",
            value="Second Item",
        )

        reconcile_pfquest_turtle_items(
            connection,
            pfquest_root=BASE_FIXTURE,
            pfquest_turtle_root=turtle_root,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )

        assert connection.execute(
            "SELECT name FROM items WHERE item_id = 1002"
        ).fetchone()[0] == "Second Item"
        presence = connection.execute(
            """
            SELECT ds.source_key, cs.selection_policy, so.value_json
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            JOIN source_observations AS so ON so.id = cs.observation_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'item' AND og.subject_key = '1002'
              AND og.fact_key = 'item_presence'
            """
        ).fetchone()
        assert tuple(presence) == ("pfquest", "pfquest-base-effective-items", "true")
        name = connection.execute(
            """
            SELECT ds.source_key, cs.selection_policy
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            JOIN source_observations AS so ON so.id = cs.observation_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'item' AND og.subject_key = '1002'
              AND og.fact_key = 'name'
            """
        ).fetchone()
        assert tuple(name) == ("pfquest", "explicit-base-policy")



def test_turtle_reconcile_cli_json(tmp_path, capsys):
    turtle_root = _write_turtle_overlay(tmp_path / "pfQuest-turtle")
    db_path = tmp_path / "cli.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_templates(connection)
        import_pfquest_items(
            connection,
            source_root=BASE_FIXTURE,
            source_revision=compute_pfquest_items_revision(BASE_FIXTURE),
        )

    assert main(
        [
            "reconcile-pfquest-turtle-items",
            str(BASE_FIXTURE),
            str(turtle_root),
            "--db",
            str(db_path),
            "--json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_key"] == "pfquest-turtle"
    assert payload["status"] == "succeeded"
    assert payload["details"]["item_data_patch_entries"] == 3


def test_missing_direct_or_vendor_identity_is_preserved_as_unresolved_evidence(tmp_path):
    turtle_root = _write_turtle_overlay(tmp_path / "pfQuest-turtle")
    items_path = turtle_root / "db" / "items-turtle.lua"
    items_path.write_text(
        items_path.read_text(encoding="utf-8").replace(
            "}\n",
            '  [1006] = { ["U"] = { [62229] = 17 }, ["V"] = { [62230] = 1 } },\n}\n',
            1,
        ),
        encoding="utf-8",
    )
    names_path = turtle_root / "db" / "enUS" / "items-turtle.lua"
    names_path.write_text(
        names_path.read_text(encoding="utf-8").replace(
            "}\n",
            '  [1006] = "Dangling Turtle Item",\n}\n',
            1,
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "unresolved-direct.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        base_revision, turtle_revision = _prepare(connection, turtle_root)
        first = reconcile_pfquest_turtle_items(
            connection,
            pfquest_root=BASE_FIXTURE,
            pfquest_turtle_root=turtle_root,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )
        second = reconcile_pfquest_turtle_items(
            connection,
            pfquest_root=BASE_FIXTURE,
            pfquest_turtle_root=turtle_root,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )

        assert connection.execute(
            "SELECT name FROM items WHERE item_id = 1006"
        ).fetchone()[0] == "Dangling Turtle Item"
        assert connection.execute(
            "SELECT 1 FROM creatures WHERE creature_id IN (62229, 62230)"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM creature_loot WHERE item_id = 1006"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM vendor_items WHERE item_id = 1006"
        ).fetchone() is None

        issues = first.details["unresolved_acquisition_targets"]
        assert issues == [
            {
                "item_id": 1006,
                "path_kind": "direct",
                "source_kind": "creature",
                "source_id": 62229,
                "reason": "missing_source_identity",
            },
            {
                "item_id": 1006,
                "path_kind": "vendor",
                "source_kind": "creature",
                "source_id": 62230,
                "reason": "missing_source_identity",
            },
        ]
        observed = {
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                """
                SELECT og.fact_key, og.fact_instance_key
                FROM observation_groups AS og
                JOIN source_observations AS so ON so.observation_group_id = og.id
                JOIN data_sources AS ds ON ds.id = so.source_id
                WHERE og.subject_kind = 'item' AND og.subject_key = '1006'
                  AND ds.source_key = 'pfquest-turtle'
                  AND og.fact_key IN ('loot_source', 'vendor_source')
                """
            ).fetchall()
        }
        assert observed == {
            ("loot_source", "creature:62229"),
            ("vendor_source", "creature:62230"),
        }
        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert second.details["canonical_relations_or_identities_deleted"] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
