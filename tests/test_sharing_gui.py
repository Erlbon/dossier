"""Sharing in the window: the right-click entries, the Share dialog, the Sharing tab of Properties, the mark and the Shared as column.
No real share is made: the elevated run, the share list and the grants are fakes."""
import base64
import os
import sys

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from dossier.core import sharing  # noqa: E402
from dossier.core.columns import index_of  # noqa: E402
from dossier.core.sharing import CHANGE, EVERYONE, READ, Grant, Share, ShareError  # noqa: E402
from dossier.gui.sharing import ShareDialog  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

B = chr(92)
ADDRS = sharing.Addresses("PC", "100.1.2.3", ["192.168.1.20"])


def texts(menu):
    return [a.text().split("\t")[0] for a in menu.actions() if not a.isSeparator()]


def find(menu, text):
    return next(a for a in menu.actions() if a.text().split("\t")[0] == text)


@pytest.fixture
def shared(world, monkeypatch):
    """The world with a fake set of shares: ``state["shares"]`` is what the computer has; create/change/remove change it."""
    win, d, left, right, tmp = world
    state = {"shares": [], "calls": [], "said": []}
    win.share_lister = lambda: [Share(s.name, s.path, s.remark) for s in state["shares"]]
    win.share_grant_reader = lambda name: next(list(s.grants) for s in state["shares"] if s.name == name)
    win.share_address_reader = lambda: ADDRS
    win.share_account_checker = lambda name: EVERYONE if name.casefold() == "everyone" else ("PC" + B + name.split(B)[-1])
    win._share_addrs = ADDRS

    def create(name, path, grants, remark="", start=None, run=None):
        state["calls"].append(("create", name, path, list(grants)))
        state["shares"].append(Share(name, path, remark, list(grants)))

    def change(old, name, path, grants, remark="", start=None, run=None):
        state["calls"].append(("change", old, name, list(grants)))
        state["shares"] = [s for s in state["shares"] if s.name != old] + [Share(name, path, remark, list(grants))]

    def remove(name, start=None, run=None):
        state["calls"].append(("remove", name))
        state["shares"] = [s for s in state["shares"] if s.name != name]

    monkeypatch.setattr(sharing, "create", create)
    monkeypatch.setattr(sharing, "change", change)
    monkeypatch.setattr(sharing, "remove", remove)
    monkeypatch.setattr(type(win), "_say", lambda self, text: state["said"].append(text))
    (left / "Comics").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("Comics") >= 0)
    yield win, d, left, state
    sharing.KNOWN.update([])


def known(win, state):
    sharing.KNOWN.update(win.share_lister())
    win._shares_loaded()


def answer(monkeypatch, win, fill):
    """The Share dialog is filled in by ``fill(dlg)`` and its OK pressed (accept() checks it, as the real button does)."""
    seen = []

    def ask(self, dlg):
        seen.append(dlg)
        fill(dlg)
        dlg.accept()
        return dlg.result()
    monkeypatch.setattr(type(win), "_ask_share", ask)
    return seen


def test_a_folder_offers_share_and_a_shared_one_its_shares_and_addresses(shared):
    win, d, left, state = shared
    row = win.left.model.row_of("Comics")
    assert "Share..." in texts(win.build_context_menu(win.left, row))
    state["shares"] = [Share("Comics", str(left / "Comics")), Share("Comics-rw", str(left / "Comics"))]
    known(win, state)
    menu = win.build_context_menu(win.left, row)
    assert "Share..." not in texts(menu) and "Shared as Comics, Comics-rw..." in texts(menu)
    copy = find(menu, "Copy Share Address").menu()
    assert texts(copy) == [B * 2 + "PC" + B + "Comics", B * 2 + "100.1.2.3" + B + "Comics", B * 2 + "192.168.1.20" + B + "Comics",
                           B * 2 + "PC" + B + "Comics-rw", B * 2 + "100.1.2.3" + B + "Comics-rw", B * 2 + "192.168.1.20" + B + "Comics-rw"]
    copy.actions()[1].trigger()
    assert QApplication.clipboard().text() == B * 2 + "100.1.2.3" + B + "Comics"


def test_empty_space_shares_the_folder_shown_and_servers_or_archives_offer_nothing(shared):
    win, d, left, state = shared
    assert "Share This Folder..." in texts(win.build_context_menu(win.left, -1))
    menu = win.build_context_menu(win.left, -1)
    win.add_share_entries(menu, "zip://" + str(left / "a.zip") + "/x")
    win.add_share_entries(menu, "sftp://host/x")
    assert texts(menu).count("Share This Folder...") == 1 and "Share..." not in texts(menu)


