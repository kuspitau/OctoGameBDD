from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

import pytest

from octogamedb.importers import recipe_acquisition_sources as acquisition


def _write_wdbc(path: Path, field_count: int, rows: list[list[int]]) -> None:
    record_size = field_count * 4
    records = bytearray()
    for row in rows:
        assert len(row) == field_count
        records.extend(struct.pack(f"<{field_count}I", *row))
    strings = b"\0"
    path.write_bytes(
        struct.pack("<4sIIII", b"WDBC", len(rows), field_count, record_size, len(strings))
        + records
        + strings
    )


def test_load_octodbc_learn_effects_preserves_effect_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows: list[list[int]] = []
    craft = [0] * 173
    craft[0] = 1000
    rows.append(craft)

    item_wrapper = [0] * 173
    item_wrapper[0] = 9000
    item_wrapper[61] = acquisition.SPELL_EFFECT_LEARN_SPELL  # effect slot 1; Effect starts at 60
    item_wrapper[109] = 1000  # trigger slot 1; EffectTriggerSpell starts at 108
    rows.append(item_wrapper)

    trainer_wrapper = [0] * 173
    trainer_wrapper[0] = 9001
    trainer_wrapper[60] = acquisition.SPELL_EFFECT_LEARN_SPELL
    trainer_wrapper[108] = 1000
    rows.append(trainer_wrapper)

    _write_wdbc(tmp_path / "Spell.dbc", 173, rows)
    monkeypatch.setattr(acquisition, "inspect_octodbc_recipe_reagent_layouts", lambda _: ())

    effects = acquisition.load_octodbc_learn_effects(tmp_path)
    assert effects == (
        acquisition.LearnEffect(9000, 1, 1000),
        acquisition.LearnEffect(9001, 0, 1000),
    )


def test_load_octodbc_learn_effects_fails_closed_on_unknown_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = [0] * 172
    row[0] = 1
    _write_wdbc(tmp_path / "Spell.dbc", 172, [row])
    monkeypatch.setattr(acquisition, "inspect_octodbc_recipe_reagent_layouts", lambda _: ())

    with pytest.raises(acquisition.RecipeAcquisitionError, match="unsupported P4-T04 layout"):
        acquisition.load_octodbc_learn_effects(tmp_path)


def test_sql_integer_parser_accepts_integral_decimal_but_rejects_fractional() -> None:
    assert acquisition._parse_int("0.0", "field") == 0
    assert acquisition._parse_int("-12.000", "field") == -12
    with pytest.raises(acquisition.RecipeAcquisitionError, match="integer/NULL"):
        acquisition._parse_int("1.5", "field")


def _world_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "tortoise"
    base = repo / "sql" / "base"
    updates = repo / "sql" / "database_updates" / "world"
    base.mkdir(parents=True)
    updates.mkdir(parents=True)

    (base / "tw_world_npc_trainer.sql").write_text(
        """
        DROP TABLE IF EXISTS `npc_trainer`;
        CREATE TABLE `npc_trainer` (
            `entry` int NOT NULL, `spell` int NOT NULL, `spellcost` int NOT NULL,
            `reqskill` int NOT NULL, `reqskillvalue` int NOT NULL, `reqlevel` int NOT NULL
        );
        INSERT INTO `npc_trainer` VALUES (4000,9001,2500,164,75,10);
        """,
        encoding="utf-8",
    )
    (base / "tw_world_npc_trainer_template.sql").write_text(
        """
        CREATE TABLE `npc_trainer_template` (
            `entry` int NOT NULL, `spell` int NOT NULL, `spellcost` int NOT NULL,
            `reqskill` int NOT NULL, `reqskillvalue` int NOT NULL, `reqlevel` int NOT NULL
        );
        INSERT INTO `npc_trainer_template` VALUES (42,9001,3000,164,100,12);
        """,
        encoding="utf-8",
    )
    (base / "tw_world_quest_template.sql").write_text(
        """
        CREATE TABLE `quest_template` (
            `entry` int NOT NULL, `RewSpell` int NOT NULL, `RewSpellCast` int NOT NULL
        );
        INSERT INTO `quest_template` VALUES (5000,0,9002),(5001,9003,0);
        """,
        encoding="utf-8",
    )
    (base / "tw_world_item_template.sql").write_text("", encoding="utf-8")
    (base / "tw_world_creature_template.sql").write_text(
        """
        CREATE TABLE `creature_template` (`entry` int NOT NULL, `trainer_id` int NOT NULL);
        INSERT INTO `creature_template` VALUES (4000,0),(4001,42),(4002,42);
        """,
        encoding="utf-8",
    )
    (base / "tw_world_spell_learn_spell.sql").write_text(
        """
        CREATE TABLE `spell_learn_spell` (
            `entry` int NOT NULL, `SpellID` int NOT NULL, `Active` int NOT NULL
        );
        INSERT INTO `spell_learn_spell` VALUES (9004,1000,1),(9005,1001,1);
        """,
        encoding="utf-8",
    )
    (updates / "001_world.sql").write_text(
        """
        UPDATE `item_template`
        SET `spellid_1`=9000, `spelltrigger_1`=0, `spellcharges_1`=1
        WHERE `entry`=3000;
        UPDATE `npc_trainer` SET `spellcost`=2600 WHERE `entry`=4000 AND `spell`=9001;
        UPDATE `npc_trainer` SET `reqlevel`=6 WHERE `reqlevel` > 6;
        UPDATE `quest_template` SET `RewSpellCast`=0.0 WHERE `entry`=5001;
        UPDATE `quest_template` SET `title`='WHERE commas, AND quotes stay irrelevant'
        WHERE `entry`=5000;
        UPDATE `creature_template` SET `vendor_id` = 0;
        UPDATE `creature_template` SET `vendor_id` = 1 WHERE `spell_list_id` = 99;
        UPDATE `item_template` SET `description`='text, WHERE AND (quoted)' WHERE `class` > 1;
        INSERT INTO `item_template` (`entry`,`spellid_1`) VALUES (0,0);
        DELETE FROM `spell_learn_spell` WHERE (`entry`, `SpellID`) IN
        ((9005,1001),(9999,9999));
        """,
        encoding="utf-8",
    )
    return repo


