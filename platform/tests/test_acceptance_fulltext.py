# ruff: noqa: F811
"""Acceptance for full-text acquisition (plan 2A): AC 1, 14 and 15, offline on stub routes.

A corpus is built from the slice-1 helpers, so the works are promoted through both passes. The
live arXiv check is the single `network` test at the end; it is deselected by default.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Identifiers, Provenance, Work
from factory.services import check as check_service
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext, restore_document
from factory.services.fulltext_import import import_folder
from factory.services.fulltext_status import fulltext_status
from factory.services.project import init_project
from factory.services.search import list_works
from factory.services.trace import trace
from factory.sources.fulltext.arxiv import (
    ArxivHtmlRoute,
    ArxivSourceRoute,
    arxiv_version_lookup,
)
from factory.sources.http import default_http
from tests.fulltext_helpers import CONTENT, _build, _pdf, _promoted, _routes, corpus  # noqa: F401
from tests.helpers import SESSION, T0, SourcesFor, _of_type, install_skill

pytestmark = pytest.mark.slow  # acceptance suite: dev runs deselect with -m "not slow"

REPO_ROOT = Path(__file__).resolve().parents[2]
ARXIV_LIVE = "1706.03762"


# --- AC 1: every promoted work has attempts and records ---


def test_ac1_every_promoted_work_has_attempt_and_record(
    project: Project, corpus: list[str]
) -> None:
    assert len(corpus) >= 3
    first, late = corpus[0], corpus[1]

    # Pass 1: only the first work is retrieved; every other promoted work gets a reason per route.
    pass_one = fetch_fulltext(project, routes=_routes(html={first}), limit=200)
    assert pass_one.remaining == len(corpus) - 1

    # Pass 2: arXiv HTML now retrieves every remaining work. Works that failed in pass 1 are retried
    # only by `refresh`, since the default selection skips any work that has an attempt.
    pass_two = fetch_fulltext(project, routes=_routes(html=set(corpus)), refresh=True, limit=200)
    assert pass_two.remaining == 0

    attempts = _of_type(project, "fulltext.attempted")
    attempted_works = {e.payload["work_id"] for e in attempts}
    assert set(corpus) <= attempted_works, "every promoted work has at least one attempt"

    # Every retrieved document's attempt carries the acquisition fields.
    for added in _of_type(project, "fulltext.document_added"):
        [attempt] = [e for e in attempts if e.payload["attempt_id"] == added.payload["attempt_id"]]
        payload = attempt.payload
        assert payload["route"] == added.payload["route"]
        assert payload["url"]
        assert payload["source_version"]
        assert payload["source_version"] == added.payload["source_version"]
        # The stub retrieves with no licence, so the licence status is not-reported.
        assert payload["licence_status"] == "not-reported"
        assert payload["retrieved_at"]
        assert payload["raw_hash"] == added.payload["raw_hash"]

    # The first pass's failed works carry a reason for each automatic route.
    pass_one_attempts = [e for e in attempts if e.payload["fetch_id"] == pass_one.fetch_id]
    for work in (late, corpus[2]):
        reasons = {
            e.payload["route"]: e.payload["reason"]
            for e in pass_one_attempts
            if e.payload["work_id"] == work
        }
        assert reasons == {
            Route.ARXIV_HTML: "no arxiv-html",
            Route.ARXIV_SOURCE: "no arxiv-source",
            Route.OA_PDF: "no oa-pdf",
        }


# --- AC 14: a trace from a document reaches its attempt and its work ---


def test_ac14_trace_from_document(project: Project, corpus: list[str]) -> None:
    work = corpus[0]
    summary = fetch_fulltext(project, routes=_routes(html={work}), work_ids=[work])
    [document] = summary.works[0].documents
    [attempt] = summary.works[0].attempts

    tree = trace(project, document, direction="back")

    assert tree.id == document
    assert tree.kind == "document"
    [attempt_node] = tree.children
    assert attempt_node.id == attempt
    assert attempt_node.kind == "attempt"
    [work_node] = attempt_node.children
    assert work_node.id == work
    assert work_node.kind == "work"


# --- AC 15: literature stays out of tracked paths, and deleting it is recoverable ---


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return done.stdout


def test_ac15_no_literature_in_tracked_paths(
    tmp_path: Path, clock: FixedClock, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    shutil.copyfile(REPO_ROOT / ".gitignore", repo / ".gitignore")
    settings = Settings(root=repo, user="obd")
    install_skill(settings, "rf-screen")
    project = init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    _build(project, agent, human, mock_sources)
    promoted = set(_promoted(project))
    [work] = [w for w in list_works(project) if w.id in promoted and w.identifiers.doi][:1]
    doi = work.identifiers.doi or ""

    # The retrieved document comes from a stub route; the researcher's PDF is imported from a
    # folder outside the repository, named by the work's DOI so it matches exactly one work.
    fetch_fulltext(project, routes=_routes(html={work.id}), work_ids=[work.id])
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _pdf(inbox / f"{doi.replace('/', '_')}.pdf", "Body text")
    report = import_folder(project, inbox)
    assert len(report.imported) == 1, report

    library_files = [p for p in (repo / "projects" / "demo" / "library").rglob("*") if p.is_file()]
    assert len(library_files) == 2, "one retrieved document and one imported document"
    for path in library_files:
        rel = path.relative_to(repo).as_posix()
        ignored = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "-q", rel], capture_output=True
        )
        assert ignored.returncode == 0, f"{rel} is not git-ignored"
    ignored_lines = _git(repo, "status", "--porcelain", "--ignored").splitlines()
    assert "!! projects/demo/library/" in ignored_lines

    # Stage what git would track (`.gitignore` applies), then check every tracked file.
    _git(repo, "add", "-A")
    tracked = [repo / rel for rel in _git(repo, "ls-files").splitlines()]
    events_dir = ("projects", "demo", "events")
    assert any(path.relative_to(repo).parts[:3] == events_dir for path in tracked)
    library_root = (repo / "projects" / "demo" / "library").resolve()
    for path in tracked:
        assert library_root not in path.resolve().parents, f"{path.name} is a tracked library file"
        data = path.read_bytes()
        assert CONTENT not in data, f"{path.name} holds the literature content"
        for library_file in library_files:
            assert library_file.read_bytes() not in data, f"{path.name} holds a library file"


def test_ac15_delete_check_restore(project: Project, corpus: list[str]) -> None:
    work = corpus[0]
    summary = fetch_fulltext(project, routes=_routes(html={work}), work_ids=[work])
    [document] = summary.works[0].documents
    [added] = _of_type(project, "fulltext.document_added")
    raw_hash = str(added.payload["raw_hash"])
    status_before = fulltext_status(project).model_dump(mode="json")

    project.library.path(raw_hash).unlink()  # the library is not in git, so it can be lost
    assert not project.library.exists(raw_hash)
    missing = [
        finding
        for finding in check_service.check(project).findings
        if finding.code == "library-missing"
    ]
    assert [finding.refs[0] for finding in missing] == [document]
    assert fulltext_status(project).model_dump(mode="json") == status_before

    restored = restore_document(project, document, routes=_routes(html={work}))

    assert restored == "restored"
    assert project.library.exists(raw_hash)
    assert not [
        finding
        for finding in check_service.check(project).findings
        if finding.code == "library-missing"
    ]


# --- The live arXiv routes, on one stable paper. Deselected by default (network marker). ---


@pytest.mark.network
def test_live_arxiv_html_and_source(tmp_path: Path) -> None:
    http = default_http(Settings(root=tmp_path, user="obd"))
    work = Work.build(
        title="Attention Is All You Need",
        identifiers=Identifiers(arxiv=ARXIV_LIVE),
        provenance=[
            Provenance(
                source="arxiv",
                run_id=f"run_{SESSION}",
                query_id=f"qry_{SESSION}",
                at=T0,
                raw_blob="sha256:" + "0" * 64,
            )
        ],
    )
    try:
        lookup = arxiv_version_lookup(http)
        html = ArxivHtmlRoute(http, lookup=lookup).fetch(work)
        source = ArxivSourceRoute(http, lookup=lookup).fetch(work)
    finally:
        http._http.close()  # PoliteClient has no close(); release the socket pool

    assert html.outcome is AttemptOutcome.RETRIEVED
    assert source.outcome is AttemptOutcome.RETRIEVED
    assert html.source_version is not None
    assert re.fullmatch(rf"{ARXIV_LIVE}v\d+", html.source_version)
    assert html.source_version == source.source_version
    (tmp_path / "html.bin").write_bytes(html.content or b"")
    (tmp_path / "source.bin").write_bytes(source.content or b"")
