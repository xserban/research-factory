"""Contradiction map (night feature N10): proposals between two m-claims rows with verified
quotes, and the hub payload that groups the pairs by topic."""

# ruff: noqa: F811
from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import MinerScope
from factory.model.findings import ContradictionInput, ContradictionProposed
from factory.model.screening import PassLabel
from factory.services import finders
from factory.services import hub_contradictions as hc
from factory.services.context import Project
from factory.services.extraction import live_rows
from tests.claims_helpers import QUOTES, claim_row, claims_spec
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)
from tests.miner_helpers import list_miner, mine_pass, miner_actor


def _refs(project: Project, agent: Actor, world: list[str]) -> tuple[str, str]:
    list_miner(project, agent, claims_spec())
    mina = miner_actor("01JZ9Q3K5M7N8P0R2S4T6V8W1E", "claude-opus-5-5")
    mine_pass(
        project, mina, PassLabel.A, lambda w: [claim_row("finding", QUOTES[0])], name="m-claims"
    )
    works = sorted(world)[:2]
    keys = {r.work_id: r.row_key for r in live_rows(project, scope=MinerScope("m-claims"))}
    return tuple(hc.row_ref(w, keys[w]) for w in works)  # type: ignore[return-value]


def _events(project: Project, kind: str) -> list[dict[str, object]]:
    from factory.events.reader import read_all

    return [
        dict(e.payload)
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == kind
    ]


def test_row_refs_are_stored_with_verified_quote_and_anchor(
    project: Project, agent: Actor, world: list[str]
) -> None:
    a, b = _refs(project, agent, world)
    ident, new = finders.propose_contradiction(
        project, agent, ContradictionInput(ref_a=a, ref_b=b, note="opposite direction")
    )
    assert new
    [payload] = _events(project, "contradiction.proposed")
    p = ContradictionProposed.model_validate(payload)
    assert p.contradiction_id == ident
    assert (p.quote_a, p.quote_b) == (QUOTES[0], QUOTES[0])
    assert (p.anchor_a, p.anchor_b) == ("s3.p1", "s3.p1")
    again, new2 = finders.propose_contradiction(
        project, agent, ContradictionInput(ref_a=b, ref_b=a, note="same pair")
    )
    assert (again, new2) == (ident, False)


def test_unknown_row_key_is_refused_and_writes_nothing(
    project: Project, agent: Actor, world: list[str]
) -> None:
    a, _b = _refs(project, agent, world)
    bad = hc.row_ref(sorted(world)[1], "no-such-key")
    with pytest.raises(FactoryValidationError) as err:
        finders.propose_contradiction(
            project, agent, ContradictionInput(ref_a=a, ref_b=bad, note="x")
        )
    assert [(i.field, i.reason) for i in err.value.issues] == [("ref_b", "ref-unknown")]
    assert _events(project, "contradiction.proposed") == []


def test_old_events_without_anchors_stay_valid() -> None:
    old = {
        "contradiction_id": "ctr_01JZ9Q3K5M7N8P0R2S4T6V8W1E",
        "ref_a": "clm_01JZ9Q3K5M7N8P0R2S4T6V8W1E",
        "ref_b": "clm_01JZ9Q3K5M7N8P0R2S4T6V8W1F",
        "work_a": "rf:a-negative-1-73bc34f9",
        "work_b": "rf:b-negative-1-73bc34f8",
        "quote_a": "q",
        "quote_b": "r",
        "note": "n",
    }
    p = ContradictionProposed.model_validate(old)
    assert p.anchor_a is None and p.anchor_b is None


