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
from factory.services.lead_candidates import lead_candidates
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
    gap = gaps["technique-gap:ide-03:ideation>experiment"]
    assert gap.works_total == 1 and gap.overlap_works == 0 and gap.score is not None
    assert [w.work_id for w in gap.works] == [ordered[1]]
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
