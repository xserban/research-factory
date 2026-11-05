# ruff: noqa: F401, F811
"""`check` findings of the interpretation layer (slice 3c, plan G3-C, task 3)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from factory.events.envelope import Actor
from factory.model.intuition import ConceptInput, UseBasisInput
from factory.model.project import RigorMode
from factory.model.screening import Channel
from factory.services import check as check_module
from factory.services.check import (
    INTERPRETATION_UNREVIEWED_CEILING,
    LAYER_CHECK_CODES,
    LEVELS,
    Finding,
    _findings_as,
    check,
    evidence_snapshot,
)
from factory.services.concepts import (
    decide_concept_link,
    decide_concept_source,
    define_concept,
    propose_concept_link,
    review_concept,
)
from factory.services.context import Project
from factory.services.interpretations import (
    intuition_next,
    record_interpretation,
    review_interpretation,
)
from tests.intuition_helpers import (
    CPT1,
    CPT2,
    CUL1,
    CUL2,
    IWorld,
    concept_reviewed,
    ctr_a,
    ctr_b,
    iw,
    lin,
    link_proposed,
    record_event,
    reviewed,
    reviewer,
    screened,
    world,
)
from tests.intuition_separation import populate_layer
from tests.lineage_helpers import with_references

EXPLORATORY, PILOT, SYSTEMATIC = RigorMode.EXPLORATORY, RigorMode.PILOT, RigorMode.SYSTEMATIC
TEXTBOOK = {"kind": "textbook", "citation": "Textbook, chapter 3"}


def codes(project: Project, mode: RigorMode = PILOT) -> dict[str, Finding]:
    """The layer's findings under `mode`, through the rule and the level table only (the rest of
    `check` is not recomputed); `test_end_to_end_findings_agree` ties this to `_findings_as`."""
    project.index.sync()
    out: dict[str, Finding] = {}
    for hit in check_module._layer(project):
        severity = check_module._severity(hit, mode)
        if severity is not None:
            out[hit.code] = check_module._finding(hit, severity)
    return out


def test_end_to_end_findings_agree(project: Project, iw: IWorld) -> None:
    agent_interpretation(project, iw)
    for mode in (EXPLORATORY, SYSTEMATIC):
        whole = {f.code: f for f in _findings_as(project, mode) if f.code in LAYER_CHECK_CODES}
        assert whole == codes(project, mode)


def agent_interpretation(project: Project, iw: IWorld, target: str | None = None) -> str:
    batch = intuition_next(project, iw.writer, targets=[target or iw.idea1]).batch
    assert batch is not None
    return record_interpretation(
        project, iw.writer, iw.entry(target or iw.idea1), task_id=batch.task_id
    )


def concept(
    project: Project, iw: IWorld, name: str, *, approve: bool = True, source: bool = True
) -> str:
    entry = ConceptInput.model_validate({"name": name, "source": TEXTBOOK if source else None})
    cid = define_concept(project, iw.writer, entry)
    if approve:
        decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    return cid


def _finding(code: str, severity: str = "error") -> Finding:
    return Finding(code=code, severity=severity, refs=[], message="m")  # type: ignore[arg-type]


def test_evidence_ok_ignores_layer_errors_except_a_leak() -> None:
    def report(*findings: Finding) -> check_module.CheckReport:
        return check_module.CheckReport(mode=PILOT, evaluated_as=PILOT, findings=list(findings))

    unreviewed = _finding("interpretation-unreviewed")
    assert not report(unreviewed).ok and report(unreviewed).evidence_ok
    assert report(_finding("concept-cycle")).evidence_ok
    assert not report(_finding("layer-leak")).evidence_ok
    assert not report(unreviewed, _finding("broken-link")).evidence_ok
    assert report(_finding("broken-link", "warning")).evidence_ok
    assert report().evidence_ok and report().ok


def test_a_sound_project_with_an_unreviewed_interpretation_is_evidence_ok(
    project: Project, iw: IWorld
) -> None:
    agent_interpretation(project, iw)
    report = check(project, promote_to=None)
    layer_errors = [f for f in _findings_as(project, SYSTEMATIC) if f.code in LAYER_CHECK_CODES]
    assert any(f.severity == "error" for f in layer_errors)  # the spec's systematic error
    from factory.cli.render import check_lines

    lines = check_lines(report)
    assert any(line.startswith("interpretation layer (not evidence)") for line in lines)
    assert report.evidence_ok == (
        not any(f.severity == "error" and f.code not in LAYER_CHECK_CODES for f in report.findings)
    )


def test_the_severity_table_is_as_specified() -> None:
    assert LEVELS["interpretation-unreviewed"] == ("warning", "warning", "error")
    assert LEVELS["concept-unreviewed"] == ("warning", "warning", "error")
    for code in (
        "interpretation-source-stale",
        "interpretation-self-reviewed",
        "concept-source-missing",
        "concept-link-unconfirmed",
        "layer-review-dropped",
    ):
        assert LEVELS[code] == ("warning", "warning", "warning"), code
    for code in ("layer-leak", "concept-cycle"):
        assert LEVELS[code] == ("error", "error", "error"), code
    assert INTERPRETATION_UNREVIEWED_CEILING == 0


def test_no_new_codes_without_layer(project: Project, iw: IWorld) -> None:
    """Review Focus 5."""
    for mode in (EXPLORATORY, PILOT, SYSTEMATIC):
        assert [f for f in _findings_as(project, mode) if f.code in LAYER_CHECK_CODES] == []


def test_interpretation_unreviewed_fires_and_clears(project: Project, iw: IWorld) -> None:
    ident = agent_interpretation(project, iw)
    finding = codes(project)["interpretation-unreviewed"]
    assert finding.refs == [ident] and finding.severity == "warning"
    assert "1 interpretation" in finding.message
    review_interpretation(project, iw.human, ident, "reviewed", "", Channel.CLI)
    assert "interpretation-unreviewed" not in codes(project)


def test_unreviewed_error_only_in_systematic(project: Project, iw: IWorld) -> None:
    agent_interpretation(project, iw)
    concept(project, iw, "softmax attention")
    for code in ("interpretation-unreviewed", "concept-unreviewed"):
        assert codes(project, EXPLORATORY)[code].severity == "warning"
        assert codes(project, PILOT)[code].severity == "warning"
        assert codes(project, SYSTEMATIC)[code].severity == "error"


def test_ceiling_above_the_count_keeps_a_warning(
    project: Project, iw: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_interpretation(project, iw)
    monkeypatch.setattr(check_module, "INTERPRETATION_UNREVIEWED_CEILING", 1)
    assert codes(project, SYSTEMATIC)["interpretation-unreviewed"].severity == "warning"


def test_concept_unreviewed_needs_an_approved_unmerged_concept(
    project: Project, iw: IWorld
) -> None:
    concept(project, iw, "unapproved one", approve=False)
    assert "concept-unreviewed" not in codes(project)
    cid = concept(project, iw, "softmax attention")
    assert codes(project)["concept-unreviewed"].refs == [cid]
    review_concept(project, iw.human, cid, "reviewed", "", Channel.CLI)
    assert "concept-unreviewed" not in codes(project)


def test_source_stale_after_a_new_document_version(
    project: Project, iw: IWorld, agent: Actor
) -> None:
    ident = agent_interpretation(project, iw)
    assert "interpretation-source-stale" not in codes(project)
    with_references(project, agent, iw.source, version="v4")
    finding = codes(project)["interpretation-source-stale"]
    assert finding.refs == [ident]
    assert codes(project, SYSTEMATIC)["interpretation-source-stale"].severity == "warning"


def test_self_reviewed_interpretation_and_concept(project: Project, iw: IWorld) -> None:
    from factory.services.interpretations import record_interpretation as record

    ident = record(project, iw.human, iw.entry(iw.idea2))
    review_interpretation(project, iw.human, ident, "reviewed", "", Channel.CLI)
    cid = define_concept(
        project,
        iw.human,
        ConceptInput.model_validate({"name": "feature map", "source": TEXTBOOK}),
        approve_source=True,
    )
    review_concept(project, iw.human, cid, "reviewed", "", Channel.CLI)
    finding = codes(project)["interpretation-self-reviewed"]
    assert finding.refs == sorted([ident, cid])


def test_self_reviewed_absent_for_an_independent_review(project: Project, iw: IWorld) -> None:
    ident = agent_interpretation(project, iw)
    review_interpretation(project, iw.human, ident, "reviewed", "", Channel.CLI)
    assert "interpretation-self-reviewed" not in codes(project)


def test_concept_source_missing_includes_rejected(project: Project, iw: IWorld) -> None:
    none = concept(project, iw, "no source", approve=False, source=False)
    proposed = concept(project, iw, "waiting", approve=False)
    rejected = concept(project, iw, "refused", approve=False)
    decide_concept_source(project, iw.human, rejected, "reject", "no", Channel.CLI)
    ok = concept(project, iw, "fine")
    assert codes(project)["concept-source-missing"].refs == sorted([none, proposed, rejected])
    assert ok not in codes(project)["concept-source-missing"].refs


def test_concept_link_unconfirmed_clears_on_a_decision(project: Project, iw: IWorld) -> None:
    cid = concept(project, iw, "softmax attention")
    link = propose_concept_link(project, iw.writer, iw.idea1, cid, UseBasisInput(), note="x")
    assert codes(project)["concept-link-unconfirmed"].refs == [link.link_id]
    decide_concept_link(project, iw.human, link.link_id, "confirm", "checked", Channel.CLI)
    assert "concept-link-unconfirmed" not in codes(project)


def test_layer_review_dropped_names_the_review_event(project: Project, iw: IWorld) -> None:
    """The G3-A carry-over: a review the fold dropped is reported, so a researcher sees a review
    that did not count."""
    ident = agent_interpretation(project, iw)
    # the writer's own session answering: the fold drops it (R-51)
    event = record_event(project, "interpretation.reviewed", reviewed(ident), iw.writer)
    cid = concept(project, iw, "softmax attention")
    defn = _definition_event(project, cid)
    ev2 = record_event(project, "concept.reviewed", concept_reviewed(cid, defn), iw.writer)
    finding = codes(project)["layer-review-dropped"]
    assert finding.refs == sorted([event.id, ev2.id])
    assert codes(project, SYSTEMATIC)["layer-review-dropped"].severity == "warning"


def _definition_event(project: Project, cid: str) -> str:
    from tests.intuition_helpers import rows

    [(event_id,)] = rows(project, f"SELECT definition_event FROM concepts WHERE concept_id='{cid}'")
    return str(event_id)


def test_a_relayed_review_is_stored_unfolded_and_reported(project: Project, iw: IWorld) -> None:
    """A human-kind review that came over the MCP channel (a relay by an agent session) never
    counts, whatever its session; the service refusal stays, and the log is still kept."""
    from tests.intuition_helpers import rows

    ident = agent_interpretation(project, iw)
    relay = iw.human.model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W5A"})
    event = record_event(
        project, "interpretation.reviewed", reviewed(ident, "reviewed", channel="mcp"), relay
    )
    assert rows(project, "SELECT folded FROM interpretation_reviews") == [(0,)]
    assert rows(project, "SELECT review_state FROM interpretations") == [("unreviewed",)]
    cid = concept(project, iw, "softmax attention")
    definition = _definition_event(project, cid)
    ev2 = record_event(
        project, "concept.reviewed", concept_reviewed(cid, definition, channel="mcp"), relay
    )
    assert rows(project, "SELECT folded FROM concept_reviews") == [(0,)]
    assert rows(project, "SELECT review_state FROM concepts") == [("unreviewed",)]
    assert codes(project)["layer-review-dropped"].refs == sorted([event.id, ev2.id])


def test_a_relayed_link_or_source_decision_does_not_count(project: Project, iw: IWorld) -> None:
    from tests.intuition_helpers import link_decided, rows, source_decided

    entry = ConceptInput.model_validate({"name": "kernel", "source": TEXTBOOK})
    cid = define_concept(project, iw.writer, entry)
    digest = rows(project, f"SELECT source_digest FROM concepts WHERE concept_id='{cid}'")[0][0]
    relay = iw.human.model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W5A"})
    record_event(
        project,
        "concept.source_decided",
        source_decided(cid, "approve", str(digest), channel="mcp"),
        relay,
    )
    assert rows(project, "SELECT source_state FROM concepts") == [("proposed",)]
    link = propose_concept_link(project, iw.writer, iw.idea1, cid, UseBasisInput(), note="x")
    payload = link_decided(link.link_id, "confirm")
    payload["channel"] = "mcp"
    record_event(project, "concept.link_decided", payload, relay)
    assert rows(project, "SELECT status FROM concept_uses") == [("inferred",)]


def test_a_review_that_counted_is_not_reported_dropped(project: Project, iw: IWorld) -> None:
    ident = agent_interpretation(project, iw)
    review_interpretation(project, iw.human, ident, "reviewed", "", Channel.CLI)
    assert "layer-review-dropped" not in codes(project)


def test_concept_cycle_from_constructed_log(project: Project, iw: IWorld) -> None:
    """The service refuses a cycle; a log written around it is still reported."""
    a = concept(project, iw, "alpha")
    b = concept(project, iw, "beta")
    record_event(
        project,
        "concept.link_proposed",
        link_proposed(
            CUL1, from_node=a, from_kind="concept", concept=b, reason="concept-to-concept"
        ),
        iw.writer,
    )
    assert "concept-cycle" not in codes(project)
    record_event(
        project,
        "concept.link_proposed",
        link_proposed(
            CUL2, from_node=b, from_kind="concept", concept=a, reason="concept-to-concept"
        ),
        iw.writer,
    )
    for mode in (EXPLORATORY, PILOT, SYSTEMATIC):
        finding = codes(project, mode)["concept-cycle"]
        assert finding.severity == "error" and finding.refs == sorted([a, b])


def test_layer_leak_fires_on_a_planted_reference(
    project: Project, iw: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_interpretation(project, iw)  # a leak needs a layer to leak
    assert "layer-leak" not in codes(project)
    monkeypatch.setattr(
        check_module,
        "grouped_rows",
        lambda _p: ["rows mention int_01HZX3K4M5N6P7Q8R9S0T1V2WA"],
    )
    for mode in (EXPLORATORY, PILOT, SYSTEMATIC):
        finding = codes(project, mode)["layer-leak"]
        assert finding.severity == "error" and finding.refs == ["grouped_rows"]


def test_a_quote_that_starts_like_an_edge_id_is_not_a_leak(
    project: Project, iw: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_interpretation(project, iw)
    monkeypatch.setattr(
        check_module,
        "grouped_rows",
        lambda _p: ['{"quote":"uses: a kernel","note":"explains: why"}'],
    )
    assert "layer-leak" not in codes(project, SYSTEMATIC)
    monkeypatch.setattr(
        check_module, "grouped_rows", lambda _p: ['"uses:cul_01HZX3K4M5N6P7Q8R9S0T1V2WA"']
    )
    assert codes(project)["layer-leak"].refs == ["grouped_rows"]


def test_an_output_that_cannot_be_computed_is_reported_unscanned(
    project: Project, iw: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.errors import FactoryValidationError, ValidationIssue

    agent_interpretation(project, iw)

    def fails(_p: object) -> None:
        raise FactoryValidationError([ValidationIssue("schema", "missing")])

    monkeypatch.setattr(check_module, "evidence_report", fails)
    finding = codes(project)["layer-scan-incomplete"]
    assert finding.severity == "warning" and finding.refs == ["evidence_report"]
    assert "layer-leak" not in codes(project)


def test_the_snapshot_includes_rendered_methods_text_and_status(
    project: Project, iw: IWorld
) -> None:
    snapshot = evidence_snapshot(project)
    assert {"methods_text", "status"} <= set(snapshot)


def test_layer_leak_fires_on_a_layer_class_in_an_export(
    project: Project, iw: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_interpretation(project, iw)

    def planted(*_a: object, **_k: object) -> Iterator[str]:
        yield '{"nodes":[{"class":"interpretation","id":"x"}]}\n'

    monkeypatch.setattr(check_module, "iter_graph_export", planted)
    assert codes(project)["layer-leak"].refs == ["export:dot", "export:json"]


def test_a_populated_layer_leaks_nothing_into_the_evidence(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    assert "layer-leak" not in codes(project)
    snapshot = evidence_snapshot(project)
    assert "final_rows" in snapshot and "evidence_report" in snapshot


def test_messages_carry_no_document_text(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    for mode in (EXPLORATORY, PILOT, SYSTEMATIC):
        for finding in _findings_as(project, mode):
            if finding.code in LAYER_CHECK_CODES:
                blob = finding.message + " ".join(finding.refs)
                assert "very long sequences" not in blob and "Unlike softmax" not in blob
                assert "A human replacement" not in blob


def test_check_is_read_only(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    from factory.events.reader import read_all

    before = len(read_all(project.paths.events_dir, project.catalog))
    check(project)
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
