"""Mount a network share (SMB or NFS) through the operating system, from the Home page or the Go menu."""
from __future__ import annotations

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout)

from ..core import mounting
from ..core.drives import list_drives
from .owned_dialog import OwnedDialog
from .background import run_in_background


class MountDialog(OwnedDialog):
    def __init__(self, parent, letters: list, nfs_on: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a Network Share")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.protocol = QComboBox()
        for key, label in mounting.PROTOCOLS:
            self.protocol.addItem(label, key)
        self.address = QLineEdit()
        self.address.setPlaceholderText("\\\\server\\share")
        self.letter = QComboBox()
        self.letter.addItem("Next free letter", "")
        for letter in letters:
            self.letter.addItem(letter, letter)
        self.mount = QCheckBox("Also mount it on a drive letter")
        form.addRow("Type", self.protocol)
        form.addRow("Address", self.address)
        form.addRow("", self.mount)
        form.addRow("Drive letter", self.letter)
        layout.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.addButton("Add", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._nfs_on = nfs_on
        self.protocol.currentIndexChanged.connect(self._changed)
        self.mount.toggled.connect(self._changed)
        self._changed()

    def _changed(self, *_args) -> None:
        nfs = self.protocol.currentData() == mounting.NFS
        if nfs:                                        # Windows cannot open an NFS share by its address: it must be mounted
            self.mount.setChecked(True)
        self.mount.setEnabled(not nfs)
        self.letter.setEnabled(self.mount.isChecked())
        self.ok.setText("Mount" if self.mount.isChecked() else "Add")
        self.address.setPlaceholderText("server:/export   or   \\\\server\\export" if nfs else "\\\\server\\share")
        self.note.setText("Client for NFS is not switched on in Windows. You will be told how to switch it on."
                          if nfs and not self._nfs_on else
                          ("No password is typed here. A share that needs a login works when Windows already has it "
                           "(Credential Manager); otherwise the mount fails and says so." if self.mount.isChecked() else
                           "The address is saved on the Home page and opened like a folder. Nothing is contacted now.")
                          if not nfs else "NFS shares must be mounted on a drive letter first.")

    def values(self) -> tuple:
        return (self.protocol.currentData(), self.address.text(), self.letter.currentData() or "",
                self.mount.isChecked() or self.protocol.currentData() == mounting.NFS)


class MountMixin:
    """Part of ``MainWindow``."""

    def add_network_share(self) -> None:
        """One way in for every network share: save an SMB address on the Home page, or mount it (always for NFS)."""
        nfs_on = mounting.nfs_client_installed()
        used = [d.path for d in list_drives()]
        dlg = MountDialog(self, mounting.free_letters(used), bool(nfs_on))
        if self._ask_mount(dlg) != QDialog.DialogCode.Accepted:
            return
        protocol, text, letter, mount = dlg.values()
        if mount:
            self.mount_share_with(protocol, text, letter)
        else:
            self.save_network_location(text)

    def _ask_mount(self, dlg: MountDialog):                  # a seam for tests
        return dlg.exec()

    def mount_share_with(self, protocol: str, text: str, letter: str = "") -> None:
        address = mounting.clean_address(protocol, text)
        if not address:
            self.dialogs.info("Mount a Network Share", "That is not a share address. Use the form \\\\server\\share"
                              + (" or server:/export" if protocol == mounting.NFS else "") + ".")
            return
        if protocol == mounting.NFS and not mounting.nfs_client_installed():
            self.dialogs.info("Mount a Network Share", mounting.NFS_OFF_TEXT)
            return
        try:
            argv = mounting.build_command(protocol, address, letter)
        except OSError as e:
            self.dialogs.info("Mount a Network Share", str(e))
            return

        def work(progress, cancel):
            progress(0, 0)
            return mounting.run_command(argv, runner=self.mount_runner)

        def finished(result) -> None:
            if result.ok:
                self._say(f"Mounted {address}")
                for panel in (self.left, self.right):
                    if panel.is_home:
                        panel.refresh()
            self.dialogs.show_output(("Mounted " if result.ok else "Could not mount ") + address, result.output)

        run_in_background(self, self.cmd_runner, "Mounting", work, on_result=finished, tracked=self._size_jobs,
                          indeterminate=True, failed_title="Mount a Network Share")

    mount_runner = None                                       # tests put a fake subprocess.run here

    def nfs_status_text(self) -> str:
        on = mounting.nfs_client_installed()
        return "Client for NFS: " + ("switched on" if on else "not switched on" if on is False else "unknown")

    def explain_nfs(self) -> None:
        self.dialogs.info("Client for NFS", self.nfs_status_text() + "\n\n"
                          + ("Windows can mount NFS shares." if mounting.nfs_client_installed() else mounting.NFS_OFF_TEXT))
