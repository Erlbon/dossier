"""Tags, ComicInfo.xml and zips are written only through redactor_common's shared writers (``core/audio_write``, ``core/comicinfo_write``,
``core/zip_rewrite``; merged on 2026-11-04 from Dossier's own and the Redactor apps', which wrote the same file in fifteen different ways).
A second writer here would drift from them again: this test names the line that writes on its own."""
import os

from redactor_common.core.writer_guard import find_private_writers


def test_nothing_in_dossier_writes_outside_the_shared_writers():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert find_private_writers(os.path.join(root, "dossier")) == []
    assert find_private_writers(os.path.join(root, "tools")) == []
