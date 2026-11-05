"""Processing depth per work (slice 7b, plan V-A, task 2)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections import Counter

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.screening import Channel, PassLabel
from factory.services import extraction
from factory.services.context import Project
from factory.services.contributions import contribution_next, contribution_record
from factory.services.depth import (
    DEPTH_RANK,
    depth_counts,
    processing_depths,
)
from factory.services.extraction import in_dual_sample
from factory.services.extraction_audit import extraction_audit_record, extraction_audit_sample
from tests.contribution_helpers import ctr_a, ctr_b
from tests.contribution_helpers import world as world_contribution
from tests.extraction_helpers import (
    FIELDS,
    _both,
    _declare,
    _run,
    _same_rows,
    ext_a,
    ext_b,
    screened,
    world,
)
from tests.lineage_helpers import build_lineage

W_NEW = "rf:z1-00000001"
W_EXT = "rf:z2-00000002"
W_EXT_WORK = "rf:z3-00000003"
CH = Channel.CLI


def _insert_work(project: Project, work_id: str) -> None:
    project.index.sync()
    with project.index.connect() as conn:
        conn.execute(
            text("INSERT INTO works (work_id, data, first_event_id) VALUES (:w, '{}', 'ev')"),
            {"w": work_id},
        )
        conn.commit()


def test_rank_orders_the_four_depths() -> None:
    assert [d for d, _ in sorted(DEPTH_RANK.items(), key=lambda kv: kv[1])] == [
        "indexed",
        "screened",
        "extracted",
        "verified",
    ]


def test_indexed_only(project: Project) -> None:
    _insert_work(project, W_NEW)
    assert processing_depths(project, [W_NEW]) == {W_NEW: "indexed"}


def test_screened_after_final_decision(project: Project, screened: list[str]) -> None:
    assert set(processing_depths(project, screened).values()) == {"screened"}


def test_extracted_with_current_unit_evidence_scope(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    _run(project, ext_a, PassLabel.A, _same_rows)
    assert set(processing_depths(project, world).values()) == {"extracted"}


def test_verified_needs_agreed_or_resolved(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    assert set(processing_depths(project, world).values()) == {"verified"}


def test_single_pass_row_stays_extracted(
    project: Project,
    agent: Actor,
    ext_a: Actor,
    ext_b: Actor,
    screened: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = next(s for s in range(1000) if not any(in_dual_sample(s, w, 0.01) for w in screened))
    monkeypatch.setattr(extraction.secrets, "randbits", lambda _bits: seed)
    _declare(project, agent, 0.01)
    _both(project, ext_a, ext_b)
    assert set(processing_depths(project, screened).values()) == {"extracted"}


def test_stale_unit_is_not_extracted(
    project: Project, agent: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    _declare(project, agent, 1.0, fields=(*FIELDS, "hardware"))  # a new field stales every unit
    assert set(processing_depths(project, world).values()) == {"screened"}


def test_agreed_contribution_items_are_verified(
    project: Project,
    agent: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    world_contribution: list[str],
) -> None:
    built = build_lineage(project, agent, ctr_a, ctr_b, world_contribution)
    assert processing_depths(project, [built.source]) == {built.source: "verified"}


def test_contribution_current_unit_is_extracted(
    project: Project, ctr_a: Actor, world_contribution: list[str]
) -> None:
    served = contribution_next(project, ctr_a, PassLabel.A).batch
    assert served is not None
    work = served.records[0]["work_id"]
    contribution_record(project, ctr_a, served.task_id, [], finish=True, reason="no results")
    assert processing_depths(project, [work]) == {work: "extracted"}


def test_external_g1_work_is_indexed_and_unknown_raises(project: Project) -> None:
    project.index.sync()
    with project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO graph_nodes (node_id, node_type, event_id) VALUES (:n, 'paper', 'ev')"
            ),
            {"n": W_EXT},
        )
        conn.commit()
    assert processing_depths(project, [W_EXT]) == {W_EXT: "indexed"}
    with pytest.raises(FactoryValidationError) as err:
        processing_depths(project, ["rf:q9-99999999"])
    assert err.value.issues[0].field == "work_ids"


def test_large_batches_are_chunked(project: Project) -> None:
    ids = [f"rf:c{i}-{i:08x}" for i in range(2000)]
    project.index.sync()
    with project.index.connect() as conn:
        conn.execute(
            text("INSERT INTO works (work_id, data, first_event_id) VALUES (:w, '{}', 'ev')"),
            [{"w": w} for w in ids],
        )
        conn.commit()
    assert set(processing_depths(project, ids).values()) == {"indexed"}


def test_counts_match_per_work(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    _insert_work(project, W_NEW)
    ids = [*world, W_NEW]
    with project.index.connect() as conn:
        conn.execute(text("CREATE TEMP TABLE ids_t (work_id TEXT PRIMARY KEY)"))
        conn.execute(text("INSERT INTO ids_t VALUES (:w)"), [{"w": w} for w in ids])
        counts = depth_counts(project, "SELECT work_id FROM ids_t", {}, conn=conn)
    per_work = Counter(processing_depths(project, ids).values())
    assert counts == {d: per_work.get(d, 0) for d in DEPTH_RANK}
    assert counts["indexed"] == 1


def _audit(
    project: Project,
    work_id: str,
    *,
    audit_id: str = "xau_1",
    scope: str = "evidence",
    correct: int | None = 1,
    extraction_id: str | None = None,
) -> None:
    """An audit (if new) and one item of it, written straight into the index."""
    project.index.sync()
    with project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO extraction_audits (audit_id, scope, random_seed, "
                "population, population_digest, protocol_id, event_id) "
                "VALUES (:a, :s, 1, 1, 'd', 'P@x', 'ev')"
            ),
            {"a": audit_id, "s": scope},
        )
        conn.execute(
            text(
                "INSERT INTO extraction_audit_items (audit_id, work_id, row_key, field, scope, "
                "correct, note, extraction_id) VALUES "
                "(:a, :w, 'rk_0123456789ab', 'value', :s, :c, '', :x)"
            ),
            {"a": audit_id, "w": work_id, "s": scope, "c": correct, "x": extraction_id},
        )
        conn.commit()


def test_audit_label_counts_for_researcher_not_agent(project: Project) -> None:
    """A correct label on a current item of the latest audit makes its work `verified` in the
    researcher's depth; the agent variant ignores it (a label-derived fact, decision 37.14)."""
    _insert_work(project, W_NEW)
    _audit(project, W_NEW)
    assert processing_depths(project, [W_NEW]) == {W_NEW: "verified"}
    assert processing_depths(project, [W_NEW], agent=True) == {W_NEW: "indexed"}


