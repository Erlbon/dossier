"""The Windows installer (installer/dossier.iss) must keep Help > Check for Updates working: it installs per user (a folder the program
can write, so the updater can swap dossier.exe), it never takes the name dossier.exe for itself (that is the asset the updater
downloads), and the release publishes both."""
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


def test_the_installer_installs_per_user_where_the_updater_can_write():
    iss = read("installer", "dossier.iss")
    assert setting(iss, "PrivilegesRequired") == "lowest"
    assert setting(iss, "PrivilegesRequiredOverridesAllowed") is None   # no "for all users": Program Files is not writable
    assert setting(iss, "DefaultDirName") == "{autopf}\\Dossier"          # %LOCALAPPDATA%\Programs\Dossier for a per-user install


def test_the_installer_is_not_called_like_the_update_asset():
    iss = read("installer", "dossier.iss")
    assert setting(iss, "OutputBaseFilename") == "dossier-setup"
    assert 'Source: "..\\dist\\dossier.exe"; DestDir: "{app}"' in iss


def test_the_app_id_never_changes():
    """A new AppId would install a second Dossier beside the first instead of upgrading it."""
    assert setting(read("installer", "dossier.iss"), "AppId") == "{{C61A77AD-D4A2-44EB-8CFB-B15A58A735F3}"


def test_the_release_publishes_the_exe_and_the_installer():
    workflow = read(".github", "workflows", "release.yml")
    assert "installer\\dossier.iss" in workflow
    assert workflow.count("dist/dossier.exe dist/dossier-setup.exe") == 2
