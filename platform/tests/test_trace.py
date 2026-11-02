"""`trace`: the R-01 chain walked from any identifier, backwards or forwards (plan 5b, task 3).

Each test asserts the path it names: the kinds and identifiers along a branch, not merely that a
node exists. The fixtures are the ones the other services' tests use.
"""

from collections.abc import Callable, Mapping

import pytest

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.chase import ChaseDirection
from factory.model.screening import Channel
from factory.model.seed import SeedKind
from factory.model.work import ProvenanceMethod
from factory.services.agreement import resolve_disagreement
from factory.services.audit import audit_record, audit_sample
from factory.services.chase import search_chase
from factory.services.context import Project
from factory.services.dedup import dedup_run, revert_merge
from factory.services.protocol import current_protocol
from factory.services.search import get_work, list_works
from factory.services.seeds import all_seeds
from factory.services.trace import TraceNode, trace
from factory.sources.registry import SourceFactory
from tests.helpers import _setup
from tests.test_chase_service import _citing, _corpus, _ordinary, _settle
from tests.test_dedup_service import PREPRINT, PUBLISHED, _ingest
from tests.test_screening_next import _decide

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _path_to(root: TraceNode, kind: str, ident: str) -> list[TraceNode] | None:
    """The branch from `root` down to the first node of `kind` and `ident`, inclusive."""
    if root.kind == kind and root.id == ident:
        return [root]
    for child in root.children:
        below = _path_to(child, kind, ident)
        if below is not None:
            return [root, *below]
    return None


def _kinds(path: list[TraceNode]) -> list[str]:
    return [node.kind for node in path]


def _all_nodes(root: TraceNode) -> list[TraceNode]:
    return [root, *(node for child in root.children for node in _all_nodes(child))]


def _events_of(project: Project, name: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == name]


def test_trace_decision_reaches_question(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources, random_works=0)
    current = current_protocol(project)
    assert current is not None
    question_id = current.spec.question_id
    work_id = sorted(w.id for w in list_works(project))[0]
    decision_id = _decide(project, agent, work_id, "A", "screening", "exclude", "EX01", protocol_id)
    work = get_work(project, work_id)
    assert work is not None
    blob = work.provenance[0].raw_blob

    root = trace(project, decision_id)

    assert root.kind == "decision" and root.id == decision_id
    # The run's archived raw page, reached through the work's record.
    page = _path_to(root, "page", blob)
    assert page is not None
    assert _kinds(page) == ["decision", "work", "record", "page"]
    # The cited criterion and its parent element (the non-goal NG01), up to the question.
    element = _path_to(root, "element", f"{question_id}/NG01")
    assert element is not None
    assert _kinds(element) == ["decision", "criterion", "element"]
    assert element[1].id == f"{protocol_id}:EX01"
    question = _path_to(root, "question", question_id)
    assert question is not None
    assert {"run", "query", "protocol"} <= set(_kinds(question))


def test_trace_forward_from_criterion_lists_decisions_citing_it(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources, random_works=0)
    first, second = sorted(w.id for w in list_works(project))[:2]
    cited = _decide(project, agent, first, "A", "screening", "exclude", "EX01", protocol_id)
    other = _decide(project, agent, second, "A", "screening", "exclude", "EX02", protocol_id)

    root = trace(project, f"{protocol_id}:EX01", direction="forward")

    assert root.kind == "criterion"
    assert [c.id for c in root.children if c.kind == "decision"] == [cited]
    assert other not in {node.id for node in _all_nodes(root)}


