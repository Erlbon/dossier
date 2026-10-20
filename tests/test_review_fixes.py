"""Fixes from the code review of 2026-10-20: overwrite order and undo, a shrinking source, read-only files, roots and
trailing separators, Office files on Enter, and the other panel still opening a folder."""
import errno
import os
import shutil
import stat
import threading
import types

import pytest

from dossier.core import archives, ops as ops_module, transfer
from dossier.core.memfs import MemoryFileSystem
from dossier.core.ops import Resolution, execute, plan_copy, plan_delete, plan_move
from dossier.core.undo_log import UndoLog
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()


class Bin:
    """A recycle bin that keeps what it is given, under the name it was given."""

    def __init__(self, folder):
        self.folder = folder
        self.items = []

    def __call__(self, path):
        os.makedirs(self.folder, exist_ok=True)
        shutil.move(path, os.path.join(self.folder, os.path.basename(path)))
        self.items.append(os.path.basename(path))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def work(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    return tmp_path


def overwrite_plan(work, name="a.txt"):
    return plan_copy(fs, [str(work / "src" / name)], str(work / "dst")).resolve(Resolution.OVERWRITE, fs)


# the overwrite path (findings 1 and 2) ------------------------------------------------------------------------
def test_an_overwrite_puts_the_old_file_in_the_bin_only_after_the_new_one_is_in_place(work):
    write(work / "src" / "a.txt", "NEW")
    write(work / "dst" / "a.txt", "OLD")
    bin_ = Bin(work / "bin")
    res = execute(overwrite_plan(work), fs, trasher=bin_)
    assert not res.failed and read(work / "dst" / "a.txt") == "NEW"
    assert bin_.items == ["a.txt.dossier-old"] and read(work / "bin" / "a.txt.dossier-old") == "OLD"
    assert sorted(os.listdir(work / "dst")) == ["a.txt"]                       # no set-aside file is left behind


def test_a_failed_overwrite_leaves_the_old_file_exactly_where_it_was(work):
    write(work / "src" / "a.txt", "NEW")
    write(work / "dst" / "a.txt", "OLD")
    plan = overwrite_plan(work)
    os.remove(work / "src" / "a.txt")                                          # the source vanishes between plan and run
    bin_ = Bin(work / "bin")
    res = execute(plan, fs, trasher=bin_)
    assert [r.status for r in res.results] == ["failed"]
    assert read(work / "dst" / "a.txt") == "OLD" and bin_.items == []
    assert sorted(os.listdir(work / "dst")) == ["a.txt"]                       # no part file, no set-aside file


class FailingRename(MemoryFileSystem):
    """The last step, putting the new file in place, fails."""

    def rename(self, src, dst, *, overwrite=False):
        if self.basename(src).endswith(".dossier-part"):
            raise OSError(errno.EACCES, "locked", dst)
        return super().rename(src, dst, overwrite=overwrite)


def test_when_the_final_step_fails_the_old_file_is_put_back():
    mem = FailingRename()
    mem.put("mem://src/a.txt", b"NEW")
    mem.put("mem://dst/a.txt", b"OLD")
    plan = plan_copy(mem, ["mem://src/a.txt"], "mem://dst").resolve(Resolution.OVERWRITE, mem)
    binned = []
    res = execute(plan, mem, trasher=lambda p: binned.append(p))
    assert [r.status for r in res.results] == ["failed"] and binned == []
    with mem.open_read("mem://dst/a.txt") as f:
        assert f.read() == b"OLD"
    assert sorted(e.name for e in mem.list("mem://dst")) == ["a.txt"]


def test_a_move_over_an_existing_file_also_keeps_the_old_one_until_it_succeeds(work):
    write(work / "src" / "a.txt", "NEW")
    write(work / "dst" / "a.txt", "OLD")
    plan = plan_move(fs, [str(work / "src" / "a.txt")], str(work / "dst")).resolve(Resolution.OVERWRITE, fs)
    bin_ = Bin(work / "bin")
    res = execute(plan, fs, trasher=bin_)
    assert not res.failed and read(work / "dst" / "a.txt") == "NEW" and not (work / "src" / "a.txt").exists()
    assert bin_.items == ["a.txt.dossier-old"]
    # and one that fails (the source is gone) leaves the target alone
    write(work / "src" / "b.txt", "NEW-B")
    write(work / "dst" / "b.txt", "OLD-B")
    plan = plan_move(fs, [str(work / "src" / "b.txt")], str(work / "dst")).resolve(Resolution.OVERWRITE, fs)
    os.remove(work / "src" / "b.txt")
    res = execute(plan, fs, trasher=Bin(work / "bin2"))
    assert [r.status for r in res.results] == ["failed"] and read(work / "dst" / "b.txt") == "OLD-B"


def test_an_overwrite_has_no_undo_so_nothing_is_deleted_behind_the_user(work):
    write(work / "src" / "a.txt", "NEW")
    write(work / "dst" / "a.txt", "OLD")
    log = UndoLog()
    execute(overwrite_plan(work), fs, trasher=Bin(work / "bin"), undo_log=log)
    assert len(log) == 0 and log.undo_last(fs) is None
    assert read(work / "dst" / "a.txt") == "NEW"                              # the new file stays; the old is in the bin
    assert read(work / "bin" / "a.txt.dossier-old") == "OLD"


# a source that shrinks (finding 3) ----------------------------------------------------------------------------
class Shrinking(MemoryFileSystem):
    """Says the file is 3000 bytes, then only delivers 1000 of them."""

    def open_read(self, path):
        stream = super().open_read(path)
        if path.endswith("big.bin"):
            import io
            data = stream.read()[:1000]
            stream.close()
            return io.BytesIO(data)
        return stream


def test_a_copy_that_got_shorter_than_its_source_is_an_error_and_leaves_nothing():
    mem = Shrinking()
    mem.makedirs("mem://dst")
    mem.put("mem://src/big.bin", b"x" * 3000)
    res = execute(plan_copy(mem, ["mem://src/big.bin"], "mem://dst"), mem)
    assert [r.status for r in res.results] == ["failed"] and "changed while it was copied" in res.results[0].error
    assert mem.list("mem://dst") == []                                         # neither the copy nor a part file


def test_a_source_that_grew_is_copied_as_far_as_it_was_read(work):
    write(work / "src" / "a.txt", "12345")
    plan = plan_copy(fs, [str(work / "src" / "a.txt")], str(work / "dst"))
    with open(work / "src" / "a.txt", "a", encoding="utf-8") as f:
        f.write("6789")                                                        # grew after the plan
    res = execute(plan, fs)
    assert not res.failed and read(work / "dst" / "a.txt") in ("12345", "123456789")


# read-only files (finding 10) --------------------------------------------------------------------------------
def test_a_read_only_file_can_be_deleted_permanently(work):
    write(work / "dst" / "locked.txt", "x")
    os.chmod(work / "dst" / "locked.txt", stat.S_IREAD)
    plan = plan_delete(fs, [str(work / "dst" / "locked.txt")], to_trash=False)
    res = execute(plan, fs)
    assert not res.failed and not (work / "dst" / "locked.txt").exists()


def test_a_read_only_file_inside_a_folder_goes_with_the_folder(work):
    write(work / "dst" / "tree" / "deep" / "ro.txt", "x")
    os.chmod(work / "dst" / "tree" / "deep" / "ro.txt", stat.S_IREAD)
    res = execute(plan_delete(fs, [str(work / "dst" / "tree")], to_trash=False), fs)
    assert not res.failed and not (work / "dst" / "tree").exists()


# roots and trailing separators (finding 11) --------------------------------------------------------------------
def test_a_source_with_a_trailing_separator_is_copied_as_the_folder_it_names(work):
    write(work / "src" / "folder" / "inner.txt", "I")
    plan = plan_copy(fs, [str(work / "src" / "folder") + os.sep], str(work / "dst"))
    assert not plan.blocking
    execute(plan, fs)
    assert read(work / "dst" / "folder" / "inner.txt") == "I"                  # not poured into dst itself
    assert sorted(os.listdir(work / "dst")) == ["folder"]


def test_a_drive_root_cannot_be_copied_moved_or_deleted_as_one_item(work):
    root = os.path.splitdrive(str(work))[0] + os.sep if os.name == "nt" else "/"
    for plan in (plan_copy(fs, [root], str(work / "dst")), plan_move(fs, [root], str(work / "dst")),
                 plan_delete(fs, [root], to_trash=False)):
        assert plan.blocking and "as one item" in plan.blocking[0]
        assert not plan.ops
    assert plan_copy(fs, [""], str(work / "dst")).blocking


def test_ordinary_sources_are_not_affected_by_the_cleaning(work):
    write(work / "src" / "a.txt", "A")
    plan = plan_copy(fs, [str(work / "src" / "a.txt")], str(work / "dst"))
    assert not plan.blocking and len(plan.ops) == 1


# Office files on Enter (finding 9) ---------------------------------------------------------------------------
def make_zip(path):
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", "<x/>")
    return str(path)


def test_only_archive_names_open_as_folders_on_enter_and_content_decides_the_rest(work):
    for name, folder in (("a.zip", True), ("a.ZIP", True), ("report.docx", False), ("book.epub", False),
                         ("comic.cbz", False), ("tool.jar", False), ("sheet.xlsx", False)):
        path = make_zip(work / name)
        assert archives.opens_by_name(path) is folder, name
        assert zipfs_is_archive(path)                                          # the content is still an archive
    (work / "fake.zip").write_text("not a zip at all")
    assert not archives.opens_by_name(str(work / "fake.zip"))                  # a name alone is not enough


def zipfs_is_archive(path):
    from dossier.core import zipfs
    return zipfs.is_archive(path)


# in the window ------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402

from tests.helpers import wait_planned  # noqa: E402
from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401


def test_enter_on_a_word_document_opens_it_with_the_system_and_ctrl_pagedown_looks_inside(world, monkeypatch):
    win, _d, left, right, _t = world
    from dossier.gui import panel as panel_module
    opened = []
    monkeypatch.setattr(panel_module.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True))
    make_zip(left / "report.docx")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("report.docx"), 0))
    key(win, Qt.Key.Key_Return)
    assert len(opened) == 1 and not win.left.path.startswith("zip://")         # handed to Word, not shown as a folder
    key(win, Qt.Key.Key_PageDown, Qt.KeyboardModifier.ControlModifier)
    pump(win, lambda: win.left.path.startswith("zip://"))
    assert win.left.address_bar.parts()[-1][0] == "report.docx"