def test_tortoise_slice_replays_trainer_item_and_quest_evidence(tmp_path: Path) -> None:
    source = acquisition.load_tortoise_acquisition_slice(_world_repo(tmp_path))

    assert source.trainer_offers == (
        acquisition.TrainerOffer("direct", 4000, None, 9001, 2600, 164, 75, 6, "direct:4000:9001"),
        acquisition.TrainerOffer("template", 4001, 42, 9001, 3000, 164, 100, 12, "template:42:9001:creature:4001"),
        acquisition.TrainerOffer("template", 4002, 42, 9001, 3000, 164, 100, 12, "template:42:9001:creature:4002"),
    )
    assert source.item_spell_slots == (
        acquisition.ItemSpellSlot(3000, 0, 9000, 0, 1, "item:3000:spell:0"),
    )
    assert source.quest_reward_spells == (
        acquisition.QuestRewardSpell(5000, "RewSpellCast", 9002, "quest:5000:RewSpellCast"),
        acquisition.QuestRewardSpell(5001, "RewSpell", 9003, "quest:5001:RewSpell"),
    )
    assert source.server_learn_links == (
        acquisition.ServerLearnLink(9004, 1000, 1, "spell_learn_spell:9004:1000"),
    )
    assert source.unmapped_trainer_template_ids == ()
    assert source.input_count == 7


def test_tortoise_slice_rejects_unhandled_relevant_mutation(tmp_path: Path) -> None:
    for index, sql in enumerate(
        (
            "DELETE FROM npc_trainer WHERE entry LIKE '1%';",
            "ALTER TABLE npc_trainer ADD COLUMN unsupported_flag int NOT NULL DEFAULT 0;",
        ),
        start=1,
    ):
        repo = _world_repo(tmp_path / str(index))
        update = repo / "sql" / "database_updates" / "world" / "002_world.sql"
        update.write_text(sql, encoding="utf-8")
        with pytest.raises(acquisition.RecipeAcquisitionError, match="refusing to guess"):
            acquisition.load_tortoise_acquisition_slice(repo)


