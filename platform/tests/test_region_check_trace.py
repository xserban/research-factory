"""Region findings, trace nodes, export and the CLI (slice 3d, plan Regions-B, task 4)."""

# ruff: noqa: F811

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from factory.cli.main import app
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.question import QuestionSpec, Slot
from factory.model.regions import EdgeBasis, Facet, RegionKind
from factory.regions.rules import CorpusRule, MemberType, RuleSet, RunRule
from factory.services.check import agent_check, check
from factory.services.question import current_question, record_question
from factory.services.regions import (
    decide_member,
    define_region,
    export_version,
    link_regions,
    propose_member,
    review_region,
    snapshot_region,
)
from factory.services.trace import agent_trace, trace
from tests.cli_helpers import _env
from tests.contribution_helpers import ctr_a, ctr_b, world  # noqa: F401
from tests.helpers import pilot_question_spec
from tests.lineage_helpers import Lineage, lin  # noqa: F401
from tests.region_helpers import RWorld, add_queries, region_project, screened  # noqa: F401
from tests.test_cli_regions import _define, _run
from tests.test_region_members import quote_basis

W = MemberType.WORK
FT = CorpusRule(outcome="included", stage=ScreeningStage.FULL_TEXT)
CODES = (
    "region-unreviewed",
    "region-drift",
    "region-subregion-violated",
    "region-focus-slot-missing",
    "region-member-proposal-pending",
)


def make(
    w: RWorld, human: Actor, name: str = "attention works", rules: RuleSet | None = None
) -> str:
    return define_region(
        w.project,
        human,
        kind=RegionKind.REGION,
        name=name,
        definition=f"{name} definition",
        rules=rules or RuleSet(include=(FT,)),
    )


def barred_queries(w: RWorld, purposes: dict[str, str]) -> None:
    """Queries of the given purposes whose runs have a status the report models can read."""
    add_queries(w.project, purposes)
    with w.project.index.connect() as conn:
        conn.execute(
            text("UPDATE runs SET status = 'complete', started_at = '2026-01-01T00:00:00Z'")
        )
        conn.execute(
            text(
                "UPDATE queries SET kind = 'keyword', interface = 'cli', "
                "registered_at = '2026-01-01T00:00:00Z'"
            )
        )
        conn.commit()


def findings(w: RWorld) -> dict[str, object]:
    return {f.code: f for f in check(w.project).findings if f.code in CODES}


def test_no_region_no_finding(region_project: RWorld) -> None:
    assert findings(region_project) == {}


