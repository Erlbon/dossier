"""Copy plan step 4 (as the owner changed it, 2026-11-05): after a big job, Tools > Operations > Export Log... saves a Markdown table of
every step where the owner chooses. Nothing is written unless asked."""
import os

import pytest

from dossier.core import joblog
from dossier.core.ops import Kind, Op, OpResult, Result

pytest.importorskip("PyQt6")

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_the_log_is_a_table_of_every_step():
    result = Result([OpResult(Op(Kind.COPY, "a/x.txt", "b/x.txt", size=2048), "done", seconds=0.25),
                     OpResult(Op(Kind.COPY, "a/y|z.txt", "b/y|z.txt", size=10), "failed", "disk full", attempts=3, seconds=4.0)])
    text = joblog.markdown(result, "Copy", 1_700_000_000, 1_700_000_065)
    lines = text.splitlines()
    assert lines[0] == "# Copy" and "1 done, 1 failed" in text and "(65 s)" in text
    assert "| Path | Size | Result | Retries | Seconds |" in lines
    assert any(line.startswith("| b/x.txt | 2.0 K") and line.endswith("| done | 0 | 0.25 |") for line in lines), text
    assert "| b/y\\|z.txt |" in text and "| failed: disk full | 2 | 4.00 |" in text      # a | in a name cannot break the table


def test_a_job_is_big_by_steps_bytes_or_time():
    small = Result([OpResult(Op(Kind.COPY, "a", "b", size=10), "done")])
    assert not joblog.is_big(small, 1.0) and joblog.is_big(small, 61.0)
    assert joblog.is_big(Result([OpResult(Op(Kind.COPY, "a", "b", size=2 ** 31), "done")]), 1.0)


def test_after_a_big_job_the_log_can_be_exported_and_nothing_is_written_before(world, monkeypatch, tmp_path):
    win, dialogs, left, right, _t = world
    monkeypatch.setattr(joblog, "BIG_STEPS", 2)
    for name in ("a.txt", "b.txt", "c.txt"):
        (left / name).write_text(name)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 4)
    win.selection.add([str(left / n) for n in ("a.txt", "b.txt", "c.txt")])
    before = set(os.listdir(tmp_path))
    win.copy()
    pump(win, lambda: getattr(win, "_last_job_log", None) is not None, timeout=10)
    assert set(os.listdir(tmp_path)) == before and "Export Log" in win.status.text()
    dialogs.save_path = str(tmp_path / "log.md")
    win.export_job_log()
    text = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert text.startswith("# Copy") and text.count("| done |") == 3
