@echo off
rem Double-click this file to try the dashboard on five made-up (synthetic) chats.
rem
rem It imports the test export in tests\fixtures\e2e into a separate demo
rem workspace (workspace\demo), so your real chats are never mixed with it,
rem then opens the dashboard at http://127.0.0.1:8770. Close this window to stop.
rem Delete the workspace\demo folder any time to start the demo afresh.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python isn't set up for this project yet. Double-click TEST_EVERYTHING.bat once
    echo first; it sets everything up. Then double-click this file again.
    pause
    exit /b 1
)

rem KE_WORKSPACE_ROOT points the engine at the demo workspace for this window only.
set "KE_WORKSPACE_ROOT=%~dp0workspace\demo"
echo Importing the demo export (importing it again adds nothing)...
".venv\Scripts\python.exe" -m knowledge_engine.cli.main import "%~dp0tests\fixtures\e2e\export.zip"
if errorlevel 1 (
    echo.
    echo The demo import failed; the messages above say why. Give them to Claude.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m knowledge_engine.cli.main ui --port 8770
pause
