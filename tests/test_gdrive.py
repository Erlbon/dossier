"""Google Drive as folders: the tree made of ids, Google's own documents, writing, the sign-in (browser, code, tokens) and the saved connection."""
import threading
import urllib.parse
import urllib.request

import pytest

from dossier.core import gdriveclient, oauth, servers
from dossier.core.gdriveclient import GoogleDriveClient, app_for
from dossier.core.oauth import Tokens, TokenSource
from dossier.core.sftpfs import Session, SftpFileSystem
from dossier.core.vfs import NotWritable
from tests.fake_drive import DOC, FOLDER, FakeDrive

ROOT = "gdrive://gd-test"


def make(drive: FakeDrive, read_only: bool = False):
    drive.refresh_token = "refresh-1"
    tokens = TokenSource(app_for("client-id", "secret"), Tokens("refresh-1"), drive)
    client = GoogleDriveClient(tokens, drive)
    client.sleep = lambda _s: None
    client.connect()
    fs = SftpFileSystem("gdrive")
    fs.add_session(Session("gd-test", client, read_only=read_only, scheme="gdrive"))
    return fs, client


@pytest.fixture
def drive():
    d = FakeDrive()
    docs = d.folder("Documents")
    d.add("notes.txt", "root", b"hello drive")
    d.add("big.bin", docs, bytes(range(256)) * 40)
    return d


def names(fs, path=ROOT + "/"):
    return sorted(e.name for e in fs.list(path))


def test_the_top_shows_my_drive_and_the_two_shared_folders(drive):
    fs, _c = make(drive)
    assert names(fs) == ["Documents", "Shared drives", "Shared with me", "notes.txt"]
    assert names(fs, ROOT + "/Documents") == ["big.bin"]
    assert fs.stat(ROOT + "/notes.txt").size == 11 and fs.stat(ROOT + "/Documents").is_dir


def test_equal_names_get_a_number_google_documents_get_their_extension_and_unshowable_kinds_are_left_out(drive):
    drive.add("notes.txt", "root", b"second one")
    drive.add("Plan", "root", b"x", DOC)
    drive.add("A form", "root", b"x", "application/vnd.google-apps.form")
    target = drive.named("Documents")
    drive.add("Link to docs", "root", b"", "application/vnd.google-apps.shortcut", target=target)
    fs, _c = make(drive)
    shown = names(fs)
    assert "notes.txt" in shown and "notes (2).txt" in shown
    assert "Plan.docx" in shown and "A form" not in shown
    assert fs.stat(ROOT + "/Link to docs").is_dir and names(fs, ROOT + "/Link to docs") == ["big.bin"]


def test_a_file_is_read_in_ranges_and_a_google_document_as_its_export(drive):
    drive.add("Plan", "root", b"body", DOC)
    fs, _c = make(drive)
    with fs.open_read(ROOT + "/Documents/big.bin") as f:
        f.seek(300)
        assert f.read(5) == bytes(range(256))[44:49]
        f.seek(0)
        assert len(f.read()) == 256 * 40
    assert fs.stat(ROOT + "/Plan.docx").size == len(b"EXPORT:body")
    with fs.open_read(ROOT + "/Plan.docx") as f:
        assert f.read() == b"EXPORT:body"


def test_an_ended_access_token_is_renewed_from_the_refresh_token_and_the_call_repeated(drive):
    fs, _c = make(drive)
    before = drive.refreshes
    drive.expire()
    assert "notes.txt" in names(fs)
    assert drive.refreshes == before + 1


def test_a_busy_service_is_waited_for(drive):
    fs, _c = make(drive)
    drive.rate_limit_next = 2
    assert "notes.txt" in names(fs)


def test_new_and_overwritten_files_are_uploaded_when_closed(drive):
    fs, _c = make(drive)
    with fs.open_write(ROOT + "/Documents/new.txt") as f:
        f.write(b"abc")
        f.write(b"def")
    assert drive.files[drive.named("new.txt")]["data"] == b"abcdef"
    assert "new.txt" in names(fs, ROOT + "/Documents")
    with fs.open_write(ROOT + "/notes.txt") as f:
        f.write(b"changed")
    assert drive.files[drive.named("notes.txt")]["data"] == b"changed" and len([k for k in drive.files.values() if k["name"] == "notes.txt"]) == 1
    with pytest.raises(OSError):
        fs.open_write(ROOT + "/notes.txt", exclusive=True)


def test_folders_are_made_renamed_moved_and_deleted_into_the_bin(drive):
    fs, _c = make(drive)
    fs.mkdir(ROOT + "/Archive")
    assert "Archive" in names(fs)
    fs.rename(ROOT + "/notes.txt", ROOT + "/Archive/old notes.txt")
    assert names(fs, ROOT + "/Archive") == ["old notes.txt"] and "notes.txt" not in names(fs)
    fs.rename(ROOT + "/Archive/old notes.txt", ROOT + "/Archive/n.txt")
    assert names(fs, ROOT + "/Archive") == ["n.txt"]
    with pytest.raises(OSError):
        fs.remove(ROOT + "/Archive")                                          # not empty: the folder is kept
    assert not drive.files[drive.named("Archive")]["trashed"]
    fs.remove(ROOT + "/Archive/n.txt")
    assert [v["trashed"] for v in drive.files.values() if v["name"] == "n.txt"] == [True]      # into Drive's bin, not gone
    fs.remove(ROOT + "/Archive")
    assert "Archive" not in names(fs)


