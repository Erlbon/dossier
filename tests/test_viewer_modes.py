"""The F3 viewer in its modes: a picture, a binary file as hex, Markdown rendered; chosen by content, switchable, safe."""
import struct
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt, QUrl  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui.viewer import TextViewerWindow  # noqa: E402
from tests.test_gui_commander import pump, world  # noqa: E402,F401
from tests.test_viewer import app, settle  # noqa: E402,F401
from tests.test_viewmodes import sample_block, tiff  # noqa: E402


def wait(until, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


def picture(path, w=40, h=20, fmt="PNG"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(0x3366CC)
    assert img.save(str(path), fmt)
    return str(path)


def photo_with_exif(path, w=40, h=20, orientation=6):
    """A JPEG whose EXIF says it was taken with the camera turned (orientation 6: a quarter turn right)."""
    plain = picture(path, w, h, "JPG")
    data = open(plain, "rb").read()
    block = tiff([(0x010F, 2, ["Canon"]), (0x0110, 2, ["EOS R6"]), (0x0112, 3, [orientation])],
                 [(0x829A, 5, [(1, 250)]), (0x8827, 3, [400])])
    payload = b"Exif\x00\x00" + block
    open(plain, "wb").write(data[:2] + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + data[2:])
    return plain


@pytest.fixture
def viewer(app):
    made = []

    def make(paths, index=0):
        win = TextViewerWindow([str(p) for p in paths], index)
        win.show()
        made.append(win)
        return win
    yield make
    for w in made:
        w.close()


# pictures -------------------------------------------------------------------------------------------------------------------------
def test_a_picture_opens_as_an_image_fitted_to_the_window_with_hex_as_the_other_view(viewer, tmp_path):
    win = viewer([picture(tmp_path / "a.png", 400, 300)])
    assert win.mode == "image" and win.stack.currentWidget() is win.image_page
    wait(lambda: win.image_page.view.has_image())
    assert win.image_page.view.image_size() == (400, 300) and "400 x 300" in win.position.text()
    assert [win.mode_box.itemText(i) for i in range(win.mode_box.count())] == ["Image", "Hex"]
    view = win.image_page.view
    win.resize(300, 300)
    QApplication.processEvents()
    assert view.zoom < 1.0                                         # a big picture is fitted into a small window
    view.actual_size()
    assert view.zoom == 1.0
    view.zoom_by(2.0)
    assert abs(view.zoom - 2.0) < 1e-6 and "200%" in (win._update_status() or win.position.text())
    view.fit()
    assert view.zoom < 1.0


def test_a_small_picture_is_never_enlarged_by_fit_and_turning_swaps_its_sides(viewer, tmp_path):
    win = viewer([picture(tmp_path / "s.png", 40, 20)])
    wait(lambda: win.image_page.view.has_image())
    view = win.image_page.view
    view.fit()
    assert view.zoom == 1.0
    assert (view._item.boundingRect().width(), view._item.boundingRect().height()) == (40, 20)
    view.turn(1)
    assert (view._item.boundingRect().width(), view._item.boundingRect().height()) == (20, 40)
    view.turn(-1)
    assert view._item.boundingRect().width() == 40
    view.toggle_fit()
    assert view.zoom == 1.0


def test_a_photo_is_turned_upright_by_its_exif_and_the_info_panel_shows_the_exif(viewer, tmp_path):
    win = viewer([photo_with_exif(tmp_path / "p.jpg", 40, 20, 6)])
    wait(lambda: win.image_page.view.has_image())
    assert win.image_page.view.image_size() == (20, 40)           # stored 40 x 20, taken with the camera turned
    win.image_info.setChecked(True)
    assert not win.image_page.info.isHidden()
    texts = []
    tree = win.image_page.info

    def walk(item):
        texts.append(" ".join(item.text(i) for i in range(2)))
        for k in range(item.childCount()):
            walk(item.child(k))
    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    joined = "\n".join(texts)
    assert "Canon EOS R6" in joined and "1/250 s" in joined and "ISO 400" in joined and "20 x 40 pixels" in joined
    win.image_info.setChecked(False)
    assert win.image_page.info.isHidden()


def test_a_picture_without_exif_says_so_and_a_picture_that_cannot_be_decoded_offers_hex(viewer, tmp_path):
    win = viewer([picture(tmp_path / "plain.png")])
    wait(lambda: win.image_page.view.has_image())
    win.image_info.setChecked(True)
    assert "no EXIF block" in str([win.image_page.info.topLevelItem(i).child(0).text(1) for i in range(win.image_page.info.topLevelItemCount())])
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    bad = viewer([broken])
    wait(lambda: "cannot be decoded" in bad.status.text())
    bad.mode_box.setCurrentIndex(bad.mode_box.findData("hex"))
    assert bad.mode == "hex" and bad.hexfile is not None


def test_the_content_decides_not_the_name(viewer, tmp_path):
    odd = tmp_path / "photo.dat"
    odd.write_bytes(open(picture(tmp_path / "tmp.png"), "rb").read())
    assert viewer([odd]).mode == "image"
    text = tmp_path / "fake.jpg"
    text.write_text("this is only text\n")
    win = viewer([text])
    settle(win)
    assert win.mode == "text"


def test_next_and_previous_step_between_files_of_different_kinds(viewer, tmp_path):
    a, b = picture(tmp_path / "a.png"), tmp_path / "b.txt"
    b.write_text("hello\n")
    win = viewer([a, b])
    wait(lambda: win.image_page.view.has_image())
    win.step(1)
    settle(win)
    assert win.mode == "text" and win.stack.currentWidget() is win.view and win.image_page.view.has_image() is False
    win.step(1)
    assert win.mode == "image"


# hex ------------------------------------------------------------------------------------------------------------------------------
def make_bin(tmp_path, n=1000):
    p = tmp_path / "data.bin"
    p.write_bytes(bytes(i % 256 for i in range(n)))
    return p


def test_a_binary_file_opens_as_hex_and_the_cursor_selection_and_copy_work(viewer, tmp_path):
    win = viewer([make_bin(tmp_path)])
    assert win.mode == "hex" and win.hexfile.size == 1000 and win.stack.currentWidget() is win.hex
    assert [win.mode_box.itemText(i) for i in range(win.mode_box.count())] == ["Hex", "Text"]
    hexv = win.hex
    assert hexv.cursor == 0 and "Offset 0x0" in win.position.text() and "8-bit 0" in win.status.text()
    QTest.keyClick(hexv, Qt.Key.Key_Right)
    QTest.keyClick(hexv, Qt.Key.Key_Down)
    assert hexv.cursor == 17
    QTest.keyClick(hexv, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(hexv, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert hexv.selection() == (17, 3) and "3 bytes selected" in win.position.text()
    hexv.copy_hex()
    assert QGuiApplication.clipboard().text() == "11 12 13"
    hexv.copy_text()
    assert QGuiApplication.clipboard().text() == "..."
    QTest.keyClick(hexv, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    assert hexv.cursor == 999
    QTest.keyClick(hexv, Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
    assert hexv.cursor == 0
    QTest.keyClick(hexv, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert hexv.selection() == (0, 1000)


def test_clicking_a_byte_in_the_hex_or_the_text_column_puts_the_cursor_on_it(viewer, tmp_path):
    win = viewer([make_bin(tmp_path)])
    hexv = win.hex
    win.resize(900, 500)
    QApplication.processEvents()
    from PyQt6.QtCore import QPoint
    y = hexv.lh * 2 + 3                                            # the third row: offsets 0x20 to 0x2F
    QTest.mouseClick(hexv.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(hexv._byte_x(5) + 2, y))
    assert hexv.cursor == 32 + 5
    QTest.mouseClick(hexv.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(hexv._byte_x(12) + 2, y))
    assert hexv.cursor == 32 + 12                                  # past the gap in the middle
    QTest.mouseClick(hexv.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(hexv._text_x() + 3 * hexv.cw + 1, y))
    assert hexv.cursor == 32 + 3


def test_the_hex_find_looks_for_text_or_bytes_forward_and_back_and_goto_jumps(viewer, tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"\x00" * 100 + b"Needle" + b"\x00" * 100 + b"needle" + b"\x00" * 10)
    win = viewer([p])
    def searched():
        wait(lambda: win._job is not None and win._job.state.name in ("DONE", "CANCELLED", "FAILED") and win.status.text() != "Searching...")

    win.find_edit.setText("needle")
    win.find(forward=True)
    searched()
    assert win.hex.match == (100, 6) and "0x64" in win.status.text()            # case is ignored unless asked for
    win.find(forward=True)
    searched()
    assert win.hex.match == (206, 6)
    win.case.setChecked(True)
    win.find(forward=False)                                                     # exact case: only the lower-case one counts
    searched()
    assert win.hex.match == (206, 6) and "0xCE" in win.status.text()
    win.case.setChecked(False)
    win.hex_find_kind.setCurrentIndex(1)
    win.find_edit.setText("4E 65 65")                                           # bytes are always exact: the capital N
    win.find(forward=True)
    searched()
    assert "Found at offset 0x64" in win.status.text()
    win.find_edit.setText("zz")
    win.find(forward=True)
    assert "pairs of digits" in win.status.text()
    win.hex.goto(150)
    assert win.hex.cursor == 150
    win.hex.goto(10_000)                                            # past the end: the last byte
    assert win.hex.cursor == win.hexfile.size - 1


def test_a_text_file_can_be_seen_as_hex_and_back(viewer, tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"ABC\n")
    win = viewer([p])
    settle(win)
    assert win.mode == "text"
    win.mode_box.setCurrentIndex(win.mode_box.findData("hex"))
    assert win.mode == "hex" and win.hexfile.read(0, 4) == b"ABC\n"
    win.mode_box.setCurrentIndex(win.mode_box.findData("text"))
    settle(win)
    assert win.mode == "text" and win.hexfile is None


# Markdown -------------------------------------------------------------------------------------------------------------------------
def md(tmp_path, text, name="doc.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_a_markdown_file_is_rendered_with_its_source_one_choice_away(viewer, tmp_path):
    win = viewer([md(tmp_path, "# Title\n\nSome **bold** text.\n\n- one\n- two\n")])
    assert win.mode == "markdown" and win.stack.currentWidget() is win.markdown
    plain = win.markdown.toPlainText()
    assert "Title" in plain and "bold" in plain and "#" not in plain and "**" not in plain
    assert [win.mode_box.itemText(i) for i in range(win.mode_box.count())] == ["Markdown", "Text", "Hex"]
    win.mode_box.setCurrentIndex(win.mode_box.findData("text"))
    settle(win)
    assert win.mode == "text" and win.view.total == 6


def test_raw_html_in_markdown_is_shown_as_text_and_never_run(viewer, tmp_path):
    win = viewer([md(tmp_path, "# T\n\n<script>alert(1)</script> and <b>bold</b>\n\n`<i>code</i>`\n")])
    plain = win.markdown.toPlainText()
    assert "<script>alert(1)</script>" in plain and "<b>bold</b>" in plain and "<i>code</i>" in plain
    assert "<script" not in win.markdown.toHtml().replace("&lt;script", "")


def test_links_open_only_the_web_mail_and_files_on_this_computer(viewer, tmp_path, monkeypatch):
    other = md(tmp_path, "# Other\n", "other.md")
    win = viewer([md(tmp_path, "[x](a)\n")])
    opened = []
    monkeypatch.setattr("dossier.gui.markdown_view.QDesktopServices.openUrl", lambda url: opened.append(url.toString()) or True)
    win.markdown._clicked(QUrl("https://example.com/page"))
    win.markdown._clicked(QUrl("mailto:me@example.com"))
    assert opened == ["https://example.com/page", "mailto:me@example.com"]
    win.markdown._clicked(QUrl("javascript:alert(1)"))
    assert "not opened" in win.status.text() and len(opened) == 2
    win.markdown._clicked(QUrl("ftp://host/file"))
    assert len(opened) == 2
    win.markdown._clicked(QUrl("other.md"))                         # a file beside this one: shown next, in this window
    wait(lambda: win.paths[-1] == str(other) or str(other) in win.paths)
    assert win.paths[win.index] == str(other) and "Other" in win.markdown.toPlainText()
    win.step(-1)
    assert win.paths[win.index].endswith("doc.md")
    win.markdown._clicked(QUrl("missing-file.md"))
    assert "No such file" in win.status.text()


def test_a_big_markdown_file_is_shown_as_text_and_find_works_in_the_rendered_view(viewer, tmp_path):
    big = md(tmp_path, "word " * 60000, "big.md")
    win = viewer([big])
    settle(win)
    assert win.mode == "text" and "too big to render" in win.status.text()
    small = viewer([md(tmp_path, "# Head\n\nfind the Needle here\n\nanother needle\n", "s.md")])
    small.find_edit.setText("needle")
    small.find(forward=True)
    assert small.markdown.textCursor().selectedText().lower() == "needle" and small.status.text() == "Found"
    small.find(forward=True)
    small.find(forward=True)
    assert "wrapping" in small.status.text()


# the window opens a picture with its folder ---------------------------------------------------------------------------------------
def test_f3_on_one_picture_steps_through_the_pictures_of_its_folder(world, tmp_path):
    win, d, left, right, tmp = world
    for n in ("img10.png", "img2.png", "img1.png"):
        picture(left / n)
    (left / "notes.txt").write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 5)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("img2.png"), 0))
    win.view_file()
    viewer = win.viewers[0]
    assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in viewer.paths] == ["img1.png", "img2.png", "img10.png"]
    assert viewer.index == 1 and viewer.mode == "image"
    viewer.close()


# the wheel -------------------------------------------------------------------------------------------------------------------------------
def wheel(view, delta, mods=Qt.KeyboardModifier.NoModifier):
    from PyQt6.QtCore import QPoint, QPointF
    from PyQt6.QtGui import QWheelEvent
    pos = QPointF(10, 10)
    ev = QWheelEvent(pos, view.viewport().mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton, mods,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(view.viewport(), ev)
    QApplication.processEvents()


def test_the_wheel_steps_to_the_next_and_previous_picture_and_ctrl_wheel_still_zooms(viewer, tmp_path):
    paths = [picture(tmp_path / f"p{n}.png", 40 + n, 20) for n in range(3)]
    win = viewer(paths)
    wait(lambda: win.image_page.view.has_image())
    view = win.image_page.view
    assert win.index == 0
    wheel(view, -120)                                    # one notch down: the next picture
    wait(lambda: win.index == 1 and view.has_image())
    wheel(view, -120)
    wait(lambda: win.index == 2 and view.has_image())
    wheel(view, 120)                                     # up: back
    wait(lambda: win.index == 1 and view.has_image())
    before = view.zoom
    wheel(view, 120, Qt.KeyboardModifier.ControlModifier)
    assert win.index == 1 and view.zoom > before        # Ctrl+wheel zooms and does not step


def test_small_touchpad_steps_add_up_to_one_picture(viewer, tmp_path):
    paths = [picture(tmp_path / f"q{n}.png") for n in range(2)]
    win = viewer(paths)
    wait(lambda: win.image_page.view.has_image())
    view = win.image_page.view
    for _ in range(3):
        wheel(view, -30)
    assert win.index == 0                                # 90 so far: not yet a notch
    wheel(view, -30)
    wait(lambda: win.index == 1)


# the setting ----------------------------------------------------------------------------------------------------------------------------
def test_the_wheel_table_falls_back_to_the_defaults_for_anything_unknown():
    from dossier.core import wheel
    assert wheel.clean(None) == wheel.DEFAULTS
    assert wheel.clean({"plain": "zoom", "ctrl": "bogus"}) == {"plain": "zoom", "ctrl": "zoom", "shift": "scroll"}
    assert wheel.key_for(True, True) == "ctrl" and wheel.key_for(False, True) == "shift" and wheel.key_for(False, False) == "plain"


def test_the_viewer_does_what_the_table_says(viewer, tmp_path):
    paths = [picture(tmp_path / f"w{n}.png", 400, 300) for n in range(2)]
    win = viewer(paths)
    wait(lambda: win.image_page.view.has_image())
    view = win.image_page.view
    win.set_wheel_map({"plain": "zoom", "ctrl": "step", "shift": "none"})
    before = view.zoom
    wheel(view, 120)
    assert win.index == 0 and view.zoom > before                          # plain wheel zooms now
    wheel(view, -120, Qt.KeyboardModifier.ControlModifier)
    wait(lambda: win.index == 1 and view.has_image())                     # Ctrl+wheel steps
    zoom = view.zoom
    wheel(view, 120, Qt.KeyboardModifier.ShiftModifier)
    assert win.index == 1 and view.zoom == zoom                           # nothing


def test_scrolling_actions_move_the_bars_of_a_zoomed_picture(viewer, tmp_path):
    win = viewer([picture(tmp_path / "big.png", 800, 600)])
    wait(lambda: win.image_page.view.has_image())
    view = win.image_page.view
    view.actual_size()
    view.zoom_by(4)
    win.set_wheel_map({"plain": "scroll", "ctrl": "scroll_sideways", "shift": "none"})
    vbar, hbar = view.verticalScrollBar(), view.horizontalScrollBar()
    vbar.setValue(vbar.maximum() // 2)
    hbar.setValue(hbar.maximum() // 2)
    v0, h0 = vbar.value(), hbar.value()
    wheel(view, -120)
    assert vbar.value() > v0 and abs(hbar.value() - h0) < 20          # (the view recentres a few pixels sideways)
    wheel(view, -120, Qt.KeyboardModifier.ControlModifier)
    assert hbar.value() > h0


def test_the_wheel_dialog_keeps_the_choices_and_open_viewers_follow(world, tmp_path, monkeypatch):
    from dossier.gui.wheel_settings import WheelDialog
    win, _d, left, _r, _t = world
    picture(left / "a.png")
    picture(left / "b.png")
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("a.png") >= 0)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.png"), 0))
    win.view_file()
    wait(lambda: win.viewers and win.viewers[0].image_page.view.has_image())
    assert win.wheel_map() == {"plain": "scroll_step", "ctrl": "zoom", "shift": "scroll"}
    assert win.viewers[0].image_page.view.wheel_map == win.wheel_map()

    def choose(self, dlg):
        dlg.boxes["plain"].setCurrentIndex(dlg.boxes["plain"].findData("zoom"))
        dlg.boxes["ctrl"].setCurrentIndex(dlg.boxes["ctrl"].findData("step"))
        return True
    monkeypatch.setattr(type(win), "_run_wheel_dialog", choose)
    win.open_wheel_settings()
    assert win.wheel_map() == {"plain": "zoom", "ctrl": "step", "shift": "scroll"}
    assert win.viewers[0].image_page.view.wheel_map["plain"] == "zoom"
    dlg = WheelDialog(win, win.wheel_map())
    dlg.defaults.click()
    assert dlg.values() == {"plain": "scroll_step", "ctrl": "zoom", "shift": "scroll"}


def test_the_default_wheel_scrolls_a_zoomed_picture_and_steps_at_its_end(viewer, tmp_path, monkeypatch):
    from dossier.gui import image_view
    monkeypatch.setattr(image_view, "SETTLE", 0.0)
    paths = [picture(tmp_path / f"s{n}.png", 800, 600) for n in range(2)]
    win = viewer(paths)
    wait(lambda: win.image_page.view.has_image())
    view = win.image_page.view
    wheel(view, -120)                                    # the picture fits the window: the first notch steps at once
    wait(lambda: win.index == 1 and view.has_image())
    wheel(view, 120)
    wait(lambda: win.index == 0 and view.has_image())
    view.actual_size()
    view.zoom_by(4)
    bar = view.verticalScrollBar()
    assert bar.maximum() > bar.minimum()
    bar.setValue(bar.minimum())
    wheel(view, -120)                                    # zoomed: it scrolls down, and stays on this picture
    assert bar.value() > bar.minimum() and win.index == 0
    bar.setValue(bar.maximum())
    wheel(view, -120)                                    # at the bottom: the next picture
    wait(lambda: win.index == 1 and view.has_image())
    view.actual_size()
    view.zoom_by(4)
    bar.setValue(bar.minimum())
    wheel(view, 120)                                     # at the top, wheel up: the previous picture
    wait(lambda: win.index == 0 and view.has_image())


def test_a_spin_that_is_still_scrolling_does_not_jump_to_the_next_picture(viewer, tmp_path):
    paths = [picture(tmp_path / f"t{n}.png", 800, 600) for n in range(2)]
    win = viewer(paths)
    wait(lambda: win.image_page.view.has_image())
    view = win.image_page.view
    view.actual_size()
    view.zoom_by(4)
    bar = view.verticalScrollBar()
    bar.setValue(bar.maximum() - 50)
    wheel(view, -120)                                    # reaches the bottom, still scrolling
    wheel(view, -120)                                    # the same spin goes on: not a step yet
    assert win.index == 0


def test_a_picture_has_the_floating_bar_and_other_files_do_not(viewer, tmp_path):
    a, b = picture(tmp_path / "a.png", 400, 300), picture(tmp_path / "b.png", 40, 20)
    (tmp_path / "n.txt").write_text("text\n")
    win = viewer([a, b, str(tmp_path / "n.txt")])
    bar = win.floating
    assert bar.enabled and bar.is_visible() and bar.bar.parent() is win.image_page.view.viewport()
    assert bar.buttons["next"].isVisibleTo(bar.bar) and set(bar.buttons) >= {"prev", "next", "out", "in", "fit", "actual", "left", "right", "close"}
    wait(lambda: win.image_page.view.has_image())
    bar.buttons["next"].click()
    assert win.index == 1
    win.step(1)
    assert win.mode != "image" and not bar.enabled and bar.bar.isHidden()              # text: no bar
    win.step(-1)
    assert bar.enabled and not bar.bar.isHidden()


def test_the_toolbar_no_longer_carries_the_buttons_the_floating_bar_has(viewer, tmp_path):
    win = viewer([picture(tmp_path / "a.png")])
    texts = {b.text() for b in win.findChildren(type(win.prev_file))}
    assert not texts & {"Fit", "100%", "Turn left", "Turn right"}
    only = viewer([picture(tmp_path / "solo.png")])
    assert not only.floating.buttons["prev"].isVisibleTo(only.floating.bar)               # a single picture: nothing to step to
