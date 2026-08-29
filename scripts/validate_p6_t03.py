"""P6-T03 resumable direct-Octo item acquisition campaign and Level-2 validator."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from octogamedb.importers.octo_itemcache import parse_itemcache_wdb
from octogamedb.itemcache_campaign import (
    DEFAULT_BATCH_LIMIT,
    DEFAULT_MAX_CAMPAIGN_ATTEMPTS,
    MAX_BATCH_LIMIT,
    atomic_write_ledger,
    begin_session,
    campaign_report,
    clone_ledger,
    create_campaign_ledger,
    load_ledger,
    merge_active_session,
    reconcile_pre_session_cache_presence,
    recover_active_session_without_export,
    select_next_batch,
)
from octogamedb.itemcache_coverage import (
    build_absent_itemcache_coverage_report,
    build_itemcache_coverage_report,
    itemcache_record_hashes,
    write_json_report,
)

EXPECTED_BASELINE_SHA256 = "623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
EXPECTED_MIGRATION = 13
DEFAULT_CONFIG = Path("config.local.toml")
DEFAULT_LEDGER = Path("data/generated/p6_t03_campaign.json")
DEFAULT_REPORT_DIR = Path("data/generated/validation_logs")
ADDON_SOURCE = Path("scripts/octogamedb_item_probe")
ADDON_NAME = "OctoGameBDD_ItemProbe"
EXPORT_RE = re.compile(r'^OctoGameBDD_ItemProbeExport\s*=\s*"([^"]*)"', re.MULTILINE)
_LOG_HANDLE: TextIO | None = None


def progress(message: str) -> None:
    print(message, flush=True)
    if _LOG_HANDLE is not None:
        print(message, file=_LOG_HANDLE, flush=True)


def timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_wow_root(config_path: Path) -> Path | None:
    if not config_path.is_file():
        return None
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    raw = payload.get("source_paths", {}).get("wow_root")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser()


def validate_wow_root(path: Path) -> tuple[bool, str]:
    root = path.expanduser()
    if not root.is_dir():
        return False, "directory not found"
    executable = next(
        (candidate for candidate in (root / "WoW.exe", root / "Wow.exe") if candidate.is_file()),
        None,
    )
    if executable is None:
        return False, "WoW.exe/Wow.exe not found"
    if not (root / "Interface" / "AddOns").is_dir():
        return False, "Interface/AddOns not found"
    return True, f"validated by {executable.name} + Interface/AddOns"


def _toml_string(path: Path) -> str:
    value = path.resolve().as_posix().replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def update_wow_root_config(config_path: Path, wow_root: Path) -> None:
    """Update only [source_paths].wow_root while preserving unrelated local configuration."""

    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    lines = text.splitlines()
    section_start: int | None = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[source_paths]":
            section_start = index
            continue
        if section_start is not None and index > section_start and re.match(
            r"^\s*\[[^]]+\]\s*$", line
        ):
            section_end = index
            break

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[source_paths]")
        section_start = len(lines) - 1
        section_end = len(lines)

    pattern = re.compile(r"^(\s*wow_root\s*=).*$")
    replacement = f"wow_root = {_toml_string(wow_root)}"
    for index in range(section_start + 1, section_end):
        if pattern.match(lines[index]):
            lines[index] = replacement
            break
    else:
        lines.insert(section_end, replacement)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def wow_root_candidates(config_path: Path) -> list[Path]:
    candidates: list[Path] = []
    configured = read_wow_root(config_path)
    if configured is not None:
        candidates.append(configured)
    for key in ("OCTOWOW_ROOT", "WOW_ROOT"):
        value = os.environ.get(key)
        if value:
            candidates.append(Path(value).expanduser())
    if os.name == "nt":
        candidates.extend(
            [
                Path("C:/Games/OctoWow"),
                Path("C:/Games/OctoWoW"),
                Path("C:/Program Files/World of Warcraft"),
                Path("C:/Program Files (x86)/World of Warcraft"),
            ]
        )

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate.absolute())
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def configure_paths(config_path: Path, *, interactive: bool) -> Path:
    valid: list[Path] = []
    for candidate in wow_root_candidates(config_path):
        okay, detail = validate_wow_root(candidate)
        if okay:
            resolved = candidate.resolve()
            if resolved not in valid:
                valid.append(resolved)
            progress(f"[PASS] wow_root candidate: {resolved} ({detail})")
        elif candidate.exists():
            progress(f"[INFO] rejected wow_root candidate {candidate}: {detail}")

    configured = read_wow_root(config_path)
    if configured is not None:
        okay, _ = validate_wow_root(configured)
        if okay:
            chosen = configured.resolve()
            update_wow_root_config(config_path, chosen)
            progress(f"[PASS] Reused configured [source_paths].wow_root: {chosen}")
            return chosen

    if len(valid) == 1:
        chosen = valid[0]
    elif not interactive:
        if not valid:
            raise RuntimeError("no valid OctoWoW root discovered")
        raise RuntimeError(f"multiple valid OctoWoW roots discovered: {valid}")
    else:
        if len(valid) > 1:
            progress("[INFO] Multiple valid roots discovered; an explicit choice is required.")
        while True:
            raw = input("Path to OctoWoW root (blank to abort): ").strip().strip('"')
            if not raw:
                raise RuntimeError("wow_root path unresolved")
            chosen = Path(raw).expanduser()
            okay, detail = validate_wow_root(chosen)
            if okay:
                chosen = chosen.resolve()
                break
            progress(f"[FAIL] {chosen}: {detail}")

    update_wow_root_config(config_path, chosen)
    progress(f"[PASS] Updated only [source_paths].wow_root in {config_path.resolve()}")
    return chosen


def resolve_wow_root(args: argparse.Namespace, *, configure_if_missing: bool) -> Path:
    if args.wow_root is not None:
        root = args.wow_root.expanduser().resolve()
    else:
        configured = read_wow_root(args.config)
        if configured is None and configure_if_missing:
            configured = configure_paths(args.config, interactive=True)
        if configured is None:
            raise RuntimeError(
                "wow_root is required; run get_path.bat / configure-paths or pass --wow-root"
            )
        root = configured.expanduser().resolve()
    okay, detail = validate_wow_root(root)
    if not okay:
        raise RuntimeError(f"invalid wow_root {root}: {detail}")
    return root


def running_task_images(tasklist_output: str) -> set[str]:
    images: set[str] = set()
    for row in csv.reader(tasklist_output.splitlines()):
        if row and row[0].strip():
            images.add(row[0].strip().casefold())
    return images


def assert_wow_closed() -> None:
    if os.name != "nt":
        return
    result = subprocess.run(
        ["tasklist", "/NH", "/FO", "CSV"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    running = running_task_images(result.stdout)
    if {"wow.exe", "world of warcraft.exe"} & running:
        raise RuntimeError("WoW must be fully closed before campaign preflight/post-processing")
    progress("[PASS] WoW process is closed.")


def resolve_canonical_db(explicit: Path | None) -> Path:
    candidates = [explicit] if explicit is not None else [
        Path("data/generated/octogamedb.sqlite3"),
        Path("data/octogamedb.sqlite3"),
    ]
    existing = [
        candidate.resolve() for candidate in candidates if candidate and candidate.is_file()
    ]
    if not existing:
        raise FileNotFoundError(
            "Canonical DB not found at data/generated/octogamedb.sqlite3; pass --db if needed."
        )
    exact = [path for path in existing if sha256_file(path) == EXPECTED_BASELINE_SHA256]
    if len(exact) != 1:
        details = ", ".join(f"{path}={sha256_file(path)}" for path in existing)
        raise RuntimeError(
            "Expected exactly one migration-13 canonical baseline matching the documented SHA-256; "
            + details
        )
    return exact[0]


def assert_canonical_baseline(path: Path) -> str:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            raise RuntimeError(f"Canonical DB has forbidden SQLite sidecar: {sidecar}")
    digest = sha256_file(path)
    if digest != EXPECTED_BASELINE_SHA256:
        raise RuntimeError(
            f"Canonical DB hash drift: expected={EXPECTED_BASELINE_SHA256} actual={digest}"
        )
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        migration = int(
            connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
            ).fetchone()[0]
        )
    if migration != EXPECTED_MIGRATION:
        raise RuntimeError(f"Expected canonical migration {EXPECTED_MIGRATION}, found {migration}")
    return digest


def expected_itemcache_path(wow_root: Path, locale: str | None) -> Path:
    return (wow_root / "WDB" / (locale or "enUS") / "itemcache.wdb").resolve()


def find_itemcache_optional(wow_root: Path, locale: str | None) -> Path | None:
    roots = (wow_root / "WDB", wow_root / "Cache" / "WDB")
    candidates: list[Path] = []
    for root in roots:
        candidates.append(root / "itemcache.wdb")
        if locale:
            candidates.append(root / locale / "itemcache.wdb")
        if root.is_dir():
            candidates.extend(sorted(root.glob("*/itemcache.wdb")))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.is_file():
            resolved = candidate.resolve()
            if str(resolved) not in seen:
                seen.add(str(resolved))
                unique.append(resolved)
    if not unique:
        return None
    if locale:
        exact = [path for path in unique if path.parent.name.casefold() == locale.casefold()]
        if len(exact) == 1:
            return exact[0]
        matching_headers: list[Path] = []
        for path in unique:
            try:
                if parse_itemcache_wdb(path).header.locale.casefold() == locale.casefold():
                    matching_headers.append(path)
            except (OSError, ValueError):
                continue
        if len(matching_headers) == 1:
            return matching_headers[0]
        if len(exact) > 1 or len(matching_headers) > 1:
            raise RuntimeError(f"ambiguous {locale} itemcache.wdb candidates")
    if len(unique) != 1:
        raise RuntimeError("multiple itemcache.wdb candidates; use --locale or --itemcache")
    return unique[0]


def resolve_itemcache(args: argparse.Namespace, wow_root: Path) -> Path | None:
    if args.itemcache is not None:
        path = args.itemcache.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    return find_itemcache_optional(wow_root, args.locale)


def coverage_report(
    canonical: Path, cache_path: Path | None, expected_cache: Path
) -> dict[str, Any]:
    with sqlite3.connect(f"file:{canonical.as_posix()}?mode=ro", uri=True) as connection:
        if cache_path is None:
            return build_absent_itemcache_coverage_report(
                connection, expected_source_path=expected_cache
            )
        return build_itemcache_coverage_report(connection, source_path=cache_path)


def current_record_hashes(cache_path: Path | None) -> dict[int, str]:
    if cache_path is None:
        return {}
    return itemcache_record_hashes(parse_itemcache_wdb(cache_path))


def stage_addon(wow_root: Path) -> Path:
    source = ADDON_SOURCE.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Probe addon source not found: {source}")
    addon_dir = wow_root / "Interface" / "AddOns" / ADDON_NAME
    addon_dir.mkdir(parents=True, exist_ok=True)
    for name in ("OctoGameBDD_ItemProbe.toc", "OctoGameBDD_ItemProbe.lua"):
        shutil.copy2(source / name, addon_dir / name)
    return addon_dir


def parse_export_string(value: str) -> dict[str, Any]:
    fields: dict[str, str] = {}
    for part in value.split("|"):
        if "=" in part:
            key, raw = part.split("=", 1)
            fields[key] = raw
    if fields.get("v") != "1":
        raise ValueError(f"Unsupported probe export version: {fields.get('v')!r}")
    ids = [int(value) for value in fields.get("ids", "").split(",") if value]
    if len(ids) != len(set(ids)):
        raise ValueError("probe export contains duplicate IDs")
    results: dict[int, dict[str, str]] = {}
    if fields.get("results"):
        for entry in fields["results"].split(","):
            bits = entry.split(":")
            if len(bits) != 3:
                raise ValueError(f"Malformed probe result entry: {entry!r}")
            item_id = int(bits[0])
            if item_id in results:
                raise ValueError(f"duplicate probe result entry for {item_id}")
            results[item_id] = {"initial": bits[1], "status": bits[2]}
    return {
        "probe_id": fields.get("probe_id"),
        "started": fields.get("started"),
        "realm": fields.get("realm"),
        "character": fields.get("character"),
        "locale": fields.get("locale"),
        "client_version": fields.get("client_version"),
        "client_build": fields.get("client_build"),
        "ids": ids,
        "results": results,
        "complete": fields.get("complete") == "1",
    }


def read_saved_variables_export(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = EXPORT_RE.search(text)
    if match is None:
        raise ValueError(f"No OctoGameBDD_ItemProbeExport string in {path}")
    return parse_export_string(match.group(1))


def find_matching_saved_variables(
    wow_root: Path, requested_ids: list[int]
) -> tuple[Path, dict[str, Any]]:
    pattern = "WTF/Account/**/SavedVariables/OctoGameBDD_ItemProbe.lua"
    candidates = sorted(wow_root.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    errors: list[str] = []
    for path in candidates:
        try:
            export = read_saved_variables_export(path)
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        if export["ids"] == requested_ids:
            return path, export
    suffix = f" Parse diagnostics: {'; '.join(errors)}" if errors else ""
    raise FileNotFoundError(
        "No SavedVariables capture matches the active campaign ID list." + suffix
    )


def copy_command_to_clipboard(command: str) -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(["clip"], input=command, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        progress("[INFO] Could not copy the in-game command to the Windows clipboard.")
    else:
        progress("[PASS] In-game command copied to the Windows clipboard.")


def _cache_identity(cache_path: Path | None) -> tuple[bool, str | None]:
    return (cache_path is not None, None if cache_path is None else sha256_file(cache_path))


def _assert_ledger_baseline(ledger: dict[str, Any], canonical_hash: str) -> None:
    if ledger["canonical"]["sha256"] != canonical_hash:
        raise RuntimeError(
            "campaign ledger canonical SHA does not match the current validated baseline"
        )
    if int(ledger["canonical"]["migration"]) != EXPECTED_MIGRATION:
        raise RuntimeError("campaign ledger migration baseline is not migration 13")


def preflight(args: argparse.Namespace, *, configure_if_missing: bool = False) -> str:
    progress(
        "[INFO] P6-T03 preflight: verifying WoW is closed and canonical DB is read-only baseline."
    )
    assert_wow_closed()
    canonical = resolve_canonical_db(args.db)
    baseline_hash = assert_canonical_baseline(canonical)
    wow_root = resolve_wow_root(args, configure_if_missing=configure_if_missing)
    cache_path = resolve_itemcache(args, wow_root)
    expected_cache = expected_itemcache_path(wow_root, args.locale)
    report = coverage_report(canonical, cache_path, expected_cache)
    record_hashes = current_record_hashes(cache_path)
    cache_exists, cache_hash = _cache_identity(cache_path)
    now = timestamp()
    ledger_path = args.ledger.resolve()

    if ledger_path.is_file():
        ledger = load_ledger(ledger_path)
        _assert_ledger_baseline(ledger, baseline_hash)
        if ledger["active_session"] is not None:
            raise RuntimeError(
                "campaign has an in-flight session; run postvalidate or recover before new "
                "preflight"
            )
        retired = reconcile_pre_session_cache_presence(
            ledger, current_record_sha256=record_hashes, updated_utc=now
        )
        if retired:
            progress(
                f"[INFO] Retired {len(retired)} newly pre-cached candidate(s) as "
                "historical_cache_only."
            )
    else:
        counts = report["counts"]
        candidates = report["canonical_item_ids_missing_from_cache_unknown"]
        ledger = create_campaign_ledger(
            canonical_sha256=baseline_hash,
            canonical_migration=EXPECTED_MIGRATION,
            canonical_item_count=int(counts["canonical_items"]),
            coverage_revision=str(report["coverage_revision"]),
            cache_pre_exists=cache_exists,
            cache_pre_sha256=cache_hash,
            initial_matching_cache_count=int(counts["cache_records_with_canonical_identity"]),
            initial_cache_only_count=int(counts["cache_only_native_ids"]),
            candidate_item_ids=candidates,
            created_utc=now,
            batch_limit=args.batch_size,
            max_campaign_attempts=args.max_campaign_attempts,
        )
        progress(
            f"[PASS] Created campaign ledger over {len(candidates)} known canonical cache miss(es)."
        )

    batch = list(select_next_batch(ledger, limit=args.batch_size))
    if not batch:
        atomic_write_ledger(ledger_path, ledger)
        raise RuntimeError("campaign has no eligible candidate IDs remaining")
    pre_hashes = {item_id: record_hashes.get(item_id) for item_id in batch}
    if any(value is not None for value in pre_hashes.values()):
        raise RuntimeError("selected batch contains a pre-session cache record")

    staged = stage_addon(wow_root)
    request_revision = begin_session(
        ledger,
        requested_item_ids=batch,
        pre_coverage_revision=str(report["coverage_revision"]),
        pre_cache_exists=cache_exists,
        pre_cache_sha256=cache_hash,
        pre_record_sha256=pre_hashes,
        started_utc=now,
    )
    atomic_write_ledger(ledger_path, ledger)

    command = "/ogitemprobe start " + ",".join(str(item_id) for item_id in batch)
    copy_command_to_clipboard(command)
    progress("P6_T03_PREFLIGHT_OK")
    progress(f"[PASS] canonical_sha256={baseline_hash}")
    progress(f"[PASS] campaign_id={ledger['campaign_id']}")
    progress(f"[PASS] request_revision={request_revision}")
    progress(f"[PASS] batch_size={len(batch)}")
    progress(f"[PASS] ledger={ledger_path}")
    progress(f"[PASS] addon_dir={staged}")
    progress("IN_GAME_COMMAND=" + command)
    progress(
        "[INFO] Launch WoW, enable OctoGameBDD Item Probe, run the exact command, wait for the "
        "'complete' message, then logout/exit WoW fully before post-processing."
    )
    if sha256_file(canonical) != baseline_hash:
        raise RuntimeError("canonical DB changed during read-only preflight")
    return command


def _post_cache(args: argparse.Namespace, wow_root: Path, export: dict[str, Any]) -> Path | None:
    if args.itemcache is not None:
        path = args.itemcache.expanduser().resolve()
        return path if path.is_file() else None
    locale = export.get("locale") if export else args.locale
    return find_itemcache_optional(wow_root, locale if isinstance(locale, str) else args.locale)


def _write_campaign_report(
    args: argparse.Namespace,
    *,
    ledger: dict[str, Any],
    canonical: Path,
    cache_path: Path | None,
    wow_root: Path,
) -> Path:
    expected_cache = expected_itemcache_path(wow_root, args.locale)
    coverage = coverage_report(canonical, cache_path, expected_cache)
    counts = coverage["counts"]
    report = campaign_report(
        ledger,
        canonical_sha256_after=sha256_file(canonical),
        current_matching_cache_count=int(counts["cache_records_with_canonical_identity"]),
        current_missing_cache_count=int(counts["canonical_item_ids_missing_from_cache_unknown"]),
    )
    report_path = args.report_dir.resolve() / f"P6-T03_campaign_{timestamp()}.json"
    write_json_report(report_path, report)
    return report_path


def postvalidate(args: argparse.Namespace, *, require_complete: bool = True) -> None:
    progress("[INFO] P6-T03 post-processing: WoW must be closed before WDB/SavedVariables read.")
    assert_wow_closed()
    canonical = resolve_canonical_db(args.db)
    baseline_hash = assert_canonical_baseline(canonical)
    ledger_path = args.ledger.resolve()
    ledger = load_ledger(ledger_path)
    _assert_ledger_baseline(ledger, baseline_hash)
    active = ledger.get("active_session")
    if isinstance(active, dict):
        requested = [int(value) for value in active["requested_item_ids"]]
    elif ledger["sessions"]:
        requested = [int(value) for value in ledger["sessions"][-1]["requested_item_ids"]]
    else:
        raise RuntimeError("campaign has no active or completed session")
    wow_root = resolve_wow_root(args, configure_if_missing=False)

    saved_path, export = find_matching_saved_variables(wow_root, requested)
    if require_complete and not export["complete"]:
        raise RuntimeError(
            "matching SavedVariables capture is incomplete; use recover after the client is closed"
        )
    cache_path = _post_cache(args, wow_root, export)
    post_hashes = current_record_hashes(cache_path)
    post_cache_exists, post_cache_hash = _cache_identity(cache_path)
    candidate = clone_ledger(ledger)
    result = merge_active_session(
        candidate,
        export=export,
        post_record_sha256=post_hashes,
        post_cache_exists=post_cache_exists,
        post_cache_sha256=post_cache_hash,
        merged_utc=timestamp(),
        require_complete=require_complete,
    )
    atomic_write_ledger(ledger_path, candidate)
    report_path = _write_campaign_report(
        args,
        ledger=candidate,
        canonical=canonical,
        cache_path=cache_path,
        wow_root=wow_root,
    )
    next_batch = select_next_batch(candidate, limit=args.batch_size)

    if sha256_file(canonical) != baseline_hash:
        raise RuntimeError("canonical DB changed during P6-T03 post-processing")
    progress("P6_T03_LOCAL_VALIDATION_OK")
    progress(f"[PASS] canonical_sha256={baseline_hash}")
    progress("[PASS] canonical_db_unchanged=true")
    progress(f"[PASS] saved_variables={saved_path}")
    progress(f"[PASS] session_merge_revision={result['merge_revision']}")
    progress(f"[PASS] duplicate_noop={str(result['duplicate']).lower()}")
    progress(f"[PASS] campaign_report={report_path}")
    progress(f"[PASS] next_batch_size={len(next_batch)}")
    if next_batch:
        progress("[PASS] next_batch_preview=" + ",".join(str(item_id) for item_id in next_batch))
    progress(
        "[PASS] Resume invariant: refresh-proven/session-limited/historical/terminal IDs are not "
        "eligible for the next batch; timeout/missing evidence remains non-negative."
    )
    return result


def recover(args: argparse.Namespace) -> None:
    """Recover one interrupted in-flight session from partial/missing SavedVariables evidence."""

    progress("[INFO] Recovering an interrupted P6-T03 session; WoW must be closed.")
    assert_wow_closed()
    canonical = resolve_canonical_db(args.db)
    baseline_hash = assert_canonical_baseline(canonical)
    ledger_path = args.ledger.resolve()
    ledger = load_ledger(ledger_path)
    _assert_ledger_baseline(ledger, baseline_hash)
    active = ledger.get("active_session")
    if not isinstance(active, dict):
        raise RuntimeError("campaign has no active session")
    requested = [int(value) for value in active["requested_item_ids"]]
    wow_root = resolve_wow_root(args, configure_if_missing=False)

    export: dict[str, Any] | None = None
    try:
        saved_path, export = find_matching_saved_variables(wow_root, requested)
        progress(f"[INFO] Matching SavedVariables found for recovery: {saved_path}")
    except FileNotFoundError:
        progress("[INFO] No matching SavedVariables capture survived; using WDB-only recovery.")
    cache_path = _post_cache(args, wow_root, export or {})
    post_hashes = current_record_hashes(cache_path)
    candidate = clone_ledger(ledger)
    if export is not None:
        result = merge_active_session(
            candidate,
            export=export,
            post_record_sha256=post_hashes,
            post_cache_exists=cache_path is not None,
            post_cache_sha256=None if cache_path is None else sha256_file(cache_path),
            merged_utc=timestamp(),
            require_complete=False,
        )
    else:
        result = recover_active_session_without_export(
            candidate,
            post_record_sha256=post_hashes,
            recovered_utc=timestamp(),
        )
    atomic_write_ledger(ledger_path, candidate)
    report_path = _write_campaign_report(
        args,
        ledger=candidate,
        canonical=canonical,
        cache_path=cache_path,
        wow_root=wow_root,
    )
    if sha256_file(canonical) != baseline_hash:
        raise RuntimeError("canonical DB changed during P6-T03 recovery")
    progress("P6_T03_RECOVERY_OK")
    progress(f"[PASS] recovery_merge_revision={result['merge_revision']}")
    progress(f"[PASS] campaign_report={report_path}")
    progress("[PASS] canonical_db_unchanged=true")


def report_only(args: argparse.Namespace) -> None:
    canonical = resolve_canonical_db(args.db)
    baseline_hash = assert_canonical_baseline(canonical)
    ledger = load_ledger(args.ledger.resolve())
    _assert_ledger_baseline(ledger, baseline_hash)
    wow_root = resolve_wow_root(args, configure_if_missing=False)
    cache_path = resolve_itemcache(args, wow_root)
    report_path = _write_campaign_report(
        args, ledger=ledger, canonical=canonical, cache_path=cache_path, wow_root=wow_root
    )
    if sha256_file(canonical) != baseline_hash:
        raise RuntimeError("canonical DB changed during campaign report")
    progress("P6_T03_REPORT_OK")
    progress(f"[PASS] campaign_report={report_path}")
    progress("[PASS] canonical_db_unchanged=true")


def run_local(args: argparse.Namespace) -> None:
    global _LOG_HANDLE
    args.report_dir.resolve().mkdir(parents=True, exist_ok=True)
    log_path = args.report_dir.resolve() / f"P6-T03_level2_{timestamp()}.log"
    with log_path.open("w", encoding="utf-8", newline="\n") as handle:
        _LOG_HANDLE = handle
        try:
            progress(f"[INFO] Streaming P6-T03 Level-2 log to {log_path}")
            configure_paths(args.config, interactive=True)
            preflight(args, configure_if_missing=False)
            progress("[INFO] Complete the in-game step shown above.")
            input("Press Enter only after WoW has been fully closed: ")
            first = postvalidate(args, require_complete=True)
            if first["duplicate"]:
                raise RuntimeError("first completed-session merge was unexpectedly a duplicate")
            progress("[INFO] Re-importing the same completed session to prove no-op idempotence.")
            second = postvalidate(args, require_complete=True)
            if not second["duplicate"]:
                raise RuntimeError("repeated completed-session merge was not detected as a no-op")
            progress("[PASS] Repeated session import is an evidence-preserving duplicate no-op.")
            ledger = load_ledger(args.ledger.resolve())
            next_batch = select_next_batch(ledger, limit=args.batch_size)
            if not next_batch:
                progress("[INFO] Campaign currently has no further eligible batch.")
            progress("P6_T03_REMAINING_LOCAL_VALIDATION_COMPLETE")
            progress("[PASS] The bounded campaign remains open; migration 14 was not promoted.")
        finally:
            _LOG_HANDLE = None
    print(f"[PASS] Full Level-2 log: {log_path}")


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
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_LIMIT)
    parser.add_argument(
        "--max-campaign-attempts", type=int, default=DEFAULT_MAX_CAMPAIGN_ATTEMPTS
    )
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= MAX_BATCH_LIMIT:
        parser.error(f"--batch-size must be between 1 and {MAX_BATCH_LIMIT}")
    if args.max_campaign_attempts < 1:
        parser.error("--max-campaign-attempts must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.mode == "configure-paths":
            configure_paths(args.config, interactive=not args.non_interactive)
            progress("P6_T03_PATHS_OK")
        elif args.mode == "preflight":
            preflight(args)
        elif args.mode == "postvalidate":
            postvalidate(args)
        elif args.mode == "recover":
            recover(args)
        elif args.mode == "report":
            report_only(args)
        else:
            run_local(args)
    except Exception as exc:
        progress(f"[FAIL] P6_T03_VALIDATION_FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
