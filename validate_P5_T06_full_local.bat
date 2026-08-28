@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem ============================================================================
rem OctoGameDB - P5-T06 remaining local / Level-2 validation
rem Run by double-click after placing this file at the project root,
rem or invoke it from the project root.
rem
rem This intentionally DOES NOT rerun pip install / pytest / Ruff / compileall.
rem Those classical checks were already reported as passed before this handoff.
rem ============================================================================

cd /d "%~dp0"

set "TASK=P5-T06"
set "EXPECTED_SHA=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
set "LOG_DIR=data\generated\validation_logs"
set "EVIDENCE_DIR=data\generated\validation_logs"
set "LOG="
set "DB="
set "FINAL_EVIDENCE="

rem --- Minimal project-root sanity check --------------------------------------
if not exist "pyproject.toml" goto :wrong_root
if not exist "scripts\validate_p5_t06.py" goto :wrong_root
if not exist "src\octogamedb\audit_overlay_additions.py" goto :wrong_root

rem --- Python is required by the project and by the validator -----------------
where python >nul 2>&1
if errorlevel 1 goto :no_python
python --version >nul 2>&1
if errorlevel 1 goto :no_python

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if errorlevel 1 goto :log_dir_failed

for /f "delims=" %%T in ('python -c "from datetime import datetime; print(datetime.now().strftime('%%Y%%m%%d_%%H%%M%%S'))"') do set "STAMP=%%T"
if not defined STAMP set "STAMP=%RANDOM%_%RANDOM%"
set "LOG=%LOG_DIR%\P5-T06_local_validation_!STAMP!.log"

call :log "[INFO] OctoGameDB P5-T06 full remaining local validation"
call :log "[INFO] Project root: %CD%"
call :log "[INFO] Log: %LOG%"
call :log "[INFO] Evidence directory: %EVIDENCE_DIR%"
call :log "[INFO] Classical checks are not rerun: editable install, pytest, Ruff and compileall were already reported as passed."
call :log "[INFO] No addon/source path is required for P5-T06; the validator uses persisted migration-13 provenance only."
call :log "[INFO] Searching the project-relative canonical DB locations and requiring the exact validated SHA-256."

rem --- Select the exact validated canonical DB without hard-coded user paths --
for %%D in ("data\generated\octogamedb.sqlite3" "data\octogamedb.sqlite3") do (
    if exist "%%~D" (
        set "HASH="
        for /f "usebackq delims=" %%H in (`python -c "import hashlib,sys; print(hashlib.file_digest(open(sys.argv[1],'rb'),'sha256').hexdigest())" "%%~fD" 2^>nul`) do set "HASH=%%H"
        if defined HASH (
            call :log "[INFO] Candidate: %%~fD"
            call :log "[INFO] Candidate SHA-256: !HASH!"
            if /I "!HASH!"=="%EXPECTED_SHA%" (
                if exist "%%~fD-wal" (
                    call :log "[FAIL] Matching candidate has a -wal sidecar and is not safe for immutable validation: %%~fD-wal"
                ) else if exist "%%~fD-shm" (
                    call :log "[FAIL] Matching candidate has a -shm sidecar and is not safe for immutable validation: %%~fD-shm"
                ) else if not defined DB (
                    set "DB=%%~fD"
                    call :log "[PASS] Exact validated canonical DB selected: !DB!"
                )
            ) else (
                call :log "[INFO] Candidate does not match the required migration-13 canonical SHA and will not be used."
            )
        ) else (
            call :log "[FAIL] Could not calculate SHA-256 for candidate: %%~fD"
        )
    )
)

if not defined DB goto :no_matching_db

rem --- Make local source tree importable even if the editable install changed --
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

call :log "[INFO] Starting the autonomous P5-T06 Level-2 validator."
call :log "[INFO] The validator copies the selected DB to an isolated temporary snapshot and opens audit databases read-only."
call :log "[INFO] Critical failures stop the validation immediately."

