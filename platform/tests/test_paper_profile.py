"""Compact paper profiles (plan chat T5): final rows, pass A fallback, quotes, categories."""

# ruff: noqa: F811
from dataclasses import replace

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.spec import EnumKind, MinerField, MinerRegime, MinerSpec, spec_to_json
from factory.mining.taxonomy import Category, Dimension, TaxonomySpec
from factory.model.extraction import FieldInput, MinerScope
from factory.model.screening import Channel, PassLabel
from factory.services import paper_profile as pp
from factory.services.context import Project
from factory.services.extraction import live_rows
from factory.services.miner_gold import label_miner_calibration
from factory.services.miners import draw_miner_calibration
from factory.services.mining import mine_next, mine_record, register_miner
from factory.services.paper_profile import (
    PROFILE_CHARS_PER_TOKEN,
    PaperProfile,
    ProfileRow,
    RawMinerRow,
    category_names,
    load_miner_rows,
    paper_profiles,
    profile_size,
    render_profile,
)
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)
from tests.miner_helpers import (
    SESSION_M1,
    SESSION_M2,
    VISION_NAME,
    list_miner,
    method_vision,
    mine_exploratory,
    mine_pass,
    mine_row,
    miner_actor,
)

A, B = PassLabel.A, PassLabel.B
SESSION_P = "01JZ9Q3K5M7N8P0R2S4T6V8W1J"
SESSION_C = "01JZ9Q3K5M7N8P0R2S4T6V8W1G"


@pytest.fixture
def mina() -> Actor:
    return miner_actor(SESSION_M1, "claude-opus-5-5")


@pytest.fixture
def minb() -> Actor:
    return miner_actor(SESSION_M2, "claude-sonnet-5-5")


