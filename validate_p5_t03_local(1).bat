@echo off
setlocal EnableExtensions DisableDelayedExpansion
title OctoGameDB - P5-T03 Full Local Validation

rem ============================================================================
rem P5-T03 Level-2 local validation
rem
rem Assumptions:
rem   - The classic checks were already run successfully:
rem       pip install -e ".[dev]"
rem       pytest
rem       ruff
rem       compileall
rem   - This script therefore runs only the additional P5-T03 full-data checks.
rem
rem Safety:
rem   - The canonical DB is never intentionally modified.
rem   - scripts\validate_p5_t03.py performs the audit against a temporary snapshot.
rem   - This wrapper independently checks the canonical DB SHA-256 before/after.
rem ============================================================================

set "EXPECTED_HASH=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
set "EXPECTED_REVISION=sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db"
set "EXPECTED_UNSELECTED=9880"
set "EXIT_CODE=1"
set "RESULT=FAIL"
set "PROJECT_ROOT="

rem --- Locate project root: prefer the BAT directory, then current directory.
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

rem --- Python is required for the validator and timestamp.
where python >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python is not available on PATH.
    goto :finish
)

for /f "usebackq delims=" %%T in (`python -c "from datetime import datetime; print(datetime.now().strftime('%%Y%%m%%d_%%H%%M%%S'))"`) do set "STAMP=%%T"
if not defined STAMP set "STAMP=unknown_%RANDOM%"

set "RUN_DIR=%CD%\data\generated\validation_logs\P5-T03_batch_%STAMP%"
set "LOG_FILE=%RUN_DIR%\P5-T03_full_validation_%STAMP%.log"
set "CANONICAL_DB=%CD%\data\generated\octogamedb.sqlite3"
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

rem --- Critical file checks.
if not exist "%VALIDATOR%" (
    call :log FAIL "Missing validator: %VALIDATOR%"
    goto :finish
)
call :log PASS "P5-T03 validator found."

if not exist "%CANONICAL_DB%" (
    call :log FAIL "Canonical DB not found: %CANONICAL_DB%"
    goto :finish
)
call :log PASS "Canonical DB found."

if exist "%CANONICAL_DB%-wal" (
    call :log FAIL "Canonical DB has a -wal sidecar. Close any process using the DB before validating."
    goto :finish
)
if exist "%CANONICAL_DB%-shm" (
    call :log FAIL "Canonical DB has a -shm sidecar. Close any process using the DB before validating."
    goto :finish
)
call :log PASS "Canonical DB has no WAL/SHM sidecars."

rem --- Confirm the package is importable in the current Python environment.
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

rem --- Independent canonical hash check before validation.
set "HASH_BEFORE="
for /f "usebackq delims=" %%H in (`python -c "import hashlib, pathlib; p=pathlib.Path(r'%CANONICAL_DB%'); h=hashlib.sha256(); f=p.open('rb'); [h.update(c) for c in iter(lambda:f.read(1048576), b'')]; f.close(); print(h.hexdigest())"`) do set "HASH_BEFORE=%%H"

if not defined HASH_BEFORE (
    call :log FAIL "Could not compute canonical DB SHA-256 before validation."
    goto :finish
)
call :log INFO "Canonical DB SHA-256 before: %HASH_BEFORE%"

if /I not "%HASH_BEFORE%"=="%EXPECTED_HASH%" (
    call :log FAIL "Canonical DB SHA-256 does not match the validated migration-13 baseline."
    call :log FAIL "Expected: %EXPECTED_HASH%"
    call :log FAIL "Actual:   %HASH_BEFORE%"
    goto :finish
)
call :log PASS "Canonical DB SHA-256 matches the validated migration-13 baseline."

rem --- Run the real Level-2 validator.
call :log INFO "Running scripts\validate_p5_t03.py against the canonical DB via its snapshot workflow."
set "STEP_OUT=%RUN_DIR%\_validator_console.tmp"

python "%VALIDATOR%" --db "%CANONICAL_DB%" --output-dir "%RUN_DIR%" >"%STEP_OUT%" 2>&1
set "RC=%ERRORLEVEL%"

type "%STEP_OUT%"
type "%STEP_OUT%" >>"%LOG_FILE%"
del /q "%STEP_OUT%" >nul 2>&1

if not "%RC%"=="0" (
    call :log FAIL "P5-T03 validator returned exit code %RC%."
    goto :post_hash
)
call :log PASS "P5-T03 validator returned exit code 0."

rem --- Verify the produced Level-2 summary independently.
set "VERIFY_OUT=%RUN_DIR%\_result_verify.tmp"
python -c "import glob,json,os,sys; rd=os.environ['RUN_DIR']; fs=glob.glob(os.path.join(rd,'P5-T03_validation_*.json')); assert fs, 'No P5-T03_validation_*.json produced'; p=max(fs,key=os.path.getmtime); d=json.load(open(p,encoding='utf-8')); exp=os.environ['EXPECTED_HASH']; rev=os.environ['EXPECTED_REVISION']; n=int(os.environ['EXPECTED_UNSELECTED']); assert d.get('status')=='LEVEL_2_VALIDATION_PASSED', d.get('status'); assert d.get('canonical_sha256_before')==exp, d.get('canonical_sha256_before'); assert d.get('canonical_sha256_after')==exp, d.get('canonical_sha256_after'); c=d.get('comparison',{}); s=c.get('comparison_source',{}); assert s.get('source_key')=='pfquest-octo', s.get('source_key'); assert s.get('source_revision')==rev, s.get('source_revision'); assert s.get('unselected_group_count')==n, s.get('unselected_group_count'); sc=c.get('state_counts',{}); assert sum(int(v) for v in sc.values())==int(c.get('record_count',-1)), (sc,c.get('record_count')); print(p)" >"%VERIFY_OUT%" 2>&1
set "RC=%ERRORLEVEL%"

type "%VERIFY_OUT%"
type "%VERIFY_OUT%" >>"%LOG_FILE%"

if not "%RC%"=="0" (
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
rem --- Independent canonical hash check after all validation work.
set "HASH_AFTER="
for /f "usebackq delims=" %%H in (`python -c "import hashlib, pathlib; p=pathlib.Path(r'%CANONICAL_DB%'); h=hashlib.sha256(); f=p.open('rb'); [h.update(c) for c in iter(lambda:f.read(1048576), b'')]; f.close(); print(h.hexdigest())"`) do set "HASH_AFTER=%%H"

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

if not "%RC%"=="0" goto :finish

set "RESULT=PASS"
set "EXIT_CODE=0"
call :log PASS "P5-T03 FULL LOCAL VALIDATION PASSED."

:finish
echo.
if /I "%RESULT%"=="PASS" (
    echo ========================================================================
    echo [PASS] COMPLETE P5-T03 LOCAL VALIDATION SUCCEEDED
    echo ========================================================================
    echo P5-T03 can now be closed as validated using the generated evidence.
) else (
    echo ========================================================================
    echo [FAIL] COMPLETE P5-T03 LOCAL VALIDATION FAILED
    echo ========================================================================
    echo Review the log below and send it back for diagnosis.
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

:log
set "LOG_LEVEL=%~1"
set "LOG_MESSAGE=%~2"
echo [%LOG_LEVEL%] %LOG_MESSAGE%
if defined LOG_FILE >>"%LOG_FILE%" echo [%LOG_LEVEL%] %LOG_MESSAGE%
exit /b 0
