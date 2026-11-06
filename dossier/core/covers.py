"""Where a picture of a file or folder comes from, for the thumbnail view.

Qt-free: every function returns the *bytes of an image* (or a path of one) and the window turns them into a thumbnail. An image file is
its own picture; a comic archive (zip, RAR, 7z or tar) the cover page its ComicInfo names, else its first page; an epub its cover; an
audio file the cover art inside it; a folder a picture lying in it (cover.jpg, folder.jpg...); a video the cover attached to it (MKV) or
stored in it (MP4), else a frame (through ffmpeg, which is only used when the owner switched that on); a PDF its first page, which the
window draws (``("pdf", path)``: Qt's PDF module, not here). Every
function stays inside limits (a size to read, a time to wait) and returns ``None`` instead of raising for a file it cannot read.
"""
from __future__ import annotations

import os
import posixpath
import subprocess
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional

from .platform import no_window_flags
from .vfs import natural_key

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".jpe", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico", ".avif", ".svg")
ARCHIVE_PAGES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif")
AUDIO_EXTENSIONS = (".mp3", ".flac", ".m4a", ".m4b", ".mp4a", ".ogg", ".oga", ".opus", ".wma", ".wv", ".ape")
VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".mpg", ".mpeg", ".ts", ".m2ts", ".flv", ".3gp")
FOLDER_COVERS = ("cover", "folder", "front", "poster", "album", "albumart", "thumb", "thumbnail")
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_PAGE_BYTES = 30 * 1024 * 1024
VIDEO_TIMEOUT = 12

def kind_of(name: str, is_dir: bool) -> str:
    """What gives this item its picture: ``image``, ``comic``, ``pdf``, ``epub``, ``audio``, ``video``, ``folder`` or an empty string."""
    if is_dir:
        return "folder"
    low = name.lower()
    if low.endswith(IMAGE_EXTENSIONS):
        return "image"
    if low.endswith(COMIC_EXTENSIONS):
        return "comic"
    if low.endswith(".pdf"):
        return "pdf"
    if low.endswith(".epub"):
        return "epub"
    if low.endswith(AUDIO_EXTENSIONS):
        return "audio"
    if low.endswith(VIDEO_EXTENSIONS):
        return "video"
    return ""


COMIC_EXTENSIONS = (".cbz", ".cbr", ".cb7", ".cbt")
MKV_EXTENSIONS = (".mkv", ".mk3d", ".webm")
MP4_EXTENSIONS = (".mp4", ".m4v", ".mov")
MAX_INFO_BYTES = 1024 * 1024
MKV_COVERS = ("cover", "cover_land", "small_cover", "small_cover_land")   # the Matroska names, best first


def _comic_cover_index(info: bytes) -> Optional[int]:
    """The page ComicInfo.xml marks as the front cover (``<Page Image="n" Type="FrontCover"/>``, counted from 0), or None."""
    try:
        root = ET.fromstring(info)
    except ET.ParseError:
        return None
    for page in root.iter():
        if page.tag.endswith("Page") and (page.get("Type") or "").lower() == "frontcover":
            try:
                return int(page.get("Image", ""))
            except ValueError:
                return None
    return None


def _pick_page(names: list, info: Optional[bytes]) -> Optional[str]:
    """Of an archive's member names: the cover ComicInfo names, else the first picture by natural name order."""
    pages = sorted((n for n in names if n.lower().endswith(ARCHIVE_PAGES) and not posixpath.basename(n).startswith(".")),
                   key=natural_key)
    if not pages:
        return None
    index = _comic_cover_index(info) if info else None
    return pages[index] if index is not None and 0 <= index < len(pages) else pages[0]


def _is_comic_info(name: str) -> bool:
    return posixpath.basename(name).lower() == "comicinfo.xml"


