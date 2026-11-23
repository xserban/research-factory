"""Researcher hints at capture and the origin tag (IDEA-81): model, capture, projection, staleness,
origin, agreement, the miner option and the screening blinding."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mining.derive import derive_miner
from factory.mining.spec import MinerRegime, Selector, spec_to_json
from factory.mining.spec import Population as MinerPopulation
from factory.mining.taxonomy import Dimension, TaxonomySpec, taxonomy_to_json
from factory.model.inbox import CaptureHints, InboxLinkAdded, InboxLinkResolved, ResolveStatus
from factory.model.miners import MinerUse
from factory.model.protocol import TaxonomyUse
from factory.model.references import LayerDef, LayerSchemeRecorded
from factory.model.screening import Channel, PassLabel
from factory.services.capture_hints import (
    CaptureHint,
    _category_report,
    _layer_report,
    hint_context_text,
    hint_informed_miners,
    hint_staleness,
    hints_by_work,
    origin_matches,
    origins_of,
)
from factory.services.context import Project
from factory.services.feed import add
from factory.services.hint_input import HintInput
from factory.services.inbox import LinkInput, add_links
from factory.services.mining import miner_population, population, register_miner
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.reference_layers import record_scheme
from factory.services.screening import screen_next
from factory.services.tasks import complete_task
from factory.services.taxonomies import register_taxonomy
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.helpers import SourcesFor, _setup
from tests.inbox_helpers import KNOWLEDGE
from tests.miner_helpers import VISION_NAME, method_vision, use
from tests.screening_helpers import _draw
from tests.test_feed_add import _keyed, _world

MARK = "zz-hint-marker-4417"


@pytest.fixture
def capturer() -> Actor:
    """A human whose session joined no pass (the `world` fixtures' sessions did)."""
    return Actor(kind="human", id="obd", user="obd", session="01JZ9Q3K5M7N8P0R2S4T6V8W2A")


def _scheme(version: int = 1) -> LayerSchemeRecorded:
    def layer(i: str, ring: int) -> LayerDef:
        return LayerDef(id=i, ring=ring, snowball=ring == 0, name=i, criteria=f"criteria of {i}")

    return LayerSchemeRecorded(version=version, layers=(layer("core", 0), layer("applied", 1)))


def _layer_taxonomy() -> TaxonomySpec:
    return TaxonomySpec(
        name="t-lay",
        version=1,
        dimensions=(Dimension("layer", "Layer", "Which layer?", "single", (), layer_scheme=1),),
    )


def _items(project: Project, actor: Actor, *hints: HintInput | None) -> list[str]:
    links = [LinkInput(f"10.2000/h{i}", note=None, hints=h) for i, h in enumerate(hints)]
    result = add_links(project, actor, links, Channel.CLI)
    assert result.rejected == [], result.rejected
    return result.written


def _resolve_to(project: Project, actor: Actor, item_id: str, work_id: str) -> None:
    payload = InboxLinkResolved(
        item_id=item_id,
        query_id=project.ids.new("qry"),
        run_id=project.ids.new("run"),
        status=ResolveStatus.IN_CORPUS,
        work_id=work_id,
    )
    project.record([project.events.make("inbox.link_resolved", payload, actor, refs=(item_id,))])


def _added(project: Project) -> list[dict[str, object]]:
    return [
        dict(e.payload)
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "inbox.link_added"
    ]


# --- model ---


def test_hints_need_something_and_consistent_versions() -> None:
    with pytest.raises(ValidationError):
        CaptureHints()
    with pytest.raises(ValidationError):
        CaptureHints(layer="core")
    with pytest.raises(ValidationError):
        CaptureHints(category="layer/core", taxonomy="t-lay")
    assert CaptureHints(miner_notes="a benchmark").miner_notes == "a benchmark"
    ok = CaptureHints(layer="core", scheme_version=1)
    assert ok.layer == "core"


def test_an_event_without_hints_serialises_as_before() -> None:
    base = {
        "item_id": "inb_01JZ9Q3K5M7N8P0R2S4T6V8W1E",
        "route": "link",
        "link": "10.1/x",
        "identifier_kind": "doi",
        "identifier_value": "10.1/x",
        "channel": "cli",
    }
    payload = InboxLinkAdded.model_validate(base)
    assert "hints" not in payload.model_dump(mode="json")
    again = InboxLinkAdded.model_validate({**base, "hints": {"miner_notes": "x"}})
    assert again.model_dump(mode="json")["hints"]["miner_notes"] == "x"


def test_a_miner_use_omits_its_defaults_and_checks_origins() -> None:
    plain = MinerUse.model_validate({"name": "m-a", "version": 1})
    dumped = plain.model_dump(mode="json")
    assert "origins" not in dumped and "hint_context" not in dumped
    assert plain.hint_context is False
    on = MinerUse.model_validate(
        {"name": "m-a", "version": 1, "origins": ["inbox", "feed:cli"], "hint_context": True}
    )
    assert on.model_dump(mode="json")["origins"] == ["inbox", "feed:cli"]
    with pytest.raises(ValidationError):
        MinerUse.model_validate({"name": "m-a", "version": 1, "origins": ["search"]})


# --- capture ---


def test_hints_are_recorded_with_the_scheme_version(
    project: Project, other_session_human: Actor
) -> None:
    record_scheme(project, other_session_human, _scheme())
    [item] = _items(
        project, other_session_human, HintInput(layer="core", miner_notes="  a benchmark ")
    )
    [payload] = _added(project)
    hints = payload["hints"]
    assert isinstance(hints, dict)
    assert hints["layer"] == "core" and hints["scheme_version"] == 1
    assert hints["miner_notes"] == "a benchmark"
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT layer, scheme_version, miner_notes FROM inbox_hints WHERE item_id = :i"),
            {"i": item},
        ).one()
    assert tuple(row) == ("core", 1, "a benchmark")


