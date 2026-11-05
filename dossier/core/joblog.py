"""The log of a finished copy, move or delete, as a Markdown table (copy plan step 4, as the owner changed it on 2026-11-05; Qt-free).

Nothing is written by itself: after a big job the window offers Tools > Operations > Export Log..., and only then is this text saved where the
owner chooses (the opt-in rule for anything that records names). One row per step: the path, the size, the result (with the reason for a
failure), how many times it was tried, and the seconds it took.
"""
from __future__ import annotations

from datetime import datetime

from .ops import Kind, Result
from .sizefmt import human_size

BIG_STEPS = 500                 # a job is "big" (the log is offered) from this many steps,
BIG_BYTES = 1024 ** 3           # or this many bytes,
BIG_SECONDS = 60.0              # or when it took this long


def is_big(result: Result, seconds: float) -> bool:
    copied = sum(r.op.size for r in result.results if r.op.kind in (Kind.COPY, Kind.MOVE) and not r.op.is_dir)
    return len(result.results) >= BIG_STEPS or copied >= BIG_BYTES or seconds >= BIG_SECONDS


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def markdown(result: Result, title: str, started: float, finished: float) -> str:
    """The whole log: a heading, the totals, and the table."""
    rows = result.results
    counts = {s: sum(1 for r in rows if r.status == s) for s in ("done", "failed", "skipped", "cancelled")}
    size = sum(r.op.size for r in rows if r.status == "done" and not r.op.is_dir)
    stamp = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")          # noqa: E731
    out = [f"# {_cell(title)}", "",
           f"Started {stamp(started)}, finished {stamp(finished)} ({finished - started:.0f} s). "
           f"{counts['done']:,} done, {counts['failed']:,} failed, {counts['skipped']:,} skipped, {counts['cancelled']:,} cancelled; "
           f"{human_size(size)} done.", "",
           "| Path | Size | Result | Retries | Seconds |", "|---|---:|---|---:|---:|"]
    for r in rows:
        path = r.op.dst or r.op.src
        result_text = r.status + (f": {r.error}" if r.error else "")
        out.append(f"| {_cell(path)} | {'' if r.op.is_dir else human_size(r.op.size)} | {_cell(result_text)} | {max(r.attempts - 1, 0)} "
                   f"| {r.seconds:.2f} |")
    return "\n".join(out) + "\n"
