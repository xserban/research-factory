# ruff: noqa: F401, F811
"""Tools, separation tests, check and trace of the organisation class (slice 3d, plan Regions-C,
task 5). Labels, terms and consolidation select nothing and move no evidence output."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.model.cards import QuoteBasis
from factory.model.project import RigorMode
from factory.model.regions import RegionKind
from factory.regions.rules import CorpusRule, MemberType, RuleSet, TermRule
from factory.services import check as check_service
from factory.services.check import _findings_as
from factory.services.consolidation import (
    CONSOLIDATION_DUE_LABELS,
    complete_pass,
    decide_cluster,
    list_clusters,
    start_pass,
)
from factory.services.context import Project, open_project
from factory.services.labels import LabelInput, apply_labels, merge_labels, withdraw_label
from factory.services.lineage import graph_export
from factory.services.regions import define_region, review_region, snapshot_region
from factory.services.terms import promote_term
from factory.services.trace import trace
from tests import intuition_separation as sep
from tests.cli_helpers import _env
from tests.helpers import SESSION, install_skill, open_session
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, rows, screened, world
from tests.test_mcp_intuition import SESSION_I, _session

runner = CliRunner()
W = MemberType.WORK
QUOTE = "very long sequences degrade"
AGENT = {"role": "indexer", "model": "claude-opus-5-5", "skill": "rf-consolidate"}
ORGANISATION_CODES = frozenset(
    {"consolidation-due", "label-application-unconfirmed", "term-unused", "organisation-leak"}
)
ORGANISATION_EVENTS = ("label.", "term.", "consolidation.", "region.")


def label(
    project: Project, actor: Actor, text: str, target: str, q: QuoteBasis | None = None
) -> str:
    out = apply_labels(
        project, actor, [LabelInput(target_type=W, target=target, text=text, quote=q)]
    )
    assert not out.rejected, out.rejected
    return out.written[0]


def populate_organisation(project: Project, w: IWorld) -> None:
    """Labels (human, stated, inferred, withdrawn), a label merge, a promoted term, two regions
    (one by the term, one by corpus outcome) with snapshots and a review, and a consolidation
    pass with one decision of each kind except an idea or concept merge (those are evidence)."""
    quote = QuoteBasis(work_id=w.source, conversion_id=w.cnv, anchor="s1.p4", quote=QUOTE)
    for target in (w.source, w.other, w.third):
        label(project, w.human, "Performer", target)
        label(project, w.human, "FAVOR+", target)
    label(project, w.writer, "long sequences", w.source, quote)
    gone = label(project, w.writer, "scratch", w.other)
    withdraw_label(project, w.writer, gone, "mistaken")
    label(project, w.writer, "kernel", w.third)
    term = promote_term(
        project, w.human, name="performer", aliases=("favor+",), definition="d", applies_to=(W,)
    )
    region = define_region(
        project,
        w.human,
        kind=RegionKind.REGION,
        name="by term",
        definition="d",
        rules=RuleSet(include=(TermRule(term_id=term),)),
    )
    version = snapshot_region(project, w.human, region)
    review_region(project, w.human.model_copy(update={"user": "second"}), version, "reviewed")
    by_outcome = define_region(
        project,
        w.human,
        kind=RegionKind.REGION,
        name="included",
        definition="d",
        rules=RuleSet(include=(CorpusRule(outcome="all"),)),
    )
    snapshot_region(project, w.human, by_outcome)
    merge_labels(project, w.human, "performer", "favor+", "same method")
    pass_id = start_pass(project, w.human)
    for cluster in list_clusters(project, pass_id):
        decision = "keep" if cluster.kind != "label" else "skip"
        decide_cluster(project, w.human, pass_id, cluster.index, decision, reason="not now")
    complete_pass(project, w.human, pass_id)


def organised_twin(root: Path, project: Project, w: IWorld) -> tuple[Project, Project]:
    """The world as built and a copy of its root with the organisation class populated."""
    copy_root = root / "twin"
    shutil.copytree(project.settings.root, copy_root, ignore=shutil.ignore_patterns(".index"))
    settings = Settings(root=copy_root, user=project.settings.user)
    organised = open_project(settings, project.paths.slug, session=SESSION, clock=project.clock)
    populate_organisation(organised, IWorld(**{**w.__dict__}))
    project.index.rebuild()
    organised.index.rebuild()
    return project, organised


# --- Architecture ---

EVIDENCE_PREFIXES = (
    "factory.services.extraction",
    "factory.services.evidence",
    "factory.services.prisma",
    "factory.services.methods",
    "factory.services.screening",
    "factory.evidence",
)
ORGANISATION_MODULES = (  # `services.coverage` is not listed: `methods` reports the library's
    # coverage by design (Import-C)
    "factory.regions",
    "factory.consolidation",
    "factory.services.regions",
    "factory.services.labels",
    "factory.services.terms",
    "factory.services.consolidation",
    "factory.services.consolidation_due",
    "factory.services.label_check",
    "factory.services.label_trace",
    "factory.services.organisation_export",
    "factory.model.labels",
    "factory.model.regions",
    "factory.index.labels",
    "factory.index.regions",
)


def test_architecture_no_organisation_imports() -> None:
    modules = sep.package_modules()
    imports = sep.imports_of(modules, packages=sep.package_dirs())
    evidence = {
        m
        for m in modules
        if any(m == p or m.startswith(p + ".") or m.startswith(p) for p in EVIDENCE_PREFIXES)
    }
    assert evidence, "no evidence module found: the prefixes are stale"
    bad = sorted(
        (importer, imported)
        for importer, imported in imports
        if importer in evidence
        and any(imported == o or imported.startswith(o + ".") for o in ORGANISATION_MODULES)
    )
    assert bad == []


def test_organisation_tables_are_named_only_by_organisation_modules() -> None:
    modules = sep.package_modules()
    tables = (
        "label_merges",
        "term_aliases",
        "consolidation_passes",
        "consolidation_proposals",
        "consolidation_decisions",
    )
    readers = sep.modules_with_string_literals(modules, tables)
    allowed = {
        "factory.index.labels",
        "factory.index.index",
        "factory.regions.term_use",
        "factory.services.labels",
        "factory.services.terms",
        "factory.services.consolidation",
        "factory.services.consolidation_due",
        "factory.services.label_check",
        "factory.services.label_trace",
        "factory.services.modules.labels",
    }
    assert readers - allowed == set()


# --- Evidence outputs do not move ---


def test_differential_evidence_identical(
    tmp_path: Path, project: Project, iw: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sep, "LAYER_EVENT_PREFIXES", (*sep.LAYER_EVENT_PREFIXES, *ORGANISATION_EVENTS)
    )
    monkeypatch.setattr(sep, "LAYER_CHECK_CODES", sep.LAYER_CHECK_CODES | ORGANISATION_CODES)
    plain, organised = organised_twin(tmp_path, project, iw)
    nodes = [iw.source, iw.other, iw.idea1]
    before = sep.evidence_outputs(plain, nodes)
    after = sep.evidence_outputs(organised, nodes)
    assert set(before) == set(after)
    assert [k for k in before if before[k] != after[k]] == []
    assert rows(organised, "SELECT COUNT(*) FROM labels") != [(0,)]


def test_default_export_unchanged(project: Project, iw: IWorld) -> None:
    before = [graph_export(project, fmt) for fmt in ("json", "dot")]  # type: ignore[arg-type]
    label(project, iw.human, "performer", iw.source)
    assert [graph_export(project, fmt) for fmt in ("json", "dot")] == before  # type: ignore[arg-type]


def test_with_labels_rows_carry_class(project: Project, iw: IWorld, settings: Settings) -> None:
    populate_organisation(project, iw)
    plain = runner.invoke(app, ["graph", "export"], env=_env(settings.root))
    json_out = runner.invoke(app, ["graph", "export", "--with-labels"], env=_env(settings.root))
    assert plain.exit_code == 0 and json_out.exit_code == 0, json_out.stderr
    body = json.loads(json_out.stdout)
    assert json.dumps(body["evidence"], sort_keys=True, separators=(",", ":")) == json.dumps(
        json.loads(plain.stdout), sort_keys=True, separators=(",", ":")
    )
    part = body["organisation"]
    assert part["labels"] and part["terms"]
    assert all(row["class"] == "organisation" for row in [*part["labels"], *part["terms"]])
    dot = runner.invoke(
        app, ["graph", "export", "--format", "dot", "--with-labels"], env=_env(settings.root)
    )
    assert dot.exit_code == 0 and "cluster_organisation" in dot.stdout
    assert dot.stdout.startswith("// organisation:") and dot.stdout.rstrip().endswith("}")


# --- Findings ---


def findings(project: Project, mode: RigorMode = RigorMode.PILOT) -> dict[str, Any]:
    return {f.code: f for f in _findings_as(project, mode) if f.code in ORGANISATION_CODES}


def test_no_organisation_no_findings(project: Project, iw: IWorld) -> None:
    assert findings(project) == {}


def test_finding_consolidation_due(project: Project, iw: IWorld) -> None:
    for n in range(CONSOLIDATION_DUE_LABELS + 1):
        label(project, iw.human, f"filler {n:03d} {'abcdefghij'[n % 10] * 8}", iw.source)
    found = findings(project)["consolidation-due"]
    assert found.severity == "warning" and "51 new label key" in found.message


def test_finding_label_application_unconfirmed(project: Project, iw: IWorld) -> None:
    app_id = label(project, iw.writer, "kernel", iw.source)
    label(project, iw.human, "confirmed", iw.source)
    found = findings(project)["label-application-unconfirmed"]
    assert found.refs == [app_id] and found.severity == "warning"
    assert "label-application-unconfirmed" not in findings(project, RigorMode.EXPLORATORY)


def test_finding_term_unused(project: Project, iw: IWorld) -> None:
    term = promote_term(project, iw.human, name="orphan", definition="d", applies_to=(W,))
    found = findings(project)["term-unused"]
    assert found.refs == [term]


def test_organisation_leak_fires_on_constructed_leak(
    project: Project, iw: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    label(project, iw.human, "performer", iw.source)
    assert "organisation-leak" not in findings(project)
    real = check_service.evidence_snapshot

    def leaky(p: Project) -> dict[str, str]:
        return {**real(p), "prisma": "flow of lbl_01JZ9Q3K5M7N8P0R2S4T6V8W1J"}

    monkeypatch.setattr(check_service, "evidence_snapshot", leaky)
    for mode in (RigorMode.EXPLORATORY, RigorMode.PILOT, RigorMode.SYSTEMATIC):
        found = findings(project, mode)["organisation-leak"]
        assert found.severity == "error" and found.refs == ["prisma"]
    leaky_version = lambda p: {**real(p), "search_report": "pinned R@0a1b2c3d"}  # noqa: E731
    monkeypatch.setattr(check_service, "evidence_snapshot", leaky_version)
    assert findings(project)["organisation-leak"].refs == ["search_report"]


# --- Trace ---


def test_trace_of_organisation_ids(project: Project, iw: IWorld) -> None:
    populate_organisation(project, iw)
    [(app_id,)] = rows(project, "SELECT application_id FROM labels WHERE quote IS NOT NULL LIMIT 1")
    [(term_id,)] = rows(project, "SELECT term_id FROM terms")
    [(pass_id,)] = rows(project, "SELECT pass_id FROM consolidation_passes")
    node = trace(project, app_id)
    assert node.kind == "label" and "organisation" in node.label and QUOTE in node.label
    assert "writer" in node.label and "skill" in node.label

    def kinds(n: Any) -> set[str]:
        return {n.kind}.union(*(kinds(c) for c in n.children))

    assert kinds(node) >= {"work", "anchor"}
    assert trace(project, term_id).kind == "term"
    passed = trace(project, pass_id, direction="forward")
    assert passed.kind == "consolidation" and "organisation" in passed.label


# --- Tools ---


@pytest.mark.anyio
async def test_tool_list_never_decides(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(mcp_server.build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    mine = [n for n in names if n.startswith(("label", "consolidation", "term"))]
    assert sorted(mine) == [
        "consolidation_next",
        "consolidation_propose",
        "label_apply",
        "term_list",
    ]
    banned = ("merge", "decide", "promote", "confirm", "reject", "complete", "start", "retire")
    assert not [n for n in mine if any(b in n for b in banned)]


@pytest.mark.anyio
async def test_tools_refuse_pass_sessions(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    iw: IWorld,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-consolidate")
    for session in (ctr_a.session, SESSION):
        _session(monkeypatch, session)
        async with open_session(settings, clock) as client:
            outs = [
                await client.call(
                    "label_apply",
                    project="demo",
                    items=[{"target_type": "work", "target": iw.source, "text": "x"}],
                    **AGENT,
                ),
                await client.call("consolidation_next", project="demo", **AGENT),
                await client.call(
                    "consolidation_propose",
                    project="demo",
                    task_id="tsk_x",
                    action="keep",
                    members=["a"],
                    reason="r",
                    **AGENT,
                ),
                await client.call("term_list", project="demo"),
            ]
        for out in outs:
            assert out["ok"] is False and out["errors"][0]["field"] == "session", out
    assert rows(project, "SELECT COUNT(*) FROM labels") == [(0,)]


@pytest.mark.anyio
async def test_skill_hash_recorded_and_roundtrip(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    iw: IWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-consolidate")
    label(project, iw.human, "Performer", iw.source)
    label(project, iw.human, "FAVOR+", iw.source)
    pass_id = start_pass(project, iw.human)
    _session(monkeypatch, SESSION_I)
    async with open_session(settings, clock) as client:
        applied = await client.call(
            "label_apply",
            project="demo",
            items=[
                {
                    "target_type": "work",
                    "target": iw.source,
                    "text": "long sequences",
                    "quote": {
                        "work_id": iw.source,
                        "conversion_id": iw.cnv,
                        "anchor": "s1.p4",
                        "quote": QUOTE,
                    },
                },
                {"target_type": "work", "target": "rf:nowhere-00000000", "text": "x"},
                {"target_type": "work", "target": iw.other},
            ],
            **AGENT,
        )
        served = await client.call("consolidation_next", project="demo", **AGENT)
        members = [m["id"] for m in served["data"]["task"]["members"]]
        proposed = await client.call(
            "consolidation_propose",
            project="demo",
            task_id=served["data"]["task"]["task_id"],
            action="merge",
            into=members[0],
            members=members,
            reason="two names for one method",
            **AGENT,
        )
        listed = await client.call("term_list", project="demo")
    assert applied["ok"] is True, applied
    assert len(applied["data"]["written"]) == 1
    assert [r["index"] for r in applied["data"]["rejected"]] == [1, 2]
    assert proposed["ok"] is True, proposed
    assert proposed["data"]["proposal_id"].startswith("cnp_")
    assert listed["data"] == {"terms": []}
    events = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type in ("label.applied", "consolidation.proposed") and e.actor.kind == "agent"
    ]
    assert len(events) == 2
    for e in events:
        assert e.actor.skill is not None and e.actor.skill.startswith("rf-consolidate@")
        assert e.input_blob is not None
    assert "score" not in json.dumps(served["data"])
    assert served["data"]["task"]["pass_id"] == pass_id


def import_tag(project: Project, w: IWorld, text: str, target: str, ref: str) -> str:
    from factory.services.labels import _apply

    out = _apply(
        project,
        w.human,
        [LabelInput(target_type=W, target=target, text=text)],
        origin="import-tag",
        import_refs=[ref],
    )
    assert not out.rejected
    return out.written[0]


def test_agent_trace_withholds_import_tags_but_not_works(project: Project, iw: IWorld) -> None:
    from factory.errors import FactoryValidationError
    from factory.services.trace import agent_trace

    ref = "imp_01JZ9Q3K5M7N8P0R2S4T6V8W1J:17"
    tag = import_tag(project, iw, "Performer", iw.source, ref)
    label(project, iw.human, "performer", iw.other)
    term = promote_term(project, iw.human, name="performer", definition="d", applies_to=(W,))
    shown = agent_trace(project, term).model_dump_json()
    assert ref not in shown and tag not in shown and "from record" not in shown
    assert "imp_" not in shown
    with pytest.raises(FactoryValidationError):
        agent_trace(project, tag)
    assert ref in trace(project, term).model_dump_json()  # the researcher's trace keeps it
    # the work still reads as a corpus work through its own trace
    assert agent_trace(project, iw.source).id == iw.source


def test_label_apply_is_no_oracle_for_import_tags(project: Project, iw: IWorld) -> None:
    import_tag(project, iw, "Performer", iw.source, "imp_01JZ9Q3K5M7N8P0R2S4T6V8W1J:3")
    out = apply_labels(
        project,
        iw.writer,
        [
            LabelInput(target_type=W, target=iw.source, text="performer"),
            LabelInput(target_type=W, target=iw.other, text="performer"),
        ],
    )
    assert out.rejected == [] and len(out.written) == 2  # same answer for both works
    again = apply_labels(
        project, iw.writer, [LabelInput(target_type=W, target=iw.other, text="performer")]
    )
    assert again.rejected[0].issues[0].reason == "duplicate-application"  # its own, visible


def test_consolidation_task_carries_no_import_tag_key(project: Project, iw: IWorld) -> None:
    from factory.services.consolidation import consolidation_next, list_clusters, start_pass

    targets = (iw.source, iw.other, iw.third)
    for t in targets[:2]:
        import_tag(project, iw, "Secret Tag", t, "imp_01JZ9Q3K5M7N8P0R2S4T6V8W1J:1")
        import_tag(project, iw, "Other Name", t, "imp_01JZ9Q3K5M7N8P0R2S4T6V8W1J:2")
    pass_id = start_pass(project, iw.human)
    [cluster] = [c for c in list_clusters(project, pass_id) if c.kind == "label"]
    assert set(cluster.members) == {"secret tag", "other name"}  # the researcher sees tag keys
    served = consolidation_next(project, iw.writer)  # a tag-only cluster serves no task
    assert served is None or served.kind != "label"


def test_mixed_cluster_serves_only_the_tag_free_part(project: Project, iw: IWorld) -> None:
    from factory.services.consolidation import consolidation_next, list_clusters, start_pass

    for t in (iw.source, iw.other, iw.third):
        label(project, iw.human, "Performer", t)
        label(project, iw.human, "FAVOR+", t)
        import_tag(project, iw, "Secret Tag", t, "imp_01JZ9Q3K5M7N8P0R2S4T6V8W1J:1")
    pass_id = start_pass(project, iw.human)
    [cluster] = [c for c in list_clusters(project, pass_id) if c.kind == "label"]
    assert "secret tag" in cluster.members
    task = consolidation_next(project, iw.writer)
    while task is not None and task.kind != "label":
        task = consolidation_next(project, iw.writer)
    assert task is not None
    assert sorted(m["id"] for m in task.members) == ["favor+", "performer"]
    assert "secret" not in task.model_dump_json().lower()


def test_term_trace_skips_rejected_applications(project: Project, iw: IWorld) -> None:
    from factory.services.labels import decide_application

    keep = label(project, iw.human, "performer", iw.source)
    drop = label(project, iw.human, "performer", iw.other)
    decide_application(project, iw.human, drop, "reject")
    term = promote_term(project, iw.human, name="performer", definition="d", applies_to=(W,))
    ids = {c.id for c in trace(project, term).children}
    assert keep in ids and drop not in ids
