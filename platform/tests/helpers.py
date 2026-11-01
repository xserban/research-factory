import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.protocol import (
    Criterion,
    MethodProfile,
    PlannedQuery,
    PressElement,
    PressFinding,
    ProtocolSpec,
    Reviewer,
    ReviewerRole,
    ScreeningPlan,
    ScreeningStage,
    SourcePlan,
)
from factory.model.question import NonGoal, QuestionSpec, Slot
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import Author, Dates, Identifiers, Provenance, Work, WorkType
from factory.services.context import Project
from factory.services.probe import run_probe
from factory.services.protocol import confirm_press, press_review, record_protocol
from factory.services.question import record_question, state_goal
from factory.services.seeds import add_seeds
from factory.sources.base import PageSink, RawPage, SearchResult, SourceError
from factory.sources.registry import SourceFactory

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
SESSION = "01JZ9Q3K5M7N8P0R2S4T6V8W0X"
S2 = "01JZ9Q3K5M7N8P0R2S4T6V8W0Y"
S3 = "01JZ9Q3K5M7N8P0R2S4T6V8W0Z"


class Demo(StrictModel):
    n: int


FAKE_PAGES: list[list[dict[str, Any]]] = [
    [
        {"title": "Linear attention", "authors": ["Ada Zhou"], "year": 2024},
        {"title": "Sparse attention", "authors": ["Ben Li"], "year": 2023},
    ],
    [{"title": "Efficient transformers", "authors": ["Cai Wu"], "year": 2022}],
]


