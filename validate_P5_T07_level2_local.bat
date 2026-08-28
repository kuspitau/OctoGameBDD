@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "TASK=P5-T07"
set "EXPECTED_SHA=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
set "LOG_DIR=data\generated\validation_logs"
set "DB="
set "CONFIG=config.local.toml"
set "FINAL_EVIDENCE="
set "SUMMARY_JSON="
set "RC=0"

rem -----------------------------------------------------------------------------
rem P5-T07 Level-2-only validator.
rem Classical checks are intentionally NOT repeated here:
rem   pip install -e .[dev]
rem   pytest
rem   ruff
rem   compileall
rem The user has already run and passed those checks before launching this file.
rem -----------------------------------------------------------------------------

if not exist "pyproject.toml" goto :wrong_root
if not exist "scripts\validate_p5_t07.py" goto :missing_task_files
if not exist "scripts\configure_p5_t07_paths.py" goto :missing_task_files
if not exist "src\octogamedb\audit_spawn_raw_semantics.py" goto :missing_task_files

where python >nul 2>&1
if errorlevel 1 goto :no_python
python --version >nul 2>&1
if errorlevel 1 goto :no_python

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if errorlevel 1 goto :log_dir_failed

for /f "delims=" %%T in ('python -c "from datetime import datetime; print(datetime.now().strftime('%%Y%%m%%d_%%H%%M%%S'))"') do set "STAMP=%%T"
if not defined STAMP set "STAMP=%RANDOM%_%RANDOM%"
set "LOG=%LOG_DIR%\P5-T07_level2_local_!STAMP!.log"

set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

call :log "[INFO] OctoGameDB P5-T07 Level-2 local validation"
call :log "[INFO] Project root: %CD%"
call :log "[INFO] Log: %CD%\!LOG!"
call :log "[INFO] Classical checks are intentionally skipped in this BAT."
call :log "[INFO] Already completed externally: editable dev install, pytest, Ruff, compileall."
call :log "[INFO] Remaining gate: exact real-source + canonical-snapshot semantic validation."
call :log "[INFO] Expected canonical SHA-256: %EXPECTED_SHA%"
call :log "[INFO] Expected schema migration: 13"
call :log "[INFO] Expected P5-T06 addition baseline: 20707"
call :log "[INFO] Expected P5-T07 four-zone total: 15607"
call :log "[INFO] Expected zone counts: 406=5145, 5602=5062, 5581=2872, 1584=2528"

rem -----------------------------------------------------------------------------
rem 1. Resolve/reuse exact local pfQuest-family source roots.
rem First try completely non-interactively. If that fails, invoke the project
rem configurator interactively once, then re-run the non-interactive exact check
rem so the final resolved paths/revisions are captured in the log.
rem -----------------------------------------------------------------------------
call :log "[INFO] Checking configured/discoverable P5-T07 raw source roots and exact revisions."
set "STEP_LOG=%TEMP%\OctoGameDB_P5T07_paths_%RANDOM%_%RANDOM%.log"
python "scripts\configure_p5_t07_paths.py" --config "%CONFIG%" --non-interactive >"!STEP_LOG!" 2>&1
set "RC=!ERRORLEVEL!"
call :append_step

if not "!RC!"=="0" (
    call :log "[INFO] Automatic exact source-path resolution was incomplete."
    call :log "[INFO] Launching the project path resolver interactively."
    call :log "[INFO] Existing valid paths are reused; only unresolved exact roots will be requested."
    echo.
    python "scripts\configure_p5_t07_paths.py" --config "%CONFIG%"
    set "RC=!ERRORLEVEL!"
    echo.
    if not "!RC!"=="0" (
        call :log "[FAIL] Interactive P5-T07 source-path resolution failed with code !RC!."
        goto :failure_summary
    )
    call :log "[PASS] Interactive source-path resolution completed."

    call :log "[INFO] Re-verifying all three configured roots non-interactively for the log."
    set "STEP_LOG=%TEMP%\OctoGameDB_P5T07_paths_verify_%RANDOM%_%RANDOM%.log"
    python "scripts\configure_p5_t07_paths.py" --config "%CONFIG%" --non-interactive >"!STEP_LOG!" 2>&1
    set "RC=!ERRORLEVEL!"
    call :append_step
    if not "!RC!"=="0" (
        call :log "[FAIL] Exact source-path/revision verification still fails after configuration."
        goto :failure_summary
    )
)
call :log "[PASS] All three P5-T07 raw source roots are configured and revision-verified."