def test_a_capture_without_hints_writes_no_hints_key(
    project: Project, other_session_human: Actor
) -> None:
    _items(project, other_session_human, None, HintInput())
    assert all("hints" not in p for p in _added(project))
    with project.index.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM inbox_hints")).scalar() == 0


def test_invalid_hints_write_nothing(
    project: Project, other_session_human: Actor, agent: Actor
) -> None:
    record_scheme(project, other_session_human, _scheme())
    bad = [
        HintInput(layer="nope"),
        HintInput(category="layer/core"),  # no taxonomy registered
        HintInput(taxonomy="t-lay"),
        HintInput(miner_notes="x" * 601),
    ]
    result = add_links(
        project, other_session_human, [LinkInput("10.2000/b", hints=h) for h in bad], Channel.CLI
    )
    assert result.written == [] and len(result.rejected) == len(bad)
    fields = {e.issues[0].field for e in result.rejected}
    assert fields == {"hints.layer", "hints.category", "hints.miner_notes"} | {"hints.taxonomy"}
    assert _added(project) == []
    agent_item = add_links(
        project,
        agent,
        [LinkInput("10.2000/c", basis=KNOWLEDGE, hints=HintInput(miner_notes="mine"))],
        Channel.MCP,
    )
    assert agent_item.written == [] and agent_item.rejected[0].issues[0].field == "hints"


def test_a_category_names_its_taxonomy_and_version(
    project: Project, other_session_human: Actor
) -> None:
    record_scheme(project, other_session_human, _scheme())
    register_taxonomy(project, other_session_human, taxonomy_to_json(_layer_taxonomy()))
    [item] = _items(project, other_session_human, HintInput(category="layer/applied"))
    [payload] = _added(project)
    hints = payload["hints"]
    assert isinstance(hints, dict)
    assert hints["taxonomy"] == "t-lay" and hints["taxonomy_version"] == 1
    assert item.startswith("inb_")
    refused = add_links(
        project,
        other_session_human,
        [LinkInput("10.2000/z", hints=HintInput(category="layer/ghost"))],
        Channel.CLI,
    )
    assert refused.rejected[0].issues[0].field == "hints.category"


# --- origin, staleness, hint text ---


