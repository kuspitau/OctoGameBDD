from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - project requires Python 3.11+
    tomllib = None  # type: ignore[assignment]

from octogamedb.importers.quest_source_evidence import (
    TORTOISE_PINNED_REVISION,
    QuestSourceError,
    compare_source_snapshots,
    detect_git_revision,
    load_evidence_csv,
    load_tortoise_quest_projection,
    normalize_live_saved_variables,
    write_json,
)

REPRESENTATIVE_QUEST_IDS = (818, 815, 40788, 40675)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    if tomllib is None:
        raise RuntimeError("Python 3.11+ is required to read TOML configuration")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _source_path(config: dict[str, Any], key: str) -> Path | None:
    value = config.get("source_paths", {}).get(key)
    if not value:
        return None
    return Path(str(value)).expanduser()


def _validate_tortoise_repo(path: Path) -> bool:
    return (
        (path / "sql/base/tw_world_quest_template.sql").is_file()
        and (path / "sql/database_updates/world").is_dir()
    )


def _validate_wow_root(path: Path) -> bool:
    executable = (path / "WoW.exe").is_file() or (path / "Wow.exe").is_file()
    addons = (path / "Interface/AddOns").is_dir()
    return executable and addons


def _candidate_paths(key: str, project_root: Path) -> list[Path]:
    candidates: list[Path] = []
    home = Path.home()
    if key == "tortoise_repo":
        candidates.extend(
            [
                project_root.parent / "tortoise-wow",
                home / "Documents/GitHub/tortoise-wow",
                home / "source/repos/tortoise-wow",
            ]
        )
    elif key == "wow_root" and os.name == "nt":
        for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env_key)
            if base:
                candidates.append(Path(base) / "World of Warcraft")
        for drive in ("C:/", "D:/", "E:/"):
            games = Path(drive) / "Games"
            if games.is_dir():
                try:
                    candidates.extend(path for path in games.iterdir() if path.is_dir())
                except OSError:
                    pass
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        marker = str(candidate).casefold()
        if marker not in seen:
            seen.add(marker)
            unique.append(candidate)
    return unique


def _toml_quote(value: str) -> str:
    return '"' + value.replace("\\", "/").replace('"', '\\"') + '"'


def _update_source_paths(config_path: Path, updates: dict[str, Path]) -> None:
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    lines = text.splitlines(keepends=True)
    section_start = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[source_paths]":
            section_start = index
            for later in range(index + 1, len(lines)):
                if lines[later].lstrip().startswith("["):
                    section_end = later
                    break
            break
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append("[source_paths]\n")
        section_start = len(lines) - 1
        section_end = len(lines)

    for key, value in updates.items():
        replacement = f"{key} = {_toml_quote(str(value.resolve()))}\n"
        assignment = re.compile(rf"^\s*{re.escape(key)}\s*=")
        found = False
        for index in range(section_start + 1, section_end):
            if assignment.match(lines[index]):
                lines[index] = replacement
                found = True
                break
        if not found:
            lines.insert(section_end, replacement)
            section_end += 1
    config_path.write_text("".join(lines), encoding="utf-8")


def _resolve_path(
    *,
    key: str,
    existing: Path | None,
    validator,
    project_root: Path,
    prompt: str,
) -> Path | None:
    if existing and validator(existing):
        print(f"[reuse] {key} = {existing}")
        return existing.resolve()
    matches = [path.resolve() for path in _candidate_paths(key, project_root) if validator(path)]
    if len(matches) == 1:
        print(f"[discover] {key} = {matches[0]}")
        return matches[0]
    if len(matches) > 1:
        print(f"Multiple candidates found for {key}:")
        for index, path in enumerate(matches, start=1):
            print(f"  {index}. {path}")
    if not sys.stdin.isatty():
        print(f"[unresolved] {key}: interactive input unavailable", file=sys.stderr)
        return None
    raw = input(prompt).strip().strip('"')
    if not raw:
        return None
    selected = Path(raw).expanduser()
    if not validator(selected):
        print(f"[invalid] {key}: {selected}", file=sys.stderr)
        return None
    return selected.resolve()