@pytest.mark.parametrize(
    ("kwargs", "depth"),
    [
        ({"correct": 0}, "indexed"),  # an incorrect label verifies nothing
        ({"correct": None}, "indexed"),  # sampled, not labelled
        ({"scope": "card"}, "indexed"),  # a card audit is not extraction depth
        ({"scope": "contribution"}, "verified"),
        ({"extraction_id": "ext_gone"}, "indexed"),  # outdated: the value changed since
    ],
)
def test_audit_path_requires_a_correct_current_label(
    project: Project, kwargs: dict[str, object], depth: str
) -> None:
    _insert_work(project, W_NEW)
    _audit(project, W_NEW, **kwargs)  # type: ignore[arg-type]
    assert processing_depths(project, [W_NEW]) == {W_NEW: depth}


def test_audit_path_reads_the_latest_audit_only(project: Project) -> None:
    _insert_work(project, W_NEW)
    _insert_work(project, W_EXT_WORK)
    _audit(project, W_NEW, audit_id="xau_1")
    _audit(project, W_EXT_WORK, audit_id="xau_2")  # a later audit of the same scope
    assert processing_depths(project, [W_NEW, W_EXT_WORK]) == {
        W_NEW: "indexed",
        W_EXT_WORK: "verified",
    }


def test_stale_unit_is_not_verified_by_a_real_audit(
    project: Project,
    agent: Actor,
    human: Actor,
    ext_a: Actor,
    ext_b: Actor,
    world: list[str],
) -> None:
    _both(project, ext_a, ext_b)
    sampled = extraction_audit_sample(project, human, random_seed=1)
    item = sampled.items[0]
    extraction_audit_record(
        project, human, sampled.audit_id, item.work_id, item.row_key, item.field, True, "", CH
    )
    assert processing_depths(project, [item.work_id]) == {item.work_id: "verified"}
    _declare(project, agent, 1.0, fields=(*FIELDS, "hardware"))  # a new field stales every unit
    assert processing_depths(project, world)[item.work_id] == "screened"
