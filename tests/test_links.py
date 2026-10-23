"""Symbolic links, junctions and hard links: what a path is, making new ones, and the refusals."""
import os
import sys

import pytest

from dossier.core import links
from dossier.core.platform import IS_WINDOWS


def can_symlink(tmp_path) -> bool:
    try:
        probe = tmp_path / "probe"
        os.symlink(str(tmp_path), str(probe), target_is_directory=True)
        probe.unlink() if not IS_WINDOWS else os.rmdir(probe)
        return True
    except (OSError, NotImplementedError):
        return False


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("hello")
    (tmp_path / "out").mkdir()
    return tmp_path


def test_an_ordinary_item_is_not_a_link(tree):
    assert links.inspect(str(tree / "docs" / "a.txt")) == links.LinkInfo()
    assert links.inspect(str(tree / "docs")).kind == ""
    assert links.inspect(str(tree / "missing")).kind == ""


def test_a_hard_link_is_a_second_name_for_the_same_file(tree):
    target, link = str(tree / "docs" / "a.txt"), str(tree / "out" / "b.txt")
    links.create(links.HARDLINK, target, link)
    assert open(link).read() == "hello"
    info = links.inspect(link)
    assert info.hardlinks == 2 and info.kind == ""
    assert "2 names" in links.what_is(info)
    if IS_WINDOWS:
        assert [os.path.normcase(n) for n in info.other_names] == [os.path.normcase(target)]
    os.remove(link)
    assert os.path.exists(target) and links.inspect(target).hardlinks == 1


def test_a_symlink_shows_where_it_points_and_when_it_is_broken(tree):
    if not can_symlink(tree):
        pytest.skip("this account may not make symbolic links")
    link = str(tree / "out" / "to-docs")
    links.create(links.SYMLINK, str(tree / "docs"), link)
    info = links.inspect(link)
    assert info.kind == links.SYMLINK and os.path.normcase(info.target) == os.path.normcase(str(tree / "docs")) and not info.broken
    assert os.path.exists(os.path.join(link, "a.txt"))
    os.rename(tree / "docs", tree / "docs-moved")
    assert links.inspect(link).broken and "broken" in links.what_is(links.inspect(link))


def test_a_relative_symlink_survives_moving_both(tree):
    if not can_symlink(tree):
        pytest.skip("this account may not make symbolic links")
    links.create(links.SYMLINK, str(tree / "docs" / "a.txt"), str(tree / "out" / "rel"), relative=True)
    info = links.inspect(str(tree / "out" / "rel"))
    assert not os.path.isabs(info.target) and not info.broken
    os.rename(tree, str(tree) + "-moved")
    try:
        assert os.path.exists(os.path.join(str(tree) + "-moved", "out", "rel"))
    finally:
        os.rename(str(tree) + "-moved", tree)


@pytest.mark.skipif(not IS_WINDOWS, reason="junctions exist only on Windows")
def test_a_junction_shows_a_folder_and_deleting_it_keeps_the_folder(tree):
    link = str(tree / "out" / "j")
    links.create(links.JUNCTION, str(tree / "docs"), link)
    info = links.inspect(link)
    assert info.kind == links.JUNCTION and os.path.normcase(info.target) == os.path.normcase(str(tree / "docs"))
    assert open(os.path.join(link, "a.txt")).read() == "hello"
    os.rmdir(link)
    assert (tree / "docs" / "a.txt").exists()


@pytest.mark.skipif(IS_WINDOWS, reason="only where junctions do not exist")
def test_a_junction_is_refused_where_there_are_none(tree):
    with pytest.raises(links.LinkError, match="only on Windows"):
        links.create(links.JUNCTION, str(tree / "docs"), str(tree / "out" / "j"))


def test_the_refusals_say_why(tree):
    a = str(tree / "docs" / "a.txt")
    with pytest.raises(links.LinkError, match="does not exist"):
        links.create(links.HARDLINK, str(tree / "nope"), str(tree / "out" / "x"))
    with pytest.raises(links.LinkError, match="already there"):
        links.create(links.HARDLINK, a, str(tree / "docs" / "a.txt"))
    with pytest.raises(links.LinkError, match="folder for the link"):
        links.create(links.HARDLINK, a, str(tree / "no-such-folder" / "x"))
    with pytest.raises(links.LinkError, match="for a folder"):
        links.create(links.HARDLINK, str(tree / "docs"), str(tree / "out" / "x"))
    with pytest.raises(links.LinkError, match="unknown"):
        links.create("shortcut", a, str(tree / "out" / "x"))
    assert not (tree / "out" / "x").exists()
    if IS_WINDOWS:
        with pytest.raises(links.LinkError, match="only show a folder"):
            links.create(links.JUNCTION, a, str(tree / "out" / "x"))


def test_nothing_is_replaced(tree):
    (tree / "out" / "taken.txt").write_text("mine")
    with pytest.raises(links.LinkError):
        links.create(links.HARDLINK, str(tree / "docs" / "a.txt"), str(tree / "out" / "taken.txt"))
    assert (tree / "out" / "taken.txt").read_text() == "mine"


def test_the_default_name(tree):
    assert links.default_link_name(str(tree / "docs" / "a.txt"), links.HARDLINK) == "a - link.txt"
    assert links.default_link_name(str(tree / "docs"), links.SYMLINK) == "docs - link"


@pytest.mark.skipif(sys.platform == "win32", reason="a symlink needs a right on Windows; the refusal text is checked in the window tests")
def test_a_symlink_to_a_missing_target_is_refused(tree):
    with pytest.raises(links.LinkError):
        links.create(links.SYMLINK, str(tree / "nope"), str(tree / "out" / "x"))
