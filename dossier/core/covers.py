"""Where a picture of a file or folder comes from, for the thumbnail view.

Qt-free: every function returns the *bytes of an image* (or a path of one) and the window turns them into a thumbnail. An image file is
its own picture; a comic archive gives its first page; an epub its cover; an audio file the cover art inside it; a folder a picture
lying in it (cover.jpg, folder.jpg...); a video a frame (through ffmpeg, which is only used when the owner switched that on). Every
function stays inside limits (a size to read, a time to wait) and returns ``None`` instead of raising for a file it cannot read.
"""
from __future__ import annotations

import os
import posixpath
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".jpe", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico", ".avif", ".svg")
ARCHIVE_PAGES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif")
AUDIO_EXTENSIONS = (".mp3", ".flac", ".m4a", ".m4b", ".mp4a", ".ogg", ".oga", ".opus", ".wma", ".wv", ".ape")
VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".mpg", ".mpeg", ".ts", ".m2ts", ".flv", ".3gp")
FOLDER_COVERS = ("cover", "folder", "front", "poster", "album", "albumart", "thumb", "thumbnail")
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_PAGE_BYTES = 30 * 1024 * 1024
VIDEO_TIMEOUT = 12

_NUMBER = re.compile(r"(\d+)")


def natural(name: str) -> list:
    return [int(p) if p.isdigit() else p.lower() for p in _NUMBER.split(name)]


def kind_of(name: str, is_dir: bool) -> str:
    """What gives this item its picture: ``image``, ``comic``, ``epub``, ``audio``, ``video``, ``folder`` or an empty string."""
    if is_dir:
        return "folder"
    low = name.lower()
    if low.endswith(IMAGE_EXTENSIONS):
        return "image"
    if low.endswith(".cbz"):
        return "comic"
    if low.endswith(".epub"):
        return "epub"
    if low.endswith(AUDIO_EXTENSIONS):
        return "audio"
    if low.endswith(VIDEO_EXTENSIONS):
        return "video"
    return ""


def comic_page(path: str) -> Optional[bytes]:
    """The first page of a comic archive (zip): the first image by natural name order."""
    try:
        with zipfile.ZipFile(path) as z:
            pages = sorted((i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(ARCHIVE_PAGES)
                            and not posixpath.basename(i.filename).startswith(".")), key=lambda i: natural(i.filename))
            for info in pages[:1]:
                if info.file_size <= MAX_PAGE_BYTES:
                    return z.read(info)
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
        pass
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
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            done = subprocess.run([ffmpeg, "-v", "error", "-ss", start, "-i", path, "-frames:v", "1", "-vf",
                                   f"scale={px}:{px}:force_original_aspect_ratio=decrease", "-f", "image2pipe", "-vcodec", "png", "-"],
                                  capture_output=True, timeout=VIDEO_TIMEOUT, stdin=subprocess.DEVNULL, creationflags=flags)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if done.returncode == 0 and done.stdout[:4] == b"\x89PNG":
            return done.stdout
    return None


def picture_for(kind: str, path: str, ffmpeg: str = "", px: int = 128):
    """What to draw for an item: ``("file", path)`` for an image file, ``("bytes", data)`` for a picture taken out of a file, or None."""
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
        data = video_frame(path, ffmpeg, px)
    else:
        return None
    return ("bytes", data) if data else None