def comic_page(path: str) -> Optional[bytes]:
    """The cover of a comic archive, zip, RAR, 7z or tar (.cbz, .cbr, .cb7, .cbt; a .cbr is often a zip, and its content decides):
    the page ComicInfo.xml marks as the front cover, else the first picture by natural name order. RAR needs 7-Zip or NanaZip."""
    try:
        if tarfile.is_tarfile(path) and not zipfile.is_zipfile(path):
            return _tar_page(path)
        from . import archives
        backend = archives.backend_for(path)
        if backend is None:
            return None
        members = {m.name: m for m in backend.members(path) if not m.is_dir and not m.encrypted}
        info_member = next((m for n, m in members.items() if _is_comic_info(n) and m.size <= MAX_INFO_BYTES), None)
        info = _read_member(backend, path, info_member, MAX_INFO_BYTES) if info_member is not None else None
        chosen = _pick_page(list(members), info)
        if chosen is None or members[chosen].size > MAX_PAGE_BYTES:
            return None
        return _read_member(backend, path, members[chosen], MAX_PAGE_BYTES)
    except Exception:   # noqa: BLE001 -- an archive we cannot read has no cover
        return None


def _read_member(backend, archive: str, member, limit: int) -> Optional[bytes]:
    with backend.open(archive, member) as stream:
        data = stream.read(limit + 1)
    return data if len(data) <= limit else None


def _tar_page(path: str) -> Optional[bytes]:
    with tarfile.open(path) as t:
        files = {m.name: m for m in t.getmembers() if m.isfile()}
        info_member = next((m for n, m in files.items() if _is_comic_info(n) and m.size <= MAX_INFO_BYTES), None)
        info = t.extractfile(info_member).read() if info_member is not None else None
        chosen = _pick_page(list(files), info)
        if chosen is None or files[chosen].size > MAX_PAGE_BYTES:
            return None
        return t.extractfile(files[chosen]).read()


# MKV attachments ---------------------------------------------------------------------------------------------------------------------
EBML, SEGMENT, SEEK_HEAD, SEEK, SEEK_ID, SEEK_POSITION = 0x1A45DFA3, 0x18538067, 0x114D9B74, 0x4DBB, 0x53AB, 0x53AC
ATTACHMENTS, ATTACHED_FILE, FILE_NAME, FILE_MIME, FILE_DATA = 0x1941A469, 0x61A7, 0x466E, 0x4660, 0x465C
_UNKNOWN = -1


def _vint(f, keep_marker: bool) -> Optional[int]:
    """An EBML number: an element ID (``keep_marker``, the length bits stay) or a size (``_UNKNOWN`` when all ones). None at the end."""
    first = f.read(1)
    if not first:
        return None
    b = first[0]
    length = next((i + 1 for i in range(8) if b & (0x80 >> i)), 0)
    if not length or (keep_marker and length > 4):
        raise ValueError("not an EBML number")
    rest = f.read(length - 1)
    if len(rest) != length - 1:
        return None
    value = b if keep_marker else b & (0xFF >> length)
    for byte in rest:
        value = (value << 8) | byte
    if not keep_marker and value == (1 << (7 * length)) - 1:
        return _UNKNOWN
    return value


def _element(f) -> Optional[tuple]:
    element_id = _vint(f, True)
    size = _vint(f, False) if element_id is not None else None
    return None if size is None else (element_id, size)


def _children(f, end: int):
    """``(id, size, start of the content)`` of each element up to ``end``; the caller reads or skips each one."""
    while f.tell() < end:
        found = _element(f)
        if found is None:
            return
        start = f.tell()
        yield found[0], found[1], start
        if found[1] == _UNKNOWN:
            return                                 # a live stream's cluster: nothing after it can be found
        f.seek(start + found[1])


