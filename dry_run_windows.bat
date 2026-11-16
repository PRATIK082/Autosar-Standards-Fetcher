@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 download_autosar_standards.py --dry-run --output-dir "%~dp0AUTOSAR_Standards_Library"
) else (
  python download_autosar_standards.py --dry-run --output-dir "%~dp0AUTOSAR_Standards_Library"
)
echo.
echo Dry-run complete. Check AUTOSAR_Standards_Library\download_manifest.csv
pause
