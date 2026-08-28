@echo off
setlocal EnableExtensions DisableDelayedExpansion
title OctoGameDB - P5-T04 Hotfix Full Local Validation

rem ============================================================================
rem P5-T04 Level-2/full-data local validation
rem
rem Classic checks are intentionally NOT repeated because they have already
rem passed for this handoff:
rem   python -m pip install -e ".[dev]"
rem   pytest --basetemp="$env:TEMP\OctoGameDB_pytest"
rem   python -m ruff check src tests
rem   python -m compileall -q src tests
rem
rem This wrapper:
rem   - locates the validated migration-13 canonical DB without hard-coded
rem     user-specific paths;
rem   - accepts only the exact validated SHA-256 baseline;
rem   - runs scripts\validate_p5_t04.py, which works on its own isolated copy;
rem   - independently verifies the emitted Level-2 evidence;
rem   - independently hashes the canonical DB before and after;
rem   - writes a complete run log and keeps this window open at the end.
rem ============================================================================

set "EXPECTED_HASH=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
set "EXPECTED_REVISION=sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db"
set "EXPECTED_ONE_SIDED=22295"
set "EXPECTED_ACTIVE_ONLY=16005"
set "EXIT_CODE=1"
set "RESULT=FAIL"
set "PROJECT_ROOT="
set "CANONICAL_DB="
set "VALIDATOR_RC=999"
set "VERIFY_RC=999"
set "HASH_BEFORE="
set "HASH_AFTER="
set "RESULT_JSON="

rem --- Locate project root: BAT directory first, current directory second.
if exist "%~dp0pyproject.toml" if exist "%~dp0scripts\validate_p5_t04.py" set "PROJECT_ROOT=%~dp0"
if not defined PROJECT_ROOT if exist "%CD%\pyproject.toml" if exist "%CD%\scripts\validate_p5_t04.py" set "PROJECT_ROOT=%CD%\"

if not defined PROJECT_ROOT (
    echo [FAIL] Project root not found.
    echo [FAIL] Put this BAT in the OctoGameDB repository root, or run it from that root.
    echo.
    echo Press any key to close this window.
    pause >nul
    exit /b 1
)

pushd "%PROJECT_ROOT%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Cannot enter project root: %PROJECT_ROOT%
    echo.
    echo Press any key to close this window.
    pause >nul
    exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python is not available on PATH.
    goto :finish
)

where powershell >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Windows PowerShell is not available on PATH.
    goto :finish
)

for /f "usebackq delims=" %%T in (`python -c "from datetime import datetime; print(datetime.now().strftime('%%Y%%m%%d_%%H%%M%%S'))"`) do set "STAMP=%%T"
if not defined STAMP set "STAMP=unknown_%RANDOM%"

set "RUN_DIR=%CD%\data\generated\validation_logs\P5-T04_batch_%STAMP%"
set "LOG_FILE=%RUN_DIR%\P5-T04_full_validation_%STAMP%.log"
set "VALIDATOR=%CD%\scripts\validate_p5_t04.py"

mkdir "%RUN_DIR%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Cannot create validation output directory:
    echo        %RUN_DIR%
    goto :finish
)

call :log INFO "P5-T04 hotfix full local validation started."
call :log INFO "Project root: %CD%"
call :log INFO "Run directory: %RUN_DIR%"
call :log INFO "The previously passed full classic suite is not repeated."
call :log INFO "Because the hotfix changes P5-T04 code/tests/validator, only targeted regression/style/syntax checks are rerun before Level-2."

if not exist "%VALIDATOR%" (
    call :log FAIL "Missing validator: %VALIDATOR%"
    goto :finish
)
call :log PASS "P5-T04 validator found."

rem ============================================================================
rem Resolve the canonical migration-13 DB.
rem
rem Project contract:
rem   data\generated\octogamedb.sqlite3
rem
rem If local data was moved, discovery searches:
rem   1. the project-relative canonical path;
rem   2. the repository tree;
rem   3. the repository parent tree.
rem
rem A candidate is accepted ONLY if its SHA-256 equals EXPECTED_HASH.
rem Validation temp/log directories and rollback backups are excluded.
rem If zero or multiple valid candidates remain, the user is asked once.
rem ============================================================================

call :log INFO "Locating canonical migration-13 octogamedb.sqlite3."
call :log INFO "A DB is accepted only when SHA-256 matches the validated P4-T04/P5 baseline."