def _minimal_schema(connection: sqlite3.Connection, migration_sql: str) -> None:
    connection.executescript(
        """
        CREATE TABLE data_sources(
            id INTEGER PRIMARY KEY, source_key TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
            source_kind TEXT NOT NULL, source_path TEXT, updated_at TEXT DEFAULT ''
        );
        CREATE TABLE import_batches(
            id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, source_revision TEXT,
            status TEXT NOT NULL, importer_version TEXT, rows_read INTEGER DEFAULT 0,
            rows_accepted INTEGER DEFAULT 0, rows_skipped INTEGER DEFAULT 0,
            rows_inserted INTEGER DEFAULT 0, rows_updated INTEGER DEFAULT 0,
            warning_count INTEGER DEFAULT 0, error_count INTEGER DEFAULT 0,
            details_json TEXT, finished_at TEXT
        );
        CREATE TABLE observation_groups(
            id INTEGER PRIMARY KEY, subject_kind TEXT NOT NULL, subject_key TEXT NOT NULL,
            fact_key TEXT NOT NULL, fact_kind TEXT NOT NULL, fact_instance_key TEXT NOT NULL DEFAULT '',
            UNIQUE(subject_kind, subject_key, fact_key, fact_instance_key)
        );
        CREATE TABLE source_observations(
            id INTEGER PRIMARY KEY, observation_group_id INTEGER NOT NULL, source_id INTEGER NOT NULL,
            source_revision TEXT NOT NULL DEFAULT '', source_record_type TEXT, raw_identifier TEXT,
            value_json TEXT NOT NULL, confidence REAL, authority_tier INTEGER,
            UNIQUE(observation_group_id, source_id, source_revision, source_record_type, raw_identifier, value_json)
        );
        CREATE TABLE observation_import_batches(
            observation_id INTEGER NOT NULL, import_batch_id INTEGER NOT NULL,
            PRIMARY KEY(observation_id, import_batch_id)
        );
        CREATE TABLE canonical_selections(
            observation_group_id INTEGER PRIMARY KEY, observation_id INTEGER NOT NULL,
            selection_policy TEXT, selection_reason TEXT NOT NULL, selected_at TEXT DEFAULT ''
        );
        CREATE TABLE items(item_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE creatures(creature_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE quests(quest_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE spells(spell_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE recipes(
            recipe_id INTEGER PRIMARY KEY,
            crafting_spell_id INTEGER UNIQUE NOT NULL REFERENCES spells(spell_id),
            CHECK(recipe_id=crafting_spell_id)
        );
        """
    )
    connection.executescript(migration_sql)


