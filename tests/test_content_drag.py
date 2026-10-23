"""A picture or text from the clipboard or a drop becomes a new file; items inside an archive can be handed to other programs."""
import os
import time
import zipfile

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core import stage  # noqa: E402
from dossier.core.zipfs import archive_root  # noqa: E402
from dossier.gui import dragdrop  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def wait(until, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


def picture(width=6, height=4):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    return image


def put_on_clipboard(text=None, image=None):
    data = QMimeData()
    if text is not None:
        data.setText(text)
    if image is not None:
        data.setImageData(image)
    QApplication.clipboard().setMimeData(data)


# the clipboard ------------------------------------------------------------------------------------------------------------------------
def test_text_on_the_clipboard_becomes_a_file_with_the_typed_name(world):
    win, d, left, right, tmp = world
    put_on_clipboard(text="some notes\nsecond line")
    d.texts.append("notes")
    win.clip_paste()
    wait(lambda: (left / "notes.txt").exists())
    assert (left / "notes.txt").read_text(encoding="utf-8") == "some notes\nsecond line"
    pump(win, lambda: "Made notes.txt" in win.status.text())


def test_a_picture_on_the_clipboard_becomes_a_png_that_opens_again(world):
    win, d, left, right, tmp = world
    put_on_clipboard(image=picture())
    d.texts.append("shot")
    win.paste_as_new_file()
    wait(lambda: (left / "shot.png").exists())
    back = QImage(str(left / "shot.png"))
    assert (back.width(), back.height()) == (6, 4) and back.pixelColor(0, 0) == QColor("#336699")


def test_the_extension_picks_the_format_and_a_taken_name_is_not_overwritten(world):
    win, d, left, right, tmp = world
    (left / "pic.jpg").write_text("mine")
    put_on_clipboard(image=picture())
    d.texts.append("pic.jpg")
    win.paste_as_new_file()
    wait(lambda: (left / "pic (2).jpg").exists())
    assert (left / "pic.jpg").read_text() == "mine"
    assert (left / "pic (2).jpg").read_bytes()[:2] == b"\xff\xd8"          # a JPEG, because the name said so


def test_the_name_dialog_is_asked_again_for_a_bad_name_and_cancel_makes_nothing(world):
    win, d, left, right, tmp = world
    put_on_clipboard(text="x")
    d.texts += ["a/b.txt", "fine"]
    win.paste_as_new_file()
    wait(lambda: (left / "fine.txt").exists())
    assert d.infos and "separator" in d.infos[-1][1]
    before = set(os.listdir(left))
    put_on_clipboard(text="y")
    win.paste_as_new_file()                                       # the fake dialog answers None: cancelled
    for _ in range(20):
        QApplication.processEvents()
    assert set(os.listdir(left)) == before


def test_nothing_usable_on_the_clipboard(world):
    win, d, left, right, tmp = world
    QApplication.clipboard().clear()
    win.clip_paste()
    assert "no files, picture or text" in win.status.text()
    win.paste_as_new_file()
    assert "no picture or text" in win.status.text()


def test_files_on_the_clipboard_still_paste_as_files(world):
    win, d, left, right, tmp = world
    (right / "f.txt").write_text("file")
    win.right.refresh()
    pump(win, lambda: win.right.model.entry_count() >= 2)
    win.active = win.right if win.active is not win.right else win.active
    win.selection.add([str(right / "f.txt")])
    win.clip_copy()
    win.active = win.left
    win.clip_paste()
    pump(win, lambda: (left / "f.txt").exists())
    assert d.texts == []                                          # no name was asked for


# a drop ---------------------------------------------------------------------------------------------------------------------------------
def drop_of(mime, widget, point):
    return QDropEvent(QPointF(point), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def test_a_drop_of_text_on_the_list_makes_a_file_in_this_folder(world):
    win, d, left, right, tmp = world
    d.texts.append("dropped")
    mime = QMimeData()
    mime.setText("dropped words")
    table = win.left.table
    enter = QDragEnterEvent(QPoint(30, 400), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    table.dragEnterEvent(enter)
    assert enter.isAccepted()
    table.dropEvent(drop_of(mime, table, QPoint(30, 400)))
    wait(lambda: (left / "dropped.txt").exists())
    assert (left / "dropped.txt").read_text() == "dropped words"


def test_a_drop_of_a_picture_on_a_folder_row_makes_the_file_inside_it(world):
    win, d, left, right, tmp = world
    (left / "inbox").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    row = next(r for r in range(win.left.model.entry_count()) if win.left.model.entry_at(r).name == "inbox")
    table = win.left.table
    spot = table.visualRect(table.model().index(row, 0)).center()
    mime = QMimeData()
    mime.setImageData(picture())
    d.texts.append("cat")
    table.dropEvent(drop_of(mime, table, spot))
    wait(lambda: (left / "inbox" / "cat.png").exists())


def test_a_drop_of_files_or_our_own_list_is_not_taken_as_content(world):
    win, d, left, right, tmp = world
    from PyQt6.QtCore import QUrl
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(right))])
    mime.setText(str(right))
    assert dragdrop.content_of(mime) is None
    own = dragdrop.make_mime([str(right)], "x")
    assert dragdrop.content_of(own) is None
    empty = QMimeData()
    empty.setText("   ")
    assert dragdrop.content_of(empty) is None


