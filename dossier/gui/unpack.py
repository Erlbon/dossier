"""Opening a file that lives inside an archive: unpack it to a temporary folder on a thread, then open it."""
from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from ..core import zipfs
from .background import run_in_background
from .models import human_size

EXTRACT_CONFIRM = 200 * 1024 * 1024     # a file unpacked from an archive: ask first above this size


class UnpackMixin:
    """Part of ``MainWindow``."""

    def _open_with_system(self, local_path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(local_path))

    def _unpack_then(self, paths: list, then) -> None:
        """Unpack items of an archive to a temporary folder on a thread (with a box, Cancel and a question first when
        it is big), then call ``then(list of the unpacked paths)`` on the window's thread."""
        sizes = []
        for p in paths:
            try:
                sizes.append(self.fs.stat(p).size)
            except OSError as e:
                self.dialogs.info("Open", f"Cannot read {self.fs.basename(p)}: {e.strerror or e}")
                return
        total = sum(sizes)
        if total > EXTRACT_CONFIRM and not self.dialogs.confirm(
                "Open from an Archive", f"{human_size(total)} will be unpacked to a temporary folder to open it. Go on?", "Unpack"):
            return

        def work(progress, cancel):
            out, before = [], 0
            for p, size in zip(paths, sizes):
                out.append(zipfs.local_copy(self.fs, p, cancel, lambda done, b=before: progress(b + done, total)))
                before += size
            return out

        what = self.fs.basename(paths[0]) + (f" and {len(paths) - 1} more" if len(paths) > 1 else "")
        run_in_background(self, self.cmd_runner, "Unpacking", work, on_result=then, tracked=self._size_jobs,
                          detail=lambda: what, plan_bytes=total, failed_title="Open from an Archive")
