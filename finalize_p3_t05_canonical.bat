@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "P3_ROOT=%CD%"
if not exist "%P3_ROOT%\pyproject.toml" set "P3_ROOT=%~dp0"

set "P3_SELF=%~f0"
set "P3_PS1=%TEMP%\OctoGameBDD_P3T05_FINAL_%RANDOM%_%RANDOM%.ps1"
set "P3_PY=%TEMP%\OctoGameBDD_P3T05_FINAL_%RANDOM%_%RANDOM%.py"

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Windows PowerShell is required but was not found.
    echo [FAIL] Nothing was changed.
    pause
    exit /b 2
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$lines = Get-Content -LiteralPath $env:P3_SELF; $ps = @(); $py = @(); foreach ($line in $lines) { if ($line.StartsWith('::PS::')) { $ps += $line.Substring(6) } elseif ($line.StartsWith('::PY::')) { $py += $line.Substring(6) } }; Set-Content -LiteralPath $env:P3_PS1 -Value $ps -Encoding UTF8; Set-Content -LiteralPath $env:P3_PY -Value $py -Encoding UTF8"
if errorlevel 1 (
    echo [FAIL] Could not extract the embedded finalization helpers.
    del /q "%P3_PS1%" "%P3_PY%" >nul 2>&1
    pause
    exit /b 2
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$tokens=$null; $errors=$null; $ast=[System.Management.Automation.Language.Parser]::ParseFile($env:P3_PS1,[ref]$tokens,[ref]$errors); if ($errors.Count -gt 0) { foreach ($e in $errors) { Write-Host ('[FAIL] PowerShell syntax: ' + $e.Message) }; exit 3 }"
if errorlevel 1 (
    echo [FAIL] Embedded PowerShell helper did not pass syntax preflight.
    del /q "%P3_PS1%" "%P3_PY%" >nul 2>&1
    pause
    exit /b 3
)

python -m py_compile "%P3_PY%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Embedded Python helper did not pass syntax preflight.
    del /q "%P3_PS1%" "%P3_PY%" >nul 2>&1
    pause
    exit /b 4
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%P3_PS1%" -ProjectRoot "%P3_ROOT%" -HelperPath "%P3_PY%"
set "P3_RC=%ERRORLEVEL%"

del /q "%P3_PS1%" "%P3_PY%" >nul 2>&1

echo.
if "%P3_RC%"=="0" (
    echo [PASS] P3-T05 canonical finalization finished successfully.
) else (
    echo [FAIL] P3-T05 canonical finalization stopped with errors. See the log path printed above.
)
echo [INFO] This window will remain open so you can read the summary.
pause
exit /b %P3_RC%
::PS::param(
::PS::    [Parameter(Mandatory = $true)][string]$ProjectRoot,
::PS::    [Parameter(Mandatory = $true)][string]$HelperPath
::PS::)
::PS::
::PS::$ErrorActionPreference = "Stop"
::PS::$ProgressPreference = "SilentlyContinue"
::PS::$env:PYTHONUNBUFFERED = "1"
::PS::
::PS::$Root = (Resolve-Path -LiteralPath $ProjectRoot).Path
::PS::Set-Location -LiteralPath $Root
::PS::
::PS::if (-not (Test-Path -LiteralPath (Join-Path $Root "pyproject.toml") -PathType Leaf) -or
::PS::    -not (Test-Path -LiteralPath (Join-Path $Root "scripts\validate_p3_t05.py") -PathType Leaf) -or
::PS::    -not (Test-Path -LiteralPath (Join-Path $Root "src\octogamedb\importers\quest_item_facts.py") -PathType Leaf)) {
::PS::    Write-Host "[FAIL] Place this BAT in the OctoGameBDD project root, or launch it while the current directory is that root."
::PS::    exit 2
::PS::}
::PS::
::PS::$ValidationRoot = Join-Path $Root "data\validation"
::PS::New-Item -ItemType Directory -Force -Path $ValidationRoot | Out-Null
::PS::$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
::PS::$RunDir = Join-Path $ValidationRoot ("p3_t05_canonical_finalize_" + $Stamp)
::PS::New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
::PS::$LogFile = Join-Path $RunDir "P3-T05-canonical-finalization.log"
::PS::Set-Content -LiteralPath $LogFile -Value "" -Encoding UTF8
::PS::
::PS::function Write-Log {
::PS::    param([ValidateSet("INFO", "PASS", "FAIL")][string]$Level, [string]$Message)
::PS::    $line = "[$Level] $Message"
::PS::    Write-Host $line
::PS::    Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8
::PS::}
::PS::
::PS::function Write-Raw {
::PS::    param([string]$Message)
::PS::    Write-Host $Message
::PS::    Add-Content -LiteralPath $script:LogFile -Value $Message -Encoding UTF8
::PS::}
::PS::
::PS::function Invoke-Native {
::PS::    param(
::PS::        [string]$Label,
::PS::        [string]$FilePath,
::PS::        [string[]]$Arguments
::PS::    )
::PS::    Write-Log "INFO" $Label
::PS::    Write-Log "INFO" ("COMMAND: " + $FilePath + " " + ($Arguments -join " "))
::PS::    $savedPreference = $ErrorActionPreference
::PS::    $global:LASTEXITCODE = 0
::PS::    try {
::PS::        $ErrorActionPreference = "Continue"
::PS::        $nativeOutput = @(& $FilePath @Arguments 2>&1)
::PS::        $code = $LASTEXITCODE
::PS::    }
::PS::    finally {
::PS::        $ErrorActionPreference = $savedPreference
::PS::    }
::PS::    foreach ($line in $nativeOutput) {
::PS::        Write-Raw ([string]$line)
::PS::    }
::PS::    if ($code -ne 0) {
::PS::        throw "${Label} failed with exit code $code"
::PS::    }
::PS::    Write-Log "PASS" $Label
::PS::}
::PS::
::PS::function Get-Sha256 {
::PS::    param([string]$Path)
::PS::    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
::PS::        throw "File is missing: $Path"
::PS::    }
::PS::    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
::PS::}
::PS::
::PS::function Find-ValidatedRun {
::PS::    param([string]$RootPath)
::PS::    $dirs = @(Get-ChildItem -LiteralPath $RootPath -Directory -Filter "p3_t05_validation_*" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
::PS::    foreach ($dir in $dirs) {
::PS::        $log = Join-Path $dir.FullName "P3-T05-validation.log"
::PS::        if (-not (Test-Path -LiteralPath $log -PathType Leaf)) { continue }
::PS::        $text = Get-Content -LiteralPath $log -Raw -ErrorAction SilentlyContinue
::PS::        if (-not $text.Contains("[PASS] P3-T05 NON-DESTRUCTIVE LEVEL-2 VALIDATION COMPLETE: all remaining read-only/disposable checks passed.")) { continue }
::PS::        $required = @(
::PS::            "canonical-baseline.json",
::PS::            "tortoise-full-a.json",
::PS::            "tortoise-full-check.json",
::PS::            "live.json",
::PS::            "octodb.json",
::PS::            "cmangos.json",
::PS::            "source-check.json",
::PS::            "p3_t05_report.json",
::PS::            "p3_t05_audit.json"
::PS::        )
::PS::        $missing = @()
::PS::        foreach ($name in $required) {
::PS::            if (-not (Test-Path -LiteralPath (Join-Path $dir.FullName $name) -PathType Leaf)) { $missing += $name }
::PS::        }
::PS::        if ($missing.Count -eq 0) { return $dir.FullName }
::PS::    }
::PS::    throw "No successful P3-T05 non-destructive Level-2 run with all required artifacts was found under data\validation. Run validate_p3_t05_local_v5_ready.bat first."
::PS::}
::PS::
::PS::$Succeeded = $false
::PS::$MutationStarted = $false
::PS::$CanonicalBefore = $null
::PS::$CanonicalDb = Join-Path $Root "data\generated\octogamedb.sqlite3"
::PS::$CanonicalBackup = Join-Path $Root "data\generated\octogamedb_bak.sqlite3"
::PS::
::PS::try {
::PS::    Write-Log "INFO" "P3-T05 canonical finalization started."
::PS::    Write-Log "INFO" "Project root: $Root"
::PS::    Write-Log "INFO" "Finalization run directory: $RunDir"
::PS::    Write-Log "INFO" "This script DOES modify the real canonical DB, but only after validating the previously successful Level-2 run and the migration-9 baseline hash."
::PS::    Write-Log "INFO" "If any post-write check fails, the script attempts to restore the exact migration-9 backup automatically."
::PS::
::PS::    $pythonCommand = Get-Command python -ErrorAction Stop
::PS::    $Python = $pythonCommand.Source
::PS::    Write-Log "PASS" "Python found: $Python"
::PS::    $env:PYTHONPATH = Join-Path $Root "src"
::PS::
::PS::    $ValidatedRun = Find-ValidatedRun $ValidationRoot
::PS::    Write-Log "PASS" "Using newest complete successful non-destructive validation run: $ValidatedRun"
::PS::
::PS::    $PreflightReport = Join-Path $RunDir "canonical-preflight.json"
::PS::    Invoke-Native "Verify validated snapshots, disposable acceptance results and current migration-9 canonical baseline" $Python @(
::PS::        $HelperPath, "verify-run",
::PS::        "--run-dir", $ValidatedRun,
::PS::        "--canonical", $CanonicalDb,
::PS::        "--output", $PreflightReport
::PS::    )
::PS::    $Preflight = Get-Content -LiteralPath $PreflightReport -Raw | ConvertFrom-Json
::PS::    $ExpectedBaseline = ([string]$Preflight.baseline_sha256).ToLowerInvariant()
::PS::    if ([string]::IsNullOrWhiteSpace($ExpectedBaseline)) { throw "Preflight did not return a baseline SHA256." }
::PS::
::PS::    $CanonicalBefore = Get-Sha256 $CanonicalDb
::PS::    if ($CanonicalBefore -ne $ExpectedBaseline) {
::PS::        throw "Real canonical DB no longer matches the validated migration-9 baseline: expected=$ExpectedBaseline actual=$CanonicalBefore"
::PS::    }
::PS::    Write-Log "PASS" "Real canonical DB still matches validated migration-9 SHA256=$CanonicalBefore"
::PS::
::PS::    $Tortoise = Join-Path $ValidatedRun "tortoise-full-a.json"
::PS::    $Live = Join-Path $ValidatedRun "live.json"
::PS::    $OctoDb = Join-Path $ValidatedRun "octodb.json"
::PS::    $Cmangos = Join-Path $ValidatedRun "cmangos.json"
::PS::    $ValidatedReport = Join-Path $ValidatedRun "p3_t05_report.json"
::PS::    $ValidatedAudit = Join-Path $ValidatedRun "p3_t05_audit.json"
::PS::    $CanonicalReport = Join-Path $RunDir "p3_t05_canonical_report.json"
::PS::
::PS::    Write-Log "INFO" "Beginning the deliberate D-029 canonical evolution from migration 9 to migration 10."
::PS::    $MutationStarted = $true
::PS::    Invoke-Native "Apply P3-T05 to the REAL canonical DB with mandatory D-029 backup and second-pass idempotence" $Python @(
::PS::        "scripts\validate_p3_t05.py", "apply",
::PS::        "--database", $CanonicalDb,
::PS::        "--snapshot", $Tortoise,
::PS::        "--snapshot", $Live,
::PS::        "--snapshot", $OctoDb,
::PS::        "--snapshot", $Cmangos,
::PS::        "--twice", "--canonical",
::PS::        "--output", $CanonicalReport
::PS::    )
::PS::
::PS::    if (-not (Test-Path -LiteralPath $CanonicalBackup -PathType Leaf)) {
::PS::        throw "Canonical mode did not create data\generated\octogamedb_bak.sqlite3"
::PS::    }
::PS::    $BackupHash = Get-Sha256 $CanonicalBackup
::PS::    if ($BackupHash -ne $CanonicalBefore) {
::PS::        throw "D-029 backup is not byte-identical to the validated migration-9 canonical DB: expected=$CanonicalBefore actual=$BackupHash"
::PS::    }
::PS::    Write-Log "PASS" "D-029 backup verified byte-identical to pre-migration canonical SHA256=$BackupHash"
::PS::
::PS::    Invoke-Native "Run project read-only check on the REAL migration-10 canonical DB" $Python @(
::PS::        "scripts\validate_p3_t05.py", "check", "--database", $CanonicalDb
::PS::    )
::PS::
::PS::    $FinalReport = Join-Path $RunDir "canonical-final-check.json"
::PS::    Invoke-Native "Compare REAL canonical result with the fully validated disposable result" $Python @(
::PS::        $HelperPath, "final-check",
::PS::        "--database", $CanonicalDb,
::PS::        "--backup", $CanonicalBackup,
::PS::        "--expected-backup-sha256", $CanonicalBefore,
::PS::        "--validated-report", $ValidatedReport,
::PS::        "--canonical-report", $CanonicalReport,
::PS::        "--validated-audit", $ValidatedAudit,
::PS::        "--output", $FinalReport
::PS::    )
::PS::
::PS::    foreach ($questId in @("818", "815", "40788", "40675")) {
::PS::        Invoke-Native ("Read-model smoke check for representative quest " + $questId) $Python @(
::PS::            "scripts\validate_p3_t05.py", "quest", "--database", $CanonicalDb, "--quest-id", $questId
::PS::        )
::PS::    }
::PS::
::PS::    $CanonicalAfter = Get-Sha256 $CanonicalDb
::PS::    if ($CanonicalAfter -eq $CanonicalBefore) {
::PS::        throw "Canonical DB hash did not change after a reported successful migration 9 -> 10."
::PS::    }
::PS::    if ((Get-Sha256 $CanonicalBackup) -ne $CanonicalBefore) {
::PS::        throw "D-029 backup changed after final checks."
::PS::    }
::PS::
::PS::    $Succeeded = $true
::PS::    Write-Log "PASS" "P3-T05 REAL CANONICAL FINALIZATION COMPLETE."
::PS::    Write-Log "PASS" "Canonical DB is now migration 10 and passed all post-write checks."
::PS::    Write-Log "PASS" "Migration-9 rollback backup remains available at: $CanonicalBackup"
::PS::    Write-Log "INFO" "Canonical SHA256 before: $CanonicalBefore"
::PS::    Write-Log "INFO" "Canonical SHA256 after : $CanonicalAfter"
::PS::}
::PS::catch {
::PS::    Write-Log "FAIL" ("P3-T05 canonical finalization stopped: " + $_.Exception.Message)
::PS::    Write-Raw ("Exception type: " + $_.Exception.GetType().FullName)
::PS::    if ($_.ScriptStackTrace) {
::PS::        Write-Raw "Stack trace:"
::PS::        Write-Raw $_.ScriptStackTrace
::PS::    }
::PS::
::PS::    if ($MutationStarted -and $CanonicalBefore) {
::PS::        try {
::PS::            if (Test-Path -LiteralPath $CanonicalBackup -PathType Leaf) {
::PS::                $RollbackHash = Get-Sha256 $CanonicalBackup
::PS::                if ($RollbackHash -eq $CanonicalBefore) {
::PS::                    Write-Log "INFO" "A mutation had started. Restoring the verified migration-9 D-029 backup automatically."
::PS::                    Copy-Item -LiteralPath $CanonicalBackup -Destination $CanonicalDb -Force
::PS::                    $RestoredHash = Get-Sha256 $CanonicalDb
::PS::                    if ($RestoredHash -eq $CanonicalBefore) {
::PS::                        Write-Log "PASS" "Rollback succeeded. Real canonical DB is restored byte-for-byte to the validated migration-9 baseline."
::PS::                    }
::PS::                    else {
::PS::                        Write-Log "FAIL" "Rollback copy completed but restored canonical hash is wrong: expected=$CanonicalBefore actual=$RestoredHash"
::PS::                    }
::PS::                }
::PS::                else {
::PS::                    Write-Log "FAIL" "Automatic rollback refused because the backup hash does not match the pre-mutation canonical hash."
::PS::                }
::PS::            }
::PS::            else {
::PS::                Write-Log "FAIL" "Automatic rollback cannot run because the D-029 backup file is missing."
::PS::            }
::PS::        }
::PS::        catch {
::PS::            Write-Log "FAIL" ("Automatic rollback itself failed: " + $_.Exception.Message)
::PS::        }
::PS::    }
::PS::}
::PS::finally {
::PS::    Write-Host ""
::PS::    Write-Log "INFO" "Full log: $LogFile"
::PS::    Write-Log "INFO" "Finalization artifacts: $RunDir"
::PS::    if ($Succeeded) {
::PS::        Write-Host ""
::PS::        Write-Host "[PASS] SUMMARY: P3-T05 canonical migration 9 -> 10 completed and verified."
::PS::        Write-Host "[PASS] Send this log back for project closeout: $LogFile"
::PS::        exit 0
::PS::    }
::PS::    else {
::PS::        Write-Host ""
::PS::        Write-Host "[FAIL] SUMMARY: P3-T05 canonical finalization did not complete successfully."
::PS::        Write-Host "[FAIL] Send this log back: $LogFile"
::PS::        exit 1
::PS::    }
::PS::}
::PY::from __future__ import annotations
::PY::
::PY::import argparse
::PY::import hashlib
::PY::import json
::PY::import sqlite3
::PY::from pathlib import Path
::PY::
::PY::PASS_MARKER = "[PASS] P3-T05 NON-DESTRUCTIVE LEVEL-2 VALIDATION COMPLETE: all remaining read-only/disposable checks passed."
::PY::P3_FACT_KEYS = (
::PY::    "quest_required_item",
::PY::    "quest_required_item_set",
::PY::    "quest_required_source",
::PY::    "quest_required_source_set",
::PY::    "quest_provided_item",
::PY::    "quest_provided_item_count",
::PY::    "quest_provided_item_set",
::PY::    "quest_reward_item",
::PY::    "quest_reward_item_set",
::PY::    "quest_choice_reward_item",
::PY::    "quest_choice_reward_item_set",
::PY::)
::PY::
::PY::
::PY::def sha256_file(path: str | Path) -> str:
::PY::    h = hashlib.sha256()
::PY::    with Path(path).open("rb") as handle:
::PY::        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
::PY::            h.update(chunk)
::PY::    return h.hexdigest()
::PY::
::PY::
::PY::def load_json(path: str | Path) -> dict:
::PY::    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
::PY::    if not isinstance(value, dict):
::PY::        raise RuntimeError(f"expected JSON object: {path}")
::PY::    return value
::PY::
::PY::
::PY::def write_json(path: str | Path, value: dict) -> None:
::PY::    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
::PY::
::PY::
::PY::def assert_report(report: dict, label: str) -> None:
::PY::    checks = report.get("checks")
::PY::    if not isinstance(checks, dict):
::PY::        raise RuntimeError(f"{label}: missing checks")
::PY::    if checks.get("schema_version") != 10 or checks.get("p3_t05_schema_ready") is not True:
::PY::        raise RuntimeError(f"{label}: schema is not P3-T05 migration 10")
::PY::    if checks.get("foreign_key_check") != []:
::PY::        raise RuntimeError(f"{label}: foreign_key_check is not empty")
::PY::    if checks.get("integrity_check") != ["ok"]:
::PY::        raise RuntimeError(f"{label}: integrity_check is not ['ok']")
::PY::    counts = checks.get("canonical_counts")
::PY::    if not isinstance(counts, dict) or any(int(counts.get(k, 0)) <= 0 for k in (
::PY::        "required_item", "required_source", "provided_item", "reward_item", "choice_reward_item"
::PY::    )):
::PY::        raise RuntimeError(f"{label}: canonical family counts are incomplete: {counts}")
::PY::
::PY::    second = report.get("second")
::PY::    if not isinstance(second, dict):
::PY::        raise RuntimeError(f"{label}: missing mandatory second pass")
::PY::    if second.get("status") != "succeeded" or int(second.get("error_count", -1)) != 0:
::PY::        raise RuntimeError(f"{label}: second pass did not succeed cleanly")
::PY::    if int(second.get("rows_inserted", -1)) != 0 or int(second.get("rows_updated", -1)) != 0:
::PY::        raise RuntimeError(f"{label}: second pass was not idempotent")
::PY::    details = second.get("details")
::PY::    if not isinstance(details, dict) or int(details.get("canonical_rows_deleted", -1)) != 0:
::PY::        raise RuntimeError(f"{label}: second pass deleted canonical rows")
::PY::    if details.get("ambiguous_same_priority") not in ([], None):
::PY::        raise RuntimeError(f"{label}: same-priority ambiguity remains")
::PY::    if details.get("anomalies") not in ([], None):
::PY::        raise RuntimeError(f"{label}: reconciliation anomalies remain")
::PY::
::PY::
::PY::def verify_audit(audit: dict, label: str) -> None:
::PY::    if audit.get("schema_version") != 10:
::PY::        raise RuntimeError(f"{label}: audit schema_version is not 10")
::PY::    if audit.get("foreign_key_check") != [] or audit.get("integrity_check") != ["ok"]:
::PY::        raise RuntimeError(f"{label}: audit FK/integrity failed")
::PY::    if int(audit.get("failed_import_batches", -1)) != 0:
::PY::        raise RuntimeError(f"{label}: failed P3-T05 import batches exist")
::PY::    if int(audit.get("anomaly_count", -1)) != 0 or int(audit.get("ambiguous_same_priority_count", -1)) != 0:
::PY::        raise RuntimeError(f"{label}: anomalies/ambiguities remain")
::PY::    if int(audit.get("invalid_required_quantity_count", -1)) != 0:
::PY::        raise RuntimeError(f"{label}: invalid required quantities exist")
::PY::    gaps = audit.get("provenance_gaps")
::PY::    if not isinstance(gaps, dict) or any(int(v) != 0 for v in gaps.values()):
::PY::        raise RuntimeError(f"{label}: canonical provenance gaps exist: {gaps}")
::PY::    if int(audit.get("reqsource_zero_observation_count", 0)) <= 0:
::PY::        raise RuntimeError(f"{label}: raw ReqSourceCount=0 provenance evidence is missing")
::PY::
::PY::
::PY::def cmd_verify_run(args: argparse.Namespace) -> int:
::PY::    run = Path(args.run_dir).resolve()
::PY::    log = run / "P3-T05-validation.log"
::PY::    if PASS_MARKER not in log.read_text(encoding="utf-8-sig", errors="replace"):
::PY::        raise RuntimeError("selected validation run lacks the final Level-2 PASS marker")
::PY::
::PY::    baseline = load_json(run / "canonical-baseline.json")
::PY::    if baseline.get("schema_version") != 9 or baseline.get("foreign_key_check") != [] or baseline.get("integrity_check") != ["ok"]:
::PY::        raise RuntimeError(f"validated canonical baseline is not a clean migration-9 DB: {baseline}")
::PY::    baseline_sha = str(baseline.get("sha256", "")).lower()
::PY::    if len(baseline_sha) != 64:
::PY::        raise RuntimeError("validated baseline SHA256 is missing/invalid")
::PY::    current_sha = sha256_file(args.canonical)
::PY::    if current_sha != baseline_sha:
::PY::        raise RuntimeError(f"current canonical hash differs from validated baseline: expected={baseline_sha} actual={current_sha}")
::PY::
::PY::    tortoise_check = load_json(run / "tortoise-full-check.json")
::PY::    tortoise_sha = sha256_file(run / "tortoise-full-a.json")
::PY::    if tortoise_sha != str(tortoise_check.get("first_sha256", "")).lower():
::PY::        raise RuntimeError("tortoise-full-a.json no longer matches the validated deterministic projection hash")
::PY::
::PY::    source_check = load_json(run / "source-check.json")
::PY::    sources = source_check.get("sources")
::PY::    if not isinstance(sources, dict):
::PY::        raise RuntimeError("source-check.json lacks sources")
::PY::    for key, filename in (("live", "live.json"), ("octodb", "octodb.json"), ("cmangos", "cmangos.json")):
::PY::        entry = sources.get(key)
::PY::        if not isinstance(entry, dict):
::PY::            raise RuntimeError(f"source-check.json lacks {key}")
::PY::        expected = str(entry.get("sha256", "")).lower()
::PY::        actual = sha256_file(run / filename)
::PY::        if expected != actual:
::PY::            raise RuntimeError(f"{filename} changed after Level-2 validation: expected={expected} actual={actual}")
::PY::
::PY::    validated_report = load_json(run / "p3_t05_report.json")
::PY::    assert_report(validated_report, "validated disposable report")
::PY::    validated_audit = load_json(run / "p3_t05_audit.json")
::PY::    verify_audit(validated_audit, "validated disposable audit")
::PY::
::PY::    payload = {
::PY::        "validated_run": str(run),
::PY::        "baseline_sha256": baseline_sha,
::PY::        "snapshot_sha256": {
::PY::            "tortoise": tortoise_sha,
::PY::            "live": sha256_file(run / "live.json"),
::PY::            "octodb": sha256_file(run / "octodb.json"),
::PY::            "cmangos": sha256_file(run / "cmangos.json"),
::PY::        },
::PY::        "canonical_counts": validated_report["checks"]["canonical_counts"],
::PY::        "reqsource_zero_observation_count": validated_audit.get("reqsource_zero_observation_count"),
::PY::        "unresolved_count": validated_audit.get("unresolved_count"),
::PY::    }
::PY::    write_json(args.output, payload)
::PY::    print(json.dumps(payload, sort_keys=True))
::PY::    return 0
::PY::
::PY::
::PY::def connect_ro(path: str | Path) -> sqlite3.Connection:
::PY::    p = Path(path).resolve()
::PY::    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
::PY::    conn.row_factory = sqlite3.Row
::PY::    return conn
::PY::
::PY::
::PY::def source_observation_counts(conn: sqlite3.Connection) -> dict[str, int]:
::PY::    placeholders = ",".join("?" for _ in P3_FACT_KEYS)
::PY::    rows = conn.execute(
::PY::        f"""
::PY::        SELECT ds.source_key, COUNT(*) AS observation_count
::PY::        FROM source_observations AS so
::PY::        JOIN observation_groups AS og ON og.id = so.observation_group_id
::PY::        JOIN data_sources AS ds ON ds.id = so.source_id
::PY::        WHERE og.fact_key IN ({placeholders})
::PY::        GROUP BY ds.source_key ORDER BY ds.source_key
::PY::        """,
::PY::        P3_FACT_KEYS,
::PY::    ).fetchall()
::PY::    return {str(r["source_key"]): int(r["observation_count"]) for r in rows}
::PY::
::PY::
::PY::def cmd_final_check(args: argparse.Namespace) -> int:
::PY::    expected_backup = args.expected_backup_sha256.lower()
::PY::    actual_backup = sha256_file(args.backup)
::PY::    if actual_backup != expected_backup:
::PY::        raise RuntimeError(f"D-029 backup hash mismatch: expected={expected_backup} actual={actual_backup}")
::PY::
::PY::    validated_report = load_json(args.validated_report)
::PY::    canonical_report = load_json(args.canonical_report)
::PY::    validated_audit = load_json(args.validated_audit)
::PY::    assert_report(validated_report, "validated disposable report")
::PY::    assert_report(canonical_report, "real canonical report")
::PY::    verify_audit(validated_audit, "validated disposable audit")
::PY::
::PY::    if validated_report["checks"]["canonical_counts"] != canonical_report["checks"]["canonical_counts"]:
::PY::        raise RuntimeError("real canonical family counts differ from the validated disposable result")
::PY::
::PY::    for pass_name in ("first", "second"):
::PY::        v = validated_report.get(pass_name, {})
::PY::        c = canonical_report.get(pass_name, {})
::PY::        vd = v.get("details", {}) if isinstance(v, dict) else {}
::PY::        cd = c.get("details", {}) if isinstance(c, dict) else {}
::PY::        if vd.get("source_revisions") != cd.get("source_revisions"):
::PY::            raise RuntimeError(f"{pass_name}: source revisions differ from validated run")
::PY::        if vd.get("comparison_hash") != cd.get("comparison_hash"):
::PY::            raise RuntimeError(f"{pass_name}: comparison hash differs from validated run")
::PY::        if vd.get("canonical_counts") != cd.get("canonical_counts"):
::PY::            raise RuntimeError(f"{pass_name}: canonical counts differ from validated run")
::PY::
::PY::    expected_counts = validated_report["checks"]["canonical_counts"]
::PY::    with connect_ro(args.database) as conn:
::PY::        integrity = [str(r[0]) for r in conn.execute("PRAGMA integrity_check")]
::PY::        foreign_keys = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check")]
::PY::        version_row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
::PY::        version = int(version_row[0]) if version_row and version_row[0] is not None else 0
::PY::        migration_row = conn.execute("SELECT name FROM schema_migrations WHERE version=10").fetchone()
::PY::        migration_name = str(migration_row[0]) if migration_row else None
::PY::        actual_counts = {
::PY::            "required_item": int(conn.execute("SELECT COUNT(*) FROM quest_required_items").fetchone()[0]),
::PY::            "required_source": int(conn.execute("SELECT COUNT(*) FROM quest_required_sources").fetchone()[0]),
::PY::            "provided_item": int(conn.execute("SELECT COUNT(*) FROM quest_provided_items").fetchone()[0]),
::PY::            "reward_item": int(conn.execute("SELECT COUNT(*) FROM quest_reward_items").fetchone()[0]),
::PY::            "choice_reward_item": int(conn.execute("SELECT COUNT(*) FROM quest_choice_reward_items").fetchone()[0]),
::PY::        }
::PY::        invalid_required = int(conn.execute("SELECT COUNT(*) FROM quest_required_items WHERE quantity <= 0").fetchone()[0])
::PY::        failed_batches = int(conn.execute("SELECT COUNT(*) FROM import_batches WHERE importer_version='quest-item-facts/1' AND status <> 'succeeded'").fetchone()[0])
::PY::        source_counts = source_observation_counts(conn)
::PY::
::PY::    if integrity != ["ok"] or foreign_keys != []:
::PY::        raise RuntimeError(f"real canonical direct SQLite integrity/FK check failed: integrity={integrity} fk={foreign_keys}")
::PY::    if version != 10 or migration_name != "0010_quest_item_facts.sql":
::PY::        raise RuntimeError(f"real canonical migration state is wrong: version={version} name={migration_name}")
::PY::    if actual_counts != expected_counts:
::PY::        raise RuntimeError(f"real canonical direct family counts differ: expected={expected_counts} actual={actual_counts}")
::PY::    if invalid_required != 0:
::PY::        raise RuntimeError("real canonical contains non-positive quest_required_items.quantity")
::PY::    if failed_batches != 0:
::PY::        raise RuntimeError("real canonical contains failed quest-item-facts import batches")
::PY::    if source_counts != validated_audit.get("source_observation_counts"):
::PY::        raise RuntimeError("real canonical P3-T05 source observation counts differ from validated disposable audit")
::PY::
::PY::    payload = {
::PY::        "database": str(Path(args.database).resolve()),
::PY::        "database_sha256": sha256_file(args.database),
::PY::        "backup_sha256": actual_backup,
::PY::        "schema_version": version,
::PY::        "migration_10_name": migration_name,
::PY::        "integrity_check": integrity,
::PY::        "foreign_key_check": foreign_keys,
::PY::        "canonical_counts": actual_counts,
::PY::        "source_observation_counts": source_counts,
::PY::        "invalid_required_quantity_count": invalid_required,
::PY::        "failed_import_batches": failed_batches,
::PY::        "validated_comparison_hash": validated_report["first"]["details"].get("comparison_hash"),
::PY::        "canonical_comparison_hash": canonical_report["first"]["details"].get("comparison_hash"),
::PY::    }
::PY::    write_json(args.output, payload)
::PY::    print(json.dumps(payload, sort_keys=True))
::PY::    return 0
::PY::
::PY::
::PY::def build_parser() -> argparse.ArgumentParser:
::PY::    parser = argparse.ArgumentParser()
::PY::    sub = parser.add_subparsers(dest="command", required=True)
::PY::
::PY::    p = sub.add_parser("verify-run")
::PY::    p.add_argument("--run-dir", required=True)
::PY::    p.add_argument("--canonical", required=True)
::PY::    p.add_argument("--output", required=True)
::PY::    p.set_defaults(func=cmd_verify_run)
::PY::
::PY::    p = sub.add_parser("final-check")
::PY::    p.add_argument("--database", required=True)
::PY::    p.add_argument("--backup", required=True)
::PY::    p.add_argument("--expected-backup-sha256", required=True)
::PY::    p.add_argument("--validated-report", required=True)
::PY::    p.add_argument("--canonical-report", required=True)
::PY::    p.add_argument("--validated-audit", required=True)
::PY::    p.add_argument("--output", required=True)
::PY::    p.set_defaults(func=cmd_final_check)
::PY::    return parser
::PY::
::PY::
::PY::def main() -> int:
::PY::    args = build_parser().parse_args()
::PY::    try:
::PY::        return int(args.func(args))
::PY::    except Exception as exc:
::PY::        print(f"FINALIZATION_HELPER_ERROR: {exc}")
::PY::        return 2
::PY::
::PY::
::PY::if __name__ == "__main__":
::PY::    raise SystemExit(main())
