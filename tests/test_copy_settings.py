"""Settings > Copy and Move...: one dialog for every setting that changes how files are copied or moved."""
import pytest

pytest.importorskip("PyQt6")

from dossier.gui.copy_settings import DEFAULTS, CopySettingsDialog  # noqa: E402
from tests.test_gui_commander import app, world  # noqa: E402,F401


def test_nothing_stored_gives_the_defaults(world):
    win, *_ = world
    assert win.copy_settings() == DEFAULTS
    o = win._exec_options()
    assert o.limit_bps is None and o.verify is False and o.retries == 3 and o.workers is None
    assert o.native_copy is True and o.flush is None and o.on_error is None


def test_the_dialog_shows_the_values_and_hands_back_what_was_changed(world):
    win, *_ = world
    dlg = CopySettingsDialog(win, win.copy_settings())
    dlg.limit.setValue(12.5)
    dlg.verify.setChecked(True)
    dlg.workers.setValue(4)
    dlg.native.setChecked(False)
    dlg.flush.setCurrentIndex(dlg.flush.findData("always"))
    dlg.retries.setValue(7)
    dlg.retry_delay.setValue(1.5)
    dlg.ask.setChecked(True)
    assert dlg.values() == {"limit_mb": 12.5, "verify": True, "ask_on_error": True, "retries": 7, "retry_delay": 1.5,
                            "workers": 4, "native": False, "flush": "always", "ask_on_drop": False, "remember_queue": False}


def test_saving_changes_the_next_run_and_the_state_of_the_confirmation_checkbox(world, monkeypatch):
    win, *_ = world
    monkeypatch.setattr(type(win), "_run_copy_settings", lambda self, dlg: (
        dlg.limit.setValue(5), dlg.verify.setChecked(True), dlg.workers.setValue(2), dlg.native.setChecked(False),
        dlg.flush.setCurrentIndex(dlg.flush.findData("never")), dlg.retries.setValue(1), dlg.ask.setChecked(True), True)[-1])
    win.open_copy_settings()
    o = win._exec_options()
    assert o.limit_bps == 5 * 1024 * 1024 and o.verify and o.workers == 2 and not o.native_copy
    assert o.flush is False and o.retries == 1 and o.on_error is not None
    assert win.act_verify.isChecked() and win.act_ask_error.isChecked()
    assert str(win.settings.value("copy/verify")).lower() == "true"


def test_cancelling_changes_nothing(world, monkeypatch):
    win, *_ = world
    monkeypatch.setattr(type(win), "_run_copy_settings", lambda self, dlg: False)
    win.open_copy_settings()
    assert win.copy_settings() == DEFAULTS


def test_damaged_stored_values_fall_back_to_sane_ones(world):
    win, *_ = world
    for k, v in (("limit_mb", "fast"), ("retries", "-4"), ("workers", "999"), ("flush", "sometimes"), ("retry_delay", "x")):
        win.settings.setValue("copy/" + k, v)
    s = win.copy_settings()
    assert s["limit_mb"] == 0.0 and s["retries"] == 0 and s["workers"] == 32 and s["flush"] == "auto" and s["retry_delay"] == 0.25


def test_the_settings_menu_has_one_entry_and_the_old_three_are_gone(world):
    win, *_ = world
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    texts = [a.text() for a in menus["Settings"].actions()]
    assert "Copy and Move..." in texts
    assert not {"Copy Speed Limit", "Verify Copies After Copying", "Ask When a File Cannot Be Copied"} & set(texts)
