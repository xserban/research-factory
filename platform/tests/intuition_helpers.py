"""Shared setup for the intuition-layer tests (slice 3c, plan G3-A).

Payload-level builders (`recorded`, `reviewed`, `quote_src`, `cite_src`) write events straight to
the log as the other index tests do. The world fixture (`ilin`, a G2 world with confirmed ideas,
converted papers and live contribution items) is added with the service tests. Every identifier is
invented; document text is hand-written Markdown from `tests/contribution_helpers.py`.
"""

from __future__ import annotations

# ruff: noqa: F401, F811
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor, Event
from factory.model.intuition import InterpretationInput
from factory.model.lineage import LineageDecision
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.ideas import decide_idea, propose_idea
from tests.contribution_helpers import ext_a
from tests.evidence_helpers import claim_input, run_pass
from tests.helpers import S2, S3
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world
from tests.test_extraction_agreement import _r, ext_b

ULID = "01HZX3K4M5N6P7Q8R9S0T1V2W"
INT1 = f"int_{ULID}A"
INT2 = f"int_{ULID}B"
INT3 = f"int_{ULID}C"
IDEA1 = "ida_01HZX3K4M5N6P7Q8R9S0000201"
IDEA2 = "ida_01HZX3K4M5N6P7Q8R9S0000202"
PAPER1 = "rf:p1-00000001"
CNV1 = f"cnv_{ULID}A"
DOC1 = f"doc_{ULID}A"


def quote_src(
    work: str = PAPER1,
    conversion: str = CNV1,
    anchor: str = "s1.p2",
    quote: str = "positive random-feature map",
    role: str = "supports",
) -> dict[str, Any]:
    return {
        "kind": "quote",
        "role": role,
        "work_id": work,
        "conversion_id": conversion,
        "anchor": anchor,
        "quote": quote,
    }


def cite_src(*, reference: str | None = None, work: str | None = None) -> dict[str, Any]:
    return {"kind": "citation", "role": "background", "reference": reference, "work_id": work}


def stored(source: dict[str, Any], **computed: Any) -> dict[str, Any]:
    """A source as the recorded event stores it."""
    full: dict[str, Any] = {
        "kind": None,
        "role": None,
        "work_id": None,
        "conversion_id": None,
        "anchor": None,
        "quote": None,
        "reference": None,
        "document_id": None,
        "link_state": None,
        "resolved_work": None,
    }
    full.update(source)
    if source["kind"] == "quote":
        full["document_id"] = DOC1
    full.update(computed)
    return full


def recorded(
    interpretation_id: str = INT1,
    *,
    target: str = IDEA1,
    target_kind: str = "idea",
    author: str = "agent",
    supersedes: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    text_: str = "It approximates the softmax kernel.",
) -> dict[str, Any]:
    return {
        "interpretation_id": interpretation_id,
        "target": target,
        "target_kind": target_kind,
        "text": text_,
        "sources": [stored(s) for s in (sources if sources is not None else [quote_src()])],
        "author": author,
        "supersedes": supersedes,
        "task_id": None,
        "verifier": 1,
    }


def reviewed(
    interpretation_id: str = INT1,
    state: str = "reviewed",
    *,
    note: str = "",
    self_reviewed: bool = False,
    channel: str = "cli",
) -> dict[str, Any]:
    return {
        "interpretation_id": interpretation_id,
        "state": state,
        "note": note,
        "self_reviewed": self_reviewed,
        "channel": channel,
    }


CPT1 = f"cpt_{ULID}A"
CPT2 = f"cpt_{ULID}B"
CPT3 = f"cpt_{ULID}C"
CUL1 = f"cul_{ULID}A"
CUL2 = f"cul_{ULID}B"
CUL3 = f"cul_{ULID}C"


def concept_source(
    kind: str = "textbook", citation: str = "Textbook, chapter 3", work_id: str | None = None
) -> dict[str, Any]:
    """A stored concept source (digest and verifiability computed as the service does)."""
    from factory.intuition.classify import source_digest
    from factory.model.intuition import ConceptSourceInput

    digest = source_digest(
        ConceptSourceInput.model_validate({"kind": kind, "citation": citation, "work_id": work_id})
    )
    return {
        "kind": kind,
        "citation": citation,
        "work_id": work_id,
        "digest": digest,
        "verifiable": work_id is not None,
    }


def defined(
    concept_id: str = CPT1,
    *,
    name: str = "random features",
    aliases: tuple[str, ...] = (),
    text_: str | None = "A map that approximates a kernel.",
    source: dict[str, Any] | None = None,
    quotes: list[dict[str, Any]] | None = None,
    author: str = "agent",
    supersedes: str | None = None,
) -> dict[str, Any]:
    return {
        "concept_id": concept_id,
        "name": name,
        "aliases": list(aliases),
        "text": text_,
        "source": source,
        "quotes": [stored(q) for q in (quotes or [])],
        "author": author,
        "supersedes": supersedes,
    }


def source_decided(
    concept_id: str, decision: str, digest: str, *, note: str = "", channel: str = "cli"
) -> dict[str, Any]:
    return {
        "concept_id": concept_id,
        "decision": decision,
        "source_digest": digest,
        "note": note,
        "channel": channel,
    }


def concept_reviewed(
    concept_id: str,
    definition: str,
    state: str = "reviewed",
    *,
    note: str = "",
    self_reviewed: bool = False,
    channel: str = "cli",
) -> dict[str, Any]:
    return {
        "concept_id": concept_id,
        "definition": definition,
        "state": state,
        "note": note,
        "self_reviewed": self_reviewed,
        "channel": channel,
    }


