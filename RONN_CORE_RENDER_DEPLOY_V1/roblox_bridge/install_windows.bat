@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m venv .venv || goto :fail
  call .venv\Scripts\activate.bat || goto :fail
  python -m pip install --upgrade pip || goto :fail
  pip install -r requirements.txt || goto :fail
) else (
  where python >nul 2>nul || (
    echo Python 3.10+ is required.
    pause
    exit /b 1
  )
  python -m venv .venv || goto :fail
  call .venv\Scripts\activate.bat || goto :fail
  python -m pip install --upgrade pip || goto :fail
  pip install -r requirements.txt || goto :fail
)
python bridge.py --check
if errorlevel 1 (
  echo.
  echo RONN bridge installed, but Roblox Studio MCP is not enabled yet.
  echo Open Roblox Studio ^> Assistant ^> ... ^> Manage MCP Servers ^> Enable Studio as MCP server.
  echo Then run PAIR_AND_RUN_WINDOWS.bat.
  pause
  exit /b 0
)
echo.
echo RONN Roblox Bridge installed successfully.
echo Run PAIR_AND_RUN_WINDOWS.bat to connect this PC to RONN.
pause
exit /b 0
:fail
echo.
echo Installation failed. No Roblox project was changed.
pause
exit /b 1
