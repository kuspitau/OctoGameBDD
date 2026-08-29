"""Read-only P6-T02 coverage report and bounded real-client freshness validator."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("Python 3.11+ is required (tomllib missing).") from exc

from octogamedb.importers.octo_itemcache import parse_itemcache_wdb
from octogamedb.itemcache_coverage import (
    PROBE_STATUS_ALREADY_CACHED,
    PROBE_STATUS_LOADED_AFTER_QUERY,
    PROBE_STATUS_TIMEOUT,
    build_absent_itemcache_coverage_report,
    build_itemcache_coverage_report,
    choose_missing_canonical_probe_ids,
    classify_probe_observation,
    itemcache_record_hashes,
    write_json_report,
)

EXPECTED_BASELINE_SHA256 = "623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
DEFAULT_CONFIG = Path("config.local.toml")
DEFAULT_STATE = Path("data/generated/p6_t02_preflight.json")
DEFAULT_REPORT_DIR = Path("data/generated/validation_logs")
ADDON_SOURCE = Path("scripts/octogamedb_item_probe")
ADDON_NAME = "OctoGameBDD_ItemProbe"
EXPORT_RE = re.compile(r'^OctoGameBDD_ItemProbeExport\s*=\s*"([^"]*)"', re.MULTILINE)


def progress(message: str) -> None:
    print(message, flush=True)


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
        data = tomllib.load(handle)
    raw = data.get("source_paths", {}).get("wow_root")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser()


def resolve_canonical_db(explicit: Path | None) -> Path:
    candidates = [explicit] if explicit is not None else [
        Path("data/generated/octogamedb.sqlite3"),
        Path("data/octogamedb.sqlite3"),
    ]
    existing = [path.resolve() for path in candidates if path is not None and path.is_file()]
    if not existing:
        raise FileNotFoundError(
            "Canonical DB not found. Expected data/generated/octogamedb.sqlite3 "
            "(or legacy data/octogamedb.sqlite3), or pass --db."
        )
    exact = [path for path in existing if sha256_file(path) == EXPECTED_BASELINE_SHA256]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise RuntimeError("Multiple byte-identical canonical baseline candidates found; pass --db")
    raise RuntimeError(
        "No candidate matches the documented migration-13 canonical SHA-256; do not continue. "
        + ", ".join(f"{path}={sha256_file(path)}" for path in existing)
    )


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
        version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
            ).fetchone()[0]
        )
        if version != 13:
            raise RuntimeError(f"Expected canonical migration 13, found {version}")
    return digest


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
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            unique.append(resolved)

    if not unique:
        return None

    if locale:
        exact = [path for path in unique if path.parent.name.lower() == locale.lower()]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise RuntimeError(f"Ambiguous {locale} itemcache candidates: {exact}")

        matching_header: list[Path] = []
        for path in unique:
            try:
                if parse_itemcache_wdb(path).header.locale.lower() == locale.lower():
                    matching_header.append(path)
            except (OSError, ValueError):
                continue
        if len(matching_header) == 1:
            return matching_header[0]
        if len(matching_header) > 1:
            raise RuntimeError(
                f"Multiple itemcache.wdb files report locale {locale}: {matching_header}"
            )

    if len(unique) != 1:
        raise RuntimeError("Multiple itemcache.wdb candidates; rerun with --itemcache or --locale")
    return unique[0]


def resolve_itemcache_optional(
    args: argparse.Namespace, wow_root: Path | None
) -> Path | None:
    if args.itemcache is not None:
        path = args.itemcache.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    if wow_root is None:
        return None
    return find_itemcache_optional(wow_root, args.locale)


def expected_itemcache_path(wow_root: Path, locale: str | None) -> Path:
    target_locale = locale or "enUS"
    return (wow_root / "WDB" / target_locale / "itemcache.wdb").resolve()


def timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_coverage(canonical: Path, cache_path: Path, report_path: Path) -> dict[str, object]:
    progress(f"[coverage] parsing {cache_path}")
    with sqlite3.connect(f"file:{canonical.as_posix()}?mode=ro", uri=True) as connection:
        report = build_itemcache_coverage_report(connection, source_path=cache_path)
    write_json_report(report_path, report)
    counts = report["counts"]
    progress(
        "[coverage] cache_records={cache_records} canonical_items={canonical_items} "
        "matched={cache_records_with_canonical_identity} cache_only={cache_only_native_ids} "
        "canonical_missing_unknown={canonical_item_ids_missing_from_cache_unknown}".format(**counts)
    )
    progress(f"[coverage] report={report_path}")
    return report


def build_absent_coverage(
    canonical: Path, expected_cache_path: Path, report_path: Path
) -> dict[str, object]:
    progress("[coverage] no preflight itemcache.wdb exists; recording clean-cache state")
    with sqlite3.connect(f"file:{canonical.as_posix()}?mode=ro", uri=True) as connection:
        report = build_absent_itemcache_coverage_report(
            connection, expected_source_path=expected_cache_path
        )
    write_json_report(report_path, report)
    counts = report["counts"]
    progress(
        "[coverage] cache_records=0 canonical_items={canonical_items} "
        "canonical_missing_unknown={canonical_item_ids_missing_from_cache_unknown}".format(
            **counts
        )
    )
    progress(f"[coverage] report={report_path}")
    return report


def stage_addon(wow_root: Path) -> Path:
    source = ADDON_SOURCE.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Probe addon source not found: {source}")
    addon_dir = wow_root / "Interface" / "AddOns" / ADDON_NAME
    addon_dir.mkdir(parents=True, exist_ok=True)
    for name in ("OctoGameBDD_ItemProbe.toc", "OctoGameBDD_ItemProbe.lua"):
        shutil.copy2(source / name, addon_dir / name)
    return addon_dir


def parse_export_string(value: str) -> dict[str, object]:
    fields: dict[str, str] = {}
    for part in value.split("|"):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        fields[key] = raw
    if fields.get("v") != "1":
        raise ValueError(f"Unsupported probe export version: {fields.get('v')!r}")
    ids = [int(value) for value in fields.get("ids", "").split(",") if value]
    results: dict[int, dict[str, str]] = {}
    raw_results = fields.get("results", "")
    if raw_results:
        for entry in raw_results.split(","):
            bits = entry.split(":")
            if len(bits) != 3:
                raise ValueError(f"Malformed probe result entry: {entry!r}")
            item_id = int(bits[0])
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


def read_saved_variables_export(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = EXPORT_RE.search(text)
    if match is None:
        raise ValueError(f"No OctoGameBDD_ItemProbeExport string in {path}")
    return parse_export_string(match.group(1))


def find_matching_saved_variables(
    wow_root: Path, requested_ids: list[int]
) -> tuple[Path, dict[str, object]]:
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
        "No SavedVariables capture matches the preflight ID list. Ensure the addon was enabled, "
        "run the exact /ogitemprobe start command, wait for completion, then logout/exit WoW."
        + suffix
    )


def preflight(args: argparse.Namespace) -> None:
    progress("[preflight] verifying migration-13 canonical baseline (read-only)")
    canonical = resolve_canonical_db(args.db)
    baseline_hash = assert_canonical_baseline(canonical)
    wow_root = args.wow_root.resolve() if args.wow_root else read_wow_root(args.config)
    if wow_root is None:
        raise RuntimeError(
            "wow_root is required for the real-client probe; pass --wow-root or configure "
            "[source_paths].wow_root"
        )
    wow_root = wow_root.resolve()
    if not wow_root.is_dir():
        raise FileNotFoundError(f"WoW root not found: {wow_root}")

    cache_path = resolve_itemcache_optional(args, wow_root)
    expected_cache = expected_itemcache_path(wow_root, args.locale)

    run_id = timestamp()
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    coverage_path = report_dir / f"P6-T02_coverage_{run_id}.json"

    if cache_path is None:
        report = build_absent_coverage(canonical, expected_cache, coverage_path)
        pre_hashes_source: dict[int, str] = {}
        cache_pre_hash = None
        cache_pre_exists = False
    else:
        report = build_coverage(canonical, cache_path, coverage_path)
        snapshot = parse_itemcache_wdb(cache_path)
        pre_hashes_source = itemcache_record_hashes(snapshot)
        cache_pre_hash = sha256_file(cache_path)
        cache_pre_exists = True

    candidate_ids = list(choose_missing_canonical_probe_ids(report, limit=args.limit))
    if not candidate_ids:
        raise RuntimeError(
            "Coverage contains no canonical IDs missing from the cache; no cache-miss freshness "
            "probe can be formed without inventing/brute-forcing IDs."
        )

    pre_hashes = {str(item_id): pre_hashes_source.get(item_id) for item_id in candidate_ids}
    if any(value is not None for value in pre_hashes.values()):
        raise RuntimeError("Probe candidates must be absent from the preflight cache snapshot")

    progress("[preflight] staging bounded probe addon into the configured WoW client")
    addon_dir = stage_addon(wow_root)

    state = {
        "version": 2,
        "created_utc": run_id,
        "canonical_db": str(canonical),
        "canonical_sha256": baseline_hash,
        "itemcache_pre_exists": cache_pre_exists,
        "itemcache": None if cache_path is None else str(cache_path),
        "itemcache_expected_path": str(expected_cache),
        "itemcache_pre_sha256": cache_pre_hash,
        "cache_locale_hint": args.locale,
        "coverage_report": str(coverage_path),
        "coverage_revision": report["coverage_revision"],
        "candidate_item_ids": candidate_ids,
        "pre_record_sha256": pre_hashes,
        "wow_root": str(wow_root),
        "addon_dir": str(addon_dir),
    }
    write_json_report(args.state.resolve(), state)

    command = "/ogitemprobe start " + ",".join(str(item_id) for item_id in candidate_ids)
    progress("P6_T02_PREFLIGHT_OK")
    progress(f"canonical_sha256={baseline_hash}")
    progress(f"cache_pre_exists={str(cache_pre_exists).lower()}")
    progress(f"coverage_report={coverage_path}")
    progress("probe_item_ids=" + ",".join(str(item_id) for item_id in candidate_ids))
    progress(f"addon_dir={addon_dir}")
    progress("IN_GAME_COMMAND=" + command)
    progress(
        "IN_GAME_NEXT=Enable OctoGameBDD Item Probe, login, run the command above, wait for the "
        "'complete' message, then logout or exit WoW before continuing."
    )


def postvalidate(args: argparse.Namespace) -> None:
    state_path = args.state.resolve()
    if not state_path.is_file():
        raise FileNotFoundError(f"Preflight state not found: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    requested_ids = [int(value) for value in state["candidate_item_ids"]]
    canonical = Path(state["canonical_db"])
    wow_root = Path(state["wow_root"])

    progress("[post] verifying canonical DB stayed byte-identical")
    baseline_hash = assert_canonical_baseline(canonical)
    if baseline_hash != state["canonical_sha256"]:
        raise RuntimeError("Canonical baseline differs from preflight state")

    progress("[post] reading matching real-client SavedVariables export")
    saved_path, export = find_matching_saved_variables(wow_root, requested_ids)
    if not export["complete"]:
        raise RuntimeError(f"Probe capture is not complete: {saved_path}")
    results = export["results"]
    missing_results = [item_id for item_id in requested_ids if item_id not in results]
    if missing_results:
        raise RuntimeError(f"Probe export lacks requested IDs: {missing_results}")

    allowed_statuses = {
        PROBE_STATUS_ALREADY_CACHED,
        PROBE_STATUS_LOADED_AFTER_QUERY,
        PROBE_STATUS_TIMEOUT,
    }
    for item_id in requested_ids:
        status = results[item_id]["status"]
        if status not in allowed_statuses:
            raise RuntimeError(f"Unsupported probe status for {item_id}: {status}")

    progress("[post] locating any post-session itemcache.wdb")
    cache_path: Path | None = None
    state_cache = state.get("itemcache")
    if state_cache:
        candidate = Path(state_cache)
        if candidate.is_file():
            cache_path = candidate.resolve()
    if cache_path is None:
        export_locale = export.get("locale")
        locale = export_locale if isinstance(export_locale, str) and export_locale else None
        cache_path = find_itemcache_optional(wow_root, locale)

    post_hashes: dict[int, str] = {}
    post_cache_hash: str | None = None
    if cache_path is None:
        progress(
            "[post] no itemcache.wdb exists after the session; successful in-session loads will "
            "remain session_observed_freshness_limited"
        )
    else:
        progress(f"[post] parsing post-session WDB: {cache_path}")
        post_snapshot = parse_itemcache_wdb(cache_path)
        post_hashes = itemcache_record_hashes(post_snapshot)
        post_cache_hash = sha256_file(cache_path)

    classifications = []
    for item_id in requested_ids:
        classification = classify_probe_observation(
            item_id=item_id,
            pre_record_sha256=state["pre_record_sha256"].get(str(item_id)),
            post_record_sha256=post_hashes.get(item_id),
            probe_status=results[item_id]["status"],
        )
        classifications.append(classification)

    counts: dict[str, int] = {}
    for classification in classifications:
        counts[classification.freshness_class] = counts.get(classification.freshness_class, 0) + 1

    output = {
        "report_version": 2,
        "preflight": state,
        "saved_variables": str(saved_path),
        "capture": export,
        "itemcache_post_exists": cache_path is not None,
        "itemcache_post": None if cache_path is None else str(cache_path),
        "itemcache_post_sha256": post_cache_hash,
        "classifications": [value.to_json() for value in classifications],
        "freshness_class_counts": counts,
        "canonical_db_unchanged": sha256_file(canonical) == state["canonical_sha256"],
    }
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"P6-T02_refresh_probe_{timestamp()}.json"
    write_json_report(report_path, output)

    progress("P6_T02_LOCAL_VALIDATION_OK")
    progress(f"canonical_sha256={baseline_hash}")
    progress("canonical_db_unchanged=true")
    progress(f"saved_variables={saved_path}")
    progress(f"itemcache_post_exists={str(cache_path is not None).lower()}")
    progress(f"refresh_probe_report={report_path}")
    for key in sorted(counts):
        progress(f"freshness_{key}={counts[key]}")
    progress(
        "INTERPRETATION=Only refresh_proven_direct_observation entries have cache-miss + "
        "in-session load + post-WDB raw-record proof. Successful loads without a written WDB "
        "record are session-limited evidence; timeouts remain unknown."
    )


def coverage_only(args: argparse.Namespace) -> None:
    canonical = resolve_canonical_db(args.db)
    baseline_hash = assert_canonical_baseline(canonical)
    wow_root = args.wow_root.resolve() if args.wow_root else read_wow_root(args.config)
    if wow_root is not None:
        wow_root = wow_root.resolve()
    cache_path = resolve_itemcache_optional(args, wow_root)
    report_path = args.output or (args.report_dir / f"P6-T02_coverage_{timestamp()}.json")
    report_path = report_path.resolve()
    if cache_path is None:
        if wow_root is None:
            raise RuntimeError(
                "No itemcache.wdb exists and no wow_root is available to represent the clean "
                "cache state."
            )
        build_absent_coverage(
            canonical, expected_itemcache_path(wow_root, args.locale), report_path
        )
    else:
        build_coverage(canonical, cache_path, report_path)
    if sha256_file(canonical) != baseline_hash:
        raise RuntimeError("Canonical DB changed during read-only coverage report")
    progress("P6_T02_COVERAGE_REPORT_OK")
    progress("canonical_db_unchanged=true")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("coverage", "preflight", "postvalidate"))
    parser.add_argument("--db", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--wow-root", type=Path)
    parser.add_argument("--itemcache", type=Path)
    parser.add_argument("--locale", default="enUS")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("--limit must be between 1 and 20")
    return args


def main() -> None:
    args = parse_args()
    try:
        if args.mode == "coverage":
            coverage_only(args)
        elif args.mode == "preflight":
            preflight(args)
        else:
            postvalidate(args)
    except Exception as exc:
        progress(f"P6_T02_VALIDATION_FAILED: {exc}")
        raise


if __name__ == "__main__":
    main()
