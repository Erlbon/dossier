"""F5 and F6 run at once into the other panel; Ctrl+F5 and Ctrl+F6 first show the box that asks where to (``transfer_dialog.py``). Also the
summary of a copy or move, what a typed destination means, and the run. The plans themselves are ``core/ops.py``'s ``plan_copy`` and
``plan_move``."""
from __future__ import annotations

import os

from ..core.ops import Plan, Resolution, plan_copy, plan_move, skip_same
from ..core.platform import has_scheme, is_full_path, path_key
from ..core.sizefmt import human_size
from ..core.vfs import stat_or_none
from .zip_edit import zip_parts

SUMMARY_ITEMS = 12    # the confirmation lists this many items, then says how many more


class TransferMixin:
    """Part of ``MainWindow``."""

    def _summary(self, plan: Plan, dest: str = "", sources=None, origin: str = "") -> str:
        """The text of the confirmation: how much, from where to where, and the items themselves (those of the
        panel the command was started from), folders with what is in them."""
        n_files = len([op for op in plan.ops if op.kind.value in ("copy", "move") and not op.is_dir])
        size = sum(op.size for op in plan.ops if op.kind.value in ("copy", "move") and not op.is_dir)
        top = list(sources) if sources else []
        count = len(top) if top else len([op for op in plan.ops if op.kind.value != "mkdir"])
        text = f"{plan.title} {count} item{'s' if count != 1 else ''}"
        if size:
            text += f" ({human_size(size)}" + (f", {n_files} files" if n_files != count else "") + ")"
        if origin:
            text += f"{chr(10)}from {origin}"
        if dest:
            text += f"{chr(10)}to {dest}"
        if top:
            sep = self.fs.sep
            lines = []
            for src in top[:SUMMARY_ITEMS]:
                below = [op for op in plan.ops if op.src == src or op.src.startswith(src.rstrip(sep) + sep)]
                files = [op for op in below if not op.is_dir and op.kind.value in ("copy", "move")]
                name = self.fs.basename(src)
                if any(op.src != src for op in below):                      # a folder with files in it
                    lines.append(f"  {name}{sep}   {len(files)} files, {human_size(sum(op.size for op in files))}")
                elif len(files) == 1 and files[0].src == src:
                    lines.append(f"  {name}   {human_size(files[0].size)}")
                else:
                    lines.append(f"  {name}")
            if len(top) > SUMMARY_ITEMS:
                lines.append(f"  ... and {len(top) - SUMMARY_ITEMS} more")
            text += chr(10) * 2 + chr(10).join(lines)
        if plan.warnings:
            text += chr(10) * 2 + chr(10).join(plan.warnings[:8])
        return text

    def _transfer(self, move: bool, ask: bool = False) -> None:
        """F5/F6 (``ask`` False): straight into the other panel, conflicts still asked about. Ctrl+F5/F6 (``ask``): the box first, to
        choose another destination, only some files, flatten, skip the same, newer only or verify (the owner's choice, 2026-11-11)."""
        if self._home_blocked("Move" if move else "Copy"):
            return
        sources = self.active.targets()
        if not sources:
            return                                   # a busy window queues the operation
        if self.other.loading:                       # its path is still the old folder: the files would land there
            self.dialogs.info("Copy" if not move else "Move", f"The other panel is still opening "
                              f"{self.other.pending_path}. Wait for it, or press Esc in that panel, and try again.")
            return
        dest, origin = self.other.path, self.active.real_folder()
        if zip_parts(dest) is not None:                  # into an open zip: one rewrite of the archive, not a copy per file
            self._into_zip(sources, dest, move)
            return

        def build(watch):
            return (plan_move if move else plan_copy)(self.fs, sources, dest, watch=watch)

        if ask:
            then = lambda plan: self._confirm_and_run(plan, sources, dest, origin, move)          # noqa: E731
        else:
            then = lambda plan: self._settle_and_run(plan, self._plain_answer(dest), sources, dest, origin, move)   # noqa: E731
        self._plan_in_background(f"Preparing the {'move' if move else 'copy'}", build, then)

    def _plain_answer(self, dest: str):
        """What the box would answer when nothing in it is changed: the other panel, Verify as last chosen, no other options."""
        from .transfer_dialog import TransferAnswer
        return TransferAnswer(dest, self.act_verify.isChecked(), "", False, False, False)

    def _confirm_and_run(self, plan: Plan, sources: list, dest: str, origin: str, move: bool = False) -> None:
        """The plan is ready: the F5 / F6 box (where to, verify, options), a new plan when the answer changed where or what, the
        conflicts, then the run."""
        answer = self.dialogs.ask_transfer(plan.title, self._summary(plan, dest, sources, origin), plan.title, dest,
                                           self.act_verify.isChecked(), move, local=not has_scheme(dest))
        if answer is None:
            return
        self.act_verify.setChecked(answer.verify)    # the choice is remembered for the next time (and shown in Settings)
        if answer.dest == dest and not (answer.only or answer.flatten or answer.skip_same):
            self._settle_and_run(plan, answer, sources, dest, origin, move)
            return
        typed = answer.dest

        def build(watch):
            folder, new_name, make, problem = self._transfer_target(typed, dest, sources)
            if problem:
                return Plan("Move" if move else "Copy", blocking=(problem,)), folder
            if zip_parts(folder) is not None:
                return Plan("Move" if move else "Copy", blocking=("to copy into an archive, open it in the other panel first",)), folder
            if move:
                return plan_move(self.fs, sources, folder, watch=watch, make_dest=make, new_name=new_name), folder
            plan = plan_copy(self.fs, sources, folder, watch=watch, make_dest=make, new_name=new_name, only=answer.only,
                             flatten=answer.flatten)
            if answer.skip_same:                                 # finish the job: only what is missing or changed (by content with Verify)
                plan = skip_same(plan, self.fs, by_content=answer.verify, cancel=getattr(watch, "cancel", None), watch=watch)
            return plan, folder

        self._plan_in_background(f"Preparing the {'move' if move else 'copy'}", build,
                                 lambda found: self._settle_and_run(found[0], answer, sources, found[1], origin, move))

    def _transfer_target(self, typed: str, default_dest: str, sources: list) -> tuple:
        """What a typed destination means: ``(folder, new name for the one item, make the folder, problem)``. A path that is not absolute is
        below the other panel's folder; an existing folder (or a path ending in a separator) is the folder to copy into, made when
        missing; for one item, any other path is its new name in the folder above. Looks at the disk: on a thread."""
        fs = self.fs
        text = typed.strip()
        if not text:
            return default_dest, "", False, "say where to"
        into = text.endswith(("/", "\\"))
        if not has_scheme(text) and not is_full_path(text) and not (len(text) > 1 and text[1] == ":"):
            text = fs.join(default_dest, text)                   # backup -> backup inside the other panel's folder
        if into:
            text = text.rstrip("/\\") or text
            return text, "", stat_or_none(fs, text) is None, ""
        found = stat_or_none(fs, text)
        if found is not None and found.is_dir:
            return text, "", False, ""
        if len(sources) != 1:
            if found is not None:
                return text, "", False, f"{text} is a file: several items go into a folder"
            return text, "", True, ""                            # several items: the folder is made
        above = fs.dirname(text)
        parent = stat_or_none(fs, above)
        if parent is not None and not parent.is_dir:
            return above, "", False, f"{above} is a file"
        return above, fs.basename(text), parent is None, ""

    def _settle_and_run(self, plan: Plan, answer, sources: list, folder: str, origin: str, move: bool) -> None:
        if not move and path_key(folder) == path_key(origin):      # a copy into its own folder is a duplicate beside it
            same = [i for i, op in enumerate(plan.ops) if op.conflict and path_key(op.src) == path_key(op.dst)]
            if same:
                plan = plan.resolve(Resolution.KEEP_BOTH, self.fs, only=same)
        if answer.newer:
            plan = plan.resolve(Resolution.OVERWRITE_IF_NEWER, self.fs)       # an older file is replaced, a newer one stays
        plan = self._settle(plan)
        if plan is None:
            return
        self._run(plan, unmark=sources, remember=self.intent_for(plan, sources, folder))

    def copy(self) -> None:
        self._transfer(move=False)

    def move(self) -> None:
        self._transfer(move=True)

    def copy_with_box(self) -> None:
        self._transfer(move=False, ask=True)

    def move_with_box(self) -> None:
        self._transfer(move=True, ask=True)

