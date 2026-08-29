"""Resume-aware Windows entry point for the P6-T03 Level-2 validator.

This wrapper exists because the durable campaign ledger can legitimately outlive the CMD process.
If the previous CMD was closed after preflight, a later invocation must finish or resume
the recorded in-flight batch rather than trying to reserve a new one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_LEDGER = Path("data/generated/p6_t03_campaign.json")
VALIDATOR = Path("scripts/validate_p6_t03.py")


def load_active_request_ids(path: Path) -> tuple[int, ...]:
    """Return the exact durable in-flight ID order, or an empty tuple when none exists."""

    if not path.is_file():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("P6-T03 campaign ledger root must be an object")
    active = payload.get("active_session")
    if active is None:
        return ()
    if not isinstance(active, dict):
        raise TypeError("P6-T03 active_session must be an object or null")
    raw_ids = active.get("requested_item_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise TypeError("P6-T03 active_session requested_item_ids must be a non-empty list")
    item_ids = tuple(int(value) for value in raw_ids)
    if any(item_id <= 0 for item_id in item_ids) or len(item_ids) != len(set(item_ids)):
        raise ValueError("P6-T03 active_session requested IDs must be unique positive integers")
    return item_ids


def in_game_command(item_ids: tuple[int, ...]) -> str:
    if not item_ids:
        raise ValueError("cannot build an item-probe command without in-flight IDs")
    return "/ogitemprobe start " + ",".join(str(item_id) for item_id in item_ids)


def is_capture_not_ready(output: str) -> bool:
    """Recognize only failures for which rerunning the same client batch is appropriate."""

    markers = (
        "No SavedVariables capture matches the active campaign ID list",
        "matching SavedVariables capture is incomplete",
    )
    return any(marker in output for marker in markers)


def run_validator(mode: str, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(VALIDATOR), mode]
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
        print("[PASS] Resumed in-game command copied to the Windows clipboard.")


def _finish_completed_capture() -> int:
    first = run_validator("postvalidate", capture=True)
    if first.returncode != 0:
        combined = (first.stdout or "") + (first.stderr or "")
        if is_capture_not_ready(combined):
            return 2
        return first.returncode

    second = run_validator("postvalidate", capture=True)
    if second.returncode != 0:
        return second.returncode
    if "duplicate_noop=true" not in (second.stdout or ""):
        print("[FAIL] Replayed resumed session was not reported as duplicate_noop=true.")
        return 1
    print("[PASS] Resumed completed session replay is an evidence-preserving duplicate no-op.")
    print("P6_T03_RESUME_COMPLETE")
    return 0


def resume_or_run_fresh(ledger_path: Path = DEFAULT_LEDGER) -> int:
    configured = run_validator("configure-paths")
    if configured.returncode != 0:
        return configured.returncode

    active_ids = load_active_request_ids(ledger_path)
    if not active_ids:
        print("[INFO] No durable in-flight P6-T03 session; starting normal Level-2 workflow.")
        return run_validator("run-local").returncode

    print(
        "[INFO] Durable P6-T03 in-flight session detected; skipping new preflight and preserving "
        "the existing batch."
    )
    completed = _finish_completed_capture()
    if completed != 2:
        return completed

    command = in_game_command(active_ids)
    print("[INFO] No complete matching capture exists yet; resume the exact existing client batch.")
    print("IN_GAME_COMMAND=" + command)
    copy_to_clipboard(command)
    input("Press Enter only after the probe completes and WoW has been fully closed: ")

    completed = _finish_completed_capture()
    if completed == 2:
        print("[FAIL] Matching SavedVariables capture is still missing/incomplete after resume.")
        return 1
    return completed


def main() -> int:
    try:
        return resume_or_run_fresh()
    except (OSError, ValueError, TypeError) as exc:
        print(f"[FAIL] P6_T03_RESUME_FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