def test_a_read_only_connection_changes_nothing(drive):
    fs, _c = make(drive, read_only=True)
    before = list(drive.calls)
    with pytest.raises(NotWritable):
        fs.remove(ROOT + "/notes.txt")
    with pytest.raises(NotWritable):
        fs.open_write(ROOT + "/x.txt")
    assert [c for c in drive.calls[len(before):] if c[0] != "GET"] == []


def test_files_shared_with_me_and_shared_drives_are_folders(drive):
    other = drive.add("from a friend.txt", "elsewhere", b"hi")
    drive.shared.append(other)
    drive.drives["sd1"] = "Team"
    drive.add("team file.txt", "sd1", b"team")
    fs, _c = make(drive)
    assert names(fs, ROOT + "/Shared with me") == ["from a friend.txt"]
    assert names(fs, ROOT + "/Shared drives") == ["Team"]
    assert names(fs, ROOT + "/Shared drives/Team") == ["team file.txt"]
    with pytest.raises(PermissionError):
        fs.mkdir(ROOT + "/Shared with me/new")


# the sign-in -------------------------------------------------------------------------------------------------------------------------
def browser(drive, code="the-code", tamper=None):
    """A fake browser: when told to open the sign-in page it does what a person's browser does, going back to the program's address."""
    def open_it(url):
        query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
        assert query["code_challenge_method"] == "S256" and query["access_type"] == "offline" and query["scope"].endswith("/drive")
        back = query["redirect_uri"] + "/?" + urllib.parse.urlencode(
            {"code": code, "state": tamper or query["state"]} if code else {"error": "access_denied", "state": query["state"]})
        threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=5).read(), daemon=True).start()
    return open_it


def test_the_browser_sign_in_gives_a_refresh_token_that_opens_the_drive(drive):
    drive.client_secret = "secret"
    tokens = oauth.sign_in(app_for("client-id", "secret"), browser(drive), drive, seconds=10)
    assert tokens.refresh == "refresh-1" and tokens.access in drive.valid
    client = GoogleDriveClient(TokenSource(app_for("client-id", "secret"), tokens, drive), drive)
    client.connect()
    assert client.account == "erlend@example.com"


def test_a_refused_or_foreign_answer_is_not_trusted(drive):
    with pytest.raises(oauth.OAuthError):
        oauth.sign_in(app_for("client-id", "secret"), browser(drive, code=""), drive, seconds=10)           # the person said no
    with pytest.raises(oauth.OAuthError):
        oauth.sign_in(app_for("client-id", "secret"), browser(drive, tamper="not-our-state"), drive, seconds=10)


def test_the_sign_in_can_be_cancelled_and_times_out(drive):
    with pytest.raises(oauth.OAuthError) as e:
        oauth.sign_in(app_for("client-id", "secret"), lambda url: None, drive, cancelled=lambda: True, seconds=10)
    assert e.value.code == "cancelled"
    with pytest.raises(oauth.OAuthError) as e:
        oauth.sign_in(app_for("client-id", "secret"), lambda url: None, drive, seconds=0.3)
    assert e.value.code == "timeout"


def test_a_revoked_refresh_token_says_to_sign_in_again(drive):
    drive.refresh_token = "something-else"
    client = GoogleDriveClient(TokenSource(app_for("client-id", "secret"), Tokens("refresh-1"), drive), drive)
    with pytest.raises(oauth.OAuthError) as e:
        client.connect()
    assert e.value.code == "invalid_grant"


# the saved connection ----------------------------------------------------------------------------------------------------------------
def test_a_saved_google_drive_connection_keeps_the_client_id_but_no_secret():
    c = servers.Connection("My Google", "gd-abc12345", protocol="gdrive", client_id="123.apps.googleusercontent.com", read_only=False)
    assert c.problem() == "" and c.describe() == "Google Drive" and c.url("/") == "gdrive://gd-abc12345/"
    text = servers.to_json([c])
    assert "123.apps.googleusercontent.com" in text and "secret" not in text
    (back,) = servers.from_json(text)
    assert back.client_id == c.client_id and back.protocol == "gdrive"
    assert servers.Connection("x", "gd-1", protocol="gdrive").problem() != ""                                  # no client id


def test_every_list_of_server_schemes_agrees():
    from dossier.core.platform import SERVER_SCHEMES
    from dossier.core.sftpfs import SCHEMES
    assert tuple(s + "://" for s in SCHEMES) == SERVER_SCHEMES
    assert set(servers.NAMES) == set(SCHEMES) and {p for p, _t in servers.PROTOCOLS} == set(SCHEMES)