def test_a_read_only_place_cannot_take_content(world):
    win, d, left, right, tmp = world
    archive = tmp / "a.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("inside.txt", "x")
    win.left.set_folder(archive_root(str(archive)))
    pump(win, lambda: win.left.path.startswith("zip://"))
    assert win.left._content_target(-1) is None
    win._new_file_from_content("text", "x", win.left.path)
    assert "read-only" in win.status.text() and d.texts == []


# dragging out of an archive -------------------------------------------------------------------------------------------------------------
@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "pack.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("readme.txt", "hello")
        z.writestr("docs/one.txt", "1" * 100)
    return str(path)


def test_items_inside_an_archive_get_file_urls_only_when_asked(world, archive, monkeypatch, tmp_path):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    win, d, left, right, tmp = world
    root = archive_root(archive)
    win.left.set_folder(root)
    pump(win, lambda: win.left.path == root)
    paths = [root + "readme.txt", root + "docs"]
    staging = win.left._stage_for_paths(paths)
    assert staging is not None
    called = []
    mime = dragdrop.make_mime(paths, "left", lambda: called.append(1) or staging())
    assert isinstance(mime, dragdrop.LazyFilesMime) and called == []             # nothing copied yet
    assert mime.hasFormat("text/uri-list") and "text/uri-list" in mime.formats() and dragdrop.MIME in mime.formats()
    urls = mime.urls()                                                            # what another program asks for at the drop
    assert [u.fileName() for u in urls] == ["readme.txt", "docs"] and called == [1]
    local = [u.toLocalFile() for u in urls]
    assert open(local[0]).read() == "hello" and open(os.path.join(local[1], "one.txt")).read() == "1" * 100
    mime.urls()
    assert called == [1]                                                          # asked twice, copied once
    paths_back, source = dragdrop.read_paths(mime)
    assert paths_back == paths and source == "left"                               # inside Dossier the exact list is used
    stage.clean_up(everything=True)


def test_local_items_need_no_staging_and_a_big_drag_is_refused(world, archive, monkeypatch):
    win, d, left, right, tmp = world
    assert win.left._stage_for_paths([str(left / "x.txt")]) is None
    root = archive_root(archive)
    win.left.set_folder(root)
    pump(win, lambda: win.left.path == root)
    monkeypatch.setattr(stage, "LIMIT", 3)
    assert win.left._stage_for_paths([root + "readme.txt"]) is None
    pump(win, lambda: "Too big to hand to another program" in win.status.text())


def test_a_failed_staging_gives_the_other_program_nothing_instead_of_crashing(world):
    def boom():
        raise OSError("server went away")
    mime = dragdrop.make_mime(["sftp://host/a.txt"], "left", boom)
    assert mime.urls() == []


def test_the_edit_menu_has_the_command(world):
    win, d, left, right, tmp = world
    texts = {a.text() for a in win.findChildren(type(win.menuBar().actions()[0])) if a.text()}
    assert "Paste Picture or Text as New File..." in texts


def test_a_web_link_dropped_from_a_browser_becomes_an_internet_shortcut(world):
    from PyQt6.QtCore import QUrl
    win, d, left, right, tmp = world
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.org/page?x=1")])
    assert dragdrop.content_of(mime) == ("link", "https://example.org/page?x=1")
    table = win.left.table
    d.texts.append("example.org")
    table.dropEvent(drop_of(mime, table, QPoint(30, 400)))
    wait(lambda: (left / "example.org.url").exists())
    assert (left / "example.org.url").read_bytes() == b"[InternetShortcut]\r\nURL=https://example.org/page?x=1\r\n"


def test_the_names_of_a_link_file():
    from dossier.core import newfile
    assert newfile.suggested_name(newfile.LINK, url="https://www.example.org/a/b") == "www.example.org.url"
    assert newfile.suggested_name(newfile.LINK, url="nonsense") == "link.url"
    assert newfile.clean_name("site", newfile.LINK) == "site.url"
