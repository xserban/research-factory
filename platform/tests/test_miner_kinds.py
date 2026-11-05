"""Field-kind checks on the existing verifiers (M-C, task 3; spec acceptance 10)."""

# ruff: noqa: F811
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy import event as sa_event

from factory.document.anchors import AnchorKind, Manifest
from factory.events.envelope import Actor
from factory.extraction import verify as verify_module
from factory.mining import kinds as kinds_module
from factory.mining.compile import compile_miner
from factory.mining.kinds import (
    ANCHOR_KIND,
    ANCHOR_NOT_FOUND,
    ENTRY_NOT_FOUND,
    ENUM_NEEDS_QUOTE,
    NO_CITATION_MARKER,
    TOO_FEW_QUOTES,
    WORK_NOT_FOUND,
    close_checks,
    entry_link_state,
    kind_checks,
    title_ref,
)
from factory.mining.spec import (
    AnchorKindRef,
    CitationKind,
    EnumKind,
    EvidenceRule,
    MinerField,
    MinerSpec,
    QuoteKind,
    WorkRefKind,
)
from factory.model.extraction import FieldInput, StoredField
from factory.model.seed import SeedKind, SeedSpec
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.document_read import default_conversion
from factory.services.extraction import UnitPin
from factory.services.extraction_verify import verify_row_in
from factory.services.search import list_works
from factory.services.seeds import add_seeds
from tests.contribution_helpers import screened, with_references, world  # noqa: F401
from tests.miner_helpers import vision_result

PARA = ("s3.p1", "Lorem ipsum dolor sit amet.")


def _spec(*extra: MinerField, **over: Any) -> MinerSpec:
    base = vision_result()
    fields = (base.fields[0], base.fields[1], base.fields[2], *extra)
    return replace(base, fields=fields, **over)


def _stored(
    value: str | int,
    anchor: str | None = None,
    quote: str | None = None,
) -> StoredField:
    return StoredField(value=value, anchor=anchor, quote=quote, copy_marker=False)


def _pin(project: Project, work: str) -> UnitPin:
    ref = default_conversion(project, work)
    assert ref is not None
    from factory.model.screening import PassLabel

    return UnitPin("tsk_x", work, PassLabel.A, _scope(), ref.document_id, ref.conversion_id)


def _scope() -> Any:
    from factory.model.extraction import Scope

    return Scope.EVIDENCE


def _reasons(verdict: Any) -> dict[str, str]:
    return {i.field: i.reason for i in verdict.issues}


BASE = {"metric": _stored("Lorem", "s3.p1", "Lorem ipsum"), "value": _stored("1")}


def _run(
    project: Project, work: str, spec: MinerSpec, fields: dict[str, StoredField]
) -> dict[str, str]:
    check = kind_checks(spec)
    return _reasons(check(project, _pin(project, work), {**BASE, **fields}, []))


