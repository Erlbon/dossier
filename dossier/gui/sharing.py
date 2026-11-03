"""Sharing a folder or a drive on the network: right-click > Share..., the Sharing tab of Properties, Copy Share Address.

The Share dialog makes a share or changes one; the Sharing tab of Properties lists every share of a folder, with Add, Change and Stop
Sharing. Each change is one administrator prompt on Windows (``core/sharing.py``) and runs on a thread, so the window never waits on
it. Which folders are shared is read on a thread when the window opens, after each change and on Refresh: the file list marks them
and the Shared as column names them.
"""
from __future__ import annotations

import os
import threading
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                             QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import sharing
from ..core.drives import is_remote_quick
from ..core.platform import has_scheme
from ..core.sharing import ACCESS, ACCESS_LABELS, EVERYONE, READ, Grant, Share, ShareError
from . import theme
from .background import run_in_background
from .owned_dialog import OwnedDialog

EVERYONE_TEXT = "Everyone on the network"
WINDOWS_NOTE = ("Windows asks for administrator rights once when you press {ok}. "
                "The folder's own file permissions still apply on top of the share's.")
LINUX_NOTE = "The share is made with Samba's usershares, which need no root. The folder's own file permissions still apply."


def can_share(path: str) -> bool:
    """Only a folder on this computer can be shared (not a server, an archive, a network drive or the Home page)."""
    return bool(path) and not has_scheme(path) and not is_remote_quick(path)


class GrantRow(QWidget):
    """One line of the Who list: a person or group (picked or typed), what they may do, and a button that takes the line away."""

    def __init__(self, choices: list, grant: Optional[Grant] = None, on_remove: Optional[Callable] = None) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.who = QComboBox()
        self.who.setEditable(True)
        self.who.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.who.setMinimumWidth(230)
        self.who.lineEdit().setPlaceholderText("User or group, e.g. PC\\name")
        for text, account in choices:
            self.who.addItem(text, account)
        self.access = QComboBox()
        for key in ACCESS:
            self.access.addItem(ACCESS_LABELS[key], key)
        self.remove = QToolButton()
        self.remove.setText("×")
        self.remove.setToolTip("Take this line away")
        if on_remove is not None:
            self.remove.clicked.connect(lambda: on_remove(self))
        row.addWidget(self.who, 1)
        row.addWidget(self.access)
        row.addWidget(self.remove)
        if grant is not None:
            i = self.who.findData(grant.account)
            if i < 0:
                i = next((n for n in range(self.who.count()) if str(self.who.itemData(n)).casefold() == grant.account.casefold()), -1)
            if i >= 0:
                self.who.setCurrentIndex(i)
            else:
                self.who.setEditText(grant.account)
            self.access.setCurrentIndex(max(0, ACCESS.index(grant.access)))

    def account(self) -> str:
        """The account of the line: a listed choice by its account, anything else as typed."""
        text = self.who.currentText().strip()
        i = self.who.findText(text, Qt.MatchFlag.MatchFixedString)
        return str(self.who.itemData(i)) if i >= 0 and self.who.itemData(i) else text

    def grant(self) -> Grant:
        return Grant(self.account(), self.access.currentData() or READ)


