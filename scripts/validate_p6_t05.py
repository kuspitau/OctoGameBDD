"""P6-T05 migration-14 coverage expansion and guarded incremental canonical promotion.

Acquisition sessions reuse ``scripts/validate_p6_t03.py`` with the P6-T05 ledger path.  This
validator consumes the resulting ledger plus retained historical D-037 evidence, builds an exact
current-hash plan, rehearses migration-14 -> migration-14 ingestion on a disposable copy, and only
then permits a D-029 canonical promotion.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from octogamedb.canonical_baseline import (
    ACCEPTED_CANONICAL_BASELINE,
    P6_T04_INPUT_BASELINE,
    P6_T05_INPUT_BASELINE,
    CanonicalBaseline,
    assert_canonical_baseline as assert_shared_canonical_baseline,
    sha256_file,
)
from octogamedb.db import apply_migrations, get_applied_migrations
from octogamedb.importers.octo_itemcache import (
    SELECTION_POLICY,
    import_octo_itemcache_slice,
    parse_itemcache_wdb,
)
from octogamedb.item_search import query_item_templates
from octogamedb.itemcache_campaign import load_ledger
from octogamedb.itemcache_coverage import build_itemcache_coverage_report, itemcache_record_hashes
from octogamedb.itemcache_incremental_promotion import (
    IncrementalPromotionPlan,
    build_incremental_promotion_plan,
    campaign_counts,
    proofs_from_campaign_ledger,
    write_plan,
)
from octogamedb.itemcache_promotion import (
    FRESHNESS_HISTORICAL_CACHE,
    FRESHNESS_REFRESH_PROVEN,
    FRESHNESS_SESSION_OBSERVED,
    FRESHNESS_UNKNOWN,
    FreshnessProof,
    load_json_object,
    proofs_from_p6_t02_report,
    proofs_from_p6_t03_ledger,
)

EXPECTED_BASELINE_SHA256 = ACCEPTED_CANONICAL_BASELINE.sha256
EXPECTED_BASELINE_MIGRATION = ACCEPTED_CANONICAL_BASELINE.migration
EXPECTED_BASELINE_LABEL = ACCEPTED_CANONICAL_BASELINE.label
TARGET_MIGRATION = 14
EXPECTED_TARGET_MIGRATION_NAME = "0014_item_template_facts.sql"
MIN_NEW_REFRESH_PROVEN = 10
MAX_NEW_ATTEMPTED_UNIQUE = 100

DEFAULT_DB = Path("data/generated/octogamedb.sqlite3")
DEFAULT_BACKUP = Path("data/generated/octogamedb_bak.sqlite3")
DEFAULT_CURRENT_VALIDATION_DB = Path("data/generated/p6_itemcache_validation.sqlite3")
DEFAULT_CURRENT_PLAN = Path("data/generated/p6_itemcache_promotion_plan.json")
DEFAULT_CURRENT_CAMPAIGN = Path("data/generated/p6_itemcache_campaign.json")
DEFAULT_HISTORICAL_VALIDATION_DB = Path("data/generated/p6_t05_validation.sqlite3")
DEFAULT_HISTORICAL_PLAN = Path("data/generated/p6_t05_promotion_plan.json")
DEFAULT_HISTORICAL_CAMPAIGN = Path("data/generated/p6_t05_campaign.json")
DEFAULT_VALIDATION_DB = DEFAULT_CURRENT_VALIDATION_DB
DEFAULT_PLAN = DEFAULT_CURRENT_PLAN
DEFAULT_CAMPAIGN = DEFAULT_CURRENT_CAMPAIGN
DEFAULT_LEGACY_LEDGER = Path("data/generated/p6_t03_campaign.json")
DEFAULT_REPORT_DIR = Path("data/generated/validation_logs")
DEFAULT_CONFIG = Path("config.local.toml")

_MANAGED_P6_POLICIES = frozenset(
    {
        "p6-item-template/octo-itemcache",
        "p6-item-template/octodb",
        "p6-item-template/tortoise-fallback",
        "p6-item-template/cmangos-fallback",
    }
)


def progress(message: str) -> None:
    print(message, flush=True)


def timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _current_baseline() -> CanonicalBaseline:
    # Keep test monkeypatching possible while sourcing production values from one shared contract.
    return CanonicalBaseline(
        migration=EXPECTED_BASELINE_MIGRATION,
        sha256=EXPECTED_BASELINE_SHA256,
        label=EXPECTED_BASELINE_LABEL,
    )


def baseline_for_mode(mode: str) -> CanonicalBaseline:
    if mode == "current":
        return ACCEPTED_CANONICAL_BASELINE
    if mode == "p6-t05-input":
        return P6_T05_INPUT_BASELINE
    raise ValueError(f"unsupported baseline mode: {mode}")


def configure_runtime_baseline(baseline: CanonicalBaseline) -> None:
    global EXPECTED_BASELINE_SHA256, EXPECTED_BASELINE_MIGRATION, EXPECTED_BASELINE_LABEL
    EXPECTED_BASELINE_SHA256 = baseline.sha256
    EXPECTED_BASELINE_MIGRATION = baseline.migration
    EXPECTED_BASELINE_LABEL = baseline.label


def default_artifacts_for_mode(mode: str) -> tuple[Path, Path, Path, str]:
    if mode == "current":
        return (
            DEFAULT_CURRENT_VALIDATION_DB,
            DEFAULT_CURRENT_PLAN,
            DEFAULT_CURRENT_CAMPAIGN,
            "P6-itemcache",
        )
    if mode == "p6-t05-input":
        return (
            DEFAULT_HISTORICAL_VALIDATION_DB,
            DEFAULT_HISTORICAL_PLAN,
            DEFAULT_HISTORICAL_CAMPAIGN,
            "P6-T05",
        )
    raise ValueError(f"unsupported baseline mode: {mode}")


def schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    return int(row[0])


def sqlite_sidecars(path: Path) -> list[Path]:
    return [
        candidate
        for suffix in ("-wal", "-shm", "-journal")
        if (candidate := Path(str(path) + suffix)).exists()
    ]


def assert_no_sidecars(path: Path) -> None:
    sidecars = sqlite_sidecars(path)
    if sidecars:
        raise RuntimeError(
            "SQLite sidecar(s) exist; close all writers/clients and resolve them first: "
            + ", ".join(str(candidate) for candidate in sidecars)
        )


def open_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def assert_canonical_baseline(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Canonical DB not found at required D-029 path: {path}")
    return assert_shared_canonical_baseline(path, baseline=_current_baseline())


def read_wow_root(config_path: Path) -> Path | None:
    if not config_path.is_file():
        return None
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    value = payload.get("source_paths", {}).get("wow_root")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def find_itemcache(wow_root: Path, locale: str) -> Path:
    roots = (wow_root / "WDB", wow_root / "Cache" / "WDB")
    candidates: list[Path] = []
    for root in roots:
        candidates.append(root / locale / "itemcache.wdb")
        candidates.append(root / "itemcache.wdb")
        if root.is_dir():
            candidates.extend(sorted(root.glob("*/itemcache.wdb")))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if str(resolved) not in seen:
            seen.add(str(resolved))
            unique.append(resolved)
    if not unique:
        raise FileNotFoundError(
            f"No itemcache.wdb found below configured wow_root {wow_root}; pass --itemcache"
        )
    exact = [path for path in unique if path.parent.name.casefold() == locale.casefold()]
    if len(exact) == 1:
        return exact[0]
    header_matches: list[Path] = []
    for path in unique:
        try:
            if parse_itemcache_wdb(path).header.locale.casefold() == locale.casefold():
                header_matches.append(path)
        except (OSError, ValueError):
            continue
    if len(header_matches) == 1:
        return header_matches[0]
    if len(unique) == 1:
        return unique[0]
    raise RuntimeError(f"Ambiguous itemcache.wdb candidates: {unique}; pass --itemcache")


def resolve_itemcache(args: argparse.Namespace) -> Path:
    if args.itemcache is not None:
        path = args.itemcache.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    wow_root = read_wow_root(args.config)
    if wow_root is None:
        raise RuntimeError(
            "[source_paths].wow_root is not configured; P6-T05 reuses the P6-T03 path. "
            "Run the existing configure-paths mode or pass --itemcache."
        )
    return find_itemcache(wow_root.expanduser().resolve(), args.locale)


def discover_p6_t02_reports(report_dir: Path) -> list[Path]:
    if not report_dir.is_dir():
        return []
    return sorted(report_dir.glob("P6-T02_refresh_probe_*.json"))


def _p6_t02_report_baseline(report: dict[str, Any]) -> str:
    preflight = report.get("preflight")
    if not isinstance(preflight, dict):
        raise TypeError("P6-T02 report lacks preflight metadata")
    digest = str(preflight.get("canonical_sha256", ""))
    accepted = {
        P6_T04_INPUT_BASELINE.sha256,
        P6_T05_INPUT_BASELINE.sha256,
        ACCEPTED_CANONICAL_BASELINE.sha256,
        EXPECTED_BASELINE_SHA256,
    }
    if digest not in accepted:
        raise ValueError(
            "P6-T02 evidence is anchored to an unaccepted canonical baseline: " + digest
        )
    return digest


def _load_evidence(
    args: argparse.Namespace, campaign: dict[str, Any]
) -> tuple[list[FreshnessProof], list[dict[str, Any]]]:
    proofs: list[FreshnessProof] = []
    artifacts: list[dict[str, Any]] = []

    report_paths = [path.resolve() for path in args.p6_t02_report]
    if not report_paths:
        report_paths = discover_p6_t02_reports(args.report_dir.resolve())
    for report_path in report_paths:
        report_hash = sha256_file(report_path)
        report = load_json_object(report_path)
        anchored_sha = _p6_t02_report_baseline(report)
        proofs.extend(
            proofs_from_p6_t02_report(
                report,
                artifact_sha256=report_hash,
                expected_canonical_sha256=anchored_sha,
            )
        )
        artifacts.append(
            {
                "kind": "p6_t02_refresh_report",
                "name": report_path.name,
                "sha256": report_hash,
                "canonical_sha256": anchored_sha,
            }
        )

    legacy_path = args.legacy_ledger.resolve()
    if legacy_path.is_file():
        legacy_hash = sha256_file(legacy_path)
        legacy = load_ledger(legacy_path)
        proofs.extend(
            proofs_from_p6_t03_ledger(
                legacy,
                artifact_sha256=legacy_hash,
                expected_canonical_sha256=P6_T04_INPUT_BASELINE.sha256,
            )
        )
        artifacts.append(
            {
                "kind": "p6_t03_campaign_ledger",
                "name": legacy_path.name,
                "sha256": legacy_hash,
                "canonical_sha256": P6_T04_INPUT_BASELINE.sha256,
            }
        )
    else:
        progress(
            "[INFO] Historical P6-T03 ledger is absent; retained P6-T02 + P6-T05 evidence "
            "will be used."
        )

    campaign_path = args.campaign.resolve()
    campaign_hash = sha256_file(campaign_path)
    proofs.extend(
        proofs_from_campaign_ledger(
            campaign,
            artifact_sha256=campaign_hash,
            expected_canonical_sha256=EXPECTED_BASELINE_SHA256,
            expected_canonical_migration=EXPECTED_BASELINE_MIGRATION,
        )
    )
    artifacts.append(
        {
            "kind": "p6_t05_campaign_ledger",
            "name": campaign_path.name,
            "sha256": campaign_hash,
            "canonical_sha256": EXPECTED_BASELINE_SHA256,
        }
    )
    return proofs, artifacts


def _materialized_stats(record: Any) -> tuple[tuple[int, int, int], ...]:
    return tuple(
        (int(slot.slot_index), int(slot.stat_type), int(slot.stat_value))
        for slot in record.stat_slots
        if int(slot.stat_type) != 0 or int(slot.stat_value) != 0
    )


def _is_current_direct_projection(
    connection: sqlite3.Connection, *, record: Any
) -> bool:
    item_id = int(record.item_id)
    values = record.scalar_values()
    fields = tuple(values)
    template = connection.execute(
        f"SELECT {', '.join(fields)} FROM item_templates WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    if template is None:
        return False
    if any(int(template[field]) != int(values[field]) for field in fields):
        return False

    stats = tuple(
        (int(row["slot_index"]), int(row["stat_type"]), int(row["stat_value"]))
        for row in connection.execute(
            """
            SELECT slot_index, stat_type, stat_value
            FROM item_stat_modifiers
            WHERE item_id = ?
            ORDER BY slot_index
            """,
            (item_id,),
        ).fetchall()
    )
    if stats != _materialized_stats(record):
        return False

    expected_facts = {f"template.{field}" for field in fields} | {"template.stat_slots"}
    selected = connection.execute(
        """
        SELECT og.fact_key, cs.selection_policy, ds.source_key
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = 'item'
          AND CAST(og.subject_key AS INTEGER) = ?
          AND og.fact_key LIKE 'template.%'
        """,
        (item_id,),
    ).fetchall()
    by_fact = {str(row["fact_key"]): row for row in selected}
    if not expected_facts.issubset(by_fact):
        return False
    return all(
        str(by_fact[fact]["source_key"]) == "octo-itemcache"
        and str(by_fact[fact]["selection_policy"]) == SELECTION_POLICY
        for fact in expected_facts
    )


def _already_current_items(
    connection: sqlite3.Connection,
    *,
    snapshot: Any,
    candidate_item_ids: set[int],
) -> set[int]:
    by_id = snapshot.by_id
    return {
        item_id
        for item_id in sorted(candidate_item_ids)
        if item_id in by_id
        and _is_current_direct_projection(connection, record=by_id[item_id])
    }


def build_current_plan(
    args: argparse.Namespace,
) -> tuple[IncrementalPromotionPlan, Path, dict[str, Any]]:
    canonical = args.db.resolve()
    baseline_hash = assert_canonical_baseline(canonical)
    campaign_path = args.campaign.resolve()
    if not campaign_path.is_file():
        raise FileNotFoundError(
            f"P6-T05 campaign ledger not found: {campaign_path}. Run the bounded acquisition first."
        )
    campaign = load_ledger(campaign_path)
    canonical_meta = campaign.get("canonical", {})
    if (
        str(canonical_meta.get("sha256", "")) != baseline_hash
        or int(canonical_meta.get("migration", -1)) != EXPECTED_BASELINE_MIGRATION
    ):
        raise RuntimeError(
            "P6-T05 campaign is not anchored to the accepted migration-14 baseline; "
            "do not reuse or mutate the historical P6-T03 ledger."
        )
    counts = campaign_counts(campaign)
    if counts["attempted_unique_items"] > MAX_NEW_ATTEMPTED_UNIQUE:
        raise RuntimeError(
            f"P6-T05 attempted {counts['attempted_unique_items']} unique IDs; hard validation "
            f"cap is {MAX_NEW_ATTEMPTED_UNIQUE}."
        )
    if counts["refresh_proven_items"] < args.min_refresh_proven:
        raise RuntimeError(
            "P6-T05 acquisition target is not met: "
            f"refresh_proven={counts['refresh_proven_items']} required={args.min_refresh_proven}. "
            "Stop and report server instability rather than weakening freshness rules."
        )

    cache_path = resolve_itemcache(args)
    snapshot = parse_itemcache_wdb(cache_path)
    cache_hash = sha256_file(cache_path)
    current_hashes = itemcache_record_hashes(snapshot)
    proofs, artifacts = _load_evidence(args, campaign)
    refresh_candidates = {
        proof.item_id
        for proof in proofs
        if proof.freshness_class == FRESHNESS_REFRESH_PROVEN
        and proof.raw_record_sha256 == current_hashes.get(proof.item_id)
    }

    uri = f"file:{canonical.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        if refresh_candidates:
            placeholders = ",".join("?" for _ in refresh_candidates)
            rows = connection.execute(
                f"SELECT item_id FROM items WHERE item_id IN ({placeholders}) ORDER BY item_id",
                tuple(sorted(refresh_candidates)),
            ).fetchall()
            canonical_ids = {int(row[0]) for row in rows}
        else:
            canonical_ids = set()
        missing_identity = sorted(refresh_candidates - canonical_ids)
        if missing_identity:
            raise RuntimeError(
                "Refresh proof includes IDs without canonical item identity; placeholder "
                f"creation is forbidden: {missing_identity}"
            )
        already_current = _already_current_items(
            connection,
            snapshot=snapshot,
            candidate_item_ids=refresh_candidates,
        )
        coverage = build_itemcache_coverage_report(connection, source_path=cache_path)

    plan = build_incremental_promotion_plan(
        canonical_sha256=baseline_hash,
        canonical_migration=EXPECTED_BASELINE_MIGRATION,
        itemcache_sha256=cache_hash,
        itemcache_locale=snapshot.header.locale,
        itemcache_client_version=snapshot.header.client_version,
        current_record_sha256=current_hashes,
        proofs=proofs,
        already_current_item_ids=already_current,
        evidence_artifacts=artifacts,
        current_campaign_counts=counts,
    )
    if not plan.eligible_item_ids:
        raise RuntimeError(
            "No new exact refresh-proven item remains after current-hash and already-current no-op "
            "filtering; do not perform a canonical write."
        )
    write_plan(args.plan.resolve(), plan)
    progress(f"[plan] plan_revision={plan.plan_revision}")
    progress(f"[plan] new_refresh_proven={counts['refresh_proven_items']}")
    progress(f"[plan] attempted_unique={counts['attempted_unique_items']}")
    progress(f"[plan] eligible_item_count={len(plan.eligible_item_ids)}")
    progress(f"[plan] already_current_noop_count={len(plan.already_current_noops)}")
    coverage_counts = dict(coverage["counts"])
    progress(
        "[plan] coverage_counts="
        + json.dumps(coverage_counts, sort_keys=True, separators=(",", ":"))
    )
    return plan, cache_path, coverage_counts


def protected_template_selections(
    connection: sqlite3.Connection, item_ids: tuple[int, ...]
) -> dict[int, tuple[int, str | None]]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" for _ in item_ids)
    rows = connection.execute(
        f"""
        SELECT og.id, cs.observation_id, cs.selection_policy
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        WHERE og.subject_kind = 'item'
          AND CAST(og.subject_key AS INTEGER) IN ({placeholders})
          AND og.fact_key LIKE 'template.%'
        """,
        item_ids,
    ).fetchall()
    result: dict[int, tuple[int, str | None]] = {}
    for row in rows:
        policy = None if row["selection_policy"] is None else str(row["selection_policy"])
        if policy not in _MANAGED_P6_POLICIES:
            result[int(row["id"])] = (int(row["observation_id"]), policy)
    return result


def attach_promotion_context(
    connection: sqlite3.Connection,
    *,
    source_revision: str,
    plan: IncrementalPromotionPlan,
    phase: str,
) -> int:
    row = connection.execute(
        """
        SELECT ib.id, ib.details_json
        FROM import_batches AS ib
        JOIN data_sources AS ds ON ds.id = ib.source_id
        WHERE ds.source_key = 'octo-itemcache'
          AND ib.source_revision = ?
          AND ib.status = 'succeeded'
        ORDER BY ib.id DESC
        LIMIT 1
        """,
        (source_revision,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Could not locate the P6 itemcache import batch just written")
    details = {} if row["details_json"] is None else json.loads(str(row["details_json"]))
    if not isinstance(details, dict):
        raise RuntimeError("P6 itemcache import details_json is not an object")
    details["p6_t05_incremental_promotion"] = {
        "phase": phase,
        "plan_revision": plan.plan_revision,
        "freshness_class": FRESHNESS_REFRESH_PROVEN,
        "eligible_item_count": len(plan.eligible_item_ids),
        "already_current_noop_count": len(plan.already_current_noops),
        "eligible_items": [
            {
                "item_id": int(item["item_id"]),
                "current_record_sha256": item["current_record_sha256"],
                "proof_revisions": [proof["proof_revision"] for proof in item["matching_proofs"]],
                "proof_kinds": sorted({proof["proof_kind"] for proof in item["matching_proofs"]}),
            }
            for item in plan.eligible_items
        ],
        "excluded_semantics": {
            FRESHNESS_SESSION_OBSERVED: "not selected: no persisted fresh field bytes",
            FRESHNESS_HISTORICAL_CACHE: "not selected: positive but not currentness-proven",
            FRESHNESS_UNKNOWN: "not selected: unknown is never negative/selection authority",
        },
    }
    connection.execute(
        "UPDATE import_batches SET details_json = ? WHERE id = ?",
        (json.dumps(details, sort_keys=True, separators=(",", ":")), int(row["id"])),
    )
    return int(row["id"])


def assert_integrity(connection: sqlite3.Connection) -> None:
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise RuntimeError(f"PRAGMA foreign_key_check failed: {foreign_keys[:10]}")
    integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
    if integrity != ["ok"]:
        raise RuntimeError(f"PRAGMA integrity_check failed: {integrity}")


def validate_incremental_database(
    connection: sqlite3.Connection,
    *,
    plan: IncrementalPromotionPlan,
    cache_path: Path,
    phase: str,
) -> dict[str, Any]:
    if schema_version(connection) != TARGET_MIGRATION:
        raise RuntimeError("P6-T05 validation target must already be migration 14")
    applied = get_applied_migrations(connection)
    if not applied or applied[-1] != (TARGET_MIGRATION, EXPECTED_TARGET_MIGRATION_NAME):
        raise RuntimeError(f"Unexpected migration tail: {applied[-1] if applied else None}")
    newly_applied = apply_migrations(connection)
    if newly_applied:
        raise RuntimeError(
            "P6-T05 must not re-apply migration 14 or advance schema: "
            f"applied={[migration.version for migration in newly_applied]}"
        )

    eligible = plan.eligible_item_ids
    protected_before = protected_template_selections(connection, eligible)
    placeholders = ",".join("?" for _ in eligible)
    template_count_before = int(
        connection.execute(
            f"SELECT COUNT(*) FROM item_templates WHERE item_id IN ({placeholders})", eligible
        ).fetchone()[0]
    )
    stats_count_before = int(
        connection.execute(
            f"SELECT COUNT(*) FROM item_stat_modifiers WHERE item_id IN ({placeholders})", eligible
        ).fetchone()[0]
    )
    observations_before = int(
        connection.execute("SELECT COUNT(*) FROM source_observations").fetchone()[0]
    )

    first = import_octo_itemcache_slice(connection, source_path=cache_path, item_ids=eligible)
    if first.rows_accepted != len(eligible) or first.rows_skipped != 0:
        raise RuntimeError(
            "Incremental import no longer matches the plan: "
            f"accepted={first.rows_accepted} skipped={first.rows_skipped}"
        )
    first_batch_id = attach_promotion_context(
        connection, source_revision=str(first.source_revision), plan=plan, phase=phase
    )
    if protected_template_selections(connection, eligible) != protected_before:
        raise RuntimeError("P6-T05 changed a protected manual/custom template selection")
    if schema_version(connection) != TARGET_MIGRATION:
        raise RuntimeError("P6-T05 changed schema migration during incremental import")

    template_count_after = int(
        connection.execute(
            f"SELECT COUNT(*) FROM item_templates WHERE item_id IN ({placeholders})", eligible
        ).fetchone()[0]
    )
    if template_count_after != len(eligible):
        raise RuntimeError("Not every eligible canonical identity has a materialized template row")
    stats_count_after = int(
        connection.execute(
            f"SELECT COUNT(*) FROM item_stat_modifiers WHERE item_id IN ({placeholders})", eligible
        ).fetchone()[0]
    )
    domain_before_replay = [
        tuple(row)
        for row in connection.execute(
            f"SELECT * FROM item_templates WHERE item_id IN ({placeholders}) ORDER BY item_id",
            eligible,
        ).fetchall()
    ]
    stats_before_replay = [
        tuple(row)
        for row in connection.execute(
            f"""
            SELECT item_id, slot_index, stat_type, stat_value
            FROM item_stat_modifiers
            WHERE item_id IN ({placeholders})
            ORDER BY item_id, slot_index
            """,
            eligible,
        ).fetchall()
    ]
    observations_after_first = int(
        connection.execute("SELECT COUNT(*) FROM source_observations").fetchone()[0]
    )

    second = import_octo_itemcache_slice(connection, source_path=cache_path, item_ids=eligible)
    second_batch_id = attach_promotion_context(
        connection,
        source_revision=str(second.source_revision),
        plan=plan,
        phase=f"{phase}_idempotence_replay",
    )
    if (second.rows_inserted, second.rows_updated) != (0, 0):
        raise RuntimeError(
            "Repeated P6-T05 import changed canonical projection: "
            f"inserted={second.rows_inserted} updated={second.rows_updated}"
        )
    observation_count_after_replay = int(
        connection.execute("SELECT COUNT(*) FROM source_observations").fetchone()[0]
    )
    if observation_count_after_replay != observations_after_first:
        raise RuntimeError("Repeated P6-T05 import duplicated source observations")
    domain_after_replay = [
        tuple(row)
        for row in connection.execute(
            f"SELECT * FROM item_templates WHERE item_id IN ({placeholders}) ORDER BY item_id",
            eligible,
        ).fetchall()
    ]
    stats_after_replay = [
        tuple(row)
        for row in connection.execute(
            f"""
            SELECT item_id, slot_index, stat_type, stat_value
            FROM item_stat_modifiers
            WHERE item_id IN ({placeholders})
            ORDER BY item_id, slot_index
            """,
            eligible,
        ).fetchall()
    ]
    if domain_after_replay != domain_before_replay or stats_after_replay != stats_before_replay:
        raise RuntimeError("Repeated P6-T05 import changed materialized template/stat rows")
    if protected_template_selections(connection, eligible) != protected_before:
        raise RuntimeError("P6-T05 replay changed a protected selection")
    if apply_migrations(connection):
        raise RuntimeError("Repeated P6-T05 validation unexpectedly found a schema migration")
    if schema_version(connection) != TARGET_MIGRATION:
        raise RuntimeError("P6-T05 replay changed schema migration")

    query_results = query_item_templates(connection, limit=1000)
    if not query_results or not any(result.trace for result in query_results):
        raise RuntimeError("Migration-14 item-template query/provenance surface is not usable")

    representative_ids = tuple(
        dict.fromkeys(
            (
                eligible[0],
                eligible[len(eligible) // 2],
                eligible[-1],
            )
        )
    )
    representative: list[dict[str, Any]] = []
    for item_id in representative_ids:
        template = connection.execute(
            """
            SELECT item_id, class_id, subclass_id, quality, inventory_type, item_level,
                   required_level, armor, max_durability
            FROM item_templates
            WHERE item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if template is None:
            raise RuntimeError(f"Representative promoted item {item_id} has no template row")
        stats = connection.execute(
            """
            SELECT slot_index, stat_type, stat_value
            FROM item_stat_modifiers
            WHERE item_id = ?
            ORDER BY slot_index
            """,
            (item_id,),
        ).fetchall()
        representative.append(
            {
                "item_id": item_id,
                "template": dict(template),
                "stats": [dict(row) for row in stats],
            }
        )

    assert_integrity(connection)
    return {
        "first_import": first.to_dict(),
        "second_import": second.to_dict(),
        "first_import_batch_id": first_batch_id,
        "second_import_batch_id": second_batch_id,
        "eligible_item_count": len(eligible),
        "already_current_noop_count": len(plan.already_current_noops),
        "item_templates_promoted": len(eligible),
        "item_stat_modifiers_promoted": stats_count_after,
        "item_templates_new_rows": template_count_after - template_count_before,
        "item_stat_modifiers_net_new_rows": stats_count_after - stats_count_before,
        "source_observations_added_first_pass": observations_after_first - observations_before,
        "protected_selection_count": len(protected_before),
        "representative_queries": representative,
        "foreign_key_check": [],
        "integrity_check": "ok",
        "migration": schema_version(connection),
    }


