"""Support resolution: eligibility and refusal reasons (slice 7b, plan W-A, task 2; ruling 2).

Most conditions are real events; where an event cannot produce the state (a superseded claim
needs a second extraction pass) the test edits the projection row, as `set_year` does elsewhere.
"""

# ruff: noqa: F811

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.drafts import SentenceClass, parse_support
from factory.services.context import Project
from factory.services.supports import REASONS, ResolvedSupport, resolve_supports
from tests.contribution_helpers import ctr_a, ctr_b, ext_a, screened  # noqa: F401
from tests.intuition_helpers import (
    CPT1,
    INT1,
    INT2,
    concept_reviewed,
    concept_source,
    defined,
    record_event,
    recorded,
    reviewed,
    reviewer,
    source_decided,
)
from tests.views_b_helpers import ext_b  # noqa: F401
from tests.writing_helpers import WWorld, ww  # noqa: F401

CLAIM, SYNTH, INTERP = SentenceClass.CLAIM, SentenceClass.SYNTHESIS, SentenceClass.INTERPRETIVE


def one(project: Project, ref: str, cls: SentenceClass = CLAIM) -> ResolvedSupport:
    return resolve_supports(project, [parse_support(ref)], cls=cls)[0]


def sql(project: Project, statement: str, **params: Any) -> None:
    with project.index.connect() as conn:
        conn.execute(text(statement), params)
        conn.commit()


def test_reasons_are_the_closed_list() -> None:
    assert REASONS == (
        "unknown",
        "superseded",
        "stale",
        "not-included",
        "not-final",
        "inferred",
        "rejected",
        "unreviewed",
        "class-not-allowed",
    )


def test_live_claim_is_eligible_with_its_quote(project: Project, ww: WWorld) -> None:
    got = one(project, ww.claim(0))
    assert got.eligible and got.reason is None
    assert got.work_ids == (ww.works[0],)
    assert got.spans == ("Lorem ipsum dolor sit amet.",)


def test_unknown_claim_refused(project: Project, ww: WWorld) -> None:
    got = one(project, "claim:clm_01JZ9Q3K5M7N8P0R2S4T6V8W99")
    assert (got.eligible, got.reason) == (False, "unknown")


def test_superseded_claim_refused(project: Project, ww: WWorld) -> None:
    sql(
        project,
        "UPDATE extraction_claims SET superseded_by = 'clm_X' WHERE claim_id = :c",
        c=ww.claims[ww.works[0]],
    )
    assert one(project, ww.claim(0)).reason == "superseded"


def test_claim_of_pass_b_is_not_final(project: Project, ww: WWorld) -> None:
    sql(
        project,
        "UPDATE extraction_claims SET pass_label = 'B' WHERE claim_id = :c",
        c=ww.claims[ww.works[0]],
    )
    assert one(project, ww.claim(0)).reason == "not-final"


def test_claim_of_excluded_work_refused(project: Project, ww: WWorld) -> None:
    sql(
        project,
        "UPDATE extraction_claims SET work_id = 'rf:out-of-corpus' WHERE claim_id = :c",
        c=ww.claims[ww.works[0]],
    )
    assert one(project, ww.claim(0)).reason == "not-included"


def test_claim_on_a_replaced_document_is_stale(project: Project, ww: WWorld) -> None:
    sql(
        project,
        "UPDATE extraction_claims SET document_id = 'doc_OLD' WHERE claim_id = :c",
        c=ww.claims[ww.works[0]],
    )
    got = one(project, ww.claim(0))
    # a claim pinned to a document that is no longer the work's current one is stale
    assert got.reason == "stale"


def test_cell_of_a_final_row_is_eligible(project: Project, ww: WWorld) -> None:
    got = one(project, ww.cell(0))
    assert got.eligible and len(got.group_ids) == 1
    assert got.spans == ("2",)
    assert got.method_names == ("lorem",)


def test_bare_row_key_means_value(project: Project, ww: WWorld) -> None:
    bare = ww.rows[ww.works[0]]
    assert one(project, bare).ref.ref == f"{bare}/value"
    assert one(project, bare).eligible


def test_cell_numbers_include_canonical_and_printed(project: Project, ww: WWorld) -> None:
    got = one(project, ww.cell(0))
    assert Decimal("2") in got.numbers


def test_unknown_cell_and_unknown_field_refused(project: Project, ww: WWorld) -> None:
    assert one(project, "cell:rk_ffffffffffff/value").reason == "unknown"
    assert one(project, ww.cell(0, "no_such_field")).reason == "unknown"


def test_cell_not_final_refused(project: Project, ww: WWorld) -> None:
    key = ww.rows[ww.works[0]]
    sql(
        project,
        "UPDATE extraction_rows SET row_key = :k WHERE row_key = :o AND pass_label = 'A'",
        k="rk_aaaaaaaaaaaa",
        o=key,
    )
    sql(
        project,
        "UPDATE extraction_rows SET row_key = :k WHERE row_key = :o",
        k="rk_bbbbbbbbbbbb",
        o=key,
    )
    assert one(project, "cell:rk_aaaaaaaaaaaa/value").reason == "not-final"


