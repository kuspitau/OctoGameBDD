"""Discover/request the three exact local pfQuest-family roots required by P5-T07."""

from __future__ import annotations

import argparse
import os
import re
import tomllib
from collections.abc import Callable
from pathlib import Path

EXPECTED_REVISIONS = {
    "pfquest": "sha256:5087d2d0a5b1c2706b7fc7ccb5ffd447c91aa24d91a23f102f2c7ac1d7440147",
    "pfquest_turtle": "sha256:7fd719cac7a7a26e80c6865fa62b6100ccfa2301dabe3b2a399c0f1551372d8c",
    "pfquest_octo": "sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db",
}
ADDON_NAMES = {
    "pfquest": "pfQuest",
    "pfquest_turtle": "pfQuest-turtle",
    "pfquest_octo": "pfQuest-octo",
}


def _read_source_paths(config_path: Path) -> dict[str, str]:
    if not config_path.is_file():
        return {}
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    section = payload.get("source_paths")
    if not isinstance(section, dict):
        return {}
    return {key: value for key, value in section.items() if isinstance(value, str)}


def _candidate_roots(
    key: str,
    *,
    configured: dict[str, str],
    accepted: dict[str, Path],
) -> list[Path]:
    candidates: list[Path] = []
    if key in configured:
        candidates.append(Path(configured[key]).expanduser())

    addon_name = ADDON_NAMES[key]
    for env_key in ("OCTOWOW_ROOT", "WOW_ROOT"):
        value = os.environ.get(env_key)
        if value:
            candidates.append(Path(value).expanduser() / "Interface" / "AddOns" / addon_name)

    for root in accepted.values():
        parent = root.parent
        candidates.append(parent / addon_name)

    # A checked-out addon tree beside the project is a harmless portable discovery case.
    project_root = Path(__file__).resolve().parents[1]
    candidates.append(project_root.parent / addon_name)
    candidates.append(project_root / addon_name)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve()) if candidate.exists() else str(candidate.absolute())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(candidate)
    return unique


def _measure_revision(key: str, root: Path) -> str:
    from octogamedb.importers.pfquest_overlay_reconcile import (
        compute_pfquest_overlay_revision,
        compute_pfquest_world_revision,
    )

    if key == "pfquest":
        return compute_pfquest_world_revision(root)
    return compute_pfquest_overlay_revision(root)


def _valid_exact_root(key: str, root: Path) -> tuple[bool, str]:
    if not root.is_dir():
        return False, "directory not found"
    try:
        revision = _measure_revision(key, root)
    except (OSError, ValueError) as exc:
        return False, str(exc)
    if revision != EXPECTED_REVISIONS[key]:
        return False, f"revision mismatch: measured {revision}"
    return True, revision


def _choose_root(
    key: str,
    *,
    configured: dict[str, str],
    accepted: dict[str, Path],
    interactive: bool,
    input_fn: Callable[[str], str] = input,
) -> Path:
    for candidate in _candidate_roots(key, configured=configured, accepted=accepted):
        valid, detail = _valid_exact_root(key, candidate)
        if valid:
            print(f"[PASS] {key}: {candidate.resolve()} ({detail})")
            return candidate.resolve()
        if candidate.exists():
            print(f"[INFO] rejected {key} candidate {candidate}: {detail}")

    if not interactive:
        raise RuntimeError(
            f"no exact P5-T07 {key} source root found; expected {EXPECTED_REVISIONS[key]}"
        )

    while True:
        raw = input_fn(f"Path to {ADDON_NAMES[key]} root (blank to abort): ").strip().strip('"')
        if not raw:
            raise RuntimeError(f"{key} path unresolved")
        candidate = Path(raw).expanduser()
        valid, detail = _valid_exact_root(key, candidate)
        if valid:
            print(f"[PASS] {key}: {candidate.resolve()} ({detail})")
            return candidate.resolve()
        print(f"[FAIL] {candidate}: {detail}")


def _toml_string(path: Path) -> str:
    value = path.resolve().as_posix().replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def _update_source_paths(config_path: Path, values: dict[str, Path]) -> None:
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    lines = text.splitlines()
    section_start: int | None = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[source_paths]":
            section_start = index
            continue
        if (
            section_start is not None
            and index > section_start
            and re.match(r"^\s*\[[^]]+\]\s*$", line)
        ):
            section_end = index
            break

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[source_paths]")
        section_start = len(lines) - 1
        section_end = len(lines)

    for key, path in values.items():
        pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=).*$")
        replacement = f"{key} = {_toml_string(path)}"
        replaced = False
        for index in range(section_start + 1, section_end):
            if pattern.match(lines[index]):
                lines[index] = replacement
                replaced = True
                break
        if not replaced:
            lines.insert(section_end, replacement)
            section_end += 1

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=project_root / "config.local.toml")
    parser.add_argument("--non-interactive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config_path = args.config.expanduser().resolve()
    configured = _read_source_paths(config_path)
    accepted: dict[str, Path] = {}
    for key in ("pfquest", "pfquest_turtle", "pfquest_octo"):
        accepted[key] = _choose_root(
            key,
            configured=configured,
            accepted=accepted,
            interactive=not args.non_interactive,
        )
    _update_source_paths(config_path, accepted)
    print(f"[PASS] Updated only [source_paths] P5-T07 keys in {config_path}")
    print("[PASS] All three roots reproduce the exact persisted source revisions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
