"""C6: optional verify after copy, and the flush that makes "done" mean the data is on the device."""
import io
import os

import pytest
from tests.helpers import wait_planned

from dossier.core import ops as ops_module
from dossier.core import transfer
from dossier.core.memfs import MemoryFileSystem
from dossier.core.ops import ExecOptions, execute, plan_copy
from dossier.core.progress import CancelToken
from dossier.core.transfer import VerifyFailed, verify_copy
from dossier.core.vfs import LocalFileSystem


class Corrupting(MemoryFileSystem):
    """A target that stores one byte wrong, as a failing stick would."""

    def __init__(self, bad_name="b.bin"):
        super().__init__()
        self.bad_name = bad_name

    def open_read(self, path):
        stream = super().open_read(path)
        if path.startswith("mem://dst/") and self.basename(path) == self.bad_name:
            data = bytearray(stream.read())
            stream.close()
            data[len(data) // 2] ^= 0xFF
            return io.BytesIO(bytes(data))
        return stream


def world(fs=None, names=("a.bin", "b.bin", "c.bin"), size=3000):
    fs = fs or MemoryFileSystem()
    fs.makedirs("mem://dst")
    for i, n in enumerate(names):
        fs.put(f"mem://src/{n}", bytes([i + 1]) * size)
    return fs, plan_copy(fs, [f"mem://src/{n}" for n in names], "mem://dst")


def test_verify_accepts_equal_files_and_names_the_byte_of_a_difference():
    fs = MemoryFileSystem()
    fs.put("mem://a", b"x" * 10_000)
    fs.put("mem://b", b"x" * 10_000)
    seen = []
    verify_copy(fs, "mem://a", fs, "mem://b", progress=seen.append, chunk_size=4096)
    assert seen[-1] == 10_000 and seen == sorted(seen)
    fs.put("mem://c", b"x" * 5000 + b"y" + b"x" * 4999)
    with pytest.raises(VerifyFailed, match="5,000"):
        verify_copy(fs, "mem://a", fs, "mem://c", chunk_size=4096)
    fs.put("mem://short", b"x" * 9000)
    with pytest.raises(VerifyFailed):
        verify_copy(fs, "mem://a", fs, "mem://short")
    fs.put("mem://empty1", b"")
    fs.put("mem://empty2", b"")
    verify_copy(fs, "mem://empty1", fs, "mem://empty2")


def test_a_bad_copy_is_removed_and_reported_and_the_good_ones_stay():
    fs, plan = world(Corrupting())
    res = execute(plan, fs, options=ExecOptions(verify=True))
    assert [r.op.src.rsplit("/", 1)[1] for r in res.failed] == ["b.bin"]
    assert "differs" in res.failed[0].error
    assert sorted(e.name for e in fs.list("mem://dst")) == ["a.bin", "c.bin"]       # the bad copy was not kept
    assert len(res.done) == 2


def test_without_verify_the_bad_copy_goes_unnoticed():
    fs, plan = world(Corrupting())
    res = execute(plan, fs, options=ExecOptions())
    assert not res.failed


def test_verify_counts_in_the_progress_and_the_bar_ends_at_the_total():
    fs, plan = world()
    reports = []
    execute(plan, fs, progress=lambda d, t: reports.append((d, t)), options=ExecOptions(verify=True, workers=1))
    assert reports[-1][0] == reports[-1][1]
    copy_bytes = 3 * 3000
    assert reports[0][1] == plan.total_work + copy_bytes                      # the copy, and reading it back
    assert [d for d, _t in reports] == sorted(d for d, _t in reports)


def test_cancel_during_verify_keeps_the_files_that_were_finished():
    fs, plan = world(names=("a.bin", "b.bin"))
    token = CancelToken()

    def progress(d, t):
        if d > 3000 * 2:               # in the second file
            token.cancel()

    res = execute(plan, fs, progress=progress, cancel=token, options=ExecOptions(verify=True, workers=1))
    assert res.cancelled and fs.stat("mem://dst/a.bin").size == 3000


# flush ----------------------------------------------------------------------------------------------------
@pytest.fixture
def flushed(monkeypatch):
    calls = []
    monkeypatch.setattr(ops_module, "flush_file", lambda path: calls.append(path))
    return calls


def local_world(tmp_path, n=3):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    for i in range(n):
        (src / f"f{i}.bin").write_bytes(bytes([i + 1]) * 2000)
    fs = LocalFileSystem()
    return fs, [str(src / f"f{i}.bin") for i in range(n)], dst


def run_copy(fs, sources, dst, **options):
    for p in dst.iterdir():
        p.unlink()
    return execute(plan_copy(fs, sources, str(dst)), fs, options=ExecOptions(**options))


def test_flush_runs_for_removable_and_network_targets_only_unless_forced(tmp_path, flushed, monkeypatch):
    fs, sources, dst = local_world(tmp_path)
    monkeypatch.setattr(ops_module, "target_kind", lambda plan: "removable")
    run_copy(fs, sources, dst)
    assert sorted(os.path.basename(p) for p in flushed) == ["f0.bin", "f1.bin", "f2.bin"]
    flushed.clear()
    monkeypatch.setattr(ops_module, "target_kind", lambda plan: "fixed")
    run_copy(fs, sources, dst)
    assert flushed == []
    run_copy(fs, sources, dst, flush=True)
    assert len(flushed) == 3
    flushed.clear()
    monkeypatch.setattr(ops_module, "target_kind", lambda plan: "removable")
    run_copy(fs, sources, dst, flush=False)
    assert flushed == []


def test_a_flush_failure_is_reported_for_that_file_only(tmp_path, monkeypatch):
    fs, sources, dst = local_world(tmp_path)

    def flush(path):
        if path.endswith("f1.bin"):
            raise OSError(5, "device not ready")

    monkeypatch.setattr(ops_module, "flush_file", flush)
    res = run_copy(fs, sources, dst, flush=True)
    assert [os.path.basename(r.op.src) for r in res.failed] == ["f1.bin"]
    assert "flushed" in res.failed[0].error and len(res.done) == 2


def test_the_bar_reserves_its_last_part_for_the_flush(tmp_path, flushed):
    fs, sources, dst = local_world(tmp_path)
    reports = []
    for p in dst.iterdir():
        p.unlink()
    execute(plan_copy(fs, sources, str(dst)), fs, progress=lambda d, t: reports.append((d, t)),
            options=ExecOptions(flush=True, workers=1))
    assert reports[-1][0] == reports[-1][1]
    assert reports[-2][0] < reports[-1][1] or len(reports) > 3
    before_flush = [d for d, t in reports if d < t]
    assert before_flush and max(before_flush) < reports[-1][1]       # something was still ahead after the last copy


def test_nothing_is_flushed_for_memory_targets(flushed):
    fs, plan = world()
    execute(plan, fs, options=ExecOptions(flush=True))
    assert flushed == []


def test_flush_file_works_on_a_real_file_and_skips_what_it_cannot_open(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"data")
    transfer.flush_file(str(f))                                  # no error
    transfer.flush_file(str(tmp_path))                           # a folder: skipped, not an error
    ro = tmp_path / "ro.bin"
    ro.write_bytes(b"data")
    os.chmod(ro, 0o444)
    transfer.flush_file(str(ro))
    os.chmod(ro, 0o666)


def test_the_window_passes_the_verify_setting(tmp_path):
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from dossier.gui.main_window import MainWindow
    from tests.test_gui_commander import FakeDialogs
    app = QApplication.instance() or QApplication([])
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path), str(tmp_path)), dialogs=FakeDialogs())
    try:
        assert win._exec_options().verify is False
        win.act_verify.setChecked(True)
        assert win._exec_options().verify is True
    finally:
        win.close()


