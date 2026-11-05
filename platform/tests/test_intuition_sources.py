"""Quote and citation source verification, stale sources (slice 3c, plan G3-A, task 3)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from typing import Any

from factory.events.envelope import Actor
from factory.model.intuition import (
    CitationSourceInput,
    QuoteSourceInput,
    SourceInput,
)
from factory.services.context import Project
from factory.services.fulltext import document_superseded
from factory.services.intuition_sources import (
    SourceVerdict,
    entry_link,
    stale_sources,
    verify_sources,
)
from tests.contribution_helpers import with_references
from tests.intuition_helpers import INT1, live_conversion, record_event, recorded, reviewed
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world

QUOTE = "very long sequences degrade"  # s1.p4 of the source document


def q(work: str, cnv: str, anchor: str = "s1.p4", quote: str = QUOTE) -> SourceInput:
    return QuoteSourceInput(
        kind="quote", role="supports", work_id=work, conversion_id=cnv, anchor=anchor, quote=quote
    )


def c(*, reference: str | None = None, work: str | None = None) -> SourceInput:
    return CitationSourceInput(
        kind="citation", role="background", reference=reference, work_id=work
    )


def reasons(v: SourceVerdict) -> dict[str, str]:
    return {i.field: i.reason for i in v.issues}


def test_verbatim_quote_accepted_and_document_pinned(project: Project, lin: Lineage) -> None:
    cnv, doc = live_conversion(project, lin.source)
    v = verify_sources(project, [q(lin.source, cnv)])
    assert v.issues == [] and v.stored[0].document_id == doc
    assert v.stored[0].quote == QUOTE and v.stored[0].kind == "quote"


def test_non_verbatim_quote_refused_without_text(project: Project, lin: Lineage) -> None:
    cnv, _ = live_conversion(project, lin.source)
    v = verify_sources(project, [q(lin.source, cnv, quote="very long sequences improve")])
    assert reasons(v) == {"sources[0].quote": "quote-not-in-anchor"}
    assert "improve" not in str(v.issues) and "degrade" not in str(v.issues)
    assert v.stored == ()


def test_unknown_anchor_and_unknown_conversion(project: Project, lin: Lineage) -> None:
    cnv, _ = live_conversion(project, lin.source)
    assert reasons(verify_sources(project, [q(lin.source, cnv, anchor="s9.p9")])) == {
        "sources[0].anchor": "anchor-unknown"
    }
    ghost = "cnv_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
    assert reasons(verify_sources(project, [q(lin.source, ghost)])) == {
        "sources[0].conversion_id": "conversion-unknown"
    }


def test_conversion_of_other_work_refused(project: Project, lin: Lineage, world: list[str]) -> None:
    cnv, _ = live_conversion(project, lin.source)
    other = next(w for w in world if w != lin.source)
    assert reasons(verify_sources(project, [q(other, cnv)])) == {
        "sources[0].conversion_id": "conversion-not-of-work"
    }


def test_unknown_work_refused(project: Project, lin: Lineage) -> None:
    cnv, _ = live_conversion(project, lin.source)
    v = verify_sources(project, [q("rf:nobody-00000000", cnv)])
    assert reasons(v) == {"sources[0].work_id": "work-unknown"}


def test_superseded_document_refused_at_write(project: Project, agent: Actor, lin: Lineage) -> None:
    """Review Focus 1: a verbatim quote cited at a conversion of a superseded document."""
    old, old_doc = live_conversion(project, lin.source)
    with_references(project, agent, lin.source, version="v4")
    new, _ = live_conversion(project, lin.source)
    assert new != old and document_superseded(project, old_doc)
    assert reasons(verify_sources(project, [q(lin.source, old)])) == {
        "sources[0].conversion_id": "document-superseded"
    }
    assert verify_sources(project, [q(lin.source, new)]).issues == []


def test_entry_key_stores_link_state(project: Project, lin: Lineage) -> None:
    v = verify_sources(project, [c(reference=f"{lin.rex}:5"), c(reference=f"{lin.rex}:1")])
    assert v.issues == []
    assert v.stored[0].link_state == "resolved" and v.stored[0].resolved_work == lin.target5
    assert v.stored[1].link_state is not None and v.stored[1].reference == f"{lin.rex}:1"
    assert entry_link(project, f"{lin.rex}:5") == ("resolved", lin.target5)
    assert entry_link(project, f"{lin.rex}:99") is None


def test_unresolved_entry_is_accepted_and_labelled(project: Project, lin: Lineage) -> None:
    states = {
        entry_link(project, f"{lin.rex}:{n}")[0]  # type: ignore[index]
        for n in range(1, 7)
        if entry_link(project, f"{lin.rex}:{n}") is not None
    }
    assert "unresolved" in states
    unresolved = next(
        n
        for n in range(1, 7)
        if (entry_link(project, f"{lin.rex}:{n}") or ("",))[0] == "unresolved"
    )
    v = verify_sources(project, [c(reference=f"{lin.rex}:{unresolved}")])
    assert v.issues == [] and v.stored[0].link_state == "unresolved"
    assert v.stored[0].resolved_work is None


def test_entry_unknown_and_extraction_not_live(project: Project, lin: Lineage) -> None:
    assert reasons(verify_sources(project, [c(reference=f"{lin.rex}:99")])) == {
        "sources[0].reference": "entry-unknown"
    }
    ghost = "rex_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
    assert reasons(verify_sources(project, [c(reference=f"{ghost}:1")])) == {
        "sources[0].reference": "extraction-not-live"
    }


def test_citation_of_work_id(project: Project, lin: Lineage) -> None:
    assert verify_sources(project, [c(work=lin.source)]).issues == []
    assert reasons(verify_sources(project, [c(work="rf:nobody-00000000")])) == {
        "sources[0].work_id": "work-unknown"
    }


def test_all_or_nothing_and_all_issues_located(project: Project, lin: Lineage) -> None:
    cnv, _ = live_conversion(project, lin.source)
    good = q(lin.source, cnv)
    bad = q(lin.source, cnv, quote="not in the paragraph")
    v = verify_sources(project, [good, bad, c(reference=f"{lin.rex}:99")])
    assert v.stored == ()
    assert reasons(v) == {
        "sources[1].quote": "quote-not-in-anchor",
        "sources[2].reference": "entry-unknown",
    }
    assert reasons(verify_sources(project, [good], field="x")) == {}


def test_stale_sources_after_new_document_version(
    project: Project, agent: Actor, lin: Lineage
) -> None:
    """Review Focus 1 / acceptance 10: reviewed stays reviewed, the source becomes stale."""
    cnv, doc = live_conversion(project, lin.source)
    source: dict[str, Any] = {
        "kind": "quote",
        "role": "supports",
        "work_id": lin.source,
        "conversion_id": cnv,
        "anchor": "s1.p4",
        "quote": QUOTE,
    }
    payload = recorded(INT1, sources=[source])
    payload["sources"][0]["document_id"] = doc
    record_event(project, "interpretation.recorded", payload, agent)
    record_event(project, "interpretation.reviewed", reviewed(INT1, "reviewed"))
    assert stale_sources(project) == {}
    with_references(project, agent, lin.source, version="v4")
    assert stale_sources(project) == {INT1: (doc,)}
    project.index.sync()
    with project.index.connect() as conn:
        from sqlalchemy import text

        state = conn.execute(text("SELECT review_state FROM interpretations")).scalar_one()
    assert state == "reviewed"
