"""The metadata columns of a folder listing: what each one shows, and how a file's tags become the values of those columns.

A file is read once (the readers of ``redactor_common``: audio tags through mutagen, ComicInfo of a CBZ, tracks of a video through
ffprobe) and every column value is taken from that one result. The readers never raise; a file that cannot be read has empty cells.
Reading opens each file, so it runs on a thread, only for the kinds of file the visible columns need, and the answers are cached by
path, size and time. Qt-free.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Callable, Optional

from .columns import META_KEYS
from .properties import kind_of, read_metadata

# which kinds of file can fill a column
KINDS_OF = {"m_title": ("audio", "comic", "video"), "m_artist": ("audio",), "m_album": ("audio",), "m_track": ("audio",),
            "m_year": ("audio", "comic", "video"), "m_genre": ("audio", "comic"), "m_length": ("audio", "video"),
            "m_bitrate": ("audio", "video"), "m_series": ("comic",), "m_number": ("comic",), "m_writer": ("comic",),
            "m_publisher": ("audio", "comic"), "m_pages": ("comic",), "m_resolution": ("video",), "m_codec": ("video",),
            "m_languages": ("video",)}
CACHE_FILES = 4000
TIMES = " " + chr(0xD7) + " "          # the reader writes a picture size as "1920 × 1080"


def kinds_needed(visible_keys) -> set:
    """The kinds of file that have to be opened for the metadata columns that are on."""
    out: set = set()
    for key in visible_keys:
        out.update(KINDS_OF.get(key, ()))
    return out


def _year(text: str) -> str:
    text = (text or "").strip()
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ""


def _first_number(text: str) -> str:
    """``3/12`` is track 3."""
    head = (text or "").split("/")[0].strip()
    return head.lstrip("0") or ("0" if head else "")


def _kbps(text: str) -> str:
    return text.replace(" kbps", "") if text else ""


def _languages(result) -> str:
    langs = [f.value for f in result.fields if f.key.startswith("audio.") and f.key.endswith(".language")]
    return ", ".join(dict.fromkeys(langs))


def values_from(kind: str, result) -> dict:
    """The column values (``{m_key: text}``) that a ``MetaResult`` of ``kind`` gives; only the columns it can fill."""
    g = result.get
    out = {"m_title": g("title"), "m_year": _year(g("date")), "m_genre": g("genre")}
    if kind == "audio":
        out.update(m_artist=g("artist"), m_album=g("album"), m_track=_first_number(g("track") or g("tracknumber")),
                   m_length=g("length"), m_bitrate=_kbps(g("bitrate")), m_publisher=g("publisher"))
    elif kind == "comic":
        out.update(m_series=g("series"), m_number=g("number"), m_writer=g("writer"), m_publisher=g("publisher"),
                   m_pages=g("pagecount") or g("pages"))
    elif kind == "video":
        out.update(m_length=g("length"), m_bitrate=_kbps(g("bitrate")), m_resolution=g("video.1.size").replace(TIMES, "x"),
                   m_codec=g("video.1.codec"), m_languages=_languages(result))
    return {k: v for k, v in out.items() if v and k in META_KEYS}


def read_values(path: str, kinds: set) -> dict:
    """The metadata column values of the file at ``path`` ({} when it is not a kind in ``kinds``, or cannot be read)."""
    kind = kind_of(path)
    if not kind or kind not in kinds:
        return {}
    try:
        result = read_metadata(path, kind)
    except Exception:   # noqa: BLE001 -- the readers do not raise, but a column must never take the list down
        return {}
    if result is None or (result.error and not result.fields):
        return {}
    return values_from(kind, result)


class MetaCache:
    """Values by (path, size, time), so a file is read once until it changes. The oldest entries go first."""

    def __init__(self, limit: int = CACHE_FILES) -> None:
        self.limit = limit
        self._items: OrderedDict = OrderedDict()

    @staticmethod
    def key(path: str, size: int, mtime: float) -> tuple:
        return (path, int(size), int(mtime))

    def get(self, key: tuple) -> Optional[dict]:
        if key in self._items:
            self._items.move_to_end(key)
            return self._items[key]
        return None

    def put(self, key: tuple, values: dict) -> None:
        self._items[key] = values
        self._items.move_to_end(key)
        while len(self._items) > self.limit:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


SHARED_CACHE = MetaCache()


def read_many(entries: list, kinds: set, cache: MetaCache, on_batch: Callable[[dict], None], *,
              reader: Callable[[str, set], dict] = read_values, cancelled: Callable[[], bool] = lambda: False,
              workers: int = 4, batch: int = 40) -> None:
    """Read the files of ``entries`` (objects with ``path``, ``size``, ``mtime``) a few at a time and hand the answers over in batches
    (``on_batch({path: values})``), so the list fills in while the rest is still being read. Stops when ``cancelled()`` says so."""
    from concurrent.futures import ThreadPoolExecutor
    todo = []
    found: dict = {}
    for e in entries:
        if kind_of(e.path) not in kinds:
            continue
        key = MetaCache.key(e.path, e.size, e.mtime)
        got = cache.get(key)
        if got is not None:
            found[e.path] = got
        else:
            todo.append((e.path, key))
    if found:
        on_batch(found)
    if not todo:
        return
    pending: dict = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dossier-meta") as pool:
        futures = [(path, key, pool.submit(reader, path, kinds)) for path, key in todo]
        for path, key, future in futures:
            if cancelled():
                for _p, _k, f in futures:
                    f.cancel()
                return
            values = future.result()
            cache.put(key, values)
            pending[path] = values
            if len(pending) >= batch:
                on_batch(pending)
                pending = {}
    if pending and not cancelled():
        on_batch(pending)