def _record_relation_observation(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    import_batch_id: int,
    target_kind: str,
    target_key: str | int,
    relation_instance_key: str,
    attributes: dict[str, object] | None = None,
    source_record_type: str | None = None,
    raw_identifier: str | int | None = None,
    confidence: float | None = None,
    authority_tier: int | None = None,
) -> int:
    import json

    row = connection.execute(
        """
        SELECT id FROM observation_groups
        WHERE subject_kind=? AND subject_key=? AND fact_key=? AND fact_instance_key=?
        """,
        (subject_kind, str(subject_key), fact_key, relation_instance_key),
    ).fetchone()
    if row is None:
        group_id = connection.execute(
            """
            INSERT INTO observation_groups(subject_kind,subject_key,fact_key,fact_kind,fact_instance_key)
            VALUES (?,?,?,'relation',?)
            """,
            (subject_kind, str(subject_key), fact_key, relation_instance_key),
        ).lastrowid
    else:
        group_id = int(row[0])
    batch = connection.execute(
        "SELECT source_id, source_revision FROM import_batches WHERE id=?", (import_batch_id,)
    ).fetchone()
    payload: dict[str, object] = {"target": {"kind": target_kind, "key": str(target_key)}}
    if attributes is not None:
        payload["attributes"] = attributes
    value_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    existing = connection.execute(
        """
        SELECT id FROM source_observations
        WHERE observation_group_id=? AND source_id=? AND source_revision=?
          AND source_record_type IS ? AND raw_identifier IS ? AND value_json=?
        """,
        (group_id, int(batch[0]), str(batch[1]), source_record_type, str(raw_identifier), value_json),
    ).fetchone()
    if existing is None:
        observation_id = connection.execute(
            """
            INSERT INTO source_observations(
                observation_group_id,source_id,source_revision,source_record_type,
                raw_identifier,value_json,confidence,authority_tier
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                group_id,
                int(batch[0]),
                str(batch[1]),
                source_record_type,
                str(raw_identifier),
                value_json,
                confidence,
                authority_tier,
            ),
        ).lastrowid
    else:
        observation_id = int(existing[0])
    connection.execute(
        "INSERT OR IGNORE INTO observation_import_batches VALUES (?,?)",
        (observation_id, import_batch_id),
    )
    return int(observation_id)


def _select_canonical_observation(
    connection: sqlite3.Connection,
    *, observation_group_id: int, observation_id: int,
    selection_policy: str | None, selection_reason: str
) -> None:
    connection.execute(
        """
        INSERT INTO canonical_selections(observation_group_id,observation_id,selection_policy,selection_reason)
        VALUES (?,?,?,?)
        ON CONFLICT(observation_group_id) DO UPDATE SET
          observation_id=excluded.observation_id, selection_policy=excluded.selection_policy,
          selection_reason=excluded.selection_reason
        """,
        (observation_group_id, observation_id, selection_policy, selection_reason),
    )


def test_import_materializes_only_proven_learning_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migration_sql = (
        Path(__file__).parents[1]
        / "src"
        / "octogamedb"
        / "db"
        / "migrations"
        / "0013_recipe_acquisition_sources.sql"
    ).read_text(encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    _minimal_schema(connection, migration_sql)

    connection.executemany("INSERT INTO spells VALUES (?,?)", [(1000, "Craft"), (9000, "Learn"), (9001, "Trainer"), (9002, "Quest"), (9004, "ServerLearn")])
    connection.execute("INSERT INTO recipes VALUES (1000,1000)")
    connection.execute("INSERT INTO items VALUES (3000,'Teaching item')")
    connection.executemany("INSERT INTO creatures VALUES (?,?)", [(4000,'Trainer'), (4001,'Template trainer')])
    connection.executemany("INSERT INTO quests VALUES (?,?)", [(5000,'Quest'), (5001,'Server quest')])
    connection.execute(
        "INSERT INTO data_sources(source_key,display_name,source_kind,source_path) VALUES ('octo-client-dbc','Octo','dbc','x')"
    )
    source_id = connection.execute("SELECT id FROM data_sources WHERE source_key='octo-client-dbc'").fetchone()[0]
    connection.execute(
        """
        INSERT INTO import_batches(source_id,source_revision,status,importer_version,rows_read,finished_at)
        VALUES (?,'dbc-rev','succeeded',?,1,'done')
        """,
        (source_id, acquisition.IDENTITY_IMPORTER_VERSION),
    )

    monkeypatch.setattr(
        acquisition,
        "load_tortoise_acquisition_slice",
        lambda _: acquisition.TortoiseAcquisitionSlice(
            trainer_offers=(
                acquisition.TrainerOffer("direct", 4000, None, 9001, 20, 164, 75, 10, "trainer"),
                acquisition.TrainerOffer("template", 4001, 42, 9001, 20, 164, 75, 10, "template"),
            ),
            item_spell_slots=(acquisition.ItemSpellSlot(3000, 0, 9000, 0, 1, "item"),),
            quest_reward_spells=(
                acquisition.QuestRewardSpell(5000, "RewSpellCast", 9002, "quest"),
                acquisition.QuestRewardSpell(5001, "RewSpell", 9004, "server-quest"),
            ),
            server_learn_links=(
                acquisition.ServerLearnLink(9002, 1000, 0, "corroborating-server"),
                acquisition.ServerLearnLink(9004, 1000, 1, "server"),
            ),
            unmapped_trainer_template_ids=(),
            source_revision='{"file_count":1,"git_revision":null,"manifest_sha256":"x"}',
            git_revision=None,
            input_count=1,
        ),
    )
    monkeypatch.setattr(acquisition, "compute_octodbc_recipe_reagent_revision", lambda _: "dbc-rev")
    monkeypatch.setattr(
        acquisition,
        "load_octodbc_learn_effects",
        lambda _: (
            acquisition.LearnEffect(9000, 1, 1000),
            acquisition.LearnEffect(9001, 0, 1000),
            acquisition.LearnEffect(9002, 2, 1000),
        ),
    )
    monkeypatch.setattr(acquisition, "record_relation_observation", _record_relation_observation)
    monkeypatch.setattr(acquisition, "select_canonical_observation", _select_canonical_observation)

    first = acquisition.import_recipe_acquisition_sources(
        connection, tortoise_repo=tmp_path, dbc_root=tmp_path
    )
    second = acquisition.import_recipe_acquisition_sources(
        connection, tortoise_repo=tmp_path, dbc_root=tmp_path
    )

    assert first.rows_inserted == 5
    assert second.rows_inserted == 0
    assert second.rows_updated == 0
    assert connection.execute("SELECT COUNT(*) FROM recipe_teaching_items").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM recipe_trainer_sources").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM recipe_quest_learning_sources").fetchone()[0] == 2
    template = connection.execute(
        "SELECT creature_id, trainer_template_id FROM recipe_trainer_sources WHERE trainer_kind='template'"
    ).fetchone()
    assert tuple(template) == (4001, 42)
    quest_dbc = connection.execute(
        "SELECT learning_proof_kind, learn_effect_index, server_learn_active FROM recipe_quest_learning_sources WHERE native_quest_id=5000"
    ).fetchone()
    assert tuple(quest_dbc) == ("octo_dbc_learn_spell", 2, 0)
    quest_server = connection.execute(
        "SELECT learning_proof_kind, learn_effect_index, server_learn_active FROM recipe_quest_learning_sources WHERE native_quest_id=5001"
    ).fetchone()
    assert tuple(quest_server) == ("tortoise_spell_learn_spell", None, 1)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