set "DEFAULT_DB=%CD%\data\generated\octogamedb.sqlite3"
if exist "%DEFAULT_DB%" call :try_default_db "%DEFAULT_DB%"
if defined CANONICAL_DB goto :db_found

set "DISCOVERY_FILE=%RUN_DIR%\db_candidates.txt"
set "DISCOVERY_PS=%RUN_DIR%\_discover_db.ps1"

>"%DISCOVERY_PS%" echo param([string]$ProjectRoot,[string]$ExpectedHash,[string]$OutFile)
>>"%DISCOVERY_PS%" echo $ErrorActionPreference = 'SilentlyContinue'
>>"%DISCOVERY_PS%" echo $resolvedProject = (Resolve-Path -LiteralPath $ProjectRoot).Path
>>"%DISCOVERY_PS%" echo $roots = New-Object System.Collections.Generic.List[string]
>>"%DISCOVERY_PS%" echo $roots.Add($resolvedProject)
>>"%DISCOVERY_PS%" echo $parent = Split-Path -Parent $resolvedProject
>>"%DISCOVERY_PS%" echo if ($parent -and -not $roots.Contains($parent)) { $roots.Add($parent) }
>>"%DISCOVERY_PS%" echo $seen = @{}
>>"%DISCOVERY_PS%" echo $valid = New-Object System.Collections.Generic.List[string]
>>"%DISCOVERY_PS%" echo foreach ($root in $roots) {
>>"%DISCOVERY_PS%" echo   Get-ChildItem -LiteralPath $root -Filter 'octogamedb.sqlite3' -File -Recurse ^| ForEach-Object {
>>"%DISCOVERY_PS%" echo     $p = $_.FullName
>>"%DISCOVERY_PS%" echo     if ($seen.ContainsKey($p)) { return }
>>"%DISCOVERY_PS%" echo     $seen[$p] = $true
>>"%DISCOVERY_PS%" echo     if ($p -match '[\\/](validation_logs^|\.validation_tmp)[\\/]') { return }
>>"%DISCOVERY_PS%" echo     if ($p -match '(^|[\\/])octogamedb_bak\.sqlite3$') { return }
>>"%DISCOVERY_PS%" echo     try {
>>"%DISCOVERY_PS%" echo       $h = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant()
>>"%DISCOVERY_PS%" echo       if ($h -eq $ExpectedHash.ToLowerInvariant()) { $valid.Add($p) }
>>"%DISCOVERY_PS%" echo     } catch {}
>>"%DISCOVERY_PS%" echo   }
>>"%DISCOVERY_PS%" echo }
>>"%DISCOVERY_PS%" echo $enc = New-Object System.Text.UTF8Encoding($false)
>>"%DISCOVERY_PS%" echo [System.IO.File]::WriteAllLines($OutFile, @($valid ^| Sort-Object -Unique), $enc)

powershell -NoProfile -ExecutionPolicy Bypass -File "%DISCOVERY_PS%" -ProjectRoot "%CD%" -ExpectedHash "%EXPECTED_HASH%" -OutFile "%DISCOVERY_FILE%" >>"%LOG_FILE%" 2>&1
set "RC=%ERRORLEVEL%"
del /q "%DISCOVERY_PS%" >nul 2>&1

if not "%RC%"=="0" (
    call :log FAIL "Automatic canonical DB discovery failed."
    goto :manual_db
)

set "DB_COUNT=0"
for /f "usebackq delims=" %%P in ("%DISCOVERY_FILE%") do (
    if not "%%P"=="" (
        set /a DB_COUNT+=1
        set "DISCOVERED_DB=%%P"
    )
)

if "%DB_COUNT%"=="1" (
    set "CANONICAL_DB=%DISCOVERED_DB%"
    call :log PASS "Exactly one SHA-matching canonical DB was discovered."
    goto :db_found
)

if "%DB_COUNT%"=="0" (
    call :log INFO "No SHA-matching canonical DB was discovered under the project root or its parent."
    goto :manual_db
)

call :log FAIL "Multiple SHA-identical canonical DB candidates were discovered."
call :log INFO "Candidates:"
for /f "usebackq delims=" %%P in ("%DISCOVERY_FILE%") do call :log INFO "  %%P"
goto :manual_db

:manual_db
echo.
echo [INFO] Automatic discovery could not resolve one unique canonical DB.
echo [INFO] Paste or drag-drop the correct octogamedb.sqlite3 path below.
echo [INFO] Press ENTER with no value to abort.
echo.
set /p "MANUAL_DB=Canonical DB path: "
if not defined MANUAL_DB (
    call :log FAIL "Canonical DB path remains unresolved."
    goto :finish
)
set "MANUAL_DB=%MANUAL_DB:"=%"

