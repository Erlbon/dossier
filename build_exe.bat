@echo off
REM Builds dist\dossier.exe with PyInstaller. Run it on Windows with Python 3.10 or newer on the path.
REM
REM It does not bump the build number (python bump_version.py does) and does not publish anything: a release is made by pushing
REM a tag, v + RELEASE from dossier\core\version.py (see .github\workflows\release.yml).

cd /d "%~dp0"
echo Working directory: %cd%
echo.

python --version
if errorlevel 1 (
    echo.
    echo ERROR: "python" was not found on your PATH. Install Python 3.10 or newer from python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

echo Installing what the program and the build need...
python -m pip install -r requirements.txt "pyinstaller>=6.6"
if errorlevel 1 (
    echo.
    echo ERROR: pip failed: no internet, or a proxy or firewall in the way. The message above says which.
    pause
    exit /b 1
)

echo.
echo Building dist\dossier.exe ...
REM "python -m PyInstaller", not "pyinstaller": the script folder of a per-user Python is often not on the path.
python -m PyInstaller dossier.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: the build failed. See above.
    pause
    exit /b 1
)

echo.
echo Done: dist\dossier.exe
pause
