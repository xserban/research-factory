"""The claims digest (plan chat T6): order, codes, gaps, status, scrub, render, size."""

# ruff: noqa: F811
import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput
from factory.model.screening import PassLabel
from factory.services import claims_digest as cd
from factory.services.claims_digest import claims_digest, render_claims_digest
from factory.services.context import Project
from factory.services.selection import SelectionSpec
from tests.claims_helpers import QUOTES, claim_row, claims_spec
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)
from tests.miner_helpers import SESSION_M1, SESSION_M2, list_miner, mine_pass, miner_actor

A, B = PassLabel.A, PassLabel.B


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
    assert (
        '- limitation | a | higher | empirical | strong: "Lorem ipsum" [s3.p1] '
        '[conditions: "sit amet" [s3.p1]] (pass-a-only)'
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