class FakeSource:
    """A scripted `Source` for search tests.

    Each page is a list of record dicts. Every page is archived through the sink before its
    records are parsed, exactly as the real adapters do. Scripted behaviour:

    - `fail_after=n`: page `n` fails with a soft error, reported as a PARTIAL/FAILED result
      with a resume token (what the HTTP adapters do on a transport error).
    - `parse_fail_at=n`: page `n` is archived, then fails to parse. As the fixed adapters do
      (R9), that is a PARTIAL/FAILED result with a `SourceError` note and the page's resume token;
      the records of earlier pages are kept.
    - `raise_at=n`: page `n` raises `raise_error` (default `SourceError`) before it is archived.
      Adapters do not raise this way any more; it exercises the service's safety net.
    - `reported`: the count the source claims; a smaller delivery is explained in the note.
    - Duplicate records within the run are skipped, as the real adapters skip them.
    - `resume_from` is the page index to start from, as a resume token would be.
    """

    name: str = "fake"
    kinds: frozenset[QueryKind] = frozenset({QueryKind.KEYWORD})

    def __init__(
        self,
        pages: list[list[dict[str, Any]]],
        *,
        reported: int | None = None,
        fail_after: int | None = None,
        parse_fail_at: int | None = None,
        raise_at: int | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self._pages = pages
        self._reported = reported
        self._fail_after = fail_after
        self._parse_fail_at = parse_fail_at
        self._raise_at = raise_at
        self._raise_error = raise_error or SourceError("fake page unreadable")

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        works: list[Work] = []
        seen: set[str] = set()
        skipped = 0
        archived = 0
        for ordinal in range(int(resume_from or 0), len(self._pages)):
            if ordinal == self._fail_after:
                return self._result(
                    works,
                    archived,
                    skipped,
                    note="FakeNetworkError: connection reset",
                    resume_token=str(ordinal),
                )
            if ordinal == self._raise_at:
                raise self._raise_error
            ref = archive(
                RawPage(
                    ordinal=ordinal,
                    body=json.dumps(self._pages[ordinal]),
                    url=f"fake://pages/{ordinal}",
                    fetched_at=T0,
                )
            )
            archived += 1
            if ordinal == self._parse_fail_at:
                return self._result(
                    works,
                    archived,
                    skipped,
                    note="SourceError: fake page unreadable",
                    resume_token=str(ordinal),
                )
            for record in self._pages[ordinal]:
                work = _work(record, run_id=run_id, query_id=query_id, raw_blob=ref)
                if work.id in seen:
                    skipped += 1
                    continue
                seen.add(work.id)
                works.append(work)

        note = None
        if skipped:
            note = f"{skipped} duplicate record(s) skipped"
        if self._reported is not None and len(works) < self._reported:
            missing = f"{self._reported - len(works)} of {self._reported} reported not delivered"
            note = f"{note}; {missing}" if note else missing
        return self._result(works, archived, skipped, note=note)

    def _result(
        self,
        works: list[Work],
        archived: int,
        skipped: int,
        *,
        note: str | None,
        resume_token: str | None = None,
    ) -> SearchResult:
        status = RunStatus.COMPLETE
        if resume_token is not None:
            status = RunStatus.PARTIAL if works else RunStatus.FAILED
        return SearchResult(
            source=self.name,
            query_sent="fake",
            reported_count=self._reported,
            works=works,
            pages=archived,
            status=status,
            skipped=skipped,
            note=note,
            resume_token=resume_token,
        )


def _work(record: dict[str, Any], *, run_id: str, query_id: str, raw_blob: str) -> Work:
    year = record.get("year")
    return Work.build(
        title=str(record["title"]),
        authors=[Author(name=name) for name in record.get("authors", [])],
        identifiers=Identifiers(
            doi=record.get("doi"), arxiv=record.get("arxiv"), openalex=record.get("openalex")
        ),
        dates=Dates(published=date(year, 1, 1)) if year else Dates(),
        type=WorkType(record["type"]) if "type" in record else WorkType.OTHER,
        abstract=record.get("abstract"),
        provenance=[
            Provenance(
                source="fake",
                run_id=run_id,
                query_id=query_id,
                at=T0,
                raw_blob=raw_blob,
            )
        ],
    )


def openalex_item(
    *,
    title: str,
    author: str,
    published: str,
    openalex_id: str,
    doi: str | None = None,
    type_: str = "article",
) -> dict[str, Any]:
    """One OpenAlex `results` entry, shaped as the REST API returns it."""
    item: dict[str, Any] = {
        "id": f"https://openalex.org/{openalex_id}",
        "display_name": title,
        "publication_date": published,
        "type": type_,
        "authorships": [{"author": {"display_name": author}, "institutions": []}],
    }
    if doi is not None:
        item["doi"] = f"https://doi.org/{doi}"
    return item


def arxiv_atom(entries: Sequence[tuple[str, str, int, str]] = ()) -> str:
    """An arXiv Atom feed. Each entry is (versioned id, title, published year, first author)."""
    body = "".join(
        f"<entry><id>http://arxiv.org/abs/{arxiv_id}</id>"
        f"<published>{year}-03-01T12:00:00Z</published>"
        f"<updated>{year}-03-01T12:00:00Z</updated>"
        f"<title>{title}</title><summary>Abstract.</summary>"
        f"<author><name>{author}</name></author></entry>"
        for arxiv_id, title, year, author in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom" '
        'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
        f"<opensearch:totalResults>{len(entries)}</opensearch:totalResults>{body}</feed>"
    )


def install_skill(settings: Settings, name: str, text: str = "test skill") -> str:
    """Write a skill file under the settings' plugin dir and return its `name@hash` reference."""
    data = text.encode("utf-8")
    path = settings.plugin_dir / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"{name}@{hashlib.sha256(data).hexdigest()[:8]}"


# --- A ready pilot protocol, for tests that exercise searches under the gate ---

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def pilot_question_spec(
    primary: str = "Does linear attention match softmax on vision?",
) -> QuestionSpec:
    return QuestionSpec(
        scheme="PICO",
        primary_question=primary,
        slots=(
            Slot(name="population", value="vision transformers"),
            Slot(name="outcome", open="which accuracy metric", resolve_in="protocol"),
        ),
        non_goals=tuple(NonGoal(id=f"NG{i:02d}", text=f"not topic {i}") for i in (1, 2, 3)),
        rationale="Vision is the target domain.",
        objectives="Compare accuracy and cost.",
        scheme_rationale="PICO fits a comparison.",
    )


def record_pilot_question(project: Project, actor: Actor, primary: str | None = None) -> str:
    """Record the goal and the pilot question; returns the question id."""
    state_goal(project, actor, "Compare attention on vision")
    spec = pilot_question_spec() if primary is None else pilot_question_spec(primary)
    return record_question(project, actor, spec).question_id


def _seed_item(n: int) -> dict[str, Any]:
    return openalex_item(
        title=f"Paper {n}",
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id=f"W{n}",
        doi=f"10.1000/p{n}",
    )


def ready_protocol(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    queries: tuple[PlannedQuery, ...] | None = None,
    press: bool = True,
) -> str:
    """Make a ready pilot protocol on a fresh project, and return its id.

    Records the question, three positive seeds, a probe that measured the included source
    (openalex), the protocol declared ready, and, when `press` is true, a PRESS review by the
    agent confirmed by the human. Searches of the planned queries are then authorised.
    """
    question_id = record_pilot_question(project, agent)
    for n in (1, 2, 3):
        seed = SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", doi=f"10.1000/p{n}")
        add_seeds(project, agent, [seed], sources=mock_sources(openalex=[_seed_item(n)]))
    probe = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    report = run_probe(project, agent, [probe], sources=mock_sources(openalex=[_seed_item(1)]))

    criteria = (
        Criterion(
            id="IN01",
            parent="slot:population",
            statement="vision transformer studies",
            rule="include studies of vision transformers",
            applies_at=ScreeningStage.TITLE_ABSTRACT,
        ),
        *(
            Criterion(
                id=f"EX{n:02d}",
                parent=f"NG{n:02d}",
                statement=f"not topic {n}",
                rule=f"exclude topic {n}",
                applies_at=ScreeningStage.TITLE_ABSTRACT,
                priority=n,
            )
            for n in (1, 2, 3)
        ),
    )
    reviewer = Reviewer(role=ReviewerRole.REVIEWER_OF_RECORD, actor=human.id, kind="human")
    spec = ProtocolSpec(
        question_id=question_id,
        method_profile=MethodProfile.SCOPING_REVIEW,
        criteria=criteria,
        sources=(SourcePlan(name="openalex", included=True, probe_id=report.probe_id),),
        queries=queries
        or (PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="attention"),),
        screening=ScreeningPlan(passes=2, dual_sample=0.5, kappa_floor=0.7, reviewers=(reviewer,)),
    )
    protocol_id = record_protocol(project, agent, spec, ready=True).protocol_id
    if press:
        finding = PressFinding(
            element=PressElement.TEXT_WORDS, finding="Add a synonym.", severity="minor"
        )
        review_id = press_review(project, agent, protocol_id, (finding,))
        confirm_press(project, human, review_id, ("Accepted; the synonym is in the next version.",))
    return protocol_id