def test_citation_accepts_a_marker_and_rejects_none(
    project: Project, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(MinerField("cite", "c", CitationKind((r"\[\d+\]",))))
    calls: list[str] = []
    real = kinds_module.citation_markers
    monkeypatch.setattr(
        kinds_module, "citation_markers", lambda t, p: (calls.append(t), real(t, p))[1]
    )
    good = {"cite": _stored("Jones", "b2", "[2] Jones, B.")}
    assert _run(project, world[0], spec, good) == {}
    bad = {"cite": _stored("Jones", "b2", "Jones, B. Dolor")}
    assert _run(project, world[0], spec, bad) == {"fields.cite.quote": NO_CITATION_MARKER}
    assert calls == ["[2] Jones, B.", "Jones, B. Dolor"]


def test_anchor_kind_accepts_listed_kind_and_rejects_others(
    project: Project, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(MinerField("where", "c", AnchorKindRef((AnchorKind.PARAGRAPH,))))
    seen: list[str] = []
    real = Manifest.get
    monkeypatch.setattr(Manifest, "get", lambda self, a: (seen.append(a), real(self, a))[1])
    assert _run(project, world[0], spec, {"where": _stored("s3.p1")}) == {}
    assert _run(project, world[0], spec, {"where": _stored("t1")}) == {
        "fields.where.value": ANCHOR_KIND
    }
    assert _run(project, world[0], spec, {"where": _stored("zz9")}) == {
        "fields.where.value": ANCHOR_NOT_FOUND
    }
    assert seen == ["s3.p1", "t1", "zz9"]


def test_enum_needs_an_evidence_quote(project: Project, world: list[str]) -> None:
    spec = _spec()
    assert _run(project, world[0], spec, {"direction": _stored("higher", "s3.p1", "Lorem")}) == {}
    assert _run(project, world[0], spec, {"direction": _stored("higher")}) == {
        "fields.direction.quote": ENUM_NEEDS_QUOTE
    }
    lax = replace(spec, evidence=EvidenceRule(1, False))
    assert _run(project, world[0], lax, {"direction": _stored("higher")}) == {}


def test_too_few_quotes(project: Project, world: list[str]) -> None:
    spec = _spec(evidence=EvidenceRule(2, True))
    assert _run(project, world[0], spec, {}) == {"fields": TOO_FEW_QUOTES}
    ok = {"direction": _stored("higher", "s3.p1", "Lorem")}
    assert _run(project, world[0], spec, ok) == {}
    close = close_checks(spec)
    row = type("R", (), {"fields": BASE})()
    assert close(project, _pin(project, world[0]), [row], None)[0].reason == TOO_FEW_QUOTES  # type: ignore[list-item]
    assert close(project, _pin(project, world[0]), [], None) == []


def test_quote_and_number_kinds_call_the_plan_d_verifiers(
    project: Project, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec()
    pack = compile_miner(spec)
    ref = default_conversion(project, world[0])
    assert ref is not None
    manifest = conversion_manifest(project, ref.conversion_id)
    quotes: list[str] = []
    numbers: list[str] = []
    real_q, real_n = verify_module.quote_in_element, verify_module.numbers_in
    monkeypatch.setattr(
        verify_module, "quote_in_element", lambda e, q: (quotes.append(q), real_q(e, q))[1]
    )
    monkeypatch.setattr(verify_module, "numbers_in", lambda t: (numbers.append(t), real_n(t))[1])

    def row(quote: str, value: str, cell: str = "t1.r3.c2") -> dict[str, FieldInput]:
        return {
            "metric": FieldInput(value="Lorem", anchor="s3.p1", quote=quote),
            "value": FieldInput(value=value, anchor="t1", cell=cell, quote=value),
        }

    names = [f.name for f in spec.fields]
    good = verify_row_in(pack, names, row("Lorem ipsum", "1"), ref.conversion_id, manifest, set())
    assert good.issues == [] and quotes and numbers
    wrong_quote = verify_row_in(
        pack, names, row("not in the paragraph", "1"), ref.conversion_id, manifest, set()
    )
    assert any(i.reason == "quote-not-in-anchor" for i in wrong_quote.issues)
    wrong_number = verify_row_in(
        pack, names, row("Lorem ipsum", "7"), ref.conversion_id, manifest, set()
    )
    assert any(i.field == "fields.value.quote" or "value" in i.field for i in wrong_number.issues)
    enum = verify_row_in(
        pack,
        names,
        {**row("Lorem ipsum", "1"), "direction": FieldInput(value="sideways")},
        ref.conversion_id,
        manifest,
        set(),
    )
    assert {i.reason for i in enum.issues} == {"value-not-allowed"}


def test_entry_kind_accepts_a_listed_ordinal_and_rejects_an_absent_one(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    work = world[0]
    rex = with_references(project, agent, work)
    spec = _spec(MinerField("cited_entry", "link", WorkRefKind("entry")))
    spy: list[str] = []
    real = kinds_module.current_extraction
    monkeypatch.setattr(
        kinds_module, "current_extraction", lambda p, w: (spy.append(w), real(p, w))[1]
    )
    ok = _run(project, work, spec, {"cited_entry": _stored(5, "s1.p1", "linear attention [5]")})
    assert ok == {}
    check = kind_checks(spec)
    verdict = check(
        project,
        _pin(project, work),
        {**BASE, "cited_entry": _stored(5, "s1.p1", "linear attention [5]")},
        [],
    )
    assert verdict.cited is not None and verdict.cited.reference_extraction_id == rex
    assert verdict.cited.ordinal == 5 and verdict.cited.marker == "matched"
    assert entry_link_state(project, verdict.cited) in ("stated", "inferred")
    assert _run(project, work, spec, {"cited_entry": _stored(99)}) == {
        "fields.cited_entry.value": ENTRY_NOT_FOUND
    }
    assert spy and set(spy) == {work}


def test_title_kind_accepts_exact_and_rejects_unknown(
    project: Project, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT work_id, title_norm, year FROM work_title_buckets "
                "WHERE year IS NOT NULL ORDER BY work_id LIMIT 1"
            )
        ).one()
    work_id, title, year = str(row[0]), str(row[1]), int(row[2])
    spec = _spec(MinerField("ref", "c", WorkRefKind("title")))
    quote = f"{title} ({year})"
    seen: list[str] = []
    real = kinds_module.match_title
    monkeypatch.setattr(
        kinds_module,
        "match_title",
        lambda f, c: (seen.append(f.title or ""), real(f, c))[1],
    )
    found = title_ref(project, title, quote)
    assert found is not None and found.work_id == work_id and found.state == "stated"
    assert _run(project, world[0], spec, {"ref": _stored(title, "s3.p1", quote)}) == {}
    nothing = {"ref": _stored("a title no work has ever carried", "s3.p1", f"x ({year})")}
    assert _run(project, world[0], spec, nothing) == {"fields.ref.value": WORK_NOT_FOUND}
    no_year = {"ref": _stored(title, "s3.p1", title)}
    assert _run(project, world[0], spec, no_year) == {"fields.ref.value": WORK_NOT_FOUND}
    assert title in seen


def test_title_ref_candidate_query_is_bounded(project: Project, world: list[str]) -> None:
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    engine = project.index._engine
    sa_event.listen(engine, "before_cursor_execute", record)
    try:
        title_ref(project, "anything at all", "cited in 2020")
    finally:
        sa_event.remove(engine, "before_cursor_execute", record)
    works = [s for s in statements if "work_title_buckets" in s or "FROM works" in s]
    assert works and all("year BETWEEN" in s for s in works)
    assert not any(s.strip().upper().startswith("SELECT * FROM WORKS") for s in statements)


def test_quote_kind_and_unused_types_are_inert(project: Project, world: list[str]) -> None:
    assert _run(project, world[0], _spec(MinerField("q", "g", QuoteKind())), {}) == {}
    assert isinstance(EnumKind(("a",)), EnumKind)


def test_merged_copies_collapse_to_the_primary(project: Project, world: list[str]) -> None:
    """An arXiv copy and its published copy are one candidate: they resolve, never ambiguous."""
    from factory.model.dedup import DedupMerged
    from factory.model.work_ids import normalize_title
    from tests.extraction_helpers import _record

    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id, title_norm, year FROM work_title_buckets "
                "WHERE year IS NOT NULL AND work_id IN :ids ORDER BY work_id"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": world},
        ).all()
    (first, _, year), (second, second_title, second_year) = rows[0], rows[1]
    assert abs(int(year) - int(second_year)) <= 1
    primary, absorbed = sorted([str(first), str(second)])
    _record(
        project,
        "dedup.merged",
        DedupMerged(
            merge_id="mrg_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
            primary=primary,
            absorbed=(absorbed,),
            rule="test",
            records=2,
        ),
    )
    lo = min(int(year), int(second_year)) - 1
    ids = [c.work_id for c in kinds_module.title_candidates(project, lo, lo + 4)]
    assert absorbed not in ids and primary in ids
    assert ids.count(primary) <= 2  # one candidate per distinct title of the merge
    found = title_ref(project, str(second_title), f"cited ({second_year})")
    assert found is not None and found.work_id == primary
    assert normalize_title(str(second_title))


def test_a_probe_only_work_is_not_a_title_reference(
    project: Project, agent: Actor, mock_sources: Any
) -> None:
    from tests.helpers import openalex_item

    item = openalex_item(
        title="Seed only paper",
        author="Ada Zhou",
        published="2021-01-01",
        openalex_id="W9",
        doi="10.1000/seedonly",
    )
    seed = SeedSpec(kind=SeedKind.POSITIVE, cite="Zhou 2021", doi="10.1000/seedonly")
    add_seeds(project, agent, [seed], sources=mock_sources(openalex=[item]))
    assert list_works(project) == []
    assert len(list_works(project, include_probe=True)) == 1
    assert kinds_module.title_candidates(project, 2020, 2022) == []
    assert title_ref(project, "Seed only paper", "cited in 2021") is None