def test_origin_is_computed_and_filterable(
    project: Project, capturer: Actor, world: list[str]
) -> None:
    work, other = sorted(world)[:2]
    [item] = _items(project, capturer, None)
    assert origins_of(project) == {}  # an unresolved item gives no origin
    _resolve_to(project, capturer, item, work)
    found = origins_of(project)
    assert set(found) == {work} and other not in found
    assert found[work].kind == "inbox" and found[work].channel == "cli"
    assert origin_matches(found[work], ("inbox",))
    assert origin_matches(found[work], ("inbox:cli",))
    assert not origin_matches(found[work], ("feed",))
    assert not origin_matches(None, ("inbox",))


def test_a_feed_send_gives_the_feed_origin(explore_project: Project, human: Actor) -> None:
    open_world = _world(explore_project)
    from tests.test_feed_actions import ENTRY

    result = add(open_world, human, ENTRY, sources=_keyed().sources())
    assert result.work_id is not None
    assert origins_of(open_world)[result.work_id].kind == "feed"


def test_a_hint_goes_stale_when_the_scheme_moves(
    project: Project, capturer: Actor, world: list[str]
) -> None:
    record_scheme(project, capturer, _scheme())
    [item] = _items(project, capturer, HintInput(layer="core", miner_notes="bench"))
    _resolve_to(project, capturer, item, world[0])
    hint = hints_by_work(project)[world[0]]
    assert hint.session == capturer.session and hint.ts
    assert hint_staleness(project, hint) == (False, False)
    assert "layer: core" in hint_context_text(project, world[0])
    assert "out of date" not in hint_context_text(project, world[0])
    record_scheme(project, capturer, _scheme(2))
    assert hint_staleness(project, hint) == (True, False)
    assert "out of date" in hint_context_text(project, world[0])
    assert hint_context_text(project, world[1]) == ""


# --- agreement (pure parts) ---


def _hint(layer: str | None, category: str | None = None) -> CaptureHint:
    return CaptureHint(
        "inb_x", "ev_x", "t", "s", layer, 1 if layer else None, category,
        "t-lay" if category else None, 1 if category else None, None,
    )  # fmt: skip


def test_layer_agreement_counts_and_never_compares_absence(
    project: Project, other_session_human: Actor
) -> None:
    record_scheme(project, other_session_human, _scheme())
    hints = {
        "w1": _hint("core"),
        "w2": _hint("core"),
        "w3": _hint("core"),
        "w4": _hint("core"),
        "w5": _hint("applied"),
    }
    values = {
        "w1": {"layer/core"},
        "w2": {"layer/applied"},
        "w3": {"layer/not-stated"},
        "w5": {"layer/applied"},
    }
    report = _layer_report(project, "m-lay", "layer", hints, values)
    assert (report.agree, report.disagree, report.absent, report.unmined) == (2, 1, 1, 1)
    assert report.compared == 3
    assert report.disagreements == (("w2", "core", "applied"),)
    record_scheme(project, other_session_human, _scheme(2))
    stale = _layer_report(project, "m-lay", "layer", hints, values)
    assert stale.stale == 5 and stale.compared == 0


def test_category_agreement(project: Project, other_session_human: Actor) -> None:
    record_scheme(project, other_session_human, _scheme())
    register_taxonomy(project, other_session_human, taxonomy_to_json(_layer_taxonomy()))
    hints = {"w1": _hint(None, "layer/core"), "w2": _hint(None, "layer/core")}
    values = {"w1": {"layer/core"}, "w2": {"layer/applied"}}
    report = _category_report(project, "m-lay", "t-lay", hints, values)
    assert (report.agree, report.disagree) == (1, 1)


# --- the miner option and the selector ---


def _list_layer_miner(project: Project, agent: Actor, human: Actor, **over: object) -> None:
    record_scheme(project, human, _scheme())
    taxonomy = _layer_taxonomy()
    register_taxonomy(project, human, taxonomy_to_json(taxonomy))
    layer_miner = derive_miner(
        taxonomy,
        ("layer",),
        name="m-lay",
        version=1,
        selector=Selector(MinerPopulation.INCLUDED_FT),
        regime=MinerRegime(2, 3, 0.8, 0.9),
        layer_ids=("core", "applied"),
    )
    register_miner(project, agent, spec_to_json(layer_miner))
    current = current_protocol(project)
    assert current is not None
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(
            update={
                "miners": (*(current.spec.miners or ()), use(layer_miner, **over)),
                "taxonomies": (TaxonomyUse(name="t-lay", version=1),),
            }
        ),
        reason="list the layer miner",
        semantic=True,
        effects={},
    )