def mkv_cover(path: str) -> Optional[bytes]:
    """The cover attached to a Matroska file: cover.*, cover_land.*, small_cover.* (the Matroska names), else the first attached
    picture. Found through the SeekHead, or by stepping over the clusters; only the chosen picture is read."""
    try:
        with open(path, "rb") as f:
            head = _element(f)
            if head is None or head[0] != EBML:
                return None
            f.seek(head[1], 1)
            seg = _element(f)
            if seg is None or seg[0] != SEGMENT:
                return None
            seg_start = f.tell()
            seg_end = seg_start + seg[1] if seg[1] != _UNKNOWN else os.fstat(f.fileno()).st_size
            where = None
            for element_id, size, start in _children(f, seg_end):
                if element_id == ATTACHMENTS:
                    where = (start, size)
                    break
                if element_id == SEEK_HEAD:
                    position = _seek_to(f, start + size, ATTACHMENTS)
                    if position is not None:
                        f.seek(seg_start + position)
                        found = _element(f)
                        if found is not None and found[0] == ATTACHMENTS:
                            where = (f.tell(), found[1])
                            break
                        f.seek(start + size)
            if where is None:
                return None
            return _pick_attachment(f, where[0] + where[1])
    except (OSError, ValueError):
        return None


def _seek_to(f, end: int, wanted: int) -> Optional[int]:
    for element_id, size, start in _children(f, end):
        if element_id != SEEK:
            continue
        seek_id = position = None
        for child, csize, cstart in _children(f, start + size):
            data = f.read(csize)
            if child == SEEK_ID:
                seek_id = int.from_bytes(data, "big")
            elif child == SEEK_POSITION:
                position = int.from_bytes(data, "big")
        f.seek(start + size)
        if seek_id == wanted and position is not None:
            return position
    return None


def _pick_attachment(f, end: int) -> Optional[bytes]:
    pictures = []                                  # (name, offset of the data, size)
    for element_id, size, start in _children(f, end):
        if element_id != ATTACHED_FILE:
            continue
        name, mime, data_at = "", "", None
        for child, csize, cstart in _children(f, start + size):
            if child == FILE_NAME:
                name = f.read(csize).decode("utf-8", "replace")
            elif child == FILE_MIME:
                mime = f.read(csize).decode("ascii", "replace").lower()
            elif child == FILE_DATA:
                data_at = (cstart, csize)
        f.seek(start + size)
        if data_at is not None and (mime.startswith("image/") or name.lower().endswith(ARCHIVE_PAGES)):
            pictures.append((name, *data_at))
    if not pictures:
        return None
    by_stem = {os.path.splitext(n)[0].lower(): (at, size) for n, at, size in reversed(pictures)}
    at, size = next((by_stem[s] for s in MKV_COVERS if s in by_stem), pictures[0][1:])
    if size > MAX_IMAGE_BYTES:
        return None
    f.seek(at)
    return f.read(size)


def video_cover(path: str) -> Optional[bytes]:
    """The cover stored in a video file itself: an MKV attachment, or the cover of an MP4 (read as audio covers are)."""
    low = path.lower()
    if low.endswith(MKV_EXTENSIONS):
        return mkv_cover(path)
    if low.endswith(MP4_EXTENSIONS):
        return audio_cover(path)
    return None


def epub_cover(path: str) -> Optional[bytes]:
    """The cover image of an epub: the item named by ``<meta name="cover">``, or the item marked ``cover-image``, or one called cover."""
    try:
        with zipfile.ZipFile(path) as z:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            opf_path = next((e.get("full-path") for e in container.iter() if e.tag.endswith("rootfile") and e.get("full-path")), "")
            if not opf_path:
                return None
            opf = ET.fromstring(z.read(opf_path))
            items = [e for e in opf.iter() if e.tag.endswith("}item") or e.tag == "item"]
            cover_id = next((e.get("content") for e in opf.iter() if (e.tag.endswith("}meta") or e.tag == "meta")
                             and e.get("name") == "cover"), None)
            chosen = None
            for item in items:
                if "cover-image" in (item.get("properties") or "").split() or (cover_id and item.get("id") == cover_id):
                    chosen = item
                    break
            if chosen is None:
                chosen = next((i for i in items if "cover" in (i.get("id") or "").lower()
                               and (i.get("media-type") or "").startswith("image/")), None)
            if chosen is None or not chosen.get("href"):
                return None
            target = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), chosen.get("href").replace("%20", " ")))
            info = z.getinfo(target)
            return z.read(info) if info.file_size <= MAX_PAGE_BYTES else None
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError, ValueError, RuntimeError):
        return None


