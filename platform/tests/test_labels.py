# ruff: noqa: F401, F811
"""Free label applications (slice 3d, plan Regions-C, task 1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.imports.model import ImportFormat
from factory.model.cards import QuoteBasis
from factory.model.imports import ImportRole
from factory.model.labels import label_key
from factory.regions.rules import MemberType
from factory.services.context import Project
from factory.services.imports import record_import
from factory.services.labels import (
    LabelInput,
    apply_labels,
    decide_application,
    import_tags_as_labels,
    labels_of,
    withdraw_label,
)
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, rows, screened, world

BIB = """@article{a, title={Made-Up Pears}, year={2019}, doi={10.9999/x.1}, keyword={pears; Fruit}}
@misc{b, title={Made-Up Fennel}, year={2021}, keyword={}}
"""


def item(
    w: IWorld, label: str, *, quote: str | None = None, target: str | None = None
) -> LabelInput:
    basis = (
        None
        if quote is None
        else QuoteBasis(work_id=w.source, conversion_id=w.cnv, anchor="s1.p4", quote=quote)
    )
    return LabelInput(
        target_type=MemberType.WORK, target=target or w.source, text=label, quote=basis
    )


def test_key_normalisation() -> None:
    assert label_key("  \uff26avor+   Performer ") == "favor+ performer"
    assert label_key("ÀB\tc") == label_key("àb c")


def test_human_application_confirmed(iw: IWorld, project: Project) -> None:
    out = apply_labels(project, iw.human, [item(iw, "Linear Attention")])
    assert len(out.written) == 1 and not out.rejected
    [view] = labels_of(project, MemberType.WORK, iw.source)
    assert (view.key, view.status, view.origin) == ("linear attention", "confirmed", "human")
    assert view.class_ == "organisation"


def test_agent_quote_with_key_stated(iw: IWorld, project: Project) -> None:
    out = apply_labels(
        project, iw.writer, [item(iw, "Long Sequences", quote="very long sequences degrade")]
    )
    assert not out.rejected
    [view] = labels_of(project, MemberType.WORK, iw.source)
    assert (view.status, view.origin) == ("stated", "agent")


def test_agent_without_quote_inferred(iw: IWorld, project: Project) -> None:
    apply_labels(project, iw.writer, [item(iw, "kernel")])
    apply_labels(project, iw.writer, [item(iw, "unrelated", quote="very long sequences degrade")])
    views = {v.key: v.status for v in labels_of(project, MemberType.WORK, iw.source)}
    assert views == {"kernel": "inferred", "unrelated": "inferred"}


def test_non_verbatim_quote_rejected_batch_partial(iw: IWorld, project: Project) -> None:
    out = apply_labels(
        project,
        iw.writer,
        [item(iw, "bad", quote="never written in the paper"), item(iw, "good")],
    )
    assert len(out.written) == 1
    [bad] = out.rejected
    assert bad.index == 0 and bad.issues[0].reason == "quote-not-verbatim"
    assert [v.key for v in labels_of(project, MemberType.WORK, iw.source)] == ["good"]


def test_invalid_items_rejected(iw: IWorld, project: Project) -> None:
    out = apply_labels(
        project,
        iw.human,
        [
            item(iw, "x" * 61),
            item(iw, "   "),
            item(iw, "ok", target="rf:nowhere-00000000"),
            item(iw, "dup"),
            item(iw, "DUP"),
        ],
    )
    assert [r.index for r in out.rejected] == [0, 1, 2, 4]
    assert [r.issues[0].reason for r in out.rejected][-1] == "duplicate-application"


def test_withdraw_supersedes(iw: IWorld, project: Project) -> None:
    [app] = apply_labels(project, iw.writer, [item(iw, "kernel")]).written
    with pytest.raises(FactoryValidationError):
        withdraw_label(project, iw.human.model_copy(update={"kind": "system"}), app, "no")
    withdraw_label(project, iw.writer, app, "mistaken")
    assert labels_of(project, MemberType.WORK, iw.source) == []
    with pytest.raises(FactoryValidationError) as caught:
        withdraw_label(project, iw.writer, app, "again")
    assert caught.value.issues[0].reason == "already-withdrawn"


def test_confirm_and_reject_are_human(iw: IWorld, project: Project) -> None:
    [app] = apply_labels(project, iw.writer, [item(iw, "kernel")]).written
    with pytest.raises(FactoryValidationError) as caught:
        decide_application(project, iw.writer, app, "confirm")
    assert caught.value.issues[0].field == "actor"
    decide_application(project, iw.human, app, "confirm")
    [view] = labels_of(project, MemberType.WORK, iw.source)
    assert view.status == "confirmed"
    decide_application(project, iw.human, app, "reject")
    assert labels_of(project, MemberType.WORK, iw.source) == []


def test_import_tags_become_confirmed_labels(
    project: Project, tmp_path: Path, world: list[str]
) -> None:
    path = tmp_path / "lib.bib"
    path.write_text(BIB)
    summary = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=1
    )
    project.index.sync()
    with project.index.connect() as conn:
        work = world[0]
        conn.execute(
            text(
                "UPDATE import_records SET link_state = 'resolved', work_id = :w "
                "WHERE import_id = :i AND ordinal = "
                "(SELECT MIN(ordinal) FROM import_records WHERE import_id = :i)"
            ),
            {"w": work, "i": summary.import_id},
        )
        conn.commit()
    assert import_tags_as_labels(project, summary.import_id) == 2
    assert import_tags_as_labels(project, summary.import_id) == 0  # idempotent
    views = labels_of(project, MemberType.WORK, work)
    assert sorted(v.key for v in views) == ["fruit", "pears"]
    assert {(v.origin, v.status) for v in views} == {("import-tag", "confirmed")}


def test_labels_not_in_graph_tables(iw: IWorld, project: Project) -> None:
    tables = ("graph_nodes", "graph_edges", "layer_nodes", "layer_edges")
    before = [rows(project, f"SELECT COUNT(*) FROM {t}") for t in tables]
    apply_labels(project, iw.human, [item(iw, "linear attention"), item(iw, "kernel")])
    assert [rows(project, f"SELECT COUNT(*) FROM {t}") for t in tables] == before


def test_rerun_keeps_a_withdrawn_tag_withdrawn(
    project: Project, tmp_path: Path, world: list[str]
) -> None:
    path = tmp_path / "lib.bib"
    path.write_text(BIB)
    summary = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=1
    )
    project.index.sync()
    with project.index.connect() as conn:
        conn.execute(
            text(
                "UPDATE import_records SET link_state = 'resolved', work_id = :w "
                "WHERE import_id = :i AND ordinal = "
                "(SELECT MIN(ordinal) FROM import_records WHERE import_id = :i)"
            ),
            {"w": world[0], "i": summary.import_id},
        )
        conn.commit()
    assert import_tags_as_labels(project, summary.import_id) == 2
    [pears] = [v for v in labels_of(project, MemberType.WORK, world[0]) if v.key == "pears"]
    withdraw_label(project, project.human_actor(), pears.application_id, "not wanted")
    assert import_tags_as_labels(project, summary.import_id) == 0
    assert [v.key for v in labels_of(project, MemberType.WORK, world[0])] == ["fruit"]


def test_rerun_keeps_a_withdrawn_tag_withdrawn_across_two_records(
    project: Project, tmp_path: Path, world: list[str]
) -> None:
    two = (
        "@article{a, title={Made-Up Pears}, year={2019}, doi={10.9999/x.1}, keyword={pears}}\n"
        "@article{b, title={Made-Up Pears 2}, year={2020}, doi={10.9999/x.2}, keyword={pears}}\n"
    )
    path = tmp_path / "two.bib"
    path.write_text(two)
    summary = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=1
    )
    project.index.sync()
    with project.index.connect() as conn:
        conn.execute(
            text(
                "UPDATE import_records SET link_state = 'resolved', work_id = :w "
                "WHERE import_id = :i"
            ),
            {"w": world[0], "i": summary.import_id},
        )
        conn.commit()
    assert import_tags_as_labels(project, summary.import_id) == 1  # one work, one key
    [pears] = labels_of(project, MemberType.WORK, world[0])
    withdraw_label(project, project.human_actor(), pears.application_id, "not wanted")
    assert import_tags_as_labels(project, summary.import_id) == 0
    assert labels_of(project, MemberType.WORK, world[0]) == []