def test_unreviewed_then_reviewed(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = make(w, human)
    found = findings(w)["region-unreviewed"]
    assert found.refs == [region] and found.severity == "warning"  # type: ignore[attr-defined]
    version = snapshot_region(w.project, human, region)
    assert "region-unreviewed" in findings(w)
    review_region(w.project, human, version, "reviewed")
    assert "region-unreviewed" not in findings(w)


def test_drift_reports_counts(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = make(w, human)
    snapshot_region(w.project, human, region)
    assert "region-drift" not in findings(w)
    decide_member(w.project, human, region, W, w.extra, "add")
    found = findings(w)["region-drift"]
    assert found.refs == [region]  # type: ignore[attr-defined]
    assert "1 member(s) added, 0 removed" in found.message  # type: ignore[attr-defined]


def test_subregion_violated_finding(region_project: RWorld, human: Actor) -> None:
    w = region_project
    child, parent = make(w, human, "child"), make(w, human, "parent")
    link_regions(
        w.project,
        human,
        "subregion-of",
        snapshot_region(w.project, human, child),
        snapshot_region(w.project, human, parent),
    )
    assert "region-subregion-violated" not in findings(w)
    decide_member(w.project, human, parent, W, w.included[0], "remove")
    snapshot_region(w.project, human, parent)
    found = findings(w)["region-subregion-violated"]
    assert found.severity == "warning" and len(found.refs) == 1  # type: ignore[attr-defined]


def test_focus_slot_missing_finding(region_project: RWorld, human: Actor) -> None:
    w = region_project
    question = current_question(w.project)
    assert question is not None
    slot = question.spec.slots[0].name
    define_region(
        w.project,
        human,
        kind=RegionKind.FOCUS,
        name="focus",
        definition="A focus.",
        rules=RuleSet(include=(FT,)),
        facet=Facet(question_id=question.question_id, slot=slot),
    )
    assert "region-focus-slot-missing" not in findings(w)
    spec = pilot_question_spec()
    renamed = QuestionSpec(
        **{**spec.model_dump(), "slots": (Slot(name="cohort", value="vision"), spec.slots[1])}
    )
    record_question(w.project, human, renamed, reason="renamed the slot")
    assert "region-focus-slot-missing" in findings(w)


def test_member_proposal_pending_finding(
    region_project: RWorld, human: Actor, agent: Actor
) -> None:
    w = region_project
    d = w.included[3]
    region = make(w, human)
    decide_member(w.project, human, region, W, d, "remove")
    propose_member(
        w.project, agent, region, W, d, EdgeBasis(edge_id="cit:rex_" + "2".zfill(26) + ":1")
    )
    found = findings(w)["region-member-proposal-pending"]
    assert found.refs == [region] and "1 member proposal(s)" in found.message  # type: ignore[attr-defined]
    decide_member(w.project, human, region, W, d, "reject")
    assert "region-member-proposal-pending" not in findings(w)


def test_findings_carry_no_text(region_project: RWorld, human: Actor, agent: Actor) -> None:
    w = region_project
    region = make(w, human, "SECRET-NAME")
    snapshot_region(w.project, human, region)
    decide_member(w.project, human, region, W, w.extra, "add")
    mine = [f for f in check(w.project).findings if f.code in CODES]
    assert mine
    for f in mine:
        assert "SECRET" not in f.message and not any("SECRET" in r for r in f.refs)
        assert "definition" not in f.message


def withheld_world(w: RWorld, human: Actor) -> tuple[str, str]:
    """A withheld region and a clean one, each drifted by one added member, and a subregion link
    from the clean region's version into the withheld region's version that no longer holds."""
    barred_queries(w, {"qry_imp": "import"})
    held = make(w, human, "held", RuleSet(include=(FT, RunRule(query_id="qry_imp"))))
    fine = make(w, human, "fine")
    held_v = snapshot_region(w.project, human, held)
    fine_v = snapshot_region(w.project, human, fine)
    link_regions(w.project, human, "subregion-of", fine_v, held_v)
    decide_member(w.project, human, held, W, w.extra, "add")
    decide_member(w.project, human, fine, W, w.extra, "add")
    decide_member(w.project, human, held, W, w.included[0], "remove")
    snapshot_region(w.project, human, held)
    return held, fine


def by_code(report: object, code: str) -> object:
    return next(f for f in report.findings if f.code == code)  # type: ignore[attr-defined]


def test_researcher_check_reports_withheld_regions(region_project: RWorld, human: Actor) -> None:
    w = region_project
    held, fine = withheld_world(w, human)
    drift = by_code(check(w.project), "region-drift")
    assert sorted(drift.refs) == [fine]  # type: ignore[attr-defined]
    # the held region was snapshotted after its change; add one more so it drifts too
    decide_member(w.project, human, held, W, w.included[1], "remove")
    both = by_code(check(w.project), "region-drift")
    assert sorted(both.refs) == sorted([held, fine])  # type: ignore[attr-defined]
    assert "1 member(s) added, 1 removed" in both.message  # type: ignore[attr-defined]
    assert by_code(check(w.project), "region-subregion-violated").refs  # type: ignore[attr-defined]


def test_agent_check_withholds_regions_and_recomputes_counts(
    region_project: RWorld, human: Actor
) -> None:
    w = region_project
    held, fine = withheld_world(w, human)
    decide_member(w.project, human, held, W, w.included[1], "remove")
    report = agent_check(w.project)
    drift = by_code(report, "region-drift")
    assert drift.refs == [fine]  # type: ignore[attr-defined]
    assert "1 member(s) added, 0 removed" in drift.message  # type: ignore[attr-defined]
    assert "region-subregion-violated" not in {f.code for f in report.findings}
    assert held in by_code(report, "region-unreviewed").refs  # type: ignore[attr-defined]


# --- Trace ---


def labels(node: object) -> list[str]:
    out = [node.label]  # type: ignore[attr-defined]
    for child in node.children:  # type: ignore[attr-defined]
        out += labels(child)
    return out


def test_trace_region_and_version(region_project: RWorld, human: Actor, agent: Actor) -> None:
    w = region_project
    region = make(w, human)
    version = snapshot_region(w.project, human, region)
    review_region(w.project, human, version, "reviewed", "checked")
    tree = trace(w.project, region, direction="forward")
    assert tree.kind == "region" and "organisation" in tree.label and "author human" in tree.label
    assert [c.id for c in tree.children] == [version]
    assert "reviewed by obd" in tree.children[0].label and "checked" not in tree.children[0].label
    back = trace(w.project, version)
    assert [c.id for c in back.children] == [region]
    by_agent = define_region(
        w.project,
        agent,
        kind=RegionKind.REGION,
        name="agent region",
        definition="d",
        rules=RuleSet(include=(FT,)),
    )
    label = trace(w.project, by_agent).label
    assert (
        "author agent" in label and "model claude-opus-5-5" in label and "input_blob -" not in label
    )
    with pytest.raises(FactoryValidationError):
        trace(w.project, "reg_" + "0" * 26)


def test_trace_member_basis(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = make(w, human)
    decide_member(w.project, human, region, W, w.extra, "add")
    version = snapshot_region(w.project, human, region)
    plain = trace(w.project, w.included[0], direction="forward")
    assert not any("region_member" in label for label in labels(plain))  # unchanged by default
    tree = trace(w.project, w.included[0], direction="forward", layer="all")
    [member] = [c for c in tree.children if c.kind == "region_member"]
    assert member.id == f"{version}/work/{w.included[0]}"
    assert f"in {region} {version} by rules 0" in member.label
    added = trace(w.project, w.extra, direction="forward", layer="all")
    [by_decision] = [c for c in added.children if c.kind == "region_member"]
    assert "by decision ev_" in by_decision.label
    back = trace(w.project, member.id)
    assert next(c.id for c in back.children) == version
    assert region in labels(back)[1]


def test_agent_trace_drops_a_withheld_region(region_project: RWorld, human: Actor) -> None:
    w = region_project
    barred_queries(w, {"qry_imp": "import"})
    held = make(w, human, "held", RuleSet(include=(FT, RunRule(query_id="qry_imp"))))
    fine = make(w, human, "fine")
    held_version = snapshot_region(w.project, human, held)
    fine_version = snapshot_region(w.project, human, fine)
    seen = trace(w.project, w.included[0], direction="forward", layer="all")
    assert {c.id.split("/")[0] for c in seen.children if c.kind == "region_member"} == {
        held_version,
        fine_version,
    }
    agent_view = agent_trace(w.project, w.included[0], direction="forward", layer="all")
    assert [c.id.split("/")[0] for c in agent_view.children if c.kind == "region_member"] == [
        fine_version
    ]
    for ref in (held, held_version):
        with pytest.raises(FactoryValidationError):
            agent_trace(w.project, ref)


# --- Export ---


def test_export_byte_identical_across_rebuilds(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = make(w, human, "SECRET-NAME")
    decide_member(w.project, human, region, W, w.extra, "add")
    version = snapshot_region(w.project, human, region)
    first = export_version(w.project, version)
    w.project.index.rebuild()
    again = export_version(w.project, version)
    assert [r.model_dump_json() for r in first] == [r.model_dump_json() for r in again]
    assert [r.member for r in first] == sorted(r.member for r in first)
    assert "SECRET" not in json.dumps([r.model_dump(mode="json") for r in first])
    with pytest.raises(FactoryValidationError):
        export_version(w.project, "R@00000000")


# --- CLI ---


def test_cli_decisions_link_and_export(
    settings: Settings, region_project: RWorld, human: Actor, tmp_path: Path
) -> None:
    w = region_project
    region = _define(settings, tmp_path)
    code, _, err = _run(
        settings.root, "regions", "remove", region, w.included[0], "--rationale", "x"
    )
    assert code == 0, err
    code, out, err = _run(settings.root, "regions", "snapshot", region)
    assert code == 0, err
    version = out.split()[-1]
    code, out, err = _run(settings.root, "regions", "add", region, w.extra, "--rationale", "kept")
    assert code == 0, err
    code, out, err = _run(settings.root, "regions", "reject", region, w.extra)
    assert code == 0 and out.startswith("reject"), err
    code, out, err = _run(settings.root, "regions", "snapshot", region)
    other = out.split()[-1]
    assert other != version
    code, _, err = _run(settings.root, "regions", "link", version, other, "--subregion-of")
    assert code == 0, err
    code, _, err = _run(settings.root, "regions", "link", other, version, "--subregion-of")
    assert code != 0 and "not-a-subset" in err
    code, _, err = _run(settings.root, "regions", "link", other, version)
    assert code == 2
    code, _, err = _run(
        settings.root, "regions", "link", other, version, "--related", "--note", "same topic"
    )
    assert code == 0, err
    code, text_out, err = _run(settings.root, "regions", "export", other)
    assert code == 0, err
    lines = text_out.splitlines()
    assert lines and lines[0].startswith("work\t") and "rules=" in lines[0]
    code, json_out, _ = _run(settings.root, "regions", "export", other, "--json")
    document = json.loads(json_out)
    assert document["version"] == other
    assert [m["id"] for m in document["members"]] == sorted(m["id"] for m in document["members"])
    code, listed, _ = _run(settings.root, "regions", "proposals", region)
    assert code == 0 and listed.strip() == "no open proposals"
    assert str(app)  # the app object is the one the runner drives
    assert w.project and _env(settings.root)


def test_cli_agent_proposal_listed(
    settings: Settings,
    region_project: RWorld,
    lin: Lineage,
    human: Actor,
    agent: Actor,
    tmp_path: Path,
) -> None:
    w = region_project
    region = _define(settings, tmp_path)
    decide_member(w.project, human, region, W, lin.source, "remove")
    proposal = propose_member(w.project, agent, region, W, lin.source, quote_basis(w, lin))
    code, out, err = _run(settings.root, "regions", "proposals", region)
    assert code == 0 and proposal in out and lin.source in out, err
    code, _, err = _run(
        settings.root,
        "regions",
        "add",
        region,
        lin.source,
        "--proposal",
        proposal,
        "--rationale",
        "ok",
    )
    assert code == 0, err
    code, out, _ = _run(settings.root, "regions", "proposals", region)
    assert out.strip() == "no open proposals"
