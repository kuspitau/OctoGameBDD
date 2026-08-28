from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "configure_p5_t07_paths.py"
    spec = importlib.util.spec_from_file_location("configure_p5_t07_paths", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_update_source_paths_preserves_unrelated_configuration(tmp_path):
    module = _load_module()
    config = tmp_path / "config.local.toml"
    config.write_text(
        "# keep me\n"
        "[paths]\n"
        "generated = \"data/generated\"\n\n"
        "[source_paths]\n"
        "pfquest = \"old\"\n"
        "octo_dbc = \"D:/DBC\"\n\n"
        "[other]\n"
        "flag = true\n",
        encoding="utf-8",
    )
    roots = {
        "pfquest": tmp_path / "pfQuest",
        "pfquest_turtle": tmp_path / "pfQuest-turtle",
        "pfquest_octo": tmp_path / "pfQuest-octo",
    }
    for root in roots.values():
        root.mkdir()

    module._update_source_paths(config, roots)
    first = config.read_text(encoding="utf-8")
    module._update_source_paths(config, roots)
    second = config.read_text(encoding="utf-8")

    assert first == second
    assert "# keep me" in first
    assert 'octo_dbc = "D:/DBC"' in first
    assert "[other]\nflag = true" in first
    for key, root in roots.items():
        assert f'{key} = "{root.resolve().as_posix()}"' in first


def test_update_source_paths_adds_missing_section(tmp_path):
    module = _load_module()
    config = tmp_path / "config.local.toml"
    config.write_text("[paths]\nraw = \"data/raw\"\n", encoding="utf-8")
    root = tmp_path / "pfQuest"
    root.mkdir()

    module._update_source_paths(config, {"pfquest": root})
    text = config.read_text(encoding="utf-8")
    assert "[paths]\nraw = \"data/raw\"" in text
    assert "[source_paths]" in text
    assert f'pfquest = "{root.resolve().as_posix()}"' in text
