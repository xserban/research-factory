"""Compact paper profiles (plan chat T5): final rows, pass A fallback, quotes, categories."""

# ruff: noqa: F811
from dataclasses import replace

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.spec import EnumKind, MinerField, MinerSpec
from factory.mining.taxonomy import Category, Dimension, TaxonomySpec
from factory.model.extraction import MinerScope
from factory.model.screening import PassLabel
from factory.services import paper_profile as pp
from factory.services.context import Project
from factory.services.extraction import live_rows
from factory.services.mining import mine_record
from factory.services.paper_profile import (
    PROFILE_CHARS_PER_TOKEN,
    PaperProfile,
    ProfileRow,
    category_names,
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
    mine_exploratory,
    mine_pass,
    mine_row,
    miner_actor,
)

A, B = PassLabel.A, PassLabel.B


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
                cardinality="single",  # type: ignore[arg-type]
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
