from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from octogamedb.importers.quest_source_evidence import (
    SOURCE_CMANGOS,
    SOURCE_LIVE,
    SOURCE_OCTODB,
    SOURCE_TORTOISE,
    UnsupportedQuestSQL,
    compare_source_snapshots,
    load_tortoise_quest_projection,
    normalize_live_saved_variables,
)

FIXTURES = Path(__file__).parent / "fixtures" / "p3_t05b"


def _copy_fixture_repo(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    shutil.copytree(FIXTURES / name, target)
    return target


def test_tortoise_replay_preserves_slots_zero_counts_duplicates_and_later_update(tmp_path: Path):
    repository = _copy_fixture_repo(tmp_path, "tortoise_repo")
    result = load_tortoise_quest_projection(
        repository,
        quest_ids=[818, 815, 40788],
        source_revision="fixture-revision",
    )

    quest = result["quests"]["818"]
    assert quest["required_items"][:2] == [
        {
            "slot": 1,
            "item_id": 1001,
            "count": 4,
            "id_field": "ReqItemId1",
            "count_field": "ReqItemCount1",
        },
        {
            "slot": 2,
            "item_id": 1001,
            "count": 1,
            "id_field": "ReqItemId2",
            "count_field": "ReqItemCount2",
        },
    ]
    assert quest["required_items"][2]["item_id"] == 0
    assert quest["required_items"][2]["count"] == 0
    assert quest["required_sources"][0]["item_id"] == 1001
    assert quest["required_sources"][0]["count"] == 0
    assert quest["reward_items"][0]["count"] == 2
    assert result["quests"]["815"]["required_items"][0]["count"] == 3
    assert result["quests"]["40788"]["required_sources"][0]["count"] == 0
    assert result["relevant_migration_count"] == 2
    assert result["missing_requested_quest_ids"] == []
    assert all(item["path"] != "sql/create_databases.sql" for item in result["inputs"])


def test_tortoise_projection_hash_is_deterministic(tmp_path: Path):
    repository = _copy_fixture_repo(tmp_path, "tortoise_repo")
    first = load_tortoise_quest_projection(repository, quest_ids=[818], source_revision="fixture")
    second = load_tortoise_quest_projection(repository, quest_ids=[818], source_revision="fixture")
    assert first["content_hash"] == second["content_hash"]
    assert first["projection_hash"] == second["projection_hash"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_tortoise_fails_closed_on_unsupported_bounded_mutation(tmp_path: Path):
    repository = _copy_fixture_repo(tmp_path, "tortoise_unsupported")
    with pytest.raises(UnsupportedQuestSQL, match="integer/NULL literal"):
        load_tortoise_quest_projection(repository, quest_ids=[818], source_revision="fixture")


def test_live_normalizer_preserves_positive_evidence_and_unknown_semantics(tmp_path: Path):
    saved_variables = tmp_path / "probe.lua"
    shutil.copyfile(FIXTURES / "live_savedvariables.lua", saved_variables)

    result = normalize_live_saved_variables(saved_variables)
    quest = result["quests"]["818"]
    assert quest["status"] == "success"
    assert quest["capture_metadata"]["realm"] == "Néant"
    assert quest["required_items"]["items"] == [{"item_id": 1001, "count": 7}]
    assert quest["reward_items"]["items"] == [{"item_id": 3001, "count": 1}]
    assert quest["choice_reward_items"]["items"] == [
        {"item_id": 4001, "count": 1},
        {"item_id": 4002, "count": 2},
    ]
    assert quest["source_item"] == {
        "id_status": "observed_positive",
        "item_id": 2001,
        "count_status": "unknown",
        "count": None,
    }
    assert quest["required_sources"] == {"status": "unknown", "items": []}
    assert all(item["fact_family"] != "source_item_count" for item in quest["evidence"])
    assert all(item["fact_family"] != "required_source" for item in quest["evidence"])

    empty_success = result["quests"]["949"]
    assert empty_success["required_items"]["status"] == "unknown"
    assert empty_success["reward_items"]["status"] == "unknown"
    assert empty_success["choice_reward_items"]["status"] == "unknown"
    assert empty_success["source_item"]["id_status"] == "unknown"

    failure = result["quests"]["436"]
    assert failure["status"] == "query_failed"
    assert failure["evidence"] == []
    assert failure["error"] == "server returned failure"


def test_live_capture_hash_is_deterministic(tmp_path: Path):
    saved_variables = tmp_path / "probe.lua"
    shutil.copyfile(FIXTURES / "live_savedvariables.lua", saved_variables)
    first = normalize_live_saved_variables(saved_variables)
    second = normalize_live_saved_variables(saved_variables)
    assert first["capture_hash"] == second["capture_hash"]
    assert first["raw_saved_variables_sha256"] == second["raw_saved_variables_sha256"]


def _snapshot(source_key: str, value: int, *, slot: int = 1) -> dict:
    return {
        "source_key": source_key,
        "source_revision": "fixture",
        "quests": {
            "818": {
                "quest_id": 818,
                "evidence": [
                    {
                        "fact_family": "required_item",
                        "fact_key": "required_item:1001",
                        "item_id": 1001,
                        "value": value,
                        "slot": slot,
                    }
                ],
            }
        },
    }


def test_comparison_chooses_higher_priority_and_retains_conflict_evidence():
    result = compare_source_snapshots(
        [
            _snapshot(SOURCE_CMANGOS, 2),
            _snapshot(SOURCE_TORTOISE, 4),
            _snapshot(SOURCE_OCTODB, 6),
            _snapshot(SOURCE_LIVE, 7),
        ]
    )
    fact = result["quests"]["818"]["facts"]["required_item:1001"]
    assert fact["selected"] == {"source_key": SOURCE_LIVE, "value": 7, "priority": 40}
    assert fact["conflict"] is True
    assert [item["source_key"] for item in fact["evidence"]] == [
        SOURCE_LIVE,
        SOURCE_OCTODB,
        SOURCE_TORTOISE,
        SOURCE_CMANGOS,
    ]


def test_comparison_preserves_same_source_slot_duplicates_without_silent_choice():
    snapshot = _snapshot(SOURCE_TORTOISE, 4, slot=1)
    snapshot["quests"]["818"]["evidence"].append(
        {
            "fact_family": "required_item",
            "fact_key": "required_item:1001",
            "item_id": 1001,
            "value": 5,
            "slot": 2,
        }
    )
    fact = compare_source_snapshots([snapshot])["quests"]["818"]["facts"]["required_item:1001"]
    assert fact["selection_status"] == "ambiguous_same_priority"
    assert fact["selected"] is None
    assert len(fact["evidence"]) == 2


def test_required_source_priority_excludes_octodb_and_live():
    bad = {
        "source_key": SOURCE_LIVE,
        "quests": {
            "818": {
                "evidence": [
                    {
                        "fact_family": "required_source",
                        "fact_key": "required_source:5000",
                        "item_id": 5000,
                        "value": 0,
                        "slot": 1,
                    }
                ]
            }
        },
    }
    with pytest.raises(Exception, match="not eligible evidence"):
        compare_source_snapshots([bad])


def test_tortoise_can_use_authoritative_create_databases_schema(tmp_path: Path):
    repository = _copy_fixture_repo(tmp_path, "tortoise_schema_external")
    result = load_tortoise_quest_projection(repository, quest_ids=[818], source_revision="fixture")
    assert result["quests"]["818"]["required_items"][0]["count"] == 2
    assert result["quests"]["818"]["required_sources"][0]["count"] == 0
    assert result["inputs"][0]["path"] == "sql/create_databases.sql"


def test_reviewed_evidence_csv_is_strict_and_deterministic():
    from octogamedb.importers.quest_source_evidence import load_evidence_csv

    result = load_evidence_csv(
        FIXTURES / "reviewed_octodb.csv", source_key=SOURCE_OCTODB, source_revision="page-hash-manifest"
    )
    assert result["quests"]["818"]["evidence"][0]["fact_key"] == "required_item:1001"
    assert result["source_revision"] == "page-hash-manifest"
    assert len(result["projection_hash"]) == 64



def test_tortoise_insert_ignore_and_replace_follow_mysql_row_semantics(tmp_path: Path):
    repository = _copy_fixture_repo(tmp_path, "tortoise_insert_semantics")
    result = load_tortoise_quest_projection(repository, quest_ids=[818], source_revision="fixture")
    assert result["quests"]["818"]["required_items"][0]["count"] == 4
    assert result["relevant_migration_count"] == 2


def test_tortoise_plain_duplicate_insert_fails_closed(tmp_path: Path):
    repository = _copy_fixture_repo(tmp_path, "tortoise_duplicate_insert")
    with pytest.raises(UnsupportedQuestSQL, match="plain INSERT duplicates"):
        load_tortoise_quest_projection(repository, quest_ids=[818], source_revision="fixture")


def test_tortoise_drop_table_migration_fails_closed(tmp_path: Path):
    repository = _copy_fixture_repo(tmp_path, "tortoise_drop_migration")
    with pytest.raises(UnsupportedQuestSQL, match="unsupported quest_template mutation"):
        load_tortoise_quest_projection(repository, quest_ids=[818], source_revision="fixture")


def test_comparison_preserves_failure_only_and_unknown_live_quest_observations(tmp_path: Path):
    saved_variables = tmp_path / "probe.lua"
    shutil.copyfile(FIXTURES / "live_savedvariables.lua", saved_variables)
    live = normalize_live_saved_variables(saved_variables)
    result = compare_source_snapshots([live])
    assert result["quests"]["436"]["facts"] == {}
    assert result["quests"]["436"]["source_observations"] == [
        {
            "source_key": SOURCE_LIVE,
            "status": "query_failed",
            "required_items_status": "unknown",
            "reward_items_status": "unknown",
            "choice_reward_items_status": "unknown",
            "required_sources_status": "unknown",
            "source_item_id_status": "unknown",
            "source_item_count_status": "unknown",
        }
    ]
    assert result["quests"]["949"]["facts"] == {}


def test_reviewed_evidence_csv_rejects_header_reordering_and_negative_counts(tmp_path: Path):
    from octogamedb.importers.quest_source_evidence import QuestSourceError, load_evidence_csv

    reordered = tmp_path / "reordered.csv"
    reordered.write_text(
        "fact_family,quest_id,item_id,value,slot\nrequired_item,818,1001,2,1\n",
        encoding="utf-8",
    )
    with pytest.raises(QuestSourceError, match="header must be exactly"):
        load_evidence_csv(reordered, source_key=SOURCE_OCTODB, source_revision="fixture")

    negative = tmp_path / "negative.csv"
    negative.write_text(
        "quest_id,fact_family,item_id,value,slot\n818,required_item,1001,-1,1\n",
        encoding="utf-8",
    )
    with pytest.raises(QuestSourceError, match="non-negative value"):
        load_evidence_csv(negative, source_key=SOURCE_OCTODB, source_revision="fixture")



def _load_validation_script_module():
    script = Path(__file__).parents[1] / "scripts" / "validate_p3_t05b.py"
    spec = importlib.util.spec_from_file_location("validate_p3_t05b_test_module", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_path_update_replaces_spacing_variants_and_preserves_unrelated_settings(tmp_path: Path):
    module = _load_validation_script_module()
    config = tmp_path / "config.local.toml"
    config.write_text(
        '[paths]\nraw = "data/raw"\n\n[source_paths]\nwow_root="C:/old"\npfquest = "C:/keep"\n',
        encoding="utf-8",
    )
    replacement = tmp_path / "wow"
    replacement.mkdir()
    module._update_source_paths(config, {"wow_root": replacement})
    text = config.read_text(encoding="utf-8")
    assert text.count("wow_root =") == 1
    assert f'wow_root = "{replacement.resolve().as_posix()}"' in text
    assert 'pfquest = "C:/keep"' in text
    assert '[paths]\nraw = "data/raw"' in text


def test_probe_uses_classicapi_nil_failure_semantics_and_remains_manually_bounded():
    probe = (
        Path(__file__).parents[1]
        / "scripts"
        / "octogamedb_quest_probe"
        / "OctoGameBDD_QuestProbe.lua"
    ).read_text(encoding="utf-8")
    assert "local MAX_QUEUE = 50" in probe
    assert "if not eventSuccess then" in probe
    assert 'SLASH_OCTOGAMEDBQUESTPROBE1 = "/oqpb"' in probe
    assert 'frame:RegisterEvent("QUEST_DATA_LOAD_RESULT")' in probe



def test_tortoise_cli_does_not_allow_declared_revision_to_mask_checkout_head(tmp_path: Path, monkeypatch):
    module = _load_validation_script_module()
    monkeypatch.setattr(module, "detect_git_revision", lambda _path: "actual-head")
    args = module.argparse.Namespace(
        config=str(tmp_path / "missing.toml"),
        tortoise_repo=str(tmp_path),
        source_revision="declared-head",
        allow_unpinned=True,
        schema_sql=None,
        quest_id=[818],
        output=str(tmp_path / "out.json"),
    )
    with pytest.raises(module.QuestSourceError, match="disagrees with the checkout HEAD"):
        module.cmd_tortoise(args)
