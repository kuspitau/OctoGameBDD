"""Bounded migration-14 real-client item acquisition using the validated P6-T03 engine.

The default mode targets the current accepted canonical baseline. Historical P6-T05 acquisition can
be replayed explicitly with ``--baseline p6-t05-input`` without changing the old P6-T03 validator.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

from octogamedb.canonical_baseline import (
    ACCEPTED_CANONICAL_BASELINE,
    P6_T05_INPUT_BASELINE,
    CanonicalBaseline,
    assert_canonical_baseline as assert_shared_canonical_baseline,
    resolve_canonical_db as resolve_shared_canonical_db,
)
from octogamedb.itemcache_campaign import (
    DEFAULT_BATCH_LIMIT,
    DEFAULT_MAX_CAMPAIGN_ATTEMPTS,
    MAX_BATCH_LIMIT,
    STATE_QUEUED,
    STATE_UNKNOWN_RETRYABLE,
    load_ledger,
)

LEGACY_VALIDATOR = Path("scripts/validate_p6_t03.py")
DEFAULT_CURRENT_CAMPAIGN = Path("data/generated/p6_itemcache_campaign.json")
DEFAULT_HISTORICAL_CAMPAIGN = Path("data/generated/p6_t05_campaign.json")
DEFAULT_CAMPAIGN = DEFAULT_CURRENT_CAMPAIGN
DEFAULT_REPORT_DIR = Path("data/generated/validation_logs")
DEFAULT_CONFIG = Path("config.local.toml")
MAX_NEW_ATTEMPTED_UNIQUE = 100


def _spread_select(values: Sequence[int], limit: int) -> list[int]:
    ordered = sorted({int(value) for value in values})
    if limit <= 0 or not ordered:
        return []
    if len(ordered) <= limit:
        return ordered
    if limit == 1:
        return [ordered[len(ordered) // 2]]
    indexes = [round(index * (len(ordered) - 1) / (limit - 1)) for index in range(limit)]
    return [ordered[index] for index in indexes]


def attempted_unique_count(ledger: Mapping[str, Any]) -> int:
    items = ledger.get("items")
    if not isinstance(items, Mapping):
        raise TypeError("campaign ledger items must be an object")
    total = 0
    for raw in items.values():
        if not isinstance(raw, Mapping):
            raise TypeError("campaign item must be an object")
        if int(raw.get("attempt_count", 0)) > 0:
            total += 1
    return total


def bounded_select_next_batch(
    ledger: Mapping[str, Any], *, limit: int | None = None
) -> tuple[int, ...]:
    """Preserve P6-T03 retry semantics while enforcing P6-T05's 100-new-ID hard ceiling."""

    if ledger.get("active_session") is not None:
        raise RuntimeError("campaign has an active in-flight session; merge or recover it first")
    policy = ledger.get("policy")
    items = ledger.get("items")
    candidate_ids = ledger.get("candidate_item_ids")
    if not isinstance(policy, Mapping) or not isinstance(items, Mapping):
        raise TypeError("campaign ledger policy/items shape is invalid")
    if not isinstance(candidate_ids, list):
        raise TypeError("campaign candidate_item_ids must be a list")

    policy_limit = int(policy.get("batch_limit", DEFAULT_BATCH_LIMIT))
    batch_limit = policy_limit if limit is None else int(limit)
    if not 1 <= batch_limit <= min(policy_limit, MAX_BATCH_LIMIT):
        raise ValueError("batch selection limit exceeds the campaign policy")

    attempted = attempted_unique_count(ledger)
    if attempted > MAX_NEW_ATTEMPTED_UNIQUE:
        raise RuntimeError(
            f"P6-T05 campaign already exceeds the {MAX_NEW_ATTEMPTED_UNIQUE}-ID unique-attempt cap"
        )
    remaining_new = MAX_NEW_ATTEMPTED_UNIQUE - attempted

    queued: list[int] = []
    retryable: list[int] = []
    for value in candidate_ids:
        item_id = int(value)
        row = items.get(str(item_id))
        if not isinstance(row, Mapping):
            raise TypeError(f"campaign item {item_id} must be an object")
        state = str(row.get("state", ""))
        attempts = int(row.get("attempt_count", 0))
        if state == STATE_QUEUED:
            if attempts != 0:
                raise ValueError(f"queued campaign item {item_id} unexpectedly has prior attempts")
            queued.append(item_id)
        elif state == STATE_UNKNOWN_RETRYABLE:
            if attempts <= 0:
                raise ValueError(f"retryable campaign item {item_id} lacks a prior attempt")
            retryable.append(item_id)

    selected: list[int] = []
    # Keep the validated P6-T03 bias toward one retry when both populations exist, then use
    # remaining capacity for new canonical IDs. If the 100-ID ceiling is reached, retries remain
    # legal.
    if retryable and queued and batch_limit >= 2:
        selected.extend(_spread_select(retryable, 1))
        queued_slots = min(batch_limit - len(selected), remaining_new)
        selected.extend(_spread_select(queued, queued_slots))
        if len(selected) < batch_limit:
            remaining_retries = [item_id for item_id in retryable if item_id not in selected]
            selected.extend(_spread_select(remaining_retries, batch_limit - len(selected)))
        return tuple(selected)

    if queued and remaining_new > 0:
        return tuple(_spread_select(queued, min(batch_limit, remaining_new)))
    if retryable:
        return tuple(_spread_select(retryable, batch_limit))
    return ()