def test_payload_groups_by_topic_with_state_counts_and_seed(
    project: Project, agent: Actor, other_session_human: Actor, world: list[str]
) -> None:
    a, b = _refs(project, agent, world)
    ident, _ = finders.propose_contradiction(
        project, agent, ContradictionInput(ref_a=a, ref_b=b, note="opposite")
    )
    out = hc.contradictions_payload(project)
    assert out["counts"] == {"proposed": 1, "accepted": 0, "rejected": 0, "stale": 0, "all": 1}
    [topic] = out["topics"]
    assert topic["topic"] == "a" and topic["count"] == 1
    [pair] = topic["pairs"]
    assert pair["id"] == ident and pair["state"] == "proposed"
    assert pair["note"] == "opposite"
    for side in (pair["a"], pair["b"]):
        assert side["quote"] == QUOTES[0] and side["anchor"] == "s3.p1"
        assert side["paragraph"] and QUOTES[0] in side["paragraph"]
        assert side["row_key"] and side["work_id"] in world
    assert pair["seed"]["selection"]["include"] == sorted(
        [pair["a"]["work_id"], pair["b"]["work_id"]]
    )
    assert pair["seed"]["selection"]["layers"] == ["core"]
    assert pair["seed"]["hypothesis"] == pair["a"]["claim"]
    assert pair["decide"] == {
        "confirm": f"factory contradictions confirm {ident} --rationale '...'",
        "reject": f"factory contradictions reject {ident} --rationale '...'",
    }
    # a researcher's decision moves the pair; the proposer's own event does not
    # (the human actor is a different session)
    finders.decide_contradiction(
        project, other_session_human, ident, "confirm", "same topic, opposite result"
    )
    out = hc.contradictions_payload(project)
    assert out["counts"]["accepted"] == 1 and out["counts"]["proposed"] == 0
    assert out["topics"][0]["pairs"][0]["state"] == "accepted"


def test_empty_payload_is_ready_and_counts_zero(project: Project) -> None:
    out = hc.contradictions_payload(project)
    assert out["ready"] is True and out["topics"] == [] and out["counts"]["all"] == 0


def test_page_is_registered_and_built() -> None:
    from factory.services import hub_build, hub_ui

    assert "contradictions" in hub_ui.PAGES
    assert hub_ui.PAGES["contradictions"].payloads == ("shell", "contradictions")
    assert "contradictions" in hub_build.BUILDERS


# --- review fixes: pinned conversion, one load per work, staleness, refusals ---


def _propose(project: Project, agent: Actor, world: list[str]) -> tuple[str, str, str]:
    a, b = _refs(project, agent, world)
    ident, _ = finders.propose_contradiction(
        project, agent, ContradictionInput(ref_a=a, ref_b=b, note="opposite")
    )
    return ident, a, b


def test_conversion_and_about_are_stored_with_the_proposal(
    project: Project, agent: Actor, world: list[str]
) -> None:
    from factory.services.document_read import default_conversion

    _propose(project, agent, world)
    [payload] = _events(project, "contradiction.proposed")
    p = ContradictionProposed.model_validate(payload)
    for work, conversion, about in (
        (p.work_a, p.conversion_a, p.about_a),
        (p.work_b, p.conversion_b, p.about_b),
    ):
        current = default_conversion(project, work)
        assert current is not None and conversion == current.conversion_id
        assert about == "a"


