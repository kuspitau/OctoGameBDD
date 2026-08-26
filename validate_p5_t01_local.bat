@echo off
setlocal EnableExtensions EnableDelayedExpansion
title OctoGameDB - P5-T01 Local Validation

rem ============================================================
rem P5-T01 autonomous Level-2 validation
rem - Does NOT rerun pytest / Ruff / compileall.
rem - Uses the real canonical DB only as a read/copy source.
rem - Runs the resolution audit on a temporary snapshot.
rem - Verifies both canonical and snapshot SHA-256 integrity.
rem ============================================================

set "EXPECTED_SHA=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
set "FINAL_RC=1"
set "SCRIPT_DIR=%~dp0"
set "START_DIR=%CD%"
set "VALIDATOR_B64=aW1wb3J0IGpzb24KaW1wb3J0IHN5cwpmcm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgKCnAgPSBQYXRoKHN5cy5hcmd2WzFdKQp0cnk6CiAgICByID0ganNvbi5sb2FkcyhwLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKSkKZXhjZXB0IEV4Y2VwdGlvbiBhcyBleGM6CiAgICBwcmludChmIltGQUlMXSBDYW5ub3QgcGFyc2UgcmVzb2x1dGlvbiBKU09OOiB7ZXhjfSIpCiAgICByYWlzZSBTeXN0ZW1FeGl0KDEpCgpkZWYgcmVxdWlyZShjb25kaXRpb24sIG1lc3NhZ2UpOgogICAgaWYgbm90IGNvbmRpdGlvbjoKICAgICAgICBwcmludChmIltGQUlMXSB7bWVzc2FnZX0iKQogICAgICAgIHJhaXNlIFN5c3RlbUV4aXQoMSkKICAgIHByaW50KGYiW1BBU1NdIHttZXNzYWdlfSIpCgpyZXF1aXJlKHIuZ2V0KCJzY29wZSIpID09ICJwcm92ZW5hbmNlLXJlc29sdXRpb24iLCAic2NvcGUgaXMgcHJvdmVuYW5jZS1yZXNvbHV0aW9uIikKcmVxdWlyZSgKICAgIHJbIm9ic2VydmF0aW9uX2dyb3VwX2NvdW50Il0KICAgID09IHJbInNlbGVjdGVkX2dyb3VwX2NvdW50Il0gKyByWyJ1bnNlbGVjdGVkX2dyb3VwX2NvdW50Il0sCiAgICAic2VsZWN0ZWQgKyB1bnNlbGVjdGVkIGVxdWFscyB0b3RhbCBvYnNlcnZhdGlvbiBncm91cHMiLAopCnJlcXVpcmUoCiAgICByWyJjb25mbGljdF9ncm91cF9jb3VudCJdCiAgICA9PSByWyJyZXNvbHZlZF9jb25mbGljdF9ncm91cF9jb3VudCJdICsgclsidW5yZXNvbHZlZF9jb25mbGljdF9ncm91cF9jb3VudCJdLAogICAgInJlc29sdmVkICsgdW5yZXNvbHZlZCBjb25mbGljdHMgZXF1YWxzIHRvdGFsIGNvbmZsaWN0cyIsCikKcmVxdWlyZSgKICAgIHJbImVtcHR5X29ic2VydmF0aW9uX2dyb3VwX2NvdW50Il0gPj0gMCwKICAgICJlbXB0eSBvYnNlcnZhdGlvbiBncm91cCBjb3VudCBpcyBub24tbmVnYXRpdmUiLAopCnJlcXVpcmUoCiAgICAwCiAgICA8PSByWyJ1bnNlbGVjdGVkX3NpbmdsZV92YWx1ZV9ncm91cF9jb3VudCJdCiAgICA8PSByWyJ1bnNlbGVjdGVkX2dyb3VwX2NvdW50Il0sCiAgICAidW5zZWxlY3RlZCBzaW5nbGUtdmFsdWUgZ3JvdXBzIGFyZSB3aXRoaW4gdW5zZWxlY3RlZCBncm91cHMiLAopCnJlcXVpcmUoCiAgICBzdW0oeFsic2VsZWN0ZWRfZ3JvdXBfY291bnQiXSBmb3IgeCBpbiByWyJzZWxlY3Rpb25fcG9saWNpZXMiXSkKICAgID09IHJbInNlbGVjdGVkX2dyb3VwX2NvdW50Il0sCiAgICAic2VsZWN0aW9uLXBvbGljeSB0b3RhbHMgZXF1YWwgc2VsZWN0ZWQgZ3JvdXBzIiwKKQpyZXF1aXJlKAogICAgc3VtKHhbInNlbGVjdGVkX2dyb3VwX2NvdW50Il0gZm9yIHggaW4gclsic2VsZWN0ZWRfc291cmNlcyJdKQogICAgPT0gclsic2VsZWN0ZWRfZ3JvdXBfY291bnQiXSwKICAgICJzZWxlY3RlZC1zb3VyY2UgdG90YWxzIGVxdWFsIHNlbGVjdGVkIGdyb3VwcyIsCikKCmZhbWlsaWVzID0gclsiZmFjdF9mYW1pbGllcyJdCmFnZ3JlZ2F0ZV9rZXlzID0gKAogICAgIm9ic2VydmF0aW9uX2dyb3VwX2NvdW50IiwKICAgICJzZWxlY3RlZF9ncm91cF9jb3VudCIsCiAgICAidW5zZWxlY3RlZF9ncm91cF9jb3VudCIsCiAgICAiZW1wdHlfb2JzZXJ2YXRpb25fZ3JvdXBfY291bnQiLAogICAgImNvbmZsaWN0X2dyb3VwX2NvdW50IiwKICAgICJyZXNvbHZlZF9jb25mbGljdF9ncm91cF9jb3VudCIsCiAgICAidW5yZXNvbHZlZF9jb25mbGljdF9ncm91cF9jb3VudCIsCiAgICAidW5zZWxlY3RlZF9zaW5nbGVfdmFsdWVfZ3JvdXBfY291bnQiLAopCmZvciBrZXkgaW4gYWdncmVnYXRlX2tleXM6CiAgICByZXF1aXJlKAogICAgICAgIHN1bShpbnQoeFtrZXldKSBmb3IgeCBpbiBmYW1pbGllcykgPT0gaW50KHJba2V5XSksCiAgICAgICAgZiJmYWN0LWZhbWlseSBzdW0gbWF0Y2hlcyBnbG9iYWwge2tleX0iLAogICAgKQoKc3VtbWFyeSA9IHsKICAgICJvYnNlcnZhdGlvbl9ncm91cF9jb3VudCI6IHJbIm9ic2VydmF0aW9uX2dyb3VwX2NvdW50Il0sCiAgICAic2VsZWN0ZWRfZ3JvdXBfY291bnQiOiByWyJzZWxlY3RlZF9ncm91cF9jb3VudCJdLAogICAgInVuc2VsZWN0ZWRfZ3JvdXBfY291bnQiOiByWyJ1bnNlbGVjdGVkX2dyb3VwX2NvdW50Il0sCiAgICAiZW1wdHlfb2JzZXJ2YXRpb25fZ3JvdXBfY291bnQiOiByWyJlbXB0eV9vYnNlcnZhdGlvbl9ncm91cF9jb3VudCJdLAogICAgImNvbmZsaWN0X2dyb3VwX2NvdW50IjogclsiY29uZmxpY3RfZ3JvdXBfY291bnQiXSwKICAgICJyZXNvbHZlZF9jb25mbGljdF9ncm91cF9jb3VudCI6IHJbInJlc29sdmVkX2NvbmZsaWN0X2dyb3VwX2NvdW50Il0sCiAgICAidW5yZXNvbHZlZF9jb25mbGljdF9ncm91cF9jb3VudCI6IHJbInVucmVzb2x2ZWRfY29uZmxpY3RfZ3JvdXBfY291bnQiXSwKICAgICJ1bnNlbGVjdGVkX3NpbmdsZV92YWx1ZV9ncm91cF9jb3VudCI6IHJbInVuc2VsZWN0ZWRfc2luZ2xlX3ZhbHVlX2dyb3VwX2NvdW50Il0sCiAgICAic2VsZWN0aW9uX3BvbGljeV9jb3VudCI6IGxlbihyWyJzZWxlY3Rpb25fcG9saWNpZXMiXSksCiAgICAic2VsZWN0ZWRfc291cmNlX2NvdW50IjogbGVuKHJbInNlbGVjdGVkX3NvdXJjZXMiXSksCiAgICAiZmFjdF9mYW1pbHlfY291bnQiOiBsZW4oclsiZmFjdF9mYW1pbGllcyJdKSwKfQoKcHJpbnQoIltQQVNTXSBQNS1UMDEgUkVTT0xVVElPTiBJTlZBUklBTlRTIFBBU1NFRCIpCnByaW50KCJbSU5GT10gTWVhc3VyZWQgcmVhbCBQMS1QNCBiYXNlbGluZToiKQpwcmludChqc29uLmR1bXBzKHN1bW1hcnksIGluZGVudD0yLCBzb3J0X2tleXM9VHJ1ZSkpCg=="