if not exist "%MANUAL_DB%" (
    call :log FAIL "The supplied DB path does not exist: %MANUAL_DB%"
    goto :finish
)

call :hash_matches "%MANUAL_DB%"
if not "%HASH_MATCH%"=="1" (
    call :log FAIL "The supplied DB does not match the validated canonical SHA-256."
    call :log FAIL "Expected: %EXPECTED_HASH%"
    if defined LAST_HASH call :log FAIL "Actual:   %LAST_HASH%"
    goto :finish
)

set "CANONICAL_DB=%MANUAL_DB%"
call :log PASS "Supplied DB matches the validated canonical SHA-256."

:db_found
if not defined CANONICAL_DB (
    call :log FAIL "Internal error: canonical DB was not resolved."
    goto :finish
)

call :log INFO "Using canonical DB: %CANONICAL_DB%"

if not exist "%CANONICAL_DB%" (
    call :log FAIL "Resolved canonical DB path is not readable: %CANONICAL_DB%"
    goto :finish
)
call :log PASS "Resolved canonical DB path is readable."

if exist "%CANONICAL_DB%-wal" (
    call :log FAIL "Canonical DB has a -wal sidecar. Close any process using the DB before validating."
    goto :finish
)
if exist "%CANONICAL_DB%-shm" (
    call :log FAIL "Canonical DB has a -shm sidecar. Close any process using the DB before validating."
    goto :finish
)
call :log PASS "Canonical DB has no WAL/SHM sidecars."

rem --- Confirm the current Python environment without rerunning installation/tests.
set "STEP_OUT=%RUN_DIR%\_python_preflight.tmp"
python -c "import sys, octogamedb; import octogamedb.audit_spawn_divergence as m; print('Python:', sys.executable); print('octogamedb:', octogamedb.__file__); print('P5-T04 audit:', m.__file__)" >"%STEP_OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%STEP_OUT%"
type "%STEP_OUT%" >>"%LOG_FILE%"
del /q "%STEP_OUT%" >nul 2>&1

if not "%RC%"=="0" (
    call :log FAIL "Python cannot import the installed P5-T04 octogamedb code."
    goto :finish
)
call :log PASS "Python environment can import the P5-T04 audit module."

rem --- Targeted regression check for files changed by the hotfix.
call :log INFO "Running targeted P5-T04 pytest regression after the duplicate-membership hotfix."
set "STEP_OUT=%RUN_DIR%\_targeted_pytest.tmp"
set "PYTEST_TMP=%RUN_DIR%\pytest_tmp"
python -m pytest -q tests\test_audit_spawn_divergence.py --basetemp="%PYTEST_TMP%" >"%STEP_OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%STEP_OUT%"
type "%STEP_OUT%" >>"%LOG_FILE%"
del /q "%STEP_OUT%" >nul 2>&1
if not "%RC%"=="0" (
    call :log FAIL "Targeted P5-T04 pytest regression failed with exit code %RC%."
    goto :finish
)
call :log PASS "Targeted P5-T04 pytest regression passed."

call :log INFO "Running targeted Ruff check for hotfix-touched Python files."
set "STEP_OUT=%RUN_DIR%\_targeted_ruff.tmp"
python -m ruff check src\octogamedb\audit_spawn_divergence.py tests\test_audit_spawn_divergence.py scripts\validate_p5_t04.py >"%STEP_OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%STEP_OUT%"
type "%STEP_OUT%" >>"%LOG_FILE%"
del /q "%STEP_OUT%" >nul 2>&1
if not "%RC%"=="0" (
    call :log FAIL "Targeted Ruff check failed with exit code %RC%."
    goto :finish
)
call :log PASS "Targeted Ruff check passed."

call :log INFO "Running targeted Python syntax compilation for hotfix-touched files."
set "STEP_OUT=%RUN_DIR%\_targeted_pycompile.tmp"
python -m py_compile src\octogamedb\audit_spawn_divergence.py tests\test_audit_spawn_divergence.py scripts\validate_p5_t04.py >"%STEP_OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%STEP_OUT%"
type "%STEP_OUT%" >>"%LOG_FILE%"
del /q "%STEP_OUT%" >nul 2>&1
if not "%RC%"=="0" (
    call :log FAIL "Targeted Python syntax compilation failed with exit code %RC%."
    goto :finish
)
call :log PASS "Targeted Python syntax compilation passed."

