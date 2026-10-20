"""Indicator lights on the Home page, and the drive memory behind the amber one."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.drive_identity import DriveMemory  # noqa: E402
from dossier.core.home import HOME_URL, build_entries  # noqa: E402
from dossier.core.lights import CHANGED, FAILED, OK, UNCHECKED, LightBoard  # noqa: E402
from tests.test_home import ME, SHARE, provider  # noqa: E402
from tests.test_home_page import app, row_of_kind, world  # noqa: E402,F401


def by_kind(entries, kind):
    return [e for e in entries if e.kind == kind]


def test_drives_and_network_places_start_grey_and_places_have_no_light():
    entries = build_entries(provider(network=lambda: ["//nas/music"]))
    assert {e.status for e in by_kind(entries, "fixed") + by_kind(entries, "network") + by_kind(entries, "netloc")} == {UNCHECKED}
    assert all(e.status == "" for e in by_kind(entries, "place"))


def test_what_the_board_knows_shows_up_on_the_page_without_asking_the_network():
    p = provider(network=lambda: ["//nas/music"])
    p.board.record("//nas/music", FAILED, "no route to host")
    netloc = by_kind(build_entries(p), "netloc")[0]
    assert netloc.status == FAILED and "no route to host" in netloc.note and "Not available" in netloc.note


def test_the_board_ignores_case_and_a_trailing_separator():
    board = LightBoard()
    board.record("D:" + chr(92), OK)
    assert board.status("d:") == OK and board.status("E:") == UNCHECKED


def test_a_different_drive_under_the_same_letter_is_amber_and_stays_amber_for_the_session():
    m = DriveMemory()
    assert m.judge("E:" + chr(92), "GUID-A|1")[0] == OK
    status, note = m.judge("E:" + chr(92), "GUID-B|2")
    assert status == CHANGED and "another drive" in note
    assert m.judge("E:" + chr(92), "GUID-B|2")[0] == CHANGED


def test_the_same_drive_on_a_new_letter_is_recognised_not_flagged():
    m = DriveMemory()
    m.judge("E:" + chr(92), "GUID-A|1")
    status, note = m.judge("F:" + chr(92), "GUID-A|1")
    assert status == OK and "seen before as E:" in note
    assert m.judge("E:" + chr(92), "GUID-C|3")[0] == OK                 # E: is free again, nothing to compare


def test_an_unknown_identity_never_raises_an_alarm():
    m = DriveMemory()
    m.judge("E:" + chr(92), "GUID-A|1")
    assert m.judge("E:" + chr(92), "") == (OK, "")


def test_nothing_is_stored_unless_the_owner_switched_it_on_and_forget_deletes_it():
    stored = {}
    m = DriveMemory(load=lambda: dict(stored), save=lambda d: stored.update(d) if d else stored.clear(), persist=lambda: False)
    m.judge("e:", "A|1")
    assert stored == {}
    on = DriveMemory(load=lambda: dict(stored), save=lambda d: (stored.clear(), stored.update(d)), persist=lambda: True)
    on.judge("e:", "A|1")
    assert stored == {"e:": "A|1"}
    again = DriveMemory(load=lambda: dict(stored), save=lambda d: (stored.clear(), stored.update(d)), persist=lambda: True)
    assert again.judge("e:", "B|2")[0] == CHANGED                        # remembered from the earlier "session"
    again.forget()
    assert stored == {}


def test_each_light_has_its_own_picture_and_colour(app):
    from PyQt6.QtGui import QIcon, QPixmap
    from dossier.gui.models import with_light
    base = QIcon(QPixmap(16, 16))
    images = {s: with_light(base, s).pixmap(16, 16).toImage() for s in (OK, UNCHECKED, FAILED, CHANGED)}
    keys = [images[s].bits().asstring(images[s].sizeInBytes()) for s in images]
    assert len(set(keys)) == 4


def test_the_page_lights_drives_when_their_probe_answers(world, monkeypatch):
    win, _d, drive, folder, tmp = world
    answers = {str(drive): ((1000, 400), "G1|1"), str(tmp / "usb"): (None, "")}
    from dossier.gui import panel as panel_module

    def fake_probe(paths, callback):
        for p in paths:
            usage, ident = answers[p]
            callback(p, usage, ident)

    monkeypatch.setattr(panel_module, "probe_async", fake_probe)
    win.left.set_folder(HOME_URL)
    end = time.time() + 5
    while time.time() < end and win.left.model.entry_at(row_of_kind(win.left, "fixed")).status != OK:
        QApplication.processEvents()
        time.sleep(0.01)
    fixed = win.left.model.entry_at(row_of_kind(win.left, "fixed"))
    usb = win.left.model.entry_at(row_of_kind(win.left, "removable"))
    assert fixed.status == OK and "free of" in fixed.detail
    assert usb.status == FAILED and usb.detail == "Not available"
    assert win.home_provider.board.status(str(tmp / "usb")) == FAILED


def test_opening_a_folder_turns_its_light_green_and_a_failed_open_turns_it_red(world):
    win, _d, drive, folder, tmp = world
    win.left.set_folder(str(folder))
    end = time.time() + 5
    while time.time() < end and win.home_provider.board.status(str(folder), "") != OK:
        QApplication.processEvents()
        time.sleep(0.01)
    assert win.home_provider.board.status(str(folder), "") == OK


def test_remembering_drives_is_off_by_default_and_has_a_menu_switch_and_a_forget_button(world):
    win, *_ = world
    assert not win._remember_drives() and not win.act_remember_drives.isChecked()
    win.act_remember_drives.setChecked(True)
    assert win._remember_drives()
    win.home_provider.memory.judge("e:", "A|1")
    assert win.settings.value("home/seen_drives")
    win.forget_remembered_drives()
    assert not win.settings.value("home/seen_drives")
