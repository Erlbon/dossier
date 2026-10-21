"""Visual details from the design review: tab height, the note's headings, header alignment, the main button of a dialog."""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QVBoxLayout  # noqa: E402

from dossier.gui.copy_settings import CopySettingsDialog, read_settings  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_the_headers_are_aligned_like_their_values(world):
    win, _d, left, _r, _t = world
    (left / "a.txt").write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("a.txt") >= 0)
    m = win.left.model
    for col in range(m.columnCount()):
        header = int(m.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole))
        cell = m.data(m.index(m.row_of("a.txt"), col), Qt.ItemDataRole.TextAlignmentRole)
        if cell is not None:
            assert header & int(Qt.AlignmentFlag.AlignRight), (col, header)
        else:
            assert header & int(Qt.AlignmentFlag.AlignLeft), (col, header)


def test_a_markdown_heading_in_the_note_is_only_a_little_larger_than_the_text(world):
    win, _d, left, _r, _t = world
    note = win.left.note
    note.setMarkdown("# Big\n\ntext\n\n## Middle\n\n### Small\n")
    base = note.font().pointSizeF()
    sizes = []
    block = note.document().begin()
    while block.isValid():
        if block.blockFormat().headingLevel() > 0:
            sizes.append(block.begin().fragment().charFormat().fontPointSize())
        block = block.next()
    assert len(sizes) == 3 and sizes[0] <= base * 1.4 and sizes[0] > sizes[1] > sizes[2] >= base


def test_the_tab_is_not_taller_than_its_text_needs(world):
    win, *_ = world
    bar = win.left.tabs
    assert bar.tabSizeHint(0).height() <= bar.fontMetrics().height() + 14


def test_the_accept_button_of_a_dialog_is_the_gold_default_one(world):
    win, *_ = world
    dlg = CopySettingsDialog(win, read_settings(win.settings))
    dlg.show()
    QApplication.processEvents()
    box = dlg.findChildren(QDialogButtonBox)[0]
    save = [b for b in box.buttons() if b.text() == "Save"][0]
    cancel = [b for b in box.buttons() if b.text() == "Cancel"][0]
    assert save.isDefault() and "background:" in save.styleSheet() and not cancel.styleSheet()
    dlg.close()
    plain = QDialog(win)
    QVBoxLayout(plain).addWidget(QDialogButtonBox(QDialogButtonBox.StandardButton.Ok))
    plain.show()
    QApplication.processEvents()
    assert "background:" in plain.findChildren(QDialogButtonBox)[0].buttons()[0].styleSheet()
    plain.close()


def test_check_box_rows_of_the_copy_dialog_start_at_the_same_left_edge(world):
    win, *_ = world
    dlg = CopySettingsDialog(win, read_settings(win.settings))
    dlg.show()
    QApplication.processEvents()
    lefts = {box.mapTo(dlg, box.rect().topLeft()).x() for box in (dlg.native, dlg.verify, dlg.ask, dlg.ask_drop, dlg.remember)}
    assert len(lefts) == 1, lefts
    dlg.close()
