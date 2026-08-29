from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_p6_t03.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("p6_t03_validator_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_update_preserves_unrelated_sections_and_only_sets_wow_root(tmp_path: Path):
    module = _load_validator()
    config = tmp_path / "config.local.toml"
    config.write_text(
        '[paths]\nraw = "custom/raw"\n\n[source_paths]\npfquest = "C:/pfQuest"\n',
        encoding="utf-8",
    )
    wow_root = tmp_path / "Wow"
    module.update_wow_root_config(config, wow_root)
    text = config.read_text(encoding="utf-8")
    assert '[paths]\nraw = "custom/raw"' in text
    assert 'pfquest = "C:/pfQuest"' in text
    assert f'wow_root = "{wow_root.resolve().as_posix()}"' in text

    module.update_wow_root_config(config, wow_root)
    assert config.read_text(encoding="utf-8").count("wow_root =") == 1


def test_wow_root_validation_requires_executable_and_addons(tmp_path: Path):
    module = _load_validator()
    root = tmp_path / "Wow"
    root.mkdir()
    assert module.validate_wow_root(root)[0] is False
    (root / "WoW.exe").write_bytes(b"")
    assert module.validate_wow_root(root)[0] is False
    (root / "Interface" / "AddOns").mkdir(parents=True)
    okay, detail = module.validate_wow_root(root)
    assert okay is True
    assert "Interface/AddOns" in detail


def test_export_parser_accepts_v1_and_fails_closed_on_duplicates_or_version():
    module = _load_validator()
    parsed = module.parse_export_string(
        "v=1|probe_id=abc|ids=10,20|results=10:missing:loaded_after_query,"
        "20:missing:timeout_unknown|complete=1"
    )
    assert parsed["ids"] == [10, 20]
    assert parsed["results"][10]["status"] == "loaded_after_query"
    assert parsed["complete"] is True

    with pytest.raises(ValueError, match="duplicate IDs"):
        module.parse_export_string("v=1|ids=10,10|results=|complete=0")
    with pytest.raises(ValueError, match="Unsupported probe export version"):
        module.parse_export_string("v=2|ids=10|results=|complete=0")


def test_savedvariables_discovery_requires_exact_ordered_batch(tmp_path: Path):
    module = _load_validator()
    saved = (
        tmp_path
        / "WTF"
        / "Account"
        / "TEST"
        / "SavedVariables"
        / "OctoGameBDD_ItemProbe.lua"
    )
    saved.parent.mkdir(parents=True)
    saved.write_text(
        'OctoGameBDD_ItemProbeExport = "v=1|probe_id=abc|ids=10,20|'
        'results=10:missing:loaded_after_query,20:missing:timeout_unknown|complete=1"\n',
        encoding="utf-8",
    )
    path, export = module.find_matching_saved_variables(tmp_path, [10, 20])
    assert path == saved
    assert export["complete"] is True
    with pytest.raises(FileNotFoundError, match="No SavedVariables capture matches"):
        module.find_matching_saved_variables(tmp_path, [20, 10])


def test_tasklist_parser_is_locale_independent_for_csv_image_names():
    module = _load_validator()
    images = module.running_task_images(
        '"System Idle Process","0","Services","0","8 K"\n'
        '"WoW.exe","1234","Console","1","500,000 K"\n'
    )
    assert "wow.exe" in images


def test_expected_itemcache_path_does_not_create_any_cache(tmp_path: Path):
    module = _load_validator()
    root = tmp_path / "Wow"
    root.mkdir()
    expected = module.expected_itemcache_path(root, "enUS")
    assert expected == (root / "WDB" / "enUS" / "itemcache.wdb").resolve()
    assert not expected.exists()


def test_clean_cache_coverage_uses_read_only_canonical_connection(tmp_path: Path):
    module = _load_validator()
    import sqlite3

    db = tmp_path / "canonical.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE items(item_id INTEGER PRIMARY KEY)")
        connection.executemany("INSERT INTO items(item_id) VALUES (?)", [(1,), (2,), (3,)])
    before = db.read_bytes()
    report = module.coverage_report(db, None, tmp_path / "WDB" / "enUS" / "itemcache.wdb")
    assert report["counts"]["canonical_items"] == 3
    assert report["canonical_item_ids_missing_from_cache_unknown"] == [1, 2, 3]
    assert db.read_bytes() == before


def test_present_cache_coverage_delegates_to_validated_p6_t02_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load_validator()
    import sqlite3

    db = tmp_path / "canonical.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE items(item_id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO items(item_id) VALUES (1)")
    cache = tmp_path / "itemcache.wdb"
    cache.write_bytes(b"fixture-placeholder")
    seen = {}

    def fake_builder(connection, *, source_path):
        seen["source_path"] = source_path
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
        return {"coverage_revision": "present-sentinel", "counts": {}}

    monkeypatch.setattr(module, "build_itemcache_coverage_report", fake_builder)
    report = module.coverage_report(db, cache, tmp_path / "unused")
    assert report["coverage_revision"] == "present-sentinel"
    assert seen["source_path"] == cache