def validate_shadow(
    args: argparse.Namespace, plan: IncrementalPromotionPlan, cache_path: Path
) -> dict[str, Any]:
    canonical = args.db.resolve()
    baseline_hash = assert_canonical_baseline(canonical)
    validation_db = args.validation_db.resolve()
    validation_db.parent.mkdir(parents=True, exist_ok=True)
    if validation_db.exists():
        validation_db.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(validation_db) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    shutil.copy2(canonical, validation_db)
    if sha256_file(validation_db) != baseline_hash:
        raise RuntimeError("Disposable validation copy is not byte-identical to canonical baseline")

    connection = open_connection(validation_db)
    try:
        details = validate_incremental_database(
            connection, plan=plan, cache_path=cache_path, phase="shadow_validation"
        )
        connection.commit()
    finally:
        connection.close()
    if sha256_file(canonical) != baseline_hash:
        raise RuntimeError("Canonical DB changed during read-only shadow validation")
    validation_hash = sha256_file(validation_db)
    result = {
        "plan_revision": plan.plan_revision,
        "canonical_sha256_before": baseline_hash,
        "canonical_db_unchanged": True,
        "validation_db": str(validation_db),
        "validation_db_sha256": validation_hash,
        **details,
    }
    progress("P6_T05_SHADOW_VALIDATION_OK")
    progress(f"eligible_item_count={len(plan.eligible_item_ids)}")
    progress(f"already_current_noop_count={len(plan.already_current_noops)}")
    progress("canonical_db_unchanged=true")
    return result


