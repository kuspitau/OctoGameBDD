@echo off
setlocal EnableExtensions DisableDelayedExpansion
title OctoGameDB - P5-T03 Full Local Validation

rem ============================================================================
rem P5-T03 Level-2 local validation - resilient DB discovery
rem
rem Classic checks are intentionally NOT repeated:
rem   pip install -e ".[dev]"
rem   pytest
rem   ruff
rem   compileall
rem
rem This wrapper locates the validated canonical DB without hard-coding a
rem user-specific absolute path, then runs scripts\validate_p5_t03.py safely.
rem ============================================================================

set "EXPECTED_HASH=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
set "EXPECTED_REVISION=sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db"
set "EXPECTED_UNSELECTED=9880"
set "EXIT_CODE=1"
set "RESULT=FAIL"
set "PROJECT_ROOT="
set "CANONICAL_DB="

rem --- Locate project root: BAT directory first, current directory second.
if exist "%~dp0pyproject.toml" if exist "%~dp0scripts\validate_p5_t03.py" set "PROJECT_ROOT=%~dp0"
if not defined PROJECT_ROOT if exist "%CD%\pyproject.toml" if exist "%CD%\scripts\validate_p5_t03.py" set "PROJECT_ROOT=%CD%\"

if not defined PROJECT_ROOT (
    echo [FAIL] Project root not found.
    echo [FAIL] Put this BAT in the OctoGameDB repository root, or run it from that root.
    echo.
    pause
    exit /b 1
)

pushd "%PROJECT_ROOT%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Cannot enter project root: %PROJECT_ROOT%
    echo.
    pause
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

set "RUN_DIR=%CD%\data\generated\validation_logs\P5-T03_batch_%STAMP%"
set "LOG_FILE=%RUN_DIR%\P5-T03_full_validation_%STAMP%.log"
set "VALIDATOR=%CD%\scripts\validate_p5_t03.py"

mkdir "%RUN_DIR%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Cannot create validation output directory:
    echo        %RUN_DIR%
    goto :finish
)

call :log INFO "P5-T03 full local validation started."
call :log INFO "Project root: %CD%"
call :log INFO "Run directory: %RUN_DIR%"
call :log INFO "Classic pytest/Ruff/compileall checks are intentionally not repeated."
call :log INFO "Only the remaining Level-2/full-data validation is executed."

if not exist "%VALIDATOR%" (
    call :log FAIL "Missing validator: %VALIDATOR%"
    goto :finish
)
call :log PASS "P5-T03 validator found."

rem ============================================================================
rem Discover the canonical DB.
rem Order:
rem   1. Current canonical project-relative path.
rem   2. Recursive search below project root.
rem   3. Recursive search below project parent (useful after folder moves).
rem Candidates are accepted only when SHA-256 matches EXPECTED_HASH.
rem Validation temp/log directories and backup names are excluded.
rem ============================================================================

call :log INFO "Locating canonical octogamedb.sqlite3 without hard-coded personal paths."

set "DEFAULT_DB=%CD%\data\generated\octogamedb.sqlite3"
if exist "%DEFAULT_DB%" call :try_default_db "%DEFAULT_DB%"
if defined CANONICAL_DB goto :db_found

set "DISCOVERY_FILE=%RUN_DIR%\db_candidates.txt"
set "DISCOVERY_PS=%RUN_DIR%\_discover_db.ps1"

>"%DISCOVERY_PS%" echo param([string]$ProjectRoot,[string]$ExpectedHash,[string]$OutFile)
>>"%DISCOVERY_PS%" echo $ErrorActionPreference = 'SilentlyContinue'
>>"%DISCOVERY_PS%" echo $roots = New-Object System.Collections.Generic.List[string]
>>"%DISCOVERY_PS%" echo $roots.Add((Resolve-Path -LiteralPath $ProjectRoot).Path)
>>"%DISCOVERY_PS%" echo $parent = Split-Path -Parent ((Resolve-Path -LiteralPath $ProjectRoot).Path)
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

rem --- Confirm current Python environment.
set "STEP_OUT=%RUN_DIR%\_python_preflight.tmp"
python -c "import sys, octogamedb; print('Python:', sys.executable); print('octogamedb:', octogamedb.__file__)" >"%STEP_OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%STEP_OUT%" >>"%LOG_FILE%"
type "%STEP_OUT%"
del /q "%STEP_OUT%" >nul 2>&1
if not "%RC%"=="0" (
    call :log FAIL "Python cannot import octogamedb in the current environment."
    goto :finish
)
call :log PASS "Python environment can import octogamedb."

rem --- Independent canonical hash before validation.
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