def campaign_metrics(path: Path) -> dict[str, int]:
    ledger = load_ledger(path.resolve())
    items = ledger.get("items")
    if not isinstance(items, Mapping):
        raise TypeError("campaign ledger items must be an object")
    attempted = attempted_unique_count(ledger)
    refresh_proven = 0
    unknown = 0
    retryable = 0
    for raw in items.values():
        if not isinstance(raw, Mapping):
            raise TypeError("campaign item must be an object")
        freshness = str(raw.get("freshness_class", ""))
        state = str(raw.get("state", ""))
        if freshness == "refresh_proven_direct_observation":
            refresh_proven += 1
        if freshness == "unknown":
            unknown += 1
        if state == STATE_UNKNOWN_RETRYABLE:
            retryable += 1
    return {
        "attempted_unique": attempted,
        "refresh_proven": refresh_proven,
        "unknown": unknown,
        "retryable": retryable,
        "remaining_new_unique_capacity": MAX_NEW_ATTEMPTED_UNIQUE - attempted,
    }


def emit_campaign_metrics(module: ModuleType, path: Path) -> dict[str, int]:
    metrics = campaign_metrics(path)
    marker_prefix = getattr(module, "P6_ITEMCACHE_MARKER_PREFIX", "P6_ITEMCACHE_ACQUISITION")
    module.progress(
        marker_prefix
        + "_METRICS "
        + " ".join(f"{key}={value}" for key, value in metrics.items())
    )
    return metrics


