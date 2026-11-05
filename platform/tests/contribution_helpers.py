"""Shared setup for the contribution recording tests (slice 3b, plan G2-B).

`world` is the full-text screened world with both schemas declared (plan G2-A's setup). The first
included work can be given a document with a bibliography and in-text markers (`with_references`),
which gives it a current G1 extraction. Body paragraphs of that document:

    s1.p1  We build on linear attention [5] for vision.   (quotes see plain text: markers read [5])
    s1.p2  Unlike softmax attention [3], our module is linear.
    s1.p3  It reaches 82.4% top-1 on ImageNet.
    s1.p4  A limitation is that very long sequences degrade.
    s1.p5  Plain text with no marker.
"""

from collections.abc import Callable, Mapping

import pytest

from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput, FieldInput, Scope
from factory.model.fulltext import Route
from factory.model.protocol import ExtractionSchema, ScreeningStage
from factory.packs.contribution import CONTRIBUTION_V1
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.references import current_extraction, extract_references
from factory.sources.registry import SourceFactory
from tests.document_helpers import make_registry, run_convert
from tests.references_service_helpers import bib_html
from tests.test_acceptance_fulltext_screening import _screened_full_text_world
from tests.test_extraction_next import FIELDS, SESSION_A, _extractor
from tests.test_fulltext_service import StubRoute, always, retrieved

C = Scope.CONTRIBUTION
FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
SESSION_C = "01JZ9Q3K5M7N8P0R2S4T6V8W1C"
SESSION_D = "01JZ9Q3K5M7N8P0R2S4T6V8W1D"
CONTRIB_FIELDS = tuple(f.name for f in CONTRIBUTION_V1.fields)

ENTRIES = [
    "A. Alpha. Softmax attention at scale. Conf One, 2017.",
    "B. Beta. Vision transformers revisited. Conf Two, 2018.",
    "C. Gamma. Attention is a kernel. Conf Three, 2019.",
    "D. Delta. Random features for attention. Conf Four, 2020.",
    "E. Epsilon. Linear attention with kernels. Conf Five, 2020.",
    "F. Zeta. Efficient vision backbones. Conf Six, 2021.",
]
BODY = [
    "We build on linear attention {cite:5} for vision.",
    "Unlike softmax attention {cite:3}, our module is linear.",
    "It reaches 82.4% top-1 on ImageNet.",
    "A limitation is that very long sequences degrade.",
    "Plain text with no marker.",
]
P1 = ("s1.p1", "We build on linear attention [5] for vision.")
P2 = ("s1.p2", "Unlike softmax attention [3], our module is linear.")
P3 = ("s1.p3", "It reaches 82.4% top-1 on ImageNet.")
P4 = ("s1.p4", "A limitation is that very long sequences degrade.")
P5 = ("s1.p5", "Plain text with no marker.")


def evidence_and_contribution_schemas() -> tuple[ExtractionSchema, ExtractionSchema]:
    evidence = ExtractionSchema(
        pack="ml-benchmark",
        pack_version=1,
        fields=FIELDS,
        comparability_keys=("task", "dataset", "metric"),
        dual_extract_sample=1.0,
    )
    contribution = ExtractionSchema(
        pack="contribution",
        pack_version=1,
        fields=CONTRIB_FIELDS,
        dual_extract_sample=1.0,
        claims=False,
    )
    return evidence, contribution


def declare_both(project: Project, agent: Actor) -> None:
    current = current_protocol(project)
    assert current is not None
    evidence, contribution = evidence_and_contribution_schemas()
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(
            update={"extraction_schema": evidence, "contribution_schema": contribution}
        ),
        reason="declare both schemas",
        semantic=True,
        effects={},
    )


@pytest.fixture
def ctr_a() -> Actor:
    return _extractor(SESSION_C, "claude-opus-5-5")


@pytest.fixture
def ctr_b() -> Actor:
    return _extractor(SESSION_D, "claude-sonnet-5-5")


@pytest.fixture
def ext_a() -> Actor:
    return _extractor(SESSION_A, "claude-opus-5-5")


@pytest.fixture
def screened(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


@pytest.fixture
def world(project: Project, agent: Actor, screened: list[str]) -> list[str]:
    declare_both(project, agent)
    return screened


def with_references(
    project: Project,
    agent: Actor,
    work: str,
    *,
    entries: list[str] | None = None,
    body: list[str] | None = None,
    version: str = "v3",
    sources: Mapping[str, SourceFactory] | None = None,
) -> str:
    """Give `work` a new document version holding this bibliography and body, convert it and
    extract its references (offline: without `sources` every lookup fails). Returns the current
    extraction id."""
    html = bib_html(ENTRIES if entries is None else entries, BODY if body is None else body)
    route = StubRoute(Route.ARXIV_HTML, always(retrieved(Route.ARXIV_HTML, html, version=version)))
    fetch_fulltext(
        project, routes={Route.ARXIV_HTML: route}, work_ids=[work], only=[Route.ARXIV_HTML]
    )
    run_convert(project, make_registry())
    extract_references(project, agent, [work], sources=sources or {})
    rex = current_extraction(project, work)
    assert rex is not None
    return rex


def field(
    value: str | int | float | bool,
    anchor: str | None = None,
    quote: str | None = None,
    *,
    unit: str | None = None,
) -> FieldInput:
    return FieldInput(value=value, anchor=anchor, quote=quote, unit=unit)


def item(
    kind: str,
    paragraph: tuple[str, str],
    *,
    name: str | None = None,
    statement: str | None = None,
    **extra: FieldInput,
) -> ExtractedRowInput:
    """An item of `kind` quoting the whole paragraph `(anchor, text)`; `name` must occur in it."""
    anchor, text = paragraph
    fields: dict[str, FieldInput] = {"item_kind": FieldInput(value=kind)}
    if kind != "not-stated":
        fields["statement"] = field(statement or text, anchor, text)
    if name is not None:
        fields["name"] = field(name, anchor, text)
    fields.update(extra)
    return ExtractedRowInput(fields=fields)


def not_stated(kind: str) -> ExtractedRowInput:
    return ExtractedRowInput(
        fields={"item_kind": FieldInput(value="not-stated"), "absent_kind": FieldInput(value=kind)}
    )
