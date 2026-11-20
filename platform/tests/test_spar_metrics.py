"""Precision panel (spar night N9): every count is computed from the index; ratings are the
researcher's, a critic verdict is only compared with them."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.services import answers as an
from factory.services import hub_chat
from factory.services import sheets as sh
from factory.services import spar_metrics as sm
from factory.services.chat_candidates import CandidateInput as C
from factory.services.context import Project
from factory.services.selection import SelectionSpec, resolve_selection_cached
from tests.cli_helpers import _env
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)

ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"
SPEC = SelectionSpec()


def _arg(work: str, stance: str, strength: str, claim: str) -> sh.ArgumentInput:
    return sh.ArgumentInput(stance, work, ANCHOR, QUOTE, claim, strength)  # type: ignore[arg-type]


def _build(project: Project, agent: Actor, world: list[str]) -> list[str]:
    """One sheet: work 0 proposed by claims and keyword, work 1 by vector. Four arguments against
    (a0..a3) and two for (a4, a5); returns their ids in that order."""
    w = sorted(world)
    proposals = [
        C(w[0], "claims", "against", ANCHOR, QUOTE),
        C(w[0], "keyword", "for", ANCHOR, QUOTE),
        C(w[1], "vector", "against", ANCHOR, QUOTE),
    ]
    sheet = sh.open_sheet(project, agent, "Reflection helps", SPEC, proposals).sheet_id
    sh.record_arguments(
        project,
        agent,
        sheet,
        [
            _arg(w[0], "against", "strong", "c0"),
            _arg(w[0], "against", "moderate", "c1"),
            _arg(w[1], "against", "moderate", "c2"),
            _arg(w[1], "against", "weak", "c3"),
        ],
    )
    sh.close_section(project, agent, sheet, "against")
    sh.record_arguments(
        project,
        agent,
        sheet,
        [_arg(w[0], "for", "strong", "c4"), _arg(w[1], "for", "weak", "c5")],
    )
    sh.close_section(project, agent, sheet, "for")
    return _ids(project, sheet)


def _ids(project: Project, sheet: str) -> list[str]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT argument_id FROM sheet_arguments WHERE sheet_id = :s ORDER BY claim"),
            {"s": sheet},
        ).all()
    return [str(r[0]) for r in rows]


def _rate(project: Project, ids: list[str], ratings: list[str | None]) -> None:
    for argument, rating in zip(ids, ratings, strict=True):
        if rating:
            sh.rate_argument(project, project.human_actor(), argument, rating)


def _row(rows: tuple[sm.Row, ...], key: str) -> sm.Row:
    return next(r for r in rows if r.key == key)


def test_counts_by_every_dimension_on_a_known_world(
    project: Project, agent: Actor, world: list[str]
) -> None:
    ids = _build(project, agent, world)
    _rate(project, ids, ["sound", "sound", "weak", "wrong", "sound", None])
    got = sm.precision(project)
    assert got.arguments["all"][0] == sm.Row("all", 3, 1, 1, 1, 5, 0.6)
    stance = got.arguments["stance"]
    assert (_row(stance, "against").sound, _row(stance, "against").rated) == (2, 4)
    assert (_row(stance, "for").sound, _row(stance, "for").rated, _row(stance, "for").unrated) == (
        1,
        1,
        1,
    )
    # an argument with several sources counts in each; the vector one only under vector
    source = got.arguments["source"]
    assert _row(source, "claims").sound == 3 and _row(source, "claims").rated == 3
    assert _row(source, "keyword").rated == 3  # work 0: c0, c1, c4 (all rated)
    assert _row(source, "vector").weak == 1 and _row(source, "vector").wrong == 1
    strength = got.arguments["strength"]
    assert _row(strength, "strong").sound == 2
    assert _row(strength, "moderate").rated == 2
    assert _row(strength, "weak").unrated == 1 and _row(strength, "weak").wrong == 1
    assert [r.key for r in got.arguments["model"]] == ["claude-opus-5-5"]
    assert [r.key for r in got.arguments["engine"]] == ["v1"]
    assert got.arguments["role"] == ()


def test_unrated_is_counted_but_not_in_precision_and_few_ratings_show_no_percentage(
    project: Project, agent: Actor, world: list[str]
) -> None:
    ids = _build(project, agent, world)
    _rate(project, ids, ["sound", "sound", None, None, None, None])
    row = sm.precision(project).arguments["all"][0]
    assert (row.rated, row.unrated, row.precision) == (2, 4, None)
    assert sm.show_precision(row) == "— (n=2)"
    _rate(project, ids[2:3], ["weak"])
    row = sm.precision(project).arguments["all"][0]
    assert row.rated == 3 and row.precision == pytest.approx(2 / 3)
    assert sm.show_precision(row) == "67% (n=3)"


def test_sheet_filter_and_since(project: Project, agent: Actor, world: list[str]) -> None:
    ids = _build(project, agent, world)
    _rate(project, ids, ["sound"] * 6)
    assert sm.precision(project, sheet_ids=["sht_none"]).arguments["all"][0].rated == 0
    assert sm.precision(project, since="2999-01-01").arguments["all"][0].rated == 0
    assert sm.precision(project, since="2000-01-01").arguments["all"][0].rated == 6


def _v2(project: Project, ids: list[str]) -> None:
    """Turn the world's sheet into a v2 one with critic checks (index rows, test only)."""
    with project.index.connect() as conn:
        sheet = str(
            conn.execute(
                text("SELECT sheet_id FROM sheet_arguments WHERE argument_id = :a"), {"a": ids[0]}
            ).scalar_one()
        )
    verdicts = ["holds", "holds", "overreaches", "misread", "holds", "overreaches"]
    with project.index.connect() as conn, conn.begin():
        conn.execute(
            text(
                "INSERT INTO chat_requests (request_id, kind, selection, engine, actor, ts, "
                "event_id) VALUES ('chr_x','spar','{}','v2','a','t','e0')"
            )
        )
        conn.execute(
            text("UPDATE sheets SET request_id = 'chr_x' WHERE sheet_id = :s"), {"s": sheet}
        )
        for i, (argument, verdict) in enumerate(zip(ids, verdicts, strict=True)):
            conn.execute(
                text(
                    "INSERT INTO argument_checks (event_id, argument_id, sheet_id, request_id, "
                    "run_id, verdict, reason, actor, ts) VALUES (:e, :a, :s, 'chr_x', 'run_x', "
                    ":v, 'r', 'ag', 't')"
                ),
                {"e": f"ev{i:02d}", "a": argument, "s": sheet, "v": verdict},
            )
        # a later check of the first argument stands: misread
        conn.execute(
            text(
                "INSERT INTO argument_checks (event_id, argument_id, sheet_id, request_id, "
                "run_id, verdict, reason, actor, ts) VALUES ('ev99', :a, :s, 'chr_x', 'run_x', "
                "'misread', 'r', 'ag', 't')"
            ),
            {"a": ids[0], "s": sheet},
        )


