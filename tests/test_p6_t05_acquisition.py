from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from octogamedb.canonical_baseline import (
    ACCEPTED_CANONICAL_BASELINE,
    P6_T05_INPUT_BASELINE,
)
from octogamedb.itemcache_campaign import (
    STATE_QUEUED,
    STATE_UNKNOWN_RETRYABLE,
    create_campaign_ledger,
)

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_p6_t05_acquisition.py"


def _load():
    spec = importlib.util.spec_from_file_location("p6_t05_acquisition_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ledger(*, attempted: int, queued: int, retryable: int, batch_limit: int = 20):
    items = {}
    ids = []
    next_id = 1
    for _ in range(attempted - retryable):
        ids.append(next_id)
        items[str(next_id)] = {
            "state": "refresh_proven_direct_observation",
            "attempt_count": 1,
        }
        next_id += 1
    for _ in range(retryable):
        ids.append(next_id)
        items[str(next_id)] = {"state": STATE_UNKNOWN_RETRYABLE, "attempt_count": 1}
        next_id += 1
    for _ in range(queued):
        ids.append(next_id)
        items[str(next_id)] = {"state": STATE_QUEUED, "attempt_count": 0}
        next_id += 1
    return {
        "active_session": None,
        "policy": {"batch_limit": batch_limit},
        "candidate_item_ids": ids,
        "items": items,
    }


def test_bounded_selector_never_reserves_a_101st_unique_id():
    module = _load()
    ledger = _ledger(attempted=100, queued=50, retryable=2)
    selected = module.bounded_select_next_batch(ledger, limit=20)
    assert selected
    assert all(ledger["items"][str(item_id)]["attempt_count"] > 0 for item_id in selected)


def test_bounded_selector_uses_only_remaining_new_capacity():
    module = _load()
    ledger = _ledger(attempted=97, queued=50, retryable=0)
    selected = module.bounded_select_next_batch(ledger, limit=20)
    assert len(selected) == 3
    assert all(ledger["items"][str(item_id)]["attempt_count"] == 0 for item_id in selected)


def test_bounded_selector_keeps_retry_plus_new_bias_without_exceeding_capacity():
    module = _load()
    ledger = _ledger(attempted=99, queued=50, retryable=4)
    selected = module.bounded_select_next_batch(ledger, limit=20)
    new_ids = [
        item_id
        for item_id in selected
        if ledger["items"][str(item_id)]["attempt_count"] == 0
    ]
    retry_ids = [
        item_id
        for item_id in selected
        if ledger["items"][str(item_id)]["attempt_count"] > 0
    ]
    assert len(new_ids) == 1
    assert retry_ids


def test_configure_validator_rebinds_current_baseline_and_separate_campaign(tmp_path: Path):
    module = _load()
    fake = ModuleType("fake_p6_t03")
    fake.EXPECTED_BASELINE_SHA256 = "old"
    fake.EXPECTED_MIGRATION = 13
    fake.DEFAULT_LEDGER = Path("old.json")
    fake.resolve_canonical_db = lambda *a, **k: None
    fake.assert_canonical_baseline = lambda *a, **k: None
    fake._assert_ledger_baseline = lambda *a, **k: None
    fake.configure_paths = lambda *a, **k: None
    fake.preflight = lambda *a, **k: None
    fake.postvalidate = lambda *a, **k: None
    fake.recover = lambda *a, **k: None
    fake.report_only = lambda *a, **k: None
    fake.run_local = lambda *a, **k: None
    fake.select_next_batch = lambda *a, **k: ()
    fake.progress = lambda message: None
    report = tmp_path / "P6-T03_campaign_fixture.json"
    report.write_text("{}", encoding="utf-8")
    fake._write_campaign_report = lambda *a, **k: report

    configured = module.configure_validator(fake)
    assert configured.EXPECTED_BASELINE_SHA256 == ACCEPTED_CANONICAL_BASELINE.sha256
    assert configured.EXPECTED_MIGRATION == 14
    assert configured.DEFAULT_LEDGER == module.DEFAULT_CURRENT_CAMPAIGN
    assert configured.select_next_batch is module.bounded_select_next_batch
    renamed = configured._write_campaign_report()
    assert renamed.name == "P6-itemcache_campaign_fixture.json"
    assert renamed.is_file()


def test_configure_validator_fails_closed_on_reuse_interface_drift():
    module = _load()
    fake = ModuleType("broken")
    with pytest.raises(RuntimeError, match="reuse contract changed"):
        module.configure_validator(fake)


def test_configure_validator_can_replay_historical_p6_t05_baseline(tmp_path: Path):
    module = _load()
    fake = ModuleType("fake_p6_t03_historical")
    fake.EXPECTED_BASELINE_SHA256 = "old"
    fake.EXPECTED_MIGRATION = 13
    fake.DEFAULT_LEDGER = Path("old.json")
    fake.resolve_canonical_db = lambda *a, **k: None
    fake.assert_canonical_baseline = lambda *a, **k: None
    fake._assert_ledger_baseline = lambda *a, **k: None
    fake.configure_paths = lambda *a, **k: None
    fake.preflight = lambda *a, **k: None
    fake.postvalidate = lambda *a, **k: None
    fake.recover = lambda *a, **k: None
    fake.report_only = lambda *a, **k: None
    fake.run_local = lambda *a, **k: None
    fake.select_next_batch = lambda *a, **k: ()
    fake.progress = lambda message: None
    report = tmp_path / "P6-T03_campaign_fixture.json"
    report.write_text("{}", encoding="utf-8")
    fake._write_campaign_report = lambda *a, **k: report

    configured = module.configure_validator(
        fake,
        baseline=P6_T05_INPUT_BASELINE,
        default_campaign=module.DEFAULT_HISTORICAL_CAMPAIGN,
        marker_prefix="P6_T05_ACQUISITION",
        report_prefix="P6-T05_campaign_",
    )
    assert configured.EXPECTED_BASELINE_SHA256 == P6_T05_INPUT_BASELINE.sha256
    assert configured.DEFAULT_LEDGER == module.DEFAULT_HISTORICAL_CAMPAIGN
    assert configured._write_campaign_report().name == "P6-T05_campaign_fixture.json"


def test_parse_args_defaults_to_current_baseline_and_separate_current_campaign():
    module = _load()
    args = module.parse_args(["report"])
    assert args.baseline == "current"
    assert args.campaign == module.DEFAULT_CURRENT_CAMPAIGN
    assert args.batch_size == 10

    replay = module.parse_args(["report", "--baseline", "p6-t05-input"])
    assert replay.campaign == module.DEFAULT_HISTORICAL_CAMPAIGN


def test_campaign_metrics_report_refresh_unknown_retryable_and_capacity(tmp_path: Path):
    module = _load()
    ledger = create_campaign_ledger(
        canonical_sha256=ACCEPTED_CANONICAL_BASELINE.sha256,
        canonical_migration=ACCEPTED_CANONICAL_BASELINE.migration,
        canonical_item_count=5,
        coverage_revision="sha256:fixture",
        cache_pre_exists=False,
        cache_pre_sha256=None,
        initial_matching_cache_count=0,
        initial_cache_only_count=0,
        candidate_item_ids=range(1, 6),
        created_utc="20260830T000000Z",
    )
    for item_id in (1, 2):
        row = ledger["items"][str(item_id)]
        row.update(
            state="refresh_proven_direct_observation",
            attempt_count=1,
            session_count=1,
            freshness_class="refresh_proven_direct_observation",
            terminal=True,
            retryable=False,
        )
    retryable_row = ledger["items"]["3"]
    retryable_row.update(
        state=STATE_UNKNOWN_RETRYABLE,
        attempt_count=1,
        session_count=1,
        freshness_class="unknown",
        terminal=False,
        retryable=True,
    )
    ledger_path = tmp_path / "campaign.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    metrics = module.campaign_metrics(ledger_path)
    assert metrics == {
        "attempted_unique": 3,
        "refresh_proven": 2,
        "unknown": 3,
        "retryable": 1,
        "remaining_new_unique_capacity": 97,
    }
