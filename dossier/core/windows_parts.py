"""Parts of Windows that are not in the Start menu, for the tools bar's Add a Program (the owner, 2026-11-07: "No one is going to remember
the exe names").

System, Network, Windows Security, Device Manager, Services and the rest are Settings pages (``ms-settings:about``), consoles
(``devmgmt.msc``) and Control Panel items (``control.exe ncpa.cpl``). The system starts each of them the way the Run box does
(``tools.launch``). A console or a Control Panel item has no icon of its own that Qt can find (it shows a blank page), so each part names
the file that holds its icon and the icon's place in it, written as Windows writes it: ``devmgr.dll,5``. Qt-free; the window reads the
icons (``tools_bar.program_icon``).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Optional

from .startmenu import Node

GROUP = "Windows"
_INDEX = re.compile(r"^(.*),(-?\d+)$")


@dataclass(frozen=True)
class Part:
    name: str
    command: str            # a file under the Windows folder ("System32/devmgmt.msc"), or an address ("ms-settings:about")
    icon: str               # the file that holds the icon, under the Windows folder, with ",index" when it holds several
    args: str = ""
    needs: str = ""         # a file that must be there besides the command (a Control Panel item started by control.exe)


PARTS = (
    Part("Advanced System Settings", "System32/SystemPropertiesAdvanced.exe", "System32/SystemPropertiesAdvanced.exe,0"),
    Part("Computer Management", "System32/compmgmt.msc", "System32/mycomput.dll,2"),
    Part("Control Panel", "System32/control.exe", "System32/control.exe,0"),
    Part("Device Manager", "System32/devmgmt.msc", "System32/devmgr.dll,5"),
    Part("Disk Management", "System32/diskmgmt.msc", "System32/dmdskres.dll,0"),
    Part("Environment Variables", "System32/rundll32.exe", "System32/sysdm.cpl,2", "sysdm.cpl,EditEnvironmentVariables",
         "System32/sysdm.cpl"),
    Part("Event Viewer", "System32/eventvwr.msc", "System32/eventvwr.exe,0"),
    Part("Firewall", "System32/wf.msc", "System32/FirewallControlPanel.dll,0"),
    Part("Installed Apps", "ms-settings:appsfeatures", "System32/appwiz.cpl,0"),
    Part("Network and Internet", "ms-settings:network", "System32/netcenter.dll,0"),
    Part("Network Connections", "System32/control.exe", "System32/netshell.dll,0", "ncpa.cpl", "System32/ncpa.cpl"),
    Part("Power Options", "System32/control.exe", "System32/powercpl.dll,0", "powercfg.cpl", "System32/powercfg.cpl"),
    Part("Registry Editor", "regedit.exe", "regedit.exe,0"),
    Part("Services", "System32/services.msc", "System32/filemgmt.dll,0"),
    Part("Settings", "ms-settings:", "ImmersiveControlPanel/SystemSettings.exe,0"),
    Part("Sound", "System32/control.exe", "System32/mmsys.cpl,0", "mmsys.cpl", "System32/mmsys.cpl"),
    Part("System", "ms-settings:about", "System32/sysdm.cpl,0"),
    Part("Task Manager", "System32/Taskmgr.exe", "System32/Taskmgr.exe,0"),
    Part("Task Scheduler", "System32/taskschd.msc", "System32/miguiresource.dll,1"),
    Part("Windows Security", "windowsdefender:", "System32/wscui.cpl,4"),
    Part("Windows Update", "ms-settings:windowsupdate", "ImmersiveControlPanel/SystemSettings.exe,0"),
)


def _is_address(command: str) -> bool:
    return ":" in command and not os.path.isabs(command) and "/" not in command.split(":", 1)[0]


def _under(root: str, relative: str) -> str:
    return os.path.join(root, *relative.split("/"))


def windows_group(exists: Callable[[str], bool] = os.path.exists, system_root: Optional[str] = None) -> Node:
    """The "Windows" group of Add a Program: a part whose program (or the Control Panel item it opens) is not on this computer is left
    out; a Settings page or another address needs no file. Looks at the disk, so the window calls it on a thread."""
    root = system_root or os.environ.get("SystemRoot") or os.environ.get("windir") or "C:" + os.sep + "Windows"
    children = []
    for part in PARTS:
        command = part.command if _is_address(part.command) else _under(root, part.command)
        if not _is_address(part.command) and not exists(command):
            continue
        if part.needs and not exists(_under(root, part.needs)):
            continue
        children.append(Node(part.name, command, args=part.args, icon=_under(root, part.icon)))
    children.sort(key=lambda n: n.name.casefold())
    return Node(GROUP, "", children)


def icon_spec(spec: str) -> tuple:
    """``(file, index)`` of an icon written as Windows writes it (``devmgr.dll,5``; a negative index is a resource number); the index is
    None for a plain file, whose own icon is meant."""
    m = _INDEX.match(spec or "")
    return (m.group(1), int(m.group(2))) if m else (spec or "", None)
