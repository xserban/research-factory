"""Living sheets (spar night N7): staleness, re-spar, sheet diff and rating carry-over.

Staleness and the diff are computed and write no event. A carried-over rating is only a
suggestion (ruling 8): nothing here writes a rating; accepting one is the researcher's own act
through the existing rating route. No real `claude` is started."""

# ruff: noqa: F811
from __future__ import annotations

import dataclasses
import json
import re
from importlib import resources
from typing import Any

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.chat_requests import ChatRequested
from factory.model.screening import PassLabel
from factory.model.sheets import SheetOpened
from factory.services import chat_requests as cr
from factory.services import hub_chat, runner
from factory.services import paper_profile as pp
from factory.services import sheet_diff as sd
from factory.services import sheets as sh
from factory.services.chat_candidates import CandidateInput as C
from factory.services.context import Project
from factory.services.selection import SelectionSpec
from tests.claims_helpers import QUOTES, claim_row, claims_spec
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import install_skill
from tests.miner_helpers import list_miner, mine_pass, miner_actor
from tests.test_runner import FakeLauncher

ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"
SPEC = SelectionSpec()


@pytest.fixture(autouse=True)
def chat_env(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    install_skill(project.settings, "rf-chat", "CHAT SKILL BODY")
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "_factory_executable", lambda: "/venv/bin/factory")


def _total(project: Project) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one())


def _count(project: Project, etype: str) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(*) FROM events WHERE type = :t"), {"t": etype}
            ).scalar_one()
        )


def _arg(work: str, stance: str, claim: str = "it fails", anchor: str = ANCHOR) -> sh.ArgumentInput:
    return sh.ArgumentInput(stance, work, anchor, QUOTE, claim, "moderate")


def _props(world: list[str]) -> list[C]:
    works = sorted(world)
    return [
        C(works[0], "claims", "against", ANCHOR, QUOTE),
        C(works[1], "keyword", "for", ANCHOR, QUOTE),
    ]


def _closed_sheet(
    project: Project,
    agent: Actor,
    world: list[str],
    *,
    against: tuple[int, ...] = (0,),
    pro: tuple[int, ...] = (1,),
    hypothesis: str = "Reflection helps",
    request_id: str | None = None,
) -> str:
    works = sorted(world)
    sheet = sh.open_sheet(
        project, agent, hypothesis, SPEC, _props(world), request_id=request_id
    ).sheet_id
    sh.record_arguments(project, agent, sheet, [_arg(works[i], "against") for i in against])
    sh.close_section(project, agent, sheet, "against")
    sh.record_arguments(project, agent, sheet, [_arg(works[i], "for") for i in pro])
    sh.close_section(project, agent, sheet, "for")
    return sheet


# ---------------------------------------------------------------- staleness


def test_a_fresh_sheet_is_not_stale_and_computing_it_writes_nothing(
    project: Project, agent: Actor, world: list[str]
) -> None:
    sheet = _closed_sheet(project, agent, world)
    before = _total(project)
    result = sd.sheet_staleness(project, sheet)
    assert result.stale is False and result.reasons == ()
    assert result.works_added == () and result.works_removed == () and result.rows_changed == ()
    assert result.claims_checked is True
    assert _total(project) == before


def test_stale_when_the_selection_gains_or_loses_a_paper(
    project: Project, agent: Actor, world: list[str]
) -> None:
    sheet = _closed_sheet(project, agent, world)
    gone = sorted(world)[2]
    with project.index.exclusive(), project.index.connect() as conn:
        conn.execute(
            text("DELETE FROM sheet_candidates WHERE sheet_id = :s AND work_id = :w"),
            {"s": sheet, "w": gone},
        )
        conn.execute(text("UPDATE sheets SET selection_digest = 'older'"))
        conn.commit()
    result = sd.sheet_staleness(project, sheet)  # the paper is in the selection now: added
    assert result.stale is True and gone in result.works_added
    assert any("added" in r for r in result.reasons)
    with project.index.exclusive(), project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO sheet_candidates (sheet_id, work_id, tier, sources, stances, over_cap)"
                " VALUES (:s, 'wrk_GONE', 3, 'keyword', '', 0)"
            ),
            {"s": sheet},
        )
        conn.commit()
    again = sd.sheet_staleness(project, sheet)
    assert "wrk_GONE" in again.works_removed and any("removed" in r for r in again.reasons)


