"""Completing what is typed in the command line: file and folder names, and program names. Qt-free.

``complete`` looks at the word the cursor is in and answers with the words that could replace it. It reads the disk (a folder listing,
the folders of ``PATH``), so the window calls it on a thread. A name with a space is put in double quotes (a word that was begun with a
quote stays in it); a folder ends in the separator so the next press goes one level in. Nothing here runs or changes anything.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .platform import IS_WINDOWS
from .vfs import natural_key

MAX_ITEMS = 500
PROGRAM_SUFFIXES = (".exe", ".cmd", ".bat", ".com", ".ps1") if IS_WINDOWS else ()


@dataclass
class Completion:
    start: int = 0                                  # the word to replace is text[start:end]
    end: int = 0
    items: list = field(default_factory=list)       # the words that fit, without quotes, folders first
    quote: str = ""                                 # the quote the typed word was opened with
    complete: bool = True                           # False: more matched than ``MAX_ITEMS``

    def render(self, body: str, closing: bool = False) -> str:
        """``body`` as it goes into the line: in quotes if it has a space (or the word was opened with one). ``closing`` shuts the quote:
        right for a finished file name, wrong for a start or a folder, where the next press goes on."""
        q = self.quote or ('"' if _needs_quotes(body) else "")
        return q + body + (q if closing and q else "")

    def common(self) -> str:
        """The longest start every item has (case as the first item has it)."""
        if not self.items:
            return ""
        first = self.items[0]
        n = len(first)
        fold = (lambda t: t.lower()) if IS_WINDOWS else (lambda t: t)
        for item in self.items[1:]:
            same = 0
            while same < n and same < len(item) and fold(first[same]) == fold(item[same]):
                same += 1
            n = same
        return first[:n]


def word_at(text: str, pos: int) -> tuple:
    """``(start, word, quote, first)``: where the word the cursor is in begins, the word without its opening quote, the quote it was
    opened with (``""`` for none), and whether it is the first word (the program name)."""
    pos = max(0, min(pos, len(text)))
    quote = ""
    start = 0
    i = 0
    while i < pos:
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            if i == 0 or text[i - 1] == " ":
                start = i
        elif ch == " ":
            start = i + 1
        i += 1
    word = text[start:pos]
    if word[:1] in ("\"", "'"):
        quote, word = word[0], word[1:]
    elif quote:
        quote = ""
    first = not text[:start].strip()
    return start, word, quote, first


def _needs_quotes(name: str) -> bool:
    return any(c in name for c in " &()^;") or (IS_WINDOWS and "%" in name)


def _folder_names(folder: str) -> list:
    try:
        with os.scandir(folder) as it:
            return [(e.name, _is_dir(e)) for e in it]
    except OSError:
        return []


def _is_dir(entry) -> bool:
    try:
        return entry.is_dir()
    except OSError:
        return False


def programs(path_dirs: Iterable[str]) -> list:
    """The program names found in the folders of ``PATH`` (without the extension where one is implied), each once."""
    seen: dict = {}
    for d in path_dirs:
        for name, is_dir in _folder_names(d):
            if is_dir:
                continue
            low = name.lower()
            if PROGRAM_SUFFIXES:
                if not low.endswith(PROGRAM_SUFFIXES):
                    continue
                shown = name[:name.rfind(".")]
            else:
                full = os.path.join(d, name)
                if not os.access(full, os.X_OK):
                    continue
                shown = name
            seen.setdefault(shown.lower() if IS_WINDOWS else shown, shown)
    return sorted(seen.values(), key=natural_key)


def complete(text: str, pos: int, folder: str, *, path_dirs: Optional[Iterable[str]] = None, cached_programs: Optional[list] = None,
             history: Iterable[str] = ()) -> Completion:
    """The words that could replace the word at ``pos``. ``folder`` is where relative names are looked up (the panel's folder).
    ``cached_programs`` spares reading ``PATH`` again; ``history`` adds earlier first words to the program names."""
    start, word, quote, first = word_at(text, pos)
    result = Completion(start=start, end=pos)
    sep_in_word = ("/" in word) or (IS_WINDOWS and "\\" in word)
    names: list = []                                  # (shown text, is a folder)
    prefix = ""                                       # the typed folder part, kept as typed
    if sep_in_word or not first or word.startswith("~"):
        cut = max(word.rfind("/"), word.rfind("\\") if IS_WINDOWS else -1)
        prefix, leaf = (word[:cut + 1], word[cut + 1:]) if cut >= 0 else ("", word)
        base = os.path.expanduser(prefix) if prefix.startswith("~") else prefix
        where = base if os.path.isabs(base) else os.path.join(folder, base)
        if prefix == "" and word.startswith("~"):
            prefix, leaf, where = "", word, folder
        for name, is_dir in _folder_names(where or folder):
            names.append((name, is_dir))
    else:
        leaf = word
        for name, is_dir in _folder_names(folder):
            names.append((name, is_dir))
        known = cached_programs if cached_programs is not None else programs(path_dirs if path_dirs is not None else os.environ.get("PATH", "").split(os.pathsep))
        have = {n for n, _d in names}
        names += [(p, False) for p in known if p not in have]
        names += [(h, False) for h in dict.fromkeys(x.split(" ", 1)[0] for x in history if x) if h not in have and h not in known]
    low = leaf.lower() if IS_WINDOWS or first else leaf
    hits = [(n, d) for n, d in names if (n.lower() if IS_WINDOWS or first else n).startswith(low) and (leaf.startswith(".") or not n.startswith(".") or leaf == n)]
    hits.sort(key=lambda nd: (not nd[1], natural_key(nd[0])))
    result.complete = len(hits) <= MAX_ITEMS
    result.quote = quote
    result.items = [prefix + name + (os.sep if is_dir else "") for name, is_dir in hits[:MAX_ITEMS]]
    return result
