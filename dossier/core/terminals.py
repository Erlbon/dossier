"""Interpreter profiles and terminal sessions (docs/terminals-plan.md).

A profile says how to run one command (for the command line under the panels) and how to open an
interactive session in a folder (the "Terminal here" buttons). Nothing here starts a process: it
builds a ``Launch`` that a launcher runs, so every case can be tested without opening a window.

Rights: Dossier never raises its own. ``admin=True`` asks the system for an elevated *terminal*
(the UAC prompt on Windows, ``sudo -s`` typed inside the terminal elsewhere); the password never
passes through Dossier.
"""
from __future__ import annotations

import base64
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

from .platform import IS_WINDOWS

Which = Callable[[str], Optional[str]]


class UnsafeArgument(ValueError):
    """A name that cannot be passed to the chosen interpreter without risking a second command."""


@dataclass(frozen=True)
class Profile:
    id: str
    title: str
    kind: str                    # cmd | powershell | posix | wsl | custom
    program: str                 # the executable looked up on the path
    session_args: tuple = ()     # arguments that make it interactive and keep it open
    template: str = ""           # custom profiles only: a command with {dir} (session) or {command} (run)


@dataclass(frozen=True)
class Launch:
    """What a launcher must do: ``argv`` (a list, or one string on Windows), the folder, and whether
    the system should ask for administrator rights first."""
    argv: object
    cwd: str
    elevate: bool = False
    program: str = ""            # the executable for the elevated path


# profiles ------------------------------------------------------------------------------------------
WINDOWS_PROFILES = (
    Profile("powershell", "Windows PowerShell", "powershell", "powershell.exe", ("-NoLogo", "-NoExit")),
    Profile("pwsh", "PowerShell 7", "powershell", "pwsh.exe", ("-NoLogo", "-NoExit")),
    Profile("cmd", "Command Prompt", "cmd", "cmd.exe", ("/k",)),
    Profile("gitbash", "Git Bash", "posix", "bash.exe", ("--login", "-i")),
    Profile("wsl", "WSL", "wsl", "wsl.exe", ()),
)
POSIX_PROFILES = (
    Profile("login-shell", "Login shell", "posix", os.environ.get("SHELL", "sh") or "sh", ("-i",)),
    Profile("pwsh", "PowerShell 7", "powershell", "pwsh", ("-NoLogo", "-NoExit")),
)
EMULATORS = ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "kitty", "alacritty", "xterm")


def builtin_profiles() -> list:
    return list(WINDOWS_PROFILES if IS_WINDOWS else POSIX_PROFILES)


def custom_profile(template: str, title: str = "Custom") -> Profile:
    return Profile("custom", title, "custom", "", (), template)


def detect(profiles: list, which: Which = shutil.which) -> list:
    """``[(profile, found_path_or_None)]``. A profile whose program is missing is listed, not hidden,
    so the settings can say why it is unavailable."""
    return [(p, which(p.program) if p.program else "custom") for p in profiles]


def default_profile(found: list) -> Optional[Profile]:
    """The first profile that is available."""
    return next((p for p, path in found if path), None)


# quoting -----------------------------------------------------------------------------------------------
_PS_QUOTES = "'\u2018\u2019\u201a\u201b"      # PowerShell treats all of these as a single quote


def quote_for(profile: Profile, arg: str) -> str:
    """``arg`` as one literal word for ``profile``'s interpreter. Refuses what it cannot make safe
    rather than guessing: a file called ``a&b`` must stay a name, never become a command."""
    if "\x00" in arg or "\n" in arg or "\r" in arg:
        raise UnsafeArgument("a name with a line break or a zero byte cannot be used in a command")
    if profile.kind == "cmd":
        if any(c in arg for c in '"%'):
            raise UnsafeArgument('Command Prompt cannot take a name with " or % safely; use PowerShell')
        return '"' + arg + '"'
    if profile.kind == "powershell":
        return "'" + "".join(c + c if c in _PS_QUOTES else c for c in arg) + "'"
    if profile.kind == "wsl":
        return shlex.quote(to_wsl_path(arg))
    return shlex.quote(arg)


def to_wsl_path(path: str) -> str:
    """``C:\\Users\\x`` to ``/mnt/c/Users/x`` for WSL. Anything else (a UNC path, a relative one) is
    refused: WSL cannot see it under a predictable name."""
    if len(path) >= 3 and path[1] == ":" and path[2] in "\\/" and path[0].isalpha():
        return "/mnt/" + path[0].lower() + "/" + path[3:].replace("\\", "/")
    if path.startswith("/"):
        return path
    raise UnsafeArgument(f"WSL cannot reach {path}")


