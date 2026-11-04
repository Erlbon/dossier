"""The window's thread never touches the disk (code review 2026-11-04, F2, F5, F6, F8, F10): every command below used to look at
the disk on it, which froze the window for as long as a slow share or a hung server took to answer."""
import threading
import zipfile

import pytest

pytest.importorskip("PyQt6")

from dossier.core import archives  # noqa: E402
from dossier.gui import batch_rename as batch_rename_module, compare_folders as compare_module, main_window as main_module  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def recorder(where: list, result):
    """A stand-in that notes whether it ran on the window's (main) thread, then returns ``result``."""
    def fn(*_a, **_k):
        where.append(threading.current_thread() is threading.main_thread())
        return result(*_a, **_k) if callable(result) else result
    return fn


def put_cursor(win, name):
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of(name) >= 0)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of(name), 0))


def test_delete_and_rename_are_planned_on_a_thread(world, monkeypatch):
    win, d, left, right, tmp = world
    (left / "a.txt").write_text("A")
    put_cursor(win, "a.txt")
    where = []
    monkeypatch.setattr(main_module, "plan_delete", recorder(where, main_module.plan_delete))
    d.confirm_answer = False                                                     # asked, and kept
    win.delete()
    pump(win, lambda: d.confirms)
    monkeypatch.setattr(main_module, "plan_rename", recorder(where, main_module.plan_rename))
    d.texts = ["b.txt"]
    win.rename()
    pump(win, lambda: (left / "b.txt").exists())
    assert where == [False, False]


def test_batch_rename_is_planned_on_a_thread(world, monkeypatch):
    win, d, left, right, tmp = world
    (left / "a.txt").write_text("A")
    where = []
    monkeypatch.setattr(batch_rename_module, "plan_rename_many", recorder(where, batch_rename_module.plan_rename_many))
    win._apply_renames([(str(left / "a.txt"), "z.txt")])
    pump(win, lambda: (left / "z.txt").exists())
    assert where == [False]


def test_synchronize_is_planned_on_a_thread(world, monkeypatch):
    win, d, left, right, tmp = world
    where = []
    monkeypatch.setattr(compare_module.sync, "summarise", lambda actions: None)
    monkeypatch.setattr(compare_module.sync, "build_plans", recorder(where, []))
    win.compare_action(None, str(left), str(right), "sync", ["one action"])
    pump(win, lambda: where and not win._plans)
    assert where == [False]


def test_undo_and_new_folder_run_on_a_thread(world, monkeypatch):
    win, d, left, right, tmp = world
    where = []
    real_mkdir = win.fs.mkdir
    monkeypatch.setattr(win.fs, "mkdir", recorder(where, real_mkdir))
    d.texts = ["made"]
    win.new_folder()
    pump(win, lambda: (left / "made").is_dir() and win.left.current_name() == "made")
    monkeypatch.setattr(win.undo_log, "undo_last", recorder(where, win.undo_log.undo_last))
    win.undo()
    pump(win, lambda: not (left / "made").exists())
    assert where == [False, False]


def test_enter_on_an_archive_reads_it_on_a_thread(world, monkeypatch):
    win, d, left, right, tmp = world
    with zipfile.ZipFile(left / "pack.zip", "w") as z:
        z.writestr("inside.txt", "x")
    put_cursor(win, "pack.zip")
    where = []
    monkeypatch.setattr(archives, "opens_by_name", recorder(where, archives.opens_by_name))
    win.left.open_current()
    pump(win, lambda: win.left.path.startswith("zip://") and win.left.model.row_of("inside.txt") >= 0)
    assert where == [False]


def test_f3_f4_and_enter_read_the_file_on_a_thread(world, monkeypatch):
    """F3 looked at every marked item and listed a picture's whole folder, F4 read the file, and Enter read its first bytes: all on
    the window's thread, which a slow share froze."""
    from dossier.core import viewmodes
    from dossier.gui import open_files as open_files_module
    from tests.helpers import settle
    win, d, left, right, tmp = world
    (left / "a.txt").write_text("A")
    put_cursor(win, "a.txt")
    where = []
    monkeypatch.setattr(viewmodes, "mode_for", recorder(where, viewmodes.mode_for))
    win.view_file()
    settle(win)
    assert where[0] is False and len(win.viewers) == 1           # (the viewer window then reads its own first page: still to do)
    where.clear()
    monkeypatch.setattr(main_module, "load_document", recorder(where, main_module.load_document))
    win.edit_file()
    settle(win)
    assert where == [False] and len(win.editors) == 1
    monkeypatch.setattr(open_files_module.viewmodes, "opens_in_viewer", recorder(where, lambda *a, **k: True))
    win._open_file(str(left / "a.txt"))
    settle(win)
    assert where[:2] == [False, False]
    for w in list(win.editors) + list(win.viewers):
        w.close()