class ShareDialog(OwnedDialog):
    """Share a folder or a drive (A), or change a share (from the Sharing tab). ``addresses`` fills in later when it is still read."""

    def __init__(self, parent, path: str, *, name: str, grants: list, choices: list, taken=(), editing: str = "",
                 addresses: Optional[sharing.Addresses] = None, check_account: Callable = sharing.resolve_account) -> None:
        super().__init__(parent)
        self.path = path
        self.editing = editing
        self.taken = list(taken)
        self.check_account = check_account
        self.choices = choices
        self.kept = [g for g in grants if g.denied]          # deny entries made elsewhere: never shown as editable, never written
        self.result_grants: list = []
        self.setWindowTitle(f"Change the Share {editing}" if editing else f"Share {path}")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(name)
        form.addRow("Share name", self.name)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(4)
        self.rows: list = []
        who = QWidget()
        who_layout = QVBoxLayout(who)
        who_layout.setContentsMargins(0, 0, 0, 0)
        who_layout.addLayout(self.rows_box)
        self.add_button = QPushButton("Add Someone")
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(lambda: self.add_row())
        who_layout.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)
        form.addRow("Who", who)
        for g in [g for g in grants if not g.denied] or [Grant(EVERYONE, READ)]:
            self.add_row(g)
        self.address_box = QVBoxLayout()
        self.address_box.setSpacing(2)
        form.addRow("Address", self.address_box)
        layout.addLayout(form)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet(f"color:{theme.current()['danger']};")
        self.problem.hide()
        layout.addWidget(self.problem)
        ok = "Save" if editing else "Share"
        note = QLabel((WINDOWS_NOTE.format(ok=ok) if sharing.IS_WINDOWS else LINUX_NOTE)
                      + (f" {len(self.kept)} deny entr{'y' if len(self.kept) == 1 else 'ies'} made elsewhere stay as they are."
                         if self.kept else ""))
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{theme.current()['dim']};")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.addButton(ok, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._addresses = addresses
        self.name.textChanged.connect(lambda _t: self._show_addresses())
        self._show_addresses()

    def add_row(self, grant: Optional[Grant] = None) -> GrantRow:
        row = GrantRow(self.choices, grant, on_remove=self._remove_row)
        self.rows.append(row)
        self.rows_box.addWidget(row)
        self._removable()
        return row

    def _remove_row(self, row: GrantRow) -> None:
        if len(self.rows) > 1:
            self.rows.remove(row)
            row.setParent(None)
            row.deleteLater()
        self._removable()

    def _removable(self) -> None:
        for r in self.rows:
            r.remove.setEnabled(len(self.rows) > 1)

    def set_addresses(self, addresses: sharing.Addresses) -> None:
        self._addresses = addresses
        self._show_addresses()

    def _show_addresses(self) -> None:
        while self.address_box.count():
            item = self.address_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        name = self.name.text().strip() or "?"
        if self._addresses is None:
            self.address_box.addWidget(QLabel("Reading this computer's addresses..."))
            return
        for label, text in self._addresses.of(name):
            self.address_box.addWidget(address_line(label, text))

    def address_texts(self) -> list:
        """What the address lines say (for tests)."""
        out = []
        for i in range(self.address_box.count()):
            w = self.address_box.itemAt(i).widget()
            if w is not None and w.property("address"):
                out.append(w.property("address"))
        return out

    def accept(self) -> None:
        """Check everything before the administrator prompt: a name in use or a mistyped user is refused here, not by Windows."""
        problem = sharing.check_name(self.name.text(), self.taken, own=self.editing)
        grants: list = []
        if not problem:
            try:
                for r in self.rows:
                    g = r.grant()
                    account = self.check_account(g.account)
                    if any(x.account.casefold() == account.casefold() for x in grants):
                        raise ShareError(f"{account} is in the list twice.")
                    grants.append(Grant(account, g.access))
            except ShareError as e:
                problem = str(e)
        if problem:
            self.problem.setText(problem)
            self.problem.show()
            return
        self.result_grants = grants + self.kept
        super().accept()

    def values(self) -> tuple:
        return self.name.text().strip(), list(self.result_grants)


def address_line(label: str, text: str) -> QWidget:
    """``Tailscale  \\\\100.1.2.3\\Comics  [Copy]``"""
    w = QWidget()
    w.setProperty("address", text)
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    tag = QLabel(label)
    tag.setMinimumWidth(90)
    tag.setStyleSheet(f"color:{theme.current()['dim']};")
    value = QLabel(text)
    value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    copy = QPushButton("Copy")
    copy.setAutoDefault(False)
    copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(text))
    row.addWidget(tag)
    row.addWidget(value, 1)
    row.addWidget(copy)
    return w


class SharingTab(QWidget):
    """The Sharing tab of Properties: every share of one folder with who may use it, and Add, Change, Stop Sharing."""

    def __init__(self, window, path: str) -> None:
        super().__init__()
        self.window_ = window
        self.path = path
        self.shares: list = []
        layout = QVBoxLayout(self)
        self.state = QLabel("Reading the shares...")
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Share", "Who", "Access"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 140)
        self.tree.setColumnWidth(1, 220)
        self.tree.currentItemChanged.connect(lambda *_a: self._selected())
        self.tree.itemDoubleClicked.connect(lambda *_a: self.change())
        layout.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add...")
        self.change_button = QPushButton("Change...")
        self.stop_button = QPushButton("Stop Sharing")
        for b, slot in ((self.add_button, self.add), (self.change_button, self.change), (self.stop_button, self.stop)):
            b.setAutoDefault(False)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.address_box = QVBoxLayout()
        self.address_box.setSpacing(2)
        layout.addLayout(self.address_box)
        self.reload()

    def reload(self) -> None:
        self.state.setText("Reading the shares...")
        self.window_.read_shares_of(self.path, self._loaded)

    def _loaded(self, shares: list, problem: str = "") -> None:
        try:
            self.tree.clear()
        except RuntimeError:                           # the dialog was closed while the shares were read
            return
        self.shares = shares
        for s in shares:
            for i, g in enumerate(s.grants or [Grant("?", READ)]):
                who = EVERYONE_TEXT if g.account == EVERYONE else g.account
                item = QTreeWidgetItem([s.name if i == 0 else "", who, "Denied" if g.denied else ACCESS_LABELS[g.access]])
                item.setData(0, Qt.ItemDataRole.UserRole, s.name)
                self.tree.addTopLevelItem(item)
        if problem:
            self.state.setText(problem)
        elif shares:
            self.state.setText("This folder is shared as " + ", ".join(s.name for s in shares) + ".")
        else:
            self.state.setText("This folder is not shared. Add... shares it on the network.")
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._selected()

    def current(self) -> Optional[Share]:
        item = self.tree.currentItem()
        name = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return next((s for s in self.shares if s.name == name), None)

    def _selected(self) -> None:
        share = self.current()
        self.change_button.setEnabled(share is not None)
        self.stop_button.setEnabled(share is not None)
        while self.address_box.count():
            item = self.address_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if share is not None:
            waiting = self.window_._share_addrs is None             # the full list comes a moment later: show it again then
            for label, text in self.window_.share_addresses(on_ready=(lambda _a: self._selected()) if waiting else None).of(share.name):
                self.address_box.addWidget(address_line(label, text))

    def add(self) -> None:
        self.window_.new_share(self.path, on_done=self.reload, parent=self)

    def change(self) -> None:
        share = self.current()
        if share is not None:
            self.window_.change_share(share, on_done=self.reload, parent=self)

    def stop(self) -> None:
        share = self.current()
        if share is not None:
            self.window_.stop_share(share.name, on_done=self.reload, parent=self)


