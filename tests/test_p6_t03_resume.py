from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_p6_t03_resume.py"


def _load_resume_module():
    spec = importlib.util.spec_from_file_location("p6_t03_resume_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_active_request_ids_handles_missing_idle_and_in_flight(tmp_path: Path):
    module = _load_resume_module()
    ledger = tmp_path / "campaign.json"
    assert module.load_active_request_ids(ledger) == ()

    ledger.write_text(json.dumps({"active_session": None}), encoding="utf-8")
    assert module.load_active_request_ids(ledger) == ()

    ledger.write_text(
        json.dumps({"active_session": {"requested_item_ids": [10, 20, 30]}}),
        encoding="utf-8",
    )
    assert module.load_active_request_ids(ledger) == (10, 20, 30)
    assert module.in_game_command((10, 20, 30)) == "/ogitemprobe start 10,20,30"


def test_load_active_request_ids_fails_closed_on_malformed_ledger(tmp_path: Path):
    module = _load_resume_module()
    ledger = tmp_path / "campaign.json"

    ledger.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="ledger root"):
        module.load_active_request_ids(ledger)

    ledger.write_text(json.dumps({"active_session": []}), encoding="utf-8")
    with pytest.raises(TypeError, match="active_session"):
        module.load_active_request_ids(ledger)

    ledger.write_text(
        json.dumps({"active_session": {"requested_item_ids": [10, 10]}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique positive"):
        module.load_active_request_ids(ledger)


def test_capture_not_ready_is_narrow():
    module = _load_resume_module()
    assert module.is_capture_not_ready(
        "[FAIL] No SavedVariables capture matches the active campaign ID list."
    )
    assert module.is_capture_not_ready("matching SavedVariables capture is incomplete")
    assert not module.is_capture_not_ready("canonical DB hash drift")
    assert not module.is_capture_not_ready("WoW must be fully closed")