rem --- Independently hash the canonical DB before running the Level-2 validator.
call :compute_hash "%CANONICAL_DB%"
set "HASH_BEFORE=%LAST_HASH%"

if not defined HASH_BEFORE (
    call :log FAIL "Could not compute canonical DB SHA-256 before validation."
    goto :finish
)
call :log INFO "Canonical DB SHA-256 before: %HASH_BEFORE%"

if /I not "%HASH_BEFORE%"=="%EXPECTED_HASH%" (
    call :log FAIL "Canonical DB SHA-256 does not match the validated migration-13 baseline."
    goto :finish
)
call :log PASS "Canonical DB SHA-256 matches the validated migration-13 baseline."

rem ============================================================================
rem Run the real P5-T04 Level-2 validator.
rem The validator itself:
rem   - rejects WAL/SHM sidecars;
rem   - creates an isolated byte-copy snapshot;
rem   - checks SQLite integrity/FKs/migration 13 on that snapshot;
rem   - executes the full P5-T04 real-data divergence audit;
rem   - verifies all P5-T03 membership/state baselines;
rem   - emits bounded real examples;
rem   - proves snapshot and canonical DB hashes are unchanged.
rem ============================================================================

call :log INFO "Running scripts\validate_p5_t04.py against the resolved canonical DB."
set "STEP_OUT=%RUN_DIR%\_validator_console.tmp"

python "%VALIDATOR%" --db "%CANONICAL_DB%" --output-dir "%RUN_DIR%" >"%STEP_OUT%" 2>&1
set "VALIDATOR_RC=%ERRORLEVEL%"

type "%STEP_OUT%"
type "%STEP_OUT%" >>"%LOG_FILE%"
del /q "%STEP_OUT%" >nul 2>&1

if not "%VALIDATOR_RC%"=="0" (
    call :log FAIL "P5-T04 validator returned exit code %VALIDATOR_RC%."
    goto :post_hash
)
call :log PASS "P5-T04 validator returned exit code 0."

rem ============================================================================
rem Independently verify the produced P5-T04 validation evidence.
rem This intentionally does NOT predeclare candidate/ambiguity/distance counts.
rem It checks the fixed baselines and prints the newly measured topology values
rem into the main log so the complete evidence can be sent back for closeout.
rem ============================================================================

set "VERIFY_PY=%RUN_DIR%\_verify_p5_t04_result.py"
set "VERIFY_OUT=%RUN_DIR%\_result_verify.tmp"