call :FIND_ROOT "%SCRIPT_DIR%"
if not defined PROJECT_ROOT call :FIND_ROOT "%START_DIR%"

if not defined PROJECT_ROOT (
    echo [FAIL] Could not locate the OctoGameDB project root.
    echo [INFO] Put this .bat in the repository root, or run it from the repository root.
    echo.
    pause
    exit /b 1
)

cd /d "%PROJECT_ROOT%" || (
    echo [FAIL] Could not enter project root: "%PROJECT_ROOT%"
    echo.
    pause
    exit /b 1
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
if not defined STAMP set "STAMP=unknown"

set "LOG_DIR=%PROJECT_ROOT%\data\generated\validation_logs"
set "TMP_ROOT=%PROJECT_ROOT%\.validation_tmp\P5-T01_%STAMP%"
set "LOG_FILE=%LOG_DIR%\P5-T01_validation_%STAMP%.log"
set "BASELINE_JSON=%LOG_DIR%\P5-T01_resolution_%STAMP%.json"
set "CANONICAL_DB=%PROJECT_ROOT%\data\generated\octogamedb.sqlite3"
set "SNAPSHOT_DB=%TMP_ROOT%\octogamedb_snapshot.sqlite3"
set "CHECK_PY=%TMP_ROOT%\validate_resolution.py"
set "CHECK_OUT=%TMP_ROOT%\validate_resolution.out"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if not exist "%TMP_ROOT%" mkdir "%TMP_ROOT%" >nul 2>&1

call :LOG "[INFO] P5-T01 local validation started."
call :LOG "[INFO] Project root: %PROJECT_ROOT%"
call :LOG "[INFO] Log file: %LOG_FILE%"
call :LOG "[INFO] Resolution JSON: %BASELINE_JSON%"
call :LOG "[INFO] Classical checks already reported as passed; they will not be rerun."

rem ------------------------------------------------------------
rem 1. Prerequisites
rem ------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    call :FAIL "Python is not available on PATH."
    goto :END
)
call :PASS "Python is available."

