"""The Windows installer (installer/dossier.iss) must keep Help > Check for Updates working: it installs per user, it ships the one-folder
build (which starts in a second), it never takes the name dossier.exe for itself (the asset a bare copy's update downloads), an update it
runs silently starts Dossier again, and the release publishes both files."""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def setting(script, name):
    for line in script.splitlines():
        if line.split("=", 1)[0].strip() == name:
            return line.split("=", 1)[1].strip()
    return None


def test_the_installer_installs_per_user():
    iss = read("installer", "dossier.iss")
    assert setting(iss, "PrivilegesRequired") == "lowest"
    assert setting(iss, "PrivilegesRequiredOverridesAllowed") is None   # no "for all users"
    assert setting(iss, "DefaultDirName") == "{autopf}\\Dossier"          # %LOCALAPPDATA%\Programs\Dossier for a per-user install


def test_the_installer_is_not_called_like_the_update_asset():
    assert setting(read("installer", "dossier.iss"), "OutputBaseFilename") == "dossier-setup"


def test_the_installer_ships_the_one_folder_build_and_restarts_after_a_silent_update():
    """An update run by Check for Updates passes RESTARTAPP=1 (redactor_common selfupdate.installer_command); only then does the
    installer start Dossier itself, since a silent run skips the usual "Start Dossier" box."""
    iss = read("installer", "dossier.iss")
    assert 'Source: "..\\dist\\dossier\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs' in iss
    assert "Check: RestartAfterUpdate" in iss and "{param:RESTARTAPP|0}" in iss
    spec = read("dossier.spec")
    assert 'os.environ.get("DOSSIER_BUILD", "") == "folder"' in spec and "COLLECT(" in spec


def test_the_app_id_never_changes():
    """A new AppId would install a second Dossier beside the first instead of upgrading it."""
    assert setting(read("installer", "dossier.iss"), "AppId") == "{{C61A77AD-D4A2-44EB-8CFB-B15A58A735F3}"


def test_the_release_builds_both_and_publishes_the_exe_and_the_installer():
    workflow = read(".github", "workflows", "release.yml")
    assert "installer\\dossier.iss" in workflow
    assert "DOSSIER_BUILD=folder python -m PyInstaller dossier.spec" in workflow
    assert workflow.count("dist/dossier.exe dist/dossier-setup.exe") == 2