def _load_legacy_validator() -> ModuleType:
    script = LEGACY_VALIDATOR.resolve()
    if not script.is_file():
        raise FileNotFoundError(f"Validated P6-T03 acquisition validator not found: {script}")
    spec = importlib.util.spec_from_file_location("p6_t05_reused_p6_t03_validator", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load acquisition validator: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def baseline_for_mode(mode: str) -> CanonicalBaseline:
    if mode == "current":
        return ACCEPTED_CANONICAL_BASELINE
    if mode == "p6-t05-input":
        return P6_T05_INPUT_BASELINE
    raise ValueError(f"unsupported baseline mode: {mode}")


def default_campaign_for_mode(mode: str) -> Path:
    return (
        DEFAULT_CURRENT_CAMPAIGN
        if mode == "current"
        else DEFAULT_HISTORICAL_CAMPAIGN
    )


def configure_validator(
    module: ModuleType,
    *,
    baseline: CanonicalBaseline = ACCEPTED_CANONICAL_BASELINE,
    default_campaign: Path = DEFAULT_CURRENT_CAMPAIGN,
    marker_prefix: str = "P6_ITEMCACHE_ACQUISITION",
    report_prefix: str = "P6-itemcache_campaign_",
) -> ModuleType:
    """Reuse the validated P6-T03 engine against an explicit fail-closed migration-14 baseline."""

    required = (
        "EXPECTED_BASELINE_SHA256",
        "EXPECTED_MIGRATION",
        "DEFAULT_LEDGER",
        "resolve_canonical_db",
        "assert_canonical_baseline",
        "_assert_ledger_baseline",
        "configure_paths",
        "preflight",
        "postvalidate",
        "recover",
        "report_only",
        "run_local",
        "select_next_batch",
        "_write_campaign_report",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            "P6-T03 validator reuse contract changed; review before P6 acquisition: "
            + ", ".join(missing)
        )

    module.P6_ITEMCACHE_MARKER_PREFIX = marker_prefix
    module.EXPECTED_BASELINE_SHA256 = baseline.sha256
    module.EXPECTED_MIGRATION = baseline.migration
    module.DEFAULT_LEDGER = default_campaign
    module.select_next_batch = bounded_select_next_batch

    def current_resolve_canonical_db(explicit: Path | None) -> Path:
        return resolve_shared_canonical_db(explicit, baseline=baseline)

    def current_assert_canonical_baseline(path: Path) -> str:
        return assert_shared_canonical_baseline(path, baseline=baseline)

    def current_assert_ledger_baseline(ledger: Mapping[str, Any], canonical_hash: str) -> None:
        canonical = ledger.get("canonical")
        if not isinstance(canonical, Mapping):
            raise RuntimeError("campaign ledger lacks canonical baseline metadata")
        if str(canonical.get("sha256", "")) != canonical_hash:
            raise RuntimeError(
                f"campaign ledger canonical SHA does not match {baseline.label}"
            )
        if int(canonical.get("migration", -1)) != baseline.migration:
            raise RuntimeError(
                "campaign ledger migration does not match "
                f"{baseline.label}: expected {baseline.migration}"
            )

    module.resolve_canonical_db = current_resolve_canonical_db
    module.assert_canonical_baseline = current_assert_canonical_baseline
    module._assert_ledger_baseline = current_assert_ledger_baseline

    original_progress = module.progress

    def p6_progress(message: str) -> None:
        translated = str(message).replace("P6_T03", marker_prefix).replace(
            "P6-T03", "P6 itemcache acquisition"
        )
        original_progress(translated)

    module.progress = p6_progress

    original_report_writer = module._write_campaign_report

    def p6_report_writer(*args: Any, **kwargs: Any) -> Path:
        historical_name = Path(original_report_writer(*args, **kwargs))
        target = historical_name.with_name(
            historical_name.name.replace("P6-T03_campaign_", report_prefix, 1)
        )
        if target != historical_name:
            historical_name.replace(target)
        return target

    module._write_campaign_report = p6_report_writer
    return module


def _module_args(args: argparse.Namespace) -> argparse.Namespace:
    # The reused implementation accesses exactly these attributes.  Keep this explicit so a future
    # validator interface drift fails visibly instead of inheriting unrelated argparse state.
    return argparse.Namespace(
        db=args.db,
        config=args.config,
        wow_root=args.wow_root,
        itemcache=args.itemcache,
        locale=args.locale,
        ledger=args.campaign,
        report_dir=args.report_dir,
        batch_size=args.batch_size,
        max_campaign_attempts=args.max_campaign_attempts,
        non_interactive=args.non_interactive,
    )


def run_local(module: ModuleType, args: argparse.Namespace) -> None:
    module_args = _module_args(args)
    module_args.report_dir.resolve().mkdir(parents=True, exist_ok=True)
    log_path = (
        module_args.report_dir.resolve()
        / f"{args.report_slug}_acquisition_level2_{module.timestamp()}.log"
    )
    with log_path.open("w", encoding="utf-8", newline="\n") as handle:
        module._LOG_HANDLE = handle
        try:
            module.progress(f"[INFO] Streaming P6 itemcache acquisition log to {log_path}")
            module.configure_paths(module_args.config, interactive=not module_args.non_interactive)
            module.preflight(module_args, configure_if_missing=False)
            module.progress("[INFO] Complete the in-game step shown above.")
            input("Press Enter only after WoW has been fully closed: ")
            first = module.postvalidate(module_args, require_complete=True)
            if first["duplicate"]:
                raise RuntimeError("first completed-session merge was unexpectedly a duplicate")
            module.progress(
                "[INFO] Re-importing the same completed session to prove no-op idempotence."
            )
            second = module.postvalidate(module_args, require_complete=True)
            if not second["duplicate"]:
                raise RuntimeError("repeated completed-session merge was not detected as a no-op")
            module.progress(
                "[PASS] Repeated session import is an evidence-preserving duplicate no-op."
            )
            ledger = load_ledger(module_args.ledger.resolve())
            emit_campaign_metrics(module, module_args.ledger)
            next_batch = bounded_select_next_batch(ledger, limit=module_args.batch_size)
            if next_batch:
                module.progress(
                    "[PASS] next_batch_preview=" + ",".join(str(item_id) for item_id in next_batch)
                )
            else:
                module.progress("[INFO] Campaign currently has no further eligible bounded batch.")
            module.progress(
                module.P6_ITEMCACHE_MARKER_PREFIX + "_REMAINING_LOCAL_VALIDATION_COMPLETE"
            )
        finally:
            module._LOG_HANDLE = None
    print(f"[PASS] Full P6 itemcache acquisition Level-2 log: {log_path}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=("configure-paths", "preflight", "postvalidate", "recover", "report", "run-local"),
    )
    parser.add_argument("--db", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--wow-root", type=Path)
    parser.add_argument("--itemcache", type=Path)
    parser.add_argument("--locale", default="enUS")
    parser.add_argument(
        "--baseline", choices=("current", "p6-t05-input"), default="current"
    )
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_LIMIT)
    parser.add_argument(
        "--max-campaign-attempts", type=int, default=DEFAULT_MAX_CAMPAIGN_ATTEMPTS
    )
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args(argv)
    if args.campaign is None:
        args.campaign = default_campaign_for_mode(args.baseline)
    args.report_slug = "P6-itemcache" if args.baseline == "current" else "P6-T05"
    if not 1 <= args.batch_size <= MAX_BATCH_LIMIT:
        parser.error(f"--batch-size must be between 1 and {MAX_BATCH_LIMIT}")
    if args.max_campaign_attempts < 1:
        parser.error("--max-campaign-attempts must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        baseline = baseline_for_mode(args.baseline)
        historical = args.baseline == "p6-t05-input"
        module = configure_validator(
            _load_legacy_validator(),
            baseline=baseline,
            default_campaign=args.campaign,
            marker_prefix=(
                "P6_T05_ACQUISITION" if historical else "P6_ITEMCACHE_ACQUISITION"
            ),
            report_prefix=("P6-T05_campaign_" if historical else "P6-itemcache_campaign_"),
        )
        module_args = _module_args(args)
        if args.mode == "configure-paths":
            module.configure_paths(args.config, interactive=not args.non_interactive)
            module.progress(
                "P6_T05_ACQUISITION_PATHS_OK"
                if historical
                else "P6_ITEMCACHE_ACQUISITION_PATHS_OK"
            )
        elif args.mode == "preflight":
            module.preflight(module_args)
        elif args.mode == "postvalidate":
            module.postvalidate(module_args)
            emit_campaign_metrics(module, args.campaign)
        elif args.mode == "recover":
            module.recover(module_args)
        elif args.mode == "report":
            module.report_only(module_args)
            emit_campaign_metrics(module, args.campaign)
        else:
            run_local(module, args)
    except Exception as exc:
        print(f"[FAIL] P6_ITEMCACHE_ACQUISITION_FAILED: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
