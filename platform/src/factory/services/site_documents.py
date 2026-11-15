"""The hub product "Study documents": the registered files of the project, by kind (plan
flow-transparency, part B).

The hub is built from events: a file appears only through a `file.registered` event naming its
path and hash. Each kind is a section; each file shows its title, version, registration date and a
status from `study_files.file_status` (changed since registration in amber, missing in red). A
Markdown file is rendered to HTML from the stored blob of its latest version, so the page shows
what was registered; any other file is linked to the file in the project folder, as the explorer
links originals (a file whose resolved path leaves the project folder is not linked and is marked
"outside the project"). The page is as current as the build: the status is read from the disk
then, and `documents_stamp` (stat of each registered file) makes the hub rebuild when a file
changes on disk.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import quote

from factory.model.files import FILE_KINDS
from factory.services.context import Project
from factory.services.site_synthesis import markdown_to_html
from factory.services.site_widgets import REPORT_CSS, esc, note
from factory.services.study_files import FileStatus, StudyFile, file_status, list_files

KIND_TITLES = {
    "study-document": "Study documents",
    "validation": "Validation",
    "input": "Inputs",
    "ops": "Operational files",
    "other": "Other",
}
_CSS = (
    REPORT_CSS + ".st-changed{color:var(--amber)}.st-missing{color:var(--red)}"
    ".page h1{font-size:22px}.page h2{margin-top:22px}.page p,.page li{max-width:80ch}"
    ".hist{color:var(--dim);font-size:11.5px}"
)


def _slug(path: str) -> str:
    """A file name for `path` that is distinct for distinct paths (a short hash is appended, so
    `a/b.md` and `a__b.md` do not collide)."""
    return f"{path.replace('/', '__')}-{hashlib.sha256(path.encode()).hexdigest()[:6]}"


def _href(*segments: str) -> str:
    return "/".join(quote(s, safe="") for s in segments)


def documents_stamp(project: Project) -> str:
    """A hash of (path, size, mtime) of each registered file's current on-disk state, missing
    files included. Stat only: no content is read."""
    root = project.paths.dir.resolve()
    digest = hashlib.sha256()
    for entry in list_files(project):
        path = entry.latest.path
        try:
            stat = (root / path).stat()
            state = f"{stat.st_size}:{stat.st_mtime_ns}"
        except OSError:
            state = "missing"
        digest.update(f"{path}\0{state}\0".encode())
    return digest.hexdigest()[:12]


def _status_cell(status: FileStatus | None) -> str:
    if status is None or status.state == "unchanged":
        return "unchanged"
    if status.state == "changed":
        return "<span class=st-changed>changed since registration</span>"
    return "<span class=st-missing>missing</span>"


def build_documents(project: Project, out: Path) -> None:
    from factory.services.site import page

    files = list_files(project)
    status = {s.path: s for s in file_status(project)}
    docs = out / "files"
    docs.mkdir(parents=True, exist_ok=True)
    root = project.paths.dir
    links: dict[str, str] = {}
    outside: set[str] = set()
    base = root.resolve()
    for entry in files:
        latest = entry.latest
        name = _slug(latest.path)
        if latest.path.lower().endswith((".md", ".markdown")):
            body = project.blobs.get(latest.blob).decode("utf-8", errors="replace")
            (out / f"{name}.html").write_text(
                page(
                    latest.title or latest.path,
                    f"<div class=page><p class=hist><a href='index.html'>← all documents</a> · "
                    f"{esc(latest.path)} · version {latest.version}, registered "
                    f"{esc(latest.registered_at[:10])}, sha256 {esc(latest.sha256[:12])}</p>"
                    f"{markdown_to_html(body, {})}</div>",
                    _CSS,
                ),
                encoding="utf-8",
            )
            links[latest.path] = _href(f"{name}.html")
        else:
            source = (root / latest.path).resolve()
            target = docs / name
            if target.is_symlink() or target.exists():
                target.unlink()
            if not source.is_relative_to(base):
                outside.add(latest.path)
            elif source.is_file():
                os.symlink(source, target)
                links[latest.path] = _href("files", name)
    sections = "".join(
        _kind_section(kind, [f for f in files if f.latest.kind == kind], status, links, outside)
        for kind in FILE_KINDS
    )
    empty = "" if files else note("No file is registered yet. Use `factory files register`.")
    changed = sum(1 for s in status.values() if s.state == "changed")
    missing = sum(1 for s in status.values() if s.state == "missing")
    summary = note(
        f"{len(files)} registered file(s); {changed} changed since registration, "
        f"{missing} missing. "
        "Each registration keeps the content it named, so an earlier version stays readable."
    )
    (out / "index.html").write_text(
        page(
            "Study documents",
            f"<div class=page><h1>Study documents</h1>{summary}{empty}{sections}</div>",
            _CSS,
        ),
        encoding="utf-8",
    )


def _kind_section(
    kind: str,
    entries: list[StudyFile],
    status: dict[str, FileStatus],
    links: dict[str, str],
    outside: set[str],
) -> str:
    if not entries:
        return ""
    rows = ""
    for entry in entries:
        latest = entry.latest
        href = links.get(latest.path)
        label = esc(latest.title or latest.path)
        shown = f"<a href='{esc(href)}'>{label}</a>" if href else label
        if latest.path in outside:
            shown += " <span class=st-missing>outside the project</span>"
        history = "".join(
            f"<div class=hist>v{r.version}: {esc(r.registered_at[:10])}, {esc(r.sha256[:12])}</div>"
            for r in entry.history
        )
        rows += (
            f"<tr><td>{shown}<div class=hist>{esc(latest.path)}</div></td>"
            f"<td>v{latest.version}</td><td>{esc(latest.registered_at[:10])}</td>"
            f"<td>{_status_cell(status.get(latest.path))}</td><td>{history}</td></tr>"
        )
    return (
        f"<h2>{esc(KIND_TITLES[kind])}</h2><table><tr><th>File</th><th>Version</th>"
        f"<th>Registered</th><th>Status</th><th>Earlier versions</th></tr>{rows}</table>"
    )
