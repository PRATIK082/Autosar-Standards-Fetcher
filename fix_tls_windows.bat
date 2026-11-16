@echo off
setlocal
cd /d "%~dp0"
echo This helper installs Python TLS trust-store support, then runs a dry-run.
echo It does not disable TLS certificate verification.
echo.
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 -m pip install --user truststore certifi
  if errorlevel 1 (
    echo.
    echo Could not install TLS helper packages automatically.
    echo Try: py -3 -m pip install --user truststore certifi
    echo If your network uses a company proxy, follow your IT team's certificate instructions.
    pause
    exit /b 1
  )
  py -3 download_autosar_standards.py --dry-run --tls-backend auto --output-dir "%~dp0AUTOSAR_Standards_Library"
) else (
  python -m pip install --user truststore certifi
  if errorlevel 1 (
    echo Could not install TLS helper packages. Check Python and pip installation.
    pause
    exit /b 1
  )
  python download_autosar_standards.py --dry-run --tls-backend auto --output-dir "%~dp0AUTOSAR_Standards_Library"
)
echo.
echo Dry-run complete. Review the output above and AUTOSAR_Standards_Library\DOWNLOAD_SUMMARY.txt
pause
