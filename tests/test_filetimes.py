"""Changing dates and attributes: the plan shows old and new, apply writes, restore brings the old back."""
import os

import pytest

from dossier.core import filetimes as ft
from dossier.core.platform import IS_WINDOWS
from dossier.core.progress import CancelToken, Cancelled

T = 1_600_000_000.0                  # 2020-09-13


def make(path, text="x", mtime=T, atime=T):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (atime, mtime))
    return str(path)


def test_set_the_modified_date(tmp_path):
    f = make(tmp_path / "a.txt")
    plan = ft.plan_times([f], ft.Rule(ft.SET, when=T + 86400), ["modified"])
    assert plan[0].old.modified == T and plan[0].new.modified == T + 86400 and plan[0].new.accessed == plan[0].old.accessed
    result = ft.apply(plan)
    assert result.done == 1 and not result.failed
    assert os.stat(f).st_mtime == T + 86400


def test_shift_all_the_chosen_dates_by_a_difference(tmp_path):
    f = make(tmp_path / "a.txt", mtime=T, atime=T + 10)
    plan = ft.plan_times([f], ft.Rule(ft.SHIFT, seconds=-3600), ["modified", "accessed"])
    ft.apply(plan)
    assert os.stat(f).st_mtime == T - 3600 and os.stat(f).st_atime == T + 10 - 3600


def test_take_the_date_from_another_file(tmp_path):
    src = make(tmp_path / "src.txt", mtime=T + 5000)
    dst = make(tmp_path / "dst.txt")
    ft.apply(ft.plan_times([dst], ft.Rule(ft.FROM_FILE, source=src), ["modified"]))
    assert os.stat(dst).st_mtime == T + 5000


@pytest.mark.skipif(not IS_WINDOWS, reason="only Windows has a creation date to set")
def test_the_creation_date_can_be_set_and_copied_from_modified(tmp_path):
    f = make(tmp_path / "a.txt", mtime=T)
    ft.apply(ft.plan_times([f], ft.Rule(ft.COPY_FIELD, source_field="modified"), ["created"]))
    assert abs(ft.read_times(f).created - T) < 1
    ft.apply(ft.plan_times([f], ft.Rule(ft.SET, when=T - 1000), ["created"]))
    assert abs(ft.read_times(f).created - (T - 1000)) < 1
    assert os.stat(f).st_mtime == T                                       # only the creation date moved


@pytest.mark.skipif(IS_WINDOWS, reason="where a creation date can be set, it is allowed")
def test_the_creation_date_is_refused_where_it_cannot_be_set(tmp_path):
    f = make(tmp_path / "a.txt")
    with pytest.raises(ft.TimeError):
        ft.plan_times([f], ft.Rule(ft.SET, when=T), ["created"])


def test_a_read_only_file_and_a_folder_can_be_changed(tmp_path):
    f = make(tmp_path / "ro.txt")
    folder = tmp_path / "dir"
    folder.mkdir()
    ft.apply(ft.plan_flags([f], set_on=["readonly"]))
    assert "readonly" in ft.read_flags(f)
    ft.apply(ft.plan_times([f, str(folder)], ft.Rule(ft.SET, when=T + 1), ["modified"]))
    assert os.stat(f).st_mtime == T + 1 and os.stat(folder).st_mtime == T + 1
    assert "readonly" in ft.read_flags(f)                                  # the attribute is as it was
    ft.apply(ft.plan_flags([f], set_off=["readonly"]))
    assert "readonly" not in ft.read_flags(f)


def test_a_folder_below_is_done_after_what_is_inside_it(tmp_path):
    inner = make(tmp_path / "top" / "sub" / "a.txt")
    plan = ft.plan_times([str(tmp_path / "top")], ft.Rule(ft.SET, when=T + 7), ["modified"], recursive=True)
    assert len(plan) == 3 and {c.is_dir for c in plan} == {True, False}
    ft.apply(plan)
    assert os.stat(inner).st_mtime == T + 7
    assert os.stat(tmp_path / "top" / "sub").st_mtime == T + 7 and os.stat(tmp_path / "top").st_mtime == T + 7


def test_not_into_folders_when_asked(tmp_path):
    make(tmp_path / "top" / "a.txt")
    plan = ft.plan_times([str(tmp_path / "top")], ft.Rule(ft.SET, when=T + 7), ["modified"], recursive=True, include_folders=False)
    assert [os.path.basename(c.path) for c in plan] == ["a.txt"]


def test_restore_puts_the_old_values_back(tmp_path):
    f = make(tmp_path / "a.txt")
    plan = ft.plan_times([f], ft.Rule(ft.SET, when=T + 999), ["modified"])
    ft.apply(plan)
    ft.apply(ft.restore_plan(plan))
    assert os.stat(f).st_mtime == T


def test_an_item_that_cannot_change_is_listed_and_the_rest_goes_on(tmp_path):
    f = make(tmp_path / "a.txt")
    plan = ft.plan_times([f, str(tmp_path / "missing.txt"), "sftp://host/x"], ft.Rule(ft.SET, when=T + 1), ["modified"])
    assert [bool(c.problem) for c in plan] == [False, True, True]
    result = ft.apply(plan)
    assert result.done == 1 and os.stat(f).st_mtime == T + 1


def test_nothing_is_written_by_planning(tmp_path):
    f = make(tmp_path / "a.txt")
    ft.plan_times([f], ft.Rule(ft.SET, when=T + 1), ["modified"])
    ft.plan_flags([f], set_on=["readonly"])
    assert os.stat(f).st_mtime == T and "readonly" not in ft.read_flags(f)


def test_the_photo_date_comes_from_the_picture(tmp_path, monkeypatch):
    f = make(tmp_path / "p.jpg")
    from dossier.core import exif
    monkeypatch.setattr(exif, "read_exif", lambda path: exif.Exif(fields=[("Date", "Date taken", "2019:07:14 16:02:33")]))
    plan = ft.plan_times([f], ft.Rule(ft.FROM_EXIF), ["modified"])
    ft.apply(plan)
    from datetime import datetime
    assert os.stat(f).st_mtime == datetime(2019, 7, 14, 16, 2, 33).timestamp()
    monkeypatch.setattr(exif, "read_exif", lambda path: exif.Exif(error="no EXIF block"))
    assert "no date taken" in ft.plan_times([f], ft.Rule(ft.FROM_EXIF), ["modified"])[0].problem


def test_cancel_stops_planning_and_applying(tmp_path):
    f = make(tmp_path / "a.txt")
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        ft.plan_times([f], ft.Rule(ft.SET, when=T), ["modified"], cancel=token)
    with pytest.raises(Cancelled):
        ft.apply(ft.plan_times([f], ft.Rule(ft.SET, when=T + 1), ["modified"]), cancel=token)


def test_no_date_chosen_is_a_mistake(tmp_path):
    with pytest.raises(ft.TimeError):
        ft.plan_times([make(tmp_path / "a.txt")], ft.Rule(ft.SET, when=T), [])


def test_unknown_attribute_is_refused():
    with pytest.raises(ft.TimeError):
        ft.plan_flags([], set_on=["sparkly"])
