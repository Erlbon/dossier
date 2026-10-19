import base64
import shutil
import subprocess

import pytest

import dossier.core.terminals as T
from dossier.core.platform import IS_WINDOWS
from dossier.core.terminals import (Launch, Profile, UnsafeArgument, builtin_profiles, custom_profile, default_profile,
                                    detect, quote_for, run_launch, session_launch, to_wsl_path)

CMD = Profile("cmd", "Command Prompt", "cmd", "cmd.exe", ("/k",))
PS = Profile("powershell", "Windows PowerShell", "powershell", "powershell.exe", ("-NoLogo", "-NoExit"))
SH = Profile("login-shell", "Login shell", "posix", "bash", ("-i",))
WSL = Profile("wsl", "WSL", "wsl", "wsl.exe", ())


def fake_which(*present):
    return lambda name: ("/fake/" + name) if name in present else None


# detection -----------------------------------------------------------------------------------------------
def test_builtin_profiles_exist_for_this_system_and_detection_lists_missing_ones():
    assert builtin_profiles()
    found = detect([CMD, PS], which=fake_which("powershell.exe"))
    assert [(p.id, bool(path)) for p, path in found] == [("cmd", False), ("powershell", True)]
    assert default_profile(found).id == "powershell"
    assert default_profile(detect([CMD], which=fake_which())) is None


# quoting: never a second command -------------------------------------------------------------------------------
def test_cmd_quotes_with_double_quotes_and_refuses_what_it_cannot_make_safe():
    assert quote_for(CMD, "a&b.txt") == '"a&b.txt"'
    assert quote_for(CMD, "my file.txt") == '"my file.txt"'
    for bad in ('say "hi".txt', "100%.txt", "a\nb"):
        with pytest.raises(UnsafeArgument):
            quote_for(CMD, bad)


def test_powershell_doubles_every_kind_of_single_quote():
    assert quote_for(PS, "it's") == "'it''s'"
    assert quote_for(PS, "\u2018x\u2019") == "'\u2018\u2018x\u2019\u2019'"
    assert quote_for(PS, "$(calc);`x") == "'$(calc);`x'"


def test_posix_quoting_and_wsl_path_conversion():
    assert quote_for(SH, "a b'c") == "'a b'\"'\"'c'"
    assert to_wsl_path("C:\\Users\\x y") == "/mnt/c/Users/x y"
    assert to_wsl_path("/home/x") == "/home/x"
    with pytest.raises(UnsafeArgument):
        to_wsl_path("\\\\server\\share")
    assert quote_for(WSL, "D:\\a b") == "'/mnt/d/a b'"


def test_a_zero_byte_or_line_break_is_refused_everywhere():
    for p in (CMD, PS, SH):
        for bad in ("a\x00b", "a\nb", "a\rb"):
            with pytest.raises(UnsafeArgument):
                quote_for(p, bad)


HOSTILE = ["plain.txt", "a&b.txt", "x;y", "it's.txt", "$(echo INJECTED)", "`echo INJECTED`", "a|b", "a>b", "a b  c",
           "(paren)", "[bracket].txt", "x&echo INJECTED"]


@pytest.mark.skipif(not shutil.which("powershell"), reason="needs Windows PowerShell")
@pytest.mark.parametrize("name", HOSTILE)
def test_powershell_really_receives_the_name_as_one_word(name):
    cmd = "Write-Output " + quote_for(PS, name)
    launch = run_launch(PS, cmd, ".", which=shutil.which)
    out = subprocess.run(launch.argv, capture_output=True, text=True, timeout=60).stdout.strip()
    assert out == name


@pytest.mark.skipif(not IS_WINDOWS, reason="cmd.exe")
@pytest.mark.parametrize("name", [n for n in HOSTILE if "'" not in n])
def test_cmd_really_receives_the_name_without_running_anything_else(name):
    launch = run_launch(CMD, "echo " + quote_for(CMD, name), ".", which=shutil.which)
    out = subprocess.run(launch.argv, capture_output=True, text=True, timeout=60).stdout
    assert "INJECTED" not in [line.strip() for line in out.splitlines()]
    assert out.strip() == '"' + name + '"'


@pytest.mark.skipif(not shutil.which("sh"), reason="needs a POSIX shell")
@pytest.mark.parametrize("name", HOSTILE)
def test_sh_really_receives_the_name_as_one_word(name):
    sh = Profile("sh", "sh", "posix", "sh")
    launch = run_launch(sh, "printf %s " + quote_for(sh, name), ".", which=shutil.which)
    out = subprocess.run(launch.argv, capture_output=True, text=True, timeout=60).stdout
    assert out == name


