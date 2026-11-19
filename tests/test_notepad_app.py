"""``dossier edit``: the notepad on its own, without the commander window."""
import os

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("PyQt6.Qsci")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui import app as app_module, notepad_app  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402
from dossier.gui.notepad import NotepadTabs, NotepadWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def run(args, tmp_path, problems=None):
    windows: list = []
    said = problems if problems is not None else []
    code = notepad_app.main(args, settings_path=str(tmp_path / "s.ini"), show=False, problem=said.append, windows=windows)
    return code, windows, said


def test_the_dispatcher_sends_edit_to_the_standalone_notepad(monkeypatch):
    got = []
    monkeypatch.setattr(notepad_app, "main", lambda a: got.append(a) or 0)
    assert app_module.main(["dossier", "edit", "a.txt", "b.txt"]) == 0
    assert got == [["a.txt", "b.txt"]]


def test_edit_help_prints_the_usage_and_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as e:
        app_module.main(["dossier", "edit", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "dossier edit" in out and "file" in out


def test_an_existing_file_opens_in_a_notepad_window_with_its_text(qapp, tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"one\r\ntwo\r\n")
    before = {id(w) for w in QApplication.topLevelWidgets()}
    code, windows, said = run([str(p)], tmp_path)
    try:
        assert code == 0 and said == [] and len(windows) == 1
        assert isinstance(windows[0], NotepadTabs) and len(windows[0].pages()) == 1
        win = windows[0].pages()[0]
        assert isinstance(win, NotepadWindow) and win.doc.path == str(p) and win.doc.eol == "\r\n"
        assert win.editor.text().replace("\r\n", "\n") == "one\ntwo\n"
        new = [w for w in QApplication.topLevelWidgets() if id(w) not in before]
        assert not any(isinstance(w, MainWindow) for w in new)
    finally:
        for w in windows:
            w.mark_clean()
            w.close()


def test_several_files_open_one_window_with_a_tab_each(qapp, tmp_path):
    names = [tmp_path / "a.txt", tmp_path / "b.txt"]
    for n in names:
        n.write_text("x", encoding="utf-8")
    code, windows, _said = run([str(n) for n in names], tmp_path)
    try:
        assert code == 0 and len(windows) == 1 and [w.doc.path for w in windows[0].pages()] == [str(n) for n in names]
    finally:
        for w in windows:
            w.mark_clean()
            w.close()


def test_a_missing_file_opens_empty_and_is_made_only_when_saved(qapp, tmp_path):
    p = tmp_path / "new.txt"
    code, windows, said = run([str(p)], tmp_path)
    try:
        assert code == 0 and said == [] and len(windows) == 1
        assert not p.exists()                                     # closing without saving leaves nothing behind
        win = windows[0].pages()[0]
        assert win.editor.text() == "" and "made when you save" in win.message.text()
        win.editor.setText("hello")
        win.save()
        assert p.read_text(encoding="utf-8") == "hello"
    finally:
        for w in windows:
            w.mark_clean()
            w.close()


def test_a_missing_folder_or_a_folder_instead_of_a_file_is_refused(qapp, tmp_path):
    code, windows, said = run([str(tmp_path / "no" / "x.txt"), str(tmp_path)], tmp_path)
    assert code == 2 and windows == [] and len(said) == 2


def test_a_binary_file_is_refused_but_the_other_files_still_open(qapp, tmp_path):
    binary = tmp_path / "b.bin"
    binary.write_bytes(bytes(range(256)) * 8)
    text = tmp_path / "t.txt"
    text.write_text("ok", encoding="utf-8")
    code, windows, said = run([str(binary), str(text)], tmp_path)
    try:
        assert code == 0 and len(windows) == 1 and len(windows[0].pages()) == 1 and len(said) == 1 and "binary" in said[0]
    finally:
        for w in windows:
            w.mark_clean()
            w.close()