# running one command (the command line) ------------------------------------------------------------------
def run_launch(profile: Profile, command: str, cwd: str, which: Which = shutil.which) -> Launch:
    """How to run ``command`` once, with output captured and no console window."""
    exe = which(profile.program) or profile.program if profile.program else ""
    if profile.kind == "cmd":
        return Launch(f'{exe or "cmd.exe"} /d /s /c "{command}"', cwd)
    if profile.kind == "powershell":
        # Encoded, so no quoting can break it. No progress records and plain text output: otherwise a
        # redirected -EncodedCommand run prints XML ("#< CLIXML") into the output.
        script = "$ProgressPreference='SilentlyContinue'; " + command
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return Launch([exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-OutputFormat", "Text",
                       "-EncodedCommand", encoded], cwd)
    if profile.kind == "wsl":
        return Launch([exe, "--cd", cwd, "--", "bash", "-c", command], cwd)
    if profile.kind == "custom":
        if "{command}" not in profile.template:
            raise UnsafeArgument("the custom profile has no {command} in its template")
        return Launch(profile.template.replace("{command}", command).replace("{dir}", cwd), cwd)
    return Launch([exe, "-c", command], cwd)


# opening a session in a folder ------------------------------------------------------------------------------
def session_launch(profile: Profile, cwd: str, *, admin: bool = False, windows_terminal: Optional[str] = None,
                   emulator: Optional[str] = None, which: Which = shutil.which) -> Launch:
    """How to open an interactive session of ``profile`` in ``cwd``.

    ``windows_terminal`` is the path of ``wt.exe`` if it should host the session; ``emulator`` names the
    Linux terminal program (default: the first of EMULATORS found). ``admin`` asks for an elevated
    terminal: ``runas`` on Windows, ``sudo -s`` as the terminal's first command elsewhere."""
    exe = (which(profile.program) or profile.program) if profile.program else ""
    if profile.kind == "custom":
        if "{dir}" not in profile.template:
            raise UnsafeArgument("the custom profile has no {dir} in its template")
        return Launch(profile.template.replace("{dir}", cwd), cwd, admin, "")
    inner = [exe, *profile.session_args]
    if profile.kind == "wsl":
        inner = [exe, "--cd", to_wsl_path(cwd)]
    if IS_WINDOWS:
        if windows_terminal:
            return Launch([windows_terminal, "-d", cwd, *inner], cwd, admin, windows_terminal)
        return Launch(inner, cwd, admin, exe)
    name = emulator or next((e for e in EMULATORS if which(e)), "")
    if not name:
        raise UnsafeArgument("no terminal program was found; choose one in the settings")
    root = ["sudo", "-s"] if admin else []
    flags = {
        "gnome-terminal": [name, f"--working-directory={cwd}", "--", *(root or inner)],
        "konsole": [name, "--workdir", cwd, "-e", *(root or inner)],
        "xfce4-terminal": [name, f"--working-directory={cwd}", "-x", *(root or inner)],
        "kitty": [name, "-d", cwd, *(root or inner)],
        "alacritty": [name, "--working-directory", cwd, "-e", *(root or inner)],
    }
    argv = flags.get(os.path.basename(name), [name, "-e", *(root or inner)])   # xterm and the generic wrapper
    return Launch(argv, cwd, False)


def default_launcher(launch: Launch) -> None:
    """Start it. The elevated path asks Windows to show its own prompt; Dossier never sees a password."""
    if launch.elevate and IS_WINDOWS:
        import ctypes
        argv = launch.argv if isinstance(launch.argv, list) else [launch.argv]
        params = subprocess.list2cmdline(argv[1:]) if len(argv) > 1 else ""
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", launch.program or argv[0], params, launch.cwd, 1)
        if result <= 32:      # 5 = the user declined the prompt
            raise OSError("the administrator terminal was not started" + (" (declined)" if result == 5 else ""))
        return
    flags = subprocess.CREATE_NEW_CONSOLE if IS_WINDOWS and not str(launch.argv[0]).endswith("wt.exe") else 0
    subprocess.Popen(launch.argv, cwd=launch.cwd, creationflags=flags, close_fds=True)
