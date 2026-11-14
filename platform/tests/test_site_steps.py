"""The steps page of the hub: the exploratory miner `m-stage-steps` read from the index, shown per
stage and per paper in the paper's order; a pure view, an escaping render, honest absence."""

from __future__ import annotations

import re
from pathlib import Path

from factory.model.extraction import ExtractionClosed, ExtractionRecorded, StoredField
from factory.model.screening import PassLabel
from factory.services import site
from factory.services.context import Project
from factory.services.site_steps import CSS, STAGES, render_steps, step_rows, steps_view
from tests.extraction_helpers import CNV, DOC, PROTOCOL, TASK, _record

WA = "rf:aaa2021-first-1e2f3a4b"
WB = "rf:bbb2022-second-1e2f3a4b"


def _f(value: str, quote: str | None = None, anchor: str = "s1.p1") -> StoredField:
    return StoredField(
        value=value, quote=quote if quote is not None else value, anchor=anchor, copy_marker=False
    )


def _row(
    project: Project,
    n: int,
    work: str,
    stage: str,
    order: str,
    step: str,
    *,
    actor: str = "automated",
    pass_label: PassLabel = PassLabel.A,
    schema: str = "m-stage-steps@1",
    **opt: str,
) -> None:
    fields = {
        "stage": _f(stage),
        "step_order": _f(order),
        "step": _f(step),
        "actor": _f(actor),
    }
    fields.update({k: _f(v) for k, v in opt.items()})
    _record(
        project,
        "extraction.recorded",
        ExtractionRecorded(
            extraction_id=f"ext_{n:026d}",
            work_id=work,
            pass_label=pass_label,
            task_id=TASK,
            protocol_id=PROTOCOL,
            schema_ref=schema,
            document_id=DOC,
            conversion_id=CNV,
            row_key=f"rk_{n:012d}",
            fields=fields,
            supersedes=None,
            verifier=1,
        ),
        agent=True,
    )


def _populate(project: Project) -> None:
    _row(
        project, 1, WA, "literature-review", "2", "it ranks them", check="a human reads the top ten"
    )
    _row(project, 2, WA, "literature-review", "1", "it retrieves <papers>", inputs="a query")
    _row(
        project,
        3,
        WA,
        "data-analysis",
        "1",
        "it fits a model",
        actor="not-stated",
        limits="it overfits",
    )
    _row(project, 4, WB, "literature-review", "1", "it searches", actor="human-assisted")
    _row(project, 5, WB, "other", "1", "ignored pass B", pass_label=PassLabel.B)
    _row(project, 6, WB, "other", "1", "other miner", schema="m-stages@1")
    _record(
        project,
        "extraction.closed",
        ExtractionClosed(
            work_id=WA, pass_label=PassLabel.A, task_id=TASK, rows=3, claims=0, reason=None
        ),
    )


def test_rows_are_read_from_pass_a_of_the_steps_miner_only(project: Project) -> None:
    _populate(project)
    rows = step_rows(project)
    assert len(rows) == 4
    assert {r["work"] for r in rows} == {WA, WB}
    assert all(r["step"] != "ignored pass B" for r in rows)


def test_view_groups_by_stage_and_work_in_the_papers_order(project: Project) -> None:
    _populate(project)
    view = steps_view(step_rows(project))
    assert [s["id"] for s in view["stages"]] == [s for s, _ in STAGES]
    lit = next(s for s in view["stages"] if s["id"] == "literature-review")
    assert lit["n_works"] == 2 and lit["n_steps"] == 3
    wa = lit["works"][0]
    assert [st["order"] for st in wa["steps"]] == [1, 2]
    assert wa["steps"][1]["check"]["text"] == "a human reads the top ten"
    assert wa["steps"][0]["inputs"]["anchor"] == "s1.p1"
    assert wa["steps"][0]["limits"] is None
    lab = next(s for s in view["stages"] if s["id"] == "lab-automation")
    assert lab["n_works"] == 0 and lab["works"] == []


def test_view_is_deterministic(project: Project) -> None:
    _populate(project)
    rows = step_rows(project)
    assert steps_view(rows) == steps_view(list(reversed(rows)))


def test_not_stated_is_shown_as_not_stated_and_empty_stage_says_so(project: Project) -> None:
    _populate(project)
    page = render_steps(steps_view(step_rows(project)))
    assert "not stated" in page and ">not-stated<" not in page
    assert "No steps in this stage" in page
    assert "EXPLORATORY" in page and "no calibration" in page.lower()


def test_render_escapes_everything_and_links_to_the_explorer(project: Project) -> None:
    _populate(project)
    view = steps_view(step_rows(project))
    page = render_steps(view)
    assert "it retrieves &lt;papers&gt;" in page and "it retrieves <papers>" not in page
    assert "../explorer/index.html#open=aaa2021-first-1e2f3a4b" in page
    for f in ("data-actor", "data-check", "data-limits", "id=st-search"):
        assert f in page
    view["stages"][0]["works"] = [
        {"id": "x", "slug": "x", "title": "</script><b>", "year": "", "steps": []}
    ]
    assert "&lt;/script&gt;&lt;b&gt;" in render_steps(view)


def test_the_product_is_registered_after_lifecycle() -> None:
    ids = [p.id for p in site.products()]
    assert ids.index("steps") == ids.index("lifecycle") + 1
    product = next(p for p in site.products() if p.id == "steps")
    assert product.group == "Findings" and product.title == "Steps"
    assert "extraction.%" in product.inputs


def test_the_page_builds_on_an_empty_project_and_a_populated_one(
    project: Project, tmp_path: Path
) -> None:
    product = next(p for p in site.products() if p.id == "steps")
    product.build(project, tmp_path)
    assert "No steps in this stage" in (tmp_path / "index.html").read_text(encoding="utf-8")
    _populate(project)
    product.build(project, tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "it fits a model" in page
    assert re.search(r"<span>3 steps</span>", page)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS)