>"%VERIFY_PY%" echo import glob, json, os, sys
>>"%VERIFY_PY%" echo rd = os.environ["RUN_DIR_ENV"]
>>"%VERIFY_PY%" echo fs = glob.glob(os.path.join(rd, "P5-T04_validation_*.json"))
>>"%VERIFY_PY%" echo assert fs, "No P5-T04_validation_*.json produced"
>>"%VERIFY_PY%" echo p = max(fs, key=os.path.getmtime)
>>"%VERIFY_PY%" echo with open(p, encoding="utf-8") as f:
>>"%VERIFY_PY%" echo     d = json.load(f)
>>"%VERIFY_PY%" echo exp_hash = os.environ["EXPECTED_HASH_ENV"]
>>"%VERIFY_PY%" echo exp_rev = os.environ["EXPECTED_REVISION_ENV"]
>>"%VERIFY_PY%" echo exp_one = int(os.environ["EXPECTED_ONE_SIDED_ENV"])
>>"%VERIFY_PY%" echo exp_active = int(os.environ["EXPECTED_ACTIVE_ONLY_ENV"])
>>"%VERIFY_PY%" echo assert d.get("status") == "LEVEL_2_VALIDATION_PASSED", d.get("status")
>>"%VERIFY_PY%" echo assert d.get("canonical_sha256_before") == exp_hash
>>"%VERIFY_PY%" echo assert d.get("canonical_sha256_after") == exp_hash
>>"%VERIFY_PY%" echo assert d.get("comparison_revision") == exp_rev
>>"%VERIFY_PY%" echo b = d["membership_baseline"]
>>"%VERIFY_PY%" echo assert b["one_sided_member_count"] == exp_one
>>"%VERIFY_PY%" echo assert b["active_only_member_count"] == exp_active
>>"%VERIFY_PY%" echo kinds = {r["subject_kind"]: r for r in b["by_subject_kind"]}
>>"%VERIFY_PY%" echo assert kinds["creature_spawn"]["shared_member_count"] == 85551
>>"%VERIFY_PY%" echo assert kinds["creature_spawn"]["active_only_member_count"] == 10255
>>"%VERIFY_PY%" echo assert kinds["creature_spawn"]["comparison_only_member_count"] == 3928
>>"%VERIFY_PY%" echo assert kinds["gameobject_spawn"]["shared_member_count"] == 59896
>>"%VERIFY_PY%" echo assert kinds["gameobject_spawn"]["active_only_member_count"] == 5750
>>"%VERIFY_PY%" echo assert kinds["gameobject_spawn"]["comparison_only_member_count"] == 2362
>>"%VERIFY_PY%" echo expected_t03 = {"comparison_only":12600,"active_only":32078,"same_value":394970,"different_value":2759,"not_directly_comparable":8252}
>>"%VERIFY_PY%" echo assert d["p5_t03_state_counts"] == expected_t03
>>"%VERIFY_PY%" echo topo = d["parent_topology"]
>>"%VERIFY_PY%" echo assert sum(topo["class_counts"].values()) == topo["directly_comparable_parent_count"]
>>"%VERIFY_PY%" echo assert sum(r["one_sided_member_count"] for r in d["active_membership_contexts"]) == exp_one
>>"%VERIFY_PY%" echo assert sum(r["member_count"] for r in d["active_only_selected_position_contexts"]) == exp_active
>>"%VERIFY_PY%" echo cand = d["relocation_candidate_analysis"]
>>"%VERIFY_PY%" echo card = cand["member_candidate_cardinality"]
>>"%VERIFY_PY%" echo assert card["zero"] + card["one"] + card["multiple"] == exp_one
>>"%VERIFY_PY%" echo ties = cand["member_nearest_tie_cardinality"]
>>"%VERIFY_PY%" echo assert ties["zero"] + ties["one"] + ties["multiple"] == exp_one
>>"%VERIFY_PY%" echo print("[PASS] Independent JSON evidence verification passed.")
>>"%VERIFY_PY%" echo print("[INFO] Validation JSON:", p)
>>"%VERIFY_PY%" echo print("[INFO] One-sided memberships:", b["one_sided_member_count"])
>>"%VERIFY_PY%" echo print("[INFO] Parent topology classes:", json.dumps(topo["class_counts"], sort_keys=True))
>>"%VERIFY_PY%" echo print("[INFO] Compatible candidate pairs:", cand["compatible_candidate_pair_count"])
>>"%VERIFY_PY%" echo print("[INFO] Unique nearest candidate pairs:", cand["unique_nearest_candidate_pair_count"])
>>"%VERIFY_PY%" echo print("[INFO] Candidate cardinality zero/one/multiple:", card["zero"], card["one"], card["multiple"])
>>"%VERIFY_PY%" echo print("[INFO] Nearest-tie cardinality zero/one/multiple:", ties["zero"], ties["one"], ties["multiple"])
>>"%VERIFY_PY%" echo print("[INFO] Members without compatible opposite:", cand["members_without_compatible_opposite_count"])
>>"%VERIFY_PY%" echo print("[INFO] Distance bands:", json.dumps(cand["compatible_pair_distance_bands"], ensure_ascii=False, sort_keys=True))
>>"%VERIFY_PY%" echo print("[INFO] Top parent concentrations:")
>>"%VERIFY_PY%" echo for row in d.get("top_parent_concentrations", [])[:10]:
>>"%VERIFY_PY%" echo     print("  ", json.dumps(row, ensure_ascii=False, sort_keys=True))
>>"%VERIFY_PY%" echo print("[INFO] Top zone/map concentrations:")
>>"%VERIFY_PY%" echo for row in d.get("top_zone_map_concentrations", [])[:10]:
>>"%VERIFY_PY%" echo     print("  ", json.dumps(row, ensure_ascii=False, sort_keys=True))

set "RUN_DIR_ENV=%RUN_DIR%"
set "EXPECTED_HASH_ENV=%EXPECTED_HASH%"
set "EXPECTED_REVISION_ENV=%EXPECTED_REVISION%"
set "EXPECTED_ONE_SIDED_ENV=%EXPECTED_ONE_SIDED%"
set "EXPECTED_ACTIVE_ONLY_ENV=%EXPECTED_ACTIVE_ONLY%"