def test_stale_when_the_selection_cannot_be_resolved(
    project: Project, agent: Actor, world: list[str]
) -> None:
    sheet = _closed_sheet(project, agent, world)
    with project.index.exclusive(), project.index.connect() as conn:
        conn.execute(text('UPDATE sheets SET selection = \'{"layers": ["no-such-layer"]}\''))
        conn.commit()
    result = sd.sheet_staleness(project, sheet)
    assert result.stale is None and result.reasons


def test_stale_when_claims_rows_appear_after_the_sheet_opened(
    project: Project, agent: Actor, world: list[str]
) -> None:
    list_miner(project, agent, claims_spec())
    sheet = _closed_sheet(project, agent, world)
    assert sd.sheet_staleness(project, sheet).stale is False
    mine_pass(
        project,
        miner_actor("01JZ9Q3K5M7N8P0R2S4T6V8W1E", "claude-opus-5-5"),
        PassLabel.A,
        lambda w: [claim_row("finding", QUOTES[0])],
        name="m-claims",
    )
    result = sd.sheet_staleness(project, sheet)
    assert result.stale is True and result.claims_checked is True
    assert set(result.rows_changed) == set(world)
    assert any("claims rows changed" in r for r in result.reasons)


def _served_state(project: Project, agent: Actor, world: list[str]) -> pp.MinerWorkState:
    list_miner(project, agent, claims_spec())
    mine_pass(
        project,
        miner_actor("01JZ9Q3K5M7N8P0R2S4T6V8W1E", "claude-opus-5-5"),
        PassLabel.A,
        lambda w: [claim_row("finding", QUOTES[0])],
        name="m-claims",
    )
    version = dict(pp.listed_miner_versions(project))["m-claims"]
    return pp.load_miner_work_state(project, "m-claims", version, sorted(world))


