"""The inbox service: capture, withdrawal and resolution (slice 4a acceptance 1-5, 9, 12)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.inbox.links import IdentifierKind
from factory.model.inbox import Basis, ResolveStatus
from factory.model.screening import Channel, PassLabel
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import ProvenanceMethod
from factory.services import inbox as inbox_service
from factory.services.calibration import is_pass_session
from factory.services.context import Project
from factory.services.dedup import canonical_works, dedup_run
from factory.services.inbox import (
    LinkInput,
    add_links,
    inbox_sessions,
    list_items,
    lookup_query,
    resolve_links,
    withdraw_link,
)
from factory.services.protocol import record_deviation
from factory.services.screening import join_pass
from factory.services.search import get_work
from factory.sources.base import SearchResult
from factory.sources.registry import SourceFactory
from tests.helpers import SourcesFor, _setup, ready_protocol
from tests.inbox_helpers import (
    KNOWLEDGE,
    Keyed,
    accept_supplied,
    capture,
    link_item,
    raising_sources,
    resolve,
)

ARXIV_URL = "https://arxiv.org/abs/2103.14030v2"
DOI_URL = "https://doi.org/10.2000/S1"
DOC = "doc_01HZX3K4M5N6P7Q8R9S0TVWXYZ"


def _events(project: Project, type_: str | None = None) -> list[Event]:
    events = read_all(project.paths.events_dir, project.catalog)
    return [e for e in events if type_ is None or e.type == type_]


def _keyed() -> Keyed:
    return Keyed(openalex={"doi:10.2000/s1": [link_item(1)]})


# --- Capture ---


def test_ac1_batch_with_partial_success(project: Project, human: Actor) -> None:
    items = [
        LinkInput(ARXIV_URL, note="from Ana"),
        LinkInput(DOI_URL),
        LinkInput("https://x.org/p"),
    ]
    result = add_links(project, human, items, Channel.CLI)

    assert len(result.written) == 2
    assert [(e.index, [i.reason for i in e.issues]) for e in result.rejected] == [
        (2, ["unsupported-link"])
    ]
    added = _events(project, "inbox.link_added")
    assert [e.payload["identifier_kind"] for e in added] == ["arxiv", "doi"]
    assert added[0].payload["identifier_version"] == "v2"
    assert added[0].payload["note"] == "from Ana"
    assert added[1].payload["identifier_value"] == "10.2000/s1"
    assert [e.refs for e in added] == [(result.written[0],), (result.written[1],)]


def test_ac1_agent_capture_needs_basis(project: Project, agent: Actor) -> None:
    result = add_links(project, agent, [LinkInput(ARXIV_URL)], Channel.MCP)
    assert result.written == []
    assert [i.field for i in result.rejected[0].issues] == ["basis"]
    noted_item = LinkInput(ARXIV_URL, note="x", basis=KNOWLEDGE)
    noted = add_links(project, agent, [noted_item], Channel.MCP)
    assert [i.field for i in noted.rejected[0].issues] == ["note"]
    assert _events(project, "inbox.link_added") == []


def test_agent_capture_carries_input_blob(project: Project, agent: Actor) -> None:
    basis = Basis(kind="document", document_id=DOC, anchor="b4")
    [item_id] = capture(project, agent, ARXIV_URL, basis=basis, channel=Channel.MCP)
    [event] = _events(project, "inbox.link_added")
    assert event.input_blob is not None
    assert project.blobs.get_json(event.input_blob) == {
        "link": ARXIV_URL,
        "basis": {"kind": "document", "document_id": DOC, "anchor": "b4"},
    }
    assert event.payload["basis"]["anchor"] == "b4"
    assert list_items(project).items[0].basis_kind == "document"
    assert item_id == event.payload["item_id"]


def test_human_capture_refuses_basis_and_long_note(project: Project, human: Actor) -> None:
    result = add_links(
        project,
        human,
        [LinkInput(ARXIV_URL, basis=KNOWLEDGE), LinkInput(ARXIV_URL, note="x" * 301)],
        Channel.CLI,
    )
    assert [[i.field for i in e.issues] for e in result.rejected] == [["basis"], ["note"]]


def test_system_actor_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        add_links(project, project.system_actor(), [LinkInput(ARXIV_URL)], Channel.CLI)
    assert caught.value.issues[0].field == "actor"


def test_ac2_capture_is_offline_and_needs_no_protocol(project: Project, human: Actor) -> None:
    # A fresh pilot project: no question, no protocol. `add_links` takes no sources at all.
    [item_id] = capture(project, human, DOI_URL)
    assert list_items(project).items[0].status == "open"
    assert item_id in {i.item_id for i in list_items(project, status="open").items}


# --- Resolution and the gate ---


def test_ac3_gate_without_section_needs_deviation(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    [item_id] = capture(project, human, DOI_URL)
    before = len(_events(project))

    [outcome] = resolve(project, human, _keyed())

    assert outcome.status is None
    assert "query" in {i.field for i in outcome.issues}
    assert len(_events(project)) == before
    deviation = record_deviation(project, human, description="Supplied link", reason="Colleague.")
    [done] = resolve(project, human, _keyed(), item_id, deviation_id=deviation)
    assert done.status is ResolveStatus.NEW
    [event] = _events(project, "inbox.link_resolved")
    assert event.payload["deviation_id"] == deviation


def test_ac3_section_accepts_human_and_refuses_agent(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    accept_supplied(project, agent, "human")
    [by_human] = capture(project, human, DOI_URL)
    [by_agent] = capture(project, agent, "10.2000/s2", channel=Channel.MCP)
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1)], "doi:10.2000/s2": [link_item(2)]})

    outcomes = {o.item_id: o for o in resolve(project, human, keyed)}

    assert outcomes[by_human].status is ResolveStatus.NEW
    assert outcomes[by_agent].status is None
    assert {i.field for i in outcomes[by_agent].issues} == {"query"}
    assert [e.payload["item_id"] for e in _events(project, "inbox.link_resolved")] == [by_human]


def test_ac3_exploratory_resolves_without_protocol(explore_project: Project, human: Actor) -> None:
    capture(explore_project, human, DOI_URL)
    [outcome] = resolve(explore_project, human, _keyed())
    assert outcome.status is ResolveStatus.NEW


def test_automatic_resolve_records_the_system_actor(explore_project: Project, human: Actor) -> None:
    project = explore_project
    capture(project, human, DOI_URL)
    [outcome] = resolve_links(
        project,
        project.system_actor(),
        sources=_keyed().sources(),
        automatic=True,
    )
    assert outcome.status is ResolveStatus.NEW
    [registered] = _events(project, "query.registered")
    [resolved] = _events(project, "inbox.link_resolved")
    assert registered.actor.kind == "system" and resolved.actor.kind == "system"


def test_system_actor_without_automatic_is_still_refused_by_resolve(
    explore_project: Project, human: Actor
) -> None:
    capture(explore_project, human, DOI_URL)
    with pytest.raises(FactoryValidationError) as caught:
        resolve_links(explore_project, explore_project.system_actor(), sources=_keyed().sources())
    assert caught.value.issues[0].field == "actor"
    assert _events(explore_project, "inbox.link_resolved") == []


def test_ac4_new_work_has_supplied_provenance_and_archived_pages(
    explore_project: Project, human: Actor
) -> None:
    project = explore_project
    [item_id] = capture(project, human, DOI_URL)
    [outcome] = resolve(project, human, _keyed())
    assert outcome.work_id is not None and outcome.run_id is not None

    work = get_work(project, outcome.work_id)
    assert work is not None
    assert [(p.method, p.run_id) for p in work.provenance] == [
        (ProvenanceMethod.SUPPLIED, outcome.run_id)
    ]
    with project.index.connect() as conn:
        pages = conn.execute(
            text("SELECT raw_blob FROM pages WHERE run_id = :run"), {"run": outcome.run_id}
        ).all()
    assert pages and all(project.blobs.exists(str(blob)) for (blob,) in pages)
    [registered] = _events(project, "query.registered")
    assert item_id in registered.refs
    [resolved] = _events(project, "inbox.link_resolved")
    assert resolved.refs == (item_id, resolved.payload["query_id"], outcome.run_id, work.id)
    assert list_items(project).items[0].last_outcome == "new"


def test_ac5_link_to_search_result_is_in_corpus(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    accept_supplied(project, agent, "human")
    capture(project, human, "10.1000/p2")
    keyed = Keyed(openalex={"doi:10.1000/p2": [link_item(2, doi="10.1000/p2", title="Paper 2")]})

    [outcome] = resolve(project, human, keyed)

    assert outcome.status is ResolveStatus.IN_CORPUS
    # The supplied record differs in its slug (first author), so it is its own stored work until
    # dedup folds it into the search's work by DOI.
    dedup_run(project)
    [work] = [w for w in canonical_works(project) if w.identifiers.doi == "10.1000/p2"]
    assert {p.method for p in work.provenance} == {
        ProvenanceMethod.DATABASE,
        ProvenanceMethod.SUPPLIED,
    }


def test_arxiv_link_resolves_through_arxiv(explore_project: Project, human: Actor) -> None:
    capture(explore_project, human, ARXIV_URL)
    keyed = Keyed(arxiv={"2103.14030": [("2103.14030v2", "Swin", 2021, "Ze Liu")]})
    [outcome] = resolve(explore_project, human, keyed)
    assert outcome.status is ResolveStatus.NEW
    [registered] = _events(explore_project, "query.registered")
    assert registered.payload["spec"]["source"] == "arxiv"
    assert registered.payload["spec"]["purpose"] == "supplied"


def test_two_records_are_ambiguous(explore_project: Project, human: Actor) -> None:
    capture(explore_project, human, DOI_URL)
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1), link_item(9, doi="10.2000/s9")]})
    [outcome] = resolve(explore_project, human, keyed)
    assert (outcome.status, outcome.work_id) == (ResolveStatus.AMBIGUOUS, None)
    assert list_items(explore_project).items[0].status == "resolved"


def test_no_record_is_not_found(explore_project: Project, human: Actor) -> None:
    capture(explore_project, human, DOI_URL)
    [outcome] = resolve(explore_project, human, Keyed())
    assert (outcome.status, outcome.work_id) == (ResolveStatus.NOT_FOUND, None)


def test_failed_lookup_stays_open_and_retries(explore_project: Project, human: Actor) -> None:
    [item_id] = capture(explore_project, human, DOI_URL)
    [failed] = resolve(explore_project, human, Keyed(fail=True))
    assert failed.status is ResolveStatus.FAILED
    assert list_items(explore_project).items[0].status == "open"

    [retried] = resolve(explore_project, human, _keyed())
    assert retried.status is ResolveStatus.NEW
    statuses = [e.payload["status"] for e in _events(explore_project, "inbox.link_resolved")]
    assert statuses == ["failed", "new"]
    assert list_items(explore_project).items[0].item_id == item_id


def test_resolved_item_is_not_resolved_again(explore_project: Project, human: Actor) -> None:
    capture(explore_project, human, DOI_URL)
    resolve(explore_project, human, _keyed())
    keyed = _keyed()
    assert resolve(explore_project, human, keyed) == []
    assert keyed.calls == 0


def test_named_item_must_be_open(explore_project: Project, human: Actor) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        resolve_links(explore_project, human, sources=raising_sources(), item_ids=["inb_unknown"])
    assert caught.value.issues[0].field == "item_ids.0"


# --- Withdrawal ---


def test_ac12_withdrawal(explore_project: Project, human: Actor) -> None:
    project = explore_project
    [item_id, other] = capture(project, human, DOI_URL, "10.2000/s2")
    withdraw_link(project, human, item_id, "wrong paper")
    assert len(_events(project, "inbox.link_withdrawn")) == 1
    assert [i.item_id for i in list_items(project, status="withdrawn").items] == [item_id]

    # A withdrawn item no longer resolves: naming it refuses, resolving all skips it.
    before = len(_events(project))
    with pytest.raises(FactoryValidationError):
        resolve_links(project, human, sources=raising_sources(), item_ids=[item_id])
    assert len(_events(project)) == before
    keyed = Keyed(openalex={"doi:10.2000/s2": [link_item(2)]})
    assert [o.item_id for o in resolve(project, human, keyed)] == [other]

    # A resolved or withdrawn item cannot be withdrawn.
    before = len(_events(project))
    for target in (item_id, other):
        with pytest.raises(FactoryValidationError):
            withdraw_link(project, human, target, "again")
    assert len(_events(project)) == before


def test_withdrawal_is_human_only(explore_project: Project, human: Actor, agent: Actor) -> None:
    [item_id] = capture(explore_project, human, DOI_URL)
    with pytest.raises(FactoryValidationError):
        withdraw_link(explore_project, agent, item_id, "no")
    with pytest.raises(FactoryValidationError):
        withdraw_link(explore_project, human, item_id, " ")


# --- Sessions (acceptance 9) ---


def test_ac9_capturing_session_cannot_join_screening(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    capture(project, agent, DOI_URL, channel=Channel.MCP)
    assert inbox_sessions(project) == {agent.session}

    with pytest.raises(FactoryValidationError) as caught:
        join_pass(project, agent, PassLabel.A)
    assert caught.value.issues[0].reason == "this session supplied a link and cannot screen"
    assert _events(project, "screening.pass_joined") == []


def test_ac9_pass_session_refused_by_inbox(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    join_pass(project, agent, PassLabel.A)
    assert is_pass_session(project, agent.session)
    with pytest.raises(FactoryValidationError) as caught:
        add_links(project, agent, [LinkInput(DOI_URL, basis=KNOWLEDGE)], Channel.MCP)
    assert caught.value.issues[0].field == "session"
    with pytest.raises(FactoryValidationError):
        resolve_links(project, agent, sources=raising_sources())
    assert _events(project, "inbox.link_added") == []


def test_list_items_pages_and_validates(explore_project: Project, human: Actor) -> None:
    ids = capture(explore_project, human, DOI_URL, "10.2000/s2", "10.2000/s3")
    first = list_items(explore_project, limit=2)
    assert [i.item_id for i in first.items] == ids[:2]
    assert first.next_cursor == "2"
    second = list_items(explore_project, cursor=first.next_cursor, limit=2)
    assert ([i.item_id for i in second.items], second.next_cursor) == (ids[2:], None)
    with pytest.raises(FactoryValidationError):
        list_items(explore_project, status="closed")
    with pytest.raises(FactoryValidationError):
        list_items(explore_project, cursor="x")


def test_item_closed_mid_resolve_reports_the_written_run(
    explore_project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The query and run are written before the item is found closed: the outcome says so."""
    project = explore_project
    [item_id] = capture(project, human, DOI_URL)
    real_run = inbox_service.run_query

    def run_then_withdraw(*args: Any, **kwargs: Any) -> Any:
        summary = real_run(*args, **kwargs)
        withdraw_link(project, human, item_id, "withdrawn meanwhile")
        return summary

    monkeypatch.setattr(inbox_service, "run_query", run_then_withdraw)
    [outcome] = resolve(project, human, _keyed())

    assert outcome.status is None
    assert outcome.run_id is not None
    [run_started] = _events(project, "search.run_started")
    assert run_started.payload["run_id"] == outcome.run_id
    assert _events(project, "inbox.link_resolved") == []


