"""A dialog the window opens must not stay in memory after it is closed: every dialog class has the shared base, and opening dialogs again
and again leaves no widgets behind."""
import importlib
import inspect
import os
import pkgutil

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget  # noqa: E402

import dossier.gui as gui_package  # noqa: E402
from dossier.core import properties, quarantine  # noqa: E402
from dossier.core.vfs import LocalFileSystem  # noqa: E402
from dossier.gui.copy_settings import CopySettingsDialog  # noqa: E402
from dossier.gui.dates_links import DatesDialog, LinkDialog  # noqa: E402
from dossier.gui.owned_dialog import OwnedDialog  # noqa: E402
from dossier.gui.properties import PropertiesDialog  # noqa: E402
from dossier.gui.quarantine_ui import QuarantineDialog  # noqa: E402
from dossier.gui.servers import ConnectionDialog  # noqa: E402
from tests.test_gui_commander import app, world  # noqa: E402,F401


def test_every_dialog_class_of_the_window_has_the_shared_base():
    """A new dialog made straight from QDialog would stay in memory for good once it had been opened: this fails until it uses OwnedDialog."""
    plain = []
    for module_info in pkgutil.iter_modules(gui_package.__path__):
        module = importlib.import_module(f"dossier.gui.{module_info.name}")
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(cls, QDialog) and cls is not OwnedDialog and not issubclass(cls, OwnedDialog):
                plain.append(f"{module.__name__}.{name}")
    assert plain == []


def test_an_owned_dialog_deletes_itself_when_it_is_closed(world):
    win, *_ = world

    class Probe(OwnedDialog):
        pass
    from PyQt6 import sip
    dlg = Probe(win)
    assert dlg.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dlg.show()
    dlg.accept()
    assert not sip.isdeleted(dlg)                                       # not at once: the answer can still be read
    for _ in range(3):
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(dlg)


def test_what_the_caller_reads_right_after_exec_is_still_there(world, tmp_path):
    """The deletion waits for the event loop, so the answer of a dialog can be read the moment it has been accepted."""
    win, *_ = world
    dlg = LinkDialog(win, str(tmp_path / "a.txt"), str(tmp_path), False)
    dlg.show()
    dlg.accept()
    kind, target, link, relative = dlg.answer()
    assert target.endswith("a.txt") and link.startswith(str(tmp_path))


def test_opening_and_closing_dialogs_again_and_again_leaves_nothing_behind(world, tmp_path):
    win, *_ = world
    path = str(tmp_path / "a.txt")
    open(path, "w").write("x")
    fs = LocalFileSystem()
    makers = [lambda: ConnectionDialog(win), lambda: DatesDialog(win, [path]), lambda: LinkDialog(win, path, str(tmp_path), False),
              lambda: QuarantineDialog(win, quarantine.Settings(), path), lambda: CopySettingsDialog(win, win.copy_settings()),
              lambda: PropertiesDialog(win, properties.gather(fs, [path]), set())]

    def settle() -> int:
        for _ in range(4):
            QApplication.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return len(win.findChildren(QWidget))

    for make in makers:                                           # one of each first: whatever the window builds lazily is built now
        dlg = make()
        dlg.show()
        dlg.reject()
    start = settle()
    for _ in range(12):
        for make in makers:
            dlg = make()
            dlg.show()
            dlg.reject()
            del dlg
    assert settle() == start


def test_the_messages_and_questions_are_freed_after_use(world, monkeypatch):
    """The window's own message boxes (the real Dialogs class) are made with the window as parent too."""
    from dossier.gui.dialogs import Dialogs
    win, *_ = world
    seen = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: (seen.append(self.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)), 0)[1])
    real = Dialogs(win)
    real.info("t", "x")
    real.confirm("t", "x")
    real.confirm_transfer("t", "x", "OK", False)
    real.ask_resume(["a"])
    real.ask_save("a")
    real.ask_changed_on_disk("a")
    real.ask_error("x")
    assert len(seen) == 7 and all(seen)
