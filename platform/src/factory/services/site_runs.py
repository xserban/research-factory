"""The hub product "Runs": the agent-run files under `ops/`, grouped (plan flow-transparency, R3).

The files of `ops/` (prompts, screener scripts, logs, overnight status files) are not events.
This product lists them by sub-folder and batch prefix (the leading token of the file name
before the first `-`, `_` or `.`, such as `layerA`, `relA`, `mineD`) with the file count, the
modification-date range and the total size. A group is *linked* when a file name contains a run
id (`run_...`) or a task id (`tsk_...`) that some event names; the others are flagged unlinked.
Nothing is written to the project: `ops/` is symlinked into the product's out folder so each
file opens from the page. Pass labels are not matched (a name seldom holds one).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from factory.events.reader import event_files
from factory.services.context import Project
from factory.services.site_widgets import REPORT_CSS, esc, note

_ID_IN_NAME = re.compile(r"(?:run|tsk)_[0-9A-Za-z]{8,}")
_ID_IN_EVENT = re.compile(rb'"((?:run|tsk)_[0-9A-Za-z]{8,})"')
_PREFIX = re.compile(r"[-_.]")
_CSS = (
    REPORT_CSS + ".unlinked{color:var(--amber)}.linked{color:var(--green,inherit)}"
    ".page h1{font-size:22px}.page details{margin:2px 0}.page summary{cursor:pointer}"
    ".hist{color:var(--dim);font-size:11.5px}"
)


@dataclass(frozen=True)
class RunFile:
    path: str
    """Relative to `ops/`."""
    size: int
    mtime: float


@dataclass(frozen=True)
class RunGroup:
    folder: str
    """The sub-folder of `ops/` the files sit in (the first level), `.` for `ops/` itself."""
    prefix: str
    files: tuple[RunFile, ...]
    ids: tuple[str, ...]
    """The run or task ids named in file names and by an event."""

    @property
    def linked(self) -> bool:
        return bool(self.ids)

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def first(self) -> float:
        return min(f.mtime for f in self.files)

    @property
    def last(self) -> float:
        return max(f.mtime for f in self.files)


def batch_prefix(name: str) -> str:
    """The leading token of a file name before the first `-`, `_` or `.` (`layerA-3.txt` gives
    `layerA`); a name that starts with a separator keeps the name itself."""
    token = _PREFIX.split(name, maxsplit=1)[0]
    return token or name


def _event_ids(project: Project) -> set[str]:
    found: set[str] = set()
    for path in event_files(project.paths.events_dir):
        with path.open("rb") as handle:
            for line in handle:
                found.update(m.decode() for m in _ID_IN_EVENT.findall(line))
    return found


def _walk(ops: Path) -> list[RunFile]:
    found: list[RunFile] = []
    for base, dirs, names in os.walk(ops):
        dirs.sort()
        for name in sorted(names):
            full = Path(base) / name
            try:
                stat = full.stat()
            except OSError:
                continue
            found.append(RunFile(full.relative_to(ops).as_posix(), stat.st_size, stat.st_mtime))
    return found


def run_groups(project: Project) -> list[RunGroup]:
    """The groups of `ops/` by (first-level folder, batch prefix), unlinked first, then by
    folder and prefix. Empty without an `ops/` folder. Read-only."""
    ops = project.paths.dir / "ops"
    if not ops.is_dir():
        return []
    named = _event_ids(project)
    buckets: dict[tuple[str, str], list[RunFile]] = {}
    for item in _walk(ops):
        folder, _, rest = item.path.partition("/")
        if not rest:
            folder, rest = ".", item.path
        buckets.setdefault((folder, batch_prefix(rest.rsplit("/", 1)[-1])), []).append(item)
    groups: list[RunGroup] = []
    for (folder, prefix), files in buckets.items():
        ids = sorted(
            {m for f in files for m in _ID_IN_NAME.findall(f.path.rsplit("/", 1)[-1]) if m in named}
        )
        groups.append(RunGroup(folder, prefix, tuple(files), tuple(ids)))
    return sorted(groups, key=lambda g: (g.linked, g.folder, g.prefix))


def _day(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%d")


def _size(n: int) -> str:
    value = float(n)
    for unit in ("B", "kB", "MB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _group_html(group: RunGroup) -> str:
    items = "".join(
        f"<li><a href='ops/{esc(f.path)}'>{esc(f.path)}</a> "
        f"<span class=hist>{_day(f.mtime)}, {_size(f.size)}</span></li>"
        for f in sorted(group.files, key=lambda f: f.path)
    )
    state = (
        f"<span class=linked>linked: {esc(', '.join(group.ids[:3]))}</span>"
        if group.linked
        else "<span class=unlinked>unlinked</span>"
    )
    span = (
        _day(group.first)
        if _day(group.first) == _day(group.last)
        else (f"{_day(group.first)} to {_day(group.last)}")
    )
    return (
        f"<tr><td>{esc(group.folder)}</td><td>{esc(group.prefix)}</td><td>{len(group.files)}</td>"
        f"<td>{span}</td><td>{_size(group.size)}</td><td>{state}</td>"
        f"<td><details><summary>files</summary><ul>{items}</ul></details></td></tr>"
    )


def build_runs(project: Project, out: Path) -> None:
    from factory.services.site import page

    groups = run_groups(project)
    ops = project.paths.dir / "ops"
    link = out / "ops"
    if ops.is_dir():
        if link.is_symlink() or link.exists():
            link.unlink()
        os.symlink(ops, link)
    total = sum(len(g.files) for g in groups)
    unlinked = sum(1 for g in groups if not g.linked)
    summary = note(
        f"{total} file(s) in {len(groups)} group(s) under ops/; {unlinked} group(s) unlinked "
        "(no file name holds a run or task id that an event names). The files are not events."
    )
    empty = "" if groups else note("There is no ops/ folder, or it holds no file.")
    table = (
        "<table><tr><th>Folder</th><th>Batch</th><th>Files</th><th>Modified</th><th>Size</th>"
        f"<th>Linked</th><th>Files</th></tr>{''.join(_group_html(g) for g in groups)}</table>"
        if groups
        else ""
    )
    (out / "index.html").write_text(
        page("Runs", f"<div class=page><h1>Runs</h1>{summary}{empty}{table}</div>", _CSS),
        encoding="utf-8",
    )