where powershell >nul 2>&1
if errorlevel 1 (
    call :FAIL "PowerShell is not available on PATH."
    goto :END
)
call :PASS "PowerShell is available."

if not exist "%CANONICAL_DB%" (
    call :FAIL "Canonical DB not found: %CANONICAL_DB%"
    goto :END
)
call :PASS "Canonical DB found."

if exist "%CANONICAL_DB%-wal" (
    call :FAIL "Canonical DB has a -wal sidecar. Close any process using the DB before validation."
    goto :END
)
if exist "%CANONICAL_DB%-shm" (
    call :FAIL "Canonical DB has a -shm sidecar. Close any process using the DB before validation."
    goto :END
)
call :PASS "No canonical SQLite WAL/SHM sidecars are present."

rem ------------------------------------------------------------
rem 2. Canonical DB hash before validation
rem ------------------------------------------------------------
call :GET_SHA "%CANONICAL_DB%" CANONICAL_SHA_BEFORE
if errorlevel 1 (
    call :FAIL "Could not compute canonical DB SHA-256."
    goto :END
)
call :LOG "[INFO] Canonical SHA-256 before validation: !CANONICAL_SHA_BEFORE!"

if /I not "!CANONICAL_SHA_BEFORE!"=="%EXPECTED_SHA%" (
    call :FAIL "Canonical DB SHA-256 does not match the validated migration-13 baseline."
    call :LOG "[INFO] Expected: %EXPECTED_SHA%"
    call :LOG "[INFO] Actual:   !CANONICAL_SHA_BEFORE!"
    goto :END
)
call :PASS "Canonical DB SHA-256 matches the validated migration-13 baseline."