# running one command ------------------------------------------------------------------------------------------
def test_run_launches_for_each_kind():
    w = fake_which("cmd.exe", "powershell.exe", "wsl.exe", "bash")
    assert run_launch(CMD, "dir", "C:\\x", w).argv == '/fake/cmd.exe /d /s /c "dir"'
    ps = run_launch(PS, "Get-Date -Format \"x\"", "C:\\x", w).argv
    assert ps[:7] == ["/fake/powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-OutputFormat", "Text",
                      "-EncodedCommand"]
    script = base64.b64decode(ps[7]).decode("utf-16-le")
    assert script.endswith("Get-Date -Format \"x\"") and "SilentlyContinue" in script      # quoting-proof
    assert run_launch(SH, "ls -l", "/tmp", w).argv == ["/fake/bash", "-c", "ls -l"]
    assert run_launch(WSL, "ls", "C:\\x", w).argv == ["/fake/wsl.exe", "--cd", "C:\\x", "--", "bash", "-c", "ls"]


def test_a_custom_profile_needs_its_placeholder_and_substitutes_it():
    p = custom_profile("mytool --dir {dir} --do {command}")
    assert run_launch(p, "go", "/work").argv == "mytool --dir /work --do go"
    with pytest.raises(UnsafeArgument):
        run_launch(custom_profile("mytool"), "go", "/work")
    with pytest.raises(UnsafeArgument):
        session_launch(custom_profile("mytool"), "/work")


# opening a session ----------------------------------------------------------------------------------------------
def test_windows_sessions_with_and_without_windows_terminal_and_elevation(monkeypatch):
    monkeypatch.setattr(T, "IS_WINDOWS", True)
    w = fake_which("powershell.exe", "cmd.exe")
    classic = session_launch(PS, "C:\\Work", which=w)
    assert classic.argv == ["/fake/powershell.exe", "-NoLogo", "-NoExit"] and classic.cwd == "C:\\Work"
    assert not classic.elevate
    hosted = session_launch(CMD, "C:\\Work", windows_terminal="C:\\wt.exe", which=w)
    assert hosted.argv == ["C:\\wt.exe", "-d", "C:\\Work", "/fake/cmd.exe", "/k"]
    admin = session_launch(PS, "C:\\Work", admin=True, which=w)
    assert admin.elevate and admin.program == "/fake/powershell.exe"
    wsl = session_launch(WSL, "C:\\My Work", which=fake_which("wsl.exe"))
    assert wsl.argv == ["/fake/wsl.exe", "--cd", "/mnt/c/My Work"]


def test_linux_sessions_pick_an_emulator_and_admin_means_sudo_inside_the_terminal(monkeypatch):
    monkeypatch.setattr(T, "IS_WINDOWS", False)
    w = fake_which("bash", "gnome-terminal", "konsole", "xterm")
    normal = session_launch(SH, "/srv/x y", which=w)
    assert normal.argv == ["gnome-terminal", "--working-directory=/srv/x y", "--", "/fake/bash", "-i"]
    assert not normal.elevate
    root = session_launch(SH, "/srv", admin=True, which=w)
    assert root.argv[-2:] == ["sudo", "-s"] and not root.elevate        # the password is typed in the terminal
    konsole = session_launch(SH, "/srv", emulator="konsole", which=w)
    assert konsole.argv[:3] == ["konsole", "--workdir", "/srv"]
    xterm = session_launch(SH, "/srv", emulator="xterm", which=w)
    assert xterm.argv[:2] == ["xterm", "-e"]
    with pytest.raises(UnsafeArgument):
        session_launch(SH, "/srv", which=fake_which("bash"))


def test_the_default_launcher_asks_windows_for_runas_and_never_for_a_password(monkeypatch):
    if not IS_WINDOWS:
        pytest.skip("Windows only")
    import ctypes
    calls = []

    class FakeShell32:
        def ShellExecuteW(self, hwnd, verb, file, params, cwd, show):
            calls.append((verb, file, params, cwd))
            return 5            # the user declined the prompt

    class FakeWin:
        shell32 = FakeShell32()

    monkeypatch.setattr(ctypes, "windll", FakeWin(), raising=False)
    with pytest.raises(OSError, match="declined"):
        T.default_launcher(Launch(["powershell.exe", "-NoExit"], "C:\\x", True, "powershell.exe"))
    assert calls == [("runas", "powershell.exe", "-NoExit", "C:\\x")]