# --- PubMed and PMC links (plan pmid-seeds) ---


class _FakePubmed:
    """A pubmed adapter that records the spec it was asked for and finds nothing."""

    name = "pubmed"
    kinds = frozenset({QueryKind.KEYWORD, QueryKind.ID_LIST})
    window_filter = False

    def __init__(self, specs: list[QuerySpec]) -> None:
        self._specs = specs

    def run(self, spec: QuerySpec, **_kw: Any) -> SearchResult:
        self._specs.append(spec)
        return SearchResult(
            source="pubmed",
            query_sent=spec.text,
            reported_count=0,
            works=[],
            pages=1,
            status=RunStatus.COMPLETE,
        )


def _pubmed_sources(specs: list[QuerySpec]) -> dict[str, SourceFactory]:
    return {
        "pubmed": SourceFactory(
            _FakePubmed.kinds,
            lambda _s, _c: _FakePubmed(specs),
        )
    }


def _idconv(records: list[dict[str, str]], urls: list[str]) -> Any:
    def fetch(url: str) -> httpx.Response:
        urls.append(url)
        return httpx.Response(
            200, content=json.dumps({"status": "ok", "records": records}).encode()
        )

    return fetch


def _resolve_with(
    project: Project, human: Actor, sources: dict[str, SourceFactory], fetch: Any = None
) -> list[Any]:
    return resolve_links(project, human, sources=sources, page_fetch=fetch)