def test_ctrl_pagedown_on_a_plain_file_says_it_is_not_an_archive(world):
    win, _d, left, *_ = world
    (left / "note.txt").write_text("hi")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("note.txt"), 0))
    key(win, Qt.Key.Key_PageDown, Qt.KeyboardModifier.ControlModifier)
    assert "not an archive" in win.status.text() and not win.left.path.startswith("zip://")


def pretend_loading(panel, path="\\\\slow-server\\share"):
    panel._pending = (types.SimpleNamespace(cancelled=False, done=threading.Event(), entries=None, error=None), path, "")


def test_copy_is_refused_while_the_other_panel_is_still_opening_a_folder(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("A")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    pretend_loading(win.right)
    try:
        win.copy()
        wait_planned(win)
        assert dialogs.infos and "still opening" in dialogs.infos[-1][1] and "slow-server" in dialogs.infos[-1][1]
        assert not win.busy and not dialogs.confirms and list(right.iterdir()) == []
        win.move()
        assert len(dialogs.infos) == 2
    finally:
        win.right._pending = None


def test_paste_and_the_other_placeholder_are_refused_too(world):
    win, dialogs, left, right, _t = world
    from dossier.gui import file_clipboard
    (left / "a.txt").write_text("A")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    key(win, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    pretend_loading(win.left)                                                  # the panel the paste would go into
    try:
        key(win, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert dialogs.infos and "still opening" in dialogs.infos[-1][1]
    finally:
        win.left._pending = None
    dialogs.infos.clear()
    pretend_loading(win.right)
    try:
        win.cmdline.setText("echo %o")
        win.run_command_line()
        assert dialogs.infos and "%o" in dialogs.infos[-1][1]
    finally:
        win.right._pending = None


def test_undo_in_the_window_after_an_overwrite_says_there_is_nothing_to_undo(world):
    win, dialogs, left, right, tmp = world
    (left / "a.txt").write_text("NEW")
    (right / "a.txt").write_text("OLD")
    from dossier.core.ops import Resolution
    dialogs.conflict_answer = Resolution.OVERWRITE
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    win.copy()
    wait_planned(win)
    pump(win, lambda: (right / "a.txt").read_text() == "NEW")
    win.undo()
    assert "Nothing to undo" in win.status.text() and (right / "a.txt").read_text() == "NEW"