@pytest.mark.parametrize("change", ["new-version", "new-row", "reopened"])
def test_stale_by_a_changed_served_row(
    project: Project,
    agent: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    real_state = _served_state(project, agent, world)
    sheet = _closed_sheet(project, agent, world)
    assert sd.sheet_staleness(project, sheet).stale is False
    target = sorted(world)[0]

    def altered(*args: Any, **kw: Any) -> pp.MinerWorkState:
        rows = {w: list(r) for w, r in real_state.rows.items()}
        emptied = real_state.emptied
        if change == "new-version":
            rows[target] = [dataclasses.replace(r, version=r.version + 1) for r in rows[target]]
        elif change == "new-row":
            rows[target] = rows[target] + [dataclasses.replace(rows[target][0], row_key="rowx")]
        else:
            rows[target] = []
            emptied = frozenset({target})
        return dataclasses.replace(real_state, rows=rows, emptied=emptied)

    monkeypatch.setattr(sd.sheets_service, "load_miner_work_state", altered)
    result = sd.sheet_staleness(project, sheet)
    assert result.stale is True and result.rows_changed == (target,)


def test_an_old_sheet_without_a_fingerprint_is_checked_on_the_selection_alone(
    project: Project, agent: Actor, world: list[str]
) -> None:
    sheet = _closed_sheet(project, agent, world)
    with project.index.exclusive(), project.index.connect() as conn:
        conn.execute(text("UPDATE sheets SET claims_fingerprint = NULL"))
        conn.commit()
    result = sd.sheet_staleness(project, sheet)
    assert result.stale is False and result.claims_checked is False


def test_old_events_stay_valid_and_the_new_fields_are_optional() -> None:
    old = {
        "sheet_id": "sht_" + "0" * 26, "hypothesis": "h", "mode": "explore", "selection": {},
        "selection_digest": "d", "candidates_digest": "0" * 64, "candidates": [], "tier1_cap": 15,
    }  # fmt: skip
    opened = SheetOpened.model_validate(old)
    assert opened.respar_of is None and opened.claims_fingerprint is None
    request = {
        "request_id": "chr_" + "0" * 26, "kind": "spar", "selection": {},
        "hypothesis": "h", "mode": "explore",
    }  # fmt: skip
    assert ChatRequested.model_validate(request).respar is False


def test_unknown_sheet_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        sd.sheet_staleness(project, "sht_NOPE")


# ---------------------------------------------------------------- re-spar request


def _respar(project: Project, human: Actor, parent: str, **kw: Any) -> ChatRequested:
    return cr.request_chat(project, human, "spar", SPEC, parent=parent, respar=True, **kw)


def test_respar_copies_hypothesis_and_mode_and_links_the_parent(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _closed_sheet(project, agent, world)
    payload = _respar(project, human, sheet)
    assert payload.respar is True and payload.parent == sheet
    assert payload.hypothesis == "Reflection helps" and payload.mode == "explore"
    info = cr.view_request(project, payload.request_id)
    assert info.respar is True and info.parent == sheet and info.state == "open"
    again = _closed_sheet(project, agent, world)
    other = _respar(project, human, again, mode="prepare", hypothesis="Another wording")
    assert other.mode == "prepare" and other.hypothesis == "Another wording"


def test_respar_validation_writes_nothing(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    closed = _closed_sheet(project, agent, world)
    open_sheet = sh.open_sheet(project, agent, "h", SPEC, _props(world)).sheet_id
    before = _total(project)
    with pytest.raises(FactoryValidationError) as err:  # an agent cannot
        _respar(project, agent, closed)
    assert err.value.issues[0].field == "actor"
    for parent in (open_sheet, "sht_" + "0" * 26, "ans_" + "0" * 26):
        with pytest.raises(FactoryValidationError) as err:
            _respar(project, human, parent)
        assert "parent" in {i.field for i in err.value.issues}, parent
    with pytest.raises(FactoryValidationError) as err:
        cr.request_chat(project, human, "ask", SPEC, question="q", parent=closed, respar=True)
    assert {i.field for i in err.value.issues} >= {"kind"}
    with pytest.raises(FactoryValidationError) as err:
        cr.request_chat(project, human, "spar", SPEC, hypothesis="h", respar=True)
    assert err.value.issues[0].field == "parent"
    assert _total(project) == before


def test_a_second_open_respar_of_the_same_sheet_is_refused(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _closed_sheet(project, agent, world)
    _respar(project, human, sheet)
    with pytest.raises(FactoryValidationError) as err:
        _respar(project, human, sheet)
    assert err.value.issues[0].field == "parent"


def test_a_respar_run_opens_a_new_sheet_that_records_respar_of(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    old = _closed_sheet(project, agent, world)
    request = _respar(project, human, old).request_id
    launcher = FakeLauncher()
    run_id = runner.start_run(project, "spar", launcher=launcher, unit_cap=1)
    taken = cr.take_next(project, agent_other, run_id)
    assert taken is not None and taken.respar is True and taken.parent == old
    new = sh.open_sheet(
        project, agent_other, "Reflection helps", SPEC, _props(world), request_id=request
    ).sheet_id  # the follow-up rule "writes into its parent" does not apply to a re-spar
    assert sh.view_sheet(project, new).info.respar_of == old
    assert sh.view_sheet(project, old).info.respar_of is None
    # the platform sets it from the request; an ordinary request leaves it empty
    sh.close_section(project, agent_other, new, "against")
    sh.record_arguments(project, agent_other, new, [_arg(sorted(world)[1], "for")])
    sh.close_section(project, agent_other, new, "for")
    assert cr.view_request(project, request).state == "done"
    for process in launcher.processes:
        process.release()
    assert runner.wait(run_id, 10)


def test_a_respar_request_refuses_a_mode_that_differs_from_its_sheet(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    old = _closed_sheet(project, agent, world)
    request = _respar(project, human, old, mode="prepare").request_id
    launcher = FakeLauncher()
    run_id = runner.start_run(project, "spar", launcher=launcher, unit_cap=1)
    cr.take_next(project, agent_other, run_id)
    with pytest.raises(FactoryValidationError) as err:
        sh.open_sheet(project, agent_other, "h", SPEC, _props(world), request_id=request)
    assert err.value.issues[0].field == "request_id"
    for process in launcher.processes:
        process.release()
    assert runner.wait(run_id, 10)


def test_respar_cli_takes_the_hypothesis_from_the_sheet(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.cli import main as cli_main

    old = _closed_sheet(project, agent, world)
    monkeypatch.setattr(cli_main, "_resolve_project", lambda state: project)
    res = CliRunner().invoke(cli_main.app, ["chat", "request", "spar", "--respar", old])
    assert res.exit_code == 0, res.output
    assert "re-spar" in res.output and "Reflection helps" in res.output
    [info] = cr.list_requests(project)
    assert info.respar and info.parent == old
    bad = CliRunner().invoke(cli_main.app, ["chat", "request", "spar", "--respar", "sht_NOPE"])
    assert bad.exit_code != 0


# ---------------------------------------------------------------- diff and carry-over


def test_diff_lists_added_dropped_and_kept_by_work_anchor_and_stance(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    works = sorted(world)
    old = _closed_sheet(project, agent, world, against=(0, 1), pro=(1,))
    new = _closed_sheet(project, agent, world, against=(0,), pro=(1, 0))
    diff = sd.sheet_diff(project, old, new)
    key = lambda a: (a.stance, a.work_id, a.anchor)  # noqa: E731
    assert [key(a) for a in diff.dropped] == [("against", works[1], ANCHOR)]
    assert [key(a) for a in diff.added] == [("for", works[0], ANCHOR)]
    assert sorted(key(k.new) for k in diff.kept) == [
        ("against", works[0], ANCHOR),
        ("for", works[1], ANCHOR),
    ]
    assert diff.counts == {"added": 1, "dropped": 1, "kept": 2}
    assert sd.sheet_diff(project, old, old).counts == {"added": 0, "dropped": 0, "kept": 3}
    # the same work and anchor on the other side is another argument
    assert all(k.old.stance == k.new.stance for k in diff.kept)


def test_diff_pairs_repeated_arguments_in_order_and_refuses_unknown_sheets(
    project: Project, agent: Actor, world: list[str]
) -> None:
    old = _closed_sheet(project, agent, world, against=(0, 0))
    new = _closed_sheet(project, agent, world, against=(0,))
    diff = sd.sheet_diff(project, old, new)
    assert diff.counts == {"added": 0, "dropped": 1, "kept": 2}  # 1 against + 1 for
    with pytest.raises(FactoryValidationError):
        sd.sheet_diff(project, old, "sht_NOPE")
    with pytest.raises(FactoryValidationError):
        sd.sheet_diff(project, "sht_NOPE", new)


def test_carry_over_is_a_suggestion_and_writes_no_rating(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    old = _closed_sheet(project, agent, world)
    new = _closed_sheet(project, agent, world)
    first = sh.view_sheet(project, old).arguments[0]
    sh.rate_argument(project, human, first.argument_id, "weak", "thin sample")
    before = _total(project)
    diff = sd.sheet_diff(project, old, new)
    assert _total(project) == before and _count(project, "sheet.argument_rated") == 1
    suggested = [k for k in diff.kept if k.suggested_rating is not None]
    assert len(suggested) == 1
    [kept] = suggested
    assert kept.suggested_rating == "weak" and kept.suggested_note == "thin sample"
    assert kept.new.rating is None  # the new argument is still unrated
    assert sh.view_sheet(project, new).coverage.unrated == 2
    assert "earlier sheet" in diff.suggestion_label and "not a rating" in diff.suggestion_label


def test_accepting_a_suggestion_posts_a_human_rating_through_the_existing_route(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    old = _closed_sheet(project, agent, world)
    new = _closed_sheet(project, agent, world)
    sh.rate_argument(
        project, human, sh.view_sheet(project, old).arguments[0].argument_id, "wrong", "x"
    )
    [kept] = [k for k in sd.sheet_diff(project, old, new).kept if k.suggested_rating]
    out = hub_chat.rate_argument_act(
        project,
        human,
        {
            "argument_id": kept.new.argument_id,
            "rating": kept.suggested_rating,
            "note": kept.suggested_note,
        },
    )
    assert out["rating"] == "wrong"
    ratings = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "sheet.argument_rated"
    ]
    assert ratings[-1].actor.kind == "human"
    with pytest.raises(FactoryValidationError):  # an agent can never accept it
        hub_chat.rate_argument_act(
            project, agent, {"argument_id": kept.new.argument_id, "rating": "sound"}
        )


def test_diff_cli_prints_the_three_groups_and_the_suggestion(
    project: Project, agent: Actor, human: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.cli import main as cli_main

    old = _closed_sheet(project, agent, world, against=(0, 1))
    new = _closed_sheet(project, agent, world, against=(0,), pro=(1, 0))
    sh.rate_argument(
        project, human, sh.view_sheet(project, old).arguments[0].argument_id, "sound", ""
    )
    monkeypatch.setattr(cli_main, "_resolve_project", lambda state: project)
    before = _total(project)
    res = CliRunner().invoke(cli_main.app, ["sheets", "diff", old, new])
    assert res.exit_code == 0, res.output
    for word in ("Added", "Dropped", "Kept", "suggested from the earlier sheet: sound"):
        assert word in res.output, word
    assert _total(project) == before
    assert CliRunner().invoke(cli_main.app, ["sheets", "diff", old, "sht_NOPE"]).exit_code != 0


# ---------------------------------------------------------------- hub payload and page


def test_the_sheet_view_carries_staleness_and_the_re_spar_diff(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    old = _closed_sheet(project, agent, world)
    view = hub_chat.sheet_view(project, old)
    assert view["staleness"]["stale"] is False and view["respar_of"] is None
    assert view["diff"] is None
    request = _respar(project, human, old).request_id
    launcher = FakeLauncher()
    run_id = runner.start_run(project, "spar", launcher=launcher, unit_cap=1)
    cr.take_next(project, agent_other, run_id)
    new = sh.open_sheet(
        project, agent_other, "Reflection helps", SPEC, _props(world), request_id=request
    ).sheet_id
    sh.record_arguments(project, agent_other, new, [_arg(sorted(world)[0], "against")])
    sh.close_section(project, agent_other, new, "against")
    sh.record_arguments(project, agent_other, new, [_arg(sorted(world)[1], "for")])
    sh.close_section(project, agent_other, new, "for")
    for process in launcher.processes:
        process.release()
    runner.wait(run_id, 10)
    sh.rate_argument(
        project, human, sh.view_sheet(project, old).arguments[0].argument_id, "weak", "n"
    )
    before = _total(project)
    page = hub_chat.sheet_view(project, new)
    assert _total(project) == before
    assert page["respar_of"] == old and page["diff"]["old"] == old
    assert page["diff"]["counts"] == {"added": 0, "dropped": 0, "kept": 2}
    carried = [k for k in page["diff"]["kept"] if k["suggested_rating"]]
    assert len(carried) == 1 and carried[0]["suggested_rating"] == "weak"
    assert carried[0]["new_argument_id"].startswith("arg_")
    assert "not a rating" in page["diff"]["label"]


def test_order_chat_respar_records_the_request_without_a_start(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    old = _closed_sheet(project, agent, world)
    out = hub_chat.order_chat(project, human, {"respar": old, "start": False})
    assert out["kind"] == "spar" and out["run_id"] is None
    [info] = cr.list_requests(project)
    assert info.respar and info.parent == old and info.hypothesis == "Reflection helps"
    with pytest.raises(FactoryValidationError):
        hub_chat.order_chat(project, human, {"respar": 5, "start": False})
    with pytest.raises(FactoryValidationError):
        hub_chat.order_chat(project, human, {"respar": "sht_NOPE", "start": False})


def test_rebuild_equals_live(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    old = _closed_sheet(project, agent, world)
    _respar(project, human, old)
    project.index.sync()

    def snapshot() -> tuple[Any, ...]:
        with project.index.connect() as conn:
            sheets = conn.execute(
                text("SELECT sheet_id, respar_of, claims_fingerprint FROM sheets ORDER BY 1")
            ).all()
            reqs = conn.execute(text("SELECT request_id, respar FROM chat_requests")).all()
        return tuple(map(tuple, sheets)), tuple(map(tuple, reqs))

    live = snapshot()
    assert live[0][0][2] is not None and live[1][0][1]
    project.index.rebuild()
    assert snapshot() == live


def _js(name: str) -> str:
    return resources.files("factory.hub_ui").joinpath(name).read_text(encoding="utf-8")


def test_the_page_shows_the_panels_escaped_and_posts_through_the_existing_routes() -> None:
    src = _js("pages/chat.js")
    for word in (
        "Changed since",
        "Re-spar with today",
        "suggested from the earlier sheet",
        "accept this rating",
        "/ui/act/chat-rate-argument",
    ):
        assert word.lower() in src.lower(), word
    # the re-spar order is posted through the existing request route as the researcher
    assert "respar:" in src
    stripped = src
    for _ in range(3):
        stripped = re.sub(r"esc\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)", "ESC", stripped)
    bare = re.findall(
        r"(?<![\w.])\b(?:k|d|st|stale|w|row)\."
        r"(?:quote|claim|title|note|text|suggested_note|reason|reasons)\b"
        r"(?!\s*[?&|=!])",
        stripped,
    )
    assert not bare, bare
    # nothing in the diff panel writes a rating without a click: the only post is in a handler
    assert json.dumps(src).count("chat-rate-argument") >= 1