def cmd_configure_paths(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    config_path = project_root / "config.local.toml"
    if not config_path.exists():
        example = project_root / "config.example.toml"
        if example.is_file():
            config_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            config_path.write_text("", encoding="utf-8")
    config = _load_config(config_path)
    tortoise = _resolve_path(
        key="tortoise_repo",
        existing=_source_path(config, "tortoise_repo"),
        validator=_validate_tortoise_repo,
        project_root=project_root,
        prompt="Path to the local Penqle/tortoise-wow checkout: ",
    )
    wow_root = _resolve_path(
        key="wow_root",
        existing=_source_path(config, "wow_root"),
        validator=_validate_wow_root,
        project_root=project_root,
        prompt="Path to the OctoWoW installation root: ",
    )
    unresolved = []
    updates: dict[str, Path] = {}
    if tortoise is None:
        unresolved.append("tortoise_repo")
    else:
        updates["tortoise_repo"] = tortoise
    if wow_root is None:
        unresolved.append("wow_root")
    else:
        updates["wow_root"] = wow_root
    if updates:
        _update_source_paths(config_path, updates)
    print("\nResolved source paths:")
    for key in ("tortoise_repo", "wow_root"):
        if key in updates:
            print(f"  {key} = {updates[key]}")
        else:
            print(f"  {key} = UNRESOLVED")
    if unresolved:
        print("Unresolved required keys: " + ", ".join(unresolved), file=sys.stderr)
        return 2
    return 0


def _quest_ids(values: list[int] | None) -> list[int]:
    return values or list(REPRESENTATIVE_QUEST_IDS)


def cmd_tortoise(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.config))
    repo = Path(args.tortoise_repo).expanduser() if args.tortoise_repo else _source_path(
        config, "tortoise_repo"
    )
    if repo is None:
        raise QuestSourceError(
            "Tortoise repository path unresolved; run get_path.bat or pass --tortoise-repo"
        )
    detected_revision = detect_git_revision(repo)
    if args.source_revision and detected_revision and args.source_revision != detected_revision:
        raise QuestSourceError(
            "--source-revision disagrees with the checkout HEAD: "
            f"declared {args.source_revision}, detected {detected_revision}"
        )
    revision = detected_revision or args.source_revision
    if revision is None:
        raise QuestSourceError(
            "cannot determine Tortoise Git revision; use a Git checkout or pass --source-revision"
        )
    if not args.allow_unpinned and revision != TORTOISE_PINNED_REVISION:
        raise QuestSourceError(
            "Tortoise checkout is not the pinned P3-T05B revision: "
            f"expected {TORTOISE_PINNED_REVISION}, got {revision}. "
            "Checkout the pinned revision or use --allow-unpinned for an explicitly identified audit."
        )
    projection = load_tortoise_quest_projection(
        repo,
        quest_ids=_quest_ids(args.quest_id),
        source_revision=revision,
        schema_sql=Path(args.schema_sql) if args.schema_sql else None,
    )
    write_json(Path(args.output), projection)
    print(f"wrote {args.output}")
    print(f"source_revision={projection['source_revision']}")
    print(f"content_hash={projection['content_hash']}")
    print(f"projection_hash={projection['projection_hash']}")
    print(f"quests={len(projection['quests'])}")
    if projection["missing_requested_quest_ids"]:
        print("missing_requested_quest_ids=" + ",".join(map(str, projection["missing_requested_quest_ids"])))
        return 3
    return 0


def _discover_saved_variables(wow_root: Path) -> list[Path]:
    account_root = wow_root / "WTF/Account"
    if not account_root.is_dir():
        return []
    return sorted(
        account_root.glob("*/SavedVariables/OctoGameBDD_QuestProbe.lua"),
        key=lambda path: str(path).casefold(),
    )


def cmd_install_probe(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.config))
    wow_root = _source_path(config, "wow_root")
    if wow_root is None or not _validate_wow_root(wow_root):
        raise QuestSourceError("wow_root unresolved/invalid; run get_path.bat first")
    source = Path(__file__).resolve().parent / "octogamedb_quest_probe"
    target = wow_root / "Interface/AddOns/OctoGameBDD_QuestProbe"
    if not source.is_dir():
        raise QuestSourceError(f"probe source directory missing: {source}")
    shutil.copytree(source, target, dirs_exist_ok=True)
    print(f"installed probe to {target}")
    print("Launch/restart WoW, then run: /oqpb 818 815 40788 40675")
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.config))
    saved_variables: Path | None = Path(args.saved_variables) if args.saved_variables else None
    if saved_variables is None:
        wow_root = _source_path(config, "wow_root")
        if wow_root is None:
            raise QuestSourceError(
                "SavedVariables path not supplied and wow_root is unresolved; run get_path.bat"
            )
        matches = _discover_saved_variables(wow_root)
        if len(matches) != 1:
            rendered = ", ".join(str(path) for path in matches) or "none"
            raise QuestSourceError(
                "expected exactly one QuestProbe SavedVariables file; "
                f"found {len(matches)} ({rendered}). Pass --saved-variables explicitly."
            )
        saved_variables = matches[0]
    projection = normalize_live_saved_variables(saved_variables)
    write_json(Path(args.output), projection)
    print(f"wrote {args.output}")
    print(f"raw_saved_variables_sha256={projection['raw_saved_variables_sha256']}")
    print(f"capture_hash={projection['capture_hash']}")
    print(f"records={projection['record_count']}")
    for quest_id, quest in projection["quests"].items():
        print(f"quest={quest_id} status={quest['status']} evidence={len(quest['evidence'])}")
    return 0


