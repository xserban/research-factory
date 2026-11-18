"""Hub flow payload and the named sets (plan hub-ui, step 3)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.services import hub_payloads as hp
from factory.services import site_corpus
from factory.services.context import Project
from factory.services.flow_ledger import LedgerRow
from factory.services.prisma import prisma_flow
from tests.fulltext_helpers import _ft_world
from tests.helpers import SourcesFor


def row(wid: str, **kw: object) -> LedgerRow:
    base: dict[str, object] = {
        "work_id": wid,
        "title": wid,
        "year": 2026,
        "source_group": "arxiv-only",
        "sources": [],
        "query_ids": [],
        "run_ids": [],
        "canonical_id": None,
        "merge_rule": None,
        "ta_outcome": "included",
        "ta_criterion": None,
        "ft_state": None,
        "ft_reasons": [],
        "ft_outcome": None,
        "ft_criterion": None,
    }
    base.update(kw)
    return LedgerRow.model_validate(base)


# ---------------------------------------------------------------- pure rules


def test_reconcile_sets_applies_the_three_lists() -> None:
    included = ["c1", "c2", "c3", "c4", "u1"]
    mined = ["c1", "dup2", "dup3", "dup1", "x1", "c4"]
    canonical_of = {"dup1": "c1", "dup2": "c2", "dup3": "c3"}
    # c1 is mined itself and through dup1; c2, c3 only through a duplicate
    s = hp.reconcile_sets(included, mined, canonical_of, {"x1": ("full_text", "EX01")})
    assert [(d.mined_id, d.canonical_id, d.canonical_also_mined) for d in s.duplicate_mapped] == [
        ("dup1", "c1", True),
        ("dup2", "c2", False),
        ("dup3", "c3", False),
    ]
    assert [(e.work_id, e.stage, e.criterion) for e in s.mined_but_excluded] == [
        ("x1", "full_text", "EX01")
    ]
    assert s.not_read_yet == ("u1",)
    assert s.miner_source("c1") == "c1"  # own rows win over the duplicate's
    assert s.miner_source("c2") == "dup2"
    assert s.miner_source("u1") == "u1"
    assert s.read_in_full == tuple(sorted(mined))


def test_unknown_excluded_stage_and_unread_duplicate_target() -> None:
    s = hp.reconcile_sets(["a"], ["z"], {}, None)
    assert s.mined_but_excluded == (hp.MinedButExcluded("z", "unknown", None),)
    assert s.not_read_yet == ("a",)


def test_duplicate_of_a_work_outside_included_is_not_a_source() -> None:
    s = hp.reconcile_sets(["a"], ["d"], {"d": "gone"})
    assert s.miner_source("a") == "a" and s.not_read_yet == ("a",)
    assert s.mined_but_excluded == ()


def test_included_ids_follow_the_stage() -> None:
    rows = [
        row("a", ft_state="retrieved", ft_outcome="included"),
        row("b", ft_state="retrieved", ft_outcome="excluded", ft_criterion="EX04"),
        row("c"),
        row("d", canonical_id="a", ta_outcome=None),
        row("e", ta_outcome="excluded", ta_criterion="EX01"),
    ]
    assert hp.included_ids(rows, True) == ["a"]
    assert hp.included_ids(rows, False) == ["a", "b", "c"]  # no stage: TA included, canonical


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"canonical_id": "z", "ta_outcome": None}, ("duplicate", None)),
        ({"ta_outcome": "excluded", "ta_criterion": "EX01"}, ("ta_excluded", "EX01")),
        ({"ta_outcome": "pending"}, ("ta_pending", None)),
        ({"ft_state": "not-sought"}, ("not_sought", None)),
        ({"ft_state": "attempted-failed"}, ("not_retrieved", None)),
        ({"ft_state": "retrieved", "ft_outcome": "included"}, ("included", None)),
        (
            {"ft_state": "retrieved", "ft_outcome": "excluded", "ft_criterion": "EX04"},
            ("ft_excluded", "EX04"),
        ),
        ({"ft_state": "retrieved", "ft_outcome": "pending"}, ("ft_pending", None)),
        ({"ft_state": "retrieved", "ft_outcome": "awaiting"}, ("ft_pending", None)),
    ],
)
def test_fate_of(kw: dict[str, object], expected: tuple[str, str | None]) -> None:
    assert hp.fate_of(row("w", **kw), True) == expected


def test_fate_without_full_text_stage_is_included_at_title_abstract() -> None:
    assert hp.fate_of(row("w"), False) == ("included", None)


# ---------------------------------------------------------------- on a screened project


def _miner_row(project: Project, eid: str, wid: str, schema: str) -> None:
    with project.index._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO extraction_rows (extraction_id, scope, pack, cited_extraction_id, "
                "cited_ordinal, cited_marker, work_id, pass_label, task_id, protocol_id, "
                "schema_ref, document_id, conversion_id, row_key, supersedes, superseded_by, "
                "event_id) VALUES (:e, 'evidence', NULL, NULL, NULL, NULL, :w, 'A', 't', 'p', "
                ":s, 'd', 'c', :e, NULL, NULL, 'e')"
            ),
            {"e": eid, "w": wid, "s": schema},
        )


@pytest.fixture
def listed_miners(monkeypatch: pytest.MonkeyPatch) -> None:
    schemas = {name: f"{name}@1" for name in site_corpus.DEFAULT_ROLES.values()}
    monkeypatch.setattr(site_corpus, "_listed_schemas", lambda _project: schemas)


def test_flow_payload_on_a_full_text_project(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    listed_miners: None,
) -> None:
    _ft_world(project, agent, human, mock_sources)
    flow = prisma_flow(project)
    pre = hp.load_flow_data(project)
    assert flow.full_text.stage_run
    # included equals PRISMA's final inclusion
    assert len(pre.sets.included) == flow.included_in_review
    included = list(pre.sets.included)
    excluded_ft = [r.work_id for r in pre.rows if r.ft_outcome == "excluded"]
    assert included and excluded_ft
    # one included work is read in full, one excluded-at-full-text work too, the rest unread
    _miner_row(project, "m1", included[0], "m-classification@1")
    _miner_row(project, "m2", excluded_ft[0], "m-classification@1")
    data = hp.load_flow_data(project)
    s = data.sets
    assert s.read_in_full == tuple(sorted([included[0], excluded_ft[0]]))
    assert [(e.work_id, e.stage) for e in s.mined_but_excluded] == [(excluded_ft[0], "full_text")]
    assert s.mined_but_excluded[0].criterion in {"EX04", "EX05"}
    assert s.not_read_yet == tuple(included[1:])
    assert s.duplicate_mapped == ()

    payload = hp.flow_payload(project, data)
    assert payload["prisma"]["included_in_review"] == len(included)
    # groups are exclusive and sum to the identified total
    assert payload["groups_sum"] == payload["identified"] == payload["records_total"]
    assert payload["reconciles"] is True
    groups = {g["key"]: g for g in payload["groups"]}
    assert groups["included"]["works"] == included
    assert sorted(groups["ft_excluded"]["works"]) == sorted(excluded_ft)
    by_c = groups["ft_excluded"]["by_criterion"]
    assert {c: v["n"] for c, v in by_c.items()} == flow.full_text.excluded
    assert groups["not_sought"]["n"] == flow.full_text.not_sought
    assert groups["not_retrieved"]["n"] == flow.full_text.not_retrieved
    assert groups["ft_pending"]["n"] == flow.full_text.pending
    assert groups["duplicate"]["n"] == flow.duplicates_removed
    assert groups["ta_excluded"]["n"] == sum(flow.excluded.values())
    ids = [w for g in payload["groups"] for w in g["works"]]
    assert len(ids) == len(set(ids))
    assert payload["sets"]["not_read_yet"] == included[1:]
    assert len(payload["records"]) == payload["records_total"]


def test_included_count_mismatch_is_refused(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ft_world(project, agent, human, mock_sources)
    monkeypatch.setattr(hp, "included_ids", lambda rows, stage_run: [])
    with pytest.raises(ValueError, match="ledger includes"):
        hp.load_flow_data(project)
