@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
set /p RONN_URL=RONN Core URL (https://...): 
set /p PAIR_CODE=Pairing code from RONN: 
if "%RONN_URL%"=="" (
  echo Missing RONN URL.
  pause
  exit /b 1
)
if "%PAIR_CODE%"=="" (
  echo Missing pairing code.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" bridge.py --server "%RONN_URL%" --pair "%PAIR_CODE%"
pause