set "STEP_LOG=%TEMP%\OctoGameDB_P5T06_%RANDOM%_%RANDOM%.tmp.log"
python "scripts\validate_p5_t06.py" --db "%DB%" --output-dir "%EVIDENCE_DIR%" >"%STEP_LOG%" 2>&1
set "VALIDATOR_RC=%ERRORLEVEL%"

type "%STEP_LOG%"
type "%STEP_LOG%" >> "%LOG%"
del /q "%STEP_LOG%" >nul 2>&1

if not "%VALIDATOR_RC%"=="0" goto :validator_failed

rem --- Locate the final evidence JSON produced by this successful run ---------
for /f "delims=" %%F in ('dir /b /a-d /o-d "%EVIDENCE_DIR%\P5-T06_validation_*.json" 2^>nul') do (
    if not defined FINAL_EVIDENCE set "FINAL_EVIDENCE=%CD%\%EVIDENCE_DIR%\%%F"
)

call :log "[PASS] P5-T06 Level-2/full-data validation completed successfully."
call :log "[PASS] The selected canonical DB passed the exact SHA, migration, integrity, FK, regression, provenance, coverage, determinism and byte-identity checks."
if defined FINAL_EVIDENCE call :log "[INFO] Final evidence JSON: !FINAL_EVIDENCE!"
call :log "[INFO] Full console log: %CD%\%LOG%"
call :log "[INFO] RESULT: COMPLETE LOCAL VALIDATION PASSED"

echo.
echo ============================================================================
echo [PASS] %TASK% COMPLETE LOCAL VALIDATION PASSED
echo [INFO] Log to keep/send: %CD%\%LOG%
if defined FINAL_EVIDENCE echo [INFO] Evidence JSON: !FINAL_EVIDENCE!
echo ============================================================================
echo.
pause
exit /b 0

:validator_failed
call :log "[FAIL] P5-T06 autonomous Level-2 validator exited with code %VALIDATOR_RC%."
call :log "[INFO] No successful validation state should be recorded from this run."
call :log "[INFO] Send this log for diagnosis: %CD%\%LOG%"
goto :failure_summary

:no_matching_db
call :log "[FAIL] No safe project-local database matched the exact required SHA-256: %EXPECTED_SHA%"
call :log "[INFO] Checked: data\generated\octogamedb.sqlite3 and data\octogamedb.sqlite3"
call :log "[INFO] If a matching DB exists with -wal/-shm sidecars, close the process using it and rerun; this script will not touch or checkpoint it."
call :log "[INFO] Send this log for diagnosis: %CD%\%LOG%"
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
set "LOG=%~dp0P5-T06_local_validation_FAILED_TO_START.log"
>"%LOG%" echo [FAIL] This BAT must be located at the OctoGameDB project root.
>>"%LOG%" echo [INFO] Expected pyproject.toml, scripts\validate_p5_t06.py and src\octogamedb\audit_overlay_additions.py beside this BAT.
echo [FAIL] This BAT must be located at the OctoGameDB project root.
echo [INFO] Expected pyproject.toml, scripts\validate_p5_t06.py and src\octogamedb\audit_overlay_additions.py beside this BAT.
echo [INFO] Log: %LOG%
echo.
pause
exit /b 1

:no_python
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
set "LOG=%LOG_DIR%\P5-T06_local_validation_NO_PYTHON_%RANDOM%_%RANDOM%.log"
>"%LOG%" echo [FAIL] Python was not found as the 'python' command.
>>"%LOG%" echo [INFO] P5-T06 validation requires the same Python environment used for the already-passed project tests.
echo [FAIL] Python was not found as the 'python' command.
echo [INFO] Use the same shell/environment where the project tests passed, then rerun this BAT.
echo [INFO] Log: %CD%\%LOG%
echo.
pause
exit /b 1

:log_dir_failed
set "LOG=%~dp0P5-T06_local_validation_LOGDIR_FAILURE.log"
>"%LOG%" echo [FAIL] Could not create %CD%\%LOG_DIR%
echo [FAIL] Could not create %CD%\%LOG_DIR%
echo [INFO] Log: %LOG%
echo.
pause
exit /b 1

:log
set "MSG=%~1"
echo(!MSG!
>>"%LOG%" echo(!MSG!
exit /b 0
