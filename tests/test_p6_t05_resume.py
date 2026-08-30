from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_p6_t05_resume.py"


def _load():
    spec = importlib.util.spec_from_file_location("p6_t05_resume_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resume_reads_exact_durable_batch_and_command(tmp_path: Path):
    module = _load()
    ledger = tmp_path / "campaign.json"
    ledger.write_text(
        json.dumps({"active_session": {"requested_item_ids": [10, 20, 30]}}),
        encoding="utf-8",
    )
    assert module.load_active_request_ids(ledger) == (10, 20, 30)
    assert module.in_game_command((10, 20, 30)) == "/ogitemprobe start 10,20,30"


def test_resume_fails_closed_on_duplicate_ids(tmp_path: Path):
    module = _load()
    ledger = tmp_path / "campaign.json"
    ledger.write_text(
        json.dumps({"active_session": {"requested_item_ids": [10, 10]}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique positive"):
        module.load_active_request_ids(ledger)


def test_resume_reuses_campaign_batch_policy(tmp_path: Path):
    module = _load()
    ledger = tmp_path / "campaign.json"
    ledger.write_text(
        json.dumps({"policy": {"batch_limit": 5}, "active_session": None}),
        encoding="utf-8",
    )
    assert module.load_campaign_batch_limit(ledger) == 5



def test_resume_defaults_follow_current_baseline_and_preserve_historical_replay():
    module = _load()
    current = module.parse_args([])
    assert current.baseline == "current"
    assert current.campaign == module.DEFAULT_CURRENT_CAMPAIGN

    historical = module.parse_args(["--baseline", "p6-t05-input"])
    assert historical.campaign == module.DEFAULT_HISTORICAL_CAMPAIGN
