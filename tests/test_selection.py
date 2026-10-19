from dossier.core.selection import SelectionStore


def test_toggle_and_count():
    s = SelectionStore()
    assert s.toggle("/a/x") is True
    assert s.toggle("/b/y") is True
    assert len(s) == 2
    assert s.toggle("/a/x") is False
    assert s.paths() == ["/b/y"]


def test_survives_navigation_across_folders():
    # A selection holds paths from several folders at once (S3, S5).
    s = SelectionStore()
    s.add(["/books/a.epub", "/books/b.epub"])
    s.add(["/scans/1.jpg"])
    assert len(s) == 3
    assert "/scans/1.jpg" in s


def test_observers_fire_once_per_real_change():
    s = SelectionStore()
    calls = []
    unsub = s.subscribe(lambda store: calls.append(len(store)))
    s.add(["/a"])
    s.add(["/a"])          # no change, no call
    s.remove(["/zzz"])     # no change, no call
    s.clear()
    assert calls == [1, 0]
    unsub()
    s.add(["/b"])
    assert calls == [1, 0]


def test_invert_within_one_folder_keeps_other_folders():
    s = SelectionStore()
    s.add(["/a/1", "/other/9"])
    s.invert(["/a/1", "/a/2", "/a/3"])
    assert sorted(s.paths()) == ["/a/2", "/a/3", "/other/9"]


def test_named_selections():
    s = SelectionStore()
    s.add(["/a", "/b"])
    s.save("first")
    s.clear()
    s.add(["/c"])
    s.recall("first", combine=True)
    assert sorted(s.paths()) == ["/a", "/b", "/c"]
    s.recall("first")
    assert sorted(s.paths()) == ["/a", "/b"]
    assert s.saved_names() == ["first"]