def audio_cover(path: str) -> Optional[bytes]:
    """The cover art inside an audio file (ID3 APIC, FLAC or Vorbis picture, MP4 covr). Needs mutagen; without it, nothing."""
    try:
        import mutagen
        audio = mutagen.File(path)
        if audio is None:
            return None
        tags = getattr(audio, "tags", None)
        pictures = list(getattr(audio, "pictures", []) or [])
        if pictures:
            return bytes(pictures[0].data)
        if tags is not None and hasattr(tags, "getall"):
            for frame in tags.getall("APIC"):
                return bytes(frame.data)
        if tags is not None and hasattr(tags, "get"):
            covr = tags.get("covr")
            if covr:
                return bytes(covr[0])
            blocks = tags.get("metadata_block_picture")                      # Ogg: a base64 FLAC picture block
            if blocks:
                import base64
                from mutagen.flac import Picture
                return bytes(Picture(base64.b64decode(blocks[0])).data)
    except Exception:   # noqa: BLE001 -- a file we cannot read has no cover
        pass
    return None


def folder_cover(directory: str) -> Optional[str]:
    """The path of a picture lying in the folder that is meant as its cover (cover.jpg, folder.png...), or None."""
    try:
        names = os.listdir(directory)
    except OSError:
        return None
    by_stem: dict = {}
    for name in names:
        stem, ext = os.path.splitext(name)
        if ext.lower() in ARCHIVE_PAGES + (".jpe", ".ico") and stem.lower() in FOLDER_COVERS:
            by_stem.setdefault(stem.lower(), name)
    for wanted in FOLDER_COVERS:
        if wanted in by_stem:
            return os.path.join(directory, by_stem[wanted])
    return None


def video_frame(path: str, ffmpeg: str, px: int) -> Optional[bytes]:
    """One frame of a video as PNG bytes, about a tenth of the way in (a few seconds, never the black first frame)."""
    if not ffmpeg:
        return None
    for start in ("00:00:08", "00:00:01", "0"):
        try:
            flags = no_window_flags()
            done = subprocess.run([ffmpeg, "-v", "error", "-ss", start, "-i", path, "-frames:v", "1", "-vf",
                                   f"scale={px}:{px}:force_original_aspect_ratio=decrease", "-f", "image2pipe", "-vcodec", "png", "-"],
                                  capture_output=True, timeout=VIDEO_TIMEOUT, stdin=subprocess.DEVNULL, creationflags=flags)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if done.returncode == 0 and done.stdout[:4] == b"\x89PNG":
            return done.stdout
    return None


def picture_for(kind: str, path: str, ffmpeg: str = "", px: int = 128):
    """What to draw for an item: ``("file", path)`` for an image file, ``("bytes", data)`` for a picture taken out of a file,
    ``("pdf", path)`` for a PDF's first page, or None."""
    if kind == "image":
        return ("file", path)
    if kind == "comic":
        data = comic_page(path)
    elif kind == "epub":
        data = epub_cover(path)
    elif kind == "audio":
        data = audio_cover(path)
    elif kind == "folder":
        cover = folder_cover(path)
        return ("file", cover) if cover else None
    elif kind == "video":
        data = video_cover(path) or video_frame(path, ffmpeg, px)     # the film's own cover first; a frame only with ffmpeg on
    elif kind == "pdf":
        return ("pdf", path)                                           # drawn by the window (Qt's PDF module), not here
    else:
        return None
    return ("bytes", data) if data else None
