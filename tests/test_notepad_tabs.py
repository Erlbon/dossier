"""Card 70: the notepad's tabs, the single standalone notepad that later starts hand their files to, and the warning when a file changed."""
import os
import time
import uuid

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("PyQt6.Qsci")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.textedit import load_document  # noqa: E402
from dossier.gui import notepad_app  # noqa: E402
from dossier.gui.app_settings import open_settings  # noqa: E402
from dossier.gui.notepad import NotepadTabs, NotepadWindow, new_page  # noqa: E402
from tests.test_gui_commander import FakeDialogs  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def pump(predicate, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def make_files(tmp_path, *names):
    out = []
    for n in names:
        p = tmp_path / n
        p.write_text(n + "\n", encoding="utf-8")
        out.append(str(p))
    return out


def start(paths, tmp_path, name, windows):
    settings = open_settings(str(tmp_path / "s.ini"))
    problems: list = []
    n = notepad_app.open_notepads(paths, settings, FakeDialogs(), problems.append, windows, server_name=name)
    return n, problems


def finish(windows):
    for w in windows:
        w.mark_clean()
        w.close()


def test_a_standalone_start_with_two_files_is_one_window_with_two_tabs(qapp, tmp_path):
    a, b = make_files(tmp_path, "a.txt", "b.txt")
    windows: list = []
    try:
        n, problems = start([a, b], tmp_path, "dossier-test-" + uuid.uuid4().hex, windows)
        assert n == 2 and problems == [] and len(windows) == 1
        host = windows[0]
        assert isinstance(host, NotepadTabs) and [p.doc.path for p in host.pages()] == [a, b]
        assert host.tabs.tabText(0) == "a.txt" and host.windowTitle().endswith("b.txt")        # the current tab is the last one added
    finally:
        finish(windows)


def test_a_second_start_hands_its_file_to_the_first_which_opens_a_tab(qapp, tmp_path):
    a, b = make_files(tmp_path, "a.txt", "b.txt")
    name = "dossier-test-" + uuid.uuid4().hex
    first: list = []
    second: list = []
    try:
        start([a], tmp_path, name, first)
        n, problems = start([b], tmp_path, name, second)
        assert n == 1 and second == [] and problems == []                  # nothing opened by the second start: it handed over
        host = first[0]
        assert pump(lambda: len(host.pages()) == 2)
        assert [p.doc.path for p in host.pages()] == [a, b] and host.current_page().doc.path == b
        n, _p = start([a], tmp_path, name, second)                         # a file already open is only brought forward
        assert n == 1 and second == []
        assert pump(lambda: host.current_page().doc.path == a)
        assert len(host.pages()) == 2
    finally:
        finish(first)


def test_a_stale_server_name_is_taken_over(qapp, tmp_path):
    from PyQt6.QtNetwork import QLocalServer
    a, b = make_files(tmp_path, "a.txt", "b.txt")
    name = "dossier-test-" + uuid.uuid4().hex
    first: list = []
    second: list = []
    try:
        start([a], tmp_path, name, first)
        first[0].session.close_server()                                    # the first one is gone without answering
        n, _p = start([b], tmp_path, name, second)
        assert n == 1 and len(second) == 1                                 # nobody answered: this one is the notepad now
        server = second[0].session.server
        assert server is not None and server.isListening() and server.serverName() == name
        QLocalServer.removeServer(name)
    finally:
        finish(first)
        finish(second)


def test_tabs_keep_their_own_text_and_closing_a_modified_tab_asks(qapp, tmp_path):
    a, b = make_files(tmp_path, "a.txt", "b.txt")
    dialogs = FakeDialogs()
    host = NotepadTabs()
    pa = new_page(load_document(a), dialogs, open_settings(str(tmp_path / "s.ini")))
    pb = new_page(load_document(b), dialogs, open_settings(str(tmp_path / "s.ini")))
    host.add_page(pa)
    host.add_page(pb)
    host.show()
    try:
        pa.editor.insertAt("changed ", 0, 0)
        assert pa.is_modified() and not pb.is_modified()
        assert host.tabs.tabText(0) == "a.txt*"
        host.tabs.setCurrentIndex(0)
        assert host.windowTitle().endswith("a.txt*")
        dialogs.save_answer = "cancel"
        pa.close()                                                          # the question is asked and answered Cancel
        assert host.tabs.count() == 2
        host.step_tab(1)
        assert host.current_page() is pb
        host.step_tab(1)
        assert host.current_page() is pa
        dialogs.save_answer = "save"
        host.close()
        assert open(a, encoding="utf-8").read().startswith("changed a.txt")
    finally:
        host.mark_clean()
        host.close()


def test_a_file_changed_on_disk_after_opening_asks_reload_or_keep(qapp, tmp_path):
    (a,) = make_files(tmp_path, "a.txt")
    dialogs = FakeDialogs()
    pad = NotepadWindow(load_document(a), dialogs)
    pad.show()
    try:
        # the check as a thread would report it: the file as it is now
        pad._on_disk_seen(a, (pad.doc.size, pad.doc.mtime_ns))
        assert getattr(dialogs, "file_changed_asked", []) == []             # unchanged: no question
        dialogs.file_changed_answer = "keep"
        pad.editor.insertAt("mine ", 0, 0)
        pad._on_disk_seen(a, (pad.doc.size + 5, pad.doc.mtime_ns + 1))
        assert dialogs.file_changed_asked == [("a.txt", True)]
        assert pad.editor.text().startswith("mine ")
        pad._on_disk_seen(a, (pad.doc.size, pad.doc.mtime_ns))              # keep mine: the new disk state is known, no second question
        assert len(dialogs.file_changed_asked) == 1
        with open(a, "w", encoding="utf-8") as f:
            f.write("from another program\n")
        dialogs.file_changed_answer = "reload"
        st = os.stat(a)
        pad._on_disk_seen(a, (st.st_size + 1, st.st_mtime_ns + 1))
        assert len(dialogs.file_changed_asked) == 2
        assert pad.editor.text() == "from another program\n" and not pad.is_modified()
    finally:
        pad.mark_clean()
        pad.close()


def test_the_disk_check_runs_on_a_thread_and_finds_a_real_change(qapp, tmp_path):
    (a,) = make_files(tmp_path, "a.txt")
    dialogs = FakeDialogs()
    dialogs.file_changed_answer = "reload"
    pad = NotepadWindow(load_document(a), dialogs)
    pad.show()
    try:
        with open(a, "w", encoding="utf-8") as f:
            f.write("changed elsewhere, longer\n")
        pad.check_disk()
        assert pump(lambda: getattr(dialogs, "file_changed_asked", []) != [])
        assert pump(lambda: pad.editor.text() == "changed elsewhere, longer\n")
    finally:
        pad.mark_clean()
        pad.close()


def test_the_notepad_tabs_are_the_panels_tabs_with_their_own_cross(qapp, tmp_path):
    """The owner, 2026-11-19: the notepad's tabs look like the main window's (rounded, gold and blue) and close with the same cross."""
    from PyQt6.QtWidgets import QTabBar, QToolButton
    from dossier.gui.panel import PanelTabBar
    a, b = make_files(tmp_path, "a.txt", "b.txt")
    dialogs = FakeDialogs()
    host = NotepadTabs()
    pa = new_page(load_document(a), dialogs, open_settings(str(tmp_path / "s.ini")))
    pb = new_page(load_document(b), dialogs, open_settings(str(tmp_path / "s.ini")))
    host.add_page(pa)
    host.add_page(pb)
    host.show()
    try:
        bar = host.tabs.tabBar()
        assert isinstance(bar, PanelTabBar) and not host.tabs.tabsClosable()
        cross = bar.tabButton(0, QTabBar.ButtonPosition.RightSide)
        assert isinstance(cross, QToolButton) and not cross.icon().isNull()
        cross.click()
        assert pump(lambda: host.tabs.count() == 1) and host.current_page() is pb
    finally:
        host.mark_clean()
        host.close()


def test_the_bar_menus_have_the_bars_own_look_and_so_do_their_submenus(qapp, tmp_path):
    """The owner, 2026-11-19, option A: the floating bar's menus are rounded glass like the bar, submenus too."""
    from PyQt6.QtCore import Qt
    a, = make_files(tmp_path, "a.txt")
    page = new_page(load_document(a), FakeDialogs(), open_settings(str(tmp_path / "s.ini")))
    page.show()
    try:
        page._popup_menu(page.settings_menu, "settings")
        assert pump(lambda: page.settings_menu.isVisible())
        for menu in (page.settings_menu, page.lang_menu, page.encoding_menu, page.file_menu):
            if menu is page.file_menu:
                page.settings_menu.close()
                page._popup_menu(page.file_menu, "file")
            assert "border-radius: 14px" in menu.styleSheet()
            assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        page.file_menu.close()
        # option A, 2026-11-20: just above the bar with a gap, lined up with the button, never over the bar
        from PyQt6.QtCore import QPoint
        bar = page.floating
        at = bar.menu_position(page.file_menu, "file")
        bar_top = bar.bar.mapToGlobal(QPoint(0, 0)).y()
        assert at.y() + page.file_menu.sizeHint().height() == bar_top - bar.MENU_GAP
        assert at.x() == bar.buttons["file"].mapToGlobal(QPoint(0, 0)).x()
    finally:
        page.mark_clean()
        page.close()
