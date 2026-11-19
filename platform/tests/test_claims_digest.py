"""The claims digest (plan chat T6): order, codes, gaps, status, scrub, render, size."""

# ruff: noqa: F811
from dataclasses import replace

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.spec import MinerRegime, spec_to_json
from factory.model.extraction import ExtractedRowInput
from factory.model.screening import Channel, PassLabel
from factory.services import claims_digest as cd
from factory.services.claims_digest import claims_digest, render_claims_digest
from factory.services.context import Project
from factory.services.miner_gold import label_miner_calibration
from factory.services.miners import draw_miner_calibration
from factory.services.mining import mine_next, mine_record, register_miner
from factory.services.selection import SelectionSpec
from tests.claims_helpers import QUOTES, claim_row, claims_spec
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)
from tests.miner_helpers import SESSION_M1, SESSION_M2, list_miner, mine_pass, miner_actor

A, B = PassLabel.A, PassLabel.B
SESSION_P = "01JZ9Q3K5M7N8P0R2S4T6V8W1J"
SESSION_P2 = "01JZ9Q3K5M7N8P0R2S4T6V8W1G"


@pytest.fixture
def mina() -> Actor:
    return miner_actor(SESSION_M1, "claude-opus-5-5")


@pytest.fixture
def minb() -> Actor:
    return miner_actor(SESSION_M2, "claude-sonnet-5-5")


def _mine(
    project: Project,
    agent: Actor,
    mina: Actor,
    by_index: dict[int, list[ExtractedRowInput]],
    works: list[str],
) -> list[str]:
    list_miner(project, agent, claims_spec())
    order = sorted(works)
    mine_pass(
        project,
        mina,
        A,
        lambda w: by_index.get(order.index(w), []),
        name="m-claims",
    )
    return order