python "%VERIFY_PY%" >"%VERIFY_OUT%" 2>&1
set "VERIFY_RC=%ERRORLEVEL%"

type "%VERIFY_OUT%"
type "%VERIFY_OUT%" >>"%LOG_FILE%"

if not "%VERIFY_RC%"=="0" (
    del /q "%VERIFY_PY%" "%VERIFY_OUT%" >nul 2>&1
    call :log FAIL "Produced Level-2 JSON did not satisfy the required P5-T04 invariants."
    goto :post_hash
)

set "RESULT_JSON="
for /f "delims=" %%F in ('dir /b /a-d /o-d "%RUN_DIR%\P5-T04_validation_*.json" 2^>nul') do if not defined RESULT_JSON set "RESULT_JSON=%RUN_DIR%\%%F"

del /q "%VERIFY_PY%" "%VERIFY_OUT%" >nul 2>&1

call :log PASS "Level-2 validation JSON satisfies the fixed P5-T04 and P5-T03 invariants."
if defined RESULT_JSON call :log INFO "Validation JSON: %RESULT_JSON%"

:post_hash
rem --- Independent canonical hash after validator success OR failure.
call :compute_hash "%CANONICAL_DB%"
set "HASH_AFTER=%LAST_HASH%"

if not defined HASH_AFTER (
    call :log FAIL "Could not compute canonical DB SHA-256 after validation."
    goto :finish
)
call :log INFO "Canonical DB SHA-256 after: %HASH_AFTER%"

if /I not "%HASH_AFTER%"=="%HASH_BEFORE%" (
    call :log FAIL "CRITICAL: canonical DB changed during validation."
    call :log FAIL "Before: %HASH_BEFORE%"
    call :log FAIL "After:  %HASH_AFTER%"
    goto :finish
)

if /I not "%HASH_AFTER%"=="%EXPECTED_HASH%" (
    call :log FAIL "Canonical DB no longer matches the validated migration-13 baseline."
    goto :finish
)
call :log PASS "Canonical DB remained byte-identical."

if not "%VALIDATOR_RC%"=="0" goto :finish
if not "%VERIFY_RC%"=="0" goto :finish

set "RESULT=PASS"
set "EXIT_CODE=0"
call :log PASS "P5-T04 FULL LOCAL VALIDATION PASSED."

:finish
echo.
if /I "%RESULT%"=="PASS" (
    echo ========================================================================
    echo [PASS] COMPLETE P5-T04 LOCAL VALIDATION SUCCEEDED
    echo ========================================================================
    echo P5-T04 now has the required Level-2/full-data validation evidence.
    echo Send the main log back so the measured P5-T04 results can be recorded
    echo and the next task can be routed from the evidence.
) else (
    echo ========================================================================
    echo [FAIL] COMPLETE P5-T04 LOCAL VALIDATION FAILED
    echo ========================================================================
    echo Send the main log below back for diagnosis.
)
echo.
if defined LOG_FILE (
    echo Main log:
    echo   %LOG_FILE%
    echo.
    echo Validation evidence directory:
    echo   %RUN_DIR%
    echo.
    if defined RESULT_JSON (
        echo Validation JSON:
        echo   %RESULT_JSON%
        echo.
    )
)
echo Press any key to close this window.
pause >nul

popd >nul 2>&1
exit /b %EXIT_CODE%

:try_default_db
call :hash_matches "%~1"
if "%HASH_MATCH%"=="1" (
    set "CANONICAL_DB=%~1"
    call :log PASS "Canonical DB found at the project-relative canonical location."
) else (
    call :log INFO "Project-relative DB exists but does not match the validated canonical SHA-256."
)
exit /b 0

:compute_hash
set "LAST_HASH="
set "HASH_TARGET=%~1"
for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "$ErrorActionPreference='Stop'; (Get-FileHash -LiteralPath $env:HASH_TARGET -Algorithm SHA256).Hash.ToLowerInvariant()" 2^>nul`) do set "LAST_HASH=%%H"
exit /b 0

:hash_matches
set "HASH_MATCH=0"
call :compute_hash "%~1"
if /I "%LAST_HASH%"=="%EXPECTED_HASH%" set "HASH_MATCH=1"
exit /b 0

:log
set "LOG_LEVEL=%~1"
set "LOG_MESSAGE=%~2"
echo [%LOG_LEVEL%] %LOG_MESSAGE%
if defined LOG_FILE >>"%LOG_FILE%" echo [%LOG_LEVEL%] %LOG_MESSAGE%
exit /b 0
