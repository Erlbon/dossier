"""Ctrl+Space in the command line completes a name, Ctrl+Down lists what was typed before. The names are found on a thread (a folder or
a share can be slow); ``CommandLine.apply_completion`` puts them into the line if it has not changed meanwhile."""
from __future__ import annotations

import os
import time

from ..core import completion
from .background import run_in_background

PROGRAM_CACHE_SECONDS = 300            # the programs of PATH are read again after this long


class CommandCompletionMixin:
    """Part of ``MainWindow``."""

    def complete_command_line(self) -> None:
        line = self.cmdline
        text, pos = line.text(), line.cursorPosition()
        if self.active.is_home:
            self._say("Open a folder first: names are completed in the folder of the active panel")
            return
        folder = self.active.real_folder()
        history = list(line.history)
        known = getattr(self, "_program_cache", None)
        use_cache = known is not None and time.time() - known[0] < PROGRAM_CACHE_SECONDS
        cached = known[1] if use_cache else None

        def work(progress, cancel):
            programs = cached
            _start, word, _quote, first = completion.word_at(text, pos)
            if programs is None and first and not ("/" in word or os.sep in word or word.startswith("~")):
                programs = completion.programs(os.environ.get("PATH", "").split(os.pathsep))
            return completion.complete(text, pos, folder, cached_programs=programs, history=history), programs

        def done(result) -> None:
            if result is None:
                return
            found, programs = result
            if programs is not None and not use_cache:
                self._program_cache = (time.time(), programs)
            if line.text() != text:
                return                                                # typed on meanwhile: the answer is for an older line
            if line.apply_completion(found, text) == 0:
                self._say("No name here starts like that")
        run_in_background(self, self.cmd_runner, "Completing the name", work, on_result=done, tracked=self._size_jobs,
                          failed_title="Complete")

    def show_command_history(self) -> None:
        if not self.cmdline.show_history():
            self._say("Nothing typed in the command line yet" if not self.cmdline.history else "No earlier command contains that")
