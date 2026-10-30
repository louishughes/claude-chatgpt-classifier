@echo off
rem Double-click this file to test the whole project.
rem
rem It sets up Python the first time (a private ".venv" folder, git-ignored),
rem runs every check CI runs (the everyday ones, then the nightly ones), and
rem opens a plain-English report in your browser: one green or red line per
rem area, and what to do about a red one. No paid AI is used: every API key is
rem removed and the AI steps use a fake model. It takes about 10-20 minutes.
rem
rem For a faster run without the nightly checks, run "TEST_EVERYTHING.bat --quick".

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setting up Python for this project. This happens once and takes a few minutes...
    py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Python 3.12 or newer wasn't found. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup. Then double-click this file again.
    pause
    exit /b 1
)

echo Installing or updating the project's packages...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -e ".[dev]"
if not errorlevel 1 goto run
rem The install can fail just because there's no internet. If the project is
rem already installed, carry on with what's there instead of stopping.
".venv\Scripts\python.exe" -c "import knowledge_engine, pytest" 2>nul
if errorlevel 1 goto install_failed
echo.
echo Couldn't update the packages (no internet?). Running the checks with the ones already installed.
goto run

:install_failed
echo.
echo Installing the packages failed; the messages above say why. Check the internet
echo connection. This project also needs Python 3.12 or newer: if yours is older,
echo install a newer one, delete the .venv folder, and double-click this file again.
pause
exit /b 1

:run
".venv\Scripts\python.exe" -m knowledge_engine.devtools.test_report %*
set RESULT=%errorlevel%
echo.
if "%RESULT%"=="0" (
    echo All green. The report is open in your browser.
) else (
    echo Some checks are red. The report in your browser says what to do.
)
pause
exit /b %RESULT%
