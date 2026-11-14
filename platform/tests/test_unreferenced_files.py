"""The `unreferenced-files` rule and the "Runs" hub product (hub records, task R3).

Written during the testing pause and not yet run.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from factory.services import site_runs
from factory.services.check import check
from factory.services.context import Project
from factory.services.site import products
from factory.services.site_runs import batch_prefix, build_runs, run_groups
from factory.services.study_files import register_file
from factory.services.unreferenced_files import (
    event_strings,
    unreferenced_files,
    walk_files,
)


def _write(project: Project, rel: str, content: bytes = b"x") -> Path:
    path = project.paths.dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_walk_skips_event_blob_library_index_site_and_dot_entries(project: Project) -> None:
    for rel in ("ops/a.txt", "top.txt", "site/x.html", "blobs/b", ".hidden/c", ".dot"):
        _write(project, rel)
    found = walk_files(project.paths.dir)
    assert "ops/a.txt" in found and "top.txt" in found
    assert not any(p.startswith(("site/", "blobs/", "events/", ".")) for p in found)


def test_event_strings_matches_exact_nested_string_values(tmp_path: Path) -> None:
    folder = tmp_path / "events" / "factory"
    folder.mkdir(parents=True)
    line = {"payload": {"a": ["ops/one.txt", {"b": "/root/ops/two.txt"}], "c": "ops/one.txt.bak"}}
    (folder / "e.jsonl").write_text(json.dumps(line) + "\nnot json\n", encoding="utf-8")
    wanted = frozenset({"ops/one.txt", "/root/ops/two.txt", "ops/three.txt", "ops/one.txt.bak"})
    assert event_strings(tmp_path / "events", wanted) == {
        "ops/one.txt",
        "/root/ops/two.txt",
        "ops/one.txt.bak",
    }
    assert event_strings(tmp_path / "events", frozenset({"ops/on"})) == set()


def test_registered_and_library_adopted_files_are_referenced(project: Project) -> None:
    _write(project, "docs/plan.md", b"# Plan\n")
    register_file(project, "docs/plan.md", "study-document", None, project.human_actor())
    _write(project, "ops/loose.txt")
    body = b"%PDF adopted"
    _write(project, "inputs/pdfs/adopted.pdf", body)
    _write(project, "inputs/pdfs/stray.pdf", b"%PDF stray")
    digest = hashlib.sha256(body).hexdigest()
    _write(project, f"library/sha256/{digest[:2]}/{digest[2:]}", body)
    report = unreferenced_files(project)
    assert report.by_folder == {"ops": 1, "inputs": 1}
    assert report.examples == ("inputs/pdfs/stray.pdf", "ops/loose.txt")
    assert report.unreferenced == 2 and report.total >= 4


def test_examples_are_capped_at_twenty(project: Project) -> None:
    for n in range(25):
        _write(project, f"ops/f{n:02d}.txt")
    report = unreferenced_files(project)
    assert report.by_folder == {"ops": 25} and len(report.examples) == 20


def test_check_reports_a_warning_not_an_error(project: Project) -> None:
    _write(project, "ops/loose.txt")
    report = check(project)
    hits = [f for f in report.findings if f.code == "unreferenced-files"]
    assert len(hits) == 1 and hits[0].severity == "warning"
    assert "ops 1" in hits[0].message and "ops/loose.txt" in hits[0].message


def test_check_is_silent_when_every_file_is_named(project: Project) -> None:
    assert not [f for f in check(project).findings if f.code == "unreferenced-files"]


def test_batch_prefix_is_the_token_before_the_first_separator() -> None:
    assert batch_prefix("layerA-3.txt") == "layerA"
    assert batch_prefix("run_cal_release.sh") == "run"
    assert batch_prefix("hub.sh") == "hub"
    assert batch_prefix("plain") == "plain"
    assert batch_prefix("-odd.txt") == "-odd.txt"


def test_runs_groups_by_folder_and_prefix_and_flag_unlinked(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    for rel in (
        "ops/screeners/layerA-1.txt",
        "ops/screeners/layerA-2.txt",
        "ops/screeners/relA-1.txt",
        "ops/screeners/relA-run_01ABCDEFGHJKMNPQRSTVWXYZ00.log",
        "ops/notes.md",
    ):
        _write(project, rel, b"abcd")
    monkeypatch.setattr(site_runs, "_event_ids", lambda _p: {"run_01ABCDEFGHJKMNPQRSTVWXYZ00"})
    groups = {(g.folder, g.prefix): g for g in run_groups(project)}
    assert set(groups) == {("screeners", "layerA"), ("screeners", "relA"), (".", "notes")}
    assert len(groups[("screeners", "layerA")].files) == 2
    assert groups[("screeners", "layerA")].size == 8
    assert not groups[("screeners", "layerA")].linked
    assert groups[("screeners", "relA")].ids == ("run_01ABCDEFGHJKMNPQRSTVWXYZ00",)
    assert [g.linked for g in run_groups(project)] == [False, False, True]


def test_runs_page_links_the_ops_folder(project: Project, tmp_path: Path) -> None:
    _write(project, "ops/screeners/layerA-1.txt", b"hello")
    out = tmp_path / "site"
    out.mkdir()
    build_runs(project, out)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "unlinked" in html and "ops/screeners/layerA-1.txt" in html
    assert (out / "ops").is_symlink()
    assert os.readlink(out / "ops") == str(project.paths.dir / "ops")


def test_runs_page_without_ops_is_empty(project: Project, tmp_path: Path) -> None:
    out = tmp_path / "site"
    out.mkdir()
    build_runs(project, out)
    assert "no ops/ folder" in (out / "index.html").read_text(encoding="utf-8")


def test_runs_product_is_last_in_mining() -> None:
    ids = [p.id for p in products() if p.group == "Mining"]
    assert ids[-1] == "runs"