def cmd_snapshot_csv(args: argparse.Namespace) -> int:
    snapshot = load_evidence_csv(
        Path(args.input), source_key=args.source_key, source_revision=args.source_revision
    )
    write_json(Path(args.output), snapshot)
    print(f"wrote {args.output}")
    print(f"source_key={snapshot['source_key']}")
    print(f"source_revision={snapshot['source_revision']}")
    print(f"projection_hash={snapshot['projection_hash']}")
    print(f"quests={len(snapshot['quests'])}")
    return 0


def _parse_source_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--source requires SOURCE_KEY=path.json")
    key, raw_path = value.split("=", 1)
    if not key or not raw_path:
        raise argparse.ArgumentTypeError("--source requires SOURCE_KEY=path.json")
    return key, Path(raw_path)


def cmd_compare(args: argparse.Namespace) -> int:
    snapshots: list[dict[str, Any]] = []
    for expected_key, path in args.source:
        payload = json.loads(path.read_text(encoding="utf-8"))
        actual_key = payload.get("source_key")
        if actual_key != expected_key:
            raise QuestSourceError(
                f"source key mismatch for {path}: argument={expected_key}, payload={actual_key}"
            )
        snapshots.append(payload)
    comparison = compare_source_snapshots(snapshots)
    write_json(Path(args.output), comparison)
    print(f"wrote {args.output}")
    print(f"comparison_hash={comparison['comparison_hash']}")
    conflicts = 0
    ambiguous = 0
    facts = 0
    for quest in comparison["quests"].values():
        for fact in quest["facts"].values():
            facts += 1
            conflicts += int(bool(fact["conflict"]))
            ambiguous += int(fact["selection_status"] != "selected")
    print(f"quests={len(comparison['quests'])} facts={facts} conflicts={conflicts} ambiguous={ambiguous}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P3-T05B bounded quest-source validation bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser("configure-paths", help="resolve local P3-T05B source paths")
    configure.add_argument("--project-root", default=".")
    configure.set_defaults(func=cmd_configure_paths)

    tortoise = subparsers.add_parser("tortoise", help="project pinned Tortoise quest_template facts")
    tortoise.add_argument("--config", default="config.local.toml")
    tortoise.add_argument("--tortoise-repo")
    tortoise.add_argument("--source-revision")
    tortoise.add_argument("--allow-unpinned", action="store_true")
    tortoise.add_argument("--schema-sql")
    tortoise.add_argument("--quest-id", type=int, action="append")
    tortoise.add_argument("--output", required=True)
    tortoise.set_defaults(func=cmd_tortoise)

    install_probe = subparsers.add_parser(
        "install-probe", help="copy the bounded QuestProbe addon into the configured WoW root"
    )
    install_probe.add_argument("--config", default="config.local.toml")
    install_probe.set_defaults(func=cmd_install_probe)

    live = subparsers.add_parser("live", help="normalize QuestProbe SavedVariables")
    live.add_argument("--config", default="config.local.toml")
    live.add_argument("--saved-variables")
    live.add_argument("--output", required=True)
    live.set_defaults(func=cmd_live)

    snapshot_csv = subparsers.add_parser(
        "snapshot-csv", help="normalize reviewed OctoDB/CMaNGOS representative evidence CSV"
    )
    snapshot_csv.add_argument("--source-key", choices=("octodb", "cmangos-vanilla"), required=True)
    snapshot_csv.add_argument("--source-revision", required=True)
    snapshot_csv.add_argument("--input", required=True)
    snapshot_csv.add_argument("--output", required=True)
    snapshot_csv.set_defaults(func=cmd_snapshot_csv)

    compare = subparsers.add_parser("compare", help="reconcile normalized evidence snapshots")
    compare.add_argument("--source", type=_parse_source_arg, action="append", required=True)
    compare.add_argument("--output", required=True)
    compare.set_defaults(func=cmd_compare)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (OSError, json.JSONDecodeError, QuestSourceError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