def test_paragraph_is_read_from_the_pinned_conversion(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from tests.extraction_helpers import _new_document_version

    _propose(project, agent, world)
    [payload] = _events(project, "contradiction.proposed")
    p = ContradictionProposed.model_validate(payload)
    _new_document_version(project, p.work_a)
    real = hc.conversion_manifest

    def manifest(project_: Project, conversion_id: str) -> object:
        if conversion_id in (p.conversion_a, p.conversion_b):
            return real(project_, conversion_id)
        return SimpleNamespace(get=lambda anchor: SimpleNamespace(text="A different paragraph."))

    monkeypatch.setattr(hc, "conversion_manifest", manifest)
    [topic] = hc.contradictions_payload(project)["topics"]
    side = topic["pairs"][0]["a"]
    assert QUOTES[0] in side["paragraph"] and "different" not in side["paragraph"]


def test_served_rows_are_loaded_once_per_work_per_call(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _propose(project, agent, world)
    calls: list[list[str]] = []
    real = finders.load_miner_work_rows

    def counting(project_: Project, name: str, version: int, works: list[str]):  # type: ignore[no-untyped-def]
        calls.append(list(works))
        return real(project_, name, version, works)

    monkeypatch.setattr(finders, "load_miner_work_rows", counting)
    monkeypatch.setattr(hc, "load_miner_work_rows", counting, raising=False)
    hc.contradictions_payload(project)
    loaded = [w for c in calls for w in c]
    assert sorted(loaded) == sorted(set(loaded)) and len(loaded) == 2


def _reserve(monkeypatch: pytest.MonkeyPatch, **change: str) -> None:
    """Serve every m-claims row with its claim_quote quote or anchor changed."""
    from dataclasses import replace

    real = finders.load_miner_work_rows

    def changed(project_: Project, name: str, version: int, works: list[str]):  # type: ignore[no-untyped-def]
        rows, emptied = real(project_, name, version, works)
        out = {}
        for work, listed in rows.items():
            fixed = []
            for r in listed:
                value, unit, anchor, quote = r.fields["claim_quote"]
                entry = (
                    change.get("quote", value),
                    unit,
                    change.get("anchor", anchor),
                    change.get("quote", quote),
                )
                fixed.append(replace(r, fields={**r.fields, "claim_quote": entry}))
            out[work] = fixed
        return out, emptied

    monkeypatch.setattr(finders, "load_miner_work_rows", changed)


@pytest.mark.parametrize("change", [{"quote": "Lorem ipsum, reworded"}, {"anchor": "s3.p2"}])
def test_pair_is_stale_when_the_served_row_changed(
    project: Project,
    agent: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, str],
) -> None:
    _propose(project, agent, world)
    _reserve(monkeypatch, **change)
    [view] = finders.list_contradictions(project, states=("stale",))
    assert view.state == "stale"
    out = hc.contradictions_payload(project)
    assert out["counts"]["stale"] == 1
    [topic] = out["topics"]
    assert topic["topic"] == "a"  # the stored topic, not "no topic recorded"


def test_unverified_quote_is_refused_for_a_row_ref(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = _refs(project, agent, world)
    _reserve(monkeypatch, quote="not in the paragraph at all")
    with pytest.raises(FactoryValidationError) as err:
        finders.propose_contradiction(
            project, agent, ContradictionInput(ref_a=a, ref_b=b, note="x")
        )
    assert {i.field for i in err.value.issues} == {"ref_a", "ref_b"}
    assert all(i.reason.startswith("quote-not-verified") for i in err.value.issues)
    assert _events(project, "contradiction.proposed") == []


def test_decide_on_a_row_ref_pair_needs_a_human_of_another_session(
    project: Project, agent: Actor, other_session_human: Actor, world: list[str]
) -> None:
    ident, _a, _b = _propose(project, agent, world)
    with pytest.raises(FactoryValidationError) as err:
        finders.decide_contradiction(project, agent, ident, "confirm", "r")
    assert [(i.field, i.reason) for i in err.value.issues] == [("actor", "human-only")]
    same = other_session_human.model_copy(update={"session": agent.session})
    with pytest.raises(FactoryValidationError) as err2:
        finders.decide_contradiction(project, same, ident, "confirm", "r")
    assert [(i.field, i.reason) for i in err2.value.issues] == [("actor", "proposer-session")]


def test_highlight_offsets_follow_the_quote_normalisation() -> None:
    from factory.document.quotes import quote_span

    text, span = quote_span(
        "Intro &amp; **bold** text\n\nSecond  paragraph here", "paragraph  here"
    )
    assert span is not None and text[span[0] : span[1]] == "paragraph here"
    assert quote_span("alpha", "beta")[1] is None