def test_v2_engine_role_and_critic_agreement(
    project: Project, agent: Actor, world: list[str]
) -> None:
    ids = _build(project, agent, world)
    _rate(project, ids, ["sound", "sound", "weak", "wrong", "weak", None])
    _v2(project, ids)
    got = sm.precision(project)
    assert [r.key for r in got.arguments["engine"]] == ["v2"]
    assert {r.key for r in got.arguments["role"]} == {"against", "for"}
    ag = got.agreement
    # latest check stands: a0 misread/sound, a1 holds/sound, a2 overreaches/weak,
    # a3 misread/wrong, a4 holds/weak; a5 is unrated and left out
    assert ag.n == 5 and ag.agreed == 3
    assert ag.table["misread"]["sound"] == 1 and ag.table["holds"]["weak"] == 1
    assert ag.raw == pytest.approx(0.6)
    assert ag.kappa is None  # n < 10


def test_cohen_kappa_on_a_fixed_table() -> None:
    table = {
        "holds": {"sound": 4, "weak": 1, "wrong": 0},
        "overreaches": {"sound": 0, "weak": 3, "wrong": 0},
        "misread": {"sound": 0, "weak": 1, "wrong": 1},
    }
    ag = sm.agreement_of(table)
    assert ag.n == 10 and ag.agreed == 8 and ag.raw == pytest.approx(0.8)
    assert ag.kappa == pytest.approx(0.43 / 0.63)
    small = sm.agreement_of({"holds": {"sound": 1, "weak": 0, "wrong": 0}})
    assert small.raw is None and small.kappa is None
    # a table where chance agreement is 1 has no kappa
    same = {"holds": {"sound": 12, "weak": 0, "wrong": 0}}
    assert sm.agreement_of(same).kappa is None


