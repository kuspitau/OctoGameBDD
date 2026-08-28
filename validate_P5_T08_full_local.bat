@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "TASK=P5-T08"
set "EXPECTED_SHA=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
set "LOG_DIR=data\generated\validation_logs"
set "DB="
set "FINAL_EVIDENCE="

if not exist "pyproject.toml" goto :wrong_root
if not exist "scripts\validate_p5_t08.py" goto :wrong_root
if not exist "src\octogamedb\audit_spawn_replacement_semantics.py" goto :wrong_root
if not exist "config.local.toml" goto :missing_paths
where python >nul 2>&1
if errorlevel 1 goto :no_python
python --version >nul 2>&1
if errorlevel 1 goto :no_python

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if errorlevel 1 goto :log_dir_failed
for /f "delims=" %%T in ('python -c "from datetime import datetime; print(datetime.now().strftime('%%Y%%m%%d_%%H%%M%%S'))"') do set "STAMP=%%T"
if not defined STAMP set "STAMP=%RANDOM%_%RANDOM%"
set "LOG=%LOG_DIR%\P5-T08_local_validation_!STAMP!.log"

call :log "[INFO] OctoGameDB P5-T08 complete local validation"
call :log "[INFO] Project root: %CD%"
call :log "[INFO] Log: %LOG%"
call :log "[INFO] Required source keys: pfquest, pfquest_turtle, pfquest_octo"
call :log "[INFO] Exact persisted/raw source revisions are checked by the semantic validator."
call :log "[INFO] Looking for the validated canonical DB in the two project-local paths accepted by P5-T07."

call :try_db "data\generated\octogamedb.sqlite3"
if not defined DB call :try_db "data\octogamedb.sqlite3"
if not defined DB goto :no_matching_db

call :log "[PASS] Exact validated canonical DB selected: !DB!"

set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "STEP_LOG=%TEMP%\OctoGameDB_P5T08_pytest_%RANDOM%_%RANDOM%.log"
call :log "[INFO] Running full pytest suite."
python -m pytest -q --basetemp="%TEMP%\OctoGameDB_P5T08_pytest_!STAMP!" >"!STEP_LOG!" 2>&1
set "RC=!ERRORLEVEL!"
call :append_step
if not "!RC!"=="0" (
    call :log "[FAIL] Full pytest suite exited with code !RC!."
    goto :failure_summary
)
call :log "[PASS] Full pytest suite passed."

set "STEP_LOG=%TEMP%\OctoGameDB_P5T08_ruff_%RANDOM%_%RANDOM%.log"
call :log "[INFO] Running Ruff."
python -m ruff check src tests scripts >"!STEP_LOG!" 2>&1
set "RC=!ERRORLEVEL!"
call :append_step
if not "!RC!"=="0" (
    call :log "[FAIL] Ruff exited with code !RC!."
    call :log "[INFO] If Ruff is not installed, run: python -m pip install -e .[dev]"
    goto :failure_summary
)
call :log "[PASS] Ruff passed."

set "STEP_LOG=%TEMP%\OctoGameDB_P5T08_compileall_%RANDOM%_%RANDOM%.log"
call :log "[INFO] Running compileall."
python -m compileall -q src tests scripts >"!STEP_LOG!" 2>&1
set "RC=!ERRORLEVEL!"
call :append_step
if not "!RC!"=="0" (
    call :log "[FAIL] compileall exited with code !RC!."
    goto :failure_summary
)
call :log "[PASS] compileall passed."

set "STEP_LOG=%TEMP%\OctoGameDB_P5T08_validator_%RANDOM%_%RANDOM%.log"
call :log "[INFO] Running P5-T08 exact replacement semantic validator."
call :log "[INFO] Passing DB explicitly: !DB!"
python "scripts\validate_p5_t08.py" --db "!DB!" --config "config.local.toml" --output-dir "%LOG_DIR%" >"!STEP_LOG!" 2>&1
set "RC=!ERRORLEVEL!"
call :append_step
if not "!RC!"=="0" (
    call :log "[FAIL] P5-T08 semantic validator exited with code !RC!."
    call :log "[INFO] If a source path/revision failed, run get_path.bat and retry."
    goto :failure_summary
)
call :log "[PASS] P5-T08 semantic validator passed."