def create_guarded_backup(canonical: Path, backup: Path) -> sqlite3.Connection:
    """Windows-safe D-029 copy-before-lock protocol, now anchored to migration 14."""

    baseline_hash = assert_canonical_baseline(canonical)
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        backup.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(backup) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    source_stat_before = canonical.stat()
    connection = open_connection(canonical)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        data_version_before = int(connection.execute("PRAGMA data_version").fetchone()[0])
        shutil.copy2(canonical, backup)
        backup_hash = sha256_file(backup)
        if backup_hash != baseline_hash:
            raise RuntimeError(
                "D-029 backup verification failed before mutation: "
                f"expected={baseline_hash} actual={backup_hash}"
            )
        source_stat_after_copy = canonical.stat()
        data_version_after_copy = int(connection.execute("PRAGMA data_version").fetchone()[0])
        if (
            data_version_after_copy != data_version_before
            or source_stat_after_copy.st_size != source_stat_before.st_size
            or source_stat_after_copy.st_mtime_ns != source_stat_before.st_mtime_ns
        ):
            raise RuntimeError("Canonical DB changed while D-029 backup was being created")
        assert_no_sidecars(canonical)
        connection.execute("BEGIN IMMEDIATE")
        data_version_locked = int(connection.execute("PRAGMA data_version").fetchone()[0])
        source_stat_locked = canonical.stat()
        if (
            data_version_locked != data_version_before
            or source_stat_locked.st_size != source_stat_before.st_size
            or source_stat_locked.st_mtime_ns != source_stat_before.st_mtime_ns
        ):
            raise RuntimeError("Canonical DB changed before promotion write lock was secured")
        if schema_version(connection) != TARGET_MIGRATION:
            raise RuntimeError("Canonical migration changed before P6-T05 promotion")
        return connection
    except Exception:
        connection.rollback()
        connection.close()
        raise


