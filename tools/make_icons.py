"""Make dossier.ico and dossier-256.png from dossier/gui/appicon/dossier.svg.

    python tools/make_icons.py

An .ico is a small directory followed by one image per size; each image here is a PNG (the form Windows
Vista and later read), so the file needs nothing but Qt, which the program already uses.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QBuffer, QIODevice  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

from dossier.gui import appicon  # noqa: E402


def png_bytes(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    appicon.render(size).save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: str, sizes) -> None:
    images = [(s, png_bytes(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    directory, data = b"", b""
    for size, png in images:
        side = 0 if size >= 256 else size                       # 0 means 256 in the directory
        directory += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    with open(path, "wb") as f:
        f.write(header + directory + data)


# The Mac's icon types that hold a PNG, with the pixel size of each (the "@2x" ones are the Retina forms of the smaller size).
ICNS_TYPES = (("icp4", 16), ("ic11", 32), ("icp5", 32), ("ic12", 64), ("ic07", 128), ("ic13", 256), ("ic08", 256),
              ("ic14", 512), ("ic09", 512), ("ic10", 1024))


def write_icns(path: str) -> None:
    """The Mac app's icon (``Dossier.app``): an ``icns`` file is a header and one PNG per size, each with a four-letter type
    and its length. Made at build time on the Mac runner; not committed (nothing on Windows reads it)."""
    pngs = {}
    body = b""
    for kind, size in ICNS_TYPES:
        png = pngs.setdefault(size, png_bytes(size))
        body += kind.encode("ascii") + struct.pack(">I", 8 + len(png)) + png
    with open(path, "wb") as f:
        f.write(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    if sys.argv[1:2] == ["--icns"]:                             # python tools/make_icons.py --icns build/dossier.icns
        write_icns(sys.argv[2])
        print("wrote", sys.argv[2])
        return
    write_ico(appicon.ICO, appicon.SIZES)
    with open(appicon.PNG, "wb") as f:
        f.write(png_bytes(256))
    print("wrote", appicon.ICO, "and", appicon.PNG)
    del app


if __name__ == "__main__":
    main()