def test_answer_sentence_ratings_by_model(project: Project, agent: Actor, world: list[str]) -> None:
    w = sorted(world)
    digest = resolve_selection_cached(project, SPEC).digest
    sentences = [an.SentenceInput(f"s{i}", w[0], ANCHOR, QUOTE) for i in range(4)]
    a = an.record_answer(project, agent, "Does it help?", SPEC, digest, sentences).answer_id
    human = project.human_actor()
    for i, rating in enumerate(["sound", "sound", "wrong"]):
        an.rate_answer(project, human, a, rating, sentence=i)
    got = sm.precision(project)
    total = got.answers["all"][0]
    assert (total.sound, total.wrong, total.unrated, total.rated) == (2, 1, 1, 3)
    assert total.precision == pytest.approx(2 / 3)
    assert got.answers["model"][0].key == "claude-opus-5-5"


def test_cli_prints_the_tables(
    project: Project, agent: Actor, world: list[str], settings: Settings
) -> None:
    ids = _build(project, agent, world)
    _rate(project, ids, ["sound", "sound", "weak", "wrong", "sound", None])
    out = CliRunner().invoke(
        app, ["--project", "demo", "chat", "precision"], env=_env(settings.root)
    )
    assert out.exit_code == 0, out.output
    assert "By stance" in out.output and "against" in out.output
    assert "60% (n=5)" in out.output
    assert "Critic against researcher" in out.output


def test_hub_payload_carries_the_precision_tables(
    project: Project, agent: Actor, world: list[str]
) -> None:
    ids = _build(project, agent, world)
    _rate(project, ids, ["sound", "sound", "weak", "wrong", "sound", None])
    p = hub_chat.chat_payload(project)["precision"]
    assert p["arguments"]["all"][0]["precision_text"] == "60% (n=5)"
    assert p["arguments"]["stance"][0]["key"] in ("against", "for")
    assert "agreement" in p and "answers" in p and p["measures"]["precision"]


def test_the_chat_page_renders_the_precision_section_escaped() -> None:
    from importlib import resources

    from factory.services import hub_ui

    src = resources.files("factory.hub_ui").joinpath("pages/chat.js").read_text(encoding="utf-8")
    assert "ch-precision" in src and "paintPrecision" in src
    assert "esc(x.key)" in src and "esc(x.precision_text)" in src and "esc(v)" in src
    assert "pages/chat.js" in hub_ui.ASSETS and "chat" in hub_ui.PAGES["chat"].payloads


def test_an_argument_whose_paper_has_no_candidate_falls_under_unknown_source(
    project: Project, agent: Actor, world: list[str]
) -> None:
    w = sorted(world)
    sheet = sh.open_sheet(
        project, agent, "Reflection helps", SPEC, [C(w[0], "claims", "against", ANCHOR, QUOTE)]
    ).sheet_id
    sh.record_arguments(
        project,
        agent,
        sheet,
        [_arg(w[0], "against", "strong", "c0"), _arg(w[1], "against", "weak", "c1")],
    )
    got = sm.precision(project)
    assert _row(got.arguments["source"], "unknown").unrated == 1
    assert _row(got.arguments["source"], "claims").unrated == 1


def test_the_hub_precision_is_cached_on_the_event_log_signature(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _build(project, agent, world)
    calls: list[int] = []
    real = sm.precision

    def counting(*a: object, **k: object) -> sm.Precision:
        calls.append(1)
        return real(*a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(sm, "precision", counting)
    hub_chat._PRECISION.clear()
    first = hub_chat.precision_payload(project)
    first["arguments"]["all"].clear()  # a caller's change must not reach the cache
    second = hub_chat.precision_payload(project)
    assert len(calls) == 1 and second["arguments"]["all"]
    _rate(project, ids[:1], ["sound"])
    assert hub_chat.precision_payload(project)["arguments"]["all"][0]["rated"] == 1
    assert len(calls) == 2


def test_the_texts_say_what_role_since_and_sheet_mean() -> None:
    assert "stance of the argument" in sm.MEASURES["role"]
    assert "left out" in sm.MEASURES["since"]
