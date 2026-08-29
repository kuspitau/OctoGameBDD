from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_p6_t02.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("p6_t02_validator_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_export_parser_preserves_ids_statuses_and_completion():
    module = _load_validator()
    parsed = module.parse_export_string(
        "v=1|probe_id=abc|started=123|realm=N_Zoth|character=Tester|locale=enUS|"
        "client_version=1.12.1|client_build=5875|ids=10,20|"
        "results=10:missing:loaded_after_query,20:missing:timeout_unknown|complete=1"
    )

    assert parsed["ids"] == [10, 20]
    assert parsed["results"][10]["initial"] == "missing"
    assert parsed["results"][10]["status"] == "loaded_after_query"
    assert parsed["results"][20]["status"] == "timeout_unknown"
    assert parsed["complete"] is True


def test_probe_export_parser_fails_closed_on_unknown_version():
    module = _load_validator()
    with pytest.raises(ValueError, match="Unsupported probe export version"):
        module.parse_export_string("v=2|ids=10|results=|complete=0")


def test_saved_variables_discovery_requires_exact_preflight_id_list(tmp_path: Path):
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
        'OctoGameBDD_ItemProbeExport = "v=1|probe_id=abc|started=123|realm=N_Zoth|'
        'character=Tester|locale=enUS|client_version=1.12.1|client_build=5875|ids=10,20|'
        'results=10:missing:loaded_after_query,20:missing:timeout_unknown|complete=1"\n',
        encoding="utf-8",
    )

    path, parsed = module.find_matching_saved_variables(tmp_path, [10, 20])
    assert path == saved
    assert parsed["complete"] is True

    with pytest.raises(FileNotFoundError, match="No SavedVariables capture matches"):
        module.find_matching_saved_variables(tmp_path, [20, 10])


def test_find_itemcache_optional_accepts_clean_wdb_then_finds_created_locale_cache(
    tmp_path: Path,
):
    module = _load_validator()
    wow_root = tmp_path / "Wow"
    (wow_root / "WDB").mkdir(parents=True)

    assert module.find_itemcache_optional(wow_root, "enUS") is None

    cache = wow_root / "WDB" / "enUS" / "itemcache.wdb"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"placeholder")

    assert module.find_itemcache_optional(wow_root, "enUS") == cache.resolve()


def test_expected_itemcache_path_does_not_create_clean_cache(tmp_path: Path):
    module = _load_validator()
    wow_root = tmp_path / "Wow"
    (wow_root / "WDB").mkdir(parents=True)

    expected = module.expected_itemcache_path(wow_root, "enUS")

    assert expected == (wow_root / "WDB" / "enUS" / "itemcache.wdb").resolve()
    assert not expected.exists()