def test_lookup_query_for_a_pmid_is_pubmed_id_list() -> None:
    spec = lookup_query(IdentifierKind.PMID, "31452104")
    assert (spec.source, spec.kind, spec.text, spec.purpose) == (
        "pubmed",
        QueryKind.ID_LIST,
        "31452104",
        QueryPurpose.SUPPLIED,
    )


def test_pmid_link_resolves_through_pubmed(explore_project: Project, human: Actor) -> None:
    capture(explore_project, human, "https://pubmed.ncbi.nlm.nih.gov/31452104/")
    specs: list[QuerySpec] = []
    [outcome] = _resolve_with(explore_project, human, _pubmed_sources(specs))
    assert outcome.status is ResolveStatus.NOT_FOUND
    assert [(s.source, s.kind, s.text) for s in specs] == [
        ("pubmed", QueryKind.ID_LIST, "31452104")
    ]
    [registered] = _events(explore_project, "query.registered")
    assert registered.payload["spec"]["purpose"] == "supplied"


def test_pmcid_converts_to_pmid(explore_project: Project, human: Actor) -> None:
    capture(explore_project, human, "PMC6700123")
    specs: list[QuerySpec] = []
    urls: list[str] = []
    fetch = _idconv([{"pmcid": "PMC6700123", "pmid": "31452104", "doi": "10.1/x"}], urls)
    [outcome] = _resolve_with(explore_project, human, _pubmed_sources(specs), fetch)
    assert outcome.status is ResolveStatus.NOT_FOUND
    assert [(s.source, s.text) for s in specs] == [("pubmed", "31452104")]
    assert urls == [
        "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?ids=PMC6700123&format=json"
    ]