def link_proposed(
    link_id: str = CUL1,
    *,
    from_node: str = IDEA1,
    from_kind: str = "idea",
    concept: str = CPT1,
    status: str = "inferred",
    reason: str = "no-basis",
    quote: dict[str, Any] | None = None,
    reference: str | None = None,
    cited_work: str | None = None,
    note: str | None = "no basis",
    basis_digest: str = "bd1",
) -> dict[str, Any]:
    return {
        "link_id": link_id,
        "from_node": from_node,
        "from_kind": from_kind,
        "concept_id": concept,
        "basis_kind": "quote" if quote else ("citation" if reference else "none"),
        "quote": None if quote is None else stored(quote),
        "reference": reference,
        "cited_work": cited_work,
        "basis_digest": basis_digest,
        "status": status,
        "status_reason": reason,
        "note": note,
    }


def link_decided(link_id: str, decision: str, rationale: str = "checked") -> dict[str, Any]:
    return {"link_id": link_id, "decision": decision, "rationale": rationale, "channel": "cli"}


def merged(into: str, from_concept: str, reason: str = "same idea") -> dict[str, Any]:
    return {"into": into, "from_concept": from_concept, "reason": reason}


def reviewer(project: Project, user: str | None = None) -> Actor:
    """A human in a session other than the (agent) fixtures'; `user` names another human."""
    base = project.human_actor()
    return base.model_copy(update={"session": S2, "user": user or base.user, "id": user or base.id})


def record_event(
    project: Project, type_: str, payload: dict[str, Any], actor: Actor | None = None
) -> Event:
    model = project.catalog.get(type_).payload.model_validate(payload)
    actor = actor or reviewer(project)
    blob = project.blobs.put_json(payload) if actor.kind == "agent" else None
    event = project.events.make(type_, model, actor, input_blob=blob)
    project.record([event])
    return event


def rows(project: Project, sql: str) -> list[tuple[Any, ...]]:
    project.index.sync()
    with project.index.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]


def live_conversion(project: Project, work: str) -> tuple[str, str]:
    """(conversion id, document id) of the latest conversion of a non-superseded document."""
    [(cnv, doc)] = rows(
        project,
        "SELECT c.conversion_id, c.document_id FROM document_conversions c "
        "JOIN fulltext_documents d ON d.document_id = c.document_id "
        f"WHERE d.work_id = '{work}' AND d.superseded_by IS NULL "
        "ORDER BY c.event_id DESC LIMIT 1",
    )
    return str(cnv), str(doc)


SKILL = "rf-intuition@1a2b3c4d"
WRITER_MODEL = "claude-intuition-only"
"""A model no other agent of the world uses, so a leak into a model list shows."""


@dataclass
class IWorld:
    """A G2 world: two confirmed ideas, the source paper converted (document v3, anchors
    s1.p1-p5) and live contribution items; `writer` is an intuition agent, `human` the
    researcher in another session."""

    lin: Lineage
    source: str
    other: str
    third: str
    idea1: str
    idea2: str
    cnv: str
    doc: str
    writer: Actor
    human: Actor

    def quote(
        self, anchor: str = "s1.p4", quote: str = "very long sequences degrade"
    ) -> dict[str, Any]:
        return quote_src(self.source, self.cnv, anchor, quote)

    def entry(
        self,
        target: str | None = None,
        *,
        text: str = "Long sequences are the stated limit of the module.",
        sources: list[dict[str, Any]] | None = None,
        supersedes: str | None = None,
    ) -> InterpretationInput:
        return InterpretationInput.model_validate(
            {
                "target": target or self.idea1,
                "text": text,
                "sources": sources if sources is not None else [self.quote()],
                "supersedes": supersedes,
            }
        )


def writer_actor(session: str = S3, ident: str = "intuiter") -> Actor:
    return Actor(
        kind="agent",
        id=ident,
        user="obd",
        session=session,
        model=WRITER_MODEL,
        skill=SKILL,
    )


@pytest.fixture
def iw(project: Project, agent: Actor, lin: Lineage, world: list[str]) -> IWorld:
    human = reviewer(project)
    others = [w for w in world if w != lin.source]
    idea1 = propose_idea(
        project, agent, "linear attention", lin.source, lin.base, [lin.source, others[0]]
    )
    idea2 = propose_idea(
        project, agent, "softmax attention", lin.source, lin.addition, [lin.source]
    )
    for idea in (idea1, idea2):
        decide_idea(project, human, idea, LineageDecision.CONFIRM, "checked")
    cnv, doc = live_conversion(project, lin.source)
    return IWorld(
        lin=lin,
        source=lin.source,
        other=others[0],
        third=others[1],
        idea1=idea1,
        idea2=idea2,
        cnv=cnv,
        doc=doc,
        writer=writer_actor(),
        human=human,
    )


@pytest.fixture
def evidenced(project: Project, ext_a: Actor, ext_b: Actor, world: list[str]) -> None:
    """Real evidence: both passes extract one row per work (so rows are agreed and final) and
    pass A records a claim per work. Runs before `lin` replaces the source document."""
    run_pass(project, ext_a, PassLabel.A, lambda _w: [_r()], lambda _w: [claim_input()])
    run_pass(project, ext_b, PassLabel.B, lambda _w: [_r()])


@pytest.fixture
def iwe(evidenced: None, iw: IWorld) -> IWorld:
    """`iw` in a world that also has final evidence rows and claims."""
    return iw
