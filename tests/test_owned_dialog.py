"""A dialog the window opens must not stay in memory after it is closed, and the caller must still be able to read the answer after exec() returns.
These tests use the REAL exec() (closed by a timer from inside it): a test double for exec() once hid that Qt deletes a delete-on-close dialog the
moment exec() returns."""
import importlib
import inspect
import pkgutil

import pytest

pytest.importorskip("PyQt6")

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QCoreApplication, QEventLoop, QEvent, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget  # noqa: E402

import dossier.gui as gui_package  # noqa: E402
from dossier.core import properties, quarantine  # noqa: E402
from dossier.core.vfs import LocalFileSystem  # noqa: E402
from dossier.gui.copy_settings import CopySettingsDialog  # noqa: E402
from dossier.gui.dates_links import DatesDialog, LinkDialog  # noqa: E402
from dossier.gui.dialogs import Dialogs  # noqa: E402
from dossier.gui.owned_dialog import OwnedDialog  # noqa: E402
from dossier.gui.properties import PropertiesDialog  # noqa: E402
from dossier.gui.quarantine_ui import QuarantineDialog  # noqa: E402
from dossier.gui.servers import ConnectionDialog  # noqa: E402
from tests.test_gui_commander import app, world  # noqa: E402,F401


def settle() -> None:
    for _ in range(4):
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_every_dialog_class_of_the_window_has_the_shared_base():
    """A new dialog made straight from QDialog would stay in memory for good once it had been opened: this fails until it uses OwnedDialog."""
    plain = []
    for module_info in pkgutil.iter_modules(gui_package.__path__):
        module = importlib.import_module(f"dossier.gui.{module_info.name}")
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(cls, QDialog) and cls is not OwnedDialog and not issubclass(cls, OwnedDialog):
                plain.append(f"{module.__name__}.{name}")
    assert plain == []


def in_the_event_loop(scenario) -> None:
    """Run ``scenario()`` from inside a running event loop, the way the window's own code runs (a handler called by the main loop)."""
    outer = QEventLoop()
    failure = []

    def go() -> None:
        try:
            scenario()
        except BaseException as error:                             # noqa: BLE001 -- handed to the test below
            failure.append(error)
        finally:
            outer.quit()
    QTimer.singleShot(0, go)
    outer.exec()
    if failure:
        raise failure[0]


def test_what_the_caller_reads_right_after_a_real_exec_is_still_there_and_the_dialog_goes_afterwards(world, tmp_path):
    win, *_ = world
    dlg = LinkDialog(win, str(tmp_path / "a.txt"), str(tmp_path), False)

    def scenario() -> None:
        QTimer.singleShot(0, dlg.accept)
        assert dlg.exec() == QDialog.DialogCode.Accepted
        kind, target, link, relative = dlg.answer()                # reads the line edits: they must still exist
        assert target.endswith("a.txt") and link.startswith(str(tmp_path)) and not sip.isdeleted(dlg)
        inner = QEventLoop()                                       # a nested loop (a follow-up dialog) must not delete it early either
        QTimer.singleShot(0, inner.quit)
        inner.exec()
        QApplication.processEvents()
        assert not sip.isdeleted(dlg)
        kind, target, link, relative = dlg.answer()
    in_the_event_loop(scenario)
    settle()
    assert sip.isdeleted(dlg)                                      # and once control is back in the caller's own loop, it is gone


def test_a_dialog_shown_without_exec_is_deleted_when_it_is_closed(world):
    win, *_ = world

    class Probe(OwnedDialog):
        pass
    dlg = Probe(win)
    dlg.show()
    dlg.accept()
    assert not sip.isdeleted(dlg)
    settle()
    assert sip.isdeleted(dlg)


def test_opening_and_closing_dialogs_again_and_again_through_a_real_exec_leaves_nothing_behind(world, tmp_path):
    win, *_ = world
    path = str(tmp_path / "a.txt")
    open(path, "w").write("x")
    fs = LocalFileSystem()
    makers = [lambda: ConnectionDialog(win), lambda: DatesDialog(win, [path]), lambda: LinkDialog(win, path, str(tmp_path), False),
              lambda: QuarantineDialog(win, quarantine.Settings(), path), lambda: CopySettingsDialog(win, win.copy_settings()),
              lambda: PropertiesDialog(win, properties.gather(fs, [path]), set())]

    def open_and_close(make, accept: bool) -> None:
        dlg = make()
        QTimer.singleShot(0, dlg.accept if accept else dlg.reject)
        dlg.exec()

    for make in makers:                                            # one of each first: whatever the window builds lazily is built now
        open_and_close(make, False)
    settle()
    start = len(win.findChildren(QWidget))
    for n in range(10):
        for make in makers:
            open_and_close(make, n % 2 == 0)
    settle()
    assert len(win.findChildren(QWidget)) == start


def test_the_messages_and_questions_work_through_a_real_exec_and_are_freed(world):
    """The window's own boxes read the clicked button after exec(): that has to keep working, and the boxes must not pile up."""
    win, *_ = world
    real = Dialogs(win)

    def press(label_part: str) -> None:
        def click():
            box = QApplication.activeModalWidget()
            assert isinstance(box, QMessageBox)
            button = next(b for b in box.buttons() if label_part in b.text().replace("&", ""))
            button.click()
        QTimer.singleShot(50, click)

    press("OK")
    assert real.confirm("Title", "Do it?", "OK") is True
    press("Cancel")
    assert real.confirm("Title", "Do it?", "OK") is False
    press("OK")
    real.info("Title", "text")
    settle()
    before = len(win.findChildren(QMessageBox))
    for _ in range(8):
        press("OK")
        real.confirm("Title", "Do it?", "OK")
    settle()
    assert len(win.findChildren(QMessageBox)) == before