for /f "delims=" %%F in ('dir /b /a-d /o-d "%LOG_DIR%\P5-T08_validation_*.json" 2^>nul') do (
    if not defined FINAL_EVIDENCE set "FINAL_EVIDENCE=%CD%\%LOG_DIR%\%%F"
)

call :log "[PASS] P5-T08 complete local validation passed."
call :log "[PASS] Full suite, Ruff, compileall, canonical DB invariants and replacement-semantic acceptance passed."
if defined FINAL_EVIDENCE call :log "[INFO] Final evidence JSON: !FINAL_EVIDENCE!"
call :log "[INFO] RESULT: COMPLETE LOCAL VALIDATION PASSED"
echo.
echo ============================================================================
echo [PASS] %TASK% COMPLETE LOCAL VALIDATION PASSED
if defined FINAL_EVIDENCE echo [INFO] Evidence JSON: !FINAL_EVIDENCE!
echo [INFO] Log: %CD%\%LOG%
echo ============================================================================
echo.
pause
exit /b 0

:try_db
set "CANDIDATE=%~f1"
if not exist "!CANDIDATE!" (
    call :log "[INFO] DB candidate not present: !CANDIDATE!"
    exit /b 0
)

set "HASH="
for /f "usebackq delims=" %%H in (`python -c "import hashlib,sys; print(hashlib.file_digest(open(sys.argv[1],'rb'),'sha256').hexdigest())" "!CANDIDATE!" 2^>nul`) do set "HASH=%%H"
if not defined HASH (
    call :log "[FAIL] Could not compute SHA-256 for candidate: !CANDIDATE!"
    exit /b 0
)

call :log "[INFO] Candidate: !CANDIDATE!"
call :log "[INFO] Candidate SHA-256: !HASH!"
if /I not "!HASH!"=="%EXPECTED_SHA%" (
    call :log "[INFO] Candidate does not match the validated migration-13 SHA-256."
    exit /b 0
)
if exist "!CANDIDATE!-wal" (
    call :log "[FAIL] Matching candidate has a -wal sidecar: !CANDIDATE!-wal"
    exit /b 0
)
if exist "!CANDIDATE!-shm" (
    call :log "[FAIL] Matching candidate has a -shm sidecar: !CANDIDATE!-shm"
    exit /b 0
)
set "DB=!CANDIDATE!"
exit /b 0

:append_step
if exist "!STEP_LOG!" (
    type "!STEP_LOG!"
    type "!STEP_LOG!" >> "%LOG%"
    del /q "!STEP_LOG!" >nul 2>&1
)
exit /b 0

:missing_paths
echo [FAIL] config.local.toml is missing.
echo [INFO] Run get_path.bat first; P5-T08 needs all three exact pfQuest-family source roots.
pause
exit /b 1

:no_matching_db
call :log "[FAIL] No project-local database matched exact SHA-256 %EXPECTED_SHA%."
call :log "[INFO] Checked: %CD%\data\generated\octogamedb.sqlite3"
call :log "[INFO] Checked: %CD%\data\octogamedb.sqlite3"
goto :failure_summary

:failure_summary
echo.
echo ============================================================================
echo [FAIL] %TASK% COMPLETE LOCAL VALIDATION FAILED
echo [INFO] Review/send log: %CD%\%LOG%
echo ============================================================================
echo.
pause
exit /b 1

:wrong_root
echo [FAIL] This BAT must be placed at the OctoGameDB project root.
pause
exit /b 1

:no_python
echo [FAIL] Python was not found as the "python" command.
pause
exit /b 1

:log_dir_failed
echo [FAIL] Could not create %CD%\%LOG_DIR%
pause
exit /b 1

:log
set "MSG=%~1"
echo(!MSG!
if defined LOG >>"%LOG%" echo(!MSG!
exit /b 0