def restore_backup(canonical: Path, backup: Path) -> None:
    if not backup.is_file():
        raise RuntimeError("Cannot restore failed P6-T05 promotion: D-029 backup is missing")
    if sha256_file(backup) != EXPECTED_BASELINE_SHA256:
        raise RuntimeError("Cannot restore failed P6-T05 promotion: backup hash is not baseline")
    for sidecar in sqlite_sidecars(canonical):
        sidecar.unlink()
    shutil.copy2(backup, canonical)
    restored = sha256_file(canonical)
    if restored != EXPECTED_BASELINE_SHA256:
        raise RuntimeError(f"Rollback copy verification failed: {restored}")


def promote_canonical(
    args: argparse.Namespace,
    plan: IncrementalPromotionPlan,
    cache_path: Path,
    shadow: dict[str, Any],
) -> dict[str, Any]:
    canonical = args.db.resolve()
    backup = args.backup.resolve()
    if (
        shadow.get("plan_revision") != plan.plan_revision
        or not shadow.get("canonical_db_unchanged")
    ):
        raise RuntimeError("Shadow validation does not authorize the current promotion plan")

    connection: sqlite3.Connection | None = None
    backup_ready = False
    try:
        progress("[promote] replacing D-029 backup with exact migration-14 pre-promotion bytes")
        connection = create_guarded_backup(canonical, backup)
        backup_ready = True
        if sha256_file(backup) != EXPECTED_BASELINE_SHA256:
            raise RuntimeError("D-029 backup changed unexpectedly before canonical mutation")
        details = validate_incremental_database(
            connection, plan=plan, cache_path=cache_path, phase="canonical_promotion"
        )
        connection.commit()
        connection.close()
        connection = None

        assert_no_sidecars(canonical)
        promoted_hash = sha256_file(canonical)
        if promoted_hash == EXPECTED_BASELINE_SHA256:
            raise RuntimeError("P6-T05 promotion produced no byte-level canonical evolution")
        verify = open_connection(canonical)
        try:
            if schema_version(verify) != TARGET_MIGRATION:
                raise RuntimeError("Canonical DB did not remain migration 14")
            if apply_migrations(verify):
                raise RuntimeError("Canonical DB exposes an unexpected post-P6-T05 migration")
            assert_integrity(verify)
        finally:
            verify.close()
        if sha256_file(backup) != EXPECTED_BASELINE_SHA256:
            raise RuntimeError("D-029 rollback snapshot changed after successful promotion")

        result = {
            "plan_revision": plan.plan_revision,
            "backup_path": str(backup),
            "backup_sha256": EXPECTED_BASELINE_SHA256,
            "canonical_sha256_before": EXPECTED_BASELINE_SHA256,
            "canonical_sha256_after": promoted_hash,
            "canonical_migration_after": TARGET_MIGRATION,
            "rollback_available": True,
            **details,
        }
        progress("P6_T05_CANONICAL_PROMOTION_OK")
        progress(f"backup_sha256={EXPECTED_BASELINE_SHA256}")
        progress(f"canonical_sha256={promoted_hash}")
        progress(f"canonical_migration={TARGET_MIGRATION}")
        progress("rollback_available=true")
        return result
    except Exception:
        if connection is not None:
            connection.rollback()
            connection.close()
        if backup_ready:
            progress("[rollback] P6-T05 gate failed; restoring exact migration-14 pre-promotion DB")
            restore_backup(canonical, backup)
            progress("P6_T05_ROLLBACK_COMPLETE")
        else:
            assert_canonical_baseline(canonical)
            progress("P6_T05_PROMOTION_ABORTED_BEFORE_MUTATION")
        raise



