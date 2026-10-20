"""Where a picture of a file comes from: images, comic pages, epub covers, audio cover art, folder covers, video frames."""
import os
import subprocess
import sys
import zipfile

import pytest

from dossier.core import covers

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-data"


def test_each_kind_of_item_says_what_gives_it_a_picture():
    assert covers.kind_of("a.JPG", False) == "image" and covers.kind_of("b.cbz", False) == "comic"
    assert covers.kind_of("c.epub", False) == "epub" and covers.kind_of("d.mp3", False) == "audio"
    assert covers.kind_of("e.mkv", False) == "video" and covers.kind_of("anything", True) == "folder"
    assert covers.kind_of("notes.txt", False) == "" and covers.kind_of("noext", False) == ""


def test_a_comic_gives_its_first_page_by_natural_order_and_skips_junk(tmp_path):
    p = tmp_path / "c.cbz"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ComicInfo.xml", "<ComicInfo/>")
        z.writestr("__MACOSX/._1.jpg", b"junk")
        z.writestr("page10.jpg", b"TEN")
        z.writestr("page2.jpg", b"TWO")
        z.writestr("page1.jpg", b"ONE")
    assert covers.comic_page(str(p)) == b"ONE"
    empty = tmp_path / "e.cbz"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("readme.txt", "x")
    assert covers.comic_page(str(empty)) is None
    bad = tmp_path / "b.cbz"
    bad.write_bytes(b"not a zip")
    assert covers.comic_page(str(bad)) is None and covers.comic_page(str(tmp_path / "missing.cbz")) is None


def make_epub(path, cover_how):
    container = ('<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                 '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
    items = {"meta": ('<meta name="cover" content="cov"/>', '<item id="cov" href="images/c.png" media-type="image/png"/>'),
             "property": ("", '<item id="x" href="images/c.png" media-type="image/png" properties="cover-image"/>'),
             "id": ("", '<item id="cover-img" href="images/c.png" media-type="image/png"/>'),
             "none": ("", '<item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>')}[cover_how]
    opf = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'{items[0]}</metadata><manifest>{items[1]}</manifest></package>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/images/c.png", PNG)


@pytest.mark.parametrize("how", ["meta", "property", "id"])
def test_an_epub_cover_is_found_the_three_usual_ways(tmp_path, how):
    p = tmp_path / "b.epub"
    make_epub(p, how)
    assert covers.epub_cover(str(p)) == PNG


def test_an_epub_without_a_cover_or_a_damaged_one_gives_nothing(tmp_path):
    p = tmp_path / "n.epub"
    make_epub(p, "none")
    assert covers.epub_cover(str(p)) is None
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"x")
    assert covers.epub_cover(str(bad)) is None


def test_a_folder_cover_is_the_first_wanted_name_in_the_order_of_preference(tmp_path):
    (tmp_path / "x.jpg").write_bytes(b"1")
    assert covers.folder_cover(str(tmp_path)) is None
    (tmp_path / "Folder.JPG").write_bytes(b"1")
    (tmp_path / "cover.png").write_bytes(b"1")
    assert os.path.basename(covers.folder_cover(str(tmp_path))) == "cover.png"
    assert covers.folder_cover(str(tmp_path / "missing")) is None


def test_picture_for_tells_files_from_bytes_and_unknowns_from_both(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(PNG)
    assert covers.picture_for("image", str(img)) == ("file", str(img))
    z = tmp_path / "c.cbz"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("1.jpg", b"ONE")
    assert covers.picture_for("comic", str(z)) == ("bytes", b"ONE")
    assert covers.picture_for("", str(img)) is None and covers.picture_for("video", str(img), ffmpeg="") is None


def test_a_video_frame_comes_from_ffmpeg_only_when_it_is_given_and_never_raises(tmp_path):
    assert covers.video_frame(str(tmp_path / "v.mkv"), "", 128) is None
    assert covers.video_frame(str(tmp_path / "v.mkv"), str(tmp_path / "no-such-ffmpeg.exe"), 128) is None


def test_audio_cover_art_is_read_in_a_clean_interpreter(tmp_path):
    """mutagen runs in its own Python here: with it inside the pytest process that also holds Qt, the interpreter has crashed at exit."""
    pytest.importorskip("mutagen")
    script = (
        "import sys\n"
        "from dossier.core import covers\n"
        "from mutagen.id3 import ID3, APIC\n"
        "p = sys.argv[1]\n"
        "open(p, 'wb').write((bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(413)) * 40)\n"
        "t = ID3(); t.add(APIC(encoding=3, mime='image/png', type=3, desc='', data=b'COVERBYTES')); t.save(p)\n"
        "assert covers.audio_cover(p) == b'COVERBYTES', covers.audio_cover(p)\n"
        "open(p, 'wb').write(b'not audio at all' * 30)\n"
        "assert covers.audio_cover(p) is None\n"
        "assert covers.audio_cover(p + '.missing') is None\n"
        "print('ok')\n")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    done = subprocess.run([sys.executable, "-c", script, str(tmp_path / "a.mp3")], capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, PYTHONPATH=root))
    assert done.returncode == 0 and "ok" in done.stdout, done.stdout + done.stderr