def test_order_codes_and_row_order(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    rows = [
        claim_row("finding", QUOTES[0]),
        claim_row("no-limitation-stated", QUOTES[2]),
        claim_row("limitation", QUOTES[1], conditions=True),
    ]
    order = _mine(project, agent, mina, {i: rows for i in range(len(world))}, world)
    digest = claims_digest(project, SelectionSpec())
    assert [p.work_id for p in digest.papers] == order
    assert [p.code for p in digest.papers] == [f"P{i:02d}" for i in range(1, len(order) + 1)]
    first = digest.papers[0]
    assert [r.claim_type for r in first.rows] == ["limitation", "finding", "no-limitation-stated"]
    assert first.gap is None and {r.status for r in first.rows} == {"pass-a-only"}
    assert first.rows[0].conditions == "sit amet" and first.rows[0].claim_anchor == "s3.p1"
    assert digest.claims == 3 * len(order)
    assert digest.version == 1 and digest.miner == "m-claims"
    again = claims_digest(project, SelectionSpec())
    assert render_claims_digest(again) == render_claims_digest(digest)


def test_gaps_no_rows_and_absence_only(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    if len(world) < 3:
        pytest.skip("needs three works")
    by = {
        0: [],
        1: [claim_row("no-limitation-stated")],
        2: [claim_row("no-limitation-stated"), claim_row("finding", QUOTES[1])],
    }
    _mine(project, agent, mina, by, world)
    digest = claims_digest(project, SelectionSpec())
    gaps = {p.code: p.gap for p in digest.papers}
    assert gaps["P01"] == "no-rows" and gaps["P02"] == "absence-only" and gaps["P03"] is None
    assert digest.papers[1].rows and digest.gaps[:2] == (
        ("P01", "no-rows"),
        ("P02", "absence-only"),
    )
    text = render_claims_digest(digest)
    assert "GAP: no m-claims rows" in text and "GAP: only no-limitation-stated" in text


def test_final_status_after_pass_b(
    project: Project, agent: Actor, mina: Actor, minb: Actor, world: list[str]
) -> None:
    list_miner(project, agent, claims_spec())
    for actor, label in ((mina, A), (minb, B)):
        mine_pass(project, actor, label, lambda w: [claim_row("finding")], name="m-claims")
    digest = claims_digest(project, SelectionSpec())
    assert {r.status for p in digest.papers for r in p.rows} == {"final"}
    assert "(pass-a-only)" not in render_claims_digest(digest)


def test_selection_restricts_and_codes_follow_it(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    order = _mine(project, agent, mina, {i: [claim_row("finding")] for i in range(9)}, world)
    digest = claims_digest(project, SelectionSpec(exclude=[order[0]]))
    assert [p.work_id for p in digest.papers] == order[1:]
    assert digest.papers[0].code == "P01"


def test_render_format_and_size(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    _mine(project, agent, mina, {0: [claim_row("limitation", conditions=True)]}, world)
    digest = claims_digest(project, SelectionSpec())
    text = render_claims_digest(digest)
    assert "## P01 " + digest.papers[0].work_id in text
    key = digest.papers[0].rows[0].row_key
    assert (
        f"- [P01.c1 key={key}] limitation | a | higher | empirical | strong: "
        '"Lorem ipsum" [s3.p1] [conditions: "sit amet" [s3.p1]] (pass-a-only)'
    ) in text
    assert digest.size.chars == len(text)
    assert digest.size.est_tokens == -(-len(text) // 4)


def test_unlisted_miner_refused(project: Project, world: list[str]) -> None:
    with pytest.raises(FactoryValidationError) as err:
        claims_digest(project, SelectionSpec())
    assert err.value.issues[0].field == "miner"


def test_held_out_scrub(
    project: Project,
    agent: Actor,
    mina: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mine(project, agent, mina, {0: [claim_row("finding")]}, world)
    plain = claims_digest(project, SelectionSpec()).papers[0]
    word = plain.title.split()[0]
    monkeypatch.setattr(
        cd, "held_out_tokens", lambda _p, include_work_ids=True: {word, "Lorem ipsum"}
    )
    scrubbed = claims_digest(project, SelectionSpec()).papers[0]
    assert word not in scrubbed.title.split() and "[withheld]" in scrubbed.title
    assert "Lorem ipsum" not in scrubbed.rows[0].claim_quote
    assert "[withheld]" in scrubbed.rows[0].claim_quote
    assert scrubbed.work_id == plain.work_id


def test_calibration_works_use_gold_else_calibration_rows(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    spec = replace(claims_spec(), regime=MinerRegime(2, 5, 0.8, 0.9))
    register_miner(project, miner_actor(SESSION_P, "claude-opus-5-5"), spec_to_json(spec))
    list_miner(project, agent, spec)
    drawn = draw_miner_calibration(project, human, "m-claims", 1, random_seed=11)
    works = [u.work_id for u in drawn.units]
    gold = claim_row("limitation", QUOTES[1])
    label_miner_calibration(
        project, human, drawn.calibration_id, works[0], [gold], channel=Channel.CLI
    )
    for work in works[1:]:  # an empty label counts as no gold
        label_miner_calibration(
            project, human, drawn.calibration_id, work, [], empty=True, channel=Channel.CLI
        )
    judge = miner_actor(SESSION_P2, "claude-sonnet-5-5")
    for _ in range(50):
        batch = mine_next(project, judge, "m-claims", 1, A, calibration=True).batch
        if batch is None:
            break
        mine_record(project, judge, batch.task_id, [claim_row("finding")], finish=True)
    digest = claims_digest(project, SelectionSpec())
    by_work = {p.work_id: p for p in digest.papers}
    assert [(r.claim_type, r.status) for r in by_work[works[0]].rows] == [("limitation", "gold")]
    for work in works[1:]:
        assert [(r.claim_type, r.status) for r in by_work[work].rows] == [
            ("finding", "calibration")
        ]
        assert by_work[work].gap is None
    assert "(gold)" in render_claims_digest(digest)


def test_pass_b_reviewed_to_empty_is_a_gap_not_pass_a_only(
    project: Project, agent: Actor, mina: Actor, minb: Actor, world: list[str]
) -> None:
    list_miner(project, agent, claims_spec())
    mine_pass(project, mina, A, lambda w: [claim_row("finding")], name="m-claims")
    before = claims_digest(project, SelectionSpec())
    assert {r.status for p in before.papers for r in p.rows} == {"pass-a-only"}
    mine_pass(project, minb, B, lambda w: [], name="m-claims")
    digest = claims_digest(project, SelectionSpec())
    assert all(p.rows == () and p.gap == "reviewed-empty" for p in digest.papers)
    assert "GAP: pass B reviewed" in render_claims_digest(digest)


def test_older_version_rows_are_tagged_and_counted(
    project: Project, agent: Actor, mina: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.model.extraction import MinerScope
    from factory.services import paper_profile as pp
    from factory.services.extraction import live_rows

    order = _mine(project, agent, mina, {0: [claim_row("finding")]}, world)
    live = live_rows(project, scope=MinerScope("m-claims"))
    monkeypatch.setattr(pp, "_row_versions", lambda _p, _n: {r.extraction_id: 0 for r in live})
    digest = claims_digest(project, SelectionSpec())
    first = digest.papers[0]
    assert first.work_id == order[0] and first.served_version == 0
    assert {r.version for r in first.rows} == {0} and digest.older_served == 1
    text = render_claims_digest(digest)
    assert f"## P01 {order[0]} (m-claims v0)" in text
    assert "served from an older version: 1" in text.splitlines()[0]
    assert all("(m-claims v" not in line for line in text.splitlines()[1:] if "P01" not in line)


def test_newer_version_only_is_a_stated_gap(
    project: Project, agent: Actor, mina: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.model.extraction import MinerScope
    from factory.services import paper_profile as pp
    from factory.services.extraction import live_rows

    order = _mine(project, agent, mina, {0: [claim_row("finding")]}, world)
    live = live_rows(project, scope=MinerScope("m-claims"))
    monkeypatch.setattr(pp, "_row_versions", lambda _p, _n: {r.extraction_id: 2 for r in live})
    digest = claims_digest(project, SelectionSpec())
    first = digest.papers[0]
    assert first.work_id == order[0] and first.rows == ()
    assert first.gap == "newer-version-only"
    assert "GAP: only rows of a newer version" in render_claims_digest(digest)


def test_every_claim_carries_the_key_and_version_sheets_validates(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    from factory.services.sheets import _claim_keys

    order = _mine(
        project,
        agent,
        mina,
        {0: [claim_row("limitation", QUOTES[0]), claim_row("finding", QUOTES[1])]},
        world,
    )
    digest = claims_digest(project, SelectionSpec())
    first = digest.papers[0]
    assert {r.row_key: r.version for r in first.rows} == _claim_keys(project, order[0])
    text = render_claims_digest(digest)
    for n, row in enumerate(first.rows, start=1):
        assert f"[P01.c{n} key={row.row_key}]" in text


def test_older_and_gold_rows_carry_their_keys(
    project: Project, agent: Actor, mina: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.model.extraction import MinerScope
    from factory.services import paper_profile as pp
    from factory.services.extraction import live_rows
    from factory.services.sheets import _claim_keys

    order = _mine(project, agent, mina, {0: [claim_row("finding")]}, world)
    live = live_rows(project, scope=MinerScope("m-claims"))
    monkeypatch.setattr(pp, "_row_versions", lambda _p, _n: {r.extraction_id: 0 for r in live})
    digest = claims_digest(project, SelectionSpec())
    [row] = digest.papers[0].rows
    assert row.version == 0 and _claim_keys(project, order[0]) == {row.row_key: 0}
    assert f"[P01.c1 key={row.row_key}]" in render_claims_digest(digest)
