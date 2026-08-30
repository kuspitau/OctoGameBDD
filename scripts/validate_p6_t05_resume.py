"""Resume-aware Windows entry point for bounded migration-14 itemcache acquisition."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_CURRENT_CAMPAIGN = Path("data/generated/p6_itemcache_campaign.json")
DEFAULT_HISTORICAL_CAMPAIGN = Path("data/generated/p6_t05_campaign.json")
VALIDATOR = Path("scripts/validate_p6_t05_acquisition.py")


def default_campaign_for_mode(mode: str) -> Path:
    if mode == "current":
        return DEFAULT_CURRENT_CAMPAIGN
    if mode == "p6-t05-input":
        return DEFAULT_HISTORICAL_CAMPAIGN
    raise ValueError(f"unsupported baseline mode: {mode}")


def load_active_request_ids(path: Path) -> tuple[int, ...]:
    if not path.is_file():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("P6 itemcache campaign ledger root must be an object")
    active = payload.get("active_session")
    if active is None:
        return ()
    if not isinstance(active, dict):
        raise TypeError("P6 itemcache active_session must be an object or null")
    raw_ids = active.get("requested_item_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise TypeError("P6 itemcache active_session requested_item_ids must be a non-empty list")
    item_ids = tuple(int(value) for value in raw_ids)
    if any(item_id <= 0 for item_id in item_ids) or len(item_ids) != len(set(item_ids)):
        raise ValueError(
            "P6 itemcache active_session requested IDs must be unique positive integers"
        )
    return item_ids


def load_campaign_batch_limit(path: Path, default: int = 10) -> int:
    if not path.is_file():
        return default
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("P6 itemcache campaign ledger root must be an object")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise TypeError("P6 itemcache campaign policy must be an object")
    limit = int(policy.get("batch_limit", default))
    if not 1 <= limit <= 20:
        raise ValueError("P6 itemcache campaign batch_limit must be between 1 and 20")
    return limit


def in_game_command(item_ids: tuple[int, ...]) -> str:
    if not item_ids:
        raise ValueError("cannot build an item-probe command without in-flight IDs")
    return "/ogitemprobe start " + ",".join(str(item_id) for item_id in item_ids)


def is_capture_not_ready(output: str) -> bool:
    markers = (
        "No SavedVariables capture matches the active campaign ID list",
        "matching SavedVariables capture is incomplete",
    )
    return any(marker in output for marker in markers)


def run_validator(
    mode: str,
    *,
    baseline_mode: str,
    campaign_path: Path,
    capture: bool = False,
    batch_size: int | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(VALIDATOR),
        mode,
        "--baseline",
        baseline_mode,
        "--campaign",
        str(campaign_path),
    ]
    if batch_size is not None and mode != "configure-paths":
        command.extend(["--batch-size", str(batch_size)])
    if capture:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result
    return subprocess.run(command, text=True, check=False)


def copy_to_clipboard(command: str) -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(["clip"], input=command, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print("[INFO] Could not copy the resumed in-game command to the Windows clipboard.")
    else:
        print("[PASS] Resumed P6 itemcache in-game command copied to the Windows clipboard.")


def _finish_completed_capture(
    *, baseline_mode: str, campaign_path: Path, batch_size: int
) -> int:
    first = run_validator(
        "postvalidate",
        baseline_mode=baseline_mode,
        campaign_path=campaign_path,
        capture=True,
        batch_size=batch_size,
    )
    if first.returncode != 0:
        combined = (first.stdout or "") + (first.stderr or "")
        if is_capture_not_ready(combined):
            return 2
        return first.returncode

    second = run_validator(
        "postvalidate",
        baseline_mode=baseline_mode,
        campaign_path=campaign_path,
        capture=True,
        batch_size=batch_size,
    )
    if second.returncode != 0:
        return second.returncode
    if "duplicate_noop=true" not in (second.stdout or ""):
        print("[FAIL] Replayed resumed P6 itemcache session was not duplicate_noop=true.")
        return 1
    print("[PASS] Resumed P6 itemcache completed-session replay is an evidence-preserving no-op.")
    print("P6_ITEMCACHE_ACQUISITION_RESUME_COMPLETE")
    return 0


def resume_or_run_fresh(
    *, baseline_mode: str = "current", campaign_path: Path | None = None
) -> int:
    campaign = campaign_path or default_campaign_for_mode(baseline_mode)
    configured = run_validator(
        "configure-paths", baseline_mode=baseline_mode, campaign_path=campaign
    )
    if configured.returncode != 0:
        return configured.returncode

    batch_size = load_campaign_batch_limit(campaign)
    active_ids = load_active_request_ids(campaign)
    if not active_ids:
        print("[INFO] No durable in-flight P6 itemcache session; starting normal bounded workflow.")
        return run_validator(
            "run-local",
            baseline_mode=baseline_mode,
            campaign_path=campaign,
            batch_size=batch_size,
        ).returncode

    print("[INFO] Durable P6 itemcache in-flight session detected; preserving the exact batch.")
    completed = _finish_completed_capture(
        baseline_mode=baseline_mode,
        campaign_path=campaign,
        batch_size=batch_size,
    )
    if completed != 2:
        return completed

    command = in_game_command(active_ids)
    print("[INFO] No complete matching capture exists yet; resume the exact existing client batch.")
    print("IN_GAME_COMMAND=" + command)
    copy_to_clipboard(command)
    input("Press Enter only after the probe completes and WoW has been fully closed: ")

    completed = _finish_completed_capture(
        baseline_mode=baseline_mode,
        campaign_path=campaign,
        batch_size=batch_size,
    )
    if completed == 2:
        print("[FAIL] Matching SavedVariables capture is still missing/incomplete after resume.")
        return 1
    return completed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline", choices=("current", "p6-t05-input"), default="current"
    )
    parser.add_argument("--campaign", type=Path)
    args = parser.parse_args(argv)
    if args.campaign is None:
        args.campaign = default_campaign_for_mode(args.baseline)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return resume_or_run_fresh(
            baseline_mode=args.baseline,
            campaign_path=args.campaign,
        )
    except (OSError, ValueError, TypeError) as exc:
        print(f"[FAIL] P6_ITEMCACHE_ACQUISITION_RESUME_FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
