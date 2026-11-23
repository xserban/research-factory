"""Plan G1 acceptance (slice 3a, criteria 1, 3-12, 14-16) in one flow on a synthetic,
pilot-shaped fixture: invented bibliographies, scripted lookup sources, no network and no real
literature text. Criterion 2 is the fixture-set scoring test of `test_references_parse.py`.

Flow: extract -> status counts sum -> an ambiguous link proposed by an agent and confirmed by a
human -> backward round (dry run, then real) -> candidates pending -> screened -> a second
round refused by the plan -> a forward round obeying its maximum -> compare -> PRISMA detail and
report rows -> rebuild gives the same state hash -> no document text in events or blobs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.chase import ChaseDirection
from factory.model.protocol import SnowballPlan
from factory.model.references import Decision, Direction, LinkState, Via
from factory.services import snowball
from factory.services.agreement import Outcome, final_outcomes
from factory.services.chase import search_chase
from factory.services.context import Project
from factory.services.methods import methods_report
from factory.services.prisma import prisma_flow, search_report
from factory.services.reference_resolve import decide_reference, entry_digest, entry_text
from factory.services.references import (
    extract_references,
    list_references,
    reference_counts,
)
from factory.services.snowball import plan_round, snowball_compare, snowball_round
from tests.document_helpers import (
    event_bytes,
    events_of_type,
    fetched_document,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.references_service_helpers import Lookups, bib_html, oa_item
from tests.test_snowball_compare import CHASED, CITING, REED, _pending, _screen
from tests.test_snowball_round import LATTICE, _amend

pytestmark = pytest.mark.slow

MOSS_1 = oa_item("Moss growth under filtered light", "Pia Ostrander", 2008, "W502")
MOSS_2 = oa_item("Moss growth under filtered lights", "Pia Ostrander", 2008, "W503")
ENTRIES_A = [
    "A. Zhou. Paper 2. Journal of Tests, 2020. doi:10.1000/p2.",
    "A. Quillfeather. A lattice is worth sixteen tokens. arXiv:2010.99999v2, 2020.",
    "R. Thornbury. Sparse kernels for tidal data. Imaginary Methods, 2019. doi:10.5555/jim.4.",
    "B. Lee. Efficient reed transformers. Reed Conference, 2021.",
    "P. Ostrander. Moss growth under filtered light v2. Bryology Today, 2008.",
]
BODY_A = ["Prior work {cite:1}, {cite:2} and {cite:3}; see {cite:4} and {cite:5}."]
ENTRIES_B = ["A. Quillfeather. A lattice is worth sixteen tokens. arXiv:2010.99999, 2020."]
BODY_B = ["As in {cite:1}."]
RULE = SnowballPlan(max_backward_rounds=1, max_forward_rounds=1)


def _sources() -> Any:
    lookups = Lookups(
        openalex=[REED, MOSS_1, MOSS_2],
        arxiv={"2010.99999": LATTICE},
        citing=[CITING],
        cited=[REED, CHASED],
    )
    return lookups.sources()


def _fields(error: FactoryValidationError) -> list[str]:
    return [issue.field for issue in error.issues]


def _item(project: Project, state: LinkState) -> Any:
    page = list_references(project, state=state, work_id=None, after=0, limit=100)
    return page.items[0]


def test_references_and_snowballing_end_to_end(
    project: Project, corpus: None, agent: Actor, human: Actor
) -> None:
    work_a, work_b = promoted_works(project)[:2]
    fetched_document(project, work_a, bib_html(ENTRIES_A, BODY_A))
    fetched_document(project, work_b, bib_html(ENTRIES_B, BODY_B))
    run_convert(project, make_registry())

    # Extraction (criteria 3, 4, 7): every entry has a link; the four states sum to the entries.
    summary = extract_references(project, agent, None, sources=_sources())
    assert len(summary.extractions) == 2 and summary.skipped == []
    counts = reference_counts(project)
    assert counts.entries == len(ENTRIES_A) + len(ENTRIES_B)
    assert counts.resolved + counts.unconfirmed + counts.ambiguous + counts.unresolved == (
        counts.entries
    )
    assert counts.ambiguous == 1 and counts.no_source_record >= 1
    again = extract_references(project, agent, None, sources=_sources())
    assert again.extractions == []  # nothing new: the extractions are current

    # An ambiguous link: an agent proposes, a human confirms (criterion 6).
    ambiguous = _item(project, LinkState.AMBIGUOUS)
    chosen = ambiguous.candidates[0][0]
    quotes = ("Moss growth under filtered light", "Moss growth under filtered light")
    decide_reference(
        project,
        agent,
        ambiguous.extraction_id,
        ambiguous.ordinal,
        Decision.PROPOSE_CONFIRM,
        rationale="Same title and year; the entry adds a version suffix.",
        quotes=quotes,
        work_id=chosen,
    )
    assert _item(project, LinkState.AMBIGUOUS).proposal is not None
    with pytest.raises(FactoryValidationError):
        decide_reference(
            project,
            agent,
            ambiguous.extraction_id,
            ambiguous.ordinal,
            Decision.CONFIRM,
            rationale="An agent may not confirm.",
            quotes=quotes,
            work_id=chosen,
        )
    decide_reference(
        project,
        human,
        ambiguous.extraction_id,
        ambiguous.ordinal,
        Decision.CONFIRM,
        rationale="Checked against the entry.",
        quotes=quotes,
        work_id=chosen,
    )
    page = list_references(project, state=LinkState.RESOLVED, work_id=None, after=0, limit=100)
    decided = next(i for i in page.items if i.ordinal == ambiguous.ordinal)
    assert decided.work_id == chosen and decided.confirmed_by == "human"

    # Backward round (criteria 8, 9): the dry run writes nothing; the real round is recorded
    # first, its candidates are pending and never included.
    before_amendment = event_bytes(project)
    assert not plan_round(project, Direction.BACKWARD).state.allowed  # no stopping rule yet
    assert event_bytes(project) == before_amendment
    _amend(project, agent, RULE)
    before = event_bytes(project)
    dry = snowball_round(project, agent, Direction.BACKWARD, sources=_sources())
    assert dry.dry_run and dry.round_id is None and dry.state.allowed and dry.candidates
    assert event_bytes(project) == before
    result = snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert result.round_id is not None and result.new_works > 0
    ledger_index = [e.type for e in events_of_type(project, "snowball.round_started")]
    assert ledger_index == ["snowball.round_started"]
    pending = _pending(project)
    assert len(pending) == result.new_works
    assert all(final_outcomes(project)[w] is Outcome.PENDING for w in pending)

    # Pending candidates block a further round; once screened, the plan's maximum does (9).
    blocked = plan_round(project, Direction.BACKWARD).state
    assert not blocked.allowed and "screening" in [i.field for i in blocked.refusals]
    _screen(project, agent, dict.fromkeys(pending, "include"))
    refused = plan_round(project, Direction.BACKWARD).state
    assert not refused.allowed and "round_no" in [i.field for i in refused.refusals]
    before = event_bytes(project)
    with pytest.raises(FactoryValidationError) as raised:
        snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert "round_no" in _fields(raised.value)
    assert event_bytes(project) == before

    # Forward round (criterion 10): delegated, via source metadata, obeys its own maximum.
    forward = snowball_round(project, agent, Direction.FORWARD, sources=_sources(), dry_run=False)
    assert forward.round_id is not None and forward.chase_round_id is not None
    assert forward.new_works == 1
    ledger = {
        e.payload["round_id"]: e.payload for e in events_of_type(project, "snowball.round_started")
    }
    assert ledger[forward.round_id]["via"] == Via.SOURCE_METADATA.value
    _screen(project, agent, dict.fromkeys(_pending(project), "include"))
    assert [i.field for i in plan_round(project, Direction.FORWARD).state.refusals] == ["round_no"]

    # Comparison (criterion 11): the document list against a backward metadata chase.
    search_chase(project, agent, [ChaseDirection.BACKWARD], sources=_sources())
    _screen(project, agent, dict.fromkeys(_pending(project), "include"))
    comparison = snowball_compare(project, result.round_id)
    reed = next(c.work_id for c in result.candidates if c.openalex == "W501")
    assert reed in comparison.both
    assert set(comparison.document_only).isdisjoint(comparison.both)
    assert comparison.document_only  # e.g. the entry without a source record
    with pytest.raises(FactoryValidationError):
        snowball_compare(project, forward.round_id)  # only backward rounds are compared

    # PRISMA and the search report (criterion 12): derived from events, summing to slice 1.
    flow = prisma_flow(project)
    assert flow.identified_other_detail["snowball-backward"] == result.new_works
    assert sum(flow.identified_other_detail.values()) == flow.identified_other["citation-chase"]
    rows = [r for r in search_report(project).rows if r.round_id == result.round_id]
    assert rows and all(r.direction is Direction.BACKWARD for r in rows)
    assert sum(r.new_after_dedup or 0 for r in rows) == result.new_works
    assert sum(r.included or 0 for r in rows) == result.new_works
    methods = methods_report(project)
    assert methods.snowball_rounds and methods.reference_entries == counts.entries

    # Rebuild (criterion 15).
    state_hash = project.index.state_hash()
    assert project.index.rebuild() == state_hash

    # Local library (criterion 16): no raw entry or paragraph text in any event or blob, and
    # every entry's hash re-derives from the pinned conversion.
    stored = "\n".join(
        p.read_text("utf-8", errors="ignore")
        for root in (project.paths.events_dir, project.paths.blobs_dir)
        for p in sorted(Path(root).rglob("*"))
        if p.is_file()
    )
    for text in (*ENTRIES_A, *ENTRIES_B, *(p.replace("{cite:", "[") for p in BODY_A)):
        assert text not in stored
    for event in events_of_type(project, "reference.extracted"):
        entries = event.payload["entries"]
        assert isinstance(entries, list)
        for entry in entries:
            ordinal = entry["ordinal"]
            raw = entry_text(project, str(event.payload["extraction_id"]), ordinal)
            assert entry_digest(raw) == entry["entry_sha256"]
    assert "found_by" not in json.dumps(
        [e.payload for e in events_of_type(project, "snowball.round_started")]
    )


def test_unknown_round_id_writes_nothing(project: Project, corpus: None) -> None:
    before = event_bytes(project)
    for call in (snowball_compare, snowball.round_yield, snowball.query_yields):
        with pytest.raises(FactoryValidationError) as raised:
            call(project, "snw_01JZ9Q3K5M7N8P0R2S4T6V8W1Z")
        assert _fields(raised.value) == ["round_id"]
    assert event_bytes(project) == before


def test_round_whose_queries_failed_to_register_is_noted_not_stopped(
    project: Project, corpus: None, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_a = promoted_works(project)[0]
    fetched_document(project, work_a, bib_html(ENTRIES_A, BODY_A))
    run_convert(project, make_registry())
    extract_references(project, agent, None, sources=_sources())
    _amend(project, agent, SnowballPlan(max_backward_rounds=2, max_forward_rounds=1))

    def down(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("scripted crash")

    with monkeypatch.context() as patch:
        patch.setattr(snowball, "register_query", down)
        with pytest.raises(RuntimeError):
            snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    state = plan_round(project, Direction.BACKWARD).state
    assert "previous_round" not in [i.field for i in state.refusals]
    assert any("only 0 of" in note and "queries ran" in note for note in state.notes), state.notes


def test_matcher_thresholds_on_fixture_titles() -> None:
    """Step 1b: the ruling-16 constants against the hand-checked fixture titles. Each title
    scores 1.0 with itself; the nearest *different* title must stay below the floor, or a
    distinct paper would be proposed as a match. Scores are printed (run with -s)."""
    from factory.references.match import TITLE_FLOOR, TITLE_FUZZY, title_score

    path = Path(__file__).parent / "fixtures" / "references" / "entries.json"
    titles = sorted({str(c["title"]) for c in json.loads(path.read_text("utf-8")) if c["title"]})
    assert len(titles) >= 5
    nearest = 0.0
    for title in titles:
        assert title_score(title, title) == 1.0
        best = max(title_score(title, other) for other in titles if other != title)
        nearest = max(nearest, best)
        print(f"{best:.3f} nearest distinct to {title!r}")
    print(f"thresholds: fuzzy {TITLE_FUZZY}, floor {TITLE_FLOOR}; highest distinct {nearest:.3f}")
    assert nearest < TITLE_FLOOR
