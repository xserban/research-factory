"""Hub journeys: stage lists, swimlanes and replay frames (plan hub-ui, step 8b)."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.services import hub_journeys as hj
from factory.services import hub_payloads as hp
from factory.services import site_corpus
from factory.services.context import Project
from factory.services.flow_ledger import LedgerRow
from factory.services.flow_trails import TrailStep, flow_trails
from tests.fulltext_helpers import _ft_world
from tests.helpers import SourcesFor
from tests.test_hub_payloads_flow import row


def step(at: str, kind: str, **d: str | int) -> TrailStep:
    return TrailStep(at=f"2026-03-{at}.000Z", kind=kind, d=dict(d))


def dec(at: str, stage: str, label: str, verdict: str, criterion: str = "") -> TrailStep:
    extra: dict[str, str | int] = {"criterion": criterion} if criterion else {}
    return step(
        at,
        "decision",
        stage=stage,
        pass_label=label,
        phase="screening",
        verdict=verdict,
        rationale=f"because {verdict}",
        quote="a quote",
        by="agent-1",
        model="m-1",
        **extra,
    )


def included_steps(extra_found: str = "01T10:00:00") -> list[TrailStep]:
    return [
        step(extra_found, "found", source="arxiv", method="database", run="r1"),
        dec("02T10:00:00", "title-abstract", "A", "include"),
        dec("02T11:00:00", "title-abstract", "B", "include"),
        step("03T10:00:00", "attempt", route="arxiv", outcome="retrieved"),
        step("03T10:05:00", "document added", document="d1", route="arxiv"),
        step("04T10:00:00", "converted", document="d1", converter="docling"),
        dec("05T10:00:00", "full-text", "A", "include"),
        dec("05T11:00:00", "full-text", "B", "include"),
        step("06T10:00:00", "extracted", schema="m-x@1", pass_label="A", rows=3),
    ]


def build() -> tuple[list[LedgerRow], dict[str, list[TrailStep]]]:
    rows = [
        row("w1", ft_state="retrieved", ft_outcome="included"),
        row("w2", canonical_id="w1", merge_rule="doi", ta_outcome=None),
        row("w3", ta_outcome="excluded", ta_criterion="EX01"),
        row("w4", ft_state="retrieved", ft_outcome="excluded", ft_criterion="EX04"),
        row("w6", ft_state="retrieved", ft_outcome="included"),
    ]
    trails = {
        "w1": [
            *included_steps(),
            step("01T12:00:00", "merged", primary="w1", absorbed="w2", rule="doi"),
        ],
        "w2": [
            step("01T11:00:00", "found", source="crossref", method="database"),
            step("01T12:00:00", "merged", primary="w1", absorbed="w2", rule="doi"),
        ],
        "w3": [
            step("01T10:00:00", "found", source="arxiv", method="database"),
            dec("02T10:00:00", "title-abstract", "A", "exclude", "EX01"),
            dec("02T11:00:00", "title-abstract", "B", "exclude", "EX01"),
        ],
        "w4": [
            *included_steps()[:6],
            dec("05T10:00:00", "full-text", "A", "exclude", "EX04"),
            dec("05T11:00:00", "full-text", "B", "exclude", "EX04"),
        ],
        "w6": included_steps("01T09:00:00")[:8],
    }
    return rows, trails


def rows_of(r: list[object]) -> list[LedgerRow]:
    return [x for x in r if isinstance(x, LedgerRow)]


def test_stops_are_ordered_by_time_then_stage_with_actor_and_trace() -> None:
    r, t = build()
    j = hj.journey("w1", r, t, True)
    own = [s for s in j.stops if s.of is None]
    keys = [(s.ts, s.stage_index) for s in own]
    assert keys == sorted(keys)
    assert [s.stage for s in own][:3] == ["found", "deduplicated", "title-abstract"]
    ta = next(s for s in own if s.stage == "title-abstract")
    assert (ta.actor_kind, ta.model, ta.outcome) == ("agent", "m-1", "included")
    assert ta.text == "because include" and ta.quote == "a quote"
    assert ta.figure_id == "work.w1.screening"
    assert own[-1].stage == "read-in-full" and own[-1].outcome == "read"
    assert hj.STAGES.index("found") == 0


def test_fate_equals_ledger_fate_and_stops_agree() -> None:
    r, t = build()
    for x in r:
        j = hj.journey(x.work_id, r, t, True)
        assert j.fate == hp.fate_of(x, True)[0]
        assert j.criterion == hp.fate_of(x, True)[1]
        assert hj.fate_consistent(j)
    j = hj.journey("w3", r, t, True)
    assert (j.fate, j.criterion) == ("ta_excluded", "EX01")
    bad = hj.journey("w3", r, {"w3": []}, True)
    assert not hj.fate_consistent(bad)


def test_duplicate_is_shown_with_its_canonical() -> None:
    r, t = build()
    j = hj.journey("w2", r, t, True)
    assert (j.fate, j.canonical_id) == ("duplicate", "w1")
    assert any(s.stage == "deduplicated" and s.outcome == "merged" for s in j.stops if not s.of)
    after = [s for s in j.stops if s.of == "w1"]
    assert after and all(s.ts >= "2026-03-01T12:00:00.000Z" for s in after)
    canon = hj.journey("w1", r, t, True)
    assert next(s for s in canon.stops if s.stage == "deduplicated").outcome == "kept"


def test_swimlane_limits_and_unknown_ids_are_refused() -> None:
    r, t = build()
    with pytest.raises(FactoryValidationError) as many:
        hj.swimlanes(r, t, [f"x{i}" for i in range(21)], True)
    assert "work_ids" in str(many.value.issues[0].field)
    with pytest.raises(FactoryValidationError) as unknown:
        hj.swimlanes(r, t, ["w1", "nope"], True)
    assert unknown.value.issues[0].field == "work_ids"
    with pytest.raises(FactoryValidationError):
        hj.swimlanes(r, t, [], True)
    ok = hj.swimlanes(r, t, [f"w{i}" for i in (1, 2, 3, 4, 6)], True)
    assert len(ok.lanes) == 5 and ok.lanes[1].canonical_id == "w1"


def test_divergence_point_is_first_stage_off_the_strict_majority() -> None:
    r, t = build()
    a = hj.swimlanes(r, t, ["w1", "w6", "w4"], True)
    d = {lane.work_id: lane.divergence for lane in a.lanes}
    assert d == {"w1": None, "w6": None, "w4": "full-text"}
    b = hj.swimlanes(r, t, ["w1", "w6", "w3"], True)
    assert {lane.work_id: lane.divergence for lane in b.lanes}["w3"] == "title-abstract"
    tie = hj.swimlanes(r, t, ["w1", "w4"], True)
    assert [lane.divergence for lane in tie.lanes] == [None, None]  # no strict majority at FT
    assert a.domain == ("2026-03-01T09:00:00.000Z", "2026-03-06T10:00:00.000Z")
    lane = a.lanes[0]
    first = {d["stage"]: d for d in lane.durations}
    assert first["found"]["seconds"] == 7200  # found 10:00, merged 12:00 the same day
    assert lane.durations[-1]["seconds"] is None


def decode(frames: Mapping[str, object]) -> dict[str, int]:
    stages = list(frames["stages"])  # type: ignore[call-overload]
    out = {s: 0 for s in stages}
    for rec in frames["records"]:  # type: ignore[attr-defined]
        for si, _t in rec[2]:
            out[stages[si]] += 1
    return out


def test_replay_encoding_round_trips_counts_per_stage() -> None:
    r, t = build()
    f = hj.replay_frames(r, t, True)
    assert f["stages"] == list(hj.STAGES)
    assert len(f["records"]) == 5 and f["ids"] == sorted(f["ids"])
    counts = decode(f)
    assert counts["found"] == 5 and counts["title-abstract"] == 4
    for name, per_day in f["hist"].items():
        assert sum(per_day) == counts[name]
    t0 = f["t0"]
    assert all(isinstance(x, int) for rec in f["records"] for _, x in rec[2])
    assert f["days"] == len(f["hist"]["found"]) and t0 > 0
    fate_idx = {rec[0]: f["fates"][rec[1]] for rec in f["records"]}
    assert fate_idx[f["ids"].index("w3")] == "ta_excluded"
    json.dumps(f)


def test_output_is_deterministic_whatever_the_input_order() -> None:
    r, t = build()
    a = json.dumps(hj.replay_frames(r, t, True), sort_keys=True)
    b = json.dumps(
        hj.replay_frames(list(reversed(r)), dict(reversed(list(t.items()))), True),
        sort_keys=True,
    )
    assert a == b
    s1 = json.dumps(hj.swimlanes(r, t, ["w1", "w3"], True).to_payload())
    s2 = json.dumps(hj.swimlanes(r, t, ["w1", "w3"], True).to_payload())
    assert s1 == s2


def test_journey_index_scope_and_text_limit() -> None:
    r, t = build()
    idx = hj.journey_index(r, t, True)
    assert idx["scope"] == "included" and sorted(idx["works"]) == ["w1", "w6"]
    assert idx["bytes"] == len(json.dumps(idx["works"], separators=(",", ":")))
    cut = hj.journey_index(r, t, True, scope="all", text_limit=4)
    assert sorted(cut["works"]) == ["w1", "w2", "w3", "w4", "w6"]
    assert all(len(s[6]) <= 4 for s in cut["works"]["w1"] if s[6])


def test_journey_index_stops_carry_the_quote_and_event_id() -> None:
    r, t = build()
    stops = hj.journey_index(r, t, True)["works"]["w1"]
    assert all(len(s) == 11 for s in stops)
    screens = [s for s in stops if s[0] == hj.STAGES.index("title-abstract")]
    assert screens and all(s[7] == "a quote" for s in screens)
    assert all(s[8] is None for s in stops)  # hand-built steps hold no event id


def test_trail_steps_hold_the_event_id_and_index_passes_it_on(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    listed_miners: None,
) -> None:
    _ft_world(project, agent, human, mock_sources)
    data = hp.load_flow_data(project)
    trails = flow_trails(project)
    decided = [s for ss in trails.values() for s in ss if s.kind == "decision"]
    assert decided and all(s.event_id and s.event_id.startswith("ev_") for s in decided)
    idx = hj.journey_index(list(data.rows), trails, data.prisma.full_text.stage_run, scope="all")
    ids = {s[8] for ss in idx["works"].values() for s in ss if s[8]}
    assert ids & {s.event_id for s in decided}


def test_reference_extras_feed_references_and_cited_by_stops(project: Project) -> None:
    from tests.test_references_index import FUZZY, _extract, _resolve
    from tests.test_references_model import CITED, WORK, resolution

    _extract(project)
    _resolve(project, [resolution(1, confidence="identifier"), FUZZY])
    project.index.sync()
    extra = hj.reference_extras(project)
    mine = extra[WORK]
    ref = [s for s in mine if s.stage == "references-extracted"]
    assert len(ref) == 1 and ref[0].text == "2 references, 1 resolved"
    cited = [s for s in extra[CITED] if s.stage == "cited-by-corpus"]
    assert len(cited) == 1 and cited[0].text == "1 corpus work"
    assert cited[0].ts == ref[0].ts


def test_journeys_payload_has_the_index_and_reference_stages(project: Project) -> None:
    from tests.test_references_index import FUZZY, _extract, _resolve
    from tests.test_references_model import resolution

    _extract(project)
    _resolve(project, [resolution(1, confidence="identifier"), FUZZY])
    payload = hj.journeys_payload(project)
    idx = payload["journey_index"]
    assert idx["bytes"] > 0 and idx["scope"] == "included"
    assert "references-extracted" in payload["replay"]["stages"]


def test_reference_stages_come_from_extra_stops() -> None:
    r, t = build()
    extra = {"w1": [hj.Stop.make("cited-by-corpus", "2026-03-09T00:00:00.000Z", "cited", text="3")]}
    j = hj.journey("w1", r, t, True, extra=extra)
    assert j.stops[-1].stage == "cited-by-corpus"


@pytest.fixture
def listed_miners(monkeypatch: pytest.MonkeyPatch) -> None:
    schemas = {name: f"{name}@1" for name in site_corpus.DEFAULT_ROLES.values()}
    monkeypatch.setattr(site_corpus, "_listed_schemas", lambda _project: schemas)


def test_on_a_screened_project_every_fate_is_consistent(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    listed_miners: None,
) -> None:
    _ft_world(project, agent, human, mock_sources)
    data = hp.load_flow_data(project)
    payload = hj.journeys_payload(project, data)
    assert payload["methods"] and len(payload["replay"]["records"]) == len(data.rows)
    trails = flow_trails(project)
    stage_run = data.prisma.full_text.stage_run
    for x in data.rows:
        j = hj.journey(x.work_id, list(data.rows), trails, stage_run)
        assert j.fate == hp.fate_of(x, stage_run)[0]
        assert hj.fate_consistent(j), x.work_id
    ids = [x.work_id for x in data.rows][:3]
    lanes = hj.swimlanes_payload(project, ids, data)
    assert [ln["work_id"] for ln in lanes["lanes"]] == ids
    json.dumps(lanes)
    assert hj.journey_index(list(data.rows), trails, stage_run)["works"]


def test_when_and_iso_normalise_mixed_timestamp_forms() -> None:
    forms = [
        "2026-03-09T10:00:00Z",
        "2026-03-09T10:00:00+00:00",
        "2026-03-09T10:00:00",  # naive: taken as UTC
        "2026-03-09T11:00:00+01:00",
    ]
    assert {hj.epoch(t) for t in forms} == {hj.epoch(forms[0])}
    assert {hj.iso(t) for t in forms} == {"2026-03-09T10:00:00.000Z"}
    assert hj.iso("2026-03-09T10:00:00.250+00:00") == "2026-03-09T10:00:00.250Z"
    assert hj.when("2026-03-09T10:00:00.250Z") > hj.when("2026-03-09T10:00:00Z")


def test_stops_are_ordered_by_instant_not_by_string() -> None:
    early, late = "2026-03-09T10:00:00+01:00", "2026-03-09T09:30:00Z"  # 09:00Z and 09:30Z
    assert early > late  # the string order is wrong for these two
    stops = hj.build_stops(
        "w",
        (),
        [
            hj.Stop.make("cited-by-corpus", late, "cited"),
            hj.Stop.make("references-extracted", early, "extracted"),
        ],
    )
    assert [s.stage for s in stops] == ["references-extracted", "cited-by-corpus"]
    assert all(s.ts.endswith("Z") for s in stops)


def test_one_references_stop_per_work_and_swimlanes_carry_the_extras(project: Project) -> None:
    from tests.test_references_index import _extract
    from tests.test_references_model import WORK

    _extract(project)
    project.index.sync()
    one = hj.reference_extras(project)[WORK]
    assert len([s for s in one if s.stage == "references-extracted"]) == 1
    # a second live extraction of the same work adds a count, not a second stop
    with project.index._engine.begin() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(reference_extractions)"))]
        sel = ", ".join("'rex_later'" if c == "extraction_id" else c for c in cols)
        conn.execute(
            text(
                f"INSERT INTO reference_extractions ({', '.join(cols)}) "
                f"SELECT {sel} FROM reference_extractions WHERE live = 1"
            )
        )
    stops = [s for s in hj.reference_extras(project)[WORK] if s.stage == "references-extracted"]
    assert len(stops) == 1 and "1 later re-extraction" in str(stops[0].text)


def test_stops_carry_the_document_and_primary_ids_of_their_step() -> None:
    steps = [
        step("01T10:00:00", "found", source="arxiv", method="database", run="r1"),
        step("02T10:00:00", "merged", primary="w9", absorbed="w1", rule="doi"),
        step("03T10:05:00", "document added", document="d1", route="arxiv"),
        step("04T10:00:00", "converted", document="d1", converter="docling"),
    ]
    by_stage = {s.stage: s for s in hj.build_stops("w1", steps)}
    assert (by_stage["deduplicated"].document_id, by_stage["deduplicated"].primary_id) == (
        None,
        "w9",
    )
    assert by_stage["retrieval"].document_id == "d1" and by_stage["conversion"].document_id == "d1"
    assert by_stage["found"].document_id is None and by_stage["found"].primary_id is None
    r, t = build()
    row = hj.journey_index(r, t, True)["works"]["w1"][0]
    assert len(row) == 11 and row[9] is None and row[10] is None
    merged = [
        s
        for s in hj.journey_index([x for x in r], {"w1": steps}, True, scope="all")["works"]["w1"]
        if s[10]
    ]
    assert merged and merged[0][10] == "w9"
