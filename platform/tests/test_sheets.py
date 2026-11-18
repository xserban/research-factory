"""Argument sheets: events, folds, guards, computed coverage, ratings (plan chat T7)."""

# ruff: noqa: F811
import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.sheets import SheetArgumentRecorded, SheetSectionClosed
from factory.services import sheets as sh
from factory.services.chat_candidates import CandidateInput as C
from factory.services.context import Project
from factory.services.selection import SelectionSpec
from tests.claims_helpers import QUOTES, claim_row, claims_spec
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)
from tests.miner_helpers import list_miner, mine_pass, miner_actor

ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"
SPEC = SelectionSpec()


def _prop(work: str, source: str = "claims", stance: str = "against") -> C:
    quoted = source in ("claims", "keyword")
    return C(work, source, stance, *((ANCHOR, QUOTE) if quoted else (None, None)))


def _arg(work: str, stance: str = "against", **kw: str | None) -> sh.ArgumentInput:
    base = {"anchor": ANCHOR, "quote": QUOTE, "claim": "it fails", "strength": "moderate"}
    return sh.ArgumentInput(stance, work, **{**base, **kw})  # type: ignore[arg-type]


def _open(project: Project, agent: Actor, world: list[str], mode: str = "explore") -> str:
    works = sorted(world)
    proposals = [_prop(works[0]), _prop(works[0], "keyword", "for"), _prop(works[1])]
    payload = sh.open_sheet(
        project,
        agent,
        "Reflection helps",
        SPEC,
        proposals,
        mode=mode,  # type: ignore[arg-type]
    )
    return payload.sheet_id


def _count(project: Project, table: str) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def _events(project: Project) -> int:
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one())


