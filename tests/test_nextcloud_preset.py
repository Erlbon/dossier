"""The Nextcloud preset of the remote sources: the address of the files is worked out, the login is an app password, and it is plain WebDAV."""
import pytest

from dossier.core import servers


# the pieces -----------------------------------------------------------------------------------------------------------------------------
def test_the_address_of_the_files_from_the_user_and_where_the_server_lives():
    assert servers.nextcloud_start("", "me") == "/remote.php/dav/files/me"
    assert servers.nextcloud_start("/nextcloud", "me") == "/nextcloud/remote.php/dav/files/me"
    assert servers.nextcloud_start("", "Erlend B") == "/remote.php/dav/files/Erlend%20B"
    assert servers.nextcloud_start("", "a/b") == "/remote.php/dav/files/a%2Fb"             # a slash in a name cannot climb out of the folder


@pytest.mark.parametrize("path, prefix", [
    ("", ""), ("/", ""), ("/nextcloud", "/nextcloud"), ("/nextcloud/", "/nextcloud"),
    ("/index.php/apps/files/", ""), ("/nextcloud/index.php/apps/files/?dir=/", "/nextcloud"),
    ("/remote.php/dav/files/me/", ""), ("/cloud/remote.php/dav/files/me", "/cloud"), ("/apps/files", ""), ("/s/abc123", "")])
def test_where_a_nextcloud_lives_from_any_address_of_it(path, prefix):
    assert servers.nextcloud_prefix(path) == prefix


def test_a_preset_connection_needs_a_user_and_describes_itself():
    c = servers.Connection("My cloud", "cloud.example.com", "", 443, "webdav", preset=servers.NEXTCLOUD)
    assert "user name" in c.problem()
    c.user = "me"
    c.start_dir = servers.nextcloud_start("", "me")
    assert c.problem() == "" and c.describe() == "Nextcloud  me@cloud.example.com  (read-only)"            # the long address of the files is not shown
    assert servers.Connection("w", "h", "u", 443, "webdav").problem() == ""                   # plain WebDAV does not need one


def test_the_preset_survives_saving_and_older_lists_load_without_it():
    c = servers.Connection("My cloud", "cloud.example.com", "me", 443, "webdav", start_dir="/remote.php/dav/files/me", preset=servers.NEXTCLOUD)
    back = servers.from_json(servers.to_json([c]))[0]
    assert back.preset == servers.NEXTCLOUD and back.protocol == "webdav" and back.start_dir == "/remote.php/dav/files/me"
    old = '[{"name": "n", "host": "h", "user": "u", "port": 443, "protocol": "webdav", "secure": true}]'
    assert servers.from_json(old)[0].preset == ""


# the dialog and the connection ------------------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")

from dossier.gui.servers import ConnectionDialog, PasswordDialog  # noqa: E402
from tests.test_servers_dav_gui import dav, save_dav  # noqa: E402,F401
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from tests.test_servers_gui import label_text, lab, wait  # noqa: E402,F401


def nextcloud_dialog(win):
    dlg = ConnectionDialog(win)
    dlg.protocol.setCurrentIndex(dlg.protocol.findData(servers.NEXTCLOUD))
    return dlg


def test_the_type_list_offers_nextcloud_and_the_dialog_explains_the_app_password(lab):
    win, *_ = lab
    dlg = nextcloud_dialog(win)
    assert any("Nextcloud" in dlg.protocol.itemText(i) for i in range(dlg.protocol.count()))
    assert "app password" in dlg.type_note.text() and "Security" in dlg.type_note.text()
    assert dlg.port.value() == 443 and dlg.secure.isChecked() and not dlg._form.isRowVisible(dlg._key_row)
    assert not dlg._form.isRowVisible(dlg.start_dir) and "app password" in dlg.remember.text()


def test_a_server_name_and_a_user_make_the_right_connection(lab):
    win, *_ = lab
    dlg = nextcloud_dialog(win)
    dlg.name.setText("Home cloud")
    dlg.host.setText("cloud.example.com")
    dlg.user.setText("me")
    c = dlg.connection()
    assert (c.protocol, c.preset, c.host, c.port, c.secure, c.user, c.start_dir) == (
        "webdav", servers.NEXTCLOUD, "cloud.example.com", 443, True, "me", "/remote.php/dav/files/me")
    assert c.read_only and c.problem() == ""                                      # still read-only until the owner says otherwise


def test_a_pasted_web_page_address_is_cut_down_to_the_server_and_its_folder(lab):
    win, *_ = lab
    dlg = nextcloud_dialog(win)
    dlg.host.setText("https://me@example.com:8443/nextcloud/index.php/apps/files/?dir=/Photos")
    dlg.host.editingFinished.emit()
    c = dlg.connection()
    assert dlg.protocol.currentData() == servers.NEXTCLOUD                       # the type stays Nextcloud
    assert (c.host, c.port, c.user, c.name, c.start_dir) == ("example.com", 8443, "me", "example.com", "/nextcloud/remote.php/dav/files/me")


def test_editing_a_saved_preset_shows_the_preset_and_keeps_where_it_lives(lab):
    win, *_ = lab
    c = servers.Connection("Cloud", "example.com", "me", 443, "webdav", start_dir="/nextcloud/remote.php/dav/files/me", preset=servers.NEXTCLOUD)
    dlg = ConnectionDialog(win, c)
    assert dlg.protocol.currentData() == servers.NEXTCLOUD
    dlg.user.setText("you")                                                       # a new user: the address of the files follows
    assert dlg.connection().start_dir == "/nextcloud/remote.php/dav/files/you"
    plain = ConnectionDialog(win, servers.Connection("W", "h", "u", 443, "webdav", start_dir="/dav"))
    assert plain.protocol.currentData() == "webdav" and plain.connection().preset == "" and plain.connection().start_dir == "/dav"


def test_no_user_cannot_be_saved(lab):
    win, *_ = lab
    dlg = nextcloud_dialog(win)
    dlg.name.setText("x")
    dlg.host.setText("cloud.example.com")
    dlg._accept()
    assert "user name" in dlg.problem.text()


def test_the_login_question_says_app_password(lab):
    win, *_ = lab
    c = servers.Connection("Cloud", "example.com", "me", 443, "webdav", preset=servers.NEXTCLOUD)
    dlg = PasswordDialog(win, c)
    assert "app password" in label_text(dlg)


def test_a_nextcloud_is_opened_like_any_web_folder_at_the_address_of_the_users_files(dav):
    win, d, left, right, tmp = dav
    server = win.dav_start(users={"me": "app-pw"}, auth="basic")
    home = win.dav_root / "remote.php" / "dav" / "files" / "me"
    home.mkdir(parents=True)
    (home / "hello.txt").write_text("hi")
    (win.dav_root / "secret.txt").write_text("outside the user's files")
    c = save_dav(win, server, user="me", read_only=True, preset=servers.NEXTCLOUD, start_dir=servers.nextcloud_start("", "me"))
    win.answers["password"] = ("app-pw", False)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.left.path == c.url("/") and win.left.model.row_of("hello.txt") >= 0)
    assert win.left.model.row_of("secret.txt") < 0                                # the top is the user's files, not the server's root
    assert "app password" in label_text(win.asked["password"][0])