def test_a_hint_informed_miner_is_never_scored(
    project: Project, agent: Actor, capturer: Actor, world: list[str]
) -> None:
    from factory.services.capture_hints import hint_agreement

    _list_layer_miner(project, agent, capturer)
    [item] = _items(project, capturer, HintInput(layer="core"))
    _resolve_to(project, capturer, item, world[0])
    assert hint_informed_miners(project) == frozenset()
    [plain] = hint_agreement(project)
    assert plain.miner == "m-lay" and not plain.excluded and plain.unmined == 1
    # switching the option on, then off again, leaves the miner informed for good
    current = current_protocol(project)
    assert current is not None
    for flag in (True, False):
        current = current_protocol(project)
        assert current is not None
        miners = tuple(
            u.model_copy(update={"hint_context": flag}) if u.name == "m-lay" else u
            for u in current.spec.miners or ()
        )
        amend_protocol(
            project,
            agent,
            current.spec.model_copy(update={"miners": miners}),
            reason=f"hint context {flag}",
            semantic=True,
            effects={},
        )
    assert hint_informed_miners(project) == frozenset({"m-lay"})
    [informed] = hint_agreement(project)
    assert informed.excluded and informed.compared == 0 and informed.agree == 0


def test_the_origin_filter_selects_the_selector_population(
    project: Project, agent: Actor, capturer: Actor, world: list[str]
) -> None:
    spec = method_vision()
    register_miner(project, agent, spec_to_json(spec))
    current = current_protocol(project)
    assert current is not None
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(
            update={"miners": (*(current.spec.miners or ()), use(spec, origins=("inbox",)))}
        ),
        reason="list with origins",
        semantic=True,
        effects={},
    )
    base = sorted(w for w, _ in population(project, spec.selector))
    assert base, "the base population must not be empty"
    assert miner_population(project, VISION_NAME) == []  # no work came through the inbox
    [item] = _items(project, capturer, None)
    _resolve_to(project, capturer, item, base[0])
    assert miner_population(project, VISION_NAME) == [base[0]]


# --- blinding ---


def test_screening_never_sees_the_hints_or_the_origin(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    from factory.model.inbox import ResolveStatus as Status
    from factory.services.protocol import record_deviation
    from tests.inbox_helpers import Keyed, link_item, resolve

    _setup(project, agent, human, mock_sources, random_works=0)
    record_scheme(project, other_session_human, _scheme())
    result = add_links(
        project,
        other_session_human,
        [LinkInput("10.2000/s1", hints=HintInput(layer="core", miner_notes=MARK))],
        Channel.CLI,
    )
    assert result.rejected == []
    deviation = record_deviation(
        project, other_session_human, description="Supplied link", reason="Colleague."
    )
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1)]})
    [outcome] = resolve(project, other_session_human, keyed, deviation_id=deviation)
    assert outcome.status is Status.NEW and outcome.work_id is not None
    assert hints_by_work(project)[outcome.work_id].miner_notes == MARK
    _draw(project)
    served: list[str] = []
    records: dict[str, dict[str, str | None]] = {}
    for _ in range(30):
        batch = screen_next(project, agent, PassLabel.A)
        if batch.batch is None:
            break
        served.append(batch.batch.model_dump_json())
        records.update({str(r["work_id"]): r for r in batch.batch.records})
        complete_task(project, agent, batch.batch.task_id)
    assert outcome.work_id in records
    other = next(w for w in records if w != outcome.work_id)
    assert set(records[outcome.work_id]) == set(records[other])
    for text_ in served:
        for banned in (MARK, "miner_notes", "scheme_version", "inb_", "supplied"):
            assert banned not in text_