def test_cell_of_a_retracted_work_refused(
    project: Project, ww: WWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    import factory.services.supports as supports

    states = {ww.works[0]: SimpleNamespace(synthesis="excluded")}
    monkeypatch.setattr(supports, "work_states", lambda _p: states)
    assert one(project, ww.cell(0)).reason == "not-included"
    assert one(project, ww.claim(0)).reason == "not-included"
    assert one(project, ww.cell(1)).eligible


def test_item_final_is_eligible_and_unknown_refused(project: Project, ww: WWorld) -> None:
    got = one(project, f"item:{ww.base_item}")
    assert got.eligible and got.work_ids == (ww.works[0],)
    assert one(project, "item:ext_01JZ9Q3K5M7N8P0R2S4T6V8W99").reason == "unknown"
    assert (
        one(project, f"item:{next(iter(ww.claims.values())).replace('clm_', 'ext_')}").reason
        == "unknown"
    )


def test_item_superseded_refused(project: Project, ww: WWorld) -> None:
    sql(
        project,
        "UPDATE extraction_rows SET superseded_by = 'ext_X' WHERE extraction_id = :i",
        i=ww.base_item,
    )
    assert one(project, f"item:{ww.base_item}").reason == "superseded"


def test_confirmed_edge_eligible_inferred_refused(project: Project, ww: WWorld) -> None:
    assert one(project, f"edge:{ww.confirmed_edge}").eligible
    got = one(project, f"edge:{ww.inferred_edge}")
    assert (got.eligible, got.reason) == (False, "inferred")


def test_edge_unknown_and_rejected(project: Project, ww: WWorld) -> None:
    assert one(project, "edge:rel_01JZ9Q3K5M7N8P0R2S4T6V8W99").reason == "unknown"
    from factory.model.lineage import LineageDecision
    from factory.services.relations import decide_relation

    decide_relation(
        project, reviewer(project), ww.inferred_edge, LineageDecision.REJECT, "not a base"
    )
    assert one(project, f"edge:{ww.inferred_edge}").reason == "rejected"


def test_group_support(project: Project, ww: WWorld) -> None:
    gid = one(project, ww.cell(0)).group_ids[0]
    got = one(project, f"group:{gid}")
    assert got.eligible and len(got.work_ids) == 4
    assert one(project, "group:grp_ffffffffffff").reason == "unknown"


def test_stat_values(project: Project, ww: WWorld) -> None:  # also in test_writing_stats
    gid = one(project, ww.cell(0)).group_ids[0]
    got = one(project, f"stat:group-works:{gid}", SYNTH)
    assert got.eligible and got.stat_value == 4 and Decimal(4) in got.numbers
    assert one(project, "stat:group-works:grp_ffffffffffff", SYNTH).reason == "unknown"
    assert one(project, "stat:no-such-kind", SYNTH).reason == "unknown"


def test_interp_reviewed_only_and_only_for_interpretive(
    project: Project, ww: WWorld, agent: Actor
) -> None:
    record_event(project, "interpretation.recorded", recorded(INT1), agent)
    assert one(project, f"interp:{INT1}", INTERP).reason == "unreviewed"
    record_event(project, "interpretation.reviewed", reviewed(INT1, "reviewed"))
    assert one(project, f"interp:{INT1}", INTERP).eligible
    assert one(project, f"interp:{INT1}", CLAIM).reason == "class-not-allowed"
    record_event(project, "interpretation.recorded", recorded(INT2), agent)
    record_event(project, "interpretation.reviewed", reviewed(INT2, "wrong", note="no"))
    assert one(project, f"interp:{INT2}", INTERP).reason == "rejected"
    assert one(project, "interp:int_01JZ9Q3K5M7N8P0R2S4T6V8W99", INTERP).reason == "unknown"


def test_concept_support(project: Project, ww: WWorld, agent: Actor) -> None:
    source = concept_source()
    first = record_event(project, "concept.defined", defined(CPT1, source=source), agent)
    assert one(project, f"interp:{CPT1}", INTERP).reason == "unreviewed"
    record_event(
        project, "concept.source_decided", source_decided(CPT1, "approve", source["digest"])
    )
    record_event(project, "concept.reviewed", concept_reviewed(CPT1, first.id))
    assert one(project, f"interp:{CPT1}", INTERP).eligible
    assert one(project, f"interp:{CPT1}", CLAIM).reason == "class-not-allowed"
    record_event(project, "concept.reviewed", concept_reviewed(CPT1, first.id, "wrong", note="x"))
    assert one(project, f"interp:{CPT1}", INTERP).reason == "rejected"


def test_resolution_reads_no_library(
    project: Project, ww: WWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> bytes:
        raise AssertionError("the library was read")

    monkeypatch.setattr(project.library, "get", boom)
    refs = [ww.claim(0), ww.cell(0), f"item:{ww.base_item}", f"edge:{ww.confirmed_edge}"]
    got = resolve_supports(project, [parse_support(r) for r in refs], cls=CLAIM)
    assert all(g.eligible for g in got)