def test_pass_a_only_until_pass_b_opens(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    mine_pass(project, mina, A, lambda w: [mine_row()])
    [profile] = paper_profiles(project, world[:1])
    assert profile.rows and {r.status for r in profile.rows} == {"pass-a-only"}
    assert profile.missing_miners == ()
    assert profile.title and profile.work_id == world[0]
    text = render_profile(profile)
    assert f"{VISION_NAME} [pass-a-only]: " in text
    assert "value=1" in text and "direction=higher" in text and "metric" not in text


def test_final_rows_used_once_pass_b_has_run(
    project: Project, agent: Actor, mina: Actor, minb: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    mine_pass(project, mina, A, lambda w: [mine_row("lower")])
    mine_pass(project, minb, B, lambda w: [mine_row("lower")])
    [profile] = paper_profiles(project, world[:1])
    assert {r.status for r in profile.rows} == {"final"}
    assert f"{VISION_NAME} [final]:" in render_profile(profile)


def test_quote_fields_omitted_for_other_miners(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    mine_pass(project, mina, A, lambda w: [mine_row()])
    [profile] = paper_profiles(project, world[:1])
    names = {k for r in profile.rows for k, _ in r.fields}
    assert "metric" not in names and "evidence" not in names
    assert {"value", "direction"} <= names


def test_quote_fields_kept_for_quoted_miners() -> None:
    spec = replace(_spec_base(), name="m-summary")
    long = "x" * 400
    row = pp._row(spec, {}, "final", "k", {"metric": (long, None), "value": ("1", "%")})
    shown = dict(row.fields)
    assert len(shown["metric"]) == pp.QUOTE_CHARS and shown["metric"].endswith("…")
    assert shown["value"] == "1 %"
    assert "m-summary" in pp.QUOTED_MINERS


def _spec_base() -> MinerSpec:
    from tests.miner_helpers import vision_result

    return vision_result()


def test_superseded_pass_a_rows_absent(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    batch = mine_exploratory(project, mina, VISION_NAME, 1, A).batch
    assert batch is not None
    work = batch.records[0]["work_id"]
    mine_record(project, mina, batch.task_id, [mine_row("higher")])
    [first] = live_rows(project, scope=MinerScope(VISION_NAME))
    mine_record(
        project,
        mina,
        batch.task_id,
        [mine_row("lower")],
        supersedes={0: first.extraction_id},
        finish=True,
    )
    [profile] = paper_profiles(project, [work])
    text = render_profile(profile)
    assert "direction=lower" in text and "direction=higher" not in text


def test_missing_miners_and_deterministic_render(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    [profile] = paper_profiles(project, world[:1])
    assert profile.rows == ()
    assert profile.missing_miners == ((VISION_NAME, 1),)
    assert render_profile(profile).splitlines()[-1] == f"missing: {VISION_NAME}"
    mine_pass(project, mina, A, lambda w: [mine_row()])
    first = [render_profile(p) for p in paper_profiles(project, world)]
    again = [render_profile(p) for p in paper_profiles(project, list(reversed(world)))]
    assert first == list(reversed(again))


def test_unknown_work_refused(project: Project, agent: Actor, world: list[str]) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        paper_profiles(project, [world[0], "W-nope"])
    assert raised.value.issues[0].field == "work_ids"


def test_taxonomy_category_rendered_as_name() -> None:
    taxonomy = TaxonomySpec(
        name="t",
        version=1,
        dimensions=(
            Dimension(
                id="technique",
                title="T",
                question="q",
                cardinality="single",
                categories=(Category("multi-agent", "Multi-agent system", "d"),),
            ),
        ),
    )
    names = category_names(taxonomy)
    assert names == {"technique/multi-agent": "Multi-agent system"}
    base = _spec_base()
    spec = replace(
        base,
        fields=(MinerField("category", "classification", EnumKind(("technique/multi-agent",))),),
    )
    row = pp._row(spec, names, "final", "k", {"category": ("technique/multi-agent", None)})
    assert row.fields == (("category", "Multi-agent system"),)
    other = pp._row(spec, names, "final", "k", {"category": ("technique/other", None)})
    assert other.fields == (("category", "technique/other"),)


def test_render_layout_and_size() -> None:
    profile = PaperProfile(
        "W1",
        "A title",
        "2024",
        (
            ProfileRow("m-b", 1, "final", "r2", (("a", "2"),)),
            ProfileRow("m-a", 1, "pass-a-only", "r2", (("a", "1"), ("b", "x"))),
            ProfileRow("m-a", 1, "pass-a-only", "r1", (("a", "0"),)),
        ),
        (("m-c", 1),),
    )
    assert render_profile(profile).splitlines() == [
        "W1 · 2024 · A title",
        "m-a [pass-a-only]: a=0 | a=1; b=x",
        "m-b [final]: a=2",
        "missing: m-c",
    ]
    assert profile_size("x" * 9) == 3 and PROFILE_CHARS_PER_TOKEN == 4


def test_two_listed_versions_of_one_miner_are_profiled_once(
    project: Project,
    agent: Actor,
    mina: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The protocol validator refuses two listed versions of a name, so the situation is built by
    # handing `paper_profiles` a protocol that lists both (e.g. from older events).
    from types import SimpleNamespace

    from tests.miner_helpers import method_vision, use

    list_miner(project, agent)
    mine_pass(project, mina, A, lambda w: [mine_row()])
    [before] = paper_profiles(project, world[:1])
    v2 = method_vision()
    uses = (use(v2), use(v2, version=2))
    monkeypatch.setattr(
        pp, "current_protocol", lambda _p: SimpleNamespace(spec=SimpleNamespace(miners=uses))
    )
    [after] = paper_profiles(project, world[:1])
    assert len(after.rows) == len(before.rows) > 0
    assert {r.version for r in after.rows} == {1}
    assert after.missing_miners == ()


def test_held_out_scrub_applied_to_title_and_values(
    project: Project,
    agent: Actor,
    mina: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_miner(project, agent)
    mine_pass(project, mina, A, lambda w: [mine_row()])
    [plain] = paper_profiles(project, world[:1])
    title_word = plain.title.split()[0]
    monkeypatch.setattr(
        pp, "held_out_tokens", lambda _p, include_work_ids=True: {title_word, "higher"}
    )
    [scrubbed] = paper_profiles(project, world[:1])
    assert title_word not in scrubbed.title.split() and "[withheld]" in scrubbed.title
    values = [v for r in scrubbed.rows for _, v in r.fields]
    assert "higher" not in values and "[withheld]" in values
    assert scrubbed.work_id == world[0]


def _sample(project: Project, agent: Actor, human: Actor, labelled: int) -> tuple[list[str], str]:
    """Register and list the fixture miner (5 calibration units), draw the sample, record a gold
    label for the first `labelled` units (an empty label for the others, which counts as none),
    and run the calibration session over all units. Returns the units and the miner's name."""
    spec = replace(method_vision(), regime=MinerRegime(2, 5, 0.8, 0.9))
    register_miner(project, miner_actor(SESSION_P, "claude-opus-5-5"), spec_to_json(spec))
    list_miner(project, agent, spec)
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=11)
    works = [u.work_id for u in drawn.units]
    for i, work in enumerate(works):
        gold = [mine_row("lower")] if i < labelled else []
        label_miner_calibration(
            project, human, drawn.calibration_id, work, gold, empty=not gold, channel=Channel.CLI
        )
    judge = miner_actor(SESSION_C, "claude-sonnet-5-5")
    for _ in range(50):
        batch = mine_next(project, judge, VISION_NAME, 1, A, calibration=True).batch
        if batch is None:
            break
        mine_record(project, judge, batch.task_id, [mine_row("higher")], finish=True, reason=None)
    return works, VISION_NAME


def test_calibration_work_gold_else_calibration_rows(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    works, name = _sample(project, agent, human, labelled=2)
    found = load_miner_rows(project, name, 1, works)
    gold, plain = works[:2], works[2:]
    for work in gold:
        assert [r.status for r in found[work]] == ["gold"]
        assert found[work][0].fields["direction"][0] == "lower"
    for work in plain:  # an empty gold label is a decision: no rows, not the calibration rows
        assert found[work] == []
    [profile] = paper_profiles(project, gold[:1])
    assert [r.status for r in profile.rows] == ["gold"]


def test_production_rows_win_over_calibration_rows() -> None:
    production = [RawMinerRow("pass-a-only", "k", {})]
    gold = [RawMinerRow("gold", "g", {})]
    calibration = [RawMinerRow("calibration", "c", {})]
    assert pp.choose_rows(production, gold, calibration) is production
    assert pp.choose_rows([], gold, calibration) is gold
    assert pp.choose_rows([], [], calibration) is calibration
    assert pp.choose_rows([], [], []) == []


def test_calibration_of_another_version_is_not_served(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    works, name = _sample(project, agent, human, labelled=2)
    assert [r.status for r in load_miner_rows(project, name, 1, works)[works[0]]] == ["gold"]
    # version 2 is not calibrated: the rows of version 1 are its tagged fallback, not its own
    assert [r.version for r in load_miner_rows(project, name, 2, works)[works[0]]] == [1]


def test_pass_b_reviewed_to_empty_does_not_serve_pass_a_rows(
    project: Project, agent: Actor, mina: Actor, minb: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    mine_pass(project, mina, A, lambda w: [mine_row("lower")])
    mine_pass(project, minb, B, lambda w: [])
    [profile] = paper_profiles(project, world[:1])
    assert profile.rows == ()
    assert profile.reviewed_empty == ((VISION_NAME, 1),) and profile.missing_miners == ()
    assert f"reviewed-empty: {VISION_NAME}" in render_profile(profile)
    rows, emptied = pp.load_miner_work_rows(project, VISION_NAME, 1, world[:1])
    assert rows == {world[0]: []} and emptied == {world[0]}


def _relabel(
    project: Project, monkeypatch: pytest.MonkeyPatch, version_of: dict[int, int], default: int
) -> None:
    """Relabel the live rows of the miner as rows of other schema versions: the n-th row (by
    extraction id) gets `version_of[n]`, else `default`. The fixture protocol lists version 1 only,
    so older versions are built by relabelling, as `_row_versions` is the one reader of them."""
    live = sorted(live_rows(project, scope=MinerScope(VISION_NAME)), key=lambda r: r.extraction_id)
    labels = {r.extraction_id: version_of.get(n, default) for n, r in enumerate(live)}
    monkeypatch.setattr(pp, "_row_versions", lambda _p, _n: labels)


def test_work_with_only_older_version_rows_is_served_those_rows_tagged(
    project: Project,
    agent: Actor,
    mina: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_miner(project, agent)
    mine_pass(project, mina, A, lambda w: [mine_row()])
    _relabel(project, monkeypatch, {}, 0)
    rows, emptied = pp.load_miner_work_rows(project, VISION_NAME, 1, world[:1])
    assert emptied == frozenset()
    assert rows[world[0]] and {(r.version, r.status) for r in rows[world[0]]} == {
        (0, "pass-a-only")
    }
    [profile] = paper_profiles(project, world[:1])
    assert profile.rows and {(r.version, r.older) for r in profile.rows} == {(0, True)}
    assert profile.missing_miners == ()
    assert f"{VISION_NAME} [pass-a-only] (v0):" in render_profile(profile)


def test_work_with_listed_version_rows_gets_only_those(
    project: Project,
    agent: Actor,
    mina: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_miner(project, agent)
    other = mine_row("lower")
    other.fields["metric"] = FieldInput(value="Low", anchor="t1.r2.c2", quote="Low")
    other.fields["value"] = FieldInput(value="2", anchor="t1", cell="t1.r3.c3", quote="2")
    mine_pass(project, mina, A, lambda w: [mine_row("higher"), other])
    live = [r for r in live_rows(project, scope=MinerScope(VISION_NAME)) if r.work_id == world[0]]
    assert len(live) == 2
    _relabel(project, monkeypatch, {}, 0)
    first = sorted(live_rows(project, scope=MinerScope(VISION_NAME)), key=lambda r: r.extraction_id)
    labels = {r.extraction_id: 0 for r in first}
    labels[min(r.extraction_id for r in live)] = 1  # one current-version row for the work
    monkeypatch.setattr(pp, "_row_versions", lambda _p, _n: labels)
    rows, _ = pp.load_miner_work_rows(project, VISION_NAME, 1, world[:1])
    assert [r.version for r in rows[world[0]]] == [1]
    [profile] = paper_profiles(project, world[:1])
    assert {r.older for r in profile.rows} == {False}
    assert "(v" not in render_profile(profile)


def test_reviewed_empty_work_gets_no_older_version_fallback(
    project: Project,
    agent: Actor,
    mina: Actor,
    minb: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_miner(project, agent)
    mine_pass(project, mina, A, lambda w: [mine_row("lower")])
    mine_pass(project, minb, B, lambda w: [])
    _relabel(project, monkeypatch, {}, 0)
    rows, emptied = pp.load_miner_work_rows(project, VISION_NAME, 1, world[:1])
    assert rows == {world[0]: []} and emptied == {world[0]}


def test_older_version_calibration_rows_are_a_fallback_of_that_version(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    works, name = _sample(project, agent, human, labelled=2)
    other = load_miner_rows(project, name, 2, works)
    assert [(r.status, r.version) for r in other[works[0]]] == [("gold", 1)]


def test_work_with_only_newer_version_rows_is_reported_not_served_not_missing(
    project: Project,
    agent: Actor,
    mina: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_miner(project, agent)
    mine_pass(project, mina, A, lambda w: [mine_row()])
    _relabel(project, monkeypatch, {}, 2)  # the listed version is 1
    rows, emptied, newer = pp.load_miner_work_report(project, VISION_NAME, 1, world[:1])
    assert rows == {world[0]: []} and emptied == frozenset() and newer == {world[0]}
    [profile] = paper_profiles(project, world[:1])
    assert profile.rows == () and profile.missing_miners == ()
    assert profile.newer_version_only == ((VISION_NAME, 1),)
    assert f"newer-version-only: {VISION_NAME}" in render_profile(profile)


def test_empty_gold_label_is_a_decision_not_a_gap(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    works, name = _sample(project, agent, human, labelled=2)
    state = pp.load_miner_work_state(project, name, 1, works)
    assert state.gold_empty == frozenset(works[2:])
    assert all(state.rows[w] == [] for w in works[2:])
    assert [r.status for r in state.rows[works[0]]] == ["gold"]
    assert state.gold_empty.isdisjoint(state.emptied | state.newer)
    [profile] = paper_profiles(project, works[2:3])
    assert profile.rows == () and profile.missing_miners == ()
    assert profile.gold_empty == ((name, 1),)
    assert f"gold-empty: {name}" in render_profile(profile)
    [plain] = paper_profiles(project, works[:1])
    assert plain.gold_empty == () and "gold-empty" not in render_profile(plain)


def test_production_rows_win_over_empty_gold(
    project: Project,
    agent: Actor,
    human: Actor,
    mina: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    works, name = _sample(project, agent, human, labelled=0)
    mine_pass(project, mina, A, lambda w: [mine_row("lower")])
    real = live_rows
    donor = real(project, PassLabel.A, scope=MinerScope(name))[0]

    def serving(*args: object, **kwargs: object) -> list:  # type: ignore[type-arg]
        found = real(*args, **kwargs)  # type: ignore[arg-type]
        if args[1:2] == (PassLabel.A,):  # a production row of the first sampled work
            found = [*found, donor.model_copy(update={"work_id": works[0]})]
        return found

    monkeypatch.setattr(pp, "live_rows", serving)
    state = pp.load_miner_work_state(project, name, 1, works)
    assert works[0] not in state.gold_empty
    assert [r.status for r in state.rows[works[0]]] == ["pass-a-only"]
    assert state.gold_empty == frozenset(works[1:])


def test_gold_empty_work_gets_no_older_version_fallback(
    project: Project,
    agent: Actor,
    human: Actor,
    mina: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    works, name = _sample(project, agent, human, labelled=0)
    # live pass A rows exist only at an older version (0) than the listed one (1)
    mine_pass(project, mina, A, lambda w: [mine_row("lower")])
    _relabel(project, monkeypatch, {}, 0)
    state = pp.load_miner_work_state(project, name, 1, works)
    assert state.gold_empty == frozenset(works)
    assert all(state.rows[w] == [] for w in works)