rem --- Run real Level-2 validator. It uses its own isolated snapshot.
call :log INFO "Running scripts\validate_p5_t03.py against the resolved canonical DB."
set "STEP_OUT=%RUN_DIR%\_validator_console.tmp"

python "%VALIDATOR%" --db "%CANONICAL_DB%" --output-dir "%RUN_DIR%" >"%STEP_OUT%" 2>&1
set "VALIDATOR_RC=%ERRORLEVEL%"

type "%STEP_OUT%"
type "%STEP_OUT%" >>"%LOG_FILE%"
del /q "%STEP_OUT%" >nul 2>&1

if not "%VALIDATOR_RC%"=="0" (
    call :log FAIL "P5-T03 validator returned exit code %VALIDATOR_RC%."
    goto :post_hash
)
call :log PASS "P5-T03 validator returned exit code 0."

rem --- Independently inspect the resulting validation JSON.
set "VERIFY_OUT=%RUN_DIR%\_result_verify.tmp"
set "RUN_DIR_ENV=%RUN_DIR%"
set "EXPECTED_HASH_ENV=%EXPECTED_HASH%"
set "EXPECTED_REVISION_ENV=%EXPECTED_REVISION%"
set "EXPECTED_UNSELECTED_ENV=%EXPECTED_UNSELECTED%"

python -c "import glob,json,os; rd=os.environ['RUN_DIR_ENV']; fs=glob.glob(os.path.join(rd,'P5-T03_validation_*.json')); assert fs, 'No P5-T03_validation_*.json produced'; p=max(fs,key=os.path.getmtime); d=json.load(open(p,encoding='utf-8')); exp=os.environ['EXPECTED_HASH_ENV']; rev=os.environ['EXPECTED_REVISION_ENV']; n=int(os.environ['EXPECTED_UNSELECTED_ENV']); assert d.get('status')=='LEVEL_2_VALIDATION_PASSED', d.get('status'); assert d.get('canonical_sha256_before')==exp; assert d.get('canonical_sha256_after')==exp; c=d.get('comparison',{}); s=c.get('comparison_source',{}); assert s.get('source_key')=='pfquest-octo'; assert s.get('source_revision')==rev; assert s.get('unselected_group_count')==n; sc=c.get('state_counts',{}); assert sum(int(v) for v in sc.values())==int(c.get('record_count',-1)); print(p)" >"%VERIFY_OUT%" 2>&1
set "VERIFY_RC=%ERRORLEVEL%"

type "%VERIFY_OUT%"
type "%VERIFY_OUT%" >>"%LOG_FILE%"

if not "%VERIFY_RC%"=="0" (
    del /q "%VERIFY_OUT%" >nul 2>&1
    call :log FAIL "Produced Level-2 JSON did not satisfy the required P5-T03 invariants."
    goto :post_hash
)

set "RESULT_JSON="
for /f "usebackq delims=" %%P in ("%VERIFY_OUT%") do set "RESULT_JSON=%%P"
del /q "%VERIFY_OUT%" >nul 2>&1

call :log PASS "Level-2 validation JSON satisfies all required P5-T03 invariants."
if defined RESULT_JSON call :log INFO "Validation JSON: %RESULT_JSON%"

:post_hash
call :compute_hash "%CANONICAL_DB%"
set "HASH_AFTER=%LAST_HASH%"

if not defined HASH_AFTER (
    call :log FAIL "Could not compute canonical DB SHA-256 after validation."
    goto :finish
)
call :log INFO "Canonical DB SHA-256 after: %HASH_AFTER%"

if /I not "%HASH_AFTER%"=="%HASH_BEFORE%" (
    call :log FAIL "Canonical DB changed during validation."
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
call :log PASS "P5-T03 FULL LOCAL VALIDATION PASSED."

:finish
echo.
if /I "%RESULT%"=="PASS" (
    echo ========================================================================
    echo [PASS] COMPLETE P5-T03 LOCAL VALIDATION SUCCEEDED
    echo ========================================================================
    echo P5-T03 now has the required Level-2/full-data validation evidence.
) else (
    echo ========================================================================
    echo [FAIL] COMPLETE P5-T03 LOCAL VALIDATION FAILED
    echo ========================================================================
    echo Send the log below back for diagnosis.
)
echo.
if defined LOG_FILE (
    echo Log:
    echo   %LOG_FILE%
    echo.
    echo Validation evidence directory:
    echo   %RUN_DIR%
)
echo.
echo Press any key to close this window.
pause >nul

popd >nul 2>&1
exit /b %EXIT_CODE%

:try_default_db
call :hash_matches "%~1"
if "%HASH_MATCH%"=="1" (
    set "CANONICAL_DB=%~1"
    call :log PASS "Canonical DB found at current project-relative location."
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