class SharingMixin:
    """Part of ``MainWindow``."""

    share_lister = None            # tests put a fake list_shares here
    share_starter = None           # tests put a fake elevated start here (argv -> exit code, or None for a refused prompt)
    share_grant_reader = None      # tests put a fake read_grants here
    share_address_reader = None    # tests put a fake read_addresses here
    share_account_checker = None   # tests put a fake resolve_account here

    def build_sharing(self) -> None:
        self._share_addrs: Optional[sharing.Addresses] = None
        self._share_addrs_reading = False
        self._share_addr_waiters: list = []
        self.refresh_shares()

    # what is shared -------------------------------------------------------------------------------------------------------
    def refresh_shares(self) -> None:
        """Read which folders are shared, on a thread, then redraw the marks and the Shared as column."""
        if getattr(self, "_closing", False):
            return
        def loaded() -> None:
            try:
                self.dispatcher(self._shares_loaded)
            except RuntimeError:                       # the window was closed while the shares were read
                pass
        sharing.KNOWN.refresh_async(loaded, lister=self.share_lister)

    def _shares_loaded(self) -> None:
        if self._closing:
            return
        for panel in (self.left, self.right):
            panel.model.shares_changed()
        if sharing.KNOWN.all_names() and self._share_addrs is None:
            self.share_addresses()                    # read the addresses now, so Copy Share Address has them

    def shared_names(self, path: str) -> list:
        return sharing.KNOWN.names_for(path) if can_share(path) else []

    def share_addresses(self, on_ready: Optional[Callable] = None) -> sharing.Addresses:
        """The host parts of the share addresses: what is known now (the computer's name at least), and ``on_ready(addresses)`` once
        the Tailscale and local network addresses are in (read once, on a thread)."""
        if self._share_addrs is not None:
            if on_ready is not None:
                on_ready(self._share_addrs)
            return self._share_addrs
        if on_ready is not None:
            self._share_addr_waiters.append(on_ready)
        if not self._share_addrs_reading:
            self._share_addrs_reading = True

            def work() -> None:
                try:
                    found = (self.share_address_reader or sharing.read_addresses)()
                except Exception:                     # noqa: BLE001 -- no address is not an error: the name is still there
                    found = sharing.Addresses(sharing.this_host())
                self.dispatcher(lambda: self._addresses_read(found))
            threading.Thread(target=work, daemon=True, name="dossier-share-addresses").start()
        return sharing.Addresses(sharing.this_host())

    def _addresses_read(self, found: sharing.Addresses) -> None:
        self._share_addrs = found
        self._share_addrs_reading = False
        waiters, self._share_addr_waiters = self._share_addr_waiters, []
        for w in waiters:
            try:
                w(found)
            except RuntimeError:                       # its dialog is gone
                pass

    def read_shares_of(self, path: str, on_done: Callable) -> None:
        """The shares of ``path`` with their grants, read on a thread, then ``on_done(shares, problem)`` on the window's thread."""
        lister = self.share_lister or sharing.list_shares
        reader = self.share_grant_reader or sharing.read_grants
        key = sharing.path_key(path)

        def work(progress, cancel):
            shares = [s for s in lister() if sharing.path_key(s.path) == key]
            problem = ""
            for s in shares:
                if not s.grants:
                    try:
                        s.grants = reader(s.name)
                    except ShareError as e:
                        problem = str(e)
            sharing.KNOWN.update(lister())
            return shares, problem

        run_in_background(self, self.cmd_runner, "Reading the shares", work, on_result=lambda r: on_done(*r),
                          tracked=self._size_jobs, indeterminate=True, failed_title="Sharing")

    # the right-click entries ----------------------------------------------------------------------------------------------
    def add_share_entries(self, menu: QMenu, path: str, label: str = "", here: bool = False) -> None:
        """Share... (or Shared as X...) and, for a shared folder, Copy Share Address with every address of every share."""
        if not can_share(path):
            return
        names = self.shared_names(path)
        if names:
            menu.addAction("Shared as " + ", ".join(names) + "...", lambda: self.show_sharing(path))
            copy = menu.addMenu("Copy Share Address")
            addrs = self.share_addresses()
            for name in names:
                for _label, text in addrs.of(name):
                    copy.addAction(text, lambda t=text: self.copy_share_address(t))
        else:
            menu.addAction("Share This Folder..." if here else "Share...", lambda: self.new_share(path, label=label))

    def copy_share_address(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self._say(f"Copied {text}")

    def show_sharing(self, path: str) -> None:
        """The Sharing tab of Properties for ``path``."""
        self.show_properties(paths=[path], tab="Sharing")

    # making, changing and stopping ----------------------------------------------------------------------------------------
    def _who_choices(self) -> list:
        me = sharing.current_user()
        choices = [(EVERYONE_TEXT, EVERYONE)]
        if me:
            choices.append((f"Only me ({me})", me))
        short_me = me.split("\\")[-1].casefold()
        choices += [(name, name) for name in sharing.local_accounts() if name.casefold() != short_me]
        return choices

    def _ask_share(self, dlg: ShareDialog):                  # a seam for tests
        return dlg.exec()

    def _share_dialog(self, path: str, parent, **kw) -> ShareDialog:
        dlg = ShareDialog(parent or self, path, choices=self._who_choices(), taken=sorted(sharing.KNOWN.all_names()),
                          addresses=self._share_addrs, check_account=self.share_account_checker or sharing.resolve_account, **kw)
        if self._share_addrs is None:
            self.share_addresses(on_ready=dlg.set_addresses)
        return dlg

    def new_share(self, path: str, label: str = "", on_done: Optional[Callable] = None, parent=None) -> None:
        if not can_share(path):
            self._say("Only folders on this computer can be shared")
            return
        if sharing.is_drive_root(path) and not self.dialogs.confirm(
                "Share a Whole Drive", f"This shares everything on {path}, every folder on the drive, with whoever you choose next.\n\n"
                "Share a folder instead if only part of it is meant for others.", "Share the Drive"):
            return
        dlg = self._share_dialog(path, parent, name=sharing.suggest_name(path, label, sharing.KNOWN.all_names()), grants=[])
        if self._ask_share(dlg) != QDialog.DialogCode.Accepted:
            return
        name, grants = dlg.values()
        self._share_change("Sharing", lambda start: sharing.create(name, path, grants, start=start), f"Shared as {name}", on_done)

    def change_share(self, share: Share, on_done: Optional[Callable] = None, parent=None) -> None:
        dlg = self._share_dialog(share.path, parent, name=share.name, grants=share.grants, editing=share.name)
        if self._ask_share(dlg) != QDialog.DialogCode.Accepted:
            return
        name, grants = dlg.values()
        self._share_change("Changing the share",
                           lambda start: sharing.change(share.name, name, share.path, grants, share.remark, start=start),
                           f"Share {name} changed", on_done)

    def stop_share(self, name: str, on_done: Optional[Callable] = None, parent=None) -> None:
        host = self.share_addresses().host
        if not self.dialogs.confirm("Stop Sharing", f"Stop sharing {name}?\n\nWhoever uses \\\\{host}\\{name} loses access to it. "
                                    "The folder and its files stay as they are.", "Stop Sharing"):
            return
        self._share_change("Stopping the share", lambda start: sharing.remove(name, start=start), f"Stopped sharing {name}", on_done)

    def _share_change(self, title: str, do: Callable, done_text: str, on_done: Optional[Callable]) -> None:
        """Run one change on a thread (the administrator prompt waits there), then read the shares again."""
        start = self.share_starter

        def work(progress, cancel):
            progress(0, 0)
            try:
                do(start)
            except sharing.Cancelled as e:
                return str(e)
            return ""

        def finished(cancelled: str) -> None:
            self._say(cancelled or done_text)
            self.refresh_shares()
            if on_done is not None:
                try:
                    on_done()
                except RuntimeError:                   # its dialog is gone
                    pass

        run_in_background(self, self.cmd_runner, title, work, on_result=finished, tracked=self._size_jobs, indeterminate=True,
                          failed_title="Sharing")
