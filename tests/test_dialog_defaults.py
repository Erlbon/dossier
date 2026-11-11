"""Enter presses a dialog's main button (Copy, Pack, Search...), not Cancel (2026-11-11: the first Enter in the F5 box cancelled it, so
copying took two presses of F5). The server-trust questions keep Enter on Cancel on purpose."""
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt, QTimer  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit, QVBoxLayout  # noqa: E402

from dossier.gui import servers  # noqa: E402
from dossier.gui.primary_button import PrimaryButtons  # noqa: E402
from dossier.gui.transfer_dialog import TransferDialog  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    if getattr(app, "_dossier_primary_buttons", None) is None:          # as the theme installs it in the real program
        app._dossier_primary_buttons = PrimaryButtons(app)
        app.installEventFilter(app._dossier_primary_buttons)
    return app


def enter_answer(app, dialog: QDialog) -> str:
    """Show ``dialog``, press Enter where the cursor is, and say what it did."""
    said = []
    dialog.accepted.connect(lambda: said.append("accepted"))
    dialog.rejected.connect(lambda: said.append("rejected"))
    # timers parented to the dialog: one left pending after the dialog is deleted would crash the whole run later
    press = QTimer(dialog)
    press.setSingleShot(True)
    press.timeout.connect(lambda: QTest.keyClick(app.focusWidget() or dialog, Qt.Key.Key_Return))
    guard = QTimer(dialog)
    guard.setSingleShot(True)
    guard.timeout.connect(dialog.reject)                                                    # never hang the run
    press.start(150)
    guard.start(3000)
    dialog.exec()
    return said[0] if said else "nothing"


@pytest.mark.parametrize("completion", [True, False])
def test_one_enter_in_the_f5_box_copies(app, completion):
    dlg = TransferDialog(None, "Copy", "Copy 1 item", "Copy", "C:/Temp", False, False, local_completion=completion)
    assert enter_answer(app, dlg) == "accepted"


def test_any_dialog_with_a_cancel_button_first_takes_enter_as_its_main_button(app):
    dlg = QDialog()
    layout = QVBoxLayout(dlg)
    field = QLineEdit("x")
    layout.addWidget(field)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)            # Cancel made first, as in Pack, Search, Compare
    buttons.addButton("Pack", QDialogButtonBox.ButtonRole.AcceptRole)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    field.setFocus()
    assert enter_answer(app, dlg) == "accepted"


def test_the_trust_questions_keep_enter_on_cancel(app):
    key = SimpleNamespace(type="ssh-ed25519", fingerprint="SHA256:abc")
    assert enter_answer(app, servers.HostKeyDialog(None, "host.example", 22, [key], "unknown")) == "rejected"
    assert enter_answer(app, servers.CertificateDialog(None, "host.example", 443, "AB:CD", "unknown")) == "rejected"
