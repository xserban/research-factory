"""Hub "Why this number?" adapter (plan hub-ui, step 8): figure ids to trace chains."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.extraction import ExtractedRowInput, FieldInput
from factory.model.screening import PassLabel
from factory.services import hub_trace as ht
from factory.services.context import Project
from factory.services.mining import register_miner  # noqa: F401
from factory.services.protocol import current_protocol
from factory.services.search import list_works
from factory.sources.registry import SourceFactory
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import _setup
from tests.miner_helpers import (
    SESSION_M1,
    SESSION_M2,
    VISION_NAME,
    list_miner,
    mine_pass,
    mine_row,
    miner_actor,
)
from tests.screening_helpers import _decide

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _screened(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> tuple[str, str, str]:
    protocol_id = _setup(project, agent, human, mock_sources, random_works=0)
    first, second = sorted(w.id for w in list_works(project))[:2]
    decision = _decide(project, agent, first, "A", "screening", "exclude", "EX01", protocol_id)
    _decide(project, agent, second, "A", "screening", "exclude", "EX02", protocol_id)
    return protocol_id, first, decision


def _events(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def test_excluded_criterion_lists_its_decisions(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, _first, decision = _screened(project, agent, human, mock_sources)
    view = ht.trace_figure(project, "prisma.excluded.EX01")
    assert view.ref == f"{protocol_id}:EX01" and view.direction == "forward"
    assert view.entries[0].kind == "criterion" and view.entries[0].depth == 0
    assert view.decisions == (decision,)
    entry = next(e for e in view.entries if e.id == decision)
    assert entry.event_type == "screening.decision_recorded"
    assert entry.actor_kind == "agent" and entry.model and entry.ts
    json.dumps(view.to_payload())


def test_prisma_figures_walk_the_protocol(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, *_ = _screened(project, agent, human, mock_sources)
    for figure in ("prisma.screened", "prisma.included"):
        view = ht.trace_figure(project, figure)
        assert view.ref == protocol_id and view.total >= 2
        assert view.entries[0].kind == "protocol"
        assert any(e.kind == "criterion" for e in view.entries)


def test_work_screening_keeps_decisions_and_criteria(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _protocol_id, first, decision = _screened(project, agent, human, mock_sources)
    view = ht.trace_figure(project, f"work.{first}.screening")
    assert view.ref == first and view.decisions == (decision,)
    kinds = {e.kind for e in view.entries[1:]}
    assert kinds <= ht.SCREENING_KINDS and "decision" in kinds
    assert view.entries[0].kind == "work"


def test_paging_counts_the_rest(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _screened(project, agent, human, mock_sources)
    full = ht.trace_figure(project, "prisma.screened", limit=ht.MAX_PAGE)
    assert full.rest == 0 and len(full.entries) == full.total
    first = ht.trace_figure(project, "prisma.screened", limit=2)
    assert len(first.entries) == 2 and first.rest == full.total - 2 and first.total == full.total
    second = ht.trace_figure(project, "prisma.screened", offset=2, limit=2)
    assert [e.id for e in second.entries] == [e.id for e in full.entries[2:4]]
    past = ht.trace_figure(project, "prisma.screened", offset=full.total + 5)
    assert past.entries == () and past.rest == 0
    # the lists of decisions and works cover the whole chain, not only the page
    assert first.decisions == full.decisions and first.works == full.works


@pytest.mark.parametrize(
    "figure",
    [
        "",
        "nonsense",
        "prisma.included.extra",
        "prisma.excluded.EX99",
        "prisma.excluded.ex01",
        "work.rf:nope.screening",
        "work.rf:nope.field.m-x.metric",
        "work..screening",
    ],
)
def test_unknown_figure_refused_with_nothing_written(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, figure: str
) -> None:
    _screened(project, agent, human, mock_sources)
    before = _events(project)
    with pytest.raises(FactoryValidationError) as raised:
        ht.trace_figure(project, figure)
    assert raised.value.issues[0].field == "figure_id"
    assert _events(project) == before


def test_bad_page_arguments_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        ht.trace_figure(project, "prisma.screened", offset=-1)
    assert raised.value.issues[0].field == "offset"
    with pytest.raises(FactoryValidationError) as raised:
        ht.trace_figure(project, "prisma.screened", limit=0)
    assert raised.value.issues[0].field == "limit"


def test_protocol_figures_refused_before_a_protocol(project: Project) -> None:
    assert current_protocol(project) is None
    for figure in ("prisma.screened", "prisma.excluded.EX01"):
        with pytest.raises(FactoryValidationError) as raised:
            ht.trace_figure(project, figure)
        assert raised.value.issues[0].field == "figure_id"


def test_mined_field_traces_back_to_its_row(
    project: Project,
    agent: Actor,
    world: list[str],  # noqa: F811
) -> None:
    list_miner(project, agent)
    mina = miner_actor(SESSION_M1, "claude-opus-5-5")
    worked = mine_pass(project, mina, PassLabel.A, lambda w: [mine_row()])
    figure = f"work.{worked[0]}.field.{VISION_NAME}.metric"
    view = ht.trace_figure(project, figure)
    assert view.direction == "back" and view.entries[0].kind == "extraction"
    assert view.entries[0].event_type is not None
    assert worked[0] in view.works
    with pytest.raises(FactoryValidationError) as raised:
        ht.trace_figure(project, f"work.{worked[0]}.field.{VISION_NAME}.nofield")
    assert raised.value.issues[0].field == "figure_id"


def _second_row() -> ExtractedRowInput:
    """A full row at the next cell of the fixture table, so it does not collide with `mine_row`."""
    fields = dict(mine_row().fields)
    fields["metric"] = FieldInput(value="Lorem ipsum", anchor="s3.p1", quote="Lorem ipsum")
    return ExtractedRowInput(fields=fields)


def _row(*without: str) -> ExtractedRowInput:
    """The fixture row without the named fields (so that row has no cell of them)."""
    return ExtractedRowInput(
        fields={k: v for k, v in mine_row().fields.items() if k not in without}
    )


def _row_ids(project: Project, work: str, label: str) -> list[str]:
    with project.index.connect() as conn:
        return [
            str(e)
            for (e,) in conn.execute(
                text(
                    "SELECT extraction_id FROM extraction_rows WHERE work_id = :w "
                    "AND pass_label = :p AND superseded_by IS NULL ORDER BY extraction_id"
                ),
                {"w": work, "p": label},
            )
        ]


def test_field_traces_the_first_non_empty_pass_a_cell(
    project: Project,
    agent: Actor,
    world: list[str],  # noqa: F811
) -> None:
    list_miner(project, agent)
    mina = miner_actor(SESSION_M1, "claude-opus-5-5")
    worked = mine_pass(project, mina, PassLabel.A, lambda w: [_row("direction"), _second_row()])
    work = worked[0]
    first, second = _row_ids(project, work, "A")[:2]
    view = ht.trace_figure(project, f"work.{work}.field.{VISION_NAME}.direction")
    assert view.entries[0].id == second != first  # the empty cell is skipped
    view = ht.trace_figure(project, f"work.{work}.field.{VISION_NAME}.metric")
    assert view.entries[0].id == first  # extraction id order, first non-empty


def test_field_ignores_pass_b_rows(
    project: Project,
    agent: Actor,
    world: list[str],  # noqa: F811
) -> None:
    list_miner(project, agent)
    mina = miner_actor(SESSION_M1, "claude-opus-5-5")
    worked = mine_pass(project, mina, PassLabel.A, lambda w: [_row("direction")])
    minb = miner_actor(SESSION_M2, "claude-sonnet-5-5")
    mine_pass(project, minb, PassLabel.B, lambda w: [_row()])
    figure = f"work.{worked[0]}.field.{VISION_NAME}.direction"
    assert _row_ids(project, worked[0], "B")  # a pass-B row with the value exists
    with pytest.raises(FactoryValidationError):
        ht.trace_figure(project, figure)


def test_field_of_a_duplicate_mapped_work_traces_the_duplicates_row(
    project: Project,
    agent: Actor,
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_miner(project, agent)
    mina = miner_actor(SESSION_M1, "claude-opus-5-5")
    works = sorted(world)
    canonical, dup = works[0], works[1]
    mine_pass(project, mina, PassLabel.A, lambda w: [mine_row()] if w == dup else [])
    monkeypatch.setattr(
        ht, "active_merges", lambda _p: [SimpleNamespace(primary=canonical, absorbed=[dup])]
    )
    view = ht.trace_figure(project, f"work.{canonical}.field.{VISION_NAME}.metric")
    assert view.entries[0].id in _row_ids(project, dup, "A")
    assert dup in view.title and "duplicate" in view.title


def _insert_decision(
    project: Project, protocol_id: str, did: str, stage: str, verdict: str
) -> None:
    with project.index._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO decisions (decision_id, work_id, pass_label, phase, stage, verdict, "
                "quote, rationale, protocol_id, task_id, event_id) VALUES (:d, 'w', 'A', "
                "'screening', :s, :v, 'q', 'r', :p, 't', 'e')"
            ),
            {"d": did, "s": stage, "v": verdict, "p": protocol_id},
        )


def test_prisma_figures_narrow_their_decisions(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, _first, decision = _screened(project, agent, human, mock_sources)
    shown = ht.trace_figure(project, "prisma.screened", limit=ht.MAX_PAGE)
    assert decision in shown.decisions and len(shown.decisions) == 2
    # no full-text decision: the title/abstract includes are the included figure; none here
    assert ht.trace_figure(project, "prisma.included", limit=ht.MAX_PAGE).decisions == ()
    _insert_decision(project, protocol_id, "dec_ta_in", "title-abstract", "include")
    _insert_decision(project, protocol_id, "dec_ft_in", "full-text", "include")
    _insert_decision(project, protocol_id, "dec_ft_out", "full-text", "exclude")
    shown = ht.trace_figure(project, "prisma.screened", limit=ht.MAX_PAGE)
    assert "dec_ta_in" in shown.decisions and "dec_ft_in" not in shown.decisions
    included = ht.trace_figure(project, "prisma.included", limit=ht.MAX_PAGE)
    assert included.decisions == ("dec_ft_in",)
    assert "full-text include" in included.title
