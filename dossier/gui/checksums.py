"""Commands > Checksums: compute, show, copy and compare checksums. Never writes a file."""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from ..core.checksums import LABELS, algorithm_of, clean_value, format_report, hash_files, match
from .background import run_in_background


class ChecksumMixin:
    """Part of ``MainWindow``."""

    def _files_to_hash(self) -> list:
        """The marked files of this panel (or the one under the cursor), judged by the listing the panel already has."""
        model = self.active.model
        is_dir = {e.path: e.is_dir for e in (model.entry_at(r) for r in range(model.entry_count())) if e is not None}
        return [p for p in self.active.targets() if not is_dir.get(p, False)]

    def show_checksums(self, algorithm: str = "sha256") -> None:
        """Checksums of the marked files (or the one under the cursor): shown in a box and put on the clipboard as
        ``hash *name`` lines, which is what sha256sum -c reads."""
        self._hash_then(algorithm, None)

    def verify_checksum(self) -> None:
        """Ask for a pasted checksum and say which of the marked files it belongs to, if any."""
        value = self.dialogs.ask_text("Verify Checksum", "Paste the checksum (MD5, SHA-1, SHA-256 or SHA-512):", "")
        if value is None:
            return
        value = clean_value(value)
        if not value:
            self.dialogs.info("Verify Checksum", "That is not a checksum: it should be 32, 40, 64 or 128 hex digits.")
            return
        self._hash_then(algorithm_of(value), value)

    def _hash_then(self, algorithm: str, expected) -> None:
        files = self._files_to_hash()
        if not files:
            self._say("Mark files (or put the cursor on one) to get their checksums; folders are not hashed")
            return
        current = {"text": ""}

        def work(progress, cancel):
            def report(done: int, total: int, name: str) -> None:
                if name:
                    current["text"] = f"{self.fs.basename(name)}  ({done + 1} of {total})"
                progress(done, total)
            return hash_files(self.fs, files, (algorithm,), cancel, report)

        def finished(results: list) -> None:
            name_of = self.fs.basename
            if expected is None:
                text = format_report(results, algorithm, name_of)
                QApplication.clipboard().setText(text)
                self.dialogs.show_output(f"{LABELS[algorithm]} checksums (copied to the clipboard)", text)
                return
            hit = match(expected, results)
            if hit:
                self.dialogs.info("Verify Checksum", f"{LABELS[algorithm]} matches: {name_of(hit[0].path)}")
            else:
                self.dialogs.info("Verify Checksum",
                                  f"No match. None of the {len(results)} file(s) has that {LABELS[algorithm]} checksum.")

        run_in_background(self, self.cmd_runner, "Checksums", work, on_result=finished, tracked=self._size_jobs,
                          detail=lambda: current["text"], failed_title="Checksums")
