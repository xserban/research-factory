# ruff: noqa: F401, F811
"""Guards of the organisation class that must fail when deleted (plan Regions-C, review round).

Each test names the guard it protects; it was checked by removing the guard and watching the test
fail.
"""

from __future__ import annotations

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.labels import ConsolidationProposed
from factory.model.regions import RegionKind
from factory.regions.rules import MemberType, RegionRule, RuleSet, TermRule
from factory.services.consolidation import consolidation_next, start_pass
from factory.services.context import Project
from factory.services.labels import LabelInput, apply_labels
from factory.services.methods import methods_report
from factory.services.regions import define_region, snapshot_region
from factory.services.terms import promote_term
from tests.helpers import install_skill, open_session
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, screened, world
from tests.test_mcp_intuition import SESSION_I, _session
from tests.test_organisation_separation import AGENT, import_tag, label

W = MemberType.WORK
REF = "imp_01JZ9Q3K5M7N8P0R2S4T6V8W1J:5"


@pytest.mark.anyio
async def test_term_list_leaves_import_tag_applications_out_of_agent_counts(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    iw: IWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard: `exclude_import_tags=True` in the MCP `term_list`."""
    install_skill(settings, "rf-consolidate")
    import_tag(project, iw, "performer", iw.source, REF)
    label(project, iw.human, "performer", iw.other)
    promote_term(project, iw.human, name="performer", definition="d", applies_to=(W,))
    _session(monkeypatch, SESSION_I)
    async with open_session(settings, clock) as client:
        out = await client.call("term_list", project="demo")
    [term] = out["data"]["terms"]
    assert term["counts"] == {"confirmed": 1, "stated": 0, "inferred": 0}


@pytest.mark.anyio
async def test_all_four_tools_wait_for_an_open_pass(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard: `_require_pass_opened` on label_apply, consolidation_next, consolidation_propose and
    term_list."""
    install_skill(settings, "rf-consolidate")
    _session(monkeypatch, SESSION_I)
    async with open_session(settings, clock) as client:
        outs = [
            await client.call(
                "label_apply",
                project="demo",
                items=[{"target_type": "work", "target": "rf:x-00000000", "text": "x"}],
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
        assert out == {"ok": False, "errors": [{"field": "graph", "reason": "not available yet"}]}


def test_term_rule_guard_follows_a_pinned_version_built_from_events(
    project: Project, iw: IWorld
) -> None:
    """Guard: the `TermRule` branch of `_reaches_all` (reached through a `region` rule)."""
    import_tag(project, iw, "performer", iw.source, REF)  # a real label.applied event
    term = promote_term(project, iw.human, name="performer", definition="d", applies_to=(W,))
    pinned = define_region(
        project,
        iw.human,
        kind=RegionKind.REGION,
        name="by term",
        definition="d",
        rules=RuleSet(include=(TermRule(term_id=term),)),
    )
    version = snapshot_region(project, iw.human, pinned)
    with pytest.raises(FactoryValidationError) as caught:
        define_region(
            project,
            iw.writer,
            kind=RegionKind.REGION,
            name="wraps it",
            definition="d",
            rules=RuleSet(include=(RegionRule(version=version),)),
        )
    assert caught.value.issues[0].field == "rules.include[0]"
    # the same wrapper by a human is allowed: the guard is for agents
    define_region(
        project,
        iw.human,
        kind=RegionKind.REGION,
        name="wraps it",
        definition="d",
        rules=RuleSet(include=(RegionRule(version=version),)),
    )


def _models(project: Project) -> set[str]:
    return set(methods_report(project).models)


def test_methods_models_ignore_organisation_agent_events(project: Project, iw: IWorld) -> None:
    """Guards: the `label.`, `region.` and `consolidation.` prefixes and the `consolidate` task
    branch of the methods statement. Each step uses a model name of its own."""

    def as_model(name: str) -> Actor:
        return iw.writer.model_copy(update={"model": name})

    before = _models(project)
    apply_labels(
        project,
        as_model("m-label"),
        [LabelInput(target_type=W, target=iw.source, text="kernel")],
    )
    define_region(
        project,
        as_model("m-region"),
        kind=RegionKind.REGION,
        name="r",
        definition="d",
        rules=RuleSet(include=(TermRule(term_id="trm_" + "0" * 26),)),
    )
    label(project, iw.human, "Performer", iw.source)
    label(project, iw.human, "FAVOR+", iw.source)
    label(project, iw.human, "Performer", iw.other)
    label(project, iw.human, "FAVOR+", iw.other)
    start_pass(project, iw.human)
    claimer = as_model("m-claim")
    task = consolidation_next(project, claimer)  # task.claimed by an agent
    assert task is not None
    proposed = ConsolidationProposed(
        proposal_id="cnp_01JZ9Q3K5M7N8P0R2S4T6V8W1J",
        pass_id=task.pass_id,
        cluster_index=task.cluster_index,
        action="keep",
        members=(task.members[0]["id"],),
        reason="r",
    )
    project.record(
        [
            project.events.make(
                "consolidation.proposed",
                proposed,
                as_model("m-proposal"),
                input_blob=project.blobs.put_json({"x": 1}),
            )
        ]
    )
    assert _models(project) == before


def _term_region(project: Project, iw: IWorld, term: str, rules: RuleSet | None = None) -> str:
    return define_region(
        project,
        iw.human,
        kind=RegionKind.REGION,
        name="by term",
        definition="d",
        rules=rules or RuleSet(include=(TermRule(term_id=term),)),
    )


def test_a_later_tag_withholds_a_region_from_agents_at_read(project: Project, iw: IWorld) -> None:
    """Guard: the `TermRule` branch of `_reaches_all`, evaluated at read by `region_withheld`."""
    from factory.services.regions import (
        agent_region_state,
        region_withheld,
        require_agent_visible,
    )

    label(project, iw.human, "performer", iw.other)
    term = promote_term(project, iw.human, name="performer", definition="d", applies_to=(W,))
    direct = _term_region(project, iw, term)
    version = snapshot_region(project, iw.human, direct)
    pinned = _term_region(project, iw, term, RuleSet(include=(RegionRule(version=version),)))
    assert not region_withheld(project, direct) and not region_withheld(project, pinned)
    import_tag(project, iw, "performer", iw.source, REF)  # a tag arrives after the definitions
    for region in (direct, pinned):
        assert region_withheld(project, region)
        with pytest.raises(FactoryValidationError):
            require_agent_visible(project, region_id=region)
    assert agent_region_state(project, direct).latest_version == version  # state shown, no counts


def test_a_later_merge_withholds_a_region_from_agents_at_read(project: Project, iw: IWorld) -> None:
    from factory.services.labels import merge_labels
    from factory.services.regions import region_withheld

    label(project, iw.human, "performer", iw.other)
    import_tag(project, iw, "secret key", iw.source, REF)
    term = promote_term(project, iw.human, name="performer", definition="d", applies_to=(W,))
    region = _term_region(project, iw, term)
    assert not region_withheld(project, region)  # the tag key is not the term's yet
    merge_labels(project, iw.human, "performer", "secret key", "same method")
    assert region_withheld(project, region)
