"""The Windows installer (installer/dossier.iss) and the release on the family's update framework (redactor_common
docs/update-framework.md, 2026-11-07): it installs per user, ships the one-folder build (which starts in a second), includes the shared
installer contract at its end, every build declares its update channel, and the release tool's configuration matches the installer and
publishes both files under the names copies from before the framework (0.7) look for."""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def setting(script, name):
    for line in script.splitlines():
        if line.split("=", 1)[0].strip() == name:
            return line.split("=", 1)[1].strip()
    return None


def release_config():
    from redactor_common import release
    return release.load_config(ROOT)


def test_the_installer_installs_per_user():
    iss = read("installer", "dossier.iss")
    assert setting(iss, "PrivilegesRequired") == "lowest"
    assert setting(iss, "PrivilegesRequiredOverridesAllowed") is None   # no "for all users"
    assert setting(iss, "DefaultDirName") == "{autopf}\\Dossier"          # %LOCALAPPDATA%\Programs\Dossier for a per-user install


def test_the_installer_is_not_called_like_the_exe():
    assert setting(read("installer", "dossier.iss"), "OutputBaseFilename") == "dossier-setup"


def test_the_installer_ships_the_one_folder_build_and_includes_the_update_contract_at_its_end():
    """The contract's event functions run before Dossier's own, and its [Run] entry starts Dossier again after a silent update
    (/relaunch=yes, or 0.7's /RESTARTAPP=1): Dossier's own restart is gone, so the two cannot both start it."""
    iss = read("installer", "dossier.iss")
    assert 'Source: "..\\dist\\dossier\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs' in iss
    assert '#define UpdateExe "dossier.exe"' in iss
    assert iss.rstrip().splitlines()[-1] == "#include UpdateContract"
    assert "RESTARTAPP" not in iss.split("#include UpdateContract")[0].split("[Setup]", 1)[1]
    assert "#error Pass /DUpdateContract" in iss
    assert '"/DUpdateContract=%CONTRACT%"' in read("build_installer.bat")
    assert "redactor_common.release contract-path" in read("build_installer.bat")


def test_the_contract_the_installer_includes_is_there():
    from redactor_common import release
    contract = read(release.contract_path())
    assert "UpdateContractRelaunch" in contract and "{param:RESTARTAPP|0}" in contract and "windows-installer" in contract


def test_every_build_declares_its_update_channel():
    """The one-file exe carries windows-exe inside (it swaps itself); the folder build gets windows-zip beside its exe, which the
    installer's contract overwrites with windows-installer."""
    spec = read("dossier.spec")
    assert 'os.environ.get("DOSSIER_BUILD", "") == "folder"' in spec and "COLLECT(" in spec
    assert 'channel.write("windows-exe\\n")' in spec and "[] if FOLDER else [(CHANNEL, \".\")]" in spec
    assert 'os.path.join(DISTPATH, "dossier", "update-channel")' in spec and 'channel.write("windows-zip\\n")' in spec


def test_the_app_id_never_changes_and_the_release_tool_knows_it():
    """A new AppId would install a second Dossier beside the first instead of upgrading it; the release gate finds the scratch install
    (and refuses to run beside a real one) by the same id."""
    app_id = setting(read("installer", "dossier.iss"), "AppId")
    assert app_id == "{{C61A77AD-D4A2-44EB-8CFB-B15A58A735F3}"
    assert release_config().installer_app_id == app_id[1:]                     # "{{" is Inno Setup's escaped "{"


def test_the_release_publishes_the_exe_and_the_installer_under_the_names_0_7_looks_for():
    from dossier.core import version
    cfg = release_config()
    assert (cfg.app, cfg.repo, cfg.exe) == ("dossier", "Erlbon/dossier", "dossier.exe")
    assert {channel: path.name for channel, path in cfg.package_paths().items()} == {
        "windows-installer": "dossier-setup.exe", "windows-exe": "dossier.exe"}
    assert cfg.version == version.APP_VERSION and cfg.tag == version.release_tag()
    assert cfg.release_title == f"Dossier {version.RELEASE} (build {version.APP_VERSION})"
    assert cfg.fill(cfg.notes) == version.release_notes()
    assert cfg.build == ["build_release.bat", "--no-pause"]
    script = read("build_release.bat")
    assert "dossier.spec" in script and 'build_installer.bat" --no-pause' in script
    assert script.index("release_check.py before") < script.index("PyInstaller") < script.index("release_check.py after")


def test_github_actions_no_longer_release():
    """The release tool pushes the tag; a workflow on that tag would publish a second, different build over the gated one."""
    folder = os.path.join(ROOT, ".github", "workflows")
    for name in os.listdir(folder):
        assert not re.search(r"(?m)^\s*tags:", read(".github", "workflows", name)), name


def test_a_release_number_already_released_under_another_build_is_refused():
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_check", os.path.join(ROOT, "tools", "release_check.py"))
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    released = [{"name": "Dossier 0.7 (build 2026-11-06#06)", "tagName": "v2026-11-06-06"}]
    assert "already released as v2026-11-06-06" in check.taken(released, tag="v2026-11-07-01", release="0.7")
    assert check.taken(released, tag="v2026-11-06-06", release="0.7") == ""        # the same build again: a re-run
    assert check.taken(released, tag="v2026-11-07-01", release="0.8") == ""
