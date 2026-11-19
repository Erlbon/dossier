"""Settings > Opening Files > Offer Dossier in Open With (card 69C): the window's side of ``core/file_associations.py``.

Two switches (pictures, text files) and "Open Default Apps...". The registry is read and written on a thread, so the window never waits
for it; the ticks show what the registry says (so what the installer's ticks did shows too), refreshed when the menu opens. Windows
only: nothing is added on the Mac and Linux. Windows asks the user for his own "Always" click, so the last step is his, in Default apps.
"""
from __future__ import annotations

from typing import Optional

from ..core import file_associations as F
from ..core.platform import IS_WINDOWS
from .background import run_in_background

DEFAULT_APPS = "ms-settings:defaultapps"
SOURCE_TIP = "Needs the installed Dossier or the dossier.exe download: from source there is no program of its own to offer."


class FileAssociationsMixin:
    """Part of ``MainWindow``."""

    assoc_registry: Optional[object] = None        # tests put a fake registry here, so nothing real is written
    assoc_exe: Optional[str] = None                # tests name the program here
    assoc_frozen: Optional[bool] = None            # tests say whether this is a built program

    def _assoc_reg(self):
        return self.assoc_registry or F.WinRegistry()

    def _assoc_program(self) -> Optional[str]:
        return self.assoc_exe or F.exe_path(self.assoc_frozen)

    def build_associations_menu(self, menu, windows: bool = IS_WINDOWS) -> None:
        """Add the switches to the Opening Files menu; nothing on the Mac and Linux."""
        self.assoc_actions = {}
        if not windows:
            return
        from PyQt6.QtGui import QAction
        menu.addSeparator()
        program = self._assoc_program()
        for group in F.GROUPS:
            act = QAction(group.label, self)
            act.setCheckable(True)
            act.setToolTip("Dossier is then listed in Open With and Default apps for these files "
                           f"({', '.join(group.extensions)}). Windows asks you to click Always yourself. Off takes it away."
                           if program else SOURCE_TIP)
            act.setEnabled(program is not None)
            act.toggled.connect(lambda on, g=group: self.set_association(g, on))
            menu.addAction(act)
            self.assoc_actions[group.key] = act
        self.act_default_apps = QAction("Open Default Apps...", self)
        self.act_default_apps.setToolTip("Windows' Default apps page, where you choose Dossier with Always")
        self.act_default_apps.triggered.connect(self.open_default_apps)
        menu.addAction(self.act_default_apps)
        menu.aboutToShow.connect(self.refresh_associations)

    def open_default_apps(self) -> None:
        self.open_web_page(DEFAULT_APPS)               # the same seam as the Help menu's pages

    def _show_associations(self, states: dict) -> None:
        for key, on in states.items():
            act = self.assoc_actions.get(key)
            if act is not None and act.isChecked() != on:
                act.blockSignals(True)
                act.setChecked(on)
                act.blockSignals(False)

    def refresh_associations(self) -> None:
        """Read the registry on a thread and set the ticks."""
        program = self._assoc_program()
        if not getattr(self, "assoc_actions", None) or program is None:
            return
        reg = self._assoc_reg()

        def work(progress, cancel):
            return {g.key: F.is_enabled(reg, g, program) for g in F.GROUPS}

        run_in_background(self, self.cmd_runner, "Reading what Windows offers", work, on_result=self._show_associations,
                          tracked=self._size_jobs, indeterminate=True, failed_title="Open With")

    def set_association(self, group: F.Group, on: bool) -> None:
        """A switch was clicked: write or remove the group's entries on a thread, then show what is true."""
        program = self._assoc_program()
        if program is None:
            self._show_associations({group.key: False})
            return
        reg = self._assoc_reg()

        def work(progress, cancel):
            progress(0, 0)
            if on:
                F.enable(reg, group, program)
            else:
                F.disable(reg, group)
            return F.is_enabled(reg, group, program)

        def done(state) -> None:
            self._show_associations({group.key: state})
            name = group.friendly.replace("Dossier ", "Dossier's ")
            self._say(f"{name} is offered in Open With. Choose Always in Default apps to make it the default." if state
                      else f"{name} is no longer offered in Open With")

        run_in_background(self, self.cmd_runner, "Changing Open With", work, on_result=done, tracked=self._size_jobs, indeterminate=True,
                          failed_title="Open With", on_end=lambda: None)
