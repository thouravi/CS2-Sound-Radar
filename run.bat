@echo off
setlocal
cd /d "%~dp0"
title CS2 Sound Radar
color 0A

echo ============================================
echo   CS2 Sound Radar
echo   Folder: %cd%
echo ============================================
echo.

REM Prefer "py -3" then "python"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [ERROR] Python not found on PATH.
  echo Install from https://www.python.org/downloads/
  echo Check "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

echo Using: %PY%
%PY% --version
echo.

echo Checking packages...
%PY% -c "import numpy, PySide6, soundcard" 2>radar_import_err.txt
if errorlevel 1 (
  echo Packages missing — installing...
  echo.
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [ERROR] pip install failed. Full error above.
    type radar_import_err.txt 2>nul
    echo.
    pause
    exit /b 1
  )
  %PY% -c "import numpy, PySide6, soundcard" 2>radar_import_err.txt
  if errorlevel 1 (
    echo [ERROR] Packages still not importable:
    type radar_import_err.txt
    pause
    exit /b 1
  )
)
del radar_import_err.txt 2>nul

echo.
echo Starting overlay window...
echo If you see nothing, check radar_log.txt in this folder.
echo Close the radar window or press Ctrl+C here to stop.
echo.

%PY% radar_overlay.py
set ERR=%ERRORLEVEL%

echo.
if not "%ERR%"=="0" (
  echo [ERROR] App exited with code %ERR%
  if exist radar_log.txt (
    echo ---- radar_log.txt ----
    type radar_log.txt
    echo -----------------------
  )
  pause
  exit /b %ERR%
)

echo Closed normally.
timeout /t 2 >nul
endlocal
