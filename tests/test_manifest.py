"""Manifests (core/manifest.py): every file with its checksum, written as CSV, read back, and compared by path and checksum."""
import hashlib
import os

import pytest

from dossier.cli.helpers import make_fs
from dossier.core import manifest as mf
from dossier.core.progress import Cancelled, CancelToken

T0 = 1_700_000_000


def put(path, data=b"x", mtime=T0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))


def test_a_manifest_lists_every_file_with_its_checksum_and_reads_back_the_same(tmp_path):
    root = tmp_path / "Maritime"
    put(root / "a.txt", b"alpha")
    put(root / "Vrakkart" / "NO" / "1910.doc", b"wreck list")
    put(root / "Vrakkart" / "café, 1910.jpg", b"jpg")
    seen = []
    items = mf.build(make_fs(), str(root), progress=lambda p: seen.append((p.files, p.total_files)))
    assert sorted(i.rel for i in items) == sorted(["a.txt", "Vrakkart/café, 1910.jpg", "Vrakkart/NO/1910.doc"])
    a = next(i for i in items if i.rel == "a.txt")
    assert a.digest == hashlib.sha256(b"alpha").hexdigest() and a.size == 5 and a.mtime == T0
    assert seen[-1] == (3, 3)
    out = tmp_path / "m.csv"
    mf.write(items, str(out))
    back = mf.read(str(out))
    assert [(i.rel, i.size, i.digest, int(i.mtime)) for i in back] == [(i.rel, i.size, i.digest, int(i.mtime)) for i in items]


def test_a_hand_made_manifest_with_backslashes_and_errors_is_read(tmp_path):
    path = tmp_path / "old.csv"
    path.write_text('"RelPath","Length","LastWriteUtc","SHA256"\n"Vrakkart\\x.pdf","3","2025-12-27T13:21:02.0000000Z","ABCDEF"\n'
                    '"b.txt","1","2025-01-01T00:00:00Z","ERROR: Access is denied"\n', encoding="utf-8-sig")
    items = mf.read(str(path))
    assert items[0].rel == "Vrakkart/x.pdf" and items[0].digest == "abcdef" and items[0].size == 3
    assert items[1].error == "Access is denied" and not items[1].digest
    bad = tmp_path / "bad.csv"
    bad.write_text("name,size\nx,1\n", encoding="utf-8")
    with pytest.raises(mf.BadManifest, match="missing"):
        mf.read(str(bad))


def test_the_diff_tells_missing_from_renamed_and_trusts_only_the_checksum():
    a = [mf.Item("same.txt", 1, T0, "aa"), mf.Item("changed.txt", 2, T0, "bb"), mf.Item("old name.pdf", 3, T0, "cc"),
         mf.Item("gone.jpg", 4, T0, "dd"), mf.Item("dst.txt", 1, T0, "ee")]
    b = [mf.Item("same.txt", 1, T0 + 3600, "aa"), mf.Item("changed.txt", 2, T0, "zz"), mf.Item("new name.pdf", 3, T0, "cc"),
         mf.Item("new.bin", 9, T0, "ff"), mf.Item("DST.txt", 1, T0, "ee")]
    d = mf.diff(a, b, case_sensitive=False)
    status = {r.rel: r.status for r in d.rows}
    assert d.same == 2                                             # an hour apart, or the name's case, does not make a file different
    assert status == {"changed.txt": mf.DIFFERENT, "old name.pdf": mf.ELSEWHERE_A, "gone.jpg": mf.ONLY_A, "new name.pdf": mf.ELSEWHERE_B,
                      "new.bin": mf.ONLY_B}
    assert next(r for r in d.rows if r.rel == "old name.pdf").elsewhere == ["new name.pdf"]
    s = d.summary()
    assert s["only_a"] == 1 and s["bytes_only_a"] == 4 and s["only_b"] == 1 and s["files_a"] == 5
    assert "old name.pdf" in mf.diff_csv(d) and "new name.pdf" in mf.diff_csv(d)
    strict = mf.diff(a, b, case_sensitive=True)                         # dst.txt and DST.txt are two names there, holding one content
    assert strict.count(mf.ELSEWHERE_A) == 2 and strict.count(mf.ELSEWHERE_B) == 2


def test_building_a_manifest_can_be_cancelled(tmp_path):
    put(tmp_path / "a.txt")
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        mf.build(make_fs(), str(tmp_path), token)