rem -----------------------------------------------------------------------------
rem 2. Find the canonical DB without hard-coded user paths.
rem Prefer the project-configured generated directory, then historical project-
rem relative canonical locations. Only an exact SHA-256 match is accepted.
rem -----------------------------------------------------------------------------
call :log "[INFO] Locating the exact validated canonical migration-13 database."
set "CONFIGURED_DB="
for /f "usebackq delims=" %%D in (`python -c "import pathlib,tomllib; p=pathlib.Path(r'%CONFIG%'); d=tomllib.load(p.open('rb')) if p.is_file() else {}; g=d.get('paths',{}).get('generated','data/generated'); print(pathlib.Path(g)/'octogamedb.sqlite3')" 2^>nul`) do set "CONFIGURED_DB=%%D"

if defined CONFIGURED_DB call :consider_db "!CONFIGURED_DB!"
if not defined DB call :consider_db "data\generated\octogamedb.sqlite3"
if not defined DB call :consider_db "data\octogamedb.sqlite3"

if not defined DB goto :no_matching_db
call :log "[PASS] Exact canonical DB selected: !DB!"

rem -----------------------------------------------------------------------------
rem 3. Run the task-owned autonomous Level-2 semantic validator.
rem It creates an isolated byte-for-byte snapshot, opens validation data read-only,
rem validates real raw source revisions, checks SQLite integrity/FKs/migration,
rem reproduces P5-T06/P5-T07 counts, checks deterministic reports and bounded real
rem transformation examples, and proves snapshot + canonical DB are unchanged.
rem -----------------------------------------------------------------------------
call :log "[INFO] Running the P5-T07 autonomous Level-2 semantic validator."
set "STEP_LOG=%TEMP%\OctoGameDB_P5T07_level2_%RANDOM%_%RANDOM%.log"
python "scripts\validate_p5_t07.py" --db "!DB!" --config "%CONFIG%" --output-dir "%LOG_DIR%" >"!STEP_LOG!" 2>&1
set "RC=!ERRORLEVEL!"
call :append_step
if not "!RC!"=="0" (
    call :log "[FAIL] P5-T07 Level-2 semantic validator exited with code !RC!."
    goto :failure_summary
)
call :log "[PASS] P5-T07 autonomous Level-2 semantic validator passed."

rem -----------------------------------------------------------------------------
rem 4. Resolve the evidence artifacts produced by this run.
rem -----------------------------------------------------------------------------
for /f "delims=" %%F in ('dir /b /a-d /o-d "%LOG_DIR%\P5-T07_validation_*.json" 2^>nul') do (
    if not defined FINAL_EVIDENCE set "FINAL_EVIDENCE=%CD%\%LOG_DIR%\%%F"
)
for /f "delims=" %%F in ('dir /b /a-d /o-d "%LOG_DIR%\P5-T07_summary_*.json" 2^>nul') do (
    echo %%F | findstr /I /C:"_repeat_" >nul
    if errorlevel 1 if not defined SUMMARY_JSON set "SUMMARY_JSON=%CD%\%LOG_DIR%\%%F"
)

if not defined FINAL_EVIDENCE (
    call :log "[FAIL] Validator returned success but no P5-T07_validation_*.json evidence file was found."
    goto :failure_summary
)
if not defined SUMMARY_JSON (
    call :log "[FAIL] Validator returned success but no primary P5-T07_summary_*.json file was found."
    goto :failure_summary
)

