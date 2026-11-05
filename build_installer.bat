@echo off
REM Builds dist\dossier-setup.exe (Inno Setup 6) from dist\dossier.exe. Run build_exe.bat first.
REM Inno Setup: https://jrsoftware.org/isdl.php (a per-user install is enough). The release workflow builds the same installer.

cd /d "%~dp0"
if not exist dist\dossier.exe (
    echo ERROR: dist\dossier.exe is missing: run build_exe.bat first.
    pause
    exit /b 1
)

set "ISCC="
for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
    if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
    where iscc >nul 2>nul && set "ISCC=iscc"
)
if not defined ISCC (
    echo ERROR: Inno Setup 6 was not found. Install it from https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

for /f "usebackq delims=" %%L in (`python -c "from dossier.core.version import RELEASE, APP_VERSION; print(RELEASE + ' ' + APP_VERSION)"`) do set "VERSIONS=%%L"
for /f "tokens=1,2" %%A in ("%VERSIONS%") do (
    set "APPRELEASE=%%A"
    set "APPBUILD=%%B"
)

"%ISCC%" /Q /DAppRelease=%APPRELEASE% /DAppBuild=%APPBUILD% installer\dossier.iss
if errorlevel 1 (
    echo ERROR: the installer build failed. See above.
    pause
    exit /b 1
)
echo Done: dist\dossier-setup.exe
pause
