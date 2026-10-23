"""Continuing unfinished copies, moves and deletes after a restart (opt-in)."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.ops import plan_copy  # noqa: E402
from dossier.core.queue_journal import Entry, Journal  # noqa: E402
from dossier.gui.copy_settings import CopySettingsDialog, write_settings  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def turn_on(win, on=True):
    values = win.copy_settings()
    values["remember_queue"] = on
    write_settings(win.settings, values)


def journal_of(win, tmp):
    return Journal(str(tmp / "queue.json"))


def wait(until, timeout=5.0):
    """Like pump, but also while an operation is paused (pump waits for the window to be idle)."""
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


def put(folder, names, text="x", mtime=None):
    folder.mkdir(exist_ok=True)
    for n in names:
        (folder / n).write_text(text + n)
        if mtime:
            os.utime(folder / n, (mtime, mtime))


def test_nothing_is_written_or_asked_while_the_setting_is_off(world):
    win, d, left, right, tmp = world
    put(left, ["a.txt"])
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    plan = plan_copy(win.fs, [str(left / "a.txt")], str(right))
    assert win.intent_for(plan, [str(left / "a.txt")], str(right)) is None
    win._run(plan, remember=win.intent_for(plan, [], ""))
    pump(win, lambda: (right / "a.txt").exists())
    assert not (tmp / "queue.json").exists()
    (tmp / "queue.json").write_text("[]")
    win.offer_resume()
    assert d.resume_asked == []


def test_an_operation_is_in_the_list_while_it_waits_and_off_it_when_it_ends(world):
    win, d, left, right, tmp = world
    turn_on(win)
    put(left, ["a.txt", "b.txt"])
    plan = plan_copy(win.fs, [str(left / "a.txt"), str(left / "b.txt")], str(right))
    entry = win.intent_for(plan, [str(left / "a.txt"), str(left / "b.txt")], str(right))
    assert entry.kind == "copy" and entry.dest == str(right)
    win.toggle_pause()                                           # it waits: the entry is on disk
    win._run(plan, remember=entry)
    kept = journal_of(win, tmp).load()
    assert len(kept) == 1 and kept[0].id == entry.id and kept[0].sources == entry.sources
    win.toggle_pause()
    pump(win, lambda: (right / "b.txt").exists())
    pump(win, lambda: journal_of(win, tmp).load() == [])


def test_closing_the_program_keeps_the_unfinished_entry(world):
    win, d, left, right, tmp = world
    turn_on(win)
    put(left, ["a.txt"])
    plan = plan_copy(win.fs, [str(left / "a.txt")], str(right))
    entry = win.intent_for(plan, [str(left / "a.txt")], str(right))
    win.toggle_pause()
    win._run(plan, remember=entry)
    win._closing = True                                          # what closeEvent sets before it cancels the jobs
    for job in list(win._jobs):
        job.cancel()
    for _ in range(50):
        QApplication.processEvents()
    assert [e.id for e in journal_of(win, tmp).load()] == [entry.id]


def test_a_cancelled_operation_is_taken_off_the_list(world):
    win, d, left, right, tmp = world
    turn_on(win)
    put(left, ["a.txt"])
    plan = plan_copy(win.fs, [str(left / "a.txt")], str(right))
    entry = win.intent_for(plan, [str(left / "a.txt")], str(right))
    win.toggle_pause()
    win._run(plan, remember=entry)
    for job in list(win._jobs):
        job.cancel()
    pump(win, lambda: journal_of(win, tmp).load() == [])


def test_the_real_copy_move_paste_and_delete_commands_remember_what_they_run(world):
    win, d, left, right, tmp = world
    turn_on(win)
    put(left, ["a.txt", "b.txt"])
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 3)
    win.selection.add([str(left / "a.txt")])
    win.toggle_pause()                                           # everything below waits, so the list can be read
    win.copy()
    wait(lambda: journal_of(win, tmp).load())
    got = journal_of(win, tmp).load()
    assert got[0].kind == "copy" and got[0].dest == str(right) and got[0].sources == [str(left / "a.txt")]
    win.toggle_pause()
    pump(win, lambda: journal_of(win, tmp).load() == [])
    # delete
    win.selection.add([str(left / "b.txt")])
    win.toggle_pause()
    win.delete(permanent=True)
    wait(lambda: journal_of(win, tmp).load())
    got = journal_of(win, tmp).load()
    assert got[0].kind == "delete" and got[0].to_trash is False and got[0].sources == [str(left / "b.txt")]
    win.toggle_pause()
    pump(win, lambda: journal_of(win, tmp).load() == [])
    assert not (left / "b.txt").exists()


def test_continuing_a_half_done_copy_copies_only_what_is_missing(world):
    win, d, left, right, tmp = world
    turn_on(win)
    names = ["a.txt", "b.txt", "c.txt"]
    put(left, names, mtime=1_700_000_000)
    put(right, ["a.txt"], mtime=1_700_000_000)                    # copied before the program was killed
    journal_of(win, tmp).add(Entry("copy", [str(left / n) for n in names], str(right)))
    d.resume_answer = "continue"
    win.offer_resume()
    pump(win, lambda: all((right / n).exists() for n in names) and journal_of(win, tmp).load() == [])
    assert d.resume_asked == [[f"Copy 3 items to {right}"]]
    assert not hasattr(d, "conflict_rows_seen")                  # the finished file was recognised, nobody was asked about it
    assert (right / "b.txt").read_text() == "xb.txt"


def test_continuing_a_part_done_move_and_delete(world):
    win, d, left, right, tmp = world
    turn_on(win)
    put(left, ["m.txt", "gone.txt"])
    put(right, ["already.txt"])
    journal_of(win, tmp).add(Entry("move", [str(left / "m.txt"), str(left / "never-existed.txt")], str(right)))
    journal_of(win, tmp).add(Entry("delete", [str(left / "gone.txt")], to_trash=False))
    d.resume_answer = "continue"
    win.offer_resume()
    pump(win, lambda: (right / "m.txt").exists() and not (left / "gone.txt").exists() and journal_of(win, tmp).load() == [])
    assert not (left / "m.txt").exists()


def test_nothing_left_to_do_clears_the_entry_and_says_so(world):
    win, d, left, right, tmp = world
    turn_on(win)
    journal_of(win, tmp).add(Entry("delete", [str(left / "was-deleted-before.txt")], to_trash=False))
    d.resume_answer = "continue"
    win.offer_resume()
    pump(win, lambda: journal_of(win, tmp).load() == [])


def test_discard_and_later(world):
    win, d, left, right, tmp = world
    turn_on(win)
    put(left, ["a.txt"])
    journal_of(win, tmp).add(Entry("copy", [str(left / "a.txt")], str(right)))
    d.resume_answer = "later"
    win.offer_resume()
    assert len(journal_of(win, tmp).load()) == 1 and not (right / "a.txt").exists()
    d.resume_answer = "discard"
    win.offer_resume()
    assert journal_of(win, tmp).load() == [] and not (right / "a.txt").exists() and not win.busy


def test_the_offer_comes_once_when_the_window_is_shown(world):
    win, d, left, right, tmp = world
    turn_on(win)
    journal_of(win, tmp).add(Entry("copy", [str(left / "a.txt")], str(right)))
    win._resume_offered = False
    win.schedule_resume_offer()
    win.schedule_resume_offer()
    pump(win, lambda: d.resume_asked)
    for _ in range(20):
        QApplication.processEvents()
    assert len(d.resume_asked) == 1


def test_the_settings_dialog_has_the_switch_and_the_forget_button(world, monkeypatch):
    win, d, left, right, tmp = world
    journal_of(win, tmp).add(Entry("copy", ["x"], "y"))
    dlg = CopySettingsDialog(win, win.copy_settings())
    assert dlg.remember.isChecked() is False and dlg.values()["remember_queue"] is False
    dlg.remember.setChecked(True)
    dlg.forget.click()
    assert dlg.values()["remember_queue"] is True and dlg.forgotten
    monkeypatch.setattr(type(win), "_run_copy_settings", lambda self, dialog: (dialog.remember.setChecked(True), dialog.forget.click(), True)[2])
    win.open_copy_settings()
    assert win.copy_settings()["remember_queue"] is True and journal_of(win, tmp).load() == []
    journal_of(win, tmp).add(Entry("copy", ["x"], "y"))
    monkeypatch.setattr(type(win), "_run_copy_settings", lambda self, dialog: (dialog.remember.setChecked(False), True)[1])
    win.open_copy_settings()                                       # switching it off also forgets what was kept
    assert win.copy_settings()["remember_queue"] is False and not (tmp / "queue.json").exists()


# the gaps: other jobs, failed jobs, kept choices, the reminder -----------------------------------------------------------------------------
def test_a_job_that_is_not_a_plain_copy_is_remembered_as_its_steps(world):
    win, d, left, right, tmp = world
    turn_on(win)
    put(left, ["a.txt", "b.txt"])
    plan = plan_copy(win.fs, [str(left / "a.txt"), str(left / "b.txt")], str(right))
    win.toggle_pause()
    win._run(plan)                                                # no intent given: what unpack, sync and the assistant do
    wait(lambda: journal_of(win, tmp).load())
    kept = journal_of(win, tmp).load()
    assert kept[0].kind == "plan" and len(kept[0].ops) == 2
    win.toggle_pause()
    pump(win, lambda: (right / "b.txt").exists() and journal_of(win, tmp).load() == [])


def test_a_kept_plan_continues_with_what_is_left_and_keeps_its_choice(world):
    win, d, left, right, tmp = world
    turn_on(win)
    put(left, ["a.txt", "b.txt"], mtime=1_700_000_000)
    put(right, ["b.txt"], text="old", mtime=1_600_000_000)         # an older, different b.txt: the owner chose to overwrite it
    from dossier.core.ops import Resolution
    from dossier.core.queue_journal import plan_entry
    plan = plan_copy(win.fs, [str(left / "a.txt"), str(left / "b.txt")], str(right)).resolve(Resolution.OVERWRITE, win.fs)
    journal_of(win, tmp).add(plan_entry(plan))
    put(right, ["a.txt"], mtime=1_700_000_000)                      # a.txt was copied before the stop
    d.resume_answer = "continue"
    win.offer_resume()
    pump(win, lambda: (right / "b.txt").read_text() == "xb.txt" and journal_of(win, tmp).load() == [])
    assert not hasattr(d, "conflict_rows_seen")                    # nobody was asked again


def test_a_job_with_failed_steps_stays_on_the_list(world):
    win, d, left, right, tmp = world
    turn_on(win)
    put(left, ["a.txt"])
    plan = plan_copy(win.fs, [str(left / "a.txt")], str(right))
    (left / "a.txt").unlink()                                      # gone before it runs: the step fails
    win._run(plan)
    pump(win, lambda: not win.busy)
    win._journal_file().flush()
    kept = journal_of(win, tmp).load()
    assert len(kept) == 1 and "failed" in kept[0].note and "failed" in kept[0].describe()


def test_the_reminder_after_not_now_and_the_menu_command(world):
    win, d, left, right, tmp = world
    turn_on(win)
    win.offer_resume(manual=True)
    assert "No unfinished" in win.status.text()
    journal_of(win, tmp).add(Entry("copy", [str(left / "a.txt")], str(right)))
    d.resume_answer = "later"
    win.offer_resume(manual=True)
    assert "1 unfinished operation remembered" in win.status.text() and "Unfinished Operations" in win.status.text()
    turn_on(win, False)
    win.offer_resume(manual=True)
    assert "not remembered" in win.status.text()


def test_the_menu_has_the_command(world):
    win, d, left, right, tmp = world
    texts = [a.text() for a in win.findChildren(type(win.menuBar().actions()[0])) if a.text()]
    assert any(t.startswith("Unfinished Operations") for t in texts)