def test_trace_chased_work_shows_chase_round(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    summary = search_chase(
        project,
        human,
        [ChaseDirection.BACKWARD],
        sources=mock_sources(openalex=[_citing(900)]),
    )
    [chased] = [
        w
        for w in list_works(project)
        if any(p.method is ProvenanceMethod.CITATION_CHASE for p in w.provenance)
    ]

    root = trace(project, chased.id)

    path = _path_to(root, "chase_round", summary.round_id)
    assert path is not None
    assert _kinds(path) == ["work", "record", "page", "run", "query", "chase_round"]
    assert path[-1].event_id != ""


def test_trace_unknown_id_refused(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    before = len(read_all(project.paths.events_dir, project.catalog))

    for ref in (
        "rf:nowhere-2020-missing-00000000",
        "qry_" + "0" * 26,
        "run_" + "0" * 26,
        "dec_" + "0" * 26,
        "Q@deadbeef",
        "P@deadbeef:IN01",
        "SEED99",
        "sha256:" + "0" * 64,
        "not an id",
    ):
        with pytest.raises(FactoryValidationError) as exc:
            trace(project, ref)
        assert exc.value.issues == [ValidationIssue("ref", "unknown id")]

    assert len(read_all(project.paths.events_dir, project.catalog)) == before


def test_trace_shows_reverted_merge(
    explore_project: Project, human: Actor, fake_sources: Callable[..., dict[str, SourceFactory]]
) -> None:
    _ingest(explore_project, fake_sources, [[PUBLISHED, PREPRINT]])
    [merge_id] = dedup_run(explore_project).created
    [merged] = _events_of(explore_project, "dedup.merged")
    primary = str(merged.payload["primary"])
    absorbed = {str(work) for work in merged.payload["absorbed"]}
    revert_merge(explore_project, human, merge_id, "different papers")

    root = trace(explore_project, primary)

    path = _path_to(root, "merge", merge_id)
    assert path is not None
    assert _kinds(path) == ["work", "merge"]
    assert "reverted" in path[-1].label
    assert "different papers" in path[-1].label
    assert {c.id for c in path[-1].children} == absorbed


def test_trace_disputed_work_links_decisions_criterion_and_resolution(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    work_id = _ordinary(project)[0]
    _decide(project, agent, work_id, "A", "screening", "include", None, protocol_id)
    _decide(project, agent, work_id, "B", "screening", "exclude", "EX01", protocol_id)
    resolve_disagreement(project, human, work_id, "exclude", "EX01", "topic one", Channel.CLI)

    back = trace(project, f"res:{work_id}")

    assert [child.kind for child in back.children] == ["decision", "decision"]
    assert _path_to(back, "work", work_id) is not None
    criterion = _path_to(back, "criterion", f"{protocol_id}:EX01")
    assert criterion is not None
    assert _kinds(criterion) == ["resolution", "decision", "criterion"]
    forward = trace(project, f"{protocol_id}:EX01", direction="forward")
    resolution = _path_to(forward, "resolution", f"res:{work_id}")
    assert resolution is not None
    assert _kinds(resolution) == ["criterion", "decision", "resolution"]


def test_trace_audited_work_links_sample_and_label(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    sampled = audit_sample(project, human, random_seed=7)
    labelled = sampled.work_ids[0]
    audit_record(project, human, sampled.audit_id, labelled, "include", None, Channel.CLI)

    sample = trace(project, sampled.audit_id, direction="forward")

    assert {child.id for child in sample.children} == {
        f"{sampled.audit_id}/{work}" for work in sampled.work_ids
    }
    item = _path_to(sample, "audit", f"{sampled.audit_id}/{labelled}")
    assert item is not None and item[-1].label == "sampled; human verdict include"
    assert item[-1].event_id.startswith("ev_")
    back = trace(project, f"{sampled.audit_id}/{labelled}")
    assert {child.kind for child in back.children} == {"audit", "work"}
    assert _path_to(back, "work", labelled) is not None


def test_trace_seed_links_its_lookup_run_and_its_work(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    seed = next(
        record
        for record in all_seeds(project)
        if record.work_id is not None and record.kind is SeedKind.POSITIVE
    )

    back = trace(project, seed.seed_id)
    forward = trace(project, seed.seed_id, direction="forward")

    assert back.label == "positive seed, resolved"
    assert seed.cite not in back.label and seed.seed_id not in back.label
    [query] = [node for node in _all_nodes(back) if node.kind == "query"]
    lookup = _path_to(back, "query", query.id)
    assert lookup is not None
    assert _kinds(lookup) == ["seed", "run", "query"]
    assert [child.id for child in forward.children] == [seed.work_id]


def test_trace_forward_from_run_lists_pages_and_their_records(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    work = get_work(project, sorted(w.id for w in list_works(project))[0])
    assert work is not None
    provenance = work.provenance[0]

    root = trace(project, provenance.run_id, direction="forward")

    record = _path_to(root, "record", f"{provenance.run_id}/{work.id}")
    assert record is not None
    assert _kinds(record) == ["run", "page", "record"]
    assert record[1].id == provenance.raw_blob
    assert record[1].event_id.startswith("ev_")
    back = trace(project, provenance.raw_blob)
    assert provenance.run_id in {child.id for child in back.children}


def test_trace_forward_from_question_reaches_criteria(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources, random_works=0)
    current = current_protocol(project)
    assert current is not None
    question_id = current.spec.question_id

    root = trace(project, question_id, direction="forward")

    criterion = _path_to(root, "criterion", f"{protocol_id}:EX01")
    assert criterion is not None
    assert _kinds(criterion) == ["question", "element", "criterion"]
    assert _path_to(root, "protocol", protocol_id) is not None


def test_trace_forward_from_absorbed_work_shows_the_reverted_merge(
    explore_project: Project, human: Actor, fake_sources: Callable[..., dict[str, SourceFactory]]
) -> None:
    _ingest(explore_project, fake_sources, [[PUBLISHED, PREPRINT]])
    [merge_id] = dedup_run(explore_project).created
    [merged] = _events_of(explore_project, "dedup.merged")
    primary = str(merged.payload["primary"])
    absorbed = str(merged.payload["absorbed"][0])  # type: ignore[index]
    revert_merge(explore_project, human, merge_id, "different papers")

    root = trace(explore_project, absorbed, direction="forward")

    path = _path_to(root, "merge", merge_id)
    assert path is not None
    assert _kinds(path) == ["work", "merge"]
    assert "reverted" in path[-1].label
    assert [child.id for child in path[-1].children] == [primary]
