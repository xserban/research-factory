"""Lead candidates (hypothesis engine, task 1): observations with the exact lead triggers."""

# ruff: noqa: F811
from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import MinerScope
from factory.model.lead_engine import SOURCES, Candidate
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.extraction import live_rows
from factory.services.lead_candidates import lead_candidates, technique_candidates
from factory.services.technique_graph import Inputs, RawRow, StageInfo, WorkMeta
from tests.claims_helpers import QUOTES
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.lead_engine_helpers import QUOTE, engine_world

KNOBS = {"layer": "all", "technique_min_works": 1}


def _by_source(project: Project, **over: object) -> dict[str, list[Candidate]]:
    result = lead_candidates(project, **{**KNOBS, **over})  # type: ignore[arg-type]
    out: dict[str, list[Candidate]] = {s: [] for s in SOURCES}
    for c in result.candidates:
        out[c.source].append(c)
    return out


def test_every_result_is_labelled_exploratory_and_never_claims_novelty(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    result = lead_candidates(project, **KNOBS)  # type: ignore[arg-type]
    assert (
        result.exploratory and result.klass == "interpretation" and "exploratory" in result.notice
    )
    dumped = result.model_dump_json(by_alias=True)
    assert '"class":"interpretation"' in dumped and '"exploratory":true' in dumped
    assert all("novel" not in c.observation.lower() for c in result.candidates)
    assert all(c.exploratory and c.miners for c in result.candidates)
    assert set(result.totals) == set(SOURCES)


def test_a_challenge_cites_the_live_rows_of_both_sides_as_items_and_works(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = engine_world(project, agent, human, world)
    [challenge] = _by_source(project)["technique-challenge"]
    assert challenge.candidate_id == "technique-challenge:ide-01"
    live = {
        r.extraction_id: r
        for r in live_rows(project, PassLabel.A, scope=MinerScope("m-tech-ideation"))
    }
    items = [t.ref for t in challenge.triggers if t.kind == "item"]
    works = [t.ref for t in challenge.triggers if t.kind == "work"]
    assert {live[i].work_id for i in items} == set(works) == set(ordered[:2])
    assert {t.kind for t in challenge.triggers} == {"item", "work"}
    assert {q.role for q in challenge.quotes} == {"failed", "supported"}
    assert all(q.quote == QUOTE and q.anchor == "s3.p1" for q in challenge.quotes)
    assert [b.extraction_id for b in challenge.basis] == items
    assert "failing by 1 work" in challenge.observation and "exploratory" in challenge.observation
    assert challenge.works_total == 2 and challenge.trigger_note is None


def test_combination_gap_and_claims_candidates(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = engine_world(project, agent, human, world)
    found = _by_source(project)
    combos = {c.candidate_id: c for c in found["technique-combination"]}
    pair = combos["technique-combination:exp-01+ide-02"]
    assert "not co-used in this corpus (exploratory, pass-A rows)" in pair.observation
    assert pair.overlap_works == 0 and pair.score is not None
    assert "technique-combination:ide-01+ide-02" not in combos  # W1 uses both: co-used
    gaps = {c.candidate_id: c for c in found["technique-gap"]}
    gap = gaps["technique-gap:ide-03"]
    assert gap.works_total == 1 and gap.overlap_works == 0 and gap.score is not None
    assert [w.work_id for w in gap.works] == [ordered[1]]
    assert gap.target_stages == ("experiment",) and gap.quotes[0].side == "ide-03"
    assert all(":" not in c.candidate_id.split(":", 1)[1] for c in gaps.values())
    claims = found["claims-limitation"]
    assert [c.quotes[0].quote for c in claims] == [QUOTES[0], QUOTES[1]]
    assert all(c.source == "claims-limitation" and len(c.triggers) == 2 for c in claims)
    assert [c.quotes[0].role for c in claims] == ["limitation", "limitation"]
    rows = {
        r.extraction_id: r.fields["claim_type"].value
        for r in live_rows(project, PassLabel.A, scope=MinerScope("m-claims"))
    }
    cited = {t.ref for c in claims for t in c.triggers if t.kind == "item"}
    assert {rows[i] for i in cited} == {"limitation"}  # no finding, no absence row
    assert lead_candidates(project, **KNOBS).absence_only_works == 1  # type: ignore[arg-type]


def test_the_core_layer_leaves_out_the_applied_work_and_caps_apply(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = engine_world(project, agent, human, world)
    core = lead_candidates(project, technique_min_works=1)
    assert core.candidates and all(
        w.work_id != ordered[2] for c in core.candidates for w in c.works
    )
    assert core.absence_only_works == 0
    capped = lead_candidates(project, **KNOBS, per_source=1)  # type: ignore[arg-type]
    for source in SOURCES:
        assert sum(1 for c in capped.candidates if c.source == source) <= 1
    full = lead_candidates(project, **KNOBS)  # type: ignore[arg-type]
    assert capped.totals == full.totals and capped.totals["technique-combination"] >= 2
    only = lead_candidates(project, sources=("claims-limitation",), **KNOBS)  # type: ignore[arg-type]
    assert {c.source for c in only.candidates} == {"claims-limitation"}
    assert set(only.totals) == {"claims-limitation"}


def test_deterministic_and_boundary_validation(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    a = lead_candidates(project, **KNOBS)  # type: ignore[arg-type]
    b = lead_candidates(project, **KNOBS)  # type: ignore[arg-type]
    assert a.model_dump_json(by_alias=True) == b.model_dump_json(by_alias=True)
    for bad in (
        {"sources": ("nope",)},
        {"sources": ()},
        {"per_source": 0},
        {"technique_min_works": 0},
        {"max_co_works": -1},
    ):
        with pytest.raises(FactoryValidationError) as caught:
            lead_candidates(project, **bad)  # type: ignore[arg-type]
        assert caught.value.issues[0].field == next(iter(bad))


def test_a_project_without_miners_gives_no_candidates_and_says_why(
    project: Project, world: list[str]
) -> None:
    result = lead_candidates(project)
    assert result.candidates == () and result.absence_only_works == 0
    assert [s.candidate_id for s in result.skipped] == ["claims-limitation"]


def test_a_claim_without_a_stored_quote_is_shown_flagged_and_never_quotes_its_value() -> None:
    from factory.services.lead_candidates import _ClaimRow, _Claims, claims_candidates

    def row(ext: str, quote: str | None, field: bool) -> _ClaimRow:
        return _ClaimRow(ext, "W0", f"rk_{ext}", "limitation", "a", quote, "s3.p1", None, field)

    data = _Claims(
        1,
        (row("ext_1", None, True), row("ext_2", "Lorem ipsum.", True), row("ext_3", None, False)),
        {"W0": "Title"},
        {},
    )
    found, total, skipped = claims_candidates(data, per_source=10, layer="all")
    assert total == 3 and [s.candidate_id for s in skipped] == ["claims-limitation:ext_3"]
    by_id = {c.candidate_id: c for c in found}
    bare = by_id["claims-limitation:ext_1"]
    assert bare.quotes[0].quote is None and bare.flags == ("no-stored-quote",)
    assert by_id["claims-limitation:ext_2"].flags == ()


STAGE_LIST = ("ideation", "experiment", "analysis", "other")
CATALOGUE = {
    "ide-a": ("ideation", "Idea A", "Defn."),
    "ide-b": ("ideation", "Idea B", "Defn."),
    "exp-a": ("experiment", "Exp A", "Defn."),
    "exp-b": ("experiment", "Exp B", "Defn."),
}


def _row(work: str, approach: str, evidence: str, n: int = 0) -> RawRow:
    return RawRow(
        approach=approach,
        stage=CATALOGUE[approach][0],
        work_id=work,
        extraction_id=f"ext_{approach}_{work}_{n}",
        status="core",
        evidence=evidence,
        described_as=f"{approach} as described in {work}",
        quote=f"quote {approach} {work}",
        anchor="s1.p1",
        parameters=None,
    )


def _inputs(rows: list[RawRow]) -> Inputs:
    works = sorted({r.work_id for r in rows})
    return Inputs(
        catalogue=CATALOGUE,
        rows=tuple(rows),
        stages=tuple(StageInfo(s, "m", 1, 0, None, None) for s in STAGE_LIST),
        works={w: WorkMeta(f"Title {w}", "2024-01-01", 2024, "core") for w in works},
        cites=(),
    )


def _technique(inputs: Inputs, sources: set[str]) -> tuple[list[Candidate], dict[str, int]]:
    return technique_candidates(
        inputs, sources=sources, per_source=50, layer="all", min_works=3, max_co_works=0
    )


def test_one_gap_candidate_per_approach_lists_every_target_stage_and_never_other() -> None:
    rows = [_row(f"w{i}", "ide-a", "own-ablation") for i in range(3)]
    rows += [_row(f"v{i}", "exp-a", "own-ablation") for i in range(3)]
    found, totals = _technique(_inputs(rows), {"technique-gap"})
    ids = [c.candidate_id for c in found]
    assert ids == sorted(set(ids)) and set(ids) == {"technique-gap:ide-a", "technique-gap:exp-a"}
    assert totals == {"technique-gap": 2}
    by_id = {c.candidate_id: c for c in found}
    assert by_id["technique-gap:ide-a"].target_stages == ("analysis", "experiment")
    assert by_id["technique-gap:exp-a"].target_stages == ("analysis", "ideation")
    for c in found:
        assert "other" not in c.target_stages and "other" not in c.observation.split("row at")[-1]
        assert c.approaches and c.triggers


def test_a_candidate_quotes_every_cited_row_with_side_description_and_evidence() -> None:
    rows = [_row(f"a{i}", "ide-a", "own-ablation") for i in range(7)]
    rows += [_row(f"b{i}", "exp-a", "independent-test") for i in range(7)]
    found, _ = _technique(_inputs(rows), {"technique-combination"})
    [combo] = [c for c in found if c.candidate_id == "technique-combination:exp-a+ide-a"]
    items = [t for t in combo.triggers if t.kind == "item"]
    assert len(items) == 10 and len(combo.quotes) == 10  # a quote for every cited row
    assert {q.extraction_id for q in combo.quotes} == {t.ref for t in items}
    assert {(q.role, q.side) for q in combo.quotes} == {("a", "exp-a"), ("b", "ide-a")} or {
        (q.role, q.side) for q in combo.quotes
    } == {("a", "ide-a"), ("b", "exp-a")}
    for q in combo.quotes:
        assert q.described_as and q.described_as.startswith(q.side or "?")
        assert q.evidence in {"own-ablation", "independent-test"} and q.quote


def test_a_challenge_flags_that_its_failure_quote_was_not_checked() -> None:
    rows = [_row("w0", "ide-a", "reported-failure")]
    rows += [_row(f"w{i}", "ide-a", "own-ablation") for i in range(1, 4)]
    found, _ = _technique(_inputs(rows), {"technique-challenge"})
    [challenge] = found
    assert "failure-quote-not-checked" in challenge.flags
    failed = next(q for q in challenge.quotes if q.role == "failed")
    assert failed.evidence == "reported-failure" and failed.described_as
    assert failed.side == "ide-a"
