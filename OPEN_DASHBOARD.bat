@echo off
rem Double-click this file to open the Knowledge Engine dashboard on YOUR chats.
rem
rem It opens the local web pages (http://127.0.0.1:8765) in your browser. They
rem run on this computer only. Your export is only ever read, never changed.
rem Uses ke.toml if you have one. Close this window to stop the dashboard.
rem
rem To try it on made-up chats first, use OPEN_DEMO_DASHBOARD.bat instead.
rem The click-through checklist is in docs\TESTING.md.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python isn't set up for this project yet. Double-click TEST_EVERYTHING.bat once
    echo first; it sets everything up. Then double-click this file again.
    pause
    exit /b 1
)

set CONFIG=
if exist "ke.toml" set CONFIG=--config ke.toml
".venv\Scripts\python.exe" -m knowledge_engine.cli.main %CONFIG% ui
pause
