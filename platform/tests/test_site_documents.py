"""The "Study documents" hub product (plan flow-transparency, B)."""

from __future__ import annotations

from pathlib import Path

from factory.services.context import Project
from factory.services.site import products
from factory.services.site_documents import build_documents
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
    assert "files/docs__protocol.pdf" in index
    assert (out / "files" / "docs__protocol.pdf").is_symlink()
    rendered = (out / "docs__plan.md.html").read_text(encoding="utf-8")
    assert "registered text" in rendered and "edited after" not in rendered