# the checkbox in the transfer dialog --------------------------------------------------------------------------
def commander(tmp_path):
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from dossier.gui.main_window import MainWindow
    from tests.test_gui_commander import FakeDialogs
    app = QApplication.instance() or QApplication([])
    left, right = tmp_path / "l", tmp_path / "r"
    left.mkdir()
    right.mkdir()
    (left / "a.txt").write_text("A")
    dialogs = FakeDialogs()
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(left), str(right)), dialogs=dialogs)
    win.show()
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    return win, dialogs, left, right


def wait_idle(win):
    import time
    from PyQt6.QtWidgets import QApplication
    end = time.time() + 10
    while time.time() < end and win.busy:
        QApplication.processEvents()
        time.sleep(0.01)


def test_the_transfer_dialog_offers_verify_off_at_first_and_runs_the_copy_with_the_choice(tmp_path, monkeypatch):
    win, dialogs, left, right = commander(tmp_path)
    seen = []
    real = ops_module.verify_copy
    monkeypatch.setattr(ops_module, "verify_copy", lambda *a, **k: seen.append(a[1]) or real(*a, **k))
    try:
        dialogs.verify_answer = True
        win.copy()
        wait_planned(win)
        assert dialogs.transfer_offered_verify is False             # off until the user asks for it
        wait_idle(win)
        assert len(seen) == 1 and (right / "a.txt").read_text() == "A"
    finally:
        win.close()


def test_the_choice_is_remembered_and_shown_in_settings_and_offered_next_time(tmp_path):
    win, dialogs, left, right = commander(tmp_path)
    try:
        dialogs.verify_answer = True
        win.copy()
        wait_planned(win)
        wait_idle(win)
        assert win.act_verify.isChecked() and str(win.settings.value("copy/verify")).lower() == "true"
        (left / "b.txt").write_text("B")
        win.left.refresh()
        win.left.table.setCurrentIndex(win.left.model.index(2, 0))
        dialogs.verify_answer = None
        win.copy()
        wait_planned(win)
        assert dialogs.transfer_offered_verify is True               # offered as last chosen
    finally:
        win.close()


def test_cancelling_the_transfer_dialog_changes_nothing_and_keeps_the_setting(tmp_path):
    win, dialogs, left, right = commander(tmp_path)
    try:
        dialogs.confirm_answer = False
        dialogs.verify_answer = True
        win.copy()
        wait_planned(win)
        assert not win.busy and list(right.iterdir()) == [] and not win.act_verify.isChecked()
    finally:
        win.close()


def test_the_real_dialog_has_the_checkbox_and_returns_its_state(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QCheckBox, QMessageBox
    from dossier.gui.dialogs import Dialogs
    app = QApplication.instance() or QApplication([])
    state = {}

    def fake_exec(self):
        box = self.checkBox()
        state["text"], state["start"] = box.text(), box.isChecked()
        box.setChecked(True)                                         # the user ticks it
        accept = [b for b in self.buttons() if self.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole][0]
        self._clicked = accept
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self._clicked)
    assert Dialogs(None).confirm_transfer("Copy", "text", "Copy", False) is True
    assert state["start"] is False and "Verify" in state["text"]
