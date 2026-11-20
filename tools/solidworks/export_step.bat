@echo off
REM Double-click to export STEP files for every changed SolidWorks part in cad\.
REM Needs Python and pywin32 (pip install pywin32), plus SolidWorks installed.
cd /d "%~dp0..\.."
python tools\solidworks\export_step.py %*
echo.
pause
