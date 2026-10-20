"""What the window does with a drop: copy or move the dragged items into the folder they were dropped on.

Keys decide first (Ctrl copies, Shift moves). With no key a move stays on one drive and a copy goes to another, as in Explorer. A drag
out of an archive can only copy. Everything goes through the normal copy and move engine: the conflict dialog, progress, Cancel,
undo, tags that follow the files. Nothing is asked before the copy unless Settings > Copy and Move says so; a drop into an open zip
is the zip's own question (it rewrites the archive).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt

from ..core.ops import plan_copy, plan_move, same_volume
from .zip_edit import zip_parts

CTRL = int(Qt.KeyboardModifier.ControlModifier.value)
SHIFT = int(Qt.KeyboardModifier.ShiftModifier.value)


class DragDropMixin:
    """Part of ``MainWindow``."""

    def _files_dropped(self, paths: list, dest: str, modifiers: int, source=None) -> None:
        paths = [p for p in paths if p]
        if not paths:
            return
        copy_key, move_key = bool(modifiers & CTRL), bool(modifiers & SHIFT)
        if zip_parts(dest) is not None:
            self._into_zip(paths, dest, move=move_key and not copy_key)
            return
        explicit = False if copy_key else True if move_key else None
        if any(p.startswith("zip://") for p in paths):
            explicit = False                                   # items inside an archive can only be copied out
        origin = self.fs.dirname(paths[0])

        def build(watch):
            move = explicit if explicit is not None else same_volume(self.fs, paths[0], dest)
            return (plan_move if move else plan_copy)(self.fs, paths, dest, watch=watch)

        def then(plan) -> None:
            if self.copy_settings()["ask_on_drop"]:
                self._confirm_and_run(plan, paths, dest, origin)
                return
            plan = self._settle(plan)                          # conflicts are asked about; the rest just runs
            if plan is not None:
                self._run(plan, unmark=paths)

        self._plan_in_background("Preparing the drop", build, then)
