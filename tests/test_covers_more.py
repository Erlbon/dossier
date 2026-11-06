"""More covers for the thumbnail view (decided 2026-11-06: covers only, no comic reader): comics in RAR, 7z and tar (.cbr, .cb7, .cbt)
as well as zip, the cover page ComicInfo names, the cover attached to an MKV or stored in an MP4 (before, and without, a frame through
ffmpeg), and the first page of a PDF."""
import io
import os
import shutil
import subprocess
import tarfile
import zipfile

import pytest

from dossier.core import archives, covers

FFMPEG = shutil.which("ffmpeg")
PAGES = {"001.jpg": b"page one", "002.jpg": b"page two", "003.jpg": b"page three"}


def comic_info(front: int) -> bytes:
    return (f'<?xml version="1.0"?><ComicInfo><Series>S</Series><Pages><Page Image="0"/><Page Image="{front}" Type="FrontCover"/>'
            f'</Pages></ComicInfo>').encode()


def make_cbz(path, info=None):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in PAGES.items():
            z.writestr(name, data)
        if info is not None:
            z.writestr("ComicInfo.xml", info)
    return str(path)


def test_the_cover_page_comicinfo_names_is_the_thumbnail(tmp_path):
    assert covers.comic_page(make_cbz(tmp_path / "a.cbz", comic_info(1))) == b"page two"
    assert covers.comic_page(make_cbz(tmp_path / "b.cbz")) == b"page one"                 # no ComicInfo: the first page by name
    assert covers.comic_page(make_cbz(tmp_path / "c.cbz", comic_info(9))) == b"page one"   # a page that is not there: the first


def test_comics_in_7z_tar_and_a_zip_named_cbr_give_their_cover(tmp_path):
    import py7zr
    with py7zr.SevenZipFile(tmp_path / "a.cb7", "w") as z:
        for name, data in PAGES.items():
            z.writestr(data, name)
        z.writestr(comic_info(2), "ComicInfo.xml")
    assert covers.comic_page(str(tmp_path / "a.cb7")) == b"page three"
    with tarfile.open(tmp_path / "a.cbt", "w") as t:
        for name, data in PAGES.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    assert covers.comic_page(str(tmp_path / "a.cbt")) == b"page one"
    assert covers.comic_page(make_cbz(tmp_path / "zip-inside.cbr")) == b"page one"         # a .cbr is often a zip
    for name in ("x.cbz", "x.cbr", "x.cb7", "x.cbt"):
        assert covers.kind_of(name, False) == "comic"
    assert covers.kind_of("x.pdf", False) == "pdf"


@pytest.mark.skipif(archives.find_seven_zip() is None, reason="no 7-Zip or NanaZip here")
def test_a_rar_comic_is_read_through_7_zip(tmp_path):
    exe = archives.find_seven_zip()
    folder = tmp_path / "pages"
    folder.mkdir()
    for name, data in PAGES.items():
        (folder / name).write_bytes(data)
    target = tmp_path / "a.cbr"
    done = subprocess.run([exe, "a", "-t7z", str(tmp_path / "a.7z"), str(folder / "*")], capture_output=True)
    assert done.returncode == 0
    os.replace(tmp_path / "a.7z", target)                                                  # 7-Zip writes no RAR: 7z inside a .cbr
    assert covers.comic_page(str(target)) == b"page one"


# MKV attachments, built by hand and by ffmpeg -------------------------------------------------------------------------------------------
def el(element_id: bytes, payload: bytes) -> bytes:
    return element_id + b"\x01" + len(payload).to_bytes(7, "big") + payload


def attached(name: str, mime: str, data: bytes) -> bytes:
    return el(b"\x61\xA7", el(b"\x46\x6E", name.encode()) + el(b"\x46\x60", mime.encode()) + el(b"\x46\x5C", data))


def make_mkv(path, *files):
    header = el(b"\x1A\x45\xDF\xA3", el(b"\x42\x82", b"matroska"))
    segment = el(b"\x18\x53\x80\x67", el(b"\x15\x49\xA9\x66", b"") + el(b"\x1F\x43\xB6\x75", b"\0" * 5000)
                 + el(b"\x19\x41\xA4\x69", b"".join(files)))
    path.write_bytes(header + segment)
    return str(path)


def test_the_cover_attached_to_an_mkv_is_found_past_the_video(tmp_path):
    path = make_mkv(tmp_path / "a.mkv", attached("font.ttf", "font/ttf", b"font"), attached("cover_land.jpg", "image/jpeg", b"wide"),
                    attached("cover.jpg", "image/jpeg", b"the cover"))
    assert covers.mkv_cover(path) == b"the cover"
    other = make_mkv(tmp_path / "b.mkv", attached("poster.png", "image/png", b"some picture"))
    assert covers.mkv_cover(other) == b"some picture"                                         # no cover.*: the first picture
    assert covers.mkv_cover(make_mkv(tmp_path / "c.mkv", attached("font.ttf", "font/ttf", b"f"))) is None
    (tmp_path / "d.mkv").write_bytes(b"not a matroska file at all")
    assert covers.mkv_cover(str(tmp_path / "d.mkv")) is None


@pytest.mark.skipif(FFMPEG is None, reason="no ffmpeg here")
def test_real_mkv_and_mp4_files_give_their_cover_without_ffmpeg_switched_on(tmp_path):
    cover = tmp_path / "cover.png"
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=32x24", "-frames:v", "1", str(cover)], check=True)
    mkv, mp4 = tmp_path / "film.mkv", tmp_path / "film.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x48:d=1", "-c:v", "mjpeg", "-attach", str(cover),
                    "-metadata:s:t:0", "mimetype=image/png", "-metadata:s:t:0", "filename=cover.png", str(mkv)], check=True)
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x48:d=1", "-i", str(cover), "-map", "0", "-map", "1",
                    "-c:v:0", "mpeg4", "-c:v:1", "copy", "-disposition:v:1", "attached_pic", str(mp4)], check=True)
    data = cover.read_bytes()
    assert covers.picture_for("video", str(mkv)) == ("bytes", data)
    assert covers.picture_for("video", str(mp4)) == ("bytes", data)


# PDF -------------------------------------------------------------------------------------------------------------------------------------
def test_a_pdf_shows_its_first_page(tmp_path):
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QColor, QPainter, QPdfWriter
    from PyQt6.QtWidgets import QApplication
    from dossier.gui import thumbnails
    app = QApplication.instance() or QApplication([])
    path = str(tmp_path / "doc.pdf")
    writer = QPdfWriter(path)
    painter = QPainter(writer)
    painter.fillRect(QRectF(0, 0, writer.width(), writer.height()), QColor("#cc2222"))
    painter.end()
    image = thumbnails.make("pdf", path, 128)
    assert image is not None and max(image.width(), image.height()) == 128
    centre = image.pixelColor(image.width() // 2, image.height() // 2)
    assert centre.red() > 150 and centre.green() < 100 and app is not None
    (tmp_path / "bad.pdf").write_bytes(b"%PDF-1.4 broken")
    assert thumbnails.make("pdf", str(tmp_path / "bad.pdf"), 128) is None
