@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 download_autosar_standards.py --output-dir "%~dp0AUTOSAR_Standards_Library"
) else (
  python download_autosar_standards.py --output-dir "%~dp0AUTOSAR_Standards_Library"
)
echo.
echo Finished. Check AUTOSAR_Standards_Library\DOWNLOAD_SUMMARY.txt and download_manifest.csv
pause