def test_share_makes_a_share_with_the_checked_people_and_marks_the_folder(shared, monkeypatch):
    win, d, left, state = shared
    folder = str(left / "Comics")

    def fill(dlg):
        assert dlg.name.text() == "Comics" and len(dlg.rows) == 1 and dlg.rows[0].account() == EVERYONE
        assert dlg.address_texts()[0] == B * 2 + "PC" + B + "Comics"
        dlg.rows[0].access.setCurrentIndex(dlg.rows[0].access.findData(READ))
        row = dlg.add_row()
        row.who.setEditText("erlend")
        row.access.setCurrentIndex(row.access.findData(CHANGE))
    answer(monkeypatch, win, fill)
    find(win.build_context_menu(win.left, win.left.model.row_of("Comics")), "Share...").trigger()
    pump(win, lambda: state["calls"] and "Comics" in sharing.KNOWN.names_for(folder))
    assert state["calls"][0] == ("create", "Comics", folder, [Grant(EVERYONE, READ), Grant("PC" + B + "erlend", CHANGE)])
    assert "Shared as Comics" in state["said"]
    m = win.left.model
    row = m.row_of("Comics")
    pump(win, lambda: m.index(row, index_of("shared")).data() == "Comics")


def test_the_dialog_refuses_a_name_in_use_and_an_unknown_person_before_any_prompt(app, tmp_path):
    def check(name):
        if name == "nobody":
            raise ShareError("There is no user or group called nobody.")
        return name
    dlg = ShareDialog(None, str(tmp_path), name="Media", grants=[], choices=[("Everyone on the network", EVERYONE)],
                      taken=["media"], check_account=check, addresses=None)
    assert dlg.address_texts() == []                                           # still reading: no line yet
    dlg.accept()
    assert dlg.result() != QDialog.DialogCode.Accepted and "already" in dlg.problem.text()
    dlg.name.setText("Films")
    dlg.rows[0].who.setEditText("nobody")
    dlg.accept()
    assert dlg.result() != QDialog.DialogCode.Accepted and "nobody" in dlg.problem.text()
    dlg.rows[0].who.setEditText("Everyone on the network")                     # the listed choice, by its text
    dlg.set_addresses(ADDRS)
    assert dlg.address_texts() == [B * 2 + "PC" + B + "Films", B * 2 + "100.1.2.3" + B + "Films", B * 2 + "192.168.1.20" + B + "Films"]
    dlg.accept()
    assert dlg.result() == QDialog.DialogCode.Accepted and dlg.values() == ("Films", [Grant(EVERYONE, READ)])


def test_the_same_person_twice_is_refused_and_the_last_line_cannot_be_taken_away(app, tmp_path):
    dlg = ShareDialog(None, str(tmp_path), name="M", grants=[Grant("PC" + B + "a", READ), Grant("pc" + B + "A", CHANGE)],
                      choices=[], check_account=lambda n: n)
    dlg.accept()
    assert "twice" in dlg.problem.text()
    dlg._remove_row(dlg.rows[1])
    assert len(dlg.rows) == 1 and not dlg.rows[0].remove.isEnabled()
    dlg._remove_row(dlg.rows[0])
    assert len(dlg.rows) == 1


def test_a_deny_entry_made_elsewhere_is_kept_and_not_shown_as_a_line(app, tmp_path):
    deny = Grant("PC" + B + "guest", READ, denied=True)
    dlg = ShareDialog(None, str(tmp_path), name="M", grants=[Grant(EVERYONE, READ), deny], choices=[(EVERYONE, EVERYONE)],
                      editing="M", check_account=lambda n: n)
    assert len(dlg.rows) == 1
    dlg.accept()
    assert dlg.values()[1] == [Grant(EVERYONE, READ), deny]


def test_a_whole_drive_is_shared_only_after_a_warning(shared, monkeypatch):
    win, d, left, state = shared
    seen = answer(monkeypatch, win, lambda dlg: None)
    drive = os.path.abspath(os.sep)
    d.confirm_answer = False
    win.new_share(drive, label="System")
    assert d.confirms and "everything on" in d.confirms[-1][1] and not seen and not state["calls"]
    d.confirm_answer = True
    win.new_share(drive, label="System")
    pump(win, lambda: state["calls"])
    assert seen and state["calls"][0][1] == "System"


