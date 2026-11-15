"""Admission of an import's records as screened candidates (slice 3d ruling 22; plan Import-B).

`admit_import` plans the queries that retrieve a `corpus` import's records, records the plan
(`import.admission_planned`) before any query is registered, then registers and runs each query
as an `import`-purpose search naming the import (`register_query(..., import_id=...)`). Records
resolved to a work some source returned go to OpenAlex (`openalex:` then `doi:` filters) or arXiv
(`id_list`) or PubMed (PMID `id_list`); every other titled record goes to the offline `importlist`
source, which builds a work from the stored fields. A record whose work is already in the corpus
needs no query.

Invariants:
- Validation precedes every write. An admission is refused, writing nothing, when the import's
  role is `reference`, when it has not been resolved, while any record is unconfirmed or
  ambiguous or was described since its resolution (the refusal gives the count; the researcher
  lists them), when the protocol gate
  refuses an import query (`pilot`/`systematic`: readiness, question, PRESS), when `pilot` or
  `systematic` has no `library_sources` entry for the import's collection and format with role
  `corpus`, or when an earlier run retrieved records and none is left to admit.
- An admission plans only records no earlier run retrieved, so a record described after the first
  admission enters by a second one, and a re-run after a crash between two queries plans what is
  left. A retried failed run is the same case. No record is admitted twice.
- In `exploratory` the missing declaration is returned in `gaps`; the admission proceeds.
- Retrieved records enter the corpus as pending works with `library-import` provenance; nothing
  is included here. Dedup (`dedup_run`) links them to searched works, and pass B's sample is
  extended by the existing path (`screen_next`).
- A work any database search also found counts as database in PRISMA (precedence, decision 75).
- Outputs carry counts only: no ordinal and no held-out membership.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.imports.model import ImportFormat, ImportRole, ParseOutcome
from factory.model.base import StrictModel
from factory.model.budgets import REQUESTS_SEARCH
from factory.model.imports import ImportAdmissionPlanned, PlannedImportQuery
from factory.model.project import RigorMode
from factory.model.references import MAX_QUERY, LinkState
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import Work
from factory.model.work_ids import arxiv_id_from_doi
from factory.services.budgets import budget_issues
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.gates import indexed_rigor_mode
from factory.services.import_resolve import surname
from factory.services.imports import (
    effective_records,
    import_row,
    pending_descriptions,
    record_key,
    retrieved_keys,
)
from factory.services.protocol import current_protocol, search_authorization
from factory.services.protocol_rules import library_source_gaps
from factory.services.search import (
    RunSummary,
    corpus_size,
    get_work,
    list_works,
    query_issues,
    register_query,
    run_query,
)
from factory.services.snowball import _pack
from factory.sources.importlist import NAME as IMPORTLIST
from factory.sources.importlist import ImportlistEntry
from factory.sources.registry import SourceFactory, importlist_factory

_PLANNED = "import.admission_planned"
_PREFIX = {"openalex": "openalex:", "doi": "doi:", "arxiv": "", "pmid": "", IMPORTLIST: ""}
_SEPARATOR = {"openalex": "|", "doi": "|", "arxiv": ",", "pmid": ",", IMPORTLIST: ","}
_SOURCE_KIND: dict[str, tuple[str, QueryKind]] = {
    "openalex": ("openalex", QueryKind.FILTER),
    "doi": ("openalex", QueryKind.FILTER),
    "arxiv": ("arxiv", QueryKind.ID_LIST),
    "pmid": ("pubmed", QueryKind.ID_LIST),
    IMPORTLIST: (IMPORTLIST, QueryKind.ID_LIST),
}
_ORDER = ("openalex", "doi", "arxiv", "pmid", IMPORTLIST)


class AdmissionSummary(StrictModel):
    """What one admission did, as counts: queries run, works new to the corpus, records whose work
    was already there, records with nothing to admit them by (no title), runs that failed, and the
    promotion gaps (exploratory only)."""

    import_id: str
    runs: list[RunSummary]
    new_works: int
    already_in_corpus: int
    failed_runs: int
    gaps: list[ValidationIssue]
    unadmittable: int = 0


@dataclass
class _Plan:
    specs: list[QuerySpec]
    keys: list[tuple[str, ...]]
    already_in_corpus: int
    unadmittable: int


@dataclass(frozen=True)
class _Row:
    ordinal: int
    state: LinkState | None
    work_id: str | None
    no_source_record: bool
    titled: bool


def import_sources(
    project: Project, sources: Mapping[str, SourceFactory]
) -> dict[str, SourceFactory]:
    """`sources` with the offline `importlist` source bound to this project, unless one is given."""
    out = dict(sources)
    out.setdefault(IMPORTLIST, importlist_factory(lambda keys: importlist_entries(project, keys)))
    return out


def importlist_entries(project: Project, keys: Sequence[str]) -> dict[str, ImportlistEntry]:
    """The stored, titled records among `keys` (`imp_<ULID>:<ordinal>`), each read through its
    description. A key of an unknown import names no record."""
    wanted: dict[str, dict[int, str]] = {}
    for key in keys:
        import_id, _, ordinal = key.partition(":")
        if ordinal.isdigit():
            wanted.setdefault(import_id, {})[int(ordinal)] = key
    out: dict[str, ImportlistEntry] = {}
    for import_id, ordinals in wanted.items():
        try:
            records = effective_records(project, import_id)
        except FactoryValidationError:
            continue
        for record in records:
            key_of = ordinals.get(record.ordinal)
            f = record.fields
            if key_of is None or record.outcome is ParseOutcome.MALFORMED or f is None:
                continue
            if f.title:
                out[key_of] = ImportlistEntry(
                    key=key_of,
                    title=f.title,
                    first_author=(surname(f.authors[0]) or None) if f.authors else None,
                    year=f.year,
                    doi=f.doi,
                    arxiv=f.arxiv,
                    url=f.url,
                    venue=f.venue,
                    record_sha256=record.record_sha256,
                    abstract=f.abstract,
                )
    return out


def _rows(project: Project, import_id: str) -> list[_Row]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.ordinal, link_state, work_id, no_source_record, "
                "(COALESCE(d.title, r.title, '') != '') FROM import_records r "
                "LEFT JOIN import_descriptions d "
                "ON d.import_id = r.import_id AND d.ordinal = r.ordinal "
                "WHERE r.import_id = :i AND outcome != :malformed ORDER BY r.ordinal"
            ),
            {"i": import_id, "malformed": ParseOutcome.MALFORMED.value},
        ).all()
    return [
        _Row(
            ordinal=int(o),
            state=None if s is None else LinkState(str(s)),
            work_id=None if w is None else str(w),
            no_source_record=bool(n),
            titled=bool(t),
        )
        for o, s, w, n, t in rows
    ]


def _route(work: Work) -> tuple[str, str] | None:
    """(query family, id) naming a stored work, or None when no source query can name it.

    Precedence: OpenAlex id, PMID (a PubMed `id_list`), arXiv id, DOI."""
    ident = work.identifiers
    arxiv = ident.arxiv or (arxiv_id_from_doi(ident.doi) if ident.doi else None)
    route: tuple[str, str] | None = None
    if ident.openalex:
        route = "openalex", ident.openalex
    elif ident.pmid:
        route = "pmid", ident.pmid
    elif arxiv:
        route = "arxiv", arxiv
    elif ident.doi and not any(sep in ident.doi for sep in "|,"):
        route = "doi", ident.doi
    if route is None or len(_PREFIX[route[0]]) + len(route[1]) > MAX_QUERY:
        return None
    return route


def _plan(project: Project, import_id: str) -> _Plan:
    project.index.sync()
    corpus = {w.id for w in list_works(project)}
    corpus |= {a for m in active_merges(project) if m.primary in corpus for a in m.absorbed}
    ids: dict[str, dict[str, list[str]]] = {family: {} for family in _ORDER}
    already = unadmittable = 0
    retrieved = retrieved_keys(project, import_id)
    for row in _rows(project, import_id):
        key = record_key(import_id, row.ordinal)
        if key in retrieved or row.state in (None, LinkState.UNCONFIRMED, LinkState.AMBIGUOUS):
            continue
        route: tuple[str, str] | None = None
        if row.state is LinkState.RESOLVED and row.work_id is not None:
            if row.work_id in corpus:
                already += 1
                continue
            work = None if row.no_source_record else get_work(project, row.work_id)
            route = None if work is None else _route(work)
        if route is None:
            if not row.titled:
                unadmittable += 1
                continue
            route = IMPORTLIST, key
        ids[route[0]].setdefault(route[1], []).append(key)
    specs: list[QuerySpec] = []
    keys: list[tuple[str, ...]] = []
    for family in _ORDER:
        source, kind = _SOURCE_KIND[family]
        prefix, separator = _PREFIX[family], _SEPARATOR[family]
        ordered = sorted(ids[family], key=_ordinal_key if family == IMPORTLIST else str)
        for t in _pack(ordered, prefix, separator):
            named = t[len(prefix) :].split(separator)
            specs.append(QuerySpec(source=source, kind=kind, text=t, purpose=QueryPurpose.IMPORT))
            keys.append(tuple(dict.fromkeys(k for n in named for k in ids[family][n])))
    return _Plan(specs, keys, already, unadmittable)


def _ordinal_key(key: str) -> int:
    return int(key.rpartition(":")[2])


def plan_admission(project: Project, import_id: str) -> list[QuerySpec]:
    """The import-purpose queries that would retrieve the import's records. Pure over the
    projection; writes nothing."""
    import_row(project, import_id)
    return _plan(project, import_id).specs


def planned_ordinals(project: Project, import_id: str) -> set[int]:
    """The records an admission would plan now: those no earlier run retrieved and that a query can
    name. Pure over the projection."""
    return {_ordinal_key(key) for keys in _plan(project, import_id).keys for key in keys}


def _blocking(project: Project, import_id: str) -> list[ValidationIssue]:
    """Why the import's records cannot be admitted yet: unresolved, unconfirmed or ambiguous."""
    rows = _rows(project, import_id)
    unresolved = sum(1 for r in rows if r.state is None)
    open_ = sum(1 for r in rows if r.state in (LinkState.UNCONFIRMED, LinkState.AMBIGUOUS))
    issues: list[ValidationIssue] = []
    if unresolved:
        issues.append(
            ValidationIssue(
                "import_id", f"{_records(unresolved)} not resolved yet; resolve the import first"
            )
        )
    if open_:
        issues.append(
            ValidationIssue(
                "import_id",
                f"{_records(open_)} unconfirmed or ambiguous; confirm or reject "
                f"{'it' if open_ == 1 else 'them'} first (`factory import show --researcher`)",
            )
        )
    described = len(pending_descriptions(project, import_id))
    if described:
        issues.append(
            ValidationIssue(
                "import_id",
                f"{_records(described)} described since resolution; run "
                f"`factory import resolve {import_id} --described`",
            )
        )
    return issues


