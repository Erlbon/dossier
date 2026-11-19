"""Settings > Typing in a Panel (card 57B): a letter typed in a panel jumps to a name, or goes to the command line.

The Mac and Linux jump by default (Finder, Files, Dolphin and Thunar do); Windows keeps the command line. Ctrl+E (Cmd+E on the
Mac) puts the cursor in the command line on every system. Part of ``MainWindow``; the rules are in ``core/typeahead.py``.
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QActionGroup

from ..core import bundles, typeahead
from ..core.platform import IS_LINUX, IS_MACOS


class TypingModeMixin:
    """Part of ``MainWindow``."""

    typing_platform = (IS_MACOS, IS_LINUX)       # (mac, linux): what the default follows; a test swaps it
    typing_pause_ms = typeahead.PAUSE_MS         # a pause this long starts the typed text over; a test shortens it
    _typed = ""

    def build_typing_menu(self, parent_menu) -> None:
        menu = parent_menu.addMenu("Typing in a Panel")
        menu.menuAction().setToolTip("What a letter typed in a file list does. Ctrl+E goes to the command line either way.")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.typing_actions = {}
        for key, label in typeahead.CHOICES:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.typing_mode() == key)
            act.setToolTip("Typed letters move the cursor to the first name that starts with them; a pause starts over"
                           if key == typeahead.JUMP else "Typed letters start a command under the panels")
            act.triggered.connect(lambda _c=False, k=key: self.set_typing_mode(k))
            group.addAction(act)
            menu.addAction(act)
            self.typing_actions[key] = act

    def typing_mode(self) -> str:
        fallback = typeahead.default_mode(*self.typing_platform)
        return typeahead.valid_mode(self.settings.value("panels/typing", fallback), fallback)

    def set_typing_mode(self, mode: str) -> None:
        self.settings.setValue("panels/typing", mode)
        self._reset_typed()
        if hasattr(self, "typing_actions") and mode in self.typing_actions:
            self.typing_actions[mode].setChecked(True)
        self._say("Typing in a panel jumps to a name" if mode == typeahead.JUMP else "Typing in a panel goes to the command line")

    def focus_command_line(self) -> None:
        """Ctrl+E (Cmd+E on the Mac): the cursor goes to the command line, whatever typing does."""
        self.cmdline.setFocus()
        self.cmdline.setCursorPosition(len(self.cmdline.text()))

    # the jump -------------------------------------------------------------------------------------------------------------------
    def _type_to_command(self, text: str) -> None:
        if self.typing_mode() == typeahead.JUMP:
            self._type_ahead(text)
            return
        self.cmdline.setFocus()
        self.cmdline.insert(text)

    def _reset_typed(self) -> None:
        self._typed = ""

    def _restart_pause(self) -> None:
        timer = getattr(self, "_typed_timer", None)
        if timer is None:
            timer = self._typed_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._reset_typed)
        timer.start(self.typing_pause_ms)

    def _jumping(self) -> bool:
        """True while letters are being typed into a jump (the pause has not passed)."""
        return self.typing_mode() == typeahead.JUMP and bool(self._typed)

    def _type_ahead(self, text: str) -> None:
        self._typed += text
        self._restart_pause()
        self._jump_to_typed()

    def _jump_to_typed(self) -> None:
        panel = self.active
        model = panel.model
        names = []
        for row in range(model.entry_count()):
            entry = model.entry_at(row)
            skip = entry is None or model.is_up_row(row) or entry.kind in ("header", "action")
            names.append(None if skip else bundles.shown_name(entry))
        row = typeahead.find_row(names, self._typed)
        if row < 0:
            self._say(f"No name starts with \"{self._typed}\"")
            return
        view = panel.stack.currentWidget()
        index = model.index(row, 0)
        view.setCurrentIndex(index)
        view.scrollTo(index)
        self._say(f"Typed: {self._typed}")

    def _jump_backspace(self) -> bool:
        """Backspace while typing a jump takes the last letter off; with nothing typed it is left to go up."""
        if not self._jumping():
            return False
        self._typed = self._typed[:-1]
        if self._typed:
            self._restart_pause()
            self._jump_to_typed()
        return True
