"""The Health window: the check, the groups, the table, and acting on findings (preview, fix, mark, ignore, copy)."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core import health, quarantine  # noqa: E402
from dossier.gui import quarantine_ui  # noqa: E402
from dossier.gui.health_window import ALL, HealthWindow  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def wait(until, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


def build(root):
    root.mkdir(exist_ok=True)
    (root / "empty.dat").write_bytes(b"")
    (root / "empty2.dat").write_bytes(b"")
    (root / "Thumbs.db").write_bytes(b"j")
    (root / "Beach.JPG").write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"0" * 20)
    (root / "sub").mkdir(exist_ok=True)
    (root / "sub" / "Desktop.INI").write_bytes(b"j")
    (root / "sub" / "keep.txt").write_bytes(b"data")


@pytest.fixture
def health_window(world, monkeypatch):
    win, d, left, right, tmp = world
    build(left)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 4)
    seen = []
    monkeypatch.setattr(win, "_show_health_window", lambda w: seen.append(w))
    win.check_folder_health()
    w = seen[0]
    wait(lambda: w.report is not None)
    return win, d, left, right, tmp, w


def rows(w):
    return [w.groups.item(i).text() for i in range(w.groups.count())]


def pick(w, rule):
    for i in range(w.groups.count()):
        if w.groups.item(i).data(Qt.ItemDataRole.UserRole) == rule:
            w.groups.setCurrentRow(i)
            return
    raise AssertionError(rule)


def table_names(w):
    return sorted(w.table.topLevelItem(i).text(1) for i in range(w.table.topLevelItemCount()))


def test_the_window_checks_the_panels_folder_and_groups_the_findings(health_window):
    win, d, left, right, tmp, w = health_window
    assert w.folder.text() == str(left) and w.report.files == 6 and not w.report.cancelled
    texts = rows(w)
    assert texts[0].startswith("All findings")
    assert any("empty-file" in t and "2" in t for t in texts) and any("junk-file" in t and "2" in t for t in texts)
    assert w.check_button.text() == "Check" and "Looked at 6 files" in w.status.text()
    assert "0 errors" in w.counts.text() and "2 warnings" in w.counts.text()


def test_a_group_lists_its_files_and_all_findings_lists_everything(health_window):
    win, d, left, right, tmp, w = health_window
    pick(w, "empty-file")
    assert table_names(w) == ["empty.dat", "empty2.dat"]
    first = w.table.topLevelItem(0)
    assert first.text(0) == "warning" and "quarantine" in first.text(4).lower()
    pick(w, ALL)
    assert w.table.topLevelItemCount() == len(w.visible()) == 5            # two empty files, two junk files, one upper-case extension


def test_the_table_headers_resize_and_sort_and_severity_sorts_by_badness(health_window):
    win, d, left, right, tmp, w = health_window
    pick(w, ALL)
    assert w.table.isSortingEnabled() and w.table.header().sectionResizeMode(0).name == "Interactive"
    w.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    order = [w.table.topLevelItem(i).text(0) for i in range(w.table.topLevelItemCount())]
    assert order == sorted(order, key=health.SEVERITIES.index)                  # warnings before notes, not alphabetical


def test_selecting_one_row_shows_what_is_wrong_and_the_fix(health_window):
    win, d, left, right, tmp, w = health_window
    pick(w, "upper-case-extension")
    w.table.topLevelItem(0).setSelected(True)
    assert "Beach.JPG" in w.detail.text() and "Lower-case the extension" in w.detail.text() and "Beach.jpg" in w.detail.text()
    assert w.fix_button.text() == "Fix selected (1)" and w.fix_button.isEnabled()
    w.table.clearSelection()
    assert w.fix_button.text() == "Fix all 1"


def test_ignoring_a_rule_hides_it_and_show_ignored_brings_it_back(health_window):
    win, d, left, right, tmp, w = health_window
    pick(w, "junk-file")
    w.ignore_rule()
    assert not any("junk-file" in t for t in rows(w)) and "hidden by ignored rules" in w.counts.text() and w.reset_button.isVisibleTo(w)
    w.show_ignored()
    assert any("junk-file" in t for t in rows(w)) and not w.reset_button.isVisibleTo(w)


def test_mark_in_the_panel_adds_the_files_to_the_shared_selection(health_window):
    win, d, left, right, tmp, w = health_window
    win.selection.clear()
    pick(w, "empty-file")
    w.mark_in_panel()
    assert {os.path.basename(p) for p in win.selection.paths()} == {"empty.dat", "empty2.dat"}
    assert "Marked 2 items" in w.status.text()


def test_copy_list_puts_the_group_on_the_clipboard(health_window):
    win, d, left, right, tmp, w = health_window
    pick(w, "empty-file")
    w.copy_list()
    lines = QApplication.clipboard().text().splitlines()
    assert len(lines) == 2 and all(line.split(chr(9))[1] == "empty-file" for line in lines)


def test_preview_shows_the_plan_and_changes_nothing(health_window, monkeypatch):
    win, d, left, right, tmp, w = health_window
    pick(w, "upper-case-extension")
    shown = []
    monkeypatch.setattr(w, "_show_preview", lambda dialog: (shown.append(dialog.text.toPlainText()), dialog.reject()))
    w.preview_button.click()
    wait(lambda: shown)
    assert "Rename" in shown[0] and "Beach.JPG" in shown[0] and "Beach.jpg" in shown[0]
    for _ in range(20):
        QApplication.processEvents()
    assert "Beach.JPG" in os.listdir(left)                                       # a rejected preview changed nothing


def test_a_rename_fix_runs_through_the_queue_and_the_finding_goes_away(health_window):
    win, d, left, right, tmp, w = health_window
    pick(w, "upper-case-extension")
    w.fix_button.click()
    wait(lambda: not any(f.rule == "upper-case-extension" for f in w.findings))
    assert "Beach.jpg" in os.listdir(left) and "upper-case-extension" not in " ".join(rows(w))
    assert "Fixed 1 item" in w.status.text()


def test_a_delete_fix_goes_to_the_bin_and_a_quarantine_fix_keeps_the_file(health_window):
    win, d, left, right, tmp, w = health_window
    quarantine_ui.write_settings(win.settings, quarantine.Settings(quarantine.FOLDER, str(tmp / "Q")))
    pick(w, "junk-file")
    w.fix_button.click()
    wait(lambda: not any(f.rule == "junk-file" for f in w.findings))
    assert not (left / "Thumbs.db").exists() and any(n.endswith("Thumbs.db") for n in os.listdir(tmp / "bin"))       # in the bin, not gone for good
    pick(w, "empty-file")
    w.fix_button.click()
    wait(lambda: not any(f.rule == "empty-file" for f in w.findings))
    assert not (left / "empty.dat").exists()
    assert os.path.isfile(quarantine.destination(str(left / "empty.dat"), win.quarantine_settings()))


def test_all_findings_fix_runs_each_kind_of_fix_as_its_own_plan(health_window, monkeypatch):
    win, d, left, right, tmp, w = health_window
    quarantine_ui.write_settings(win.settings, quarantine.Settings(quarantine.FOLDER, str(tmp / "Q")))
    pick(w, ALL)
    previews = []
    monkeypatch.setattr(w, "_show_preview", lambda dialog: (previews.append(dialog.summary.text()), dialog.accept()))
    w.preview_button.click()
    wait(lambda: previews)
    assert "3 plans" in previews[0]                                              # rename, quarantine and delete
    wait(lambda: not any(f.fix for f in w.findings), timeout=10)
    assert not any(n in os.listdir(left) for n in ("empty.dat", "empty2.dat", "Thumbs.db", "Beach.JPG"))


def test_stop_ends_a_run_and_a_new_check_starts_from_scratch(world):
    win, d, left, right, tmp = world
    build(left)
    w = HealthWindow(win, str(left), start=False)
    w.start()
    w.stop()
    wait(lambda: w.report is not None)
    assert w.check_button.text() == "Check"
    w.report = None
    w.start()
    wait(lambda: w.report is not None and w.status.text().startswith("Looked at"))
    assert w.report.files == 6


def test_closing_the_window_stops_its_check(world):
    win, d, left, right, tmp = world
    build(left)
    w = HealthWindow(win, str(left), start=False)
    w.start()
    w.close()
    wait(lambda: w._job is None)


def test_a_folder_that_is_not_there_says_so_and_the_menu_has_the_command(world):
    win, d, left, right, tmp = world
    w = HealthWindow(win, str(tmp / "nothing-here"), start=False)
    w.start()
    wait(lambda: w.report is not None)
    assert w.report.unreadable == 1 and w.report.findings == [] and "could not be read" in w.status.text()
    texts = {a.text() for a in win.findChildren(type(win.menuBar().actions()[0])) if a.text()}
    assert "Check Folder Health..." in texts