def test_pmcid_without_pmid_uses_the_doi(explore_project: Project, human: Actor) -> None:
    capture(explore_project, human, "PMC6700123")
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1)]})
    fetch = _idconv([{"pmcid": "PMC6700123", "doi": "10.2000/S1"}], [])
    [outcome] = resolve_links(explore_project, human, sources=keyed.sources(), page_fetch=fetch)
    assert outcome.status is ResolveStatus.NEW


def test_pmcid_converting_to_nothing_stays_open(explore_project: Project, human: Actor) -> None:
    [item_id] = capture(explore_project, human, "PMC6700123")
    fetch = _idconv([{"pmcid": "PMC6700123", "status": "error"}], [])
    [outcome] = _resolve_with(explore_project, human, raising_sources(), fetch)
    assert outcome.status is None
    assert [i.reason for i in outcome.issues] == ["pmcid-not-converted"]
    assert _events(explore_project, "inbox.link_resolved") == []
    assert list_items(explore_project).items[0].item_id == item_id


def test_pmcid_converter_reply_is_archived(
    explore_project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture(explore_project, human, "PMC6700123")
    body = json.dumps({"records": [{"pmcid": "PMC6700123", "pmid": "31452104"}]}).encode()

    def fetch(_url: str) -> httpx.Response:
        return httpx.Response(200, content=body)

    stored: list[bytes] = []
    real_put = explore_project.library.put

    def spy(data: bytes) -> str:
        stored.append(data)
        return real_put(data)

    monkeypatch.setattr(explore_project.library, "put", spy)
    _resolve_with(explore_project, human, _pubmed_sources([]), fetch)
    assert body in stored


def test_work_keys_include_the_normalised_pmid() -> None:
    from factory.model.work import Identifiers, Work
    from factory.services.inbox import _work_keys

    work = Work.model_construct(
        id="rf:x-12345678", identifiers=Identifiers(openalex="W1", pmid="0031452104")
    )
    keys = _work_keys(work)
    assert "pmid:31452104" in keys
    assert "openalex:W1" in keys
