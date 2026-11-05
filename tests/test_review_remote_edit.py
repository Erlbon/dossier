"""The functionality review of 2026-11-05, card 25: F4 on a file on a server or inside a zip edits a private copy, and each save
writes it back, unless the original changed in the meantime or the server is read-only."""
import zipfile

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("PyQt6.Qsci")

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

from dossier.core.memfs import MemoryFileSystem  # noqa: E402


def open_editor(win, path):
    win.edit_file(path=path)
    pump(win, lambda: win.editors or win.dialogs.infos)
    assert win.editors, win.dialogs.infos
    return win.editors[-1]


def save_text(editor, text):
    editor.editor.setText(text)
    assert editor.save()


def close_all(win):
    for w in list(win.editors):                                    # saved: nothing to ask on closing
        w.close()


@pytest.fixture
def server(world, monkeypatch):
    """A writable in-memory "server" (mem://) behind the window's file system."""
    win = world[0]
    mem = MemoryFileSystem()
    mem.put("mem://etc/app.conf", b"port=1\n", mtime=1_700_000_000)
    route = win.fs.fs_for
    monkeypatch.setattr(win.fs, "fs_for", lambda p: mem if p.startswith("mem:") else route(p))
    return mem


def test_a_file_inside_a_zip_is_edited_and_written_back(world, tmp_path):
    win, dialogs, *_ = world
    archive = tmp_path / "notes.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("todo.txt", "one\n")
        z.writestr("other.txt", "keep\n")
    editor = open_editor(win, f"zip://{archive}!/todo.txt")
    try:
        save_text(editor, "one\ntwo\n")
        pump(win, lambda: zipfile.ZipFile(archive).read("todo.txt") == b"one\ntwo\n", timeout=10)
        assert zipfile.ZipFile(archive).read("other.txt") == b"keep\n"
    finally:
        close_all(win)


def test_a_file_on_a_server_is_uploaded_on_save(world, server):
    win, *_ = world
    editor = open_editor(win, "mem://etc/app.conf")
    try:
        assert not editor.doc.path.startswith("mem:")              # a private local copy is edited
        save_text(editor, "port=2\n")
        pump(win, lambda: server._nodes["etc/app.conf"].data == b"port=2\n")
    finally:
        close_all(win)


def test_a_change_made_elsewhere_is_never_overwritten(world, server):
    win, dialogs, *_ = world
    editor = open_editor(win, "mem://etc/app.conf")
    try:
        server.put("mem://etc/app.conf", b"port=9 (someone else)\n", mtime=1_700_000_500)
        save_text(editor, "port=2\n")
        pump(win, lambda: dialogs.infos)
        assert "changed by someone else" in dialogs.infos[-1][1]
        assert server._nodes["etc/app.conf"].data == b"port=9 (someone else)\n"
    finally:
        close_all(win)


def test_a_read_only_server_is_not_edited(world, server, monkeypatch):
    win, dialogs, *_ = world
    monkeypatch.setattr(server, "writable", False)
    win.edit_file(path="mem://etc/app.conf")
    pump(win, lambda: dialogs.infos)
    assert "read-only" in dialogs.infos[-1][1] and not win.editors


def test_an_editor_program_gets_the_copy_and_its_saves_are_written_back(world, server):
    win, *_ = world
    started = []
    win.tool_starter = lambda command, argv, cwd: started.append(argv[0])
    win.settings.setValue("editor/program", r"C:\Tools\code.exe")
    win.edit_file(path="mem://etc/app.conf")
    pump(win, lambda: started)
    local = started[0]
    with open(local, "wb") as f:
        f.write(b"port=3\n")
    pump(win, lambda: server._nodes["etc/app.conf"].data == b"port=3\n", timeout=10)