def _records(n: int) -> str:
    return f"{n} record is" if n == 1 else f"{n} records are"


def _admission_runs(project: Project, import_id: str) -> list[str]:
    """Statuses of every run of the import's queries (queries naming the import in their refs)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.status FROM runs r "
                "JOIN event_refs f ON f.type = 'query.registered' AND f.position = 0 "
                "AND f.ref = r.query_id "
                "WHERE EXISTS (SELECT 1 FROM event_refs n WHERE n.event_id = f.event_id "
                "AND n.position > 0 AND n.ref = :i)"
            ),
            {"i": import_id},
        ).all()
    return [str(s) for (s,) in rows]


def admit_import(
    project: Project,
    import_id: str,
    *,
    sources: Mapping[str, SourceFactory],
    actor: Actor | None = None,
) -> AdmissionSummary:
    """Plan, record and run the admission of a `corpus` import; see the module docstring.

    `actor` defaults to the researcher. Raises `FactoryValidationError` with every issue at once,
    writing nothing.
    """
    who = actor or project.human_actor()
    adapters = import_sources(project, sources)
    with project.index.exclusive():
        project.index.sync()
        row = import_row(project, import_id)
        issues: list[ValidationIssue] = []
        if row.role is not ImportRole.CORPUS:
            issues.append(
                ValidationIssue("role", "a reference import is not admitted: its role is reference")
            )
        issues += _blocking(project, import_id)
        done = [s for s in _admission_runs(project, import_id) if s != RunStatus.FAILED.value]
        gaps = _library_gaps(project, row.collection, row.format)
        if gaps and indexed_rigor_mode(project) is not RigorMode.EXPLORATORY:
            issues += gaps
            gaps = []
        plan = _plan(project, import_id)
        if done and not plan.specs and not issues:
            issues.append(ValidationIssue("import_id", _nothing_left(plan.unadmittable)))
        for spec in plan.specs:
            issues += query_issues(project, spec, adapters)
            # The recorded plan will waive the planned-queries rule, so only the other gates
            # (protocol readiness, question, PRESS) are asked of a plan not yet written.
            issues += [
                i
                for i in search_authorization(project, spec, deviation_id=None, import_id=import_id)
                if i.field not in ("import_id", "query")
            ]
        if plan.specs:
            issues += budget_issues(project, who, REQUESTS_SEARCH)
        if issues:
            raise FactoryValidationError(list(dict.fromkeys(issues)))
        if not plan.specs:
            return AdmissionSummary(
                import_id=import_id,
                runs=[],
                new_works=0,
                already_in_corpus=plan.already_in_corpus,
                failed_runs=0,
                gaps=gaps,
                unadmittable=plan.unadmittable,
            )
        planned = ImportAdmissionPlanned(
            import_id=import_id,
            queries=tuple(
                PlannedImportQuery(source=s.source, kind=s.kind, text=s.text, record_keys=k)
                for s, k in zip(plan.specs, plan.keys, strict=True)
            ),
        )
        input_blob = (
            project.blobs.put_json({"import_id": import_id}) if who.kind == "agent" else None
        )
        project.record(
            [project.events.make(_PLANNED, planned, who, refs=(import_id,), input_blob=input_blob)]
        )

    before, _ = corpus_size(project)
    query_ids = [
        register_query(project, who, spec, sources=adapters, import_id=import_id)
        for spec in plan.specs
    ]
    runs = [run_query(project, q, sources=adapters, actor=who) for q in query_ids]
    after, _ = corpus_size(project)
    return AdmissionSummary(
        import_id=import_id,
        runs=runs,
        new_works=after - before,
        already_in_corpus=plan.already_in_corpus,
        failed_runs=sum(1 for r in runs if r.status is RunStatus.FAILED),
        gaps=gaps,
        unadmittable=plan.unadmittable,
    )


def _nothing_left(unadmittable: int) -> str:
    if not unadmittable:
        return "already admitted: no record is left to admit"
    return (
        f"already admitted: only {_records(unadmittable)} left, with no title; "
        "`factory import describe` names them"
    )


def _library_gaps(
    project: Project, collection: str | None, fmt: ImportFormat
) -> list[ValidationIssue]:
    current = current_protocol(project)
    if current is None:
        return [ValidationIssue("library_sources", "library-undeclared: no protocol is recorded")]
    return library_source_gaps(current.spec, collection, fmt)