rem ------------------------------------------------------------
rem 3. Create an isolated byte-for-byte snapshot
rem ------------------------------------------------------------
copy /b /y "%CANONICAL_DB%" "%SNAPSHOT_DB%" >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :FAIL "Could not create the temporary DB snapshot."
    goto :END
)
call :PASS "Temporary DB snapshot created."

call :GET_SHA "%SNAPSHOT_DB%" SNAPSHOT_SHA_BEFORE
if errorlevel 1 (
    call :FAIL "Could not compute snapshot SHA-256."
    goto :END
)
call :LOG "[INFO] Snapshot SHA-256 before audit: !SNAPSHOT_SHA_BEFORE!"

if /I not "!SNAPSHOT_SHA_BEFORE!"=="!CANONICAL_SHA_BEFORE!" (
    call :FAIL "Snapshot is not byte-identical to the canonical DB."
    goto :END
)
call :PASS "Snapshot is byte-identical to the canonical DB."

rem ------------------------------------------------------------
rem 4. Run the real P1-P4 resolution audit on the snapshot only
rem ------------------------------------------------------------
call :LOG "[INFO] Running resolution audit on the isolated snapshot..."
python -m octogamedb resolution --db "%SNAPSHOT_DB%" --json >"%BASELINE_JSON%" 2>>"%LOG_FILE%"
if errorlevel 1 (
    call :FAIL "The resolution audit command failed."
    goto :END
)

if not exist "%BASELINE_JSON%" (
    call :FAIL "Resolution JSON was not produced."
    goto :END
)

for %%F in ("%BASELINE_JSON%") do set "JSON_SIZE=%%~zF"
if "!JSON_SIZE!"=="0" (
    call :FAIL "Resolution JSON is empty."
    goto :END
)
call :PASS "Resolution audit completed and JSON was produced."

rem ------------------------------------------------------------
rem 5. Verify the audit did not mutate the snapshot
rem ------------------------------------------------------------
call :GET_SHA "%SNAPSHOT_DB%" SNAPSHOT_SHA_AFTER
if errorlevel 1 (
    call :FAIL "Could not compute post-audit snapshot SHA-256."
    goto :END
)
call :LOG "[INFO] Snapshot SHA-256 after audit: !SNAPSHOT_SHA_AFTER!"

if /I not "!SNAPSHOT_SHA_AFTER!"=="!SNAPSHOT_SHA_BEFORE!" (
    call :FAIL "The resolution audit modified the snapshot database."
    goto :END
)
call :PASS "Resolution audit left the real-data snapshot byte-identical."

rem ------------------------------------------------------------
rem 6. Decode and execute the invariant validator
rem ------------------------------------------------------------
set "P5_VALIDATOR_B64=%VALIDATOR_B64%"
powershell -NoProfile -Command "[IO.File]::WriteAllBytes($env:CHECK_PY,[Convert]::FromBase64String($env:P5_VALIDATOR_B64))" >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :FAIL "Could not generate the temporary invariant validator."
    goto :END
)

call :LOG "[INFO] Validating resolution aggregation invariants..."
python "%CHECK_PY%" "%BASELINE_JSON%" >"%CHECK_OUT%" 2>&1
set "CHECK_RC=!ERRORLEVEL!"

type "%CHECK_OUT%"
type "%CHECK_OUT%" >>"%LOG_FILE%"

if not "!CHECK_RC!"=="0" (
    call :FAIL "Resolution invariant validation failed."
    goto :END
)
call :PASS "Resolution aggregation invariants passed."

rem Append the complete machine-readable baseline to the log.
call :LOG "[INFO] ----- BEGIN COMPLETE RESOLUTION JSON -----"
type "%BASELINE_JSON%" >>"%LOG_FILE%" 2>&1
call :LOG "[INFO] ----- END COMPLETE RESOLUTION JSON -----"

