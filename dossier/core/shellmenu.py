"""The Windows shell's own right-click menu ("Show more options" in Windows 11), for our menu's last entry.

The menu is built by the shell from the programs that added themselves to it (7-Zip, Git, Defender, "Open with"...), through the
``IContextMenu`` interface. Nothing is installed for this: the calls go straight to the system with ``ctypes``.

Two guards against what a shell extension can do:

* **Everything runs on its own thread**, with its own hidden window and message loop. A slow or stuck extension can never freeze
  Dossier; the window only waits for the answer.
* **Our own commands win.** When the owner picks Cut, Copy, Paste, Delete or Rename, the shell is *not* asked to do it: the choice
  is handed back (``Outcome.verb``) and Dossier runs its own command, with its own conflict dialog, progress, undo and tags.
  Everything else is run by the shell, and the thread stays alive until the windows it opened (Properties, Open with...) are gone.

Only real paths on a drive or share are offered (``can_show``). Windows only.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

IS_WINDOWS = sys.platform == "win32"
OUR_VERBS = ("cut", "copy", "paste", "delete", "rename")
MAX_ITEMS = 500
FIRST_ID, LAST_ID = 1, 0x7FFF

CMF_NORMAL, CMF_EXPLORE, CMF_EXTENDEDVERBS = 0x0, 0x4, 0x100
GCS_VERBW = 4
CMIC_MASK_UNICODE, CMIC_MASK_PTINVOKE = 0x4000, 0x20000000
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x100
SW_SHOWNORMAL = 1
WM_NULL, WM_DRAWITEM, WM_MEASUREITEM, WM_INITMENUPOPUP, WM_MENUCHAR = 0x0, 0x2B, 0x2C, 0x117, 0x120
MENU_MESSAGES = (WM_DRAWITEM, WM_MEASUREITEM, WM_INITMENUPOPUP, WM_MENUCHAR)
PM_REMOVE = 1
WAIT_FOR_DIALOG, MAX_DIALOG_SECONDS = 1.5, 600


@dataclass
class Outcome:
    verb: str = ""          # one of OUR_VERBS: the owner chose it and Dossier must do it
    ran: bool = False       # the shell carried out the owner's choice (the folders may have changed)
    error: str = ""         # something went wrong (the text is for the status line)


def can_show(paths: list) -> bool:
    """Whether the shell menu can be offered for these items: Windows, real paths (not an archive, search result or the Home page),
    all in one folder (the shell builds one menu for the items of one folder)."""
    if not IS_WINDOWS or not paths or len(paths) > MAX_ITEMS:
        return False
    parents = set()
    for p in paths:
        if not isinstance(p, str) or "://" in p or not os.path.isabs(p) or len(os.path.splitdrive(p)[0]) == 0:
            return False
        parents.add(os.path.normcase(os.path.dirname(os.path.normpath(p))))
    return len(parents) == 1


def folder_can_show(folder: str) -> bool:
    """Whether the menu of this folder itself (empty space in the list) can be offered."""
    return bool(IS_WINDOWS and isinstance(folder, str) and "://" not in folder and os.path.isabs(folder)
                and os.path.splitdrive(folder)[0])


# ---------------------------------------------------------------------------------------------------------------------------
if IS_WINDOWS:
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    class CMINVOKECOMMANDINFOEX(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.DWORD), ("hwnd", ctypes.c_void_p), ("lpVerb", ctypes.c_void_p),
                    ("lpParameters", ctypes.c_void_p), ("lpDirectory", ctypes.c_void_p), ("nShow", ctypes.c_int),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", ctypes.c_void_p), ("lpTitle", ctypes.c_void_p),
                    ("lpVerbW", ctypes.c_void_p), ("lpParametersW", ctypes.c_void_p), ("lpDirectoryW", ctypes.c_void_p),
                    ("lpTitleW", ctypes.c_void_p), ("ptInvoke", wintypes.POINT)]

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p), ("hCursor", ctypes.c_void_p),
                    ("hbrBackground", ctypes.c_void_p), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    VP, PVP = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)

    _ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]
    _ole32.CoInitializeEx.argtypes = [VP, wintypes.DWORD]
    _ole32.CoTaskMemFree.argtypes = [VP]
    _shell32.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, VP, PVP, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    _shell32.SHBindToParent.argtypes = [VP, ctypes.POINTER(GUID), PVP, PVP]
    _user32.CreatePopupMenu.restype = VP
    _user32.DestroyMenu.argtypes = [VP]
    _user32.TrackPopupMenuEx.argtypes = [VP, ctypes.c_uint, ctypes.c_int, ctypes.c_int, VP, VP]
    _user32.TrackPopupMenuEx.restype = ctypes.c_int
    _user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    _user32.RegisterClassW.restype = ctypes.c_ushort
    _user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, VP, VP, VP, VP]
    _user32.CreateWindowExW.restype = VP
    _user32.DestroyWindow.argtypes = [VP]
    _user32.DefWindowProcW.argtypes = [VP, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    _user32.DefWindowProcW.restype = ctypes.c_ssize_t
    _user32.SetForegroundWindow.argtypes = [VP]
    _user32.PostMessageW.argtypes = [VP, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    _user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), VP, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.IsWindowVisible.argtypes = [VP]
    _user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, VP]
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = VP
    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, VP, ctypes.c_ssize_t)
    _user32.EnumThreadWindows.argtypes = [wintypes.DWORD, ENUMPROC, ctypes.c_ssize_t]

    def _guid(text: str) -> GUID:
        g = GUID()
        _ole32.CLSIDFromString(text, ctypes.byref(g))
        return g

    IID_IShellFolder = _guid("{000214E6-0000-0000-C000-000000000046}")
    IID_IContextMenu = _guid("{000214E4-0000-0000-C000-000000000046}")
    IID_IContextMenu2 = _guid("{000214F4-0000-0000-C000-000000000046}")
    IID_IContextMenu3 = _guid("{BCFCE0A0-EC17-11D0-8D10-00A0C90F2719}")

    def _method(obj: int, index: int, restype, *argtypes):
        """The ``index``-th method of a COM object, ready to call (``obj`` is passed first)."""
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        function = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])
        return lambda *args: function(obj, *args)

    def _release(obj) -> None:
        if obj:
            _method(obj, 2, ctypes.c_ulong)()

    def _query(obj: int, iid: GUID) -> int:
        out = ctypes.c_void_p()
        hr = _method(obj, 0, ctypes.c_long, ctypes.POINTER(GUID), PVP)(ctypes.byref(iid), ctypes.byref(out))
        return out.value or 0 if hr == 0 else 0

    _local = threading.local()
    _class_lock = threading.Lock()
    _class = {"name": None, "proc": None}

    def _wndproc(hwnd, msg, wparam, lparam):
        handler = getattr(_local, "handler", None)
        if handler is not None and msg in MENU_MESSAGES:
            result = ctypes.c_ssize_t(0)
            try:
                if handler(msg, wparam, lparam, result) == 0:
                    return result.value
            except Exception:   # noqa: BLE001 -- a shell extension that fails in a menu message is not our failure
                pass
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _window_class() -> str:
        with _class_lock:
            if _class["name"] is None:
                proc = WNDPROC(_wndproc)
                cls = WNDCLASSW()
                cls.lpfnWndProc = proc
                cls.hInstance = _kernel32.GetModuleHandleW(None)
                cls.lpszClassName = "DossierShellMenuHost"
                if not _user32.RegisterClassW(ctypes.byref(cls)):
                    raise OSError("cannot register the window class")
                _class["name"], _class["proc"] = cls.lpszClassName, proc          # the callback must stay alive
            return _class["name"]

    class Session:
        """One shell menu for some items of one folder (or for the folder itself). Use inside the thread that created it."""

        def __init__(self, paths: list, background: bool = False) -> None:
            self.paths, self.background = list(paths), background
            self.pcm = self.cm2 = self.cm3 = 0
            self.hwnd = None
            self.hmenu = None
            self._pidls: list = []
            self._folders: list = []
            _ole32.CoInitializeEx(None, 2)                      # a single-threaded apartment: what shell extensions expect
            try:
                self.hwnd = _user32.CreateWindowExW(0x80, _window_class(), "", 0x80000000, 0, 0, 0, 0, None, None,
                                                    _kernel32.GetModuleHandleW(None), None)   # a hidden pop-up: the menu's owner
                if not self.hwnd:
                    raise OSError("cannot create the menu's window")
                self._bind()
            except BaseException:
                self.close()
                raise

        def _pidl(self, path: str) -> int:
            pidl = ctypes.c_void_p()
            hr = _shell32.SHParseDisplayName(os.path.normpath(path), None, ctypes.byref(pidl), 0, None)
            if hr != 0 or not pidl.value:
                raise FileNotFoundError(path)
            self._pidls.append(pidl.value)
            return pidl.value

        def _parent(self, pidl: int):
            folder, child = ctypes.c_void_p(), ctypes.c_void_p()
            hr = _shell32.SHBindToParent(pidl, ctypes.byref(IID_IShellFolder), ctypes.byref(folder), ctypes.byref(child))
            if hr != 0 or not folder.value:
                raise OSError("the shell cannot open the folder")
            self._folders.append(folder.value)
            return folder.value, child.value

        def _bind(self) -> None:
            out = ctypes.c_void_p()
            if self.background:                                  # the menu of the folder itself (empty space in the list)
                folder, child = self._parent(self._pidl(self.paths[0]))
                sub = ctypes.c_void_p()
                hr = _method(folder, 5, ctypes.c_long, VP, VP, ctypes.POINTER(GUID), PVP)(child, None, ctypes.byref(IID_IShellFolder),
                                                                                        ctypes.byref(sub))
                if hr != 0 or not sub.value:
                    raise OSError("the shell cannot open the folder")
                self._folders.append(sub.value)
                hr = _method(sub.value, 8, ctypes.c_long, VP, ctypes.POINTER(GUID), PVP)(self.hwnd, ctypes.byref(IID_IContextMenu),
                                                                                       ctypes.byref(out))
            else:
                children = []
                folder = 0
                for p in self.paths:
                    parent, child = self._parent(self._pidl(p))
                    folder = folder or parent
                    children.append(child)
                array = (ctypes.c_void_p * len(children))(*children)
                hr = _method(folder, 10, ctypes.c_long, VP, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(GUID), PVP, PVP)(
                    self.hwnd, len(children), ctypes.cast(array, ctypes.c_void_p), ctypes.byref(IID_IContextMenu), None,
                    ctypes.byref(out))
            if hr != 0 or not out.value:
                raise OSError("the shell has no menu for this")
            self.pcm = out.value
            self.cm2, self.cm3 = _query(self.pcm, IID_IContextMenu2), _query(self.pcm, IID_IContextMenu3)

        def _handle(self, msg: int, wparam: int, lparam: int, result) -> int:
            if self.cm3:
                return _method(self.cm3, 7, ctypes.c_long, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
                               ctypes.POINTER(ctypes.c_ssize_t))(msg, wparam, lparam, ctypes.byref(result))
            if self.cm2 and msg != WM_MENUCHAR:
                return _method(self.cm2, 6, ctypes.c_long, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)(msg, wparam, lparam)
            return 1

        def fill(self, extended: bool = False) -> int:
            """Let the shell and its extensions fill a pop-up menu; returns the number of commands in it."""
            self.hmenu = _user32.CreatePopupMenu()
            flags = CMF_NORMAL | CMF_EXPLORE | (CMF_EXTENDEDVERBS if extended else 0)
            hr = _method(self.pcm, 3, ctypes.c_long, VP, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint)(
                self.hmenu, 0, FIRST_ID, LAST_ID, flags)
            return max(0, hr & 0xFFFF) if hr >= 0 else 0

        def verb(self, command: int) -> str:
            """The language-independent name of a command ("copy", "delete"...), or "" when it has none."""
            buffer = ctypes.create_unicode_buffer(260)
            hr = _method(self.pcm, 5, ctypes.c_long, ctypes.c_size_t, ctypes.c_uint, VP, ctypes.c_void_p, ctypes.c_uint)(
                command - FIRST_ID, GCS_VERBW, None, ctypes.cast(buffer, ctypes.c_void_p), 260)
            return buffer.value.lower() if hr == 0 else ""

        def choose(self, x: int, y: int) -> int:
            """Show the menu and wait; the command number, or 0 when the owner closed it."""
            _local.handler = self._handle
            try:
                _user32.SetForegroundWindow(self.hwnd)                 # without this a menu does not close when clicked away
                command = _user32.TrackPopupMenuEx(self.hmenu, TPM_RETURNCMD | TPM_RIGHTBUTTON, int(x), int(y), self.hwnd, None)
                _user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            finally:
                _local.handler = None
            return command

        def invoke(self, command: int, x: int, y: int) -> None:
            info = CMINVOKECOMMANDINFOEX()
            info.cbSize = ctypes.sizeof(info)
            info.fMask = CMIC_MASK_UNICODE | CMIC_MASK_PTINVOKE
            info.hwnd = self.hwnd
            info.lpVerb = info.lpVerbW = command - FIRST_ID
            info.nShow = SW_SHOWNORMAL
            info.ptInvoke = wintypes.POINT(int(x), int(y))
            hr = _method(self.pcm, 4, ctypes.c_long, ctypes.c_void_p)(ctypes.byref(info))
            if hr != 0:
                raise OSError(f"the command failed (0x{hr & 0xFFFFFFFF:08X})")

        def pump_while_windows_remain(self) -> None:
            """A command may open a window of its own (Properties, Open with...). It belongs to this thread, so the thread keeps
            answering messages until those windows are closed."""
            thread = _kernel32.GetCurrentThreadId()
            start = time.monotonic()
            seen = False
            msg = wintypes.MSG()
            while time.monotonic() - start < MAX_DIALOG_SECONDS:
                while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    _user32.TranslateMessage(ctypes.byref(msg))
                    _user32.DispatchMessageW(ctypes.byref(msg))
                count = []

                def look(handle, _lparam, found=count) -> bool:
                    if handle != self.hwnd and _user32.IsWindowVisible(handle):
                        found.append(handle)
                    return True
                callback = ENUMPROC(look)
                _user32.EnumThreadWindows(thread, callback, 0)
                if count:
                    seen = True
                elif seen or time.monotonic() - start > WAIT_FOR_DIALOG:
                    return
                time.sleep(0.03)

        def close(self) -> None:
            if self.hmenu:
                _user32.DestroyMenu(self.hmenu)
                self.hmenu = None
            for obj in (self.cm3, self.cm2, self.pcm):
                _release(obj)
            self.cm3 = self.cm2 = self.pcm = 0
            for folder in self._folders:
                _release(folder)
            self._folders = []
            for pidl in self._pidls:
                _ole32.CoTaskMemFree(pidl)
            self._pidls = []
            if self.hwnd:
                _user32.DestroyWindow(self.hwnd)
                self.hwnd = None
            _ole32.CoUninitialize()

        def __enter__(self) -> "Session":
            return self

        def __exit__(self, *exc) -> None:
            self.close()


def cursor_pos() -> tuple:
    """The mouse position in screen pixels, as the shell wants it (Qt's own position is scaled on a high-resolution screen)."""
    if not IS_WINDOWS:
        return 0, 0
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def show(paths: list, x: int, y: int, *, background: bool = False, extended: bool = False) -> Outcome:
    """Show the shell menu at the screen position and carry out the choice. Blocks: call it on a thread (``show_in_thread``)."""
    if not IS_WINDOWS:
        return Outcome(error="The Windows menu exists only on Windows")
    try:
        with Session(paths, background) as session:
            if session.fill(extended) <= 0:
                return Outcome(error="The Windows menu has nothing for this")
            command = session.choose(x, y)
            if command <= 0:
                return Outcome()                                   # closed without a choice
            verb = session.verb(command)
            if verb in OUR_VERBS:
                return Outcome(verb=verb)                          # Dossier does these itself
            session.invoke(command, x, y)
            session.pump_while_windows_remain()
            return Outcome(ran=True)
    except Exception as e:   # noqa: BLE001 -- a broken shell extension must not take the program down
        return Outcome(error=f"The Windows menu failed: {e}")


def show_in_thread(paths: list, x: int, y: int, on_done: Callable[[Outcome], None], *, background: bool = False,
                   extended: bool = False) -> threading.Thread:
    """``show`` on its own thread; ``on_done(outcome)`` is called on that thread when it ends (hand it over to the window)."""
    def work() -> None:
        on_done(show(paths, x, y, background=background, extended=extended))

    thread = threading.Thread(target=work, name="windows-shell-menu", daemon=True)
    thread.start()
    return thread
