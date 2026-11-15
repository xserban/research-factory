"""The "Study documents" hub product (plan flow-transparency, B)."""

from __future__ import annotations

from pathlib import Path

from factory.services.context import Project
from factory.services.site import products
from factory.services.site_documents import _slug, build_documents, documents_stamp
from factory.services.study_files import register_file


def test_product_is_listed_after_flow() -> None:
    ids = [p.id for p in products() if p.group == "Overview"]
    assert ids.index("documents") == ids.index("flow") + 1


def test_markdown_rendered_from_blob_others_linked_status_shown(
    project: Project, tmp_path: Path
) -> None:
    root = project.paths.dir
    (root / "docs").mkdir()
    md = root / "docs" / "plan.md"
    md.write_text("# Plan\n\nregistered text\n", encoding="utf-8")
    (root / "docs" / "protocol.pdf").write_bytes(b"%PDF-1.4")
    (root / "docs" / "gone.txt").write_text("g", encoding="utf-8")
    for rel, kind in (
        ("docs/plan.md", "study-document"),
        ("docs/protocol.pdf", "study-document"),
        ("docs/gone.txt", "other"),
    ):
        register_file(project, rel, kind, None, project.human_actor())
    md.write_text("# Plan\n\nedited after\n", encoding="utf-8")
    (root / "docs" / "gone.txt").unlink()
    out = tmp_path / "site"
    out.mkdir()
    build_documents(project, out)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "changed since registration" in index and "st-missing" in index
    assert f"files/{_slug('docs/protocol.pdf')}" in index
    assert (out / "files" / _slug("docs/protocol.pdf")).is_symlink()
    rendered = (out / f"{_slug('docs/plan.md')}.html").read_text(encoding="utf-8")
    assert "registered text" in rendered and "edited after" not in rendered


def test_slugs_do_not_collide_and_hrefs_are_encoded(project: Project, tmp_path: Path) -> None:
    assert _slug("a/b.md") != _slug("a__b.md")
    root = project.paths.dir
    (root / "a").mkdir()
    (root / "a" / "b c.pdf").write_bytes(b"1")
    (root / "a__b c.pdf").write_bytes(b"2")
    for rel in ("a/b c.pdf", "a__b c.pdf"):
        register_file(project, rel, "other", None, project.human_actor())
    out = tmp_path / "site"
    out.mkdir()
    build_documents(project, out)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "b%20c.pdf" in index and "b c.pdf'" not in index.replace("<div", "")
    assert len(list((out / "files").iterdir())) == 2


def test_file_resolving_outside_the_project_is_not_linked(project: Project, tmp_path: Path) -> None:
    root = project.paths.dir
    inside = root / "docs" / "p.pdf"
    inside.parent.mkdir()
    inside.write_bytes(b"1")
    register_file(project, "docs/p.pdf", "other", None, project.human_actor())
    outer = tmp_path / "elsewhere.pdf"
    outer.write_bytes(b"2")
    inside.unlink()
    inside.symlink_to(outer)
    out = tmp_path / "site"
    out.mkdir()
    build_documents(project, out)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "outside the project" in index
    assert not (out / "files" / _slug("docs/p.pdf")).exists()


def test_stamp_changes_with_the_disk_state(project: Project) -> None:
    path = project.paths.dir / "p.pdf"
    path.write_bytes(b"1")
    register_file(project, "p.pdf", "other", None, project.human_actor())
    before = documents_stamp(project)
    assert documents_stamp(project) == before
    path.write_bytes(b"22")
    changed = documents_stamp(project)
    assert changed != before
    path.unlink()
    assert documents_stamp(project) not in (before, changed)


def test_products_set_a_stamp() -> None:
    by_id = {p.id: p for p in products()}
    assert by_id["documents"].stamp is not None and by_id["runs"].stamp is not None
