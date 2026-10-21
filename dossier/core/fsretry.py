"""``os.replace`` that waits for another program to let go.

On Windows a virus scanner, the search indexer or a preview often holds a file for a moment right after it was written, and the next
rename then fails with a sharing violation (PermissionError). Waiting a little always helped; giving up at the first try lost the save.
Shared by the text editor's save and the archive writer, so there is one rule.
"""
from __future__ import annotations

import os
import time

TRIES = 12
WAIT = 0.1          # seconds; each wait is longer than the last, up to five times this


def replace_with_retry(src: str, dst: str, tries: int = TRIES, wait: float = WAIT) -> None:
    """``os.replace(src, dst)``, tried again while another program has either file open. The last PermissionError is raised as it is."""
    for attempt in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(wait * min(attempt + 1, 5))
