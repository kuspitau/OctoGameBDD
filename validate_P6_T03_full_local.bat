@echo off
setlocal
cd /d "%~dp0"

echo [INFO] P6-T03 resumable direct-Octo acquisition validation
python scripts\validate_p6_t03_resume.py
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo [FAIL] P6-T03 Level-2 validation failed with exit code %RC%.
) else (
  echo [PASS] P6-T03 Level-2 validation entry point completed.
)

echo.
pause
exit /b %RC%
