@echo off
REM Builds dist\dossier-setup.exe (Inno Setup 6): first the one-folder program (dist\dossier\, about a second to start), then the
REM installer around it, with redactor_common's installer contract (the update framework). Inno Setup: https://jrsoftware.org/isdl.php
REM (a per-user install is enough). build_exe.bat builds the one-file dist\dossier.exe (the portable download); this does not need it.
REM build_release.bat calls this with --no-pause.

cd /d "%~dp0"
set "PAUSE=pause"
if "%~1"=="--no-pause" set "PAUSE="

set "ISCC="
for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
    if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
    where iscc >nul 2>nul && set "ISCC=iscc"
)
if not defined ISCC (
    echo ERROR: Inno Setup 6 was not found. Install it from https://jrsoftware.org/isdl.php
    %PAUSE%
    exit /b 1
)

REM The family's installer contract (relaunch, update-channel, waiting for Dossier to stop) ships with redactor_common.
set "CONTRACT="
for /f "delims=" %%p in ('python -m redactor_common.release contract-path') do set "CONTRACT=%%p"
if not defined CONTRACT (
    echo ERROR: redactor_common's installer contract was not found ^(python -m redactor_common.release contract-path^).
    %PAUSE%
    exit /b 1
)

echo Building the one-folder program dist\dossier\ ...
set "DOSSIER_BUILD=folder"
python -m PyInstaller dossier.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: the build failed. See above.
    %PAUSE%
    exit /b 1
)
set "DOSSIER_BUILD="

for /f "usebackq delims=" %%L in (`python -c "from dossier.core.version import RELEASE, APP_VERSION; print(RELEASE + ' ' + APP_VERSION)"`) do set "VERSIONS=%%L"
for /f "tokens=1,2" %%A in ("%VERSIONS%") do (
    set "APPRELEASE=%%A"
    set "APPBUILD=%%B"
)

"%ISCC%" /Q /DAppRelease=%APPRELEASE% /DAppBuild=%APPBUILD% "/DUpdateContract=%CONTRACT%" installer\dossier.iss
if errorlevel 1 (
    echo ERROR: the installer build failed. See above.
    %PAUSE%
    exit /b 1
)
echo Done: dist\dossier-setup.exe
%PAUSE%
