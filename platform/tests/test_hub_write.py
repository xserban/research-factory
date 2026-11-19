"""Hub `write` payload: Markdown blocks, scope coverage, bibliography, PRISMA SVG, wiki."""

from __future__ import annotations

import re
from typing import Any

import pytest

from factory.events.envelope import Actor
from factory.services import hub_build as hb
from factory.services import hub_write as hw
from factory.services.context import Project
from factory.services.site_corpus import corpus_payload
from tests.test_hub_build import world  # noqa: F401  (fixture)
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)


def test_blocks_cut_headings_paragraphs_lists_bold_and_citations() -> None:
    body = "# T\n\nA **bold** claim [[works/a-1]] ends.\n\n- one [[works/b-2|alias]]\n- two\n\n## S"
    blocks = hw.markdown_blocks(body)
    assert [b["k"] for b in blocks] == ["h", "p", "ul", "h"]
    assert blocks[0]["level"] == 1 and blocks[3]["level"] == 2
    assert blocks[1]["parts"] == [
        {"t": "A "},
        {"b": "bold"},
        {"t": " claim "},
        {"cite": "a-1"},
        {"t": " ends."},
    ]
    assert blocks[2]["items"][0] == [{"t": "one "}, {"cite": "b-2"}]
    assert hw._cites_of(blocks) == ["a-1", "b-2"]


def test_blocks_never_emit_html() -> None:
    blocks = hw.markdown_blocks("<script>x</script> **<b>**")
    assert blocks[0]["parts"][0] == {"t": "<script>x</script> "}


def test_deeper_headings_are_capped_at_three() -> None:
    assert hw.markdown_blocks("##### deep")[0]["level"] == 3


def test_payload_sections_and_methods(world: Project) -> None:  # noqa: F811
    out = hw.build(hb.HubContext(world))
    assert out["ready"] is True
    assert set(out["methods"]) == {"pages", "scopes", "coverage", "bibliography", "prisma", "wiki"}
    assert out["errors"] == {}
    assert out["pages"] == []  # nothing recorded in the fixture


def test_bibliography_entries_match_bibtex_and_histogram(world: Project) -> None:  # noqa: F811
    ctx = hb.HubContext(world)
    bib = hw.build(ctx)["bibliography"]
    assert bib["count"] == len(bib["entries"]) == len(re.findall(r"^@", bib["bibtex"], re.M))
    assert bib["filename"] == "references.bib"
    dated = sum(1 for e in bib["entries"] if e["year"].isdigit())
    assert sum(y["n"] for y in bib["years"]) == dated
    assert dated + bib["undated"] == bib["count"]
    assert [y["year"] for y in bib["years"]] == sorted(y["year"] for y in bib["years"])
    included = set(ctx.included)
    assert all(e["id"] in included | {""} for e in bib["entries"])


def test_prisma_svg_is_the_export_of_the_flow(world: Project) -> None:  # noqa: F811
    from factory.services.exports import export_prisma_svg

    prisma = hw.build(hb.HubContext(world))["prisma"]
    export = export_prisma_svg(world)
    assert prisma["svg_file"] == export  # the download is the export, byte for byte
    assert prisma["svg"] == export.split("?>", 1)[1].lstrip()  # inline: no XML prolog
    assert prisma["svg"].startswith("<svg") and prisma["filename"] == "prisma.svg"


def test_wiki_pointer_names_the_vault_and_its_state(world: Project) -> None:  # noqa: F811
    wiki = hw.build(hb.HubContext(world))["wiki"]
    assert wiki["path"].endswith("/wiki") and wiki["start"] == "index.md"
    assert wiki["built"] is False
    assert wiki["works"] == len(corpus_payload(world)["works"])


def test_scopes_tally_equals_rows_and_overview_comes_first(world: Project) -> None:  # noqa: F811
    out = hw.build(hb.HubContext(world))
    rows, cov = out["scopes"], out["coverage"]
    assert cov["total"] == len(rows) == sum(cov["tally"].values())
    if rows:
        assert rows[0]["scope"] == "overview" and rows[0]["works"] == len(
            corpus_payload(world)["works"]
        )
    assert all(r["state"] == "none" for r in rows)


def test_a_recorded_page_is_listed_read_with_resolved_citations(
    world: Project,  # noqa: F811
    agent: Actor,
) -> None:
    from factory.services.pages import record_page

    works: list[dict[str, Any]] = corpus_payload(world)["works"]
    if not works:
        pytest.skip("the fixture has no coded work to cite")
    slug = works[0]["slug"]
    record_page(world, agent, "overview", "Overview", f"# Overview\n\nA note [[works/{slug}]].")
    out = hw.build(hb.HubContext(world))
    (page,) = out["pages"]
    assert page["scope"] == "overview" and page["state"] in {"checked", "flagged"}
    assert page["blocks"][0]["k"] == "h"
    assert set(page["cites"]) <= {slug}
    overview = next(r for r in out["scopes"] if r["scope"] == "overview")
    assert overview["page_id"] == page["page_id"] and overview["state"] == page["state"]
    assert out["coverage"]["tally"]["none"] == out["coverage"]["total"] - 1


def test_a_failing_section_is_reported_and_the_others_survive(
    world: Project,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_ctx: object) -> dict[str, Any]:
        raise RuntimeError("no svg")

    monkeypatch.setattr(hw, "_prisma_section", boom)
    out = hw.build(hb.HubContext(world))
    assert out["errors"] == {"prisma": "no svg"} and out["prisma"] is None
    assert out["bibliography"] is not None and out["wiki"] is not None
