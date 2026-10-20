"""The per-file conflict dialog: a choice per row, a limited height, bulk buttons."""
import os

import pytest

pytest.importorskip("PyQt6")

from dossier.core.ops import Resolution, conflict_rows, plan_copy  # noqa: E402
from dossier.core.vfs import LocalFileSystem  # noqa: E402
from dossier.gui.conflict_dialog import MAX_ROWS_SHOWN, ConflictDialog, default_choice  # noqa: E402
from tests.test_gui_commander import app  # noqa: E402,F401

fs = LocalFileSystem()


def make(tmp_path, specs):
    """specs: name -> (src text, src mtime, dst text, dst mtime)."""
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    for name, (st, sm, dt, dm) in specs.items():
        for folder, text, mtime in (("src", st, sm), ("dst", dt, dm)):
            f = tmp_path / folder / name
            f.write_text(text)
            os.utime(f, (mtime, mtime))
    return plan_copy(fs, [str(tmp_path / "src" / n) for n in specs], str(tmp_path / "dst"))


def test_rows_say_what_each_side_is_and_start_with_sensible_answers(tmp_path, app):
    plan = make(tmp_path, {"same": ("aaaa", 1_700_000_000, "aaaa", 1_700_000_000),
                           "newer": ("bbbbbb", 1_700_100_000, "bb", 1_700_000_000),
                           "older": ("cc", 1_600_000_000, "cccc", 1_700_000_000)})
    rows = {r.name: r for r in conflict_rows(plan, fs)}
    assert rows["same"].identical and rows["newer"].newer and rows["older"].older
    assert default_choice(rows["same"]) is Resolution.SKIP
    assert default_choice(rows["newer"]) is Resolution.OVERWRITE
    assert default_choice(rows["older"]) is Resolution.KEEP_BOTH


def test_the_answers_are_keyed_by_plan_step_and_the_bulk_buttons_change_all_rows(tmp_path, app):
    plan = make(tmp_path, {n: ("x", 1_700_100_000, "yy", 1_700_000_000) for n in "abc"})
    dlg = ConflictDialog(None, conflict_rows(plan, fs))
    assert set(dlg.answers()) == {0, 1, 2}
    dlg._all(Resolution.SKIP)
    assert set(dlg.answers().values()) == {Resolution.SKIP}
    dlg._newer_only()
    assert set(dlg.answers().values()) == {Resolution.OVERWRITE}


def test_the_table_is_never_taller_than_the_limit_however_many_files_clash(tmp_path, app):
    specs = {f"f{i:03}.txt": ("x", 1_700_100_000, "yy", 1_700_000_000) for i in range(60)}
    plan = make(tmp_path, specs)
    dlg = ConflictDialog(None, conflict_rows(plan, fs))
    row_h = dlg.table.verticalHeader().defaultSectionSize()
    assert dlg.table.height() <= dlg.table.horizontalHeader().height() + row_h * MAX_ROWS_SHOWN + 8
    assert dlg.table.rowCount() == 60


def test_a_folder_in_the_way_cannot_be_overwritten_and_the_choice_is_not_offered(tmp_path, app):
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    (tmp_path / "src" / "thing").write_text("file")
    (tmp_path / "dst" / "thing").mkdir()
    plan = plan_copy(fs, [str(tmp_path / "src" / "thing")], str(tmp_path / "dst"))
    row = conflict_rows(plan, fs)[0]
    assert not row.can_overwrite
    dlg = ConflictDialog(None, [row])
    assert dlg._combos[0].findData(Resolution.OVERWRITE) == -1
    assert dlg.answers() == {row.index: Resolution.KEEP_BOTH}