call :log "[PASS] P5-T07 Level-2 validation evidence was produced."
call :log "[INFO] Final evidence JSON: !FINAL_EVIDENCE!"
call :log "[INFO] Primary summary JSON: !SUMMARY_JSON!"
call :log "[INFO] RESULT: P5-T07 COMPLETE LOCAL VALIDATION PASSED"

echo.
echo ============================================================================
echo [PASS] P5-T07 COMPLETE LOCAL VALIDATION PASSED
echo [INFO] The classical test gate was not repeated by this BAT.
echo [INFO] Level-2 real-source/canonical-snapshot validation passed.
echo [INFO] Log to keep: %CD%\!LOG!
echo [INFO] Evidence JSON: !FINAL_EVIDENCE!
echo [INFO] Summary JSON: !SUMMARY_JSON!
echo ============================================================================
echo.
pause
exit /b 0

:consider_db
set "CANDIDATE=%~1"
if not defined CANDIDATE exit /b 0
if not exist "!CANDIDATE!" exit /b 0
for %%P in ("!CANDIDATE!") do set "CANDIDATE_FULL=%%~fP"
call :log "[INFO] Canonical DB candidate: !CANDIDATE_FULL!"
set "HASH="
for /f "usebackq delims=" %%H in (`python -c "import hashlib,sys; print(hashlib.file_digest(open(sys.argv[1],'rb'),'sha256').hexdigest())" "!CANDIDATE_FULL!" 2^>nul`) do set "HASH=%%H"
if not defined HASH (
    call :log "[FAIL] Could not compute SHA-256 for candidate: !CANDIDATE_FULL!"
    exit /b 0
)
call :log "[INFO] Candidate SHA-256: !HASH!"
if /I not "!HASH!"=="%EXPECTED_SHA%" exit /b 0
if exist "!CANDIDATE_FULL!-wal" (
    call :log "[FAIL] Exact-hash candidate has a -wal sidecar and is rejected: !CANDIDATE_FULL!-wal"
    exit /b 0
)
if exist "!CANDIDATE_FULL!-shm" (
    call :log "[FAIL] Exact-hash candidate has a -shm sidecar and is rejected: !CANDIDATE_FULL!-shm"
    exit /b 0
)
set "DB=!CANDIDATE_FULL!"
exit /b 0

:append_step
if exist "!STEP_LOG!" (
    type "!STEP_LOG!"
    type "!STEP_LOG!" >> "!LOG!"
    del /q "!STEP_LOG!" >nul 2>&1
)
exit /b 0

:no_matching_db
call :log "[FAIL] No project/config-relative database matched the exact canonical SHA-256."
call :log "[INFO] Expected SHA-256: %EXPECTED_SHA%"
call :log "[INFO] Checked the configured [paths].generated location and project-relative fallbacks."
goto :failure_summary

:failure_summary
call :log "[INFO] RESULT: P5-T07 COMPLETE LOCAL VALIDATION FAILED"
echo.
echo ============================================================================
echo [FAIL] P5-T07 COMPLETE LOCAL VALIDATION FAILED
echo [INFO] Send me this complete log:
echo [INFO] %CD%\!LOG!
echo [INFO] If a validator JSON was produced before the failure, send it too.
echo ============================================================================
echo.
pause
exit /b 1

:wrong_root
echo [FAIL] Place this BAT at the OctoGameDB project root before running it.
echo [INFO] Expected marker: pyproject.toml
echo.
pause
exit /b 1

:missing_task_files
echo [FAIL] Required P5-T07 task files are missing from this checkout.
echo [INFO] Expected:
echo [INFO]   scripts\validate_p5_t07.py
echo [INFO]   scripts\configure_p5_t07_paths.py
echo [INFO]   src\octogamedb\audit_spawn_raw_semantics.py
echo.
pause
exit /b 1

:no_python
echo [FAIL] Python was not found as the "python" command.
echo.
pause
exit /b 1

:log_dir_failed
echo [FAIL] Could not create %CD%\%LOG_DIR%
echo.
pause
exit /b 1

:log
set "MSG=%~1"
echo(!MSG!
if defined LOG >>"!LOG!" echo(!MSG!
exit /b 0
