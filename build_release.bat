@echo off
REM Builds everything a release publishes: dist\dossier.exe (the one-file portable download, update channel windows-exe) and
REM dist\dossier-setup.exe (the installer around the one-folder build, channel windows-installer). Then the built programs are tried.
REM
REM Not run by hand for a release: python -m redactor_common.release publish runs it (pyproject.toml [tool.redactor-release]) with this
REM repository's .venv first on PATH, then writes update-manifest.json, publishes a pre-release, runs the update gate and only then
REM makes the release Latest. See CLAUDE.md, "To release".

cd /d "%~dp0"
set "PAUSE=pause"
if "%~1"=="--no-pause" set "PAUSE="

python tools\release_check.py before
if errorlevel 1 (
    %PAUSE%
    exit /b 1
)

python -m pip install -q "pyinstaller>=6.6"
if errorlevel 1 (
    echo ERROR: pip could not install PyInstaller. The message above says why.
    %PAUSE%
    exit /b 1
)

echo Building dist\dossier.exe ...
python -m PyInstaller dossier.spec --noconfirm
if errorlevel 1 (
    echo ERROR: the build failed. See above.
    %PAUSE%
    exit /b 1
)

call "%~dp0build_installer.bat" --no-pause
if errorlevel 1 (
    %PAUSE%
    exit /b 1
)

python tools\release_check.py after
if errorlevel 1 (
    %PAUSE%
    exit /b 1
)
echo Done: dist\dossier.exe and dist\dossier-setup.exe
%PAUSE%