def verify_baseline(args: argparse.Namespace) -> dict[str, Any]:
    database = args.db.resolve()
    digest = assert_canonical_baseline(database)
    uri = f"file:{database.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        migration = schema_version(connection)
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = [
            str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()
        ]
    if migration != EXPECTED_BASELINE_MIGRATION:
        raise RuntimeError(
            "Unexpected canonical migration: "
            f"expected={EXPECTED_BASELINE_MIGRATION} actual={migration}"
        )
    if foreign_keys:
        raise RuntimeError(f"PRAGMA foreign_key_check failed: {foreign_keys[:10]}")
    if integrity != ["ok"]:
        raise RuntimeError(f"PRAGMA integrity_check failed: {integrity}")
    result = {
        "canonical_sha256": digest,
        "canonical_migration": migration,
        "foreign_key_check": [],
        "integrity_check": "ok",
    }
    progress("P6_CANONICAL_BASELINE_OK")
    progress(f"canonical_sha256={digest}")
    progress(f"canonical_migration={migration}")
    progress("foreign_key_check=[]")
    progress("integrity_check=ok")
    return result



def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=("verify-baseline", "plan", "validate", "promote"),
        nargs="?",
        default="validate",
    )
    parser.add_argument(
        "--baseline", choices=("current", "p6-t05-input"), default="current"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    parser.add_argument("--validation-db", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--legacy-ledger", type=Path, default=DEFAULT_LEGACY_LEDGER)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--p6-t02-report", type=Path, action="append", default=[])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--itemcache", type=Path)
    parser.add_argument("--locale", default="enUS")
    parser.add_argument("--min-refresh-proven", type=int, default=MIN_NEW_REFRESH_PROVEN)
    args = parser.parse_args(argv)
    defaults = default_artifacts_for_mode(args.baseline)
    if args.validation_db is None:
        args.validation_db = defaults[0]
    if args.plan is None:
        args.plan = defaults[1]
    if args.campaign is None:
        args.campaign = defaults[2]
    args.report_slug = defaults[3]
    if args.min_refresh_proven < MIN_NEW_REFRESH_PROVEN:
        parser.error(
            f"--min-refresh-proven cannot weaken the bounded validation target below "
            f"{MIN_NEW_REFRESH_PROVEN}"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_runtime_baseline(baseline_for_mode(args.baseline))
    try:
        if args.mode == "verify-baseline":
            verify_baseline(args)
            return 0
        plan, cache_path, coverage_counts = build_current_plan(args)
        if args.mode == "plan":
            progress("P6_T05_PLAN_OK")
            return 0

        shadow = validate_shadow(args, plan, cache_path)
        report: dict[str, Any] = {
            "report_version": 1,
            "mode": args.mode,
            "created_utc": timestamp(),
            "plan": plan.to_json(),
            "coverage_counts": coverage_counts,
            "shadow_validation": shadow,
        }
        if args.mode == "promote":
            report["canonical_promotion"] = promote_canonical(args, plan, cache_path, shadow)

        report_path = (
            args.report_dir.resolve()
            / f"{args.report_slug}_{args.mode}_{timestamp()}.json"
        )
        write_json(report_path, report)
        progress(f"report={report_path}")
        if args.mode == "validate":
            progress("P6_T05_LOCAL_VALIDATION_READY_FOR_PROMOTION")
        else:
            progress("P6_T05_LOCAL_VALIDATION_COMPLETE")
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, json.JSONDecodeError) as exc:
        progress(f"P6_T05_VALIDATION_FAILED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