def test_the_sharing_tab_lists_the_shares_and_changes_and_stops_them(shared, monkeypatch):
    win, d, left, state = shared
    folder = str(left / "Comics")
    state["shares"] = [Share("Comics", folder, "", [Grant(EVERYONE, READ), Grant("PC" + B + "erlend", CHANGE)])]
    known(win, state)
    dialogs = []
    monkeypatch.setattr(type(win), "_show_properties_dialog", lambda self, dlg: dialogs.append(dlg))
    win.show_sharing(folder)
    pump(win, lambda: dialogs and dialogs[0].sharing_tab.tree.topLevelItemCount() == 2)
    dlg = dialogs[0]
    tab = dlg.sharing_tab
    assert dlg.tabs.tabText(dlg.tabs.currentIndex()) == "Sharing"
    rows = [[tab.tree.topLevelItem(i).text(c) for c in range(3)] for i in range(2)]
    assert rows == [["Comics", "Everyone on the network", "Read only"], ["", "PC" + B + "erlend", "Read and change"]]
    assert "This folder is shared as Comics." == tab.state.text()

    answer(monkeypatch, win, lambda dlg_: dlg_.rows[1].access.setCurrentIndex(0))
    tab.change()
    pump(win, lambda: state["calls"] and tab.tree.topLevelItemCount() == 2 and tab.tree.topLevelItem(1).text(2) == "Read only")
    assert state["calls"][0] == ("change", "Comics", "Comics", [Grant(EVERYONE, READ), Grant("PC" + B + "erlend", READ)])

    tab.stop()
    pump(win, lambda: len(state["calls"]) == 2 and tab.tree.topLevelItemCount() == 0)
    assert state["calls"][1] == ("remove", "Comics") and "Stop sharing Comics?" in d.confirms[-1][1]
    assert "not shared" in tab.state.text()
    pump(win, lambda: sharing.KNOWN.names_for(folder) == [])


def test_a_refused_prompt_changes_nothing_and_says_so(shared, monkeypatch):
    win, d, left, state = shared
    monkeypatch.setattr(sharing, "create", lambda *a, **k: (_ for _ in ()).throw(sharing.Cancelled("Nothing was changed: refused.")))
    answer(monkeypatch, win, lambda dlg: None)
    win.new_share(str(left / "Comics"))
    pump(win, lambda: any("Nothing was changed" in s for s in state["said"]))
    assert not d.infos


def test_a_failed_change_shows_windows_reason(shared, monkeypatch):
    win, d, left, state = shared
    monkeypatch.setattr(sharing, "create", lambda *a, **k: (_ for _ in ()).throw(ShareError("The name has already been shared.")))
    answer(monkeypatch, win, lambda dlg: None)
    win.new_share(str(left / "Comics"))
    pump(win, lambda: d.infos)
    assert d.infos[-1] == ("Sharing", "The name has already been shared.")


@pytest.mark.skipif(sys.platform != "win32", reason="the elevated PowerShell is Windows only")
def test_share_goes_through_one_elevated_powershell(shared, monkeypatch):
    win, d, left, state = shared
    monkeypatch.undo()                                     # the real create, with only the prompt faked
    monkeypatch.setattr(type(win), "_say", lambda self, text: state["said"].append(text))
    scripts = []

    def start(argv):
        scripts.append(base64.b64decode(argv[-1]).decode("utf-16-le"))
        return 0
    win.share_starter = start
    answer(monkeypatch, win, lambda dlg: None)
    win.new_share(str(left / "Comics"))
    pump(win, lambda: "Shared as Comics" in state["said"])
    assert len(scripts) == 1 and "New-SmbShare -Name 'Comics'" in scripts[0] and "-ReadAccess @($everyone)" in scripts[0]


def test_a_shared_folder_gets_a_mark_and_sorts_first_by_its_share(shared):
    win, d, left, state = shared
    (left / "Books").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("Books") >= 0)
    m = win.left.model
    plain = m.index(m.row_of("Comics"), 0).data(Qt.ItemDataRole.DecorationRole).cacheKey()
    state["shares"] = [Share("Comics", str(left / "Comics"))]
    known(win, state)
    marked = m.index(m.row_of("Comics"), 0).data(Qt.ItemDataRole.DecorationRole).cacheKey()
    other = m.index(m.row_of("Books"), 0).data(Qt.ItemDataRole.DecorationRole).cacheKey()
    assert marked != plain and other == plain
    m.sort(index_of("shared"), Qt.SortOrder.AscendingOrder)
    assert m.entry_at(m.row_of("Comics")).name == "Comics" and m.row_of("Comics") < m.row_of("Books")
    assert m.index(m.row_of("Books"), index_of("shared")).data() == ""


def test_the_shared_as_column_starts_hidden(shared):
    win, *_ = shared
    assert win.left.table.isColumnHidden(index_of("shared"))
