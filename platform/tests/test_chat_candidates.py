"""Candidate proposals: validation, tiers, the Explore cap, coverage (plan chat T6)."""

# ruff: noqa: F811
import pytest

from factory.errors import FactoryValidationError
from factory.services.chat_candidates import CandidateInput as C
from factory.services.chat_candidates import chat_candidates
from factory.services.context import Project
from factory.services.selection import SelectionSpec
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)

ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"
SPEC = SelectionSpec()


def _p(work: str, source: str = "claims", stance: str = "against", **kw: str | None) -> C:
    quote = {"anchor": ANCHOR, "quote": QUOTE} if source in ("claims", "keyword") else {}
    return C(work, source, stance, **{**quote, **kw})  # type: ignore[arg-type]


def _issues(project: Project, proposals: list[C], **kw: object) -> dict[str, str]:
    with pytest.raises(FactoryValidationError) as err:
        chat_candidates(project, SPEC, proposals, **kw)  # type: ignore[arg-type]
    return {i.field: i.reason for i in err.value.issues}


def test_tiers_and_coverage(project: Project, world: list[str]) -> None:
    a, b, c, d = world[:4]
    result = chat_candidates(
        project,
        SPEC,
        [
            _p(a, "claims"),
            _p(a, "keyword", "for"),  # two sources: tier 1
            _p(b, "claims"),  # one source: tier 2
            _p(c, "researcher", "for"),  # researcher: tier 1
            _p(d, "claims"),
            _p(d, "claims"),  # same source twice: still one source
        ],
    )
    by = {x.work_id: x for x in result.candidates}
    assert [x.work_id for x in result.candidates] == sorted(world)
    assert (by[a].tier, by[b].tier, by[c].tier, by[d].tier) == (1, 2, 1, 2)
    assert by[a].sources == ("claims", "keyword") and by[a].stances == ("against", "for")
    assert all(x.tier == 3 for w, x in by.items() if w not in {a, b, c, d})
    assert result.total == len(world) and sum(result.by_tier.values()) == len(world)
    assert result.by_tier == {1: 2, 2: 2, 3: len(world) - 4}
    assert result.by_stance == {"against": 3, "for": 2}
    assert result.proposals == 6 and result.over_cap == 0


def test_cap_in_explore_only_and_ordering(project: Project, world: list[str]) -> None:
    works = sorted(world)
    proposals = [_p(w, "claims") for w in works[:5]] + [_p(w, "keyword") for w in works[:5]]
    proposals.append(_p(works[7], "researcher"))
    capped = chat_candidates(project, SPEC, proposals, tier1_cap=3)
    over = [x.work_id for x in capped.candidates if x.over_cap]
    # researcher pick first, then by work id among two-source works
    assert over == works[2:5]
    assert capped.by_tier[1] == 6 and capped.over_cap == 3
    assert all(x.tier == 1 for x in capped.candidates if x.over_cap)
    prepare = chat_candidates(project, SPEC, proposals, mode="prepare", tier1_cap=3)
    assert prepare.over_cap == 0 and not any(x.over_cap for x in prepare.candidates)


def test_researcher_pick_alone_is_tier_one_and_deterministic(
    project: Project, world: list[str]
) -> None:
    one = chat_candidates(project, SPEC, [_p(world[0], "researcher", note="my pick")])
    assert next(x for x in one.candidates if x.work_id == world[0]).tier == 1
    assert one.candidates[0].notes in {("my pick",), ()}
    two = chat_candidates(project, SPEC, [_p(world[0], "researcher", note="my pick")])
    assert one == two


def test_no_proposals_everything_tier_three(project: Project, world: list[str]) -> None:
    result = chat_candidates(project, SPEC, [])
    assert result.by_tier == {1: 0, 2: 0, 3: len(world)} and result.by_stance == {
        "against": 0,
        "for": 0,
    }


def test_refusals_with_field_paths(project: Project, world: list[str]) -> None:
    first = world[0]
    issues = _issues(
        project,
        [
            _p(first),  # 0 fine
            _p("rf:nope"),  # 1 unknown work
            _p(first, "claims", "against", quote=None, anchor=None),  # 2 quote missing
            _p(first, "claims", "against", anchor=ANCHOR, quote="not in the anchor at all"),  # 3
            _p(first, "claims", "against", anchor="s99.p9"),  # 4 anchor missing
            C(first, "oracle", "against"),  # 5 unknown source
            C(first, "researcher", "maybe"),  # 6 unknown stance
            C(first, "miner", "for", anchor=ANCHOR),  # 7 anchor without quote
        ],
    )
    assert "proposals[0].work_id" not in issues
    assert "unknown work" in issues["proposals[1].work_id"]
    assert "quote is required" in issues["proposals[2].quote"]
    assert "quote-not-in-anchor" in issues["proposals[3].quote"]
    assert "anchor-missing" in issues["proposals[4].quote"]
    assert "unknown source" in issues["proposals[5].source"]
    assert "unknown stance" in issues["proposals[6].stance"]
    assert "proposals[7].quote" in issues


def test_work_outside_selection_refused(project: Project, world: list[str]) -> None:
    out = world[0]
    with pytest.raises(FactoryValidationError) as err:
        chat_candidates(project, SelectionSpec(exclude=[out]), [_p(out)])
    [issue] = err.value.issues
    assert issue.field == "proposals[0].work_id" and "not in the selection" in issue.reason


def test_bad_mode_and_cap_refused(project: Project, world: list[str]) -> None:
    issues = _issues(project, [], mode="wild", tier1_cap=0)
    assert set(issues) == {"mode", "tier1_cap"}


def test_nothing_written(project: Project, world: list[str]) -> None:
    def events() -> list[bytes]:
        return [p.read_bytes() for p in sorted(project.paths.events_dir.rglob("*")) if p.is_file()]

    before = events()
    chat_candidates(project, SPEC, [_p(world[0])])
    assert events() == before
