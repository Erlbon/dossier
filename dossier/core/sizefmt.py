"""Sizes for people: one function for the list columns (``19.1 M``) and the progress box (``19 MB``)."""
from __future__ import annotations


def human_size(n, *, long: bool = False, whole_from=None) -> str:
    """``n`` bytes as text. ``long`` spells the units KB, MB...; ``whole_from`` drops the decimal from that size
    on (``10`` gives ``12 MB`` but ``9.5 MB``)."""
    units = ("B", "KB", "MB", "GB", "TB") if long else ("B", "K", "M", "G", "T")
    size = float(n)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B" or (whole_from is not None and size >= whole_from):
                return f"{size:.0f} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return str(n)