def test_open_records_computed_table_and_provenance(
    project: Project, agent: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    view = sh.view_sheet(project, sheet)
    works = sorted(world)
    cov = view.coverage
    assert cov.total == len(world) and cov.by_tier == {1: 1, 2: 1, 3: len(world) - 2}
    assert cov.by_source == {"claims": 2, "keyword": 1}
    assert cov.tier1_unargued == (works[0],) and cov.works_without_claims_source == len(world) - 2
    assert len(view.info.candidates_digest) == 64 and view.info.mode == "explore"
    with project.index.connect() as conn:
        model, skill, blob = conn.execute(
            text("SELECT model, skill, input_blob FROM events WHERE type = 'sheet.opened'")
        ).one()
    assert model == agent.model and skill == agent.skill and str(blob).startswith("sha256:")
    assert [s.sheet_id for s in sh.list_sheets(project)] == [sheet]


def test_open_refused_for_non_agent_and_bad_input_writes_nothing(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    before = _events(project)
    with pytest.raises(FactoryValidationError) as err:
        sh.open_sheet(project, human, "h", SPEC, [])
    assert err.value.issues[0].field == "actor"
    with pytest.raises(FactoryValidationError) as err2:
        sh.open_sheet(project, agent, " ", SPEC, [_prop(world[0], "claims")], supersedes="sht_X")
    assert {i.field for i in err2.value.issues} == {"hypothesis", "supersedes"}
    bad = C(world[0], "claims", "against", ANCHOR, "not in the paper")
    with pytest.raises(FactoryValidationError) as err3:
        sh.open_sheet(project, agent, "h", SPEC, [bad])
    assert err3.value.issues[0].field == "proposals[0].quote"
    assert _events(project) == before and _count(project, "sheets") == 0


def test_unverified_quote_refused_nothing_written(
    project: Project, agent: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    before = _events(project)
    good, bad = _arg(sorted(world)[0]), _arg(sorted(world)[0], quote="never said this")
    with pytest.raises(FactoryValidationError) as err:
        sh.record_arguments(project, agent, sheet, [good, bad])
    assert [i.field for i in err.value.issues] == ["arguments[1].quote"]
    assert _events(project) == before and _count(project, "sheet_arguments") == 0


def test_argument_recorded_with_verified_conversion_and_provenance(
    project: Project, agent: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    [recorded] = sh.record_arguments(project, agent, sheet, [_arg(sorted(world)[0])])
    assert isinstance(recorded, SheetArgumentRecorded)
    assert recorded.conversion_id.startswith("cnv_") and len(recorded.markdown_hash) > 8
    view = sh.view_sheet(project, sheet)
    [a] = view.arguments
    assert (a.stance, a.strength, a.model) == ("against", "moderate", agent.model)
    assert view.coverage.tier1_unargued == () and view.coverage.works_argued["against"] == 1
    with project.index.connect() as conn:
        blob = conn.execute(
            text("SELECT input_blob FROM events WHERE type = 'sheet.argument_recorded'")
        ).scalar_one()
    assert str(blob).startswith("sha256:")


def test_other_issues_are_located(project: Project, agent: Actor, world: list[str]) -> None:
    sheet = _open(project, agent, world)
    works = sorted(world)
    outside = _arg("rf:nobody-1", strength="huge", claim=" ")
    with pytest.raises(FactoryValidationError) as err:
        sh.record_arguments(project, agent, sheet, [outside])
    fields = {i.field for i in err.value.issues}
    assert {"arguments[0].strength", "arguments[0].claim"} <= fields
    with pytest.raises(FactoryValidationError) as err2:
        sh.record_arguments(project, agent, sheet, [_arg(works[0], claim_row_key="rk_nope")])
    assert [i.field for i in err2.value.issues] == ["arguments[0].claim_row_key"]
    with pytest.raises(FactoryValidationError) as err3:
        sh.record_arguments(project, agent, "sht_NOPE", [_arg(works[0])])
    assert err3.value.issues[0].field == "sheet_id"


def test_for_refused_until_against_closed(project: Project, agent: Actor, world: list[str]) -> None:
    sheet = _open(project, agent, world)
    work = sorted(world)[0]
    with pytest.raises(FactoryValidationError) as err:
        sh.record_arguments(project, agent, sheet, [_arg(work, "for")])
    assert "close the section against" in err.value.issues[0].reason
    with pytest.raises(FactoryValidationError):
        sh.close_section(project, agent, sheet, "for")
    sh.record_arguments(project, agent, sheet, [_arg(work)])
    closed = sh.close_section(project, agent, sheet, "against")
    assert isinstance(closed, SheetSectionClosed)
    with pytest.raises(FactoryValidationError):  # closed once
        sh.close_section(project, agent, sheet, "against")
    with pytest.raises(FactoryValidationError):  # against takes no more
        sh.record_arguments(project, agent, sheet, [_arg(work)])
    sh.record_arguments(project, agent, sheet, [_arg(work, "for", strength="weak")])  # explore
    view = sh.view_sheet(project, sheet)
    assert view.coverage.arguments == {"against": 1, "for": 1}
    assert view.info.against_closed and not view.info.for_closed


def test_prepare_for_section_needs_another_session(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world, mode="prepare")
    work = sorted(world)[0]
    sh.record_arguments(project, agent, sheet, [_arg(work)])
    sh.close_section(project, agent, sheet, "against")
    with pytest.raises(FactoryValidationError) as err:
        sh.record_arguments(project, agent, sheet, [_arg(work, "for")])
    assert err.value.issues[0].field == "session"
    sh.record_arguments(project, agent_other, sheet, [_arg(work, "for")])
    assert sh.view_sheet(project, sheet).coverage.arguments["for"] == 1


def test_mixed_stances_in_one_call_refused(
    project: Project, agent: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    work = sorted(world)[0]
    with pytest.raises(FactoryValidationError) as err:
        sh.record_arguments(project, agent, sheet, [_arg(work), _arg(work, "for")])
    assert err.value.issues[0].field == "arguments"


def test_claim_row_key_must_be_a_claims_row(
    project: Project, agent: Actor, world: list[str]
) -> None:
    list_miner(project, agent, claims_spec())
    from factory.model.screening import PassLabel

    mina = miner_actor("01JZ9Q3K5M7N8P0R2S4T6V8W1E", "claude-opus-5-5")
    mine_pass(
        project, mina, PassLabel.A, lambda w: [claim_row("finding", QUOTES[0])], name="m-claims"
    )
    sheet = _open(project, agent, world)
    work = sorted(world)[0]
    from factory.model.extraction import MinerScope
    from factory.services.extraction import live_rows

    key = next(
        r.row_key for r in live_rows(project, scope=MinerScope("m-claims")) if r.work_id == work
    )
    [ok] = sh.record_arguments(project, agent, sheet, [_arg(work, claim_row_key=key)])
    assert ok.claim_row_key == key and ok.claim_row_version == 1


def test_rating_is_human_only_latest_stands(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    [one, two] = sh.record_arguments(
        project, agent, sheet, [_arg(sorted(world)[0]), _arg(sorted(world)[1])]
    )
    with pytest.raises(FactoryValidationError):
        sh.rate_argument(project, agent, one.argument_id, "sound")
    with pytest.raises(FactoryValidationError):
        sh.rate_argument(project, human, one.argument_id, "great")
    with pytest.raises(FactoryValidationError):
        sh.rate_argument(project, human, "arg_NOPE", "sound")
    sh.rate_argument(project, human, one.argument_id, "weak", "thin")
    sh.rate_argument(project, human, one.argument_id, "sound")
    cov = sh.view_sheet(project, sheet).coverage
    assert cov.ratings == {"sound": 1, "weak": 0, "wrong": 0} and cov.unrated == 1
    assert two.argument_id != one.argument_id


def test_projection_guards_ignore_hand_written_events(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    """An event no service wrote (a `for` argument before `against` closed, a rating by an agent)
    stays in the log and folds nothing."""
    sheet = _open(project, agent, world)
    work = sorted(world)[0]
    [real] = sh.record_arguments(project, agent, sheet, [_arg(work)])
    forged = real.model_copy(update={"argument_id": "arg_" + "0" * 26, "stance": "for"})
    from factory.model.sheets import SheetArgumentRated

    rating = SheetArgumentRated(argument_id=real.argument_id, sheet_id=sheet, rating="wrong")
    blob = project.blobs.put_json({"forged": True})
    with project.index.exclusive():
        project.record(
            [
                project.events.make("sheet.argument_recorded", forged, agent, input_blob=blob),
                project.events.make("sheet.argument_rated", rating, agent, input_blob=blob),
            ]
        )
    assert _count(project, "sheet_arguments") == 1 and _count(project, "sheet_ratings") == 0


def test_rebuild_keeps_the_sheet(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    [one] = sh.record_arguments(project, agent, sheet, [_arg(sorted(world)[0])])
    sh.close_section(project, agent, sheet, "against")
    sh.rate_argument(project, human, one.argument_id, "sound")
    before = sh.view_sheet(project, sheet)
    project.index.rebuild()
    assert sh.view_sheet(project, sheet) == before


def _forge(project: Project, actor: Actor, payload: SheetArgumentRecorded) -> None:
    blob = project.blobs.put_json({"forged": True})
    with project.index.exclusive():
        project.record(
            [project.events.make("sheet.argument_recorded", payload, actor, input_blob=blob)]
        )


def test_projection_ignores_argument_for_a_work_outside_the_sheet(
    project: Project, agent: Actor, world: list[str]
) -> None:
    """The fold checks (sheet, work) membership; quote and row-key checks are service-only."""
    sheet = _open(project, agent, world)
    [real] = sh.record_arguments(project, agent, sheet, [_arg(sorted(world)[0])])
    outside = real.model_copy(update={"argument_id": "arg_" + "1" * 26, "work_id": "w_nowhere"})
    before = sh.view_sheet(project, sheet).coverage
    _forge(project, agent, outside)
    assert _count(project, "sheet_arguments") == 1
    assert sh.view_sheet(project, sheet).coverage == before


def test_argument_records_the_version_its_row_was_served_from(
    project: Project,
    agent: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factory.model.extraction import MinerScope
    from factory.model.screening import PassLabel
    from factory.services import paper_profile as pp
    from factory.services.extraction import live_rows

    list_miner(project, agent, claims_spec())
    mina = miner_actor("01JZ9Q3K5M7N8P0R2S4T6V8W1E", "claude-opus-5-5")
    mine_pass(
        project, mina, PassLabel.A, lambda w: [claim_row("finding", QUOTES[0])], name="m-claims"
    )
    sheet = _open(project, agent, world)
    work = sorted(world)[0]
    rows = [r for r in live_rows(project, scope=MinerScope("m-claims")) if r.work_id == work]
    key = rows[0].row_key
    [listed] = sh.record_arguments(project, agent, sheet, [_arg(work, claim_row_key=key)])
    assert listed.claim_row_version == 1
    labels = {r.extraction_id: 0 for r in live_rows(project, scope=MinerScope("m-claims"))}
    monkeypatch.setattr(pp, "_row_versions", lambda _p, _n: labels)
    [older] = sh.record_arguments(project, agent, sheet, [_arg(work, claim_row_key=key)])
    assert older.claim_row_version == 0
    views = {a.argument_id: a for a in sh.view_sheet(project, sheet).arguments}
    assert views[listed.argument_id].claim_row_version == 1
    assert views[older.argument_id].claim_row_version == 0


def test_stale_selection_refused_nothing_written(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    sheet = _open(project, agent, world)
    real = sh.resolve_selection_cached
    monkeypatch.setattr(sh, "resolve_selection_cached", lambda p, s: replace(real(p, s), digest="x"))
    before = _events(project)
    with pytest.raises(FactoryValidationError) as err:
        sh.record_arguments(project, agent, sheet, [_arg(sorted(world)[0])])
    assert "selection changed" in err.value.issues[0].reason
    assert _events(project) == before and _count(project, "sheet_arguments") == 0


def test_projection_prepare_split_ignores_for_by_the_session_that_wrote_against(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world, mode="prepare")
    work = sorted(world)[0]
    [real] = sh.record_arguments(project, agent, sheet, [_arg(work)])
    sh.close_section(project, agent, sheet, "against")
    same = real.model_copy(update={"argument_id": "arg_" + "2" * 26, "stance": "for"})
    _forge(project, agent, same)
    assert _count(project, "sheet_arguments") == 1
    other = real.model_copy(update={"argument_id": "arg_" + "3" * 26, "stance": "for"})
    _forge(project, agent_other, other)
    assert _count(project, "sheet_arguments") == 2


def test_projection_ignores_for_before_against_is_closed(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world, mode="prepare")
    [real] = sh.record_arguments(project, agent, sheet, [_arg(sorted(world)[0])])
    early = real.model_copy(update={"argument_id": "arg_" + "4" * 26, "stance": "for"})
    _forge(project, agent_other, early)
    assert _count(project, "sheet_arguments") == 1


def test_prepare_mode_without_a_session_is_not_split_safe(
    project: Project, agent: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world, mode="prepare")
    work = sorted(world)[0]
    [real] = sh.record_arguments(project, agent, sheet, [_arg(work)])
    sh.close_section(project, agent, sheet, "against")
    nameless = agent.model_copy(update={"session": None})
    with pytest.raises(FactoryValidationError) as err:
        sh.record_arguments(project, nameless, sheet, [_arg(work, "for")])
    assert err.value.issues[0].field == "session"
    # (an event with no session does not even parse, so the fold's None guard is defensive only)
    assert _count(project, "sheet_arguments") == 1 and real.sheet_id == sheet