rem ------------------------------------------------------------
rem 7. Confirm canonical DB stayed untouched
rem ------------------------------------------------------------
call :GET_SHA "%CANONICAL_DB%" CANONICAL_SHA_AFTER
if errorlevel 1 (
    call :FAIL "Could not compute final canonical DB SHA-256."
    goto :END
)
call :LOG "[INFO] Canonical SHA-256 after validation: !CANONICAL_SHA_AFTER!"

if /I not "!CANONICAL_SHA_AFTER!"=="!CANONICAL_SHA_BEFORE!" (
    call :FAIL "Canonical DB changed during validation."
    goto :END
)
if /I not "!CANONICAL_SHA_AFTER!"=="%EXPECTED_SHA%" (
    call :FAIL "Final canonical DB SHA-256 no longer matches the validated baseline."
    goto :END
)
call :PASS "Canonical DB remained byte-identical throughout validation."

rem ------------------------------------------------------------
rem 8. Success
rem ------------------------------------------------------------
set "FINAL_RC=0"
call :LOG "[PASS] P5-T01 LOCAL VALIDATION COMPLETE."
call :LOG "[PASS] All remaining local validation requirements passed."
call :LOG "[INFO] Keep and return this log if needed: %LOG_FILE%"
call :LOG "[INFO] Measured baseline JSON: %BASELINE_JSON%"
goto :END

rem ============================================================
rem Helpers
rem ============================================================

:FIND_ROOT
set "SEARCH_DIR=%~1"
if not defined SEARCH_DIR exit /b 0
for %%D in ("%SEARCH_DIR%") do set "SEARCH_DIR=%%~fD"

:FIND_ROOT_LOOP
if exist "%SEARCH_DIR%\AGENTS.md" if exist "%SEARCH_DIR%\docs\project\CURRENT_STATE.md" if exist "%SEARCH_DIR%\src\octogamedb" (
    set "PROJECT_ROOT=%SEARCH_DIR%"
    exit /b 0
)
for %%P in ("%SEARCH_DIR%\..") do set "PARENT_DIR=%%~fP"
if /I "%PARENT_DIR%"=="%SEARCH_DIR%" exit /b 0
set "SEARCH_DIR=%PARENT_DIR%"
goto :FIND_ROOT_LOOP

:GET_SHA
set "%~2="
set "HASH_TARGET=%~1"
for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash -LiteralPath $env:HASH_TARGET -Algorithm SHA256).Hash.ToLower()" 2^>nul`) do set "%~2=%%H"
if not defined %~2 exit /b 1
exit /b 0

:LOG
echo %~1
>>"%LOG_FILE%" echo %~1
exit /b 0

:PASS
call :LOG "[PASS] %~1"
exit /b 0

:FAIL
call :LOG "[FAIL] %~1"
exit /b 0

:END
if exist "%CHECK_PY%" del /q "%CHECK_PY%" >nul 2>&1
if exist "%CHECK_OUT%" del /q "%CHECK_OUT%" >nul 2>&1
if exist "%SNAPSHOT_DB%" del /q "%SNAPSHOT_DB%" >nul 2>&1
if exist "%SNAPSHOT_DB%-wal" del /q "%SNAPSHOT_DB%-wal" >nul 2>&1
if exist "%SNAPSHOT_DB%-shm" del /q "%SNAPSHOT_DB%-shm" >nul 2>&1
if exist "%TMP_ROOT%" rmdir /s /q "%TMP_ROOT%" >nul 2>&1

echo.
if "%FINAL_RC%"=="0" (
    echo ============================================================
    echo [PASS] P5-T01 validation succeeded.
    echo [INFO] Log: %LOG_FILE%
    echo [INFO] Resolution JSON: %BASELINE_JSON%
    echo ============================================================
) else (
    echo ============================================================
    echo [FAIL] P5-T01 validation failed.
    echo [INFO] Send me this log:
    echo        %LOG_FILE%
    if exist "%BASELINE_JSON%" echo [INFO] Also keep: %BASELINE_JSON%
    echo ============================================================
)

echo.
pause
exit /b %FINAL_RC%
