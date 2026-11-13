"""The R-01 chain walked from any identifier, backwards or forwards (plan 5b, task 3).

`trace` is read-only: it reads the index projection and, for the few kinds whose table holds no
event id (pages, records, merges, audit samples), the event log. Each node carries the event that
created it. The graph is directed upstream to downstream: a node's upstream neighbours are the
ones it was derived from, its downstream neighbours the ones derived from it. A back trace follows
upstream edges, a forward trace downstream edges.

Invariants:
- A node is shown once, at the first branch that reaches it; the walk keeps a visited set and
  never expands a repeat.
- A merge is shown whatever its status; a reverted merge's label says it was reverted and why.
- A work reached through a citation chase is linked to its `chase_round`: the round whose query
  text is the text the work's run ran (the round recorded before the query was registered).
- A reference extraction (`rex_…`; an entry key `rex_…:<n>` names its extraction) leads from the
  citing work's conversion and screening decisions to the bibliography anchors of its resolved
  entries, and each anchor to the work its link names, so a snowball candidate traces back to the
  citing anchor. A snowball round (`snw_…`) is derived from its source works and extractions; its
  queries are those whose `query.registered` refs name it, or, forward, its chase round.
- A reference that names no row is shown as a node with an empty `event_id`, so a broken link is
  visible rather than hidden.
- A context pack (`briefing`, named by its blob ref) leads to each `briefing.served` event of it
  (`served`) and on to the session that received it (`session`, named by its id), so a session's
  agent events, which carry that id, lead back to what the agent was told. Blob refs and session
  ids are told apart by the served table, in `_Walk.served_key`, never in `_parse`: `dangling_refs`
  must not judge them.
- An identifier that names no row raises `FactoryValidationError([ValidationIssue("ref",
  "unknown id")])`; nothing is written.
"""

import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Event
from factory.events.reader import read_all
from factory.model.base import StrictModel
from factory.model.chase import CHASE_ROUND_ID_RE
from factory.model.dedup import MERGE_ID_RE
from factory.model.extraction import CLAIM_ID_RE, EXTRACTION_ID_RE
from factory.model.fulltext import ATTEMPT_ID_RE, DOCUMENT_ID_RE
from factory.model.identity import BLOB_REF_RE, CONVERSION_ID_RE, ULID_RE
from factory.model.imports import IMPORT_ID_RE
from factory.model.inbox import INBOX_ID_RE
from factory.model.lineage import IDEA_ID_RE, REL_ID_RE
from factory.model.notices import NTC_ID_RE
from factory.model.protocol import PROTOCOL_ID_RE, ProtocolSpec
from factory.model.question import QUESTION_ID_RE, QuestionSpec
from factory.model.references import ENTRY_KEY_RE, REX_ID_RE, SNW_ID_RE
from factory.model.screening import AUDIT_ID_RE, DECISION_ID_RE, QUALIFIED_CRITERION_RE
from factory.model.seed import SEED_ID_RE
from factory.model.work import QUERY_ID_RE, RUN_ID_RE
from factory.model.work_ids import WORK_ID_RE
from factory.services import (
    draft_trace,
    lab_trace,
    label_trace,
    layer_trace,
    manuscript_trace,
    region_trace,
    slice6_trace,
)
from factory.services.context import Project
from factory.services.contributions import contribution_item
from factory.services.ideas import idea_view
from factory.services.lineage import cites_status
from factory.services.relations import relation_view
from factory.services.work_ref import resolve_work_id

KINDS: tuple[str, ...] = (
    "question",
    "element",
    "criterion",
    "protocol",
    "inbox_item",
    "query",
    "run",
    "page",
    "record",
    "merge",
    "work",
    "attempt",
    "document",
    "conversion",
    "anchor",
    "decision",
    "extraction",
    "appraisal",
    "claim",
    "relation",
    "idea",
    "cites",
    "quote",
    "cell",
    "group",
    "stat",
    "sentence",
    "verdict",
    "draft",
    "manuscript_unit",
    "manuscript_verdict",
    "resolution",
    "audit",
    "seed",
    "chase_round",
    "reference_extraction",
    "snowball_round",
    "import",
    "import_record",
    "notice",
    "version",
    "preference",
    "interpretation",
    "concept",
    "concept_link",
    "region",
    "region_version",
    "region_member",
    "label",
    "term",
    "consolidation",
    "proposal",
    *slice6_trace.KINDS,
    "briefing",
    "served",
    "session",
    lab_trace.ADOPTION_KIND,
)
"""Node kinds in chain order. The layer's kinds come last (G2's pinned order after `claim` is
unchanged; `appraisal` sits before `claim` so that stays true). Sibling nodes are listed in
this order (reversed for back traces, so the work branch of a decision comes before its
cited criterion)."""

_RANK = {kind: rank for rank, kind in enumerate(KINDS)}
_NO_EVENT = ""
_MISSING = "no such row"

_ELEMENT_RE = r"^(Q@[0-9a-f]{8})/(slot:.+|NG\d{2}|SQ\d{1,2})$"
_RECORD_RE = rf"^(run_{ULID_RE})/(rf:.+)$"
_AUDIT_ITEM_RE = rf"^(aud_{ULID_RE})/(rf:.+)$"
_ANCHOR_RE = rf"^(cnv_{ULID_RE})/([^/\s]+)$"
_RESOLUTION_RE = r"^res:(?:full-text:)?(rf:.+)$"
_IMPORT_RECORD_RE = rf"^(imp_{ULID_RE})\:([1-9][0-9]*)$"
_CELL_RE = r"^rk_[0-9a-f]{12}(?:/(?!\*$)\S+)?$"
_VERSION_RE = r"^ver:([^/\s]+)/(obs|link)/(.+)$"
_PREFERENCE_RE = r"^pref:(rf:\S+)$"
_CITES_RE = rf"^cit:(rex_{ULID_RE}):([1-9][0-9]*)$"
_QUOTE_RE = rf"^(ext_{ULID_RE})/quote$"
_APPRAISAL_RE = rf"^app_({ULID_RE})/([a-z][a-z0-9-]{{0,39}})$"
_PATTERNS: tuple[tuple[str, str], ...] = (
    *layer_trace.LAYER_PATTERNS,
    *region_trace.REGION_PATTERNS,
    *label_trace.ORGANISATION_PATTERNS,
    *slice6_trace.PATTERNS,
    *draft_trace.DRAFT_PATTERNS,
    *manuscript_trace.MANUSCRIPT_PATTERNS,
    (REL_ID_RE, "relation"),
    (IDEA_ID_RE, "idea"),
    (_CITES_RE, "cites"),
    (_QUOTE_RE, "quote"),
    (NTC_ID_RE, "notice"),
    (_VERSION_RE, "version"),
    (_PREFERENCE_RE, "preference"),
    (QUESTION_ID_RE, "question"),
    (PROTOCOL_ID_RE, "protocol"),
    (QUALIFIED_CRITERION_RE, "criterion"),
    (_ELEMENT_RE, "element"),
    (QUERY_ID_RE, "query"),
    (RUN_ID_RE, "run"),
    (MERGE_ID_RE, "merge"),
    (DECISION_ID_RE, "decision"),
    (EXTRACTION_ID_RE, "extraction"),
    (CLAIM_ID_RE, "claim"),
    (_APPRAISAL_RE, "appraisal"),
    (_CELL_RE, "cell"),
    (AUDIT_ID_RE, "audit"),
    (_AUDIT_ITEM_RE, "audit"),
    (CHASE_ROUND_ID_RE, "chase_round"),
    (REX_ID_RE, "reference_extraction"),
    (SNW_ID_RE, "snowball_round"),
    (IMPORT_ID_RE, "import"),
    (_IMPORT_RECORD_RE, "import_record"),
    (INBOX_ID_RE, "inbox_item"),
    (SEED_ID_RE, "seed"),
    (BLOB_REF_RE, "page"),
    (WORK_ID_RE, "work"),
    (ATTEMPT_ID_RE, "attempt"),
    lab_trace.ADOPTION_PATTERN,
    (DOCUMENT_ID_RE, "document"),
    (CONVERSION_ID_RE, "conversion"),
    (_ANCHOR_RE, "anchor"),
    (_RECORD_RE, "record"),
    (_RESOLUTION_RE, "resolution"),
)

_TA_STAGE = "title-abstract"


def _res_key(stage: str, work_id: str) -> str:
    """The trace key of a resolution: `res:<work_id>` at title/abstract (slice-1 keys are
    unchanged), `res:<stage>:<work_id>` at any other stage."""
    return f"res:{work_id}" if stage == _TA_STAGE else f"res:{stage}:{work_id}"


def _split_res(ident: str) -> tuple[str, str]:
    """The stage and work of a resolution key."""
    body = ident[len("res:") :]
    prefix = "full-text:"
    if body.startswith(prefix):
        return "full-text", body[len(prefix) :]
    return _TA_STAGE, body


Key = tuple[str, str]
"""A node: its kind and its identifier. Identifiers are unique within a kind."""


class TraceNode(StrictModel):
    """One node of a trace: what it is, the event that created it, and the nodes it leads to."""

    id: str
    kind: str
    label: str
    event_id: str
    children: list["TraceNode"]


@dataclass(frozen=True)
class _Described:
    label: str
    event_id: str


@dataclass(frozen=True)
class _QuestionRow:
    spec: QuestionSpec
    event_id: str


@dataclass(frozen=True)
class _ProtocolRow:
    status: str
    spec: ProtocolSpec
    event_id: str


Layer = Literal["evidence", "all"]


def trace(
    project: Project,
    ref: str,
    *,
    direction: Literal["back", "forward"] = "back",
    layer: Layer = "evidence",
) -> TraceNode:
    """The chain from `ref`, as a tree rooted at that node.

    `back` follows the nodes `ref` was derived from, `forward` the nodes derived from it. The kind
    of `ref` is given by its prefix. Raises `FactoryValidationError` for an identifier that names
    no row.

    Each node is shown once, under the first branch that reaches it (a visited set). So a back
    trace from a decision claims the protocol and the question under the work branch (through the
    query), and the criterion branch may then end at the element. Criteria lead upward to their
    protocol and element, never to queries: queries are downstream of protocols.

    A layer id (`int_...`, `cpt_...`, `cul_...`) is traced like any other and its nodes are
    labelled `interpretation · <review state>`. With `layer = all` the layer items an anchor, work
    or idea carries are added below it (forward); by default a trace of an evidence node is
    unchanged by the layer (plan G3-C).
    """
    return _trace(project, ref, direction, layer, None)


def _trace(
    project: Project,
    ref: str,
    direction: Literal["back", "forward"],
    layer: Layer,
    skip: Callable[[Key], bool] | None,
) -> TraceNode:
    """`trace`, with `skip`: keys the walk never reaches. A skipped node is not entered in the
    visited set either, so it can never claim a node a visible branch shows (an agent view)."""
    if layer not in ("evidence", "all"):
        raise FactoryValidationError([ValidationIssue("layer", "must be evidence or all")])
    if direction not in ("back", "forward"):
        raise ValueError(f"direction must be 'back' or 'forward', not {direction!r}")
    project.index.sync()
    if re.fullmatch(WORK_ID_RE, ref):
        ref = resolve_work_id(project, ref, field="ref")
    with project.index.connect() as conn:
        walk = _Walk(project, conn, layer, agent=skip is not None)
        key = walk.served_key(ref) or _parse(ref)
        described = None if key is None else walk.describe(key)
        if key is None or described is None:
            raise FactoryValidationError([ValidationIssue("ref", "unknown id")])
        return _build(walk, key, described, direction, {key}, skip)


_HIDDEN_PURPOSES = ("seed", "probe")
_GENERIC_METHODS = ("seed-admission", "hand-search", "supplied")


def agent_trace(
    project: Project,
    ref: str,
    *,
    direction: Literal["back", "forward"] = "back",
    layer: Layer = "evidence",
) -> TraceNode:
    """`trace` as an agent may read it: nothing that marks a work as a seed (R-20).

    Seed nodes are removed (their children lifted). Queries and runs of seed or probe purpose are
    removed with everything below them, and so are the records and pages reachable only through
    them, so a seed's work reads as any corpus work does. A record found by seed admission or hand
    search is labelled `supplementary`, not by its route. Provenance of probe queries is not in
    any view (the corpus does not count it either). A session verifying a draft is refused a
    chain that reaches it (ruling 12, R-131), from the ref itself or through a support it cites.
    """
    project.index.sync()
    with project.index.connect() as conn:
        hidden_queries = {
            str(q)
            for (q,) in conn.execute(
                text("SELECT query_id FROM queries WHERE purpose IN ('seed', 'probe', 'import')")
            ).all()
        }
        hidden_runs = {
            str(r)
            for (r, q) in conn.execute(text("SELECT run_id, query_id FROM runs")).all()
            if str(q) in hidden_queries
        }
        # Every label applied from an import's tags, whatever its record's part: the tag is
        # withheld, never the work (decision 43; the part is not read).
        hidden_runs |= {
            str(a)
            for (a,) in conn.execute(
                text("SELECT application_id FROM labels WHERE origin = 'import-tag'")
            ).all()
        }
    skip = _agent_skip(project, hidden_queries, hidden_runs)
    tree = without_seeds(_trace(project, ref, direction, layer, skip))
    _refuse_verifier(project, tree)
    tree = _without_withheld_regions(project, tree)
    if _hidden(tree, hidden_queries, hidden_runs):
        raise FactoryValidationError([ValidationIssue("ref", "unknown id")])
    return _pruned(tree, hidden_queries, hidden_runs)


def _refuse_verifier(project: Project, tree: TraceNode) -> None:
    """Refuse the session when the chain reaches a draft it is verifying."""
    from factory.services.drafts import refuse_verifier  # drafts reads what the trace walks

    pending, drafts = [tree], set()
    with project.index.connect() as conn:
        while pending:
            node = pending.pop()
            pending.extend(node.children)
            drafts.add(draft_trace.draft_of(conn, node.kind, node.id))
    for draft_id in sorted(d for d in drafts if d is not None):
        refuse_verifier(project, draft_id, project.session)


def _agent_skip(project: Project, queries: set[str], runs: set[str]) -> Callable[[Key], bool]:
    """The keys an agent's walk never reaches, for every hidden kind: hidden queries, runs and
    their records, import tags, imports and their records, inbox items, and regions withheld
    from agents with their versions and members."""
    from factory.services.regions import region_ids, region_withheld

    withheld = {rid for rid in region_ids(project) if region_withheld(project, rid)}
    versions: set[str] = set()
    if withheld:
        with project.index.connect() as conn:
            versions = {
                str(v)
                for (v,) in conn.execute(
                    text(
                        "SELECT DISTINCT version FROM region_snapshots WHERE region_id IN :r"
                    ).bindparams(bindparam("r", expanding=True)),
                    {"r": sorted(withheld)},
                )
            }

    def skip(key: Key) -> bool:
        kind, ident = key
        if kind == "query":
            return ident in queries
        if kind in ("run", "label"):
            return ident in runs
        if kind == "record":
            return ident.split("/", 1)[0] in runs
        if kind in ("inbox_item", "import", "import_record"):
            return True
        if kind == "region":
            return ident in withheld
        if kind == "region_version":
            return ident in versions
        return kind == "region_member" and region_trace.split_member(ident)[0] in versions

    return skip


def _without_withheld_regions(project: Project, tree: TraceNode) -> TraceNode:
    """Regions withheld from agents (they reach an import's `all` part or a barred query purpose)
    removed whole from an agent trace: the region, its versions and the memberships it holds. A
    trace rooted at one reads as an unknown id."""
    from factory.services.regions import region_ids, region_withheld

    withheld = {rid for rid in region_ids(project) if region_withheld(project, rid)}
    if not withheld:
        return tree
    with project.index.connect() as conn:
        versions = {
            str(v)
            for (v,) in conn.execute(
                text(
                    "SELECT DISTINCT version FROM region_snapshots WHERE region_id IN :r"
                ).bindparams(bindparam("r", expanding=True)),
                {"r": sorted(withheld)},
            )
        }

    def hidden(node: TraceNode) -> bool:
        if node.kind == "region":
            return node.id in withheld
        if node.kind == "region_version":
            return node.id in versions
        return node.kind == "region_member" and region_trace.split_member(node.id)[0] in versions

    def prune(node: TraceNode) -> TraceNode:
        return node.model_copy(
            update={"children": [prune(c) for c in node.children if not hidden(c)]}
        )

    if hidden(tree):
        raise FactoryValidationError([ValidationIssue("ref", "unknown id")])
    return prune(tree)


def _pruned(node: TraceNode, queries: set[str], runs: set[str]) -> TraceNode:
    kept: list[TraceNode] = []
    for child in node.children:
        if _hidden(child, queries, runs):
            continue
        below = _pruned(child, queries, runs)
        if child.kind == "page" and child.children and not below.children:
            continue  # reachable only through a hidden run
        kept.append(below)
    label = node.label
    if node.kind == "record" and any(label.startswith(f"{m} ") for m in _GENERIC_METHODS):
        label = "supplementary " + label.split(" ", 1)[1]
    return node.model_copy(update={"children": kept, "label": label})


def _hidden(node: TraceNode, queries: set[str], runs: set[str]) -> bool:
    if node.kind == "query":
        return node.id in queries
    if node.kind == "run":
        return node.id in runs
    if node.kind == "record":
        return node.id.split("/", 1)[0] in runs
    if node.kind == "label":
        return node.id in runs  # `runs` also holds the import-tag application ids
    # How a work was supplied is a route; the agent view never shows one (slice 4a ruling 8).
    # An import and its records carry ordinals, which name the held-out part (decision 43).
    return node.kind in ("inbox_item", "import", "import_record")


def without_seeds(node: TraceNode) -> TraceNode:
    """`node` with every seed node below it removed, for a surface that must not reveal which
    works the seeds are (R-20). A seed's own children move up to its parent, so what the seed led
    to stays in the tree and nothing but the seed link is lost. The root is kept as given."""
    return node.model_copy(update={"children": _lifted(node.children)})


def _lifted(nodes: list[TraceNode]) -> list[TraceNode]:
    kept: list[TraceNode] = []
    for child in nodes:
        if child.kind == "seed":
            kept.extend(_lifted(child.children))
        else:
            kept.append(child.model_copy(update={"children": _lifted(child.children)}))
    return kept


def dangling_refs(project: Project, refs: Iterable[str]) -> list[str]:
    """The identifiers among `refs` of a kind the walk describes that no row defines, sorted.

    Read-only, one walk for all of them. An identifier of a kind the walk does not describe is
    not judged: it is neither reported nor an error here.
    """
    project.index.sync()
    with project.index.connect() as conn:
        walk = _Walk(project, conn)
        dangling: set[str] = set()
        for ref in refs:
            key = _parse(ref)
            if key is not None and walk.describe(key) is None:
                dangling.add(ref)
    return sorted(dangling)


def _lookup_key(event: Event) -> str | None:
    """The identifier that finds an event, read from the one named field of its type, or None when
    the type is not looked up by payload. Other string fields are never matched."""
    payload = event.payload
    if event.type in ("search.page_archived", "search.records_parsed"):
        return str(payload["raw_blob"])
    if event.type == "dedup.merged":
        return str(payload["merge_id"])
    if event.type == "audit.sampled":
        return str(payload["audit_id"])
    if event.type == "audit.labelled":
        return f"{payload['audit_id']}/{payload['work_id']}"
    return None


def _event_index(events: Iterable[Event]) -> dict[tuple[str, str], str]:
    """(event type, named id) to the first event id with that id, for the scanned types. The
    events are taken in id order, so the first is the earliest."""
    index: dict[tuple[str, str], str] = {}
    for event in events:
        key = _lookup_key(event)
        if key is not None:
            index.setdefault((event.type, key), event.id)
    return index


def _split_cell(ident: str) -> tuple[str, str]:
    """`(row_key, field)` of a cell identifier; a bare row key names its `value` cell."""
    row_key, _, field = ident.partition("/")
    return row_key, field or "value"


def is_region_ref(ref: str) -> bool:
    """Whether `ref` has the form of a region, a region version or a region membership. Decided
    by form alone, so a caller can refuse it without reading the index."""
    key = _parse(ref.strip())
    return key is not None and key[0] in region_trace.REGION_KINDS


def _parse(ref: str) -> Key | None:
    if re.fullmatch(ENTRY_KEY_RE, ref):
        return ("reference_extraction", ref.rsplit(":", 1)[0])
    for pattern, kind in _PATTERNS:
        if re.fullmatch(pattern, ref):
            return (kind, ref)
    return None


def _build(
    walk: "_Walk",
    key: Key,
    described: _Described | None,
    direction: str,
    visited: set[Key],
    skip: Callable[[Key], bool] | None = None,
) -> TraceNode:
    """The subtree of `key`. A reference that names no row is a leaf with no event."""
    children: list[TraceNode] = []
    if described is not None:
        upstream, downstream = walk.edges(key)
        neighbours = upstream if direction == "back" else downstream
        ordered = sorted(
            set(neighbours),
            key=lambda item: (_RANK[item[0]], item[1]),
            reverse=direction == "back",
        )
        for neighbour in ordered:
            if neighbour in visited or (skip is not None and skip(neighbour)):
                continue
            visited.add(neighbour)
            children.append(
                _build(walk, neighbour, walk.describe(neighbour), direction, visited, skip)
            )
    shown = described or _Described(_MISSING, _NO_EVENT)
    return TraceNode(
        id=key[1],
        kind=key[0],
        label=shown.label,
        event_id=shown.event_id,
        children=children,
    )


class _Walk:
    """One walk's view of the projection. Caches the rows that many nodes share."""

    def __init__(
        self, project: Project, conn: Connection, layer: Layer = "evidence", agent: bool = False
    ) -> None:
        self._agent = agent
        self._project = project
        self._conn = conn
        self._layer = layer
        self._questions: dict[str, _QuestionRow] | None = None
        self._protocols: dict[str, _ProtocolRow] | None = None
        self._scanned: dict[tuple[str, str], str] | None = None
        self._chase: tuple[dict[str, str], dict[str, list[str]]] | None = None
        self._lookup_runs: dict[str, tuple[str, ...]] | None = None
        self._describers: dict[str, Callable[[str], _Described | None]] = {
            **{k: partial(self._draft_node, k) for k in draft_trace.DRAFT_KINDS},
            **{k: partial(self._manuscript_node, k) for k in manuscript_trace.MANUSCRIPT_KINDS},
            "question": self._question,
            "element": self._element,
            "criterion": self._criterion,
            "protocol": self._protocol,
            "query": self._query,
            "run": self._run,
            "page": self._page,
            "record": self._record,
            "merge": self._merge,
            "work": self._work,
            "attempt": self._attempt,
            "document": self._document,
            lab_trace.ADOPTION_KIND: self._adoption,
            "conversion": self._conversion,
            "anchor": self._anchor,
            "decision": self._decision,
            "extraction": self._extraction,
            "claim": self._claim,
            "appraisal": self._appraisal,
            "relation": self._relation,
            "idea": self._idea,
            "cites": self._cites,
            "quote": self._quote,
            "cell": self._cell,
            "resolution": self._resolution,
            "audit": self._audit,
            "seed": self._seed,
            "chase_round": self._chase_round,
            "reference_extraction": self._reference_extraction,
            "snowball_round": self._snowball_round,
            "inbox_item": self._inbox_item,
            "import": self._import,
            "import_record": self._import_record,
            "notice": self._notice,
            "version": self._version,
            "preference": self._preference,
            "interpretation": self._layer_node,
            "concept": self._layer_node,
            "concept_link": self._layer_node,
            "region": self._region_node,
            "region_version": self._region_node,
            "region_member": self._region_node,
            "label": self._organisation_node,
            "term": self._organisation_node,
            "consolidation": self._organisation_node,
            "proposal": self._organisation_node,
            "briefing": self._briefing,
            "served": self._served,
            "session": self._session,
        }
        self._describers.update({k: partial(self._slice6_node, k) for k in slice6_trace.KINDS})

    # --- Rows and events ---

    def _all(self, sql: str, **params: object) -> list[Sequence[Any]]:
        return [tuple(row) for row in self._conn.execute(text(sql), params).all()]

    def _column(self, sql: str, **params: object) -> list[str]:
        return [str(row[0]) for row in self._all(sql, **params)]

    def _question_rows(self) -> dict[str, _QuestionRow]:
        if self._questions is None:
            found: dict[str, _QuestionRow] = {}
            for qid, spec, event_id in self._all(
                "SELECT question_id, spec, event_id FROM questions ORDER BY event_id"
            ):
                if str(qid) not in found:
                    found[str(qid)] = _QuestionRow(
                        QuestionSpec.model_validate_json(str(spec)), str(event_id)
                    )
            self._questions = found
        return self._questions

    def _protocol_rows(self) -> dict[str, _ProtocolRow]:
        if self._protocols is None:
            found: dict[str, _ProtocolRow] = {}
            for pid, status, spec, event_id in self._all(
                "SELECT protocol_id, status, spec, event_id FROM protocols ORDER BY event_id"
            ):
                if str(pid) not in found:
                    found[str(pid)] = _ProtocolRow(
                        str(status), ProtocolSpec.model_validate_json(str(spec)), str(event_id)
                    )
            self._protocols = found
        return self._protocols

    def _event_of_ref(self, event_type: str, ident: str) -> str:
        """The first event of a type whose first ref is `ident` (queries and runs)."""
        found = self._column(
            "SELECT id FROM events WHERE type = :type AND json_extract(refs, '$[0]') = :ident "
            "ORDER BY id LIMIT 1",
            type=event_type,
            ident=ident,
        )
        return found[0] if found else _NO_EVENT

    def _event_for(self, event_type: str, key: str) -> str:
        """The first event of a type whose named id field is `key`. Used where the table keeps no
        event id. The event log is read once per walk, on the first such lookup; the cost is
        linear in the log, which is acceptable for a human view."""
        if self._scanned is None:
            self._scanned = _event_index(
                read_all(self._project.paths.events_dir, self._project.catalog)
            )
        return self._scanned.get((event_type, key), _NO_EVENT)

    def _chase_assignment(self) -> tuple[dict[str, str], dict[str, list[str]]]:
        """Each chase query mapped to the round it belongs to, and each round to its queries.

        A query belongs to the chase round its `query.registered` refs name. A query that names
        none (a log written before the ref existed) belongs to the latest round, recorded before
        the query, whose text it ran. Both identifiers are time-ordered ULIDs, so that comparison
        is on their ULID parts.

        Assumption for the fallback: `chase.round_started` is recorded before the round's queries
        are registered, so each query links to the latest earlier round, never to a later one.
        """
        if self._chase is None:
            named = {
                str(query_id): str(round_id)
                for query_id, round_id in self._all(
                    "SELECT q.ref, MAX(o.ref) FROM event_refs q "
                    "JOIN event_refs o ON o.event_id = q.event_id AND o.position > 0 "
                    "JOIN chase_rounds r ON r.round_id = o.ref "
                    "WHERE q.type = 'query.registered' AND q.position = 0 GROUP BY q.ref"
                )
            }
            rounds: dict[str, list[str]] = {}
            for round_id, query_text in self._all(
                "SELECT r.round_id, c.query FROM chase_rounds r "
                "JOIN chase_queries c ON c.round_id = r.round_id"
            ):
                rounds.setdefault(str(query_text), []).append(str(round_id))
            query_round: dict[str, str] = {}
            round_queries: dict[str, list[str]] = {}
            for query_id, query_text in self._all(
                "SELECT query_id, text FROM queries WHERE purpose = 'chase'"
            ):
                chosen = named.get(str(query_id))
                if chosen is None:
                    earlier = [
                        round_id
                        for round_id in rounds.get(str(query_text), [])
                        if round_id[len("chs_") :] < str(query_id)[len("qry_") :]
                    ]
                    chosen = max(earlier) if earlier else None
                if chosen is not None:
                    query_round[str(query_id)] = chosen
                    round_queries.setdefault(chosen, []).append(str(query_id))
            self._chase = (query_round, round_queries)
        return self._chase

    # --- Describing one node ---

    def describe(self, key: Key) -> _Described | None:
        """The label and creating event of a node, or None when no row names it."""
        return self._describers[key[0]](key[1])

    def _layer_node(self, ident: str) -> _Described | None:
        kind = {"int": "interpretation", "cpt": "concept", "cul": "concept_link"}[ident[:3]]
        found = layer_trace.describe(self._conn, kind, ident)
        return None if found is None else _Described(*found)

    def _region_node(self, ident: str) -> _Described | None:
        kind = (
            "region_member"
            if "/" in ident
            else "region_version"
            if ident.startswith("R@")
            else "region"
        )
        found = region_trace.describe(self._conn, kind, ident)
        return None if found is None else _Described(*found)

    def _slice6_node(self, kind: str, ident: str) -> _Described | None:
        found = slice6_trace.describe(self._conn, kind, ident)
        return None if found is None else _Described(*found)

    def _slice6_keys(self, refs: Sequence[slice6_trace.Ref]) -> list[Key]:
        keys = [r if isinstance(r, tuple) else _parse(r) for r in refs]
        return [k for k in keys if k is not None]

    def _organisation_node(self, ident: str) -> _Described | None:
        kind = {"lbl": "label", "trm": "term", "cns": "consolidation", "cnp": "proposal"}[ident[:3]]
        found = label_trace.describe(self._conn, kind, ident, agent=self._agent)
        return None if found is None else _Described(*found)

    def _draft_node(self, kind: str, ident: str) -> _Described | None:
        found = draft_trace.describe(self._conn, kind, ident)
        return None if found is None else _Described(*found)

    def _manuscript_node(self, kind: str, ident: str) -> _Described | None:
        found = manuscript_trace.describe(self._conn, kind, ident)
        return None if found is None else _Described(*found)

    def _question(self, ident: str) -> _Described | None:
        row = self._question_rows().get(ident)
        return None if row is None else _Described(row.spec.primary_question, row.event_id)

    def _element(self, ident: str) -> _Described | None:
        match = re.fullmatch(_ELEMENT_RE, ident)
        if match is None:
            return None
        row = self._question_rows().get(match.group(1))
        if row is None:
            return None
        parent = match.group(2)
        if parent.startswith("slot:"):
            slot = next((s for s in row.spec.slots if s.name == parent[len("slot:") :]), None)
            if slot is None:
                return None
            label = (
                f"{slot.name}: {slot.value}"
                if slot.value is not None
                else f"{slot.name} (open: {slot.open})"
            )
        elif parent.startswith("SQ"):
            sub_q = next((s for s in row.spec.sub_questions if s.id == parent), None)
            if sub_q is None:
                return None
            label = f"sub-question {sub_q.id}: {sub_q.text}"
        else:
            non_goal = next((g for g in row.spec.non_goals if g.id == parent), None)
            if non_goal is None:
                return None
            label = f"non-goal {non_goal.id}: {non_goal.text}"
        return _Described(label, row.event_id)

    def _criterion(self, ident: str) -> _Described | None:
        pid, cid = ident.rsplit(":", 1)
        row = self._protocol_rows().get(pid)
        if row is None:
            return None
        criterion = next((c for c in row.spec.criteria if c.id == cid), None)
        if criterion is None:
            return None
        label = f"{cid} ({criterion.kind.value}): {criterion.statement}"
        return _Described(label, row.event_id)

    def _protocol(self, ident: str) -> _Described | None:
        row = self._protocol_rows().get(ident)
        if row is None:
            return None
        label = (
            f"status {row.status}; method {row.spec.method_profile.value}; "
            f"{len(row.spec.criteria)} criteria"
        )
        return _Described(label, row.event_id)

    def _query(self, ident: str) -> _Described | None:
        rows = self._all("SELECT text FROM queries WHERE query_id = :q", q=ident)
        if not rows:
            return None
        return _Described(str(rows[0][0]), self._event_of_ref("query.registered", ident))

    def _run(self, ident: str) -> _Described | None:
        rows = self._all("SELECT status, retrieved_count FROM runs WHERE run_id = :r", r=ident)
        if not rows:
            return None
        status, retrieved = rows[0]
        count = "not finished" if retrieved is None else f"{retrieved} retrieved"
        return _Described(
            f"status {status}; {count}", self._event_of_ref("search.run_started", ident)
        )

    def served_key(self, ref: str) -> Key | None:
        """The key of `ref` when it names a served pack or a session that received one."""
        rows = self._all(
            "SELECT blob = :r FROM briefings_served WHERE blob = :r OR session = :r LIMIT 1", r=ref
        )
        if not rows:
            return None
        return ("briefing" if rows[0][0] else "session", ref)

    def _briefing(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT COUNT(*), MIN(event_id) FROM briefings_served WHERE blob = :b", b=ident
        )
        if not rows or not rows[0][0]:
            return None
        return _Described(f"context pack served to {rows[0][0]} session(s)", str(rows[0][1]))

    def _served(self, ident: str) -> _Described | None:
        rows = self._all("SELECT session, as_of FROM briefings_served WHERE event_id = :e", e=ident)
        if not rows:
            return None
        return _Described(f"briefing.served to {rows[0][0]} as of {rows[0][1]}", ident)

    def _session(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT COUNT(*), MIN(event_id) FROM briefings_served WHERE session = :s", s=ident
        )
        if not rows or not rows[0][0]:
            return None
        return _Described(f"session {ident}, {rows[0][0]} context pack(s)", str(rows[0][1]))

    def _edges_briefing(self, ident: str) -> tuple[list[Key], list[Key]]:
        served = self._column("SELECT event_id FROM briefings_served WHERE blob = :b", b=ident)
        return [], [("served", e) for e in served]

    def _edges_served(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all("SELECT blob, session FROM briefings_served WHERE event_id = :e", e=ident)
        return [("briefing", str(b)) for b, _ in rows], [("session", str(s)) for _, s in rows]

    def _edges_session(self, ident: str) -> tuple[list[Key], list[Key]]:
        served = self._column("SELECT event_id FROM briefings_served WHERE session = :s", s=ident)
        return [("served", e) for e in served], []

    def _page(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT ordinal FROM pages WHERE raw_blob = :b ORDER BY run_id, ordinal LIMIT 1",
            b=ident,
        )
        if not rows:
            return None
        label = f"archived raw page, ordinal {rows[0][0]}"
        return _Described(label, self._event_for("search.page_archived", ident))

    def _import(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT format, role, file_hash, parser, parser_version, split_mode, event_id "
            "FROM imports WHERE import_id = :i",
            i=ident,
        )
        if not rows:
            return None
        fmt, role, file_hash, parser, version, split, event_id = rows[0]
        label = f"{fmt} import, role {role}; file {file_hash}; parser {parser} {version}"
        return _Described(label + f"; split {split or 'none'}", str(event_id))

    def _import_record(self, ident: str) -> _Described | None:
        """A record of an import by hash, resolution and decision; never its title or fields."""
        import_id, ordinal = ident.rsplit(":", 1)
        rows = self._all(
            "SELECT r.outcome, r.record_sha256, r.link_state, r.method, r.decision, i.event_id "
            "FROM import_records r JOIN imports i ON i.import_id = r.import_id "
            "WHERE r.import_id = :i AND r.ordinal = :o",
            i=import_id,
            o=int(ordinal),
        )
        if not rows:
            return None
        outcome, sha, state, method, decision, event_id = rows[0]
        label = f"record {sha}; {outcome}"
        if state is not None:
            label += f"; {state} by {method or 'decision'}"
        if decision is not None:
            label += f"; decision {decision}"
        return _Described(label, str(event_id))

    def _import_lookup_runs(self) -> dict[str, tuple[str, ...]]:
        """The lookup runs of each import's latest resolution, from the log (the index keeps the
        resolutions, not the runs). Read once per walk."""
        if self._lookup_runs is None:
            found: dict[str, tuple[str, ...]] = {}
            for event in read_all(self._project.paths.events_dir, self._project.catalog):
                if event.type == "import.resolved":
                    runs = event.payload["lookup_runs"]
                    assert isinstance(runs, list)
                    found[str(event.payload["import_id"])] = tuple(str(r) for r in runs)
            self._lookup_runs = found
        return self._lookup_runs

    def _record(self, ident: str) -> _Described | None:
        run_id, work_id = ident.split("/", 1)
        rows = self._all(
            "SELECT raw_blob, method, source FROM provenance WHERE run_id = :r AND work_id = :w",
            r=run_id,
            w=work_id,
        )
        if not rows:
            return None
        blob, method, source = rows[0]
        label = f"{method} ({source})"
        return _Described(label, self._event_for("search.records_parsed", str(blob)))

    def _merge(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT rule, records, status, reverted_reason, manual FROM merges WHERE merge_id = :m",
            m=ident,
        )
        if not rows:
            return None
        rule, records, status, reason, manual = rows[0]
        base = f"{rule}; {records} records"
        if str(status) == "reverted":
            by = "by hand" if manual else "by the cascade"
            label = f"{base}; reverted {by}: {reason}"
        else:
            label = f"{base}; active"
        return _Described(label, self._event_for("dedup.merged", ident))

    def _work(self, ident: str) -> _Described | None:
        rows = self._all("SELECT data, first_event_id FROM works WHERE work_id = :w", w=ident)
        if not rows:
            return self._no_source_work(ident)
        title = json.loads(str(rows[0][0]))["title"]
        return _Described(str(title), str(rows[0][1]))

    def _no_source_work(self, ident: str) -> _Described | None:
        """A work only a reference names: no source returned it, so its entry describes it."""
        rows = self._all(
            "SELECT n.title, l.event_id FROM reference_links l JOIN reference_entries n "
            "ON n.extraction_id = l.extraction_id AND n.ordinal = l.ordinal "
            "WHERE l.work_id = :w AND l.no_source_record = 1 ORDER BY l.event_id LIMIT 1",
            w=ident,
        )
        if not rows:
            return None
        return _Described(f"{rows[0][0]} (no source record)", str(rows[0][1]))

    def _attempt(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT route, outcome, reason, event_id FROM fulltext_attempts WHERE attempt_id = :a",
            a=ident,
        )
        if not rows:
            return None
        route, outcome, reason, event_id = rows[0]
        label = f"{route}: {outcome}"
        if reason is not None:
            label += f" ({reason})"
        return _Described(label, str(event_id))

    def _adoption(self, ident: str) -> _Described | None:
        found = lab_trace.describe(self._project, self._conn, ident)
        return None if found is None else _Described(*found)

    def _document(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT route, quality, superseded_by, event_id FROM fulltext_documents "
            "WHERE document_id = :d",
            d=ident,
        )
        if not rows:
            return None
        route, quality, superseded_by, event_id = rows[0]
        label = f"{route}, {quality}"
        if superseded_by is not None:
            label += " (superseded)"
        return _Described(label, str(event_id))

    def _conversion(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT converter, converter_version, event_id FROM document_conversions "
            "WHERE conversion_id = :c",
            c=ident,
        )
        if not rows:
            return None
        converter, version, event_id = rows[0]
        return _Described(f"{converter} {version}", str(event_id))

    def _anchor(self, ident: str) -> _Described | None:
        """An anchor cited by a full-text decision, keyed `<conversion_id>/<anchor>`. It exists
        when its conversion does; its event is the conversion's."""
        conversion_id, anchor = ident.split("/", 1)
        described = self._conversion(conversion_id)
        if described is None:
            return None
        return _Described(f"anchor {anchor}", described.event_id)

    def _decision_set(self, ident: str) -> _Described | None:
        """A develop decision (slice 8): it shares the `dec_` prefix with screening decisions,
        so it is looked up here when the screening table has no such row."""
        rows = self._all(
            "SELECT d.level, d.subject, e.id FROM decision_sets d "
            "LEFT JOIN events e ON e.type = 'decision.suggested' "
            "AND json_extract(e.refs, '$[0]') = d.decision_id "
            "WHERE d.decision_id = :d",
            d=ident,
        )
        if not rows:
            return None
        level, subject, event_id = rows[0]
        return _Described(f"{level} decision: {subject}", str(event_id or _NO_EVENT))

    def _decision(self, ident: str) -> _Described | None:
        """A `dec_` id names a screening decision or, failing that, a decision suggestion (the
        two share the namespace; records cite suggestions). An id of neither has no node."""
        rows = self._all(
            "SELECT pass_label, phase, verdict, criterion, superseded_by, event_id "
            "FROM decisions WHERE decision_id = :d",
            d=ident,
        )
        if not rows:
            return self._decision_set(ident)
        pass_label, phase, verdict, criterion, superseded_by, event_id = rows[0]
        label = f"pass {pass_label}, {phase}: {verdict}"
        if criterion is not None:
            label += f" under {str(criterion).rsplit(':', 1)[-1]}"
        if superseded_by is not None:
            label += " (superseded)"
        return _Described(label, str(event_id))

    def _extraction(self, ident: str) -> _Described | None:
        """An extraction row. The label gives its pass and field count, never a value; a row of
        another scope than evidence says so. Rows of every scope are real provenance of their work,
        so the work, anchor and conversion views list them; only report cells are evidence."""
        rows = self._all(
            "SELECT pass_label, superseded_by, event_id, "
            "(SELECT COUNT(*) FROM extraction_fields f WHERE f.extraction_id = r.extraction_id), "
            "scope FROM extraction_rows r WHERE extraction_id = :e",
            e=ident,
        )
        if not rows:
            return None
        pass_label, superseded_by, event_id, fields, scope = rows[0]
        label = f"pass {pass_label}, {fields} field(s)"
        if scope != "evidence":
            label += f" ({scope})"
        if superseded_by is not None:
            label += " (superseded)"
        return _Described(label, str(event_id))

    def _appraisal_row(self, ident: str) -> Sequence[Any] | None:
        """The answer row of `app_<event ULID>/<item>`: pass, item, answer, work, conversion,
        anchor and event. The label and edges carry no quote."""
        match = re.fullmatch(_APPRAISAL_RE, ident)
        if match is None:
            return None
        rows = self._all(
            "SELECT pass_label, item, answer, work_id, conversion_id, anchor, event_id "
            "FROM appraisal_answers WHERE event_id = :e AND item = :i",
            e=f"ev_{match.group(1)}",
            i=match.group(2),
        )
        return rows[0] if rows else None

    def _appraisal(self, ident: str) -> _Described | None:
        """An appraisal answer. The label gives pass, item and answer, never a quote."""
        row = self._appraisal_row(ident)
        if row is None:
            return None
        return _Described(f"appraisal pass {row[0]} · {row[1]} · {row[2]}", str(row[6]))

    def _edges_appraisal(self, ident: str) -> tuple[list[Key], list[Key]]:
        row = self._appraisal_row(ident)
        if row is None:
            return [], []
        up: list[Key] = [("work", str(row[3])), ("conversion", str(row[4]))]
        if row[5] is not None:
            up.append(("anchor", f"{row[4]}/{row[5]}"))
        return up, []

    def _claim(self, ident: str) -> _Described | None:
        """A claim. The label gives its pass, type and strength, never its statement."""
        rows = self._all(
            "SELECT pass_label, claim_type, strength, superseded_by, event_id "
            "FROM extraction_claims WHERE claim_id = :c",
            c=ident,
        )
        if not rows:
            return None
        pass_label, claim_type, strength, superseded_by, event_id = rows[0]
        label = f"pass {pass_label}, {claim_type}, {strength}"
        if superseded_by is not None:
            label += " (superseded)"
        return _Described(label, str(event_id))

    def _relation(self, ident: str) -> _Described | None:
        """A relation. The label gives its edge type, proposal status, decision and effective
        status, never a note or a quote."""
        view = relation_view(self._project, ident)
        if view is None:
            return None
        label = f"{view.edge_type} {view.proposal_status}"
        if view.status_reason is not None:
            label += f" ({view.status_reason.value})"
        decision = "none" if view.decision is None else view.decision.value
        label += f", decision {decision}, effective {view.effective.value}"
        if view.stale_reasons:
            label += f" ({', '.join(view.stale_reasons)})"
        superseded = self._column(
            "SELECT superseded_by FROM relations WHERE relation_id = :r AND superseded_by "
            "IS NOT NULL",
            r=ident,
        )
        if superseded:
            label += " (superseded)"
        return _Described(label, view.event_id)

    def _idea(self, ident: str) -> _Described | None:
        """An idea. The label gives its state and member count, never its name."""
        view = idea_view(self._project, ident)
        if view is None:
            return None
        return _Described(f"idea {view.state}, {len(view.members)} member(s)", view.event_id)

    def _cites(self, ident: str) -> _Described | None:
        """A `cites` edge of the graph projection: its status and whether its extraction is
        the work's current one."""
        rows = self._all(
            "SELECT e.base_status, e.decision, e.live, e.event_id FROM graph_edges e "
            "WHERE e.edge_id = :i",
            i=ident,
        )
        if not rows:
            return None
        base_status, decision, live, event_id = rows[0]
        label = f"cites {cites_status(str(base_status), decision).value}"
        if not live:
            label += " (superseded extraction)"
        return _Described(label, str(event_id))

    def _quote(self, ident: str) -> _Described | None:
        """The verified quote of a contribution row, the one place a label carries document text
        (it is already in the event)."""
        row_id = ident.removesuffix("/quote")
        item = contribution_item(self._project, row_id)
        if item is None or not item.quote:
            return None
        return _Described(item.quote, item.event_id)

    def _cell(self, ident: str) -> _Described | None:
        """A cell of an evidence-report row. The label names the field and the work, never a value;
        the event is that of the earliest extraction carrying the cell."""
        row_key, field = _split_cell(ident)
        rows = self._all(
            "SELECT r.work_id, r.event_id FROM extraction_rows r "
            "JOIN extraction_fields f ON f.extraction_id = r.extraction_id "
            "WHERE r.row_key = :k AND f.field = :f AND r.scope = 'evidence' "
            "ORDER BY r.event_id LIMIT 1",
            k=row_key,
            f=field,
        )
        if not rows:
            return None
        return _Described(f"{field} cell of {rows[0][0]}", str(rows[0][1]))

    def _resolution(self, ident: str) -> _Described | None:
        stage, work_id = _split_res(ident)
        rows = self._all(
            "SELECT verdict, criterion, event_id FROM resolutions "
            "WHERE work_id = :w AND stage = :s",
            w=work_id,
            s=stage,
        )
        if not rows:
            return None
        verdict, criterion, event_id = rows[0]
        label = f"disagreement resolved: {verdict}"
        if criterion is not None:
            label += f" under {str(criterion).rsplit(':', 1)[-1]}"
        return _Described(label, str(event_id))

    def _audit(self, ident: str) -> _Described | None:
        if "/" in ident:
            audit_id, work_id = ident.split("/", 1)
            rows = self._all(
                "SELECT human_verdict FROM audit_items WHERE audit_id = :a AND work_id = :w",
                a=audit_id,
                w=work_id,
            )
            if not rows:
                return None
            verdict = rows[0][0]
            if verdict is None:
                return _Described(
                    "sampled; not labelled", self._event_for("audit.sampled", audit_id)
                )
            return _Described(
                f"sampled; human verdict {verdict}",
                self._event_for("audit.labelled", ident),
            )
        rows = self._all("SELECT population FROM audits WHERE audit_id = :a", a=ident)
        if not rows:
            return None
        drawn = self._all("SELECT COUNT(*) FROM audit_items WHERE audit_id = :a", a=ident)
        label = f"{drawn[0][0]} works drawn from a population of {rows[0][0]}"
        return _Described(label, self._event_for("audit.sampled", ident))

    def _seed(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT kind, work_id, unresolved_reason, added_event FROM seeds WHERE seed_id = :s",
            s=ident,
        )
        if not rows:
            return None
        kind, work_id, unresolved, added = rows[0]
        admitted = self._all("SELECT work_id FROM seed_admissions WHERE seed_id = :s", s=ident)
        if work_id is not None:
            status = "resolved"
        elif admitted and admitted[0][0] is not None:
            status = "admitted by ID lookup"
        elif admitted:
            status = "ID lookup found no work"
        elif unresolved is not None:
            status = "unresolved"
        else:
            status = "not yet looked up"
        return _Described(f"{kind} seed, {status}", str(added))

    def _inbox_item(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT identifier_kind, actor_kind, added_event_id FROM inbox_items "
            "WHERE item_id = :i",
            i=ident,
        )
        if not rows:
            return None
        kind, actor, event_id = rows[0]
        return _Described(f"link ({kind}) captured by {actor}", str(event_id))

    def _notice(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT n.kind, n.source, n.notice_date, n.event_id, "
            "(SELECT a.decision FROM notice_assessments a WHERE a.notice_id = n.notice_id "
            "ORDER BY a.event_id DESC LIMIT 1) FROM notices n WHERE n.notice_id = :n",
            n=ident,
        )
        if not rows:
            return None
        kind, source, when, event_id, decision = rows[0]
        date_text = "date not stated by source" if when is None else str(when)
        return _Described(
            f"{kind} notice ({source}, {date_text}); {decision or 'unassessed'}", str(event_id)
        )

    def _version(self, ident: str) -> _Described | None:
        match = re.fullmatch(_VERSION_RE, ident)
        if match is None:
            return None
        work, which, rest = match.groups()
        if which == "obs":
            route, _, version = rest.partition("/")
            rows = self._all(
                "SELECT event_id FROM version_observations WHERE work_id = :w AND route = :r "
                "AND source_version = :v",
                w=work,
                r=route,
                v=version,
            )
            return _Described(f"newer {route} version {version}", str(rows[0][0])) if rows else None
        rows = self._all(
            "SELECT event_id, source, conflicts_with FROM version_links "
            "WHERE work_id = :w AND link_key = :k",
            w=work,
            k=rest,
        )
        if not rows:
            return None
        event_id, source, clash = rows[0]
        state = "refused: held by another work" if clash else "applied as an alias"
        return _Described(f"published version {rest} ({source}); {state}", str(event_id))

    def _preference(self, ident: str) -> _Described | None:
        match = re.fullmatch(_PREFERENCE_RE, ident)
        if match is None:
            return None
        rows = self._all(
            "SELECT document_id, automatic, event_id FROM document_preferences "
            "WHERE work_id = :w ORDER BY event_id DESC LIMIT 1",
            w=match.group(1),
        )
        if not rows or rows[0][1]:
            return None
        return _Described(f"preferred document {rows[0][0]}", str(rows[0][2]))

    def _chase_round(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT directions, from_works, event_id FROM chase_rounds WHERE round_id = :c",
            c=ident,
        )
        if not rows:
            return None
        directions, from_works, event_id = rows[0]
        names = "+".join(json.loads(str(directions)))
        works = len(json.loads(str(from_works)))
        queries = self._chase_assignment()[1].get(ident, [])
        label = f"{names} chase from {works} works, {len(queries)} queries"
        return _Described(label, str(event_id))

    def _reference_extraction(self, ident: str) -> _Described | None:
        """A reference extraction. The label gives its parser and entry count, never an entry."""
        rows = self._all(
            "SELECT parser, parser_version, live, event_id, "
            "(SELECT COUNT(*) FROM reference_entries n WHERE n.extraction_id = x.extraction_id) "
            "FROM reference_extractions x WHERE extraction_id = :x",
            x=ident,
        )
        if not rows:
            return None
        parser, version, live, event_id, entries = rows[0]
        label = f"{parser} {version}, {entries} entries"
        if not live:
            label += " (superseded)"
        return _Described(label, str(event_id))

    def _snowball_round(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT direction, round_no, via, sources, event_id FROM snowball_rounds "
            "WHERE round_id = :r",
            r=ident,
        )
        if not rows:
            return None
        direction, round_no, via, sources, event_id = rows[0]
        works = len(json.loads(str(sources)))
        return _Described(f"{direction} round {round_no} via {via}, {works} sources", str(event_id))

    # --- Neighbours: upstream (derived from) and downstream (derived into) ---

    def edges(self, key: Key) -> tuple[list[Key], list[Key]]:
        """The upstream and downstream neighbours of a node, as keys. A key may name no row; the
        walk shows such a key as a missing node."""
        kind, ident = key
        if kind in region_trace.REGION_KINDS:
            return region_trace.edges(self._conn, kind, ident)
        if kind == lab_trace.ADOPTION_KIND:
            return lab_trace.edges(self._conn, ident)
        if kind in draft_trace.DRAFT_KINDS:
            return draft_trace.edges(self._project, self._conn, kind, ident)
        if kind in manuscript_trace.MANUSCRIPT_KINDS:
            return manuscript_trace.edges(self._conn, kind, ident)
        if kind in layer_trace.LAYER_KINDS:
            up, down = layer_trace.edges(self._conn, kind, ident)
        elif kind in label_trace.ORGANISATION_KINDS:
            up, down = label_trace.edges(self._conn, kind, ident)
        elif kind in slice6_trace.KINDS:
            s6_up, s6_down = slice6_trace.edges(self._conn, kind, ident)
            return self._slice6_keys(s6_up), self._slice6_keys(s6_down)
        else:
            up, down = _EDGES[kind](self, ident)
        if kind in ("work", "idea", "cell", "claim"):
            down = [
                *down,
                *self._slice6_keys(slice6_trace.attached(self._conn, kind, ident.split("/", 1)[0])),
            ]
        if kind in draft_trace.CITABLE_KINDS:
            down = [*down, *draft_trace.citing(self._conn, kind, ident)]
        if self._layer == "all" and kind in ("anchor", "work", "idea"):
            down = [*down, *layer_trace.attached(self._conn, kind, ident)]
        if self._layer == "all" and kind in ("work", "idea", "concept"):
            down = [*down, *region_trace.attached(self._conn, kind, ident)]
        return up, down

    def _up_question(self, ident: str) -> tuple[list[Key], list[Key]]:
        up = [
            ("question", s)
            for s in self._column(
                "SELECT supersedes FROM questions "
                "WHERE question_id = :q AND supersedes IS NOT NULL",
                q=ident,
            )
        ]
        down = [
            ("question", q)
            for q in self._column(
                "SELECT DISTINCT question_id FROM questions WHERE supersedes = :q", q=ident
            )
        ]
        row = self._question_rows().get(ident)
        if row is not None:
            down += [("element", f"{ident}/slot:{s.name}") for s in row.spec.slots]
            down += [("element", f"{ident}/{g.id}") for g in row.spec.non_goals]
            down += [("element", f"{ident}/{s.id}") for s in row.spec.sub_questions]
            down += [
                ("protocol", pid)
                for pid, protocol in self._protocol_rows().items()
                if protocol.spec.question_id == ident
            ]
        return up, down

    def _up_element(self, ident: str) -> tuple[list[Key], list[Key]]:
        qid, parent = ident.split("/", 1)
        up: list[Key] = [("question", qid)]
        down: list[Key] = []
        for pid, protocol in self._protocol_rows().items():
            if protocol.spec.question_id != qid:
                continue
            down += [
                ("criterion", f"{pid}:{c.id}") for c in protocol.spec.criteria if c.parent == parent
            ]
        return up, down

    def _edges_criterion(self, ident: str) -> tuple[list[Key], list[Key]]:
        pid, cid = ident.rsplit(":", 1)
        up: list[Key] = [("protocol", pid)]
        row = self._protocol_rows().get(pid)
        if row is not None:
            criterion = next((c for c in row.spec.criteria if c.id == cid), None)
            if criterion is not None and criterion.parent is not None:
                up.append(("element", f"{row.spec.question_id}/{criterion.parent}"))
        down: list[Key] = [
            ("decision", d)
            for d in self._column("SELECT decision_id FROM decisions WHERE criterion = :c", c=ident)
        ]
        down += [
            ("resolution", _res_key(str(st), str(w)))
            for st, w in self._all(
                "SELECT stage, work_id FROM resolutions WHERE criterion = :c", c=ident
            )
        ]
        down += [
            ("audit", f"{a}/{w}")
            for a, w in self._all(
                "SELECT audit_id, work_id FROM audit_items WHERE criterion = :c", c=ident
            )
        ]
        return up, down

    def _edges_protocol(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = []
        down: list[Key] = []
        row = self._protocol_rows().get(ident)
        if row is not None:
            up.append(("question", row.spec.question_id))
            down += [("criterion", f"{ident}:{c.id}") for c in row.spec.criteria]
        up += [
            ("protocol", p)
            for p in self._column(
                "SELECT json_extract(payload, '$.from_version') FROM amendments "
                "WHERE json_extract(payload, '$.to_version') = :p "
                "AND json_extract(payload, '$.from_version') <> :p",
                p=ident,
            )
        ]
        down += [
            ("protocol", p)
            for p in self._column(
                "SELECT json_extract(payload, '$.to_version') FROM amendments "
                "WHERE json_extract(payload, '$.from_version') = :p "
                "AND json_extract(payload, '$.to_version') <> :p",
                p=ident,
            )
        ]
        down += [
            ("query", q)
            for q in self._column(
                "SELECT json_extract(e.refs, '$[0]') FROM events e "
                "WHERE e.type = 'query.registered' "
                "AND EXISTS (SELECT 1 FROM json_each(e.refs) j WHERE j.value = :p)",
                p=ident,
            )
        ]
        down += [
            ("decision", d)
            for d in self._column(
                "SELECT decision_id FROM decisions WHERE protocol_id = :p", p=ident
            )
        ]
        return up, down

    def _edges_query(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("protocol", p)
            for p in self._column(
                "SELECT j.value FROM events e, json_each(e.refs) j "
                "WHERE e.type = 'query.registered' AND json_extract(e.refs, '$[0]') = :q "
                "AND j.value LIKE 'P@%'",
                q=ident,
            )
        ]
        round_id = self._chase_assignment()[0].get(ident)
        if round_id is not None:
            up.append(("chase_round", round_id))
        up += [
            ("snowball_round", r)
            for r in self._column(
                "SELECT j.value FROM events e, json_each(e.refs) j "
                "WHERE e.type = 'query.registered' AND json_extract(e.refs, '$[0]') = :q "
                "AND substr(j.value, 1, 4) = 'snw_'",
                q=ident,
            )
        ]
        up += [
            ("import", i)
            for i in self._column(
                "SELECT j.value FROM events e, json_each(e.refs) j "
                "WHERE e.type = 'query.registered' AND json_extract(e.refs, '$[0]') = :q "
                "AND substr(j.value, 1, 4) = 'imp_'",
                q=ident,
            )
        ]
        down: list[Key] = [
            ("run", r) for r in self._column("SELECT run_id FROM runs WHERE query_id = :q", q=ident)
        ]
        return up, down

    def _edges_run(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("query", q)
            for q in self._column("SELECT query_id FROM runs WHERE run_id = :r", r=ident)
        ]
        up += [("import", imp) for imp, runs in self._import_lookup_runs().items() if ident in runs]
        down: list[Key] = [
            ("page", b)
            for b in self._column("SELECT DISTINCT raw_blob FROM pages WHERE run_id = :r", r=ident)
        ]
        down += [
            ("seed", s)
            for s in self._column(
                "SELECT seed_id FROM seeds WHERE run_id = :r "
                "UNION SELECT seed_id FROM seed_admissions WHERE run_id = :r",
                r=ident,
            )
        ]
        return up, down

    def _edges_page(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("run", r)
            for r in self._column("SELECT DISTINCT run_id FROM pages WHERE raw_blob = :b", b=ident)
        ]
        down: list[Key] = [
            ("record", f"{r}/{w}")
            for r, w in self._all(
                "SELECT run_id, work_id FROM provenance WHERE raw_blob = :b AND query_id NOT IN "
                "(SELECT query_id FROM queries WHERE purpose = 'probe')",
                b=ident,
            )
        ]
        return up, down

    def _edges_record(self, ident: str) -> tuple[list[Key], list[Key]]:
        run_id, work_id = ident.split("/", 1)
        up: list[Key] = [
            ("page", b)
            for b in self._column(
                "SELECT raw_blob FROM provenance WHERE run_id = :r AND work_id = :w",
                r=run_id,
                w=work_id,
            )
        ]
        return up, [("work", work_id)]

    def _edges_merge(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("work", w)
            for w in self._column(
                "SELECT j.value FROM merges m, json_each(m.absorbed) j WHERE m.merge_id = :m",
                m=ident,
            )
        ]
        down: list[Key] = [
            ("work", w)
            for w in self._column('SELECT "primary" FROM merges WHERE merge_id = :m', m=ident)
        ]
        return up, down

    def _edges_work(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("record", f"{r}/{ident}")
            for r in self._column(
                "SELECT run_id FROM provenance WHERE work_id = :w AND query_id NOT IN "
                "(SELECT query_id FROM queries WHERE purpose = 'probe')",
                w=ident,
            )
        ]
        up += [
            ("import_record", f"{i}:{o}")
            for i, o in self._all(
                "SELECT import_id, ordinal FROM import_records "
                "WHERE work_id = :w AND link_state = 'resolved'",
                w=ident,
            )
        ]
        up += [
            ("merge", m)
            for m in self._column('SELECT merge_id FROM merges WHERE "primary" = :w', w=ident)
        ]
        up += [
            ("inbox_item", i)
            for i in self._column(
                "SELECT DISTINCT item_id FROM inbox_resolutions WHERE work_id = :w", w=ident
            )
        ]
        up += [
            ("seed", s)
            for s in self._column(
                "SELECT seed_id FROM seeds WHERE work_id = :w "
                "UNION SELECT seed_id FROM seed_admissions WHERE work_id = :w",
                w=ident,
            )
        ]
        up += [
            ("anchor", f"{c}/{a}")
            for c, a in self._all(
                "SELECT x.conversion_id, n.anchor FROM reference_links l "
                "JOIN reference_extractions x ON x.extraction_id = l.extraction_id AND x.live = 1 "
                "JOIN reference_entries n ON n.extraction_id = l.extraction_id "
                "AND n.ordinal = l.ordinal WHERE l.work_id = :w AND l.state = 'resolved'",
                w=ident,
            )
        ]
        down: list[Key] = [
            ("merge", m)
            for m in self._column(
                "SELECT m.merge_id FROM merges m, json_each(m.absorbed) j WHERE j.value = :w",
                w=ident,
            )
        ]
        down += [
            ("attempt", a)
            for a in self._column(
                "SELECT attempt_id FROM fulltext_attempts WHERE work_id = :w", w=ident
            )
        ]
        down += [
            ("document", d)
            for d in self._column(
                "SELECT document_id FROM fulltext_documents WHERE work_id = :w", w=ident
            )
        ]
        down += [
            ("decision", d)
            for d in self._column("SELECT decision_id FROM decisions WHERE work_id = :w", w=ident)
        ]
        down += [
            ("extraction", e)
            for e in self._column(
                "SELECT extraction_id FROM extraction_rows WHERE work_id = :w", w=ident
            )
        ]
        down += [
            ("claim", k)
            for k in self._column(
                "SELECT claim_id FROM extraction_claims WHERE work_id = :w", w=ident
            )
        ]
        down += [
            ("resolution", _res_key(str(st), ident))
            for st in self._column("SELECT stage FROM resolutions WHERE work_id = :w", w=ident)
        ]
        down += [
            ("audit", f"{a}/{ident}")
            for a in self._column("SELECT audit_id FROM audit_items WHERE work_id = :w", w=ident)
        ]
        down += [
            ("chase_round", c)
            for c in self._column(
                "SELECT r.round_id FROM chase_rounds r, json_each(r.from_works) j "
                "WHERE j.value = :w",
                w=ident,
            )
        ]
        down += [
            ("reference_extraction", x)
            for x in self._column(
                "SELECT extraction_id FROM reference_extractions WHERE work_id = :w", w=ident
            )
        ]
        down += [
            ("snowball_round", r)
            for r in self._column(
                "SELECT r.round_id FROM snowball_rounds r, json_each(r.sources) j "
                "WHERE j.value = :w",
                w=ident,
            )
        ]
        down += [
            ("notice", n)
            for n in self._column("SELECT notice_id FROM notices WHERE work_id = :w", w=ident)
        ]
        down += [
            ("version", f"ver:{ident}/obs/{route}/{version}")
            for route, version in self._all(
                "SELECT route, source_version FROM version_observations WHERE work_id = :w", w=ident
            )
        ]
        down += [
            ("version", f"ver:{ident}/link/{key}")
            for key in self._column(
                "SELECT link_key FROM version_links WHERE work_id = :w", w=ident
            )
        ]
        if self._describers["preference"](f"pref:{ident}") is not None:
            down.append(("preference", f"pref:{ident}"))
        return up, down

    def _edges_notice(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all("SELECT work_id, run_id FROM notices WHERE notice_id = :n", n=ident)
        if not rows:
            return [], []
        work_id, run_id = rows[0]
        return [("work", str(work_id)), ("run", str(run_id))], []

    def _edges_version(self, ident: str) -> tuple[list[Key], list[Key]]:
        match = re.fullmatch(_VERSION_RE, ident)
        return ([("work", match.group(1))] if match else []), []

    def _edges_preference(self, ident: str) -> tuple[list[Key], list[Key]]:
        match = re.fullmatch(_PREFERENCE_RE, ident)
        if match is None:
            return [], []
        rows = self._all(
            "SELECT document_id FROM document_preferences WHERE work_id = :w "
            "ORDER BY event_id DESC LIMIT 1",
            w=match.group(1),
        )
        up: list[Key] = [("work", match.group(1))]
        if rows:
            up.append(("document", str(rows[0][0])))
        return up, []

    def _edges_attempt(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all(
            "SELECT work_id, document_id FROM fulltext_attempts WHERE attempt_id = :a", a=ident
        )
        up: list[Key] = []
        down: list[Key] = []
        if rows:
            work_id, document_id = rows[0]
            up.append(("work", str(work_id)))
            if document_id is not None:
                down.append(("document", str(document_id)))
        return up, down

    def _edges_document(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("attempt", a)
            for a in self._column(
                "SELECT attempt_id FROM fulltext_documents WHERE document_id = :d", d=ident
            )
        ]
        up += [
            (lab_trace.ADOPTION_KIND, lab_trace.adoption_key(d))
            for d in self._column(
                "SELECT document_id FROM fulltext_adoptions WHERE document_id = :d", d=ident
            )
        ]
        down: list[Key] = [
            ("conversion", c)
            for c in self._column(
                "SELECT conversion_id FROM document_conversions WHERE document_id = :d", d=ident
            )
        ]
        return up, down

    def _edges_conversion(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("document", d)
            for d in self._column(
                "SELECT document_id FROM document_conversions WHERE conversion_id = :c", c=ident
            )
        ]
        down: list[Key] = [
            ("anchor", f"{ident}/{a}")
            for a in self._column(
                "SELECT DISTINCT anchor FROM decisions "
                "WHERE conversion_id = :c AND anchor IS NOT NULL",
                c=ident,
            )
        ]
        down += [("anchor", f"{ident}/{a}") for a in self._extraction_anchors(ident)]
        return up, down

    def _extraction_anchors(self, conversion_id: str) -> list[str]:
        """The anchors and cells that extraction rows and claims cite in a conversion."""
        return self._column(
            "SELECT f.anchor FROM extraction_fields f JOIN extraction_rows r "
            "ON r.extraction_id = f.extraction_id WHERE r.conversion_id = :c "
            "AND f.anchor IS NOT NULL "
            "UNION SELECT f.cell FROM extraction_fields f JOIN extraction_rows r "
            "ON r.extraction_id = f.extraction_id WHERE r.conversion_id = :c "
            "AND f.cell IS NOT NULL "
            "UNION SELECT anchor FROM extraction_claims WHERE conversion_id = :c",
            c=conversion_id,
        )

    def _edges_anchor(self, ident: str) -> tuple[list[Key], list[Key]]:
        conversion_id, anchor = ident.split("/", 1)
        down: list[Key] = [
            ("decision", d)
            for d in self._column(
                "SELECT decision_id FROM decisions WHERE conversion_id = :c AND anchor = :a",
                c=conversion_id,
                a=anchor,
            )
        ]
        down += [
            ("extraction", e)
            for e in self._column(
                "SELECT DISTINCT r.extraction_id FROM extraction_rows r JOIN extraction_fields f "
                "ON f.extraction_id = r.extraction_id WHERE r.conversion_id = :c "
                "AND (f.anchor = :a OR f.cell = :a)",
                c=conversion_id,
                a=anchor,
            )
        ]
        down += [
            ("claim", k)
            for k in self._column(
                "SELECT claim_id FROM extraction_claims WHERE conversion_id = :c AND anchor = :a",
                c=conversion_id,
                a=anchor,
            )
        ]
        extractions = self._column(
            "SELECT DISTINCT x.extraction_id FROM reference_extractions x "
            "JOIN reference_entries n ON n.extraction_id = x.extraction_id "
            "WHERE x.conversion_id = :c AND n.anchor = :a",
            c=conversion_id,
            a=anchor,
        )
        down += [
            ("work", w)
            for w in self._column(
                "SELECT DISTINCT l.work_id FROM reference_links l "
                "JOIN reference_extractions x ON x.extraction_id = l.extraction_id AND x.live = 1 "
                "JOIN reference_entries n ON n.extraction_id = l.extraction_id "
                "AND n.ordinal = l.ordinal WHERE x.conversion_id = :c AND n.anchor = :a "
                "AND l.state = 'resolved' AND l.work_id IS NOT NULL",
                c=conversion_id,
                a=anchor,
            )
        ]
        up: list[Key] = [("conversion", conversion_id)]
        up += [("reference_extraction", x) for x in extractions]
        return up, down

    def _full_text_decisions(self, work_id: str) -> list[Key]:
        return [
            ("decision", d)
            for d in self._column(
                "SELECT decision_id FROM decisions WHERE work_id = :w AND stage = 'full-text'",
                w=work_id,
            )
        ]

    def _edges_extraction(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all(
            "SELECT work_id, protocol_id, conversion_id, supersedes, superseded_by "
            "FROM extraction_rows WHERE extraction_id = :e",
            e=ident,
        )
        up: list[Key] = []
        down: list[Key] = []
        if rows:
            work_id, protocol_id, conversion_id, supersedes, superseded_by = rows[0]
            up += [("work", str(work_id)), ("protocol", str(protocol_id))]
            cited = self._column(
                "SELECT anchor FROM extraction_fields WHERE extraction_id = :e "
                "AND anchor IS NOT NULL UNION SELECT cell FROM extraction_fields "
                "WHERE extraction_id = :e AND cell IS NOT NULL",
                e=ident,
            )
            up += [("anchor", f"{conversion_id}/{a}") for a in cited]
            up += self._full_text_decisions(str(work_id))
            if supersedes is not None:
                up.append(("extraction", str(supersedes)))
            if superseded_by is not None:
                down.append(("extraction", str(superseded_by)))
            if self._column(
                "SELECT extraction_id FROM extraction_rows WHERE extraction_id = :e "
                "AND scope = 'contribution'",
                e=ident,
            ) and self._quote_anchors(ident):
                up.append(("quote", f"{ident}/quote"))
            down += [
                ("relation", r)
                for r in self._column(
                    "SELECT relation_id FROM relations WHERE basis_item = :e", e=ident
                )
            ]
            down += [
                ("idea", i)
                for i in self._column("SELECT idea_id FROM ideas WHERE name_item = :e", e=ident)
            ]
        return up, down

    def _edges_claim(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all(
            "SELECT work_id, protocol_id, conversion_id, anchor, supersedes, superseded_by "
            "FROM extraction_claims WHERE claim_id = :c",
            c=ident,
        )
        up: list[Key] = []
        down: list[Key] = []
        if rows:
            work_id, protocol_id, conversion_id, anchor, supersedes, superseded_by = rows[0]
            up += [("work", str(work_id)), ("protocol", str(protocol_id))]
            up.append(("anchor", f"{conversion_id}/{anchor}"))
            up += self._full_text_decisions(str(work_id))
            if supersedes is not None:
                up.append(("claim", str(supersedes)))
            if superseded_by is not None:
                down.append(("claim", str(superseded_by)))
        return up, down

    def _edges_relation(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all(
            "SELECT source_work, target, basis_item, reference_extraction_id, supersedes, "
            "superseded_by FROM relations WHERE relation_id = :r",
            r=ident,
        )
        up: list[Key] = []
        down: list[Key] = []
        if rows:
            source, target, basis, rex, supersedes, superseded_by = rows[0]
            up.append(("work", str(source)))
            up.append(("idea" if str(target).startswith("ida_") else "work", str(target)))
            if basis is not None:
                up.append(("extraction", str(basis)))
            if rex is not None:
                up.append(("reference_extraction", str(rex)))
            if supersedes is not None:
                up.append(("relation", str(supersedes)))
            if superseded_by is not None:
                down.append(("relation", str(superseded_by)))
        return up, down

    def _edges_idea(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all(
            "SELECT name_item, origin, supersedes, superseded_by, merged_into FROM ideas "
            "WHERE idea_id = :i",
            i=ident,
        )
        up: list[Key] = []
        down: list[Key] = []
        if rows:
            name_item, origin, supersedes, superseded_by, merged_into = rows[0]
            up += [("extraction", str(name_item)), ("work", str(origin))]
            up += [
                ("work", w)
                for w in self._column(
                    "SELECT work_id FROM idea_members WHERE idea_id = :i ORDER BY work_id", i=ident
                )
            ]
            up += [
                ("idea", i)
                for i in self._column(
                    "SELECT idea_id FROM ideas WHERE merged_into = :i AND superseded_by IS NULL",
                    i=ident,
                )
            ]
            if supersedes is not None:
                up.append(("idea", str(supersedes)))
            if superseded_by is not None:
                down.append(("idea", str(superseded_by)))
            if merged_into is not None:
                down.append(("idea", str(merged_into)))
        down += [
            ("relation", r)
            for r in self._column("SELECT relation_id FROM relations WHERE target = :i", i=ident)
        ]
        return up, down

    def _edges_cites(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all(
            "SELECT e.reference_extraction_id, e.ordinal, e.target, x.conversion_id, n.anchor "
            "FROM graph_edges e "
            "LEFT JOIN reference_extractions x ON x.extraction_id = e.reference_extraction_id "
            "LEFT JOIN reference_entries n ON n.extraction_id = e.reference_extraction_id "
            "AND n.ordinal = e.ordinal WHERE e.edge_id = :i",
            i=ident,
        )
        up: list[Key] = []
        if rows:
            rex, _, target, conversion_id, anchor = rows[0]
            up += [("reference_extraction", str(rex)), ("work", str(target))]
            if anchor is not None and conversion_id is not None:
                up.append(("anchor", f"{conversion_id}/{anchor}"))
        return up, []

    def _edges_quote(self, ident: str) -> tuple[list[Key], list[Key]]:
        row_id = ident.removesuffix("/quote")
        up = [("anchor", a) for a in self._quote_anchors(row_id)]
        return up, [("extraction", row_id)]

    def _quote_anchors(self, extraction_id: str) -> list[str]:
        """The anchors of the quoted fields of a row, as anchor keys of its conversion."""
        return [
            f"{c}/{a}"
            for c, a in self._all(
                "SELECT DISTINCT r.conversion_id, f.anchor FROM extraction_rows r "
                "JOIN extraction_fields f ON f.extraction_id = r.extraction_id "
                "WHERE r.extraction_id = :e AND f.quote IS NOT NULL AND f.anchor IS NOT NULL "
                "ORDER BY f.anchor",
                e=extraction_id,
            )
        ]

    def _edges_cell(self, ident: str) -> tuple[list[Key], list[Key]]:
        row_key, field = _split_cell(ident)
        up: list[Key] = [
            ("extraction", e)
            for e in self._column(
                "SELECT r.extraction_id FROM extraction_rows r "
                "JOIN extraction_fields f ON f.extraction_id = r.extraction_id "
                "WHERE r.row_key = :k AND f.field = :f AND r.scope = 'evidence' "
                "ORDER BY r.event_id",
                k=row_key,
                f=field,
            )
        ]
        return up, []

    def _edges_decision(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all(
            "SELECT work_id, criterion, protocol_id, supersedes FROM decisions "
            "WHERE decision_id = :d",
            d=ident,
        )
        up: list[Key] = []
        if rows:
            work_id, criterion, protocol_id, supersedes = rows[0]
            up.append(("work", str(work_id)))
            if criterion is not None:
                up.append(("criterion", str(criterion)))
            up.append(("protocol", str(protocol_id)))
            if supersedes is not None:
                up.append(("decision", str(supersedes)))
            for conversion_id, anchor in self._all(
                "SELECT conversion_id, anchor FROM decisions WHERE decision_id = :d "
                "AND conversion_id IS NOT NULL AND anchor IS NOT NULL",
                d=ident,
            ):
                up.append(("anchor", f"{conversion_id}/{anchor}"))
        down: list[Key] = [
            ("decision", d)
            for d in self._column(
                "SELECT decision_id FROM decisions WHERE supersedes = :d", d=ident
            )
        ]
        down += [
            ("resolution", _res_key(str(st), str(w)))
            for st, w in self._all(
                "SELECT r.stage, r.work_id FROM resolutions r JOIN decisions d "
                "ON d.work_id = r.work_id AND d.stage = r.stage WHERE d.decision_id = :d",
                d=ident,
            )
        ]
        return up, down

    def _edges_resolution(self, ident: str) -> tuple[list[Key], list[Key]]:
        stage, work_id = _split_res(ident)
        up: list[Key] = [("work", work_id)]
        up += [
            ("criterion", c)
            for c in self._column(
                "SELECT criterion FROM resolutions "
                "WHERE work_id = :w AND stage = :s AND criterion IS NOT NULL",
                w=work_id,
                s=stage,
            )
        ]
        up += [
            ("decision", d)
            for d in self._column(
                "SELECT decision_id FROM decisions WHERE work_id = :w AND stage = :s",
                w=work_id,
                s=stage,
            )
        ]
        return up, []

    def _edges_audit(self, ident: str) -> tuple[list[Key], list[Key]]:
        if "/" in ident:
            audit_id, work_id = ident.split("/", 1)
            up: list[Key] = [("audit", audit_id), ("work", work_id)]
            up += [
                ("criterion", c)
                for c in self._column(
                    "SELECT criterion FROM audit_items "
                    "WHERE audit_id = :a AND work_id = :w AND criterion IS NOT NULL",
                    a=audit_id,
                    w=work_id,
                )
            ]
            return up, []
        down: list[Key] = [
            ("audit", f"{ident}/{w}")
            for w in self._column("SELECT work_id FROM audit_items WHERE audit_id = :a", a=ident)
        ]
        return [], down

    def _edges_seed(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("run", r)
            for r in self._column(
                "SELECT run_id FROM seeds WHERE seed_id = :s AND run_id IS NOT NULL "
                "UNION SELECT run_id FROM seed_admissions WHERE seed_id = :s",
                s=ident,
            )
        ]
        down: list[Key] = [
            ("work", w)
            for w in self._column(
                "SELECT work_id FROM seeds WHERE seed_id = :s AND work_id IS NOT NULL "
                "UNION SELECT work_id FROM seed_admissions "
                "WHERE seed_id = :s AND work_id IS NOT NULL",
                s=ident,
            )
        ]
        return up, down

    def _edges_inbox_item(self, ident: str) -> tuple[list[Key], list[Key]]:
        """An inbox item leads to the works its resolutions found (slice 4a)."""
        down: list[Key] = [
            ("work", w)
            for w in self._column(
                "SELECT DISTINCT work_id FROM inbox_resolutions "
                "WHERE item_id = :i AND work_id IS NOT NULL",
                i=ident,
            )
        ]
        return [], down

    def _edges_chase_round(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("work", w)
            for w in self._column(
                "SELECT j.value FROM chase_rounds r, json_each(r.from_works) j "
                "WHERE r.round_id = :c",
                c=ident,
            )
        ]
        up += [
            ("snowball_round", r)
            for r in self._column(
                "SELECT round_id FROM snowball_rounds WHERE chase_round_id = :c", c=ident
            )
        ]
        down: list[Key] = [("query", q) for q in self._chase_assignment()[1].get(ident, [])]
        return up, down

    def _edges_reference_extraction(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all(
            "SELECT work_id, conversion_id FROM reference_extractions WHERE extraction_id = :x",
            x=ident,
        )
        up: list[Key] = []
        down: list[Key] = []
        if rows:
            work_id, conversion_id = (str(v) for v in rows[0])
            up += [("conversion", conversion_id), ("work", work_id)]
            up += [
                ("decision", d)
                for d in self._column(
                    "SELECT decision_id FROM decisions WHERE work_id = :w", w=work_id
                )
            ]
            down += [
                ("anchor", f"{conversion_id}/{a}")
                for a in self._column(
                    "SELECT n.anchor FROM reference_entries n JOIN reference_links l "
                    "ON l.extraction_id = n.extraction_id AND l.ordinal = n.ordinal "
                    "WHERE n.extraction_id = :x AND l.state = 'resolved' ORDER BY n.ordinal",
                    x=ident,
                )
            ]
        down += [
            ("snowball_round", r)
            for r in self._column(
                "SELECT r.round_id FROM snowball_rounds r, json_each(r.extraction_ids) j "
                "WHERE j.value = :x",
                x=ident,
            )
        ]
        return up, down

    def _edges_snowball_round(self, ident: str) -> tuple[list[Key], list[Key]]:
        rows = self._all(
            "SELECT sources, extraction_ids, chase_round_id FROM snowball_rounds "
            "WHERE round_id = :r",
            r=ident,
        )
        up: list[Key] = []
        down: list[Key] = []
        if rows:
            sources, extractions, chase = rows[0]
            up += [("work", str(w)) for w in json.loads(str(sources))]
            up += [("reference_extraction", str(x)) for x in json.loads(str(extractions))]
            if chase is not None:
                down.append(("chase_round", str(chase)))
        down += [
            ("query", q)
            for q in self._column(
                "SELECT json_extract(e.refs, '$[0]') FROM events e "
                "WHERE e.type = 'query.registered' "
                "AND EXISTS (SELECT 1 FROM json_each(e.refs) j WHERE j.value = :r)",
                r=ident,
            )
        ]
        return up, down

    def _edges_import(self, ident: str) -> tuple[list[Key], list[Key]]:
        down: list[Key] = [
            ("query", q)
            for q in self._column(
                "SELECT json_extract(e.refs, '$[0]') FROM events e "
                "WHERE e.type = 'query.registered' "
                "AND EXISTS (SELECT 1 FROM json_each(e.refs) j WHERE j.value = :i)",
                i=ident,
            )
        ]
        down += [("run", r) for r in self._import_lookup_runs().get(ident, ())]
        return [], down

    def _edges_import_record(self, ident: str) -> tuple[list[Key], list[Key]]:
        import_id, ordinal = ident.rsplit(":", 1)
        up: list[Key] = [("import", import_id)]
        down: list[Key] = [
            ("work", w)
            for w in self._column(
                "SELECT work_id FROM import_records WHERE import_id = :i AND ordinal = :o "
                "AND link_state = 'resolved' AND work_id IS NOT NULL",
                i=import_id,
                o=int(ordinal),
            )
        ]
        return up, down


_EDGES: dict[str, Callable[[_Walk, str], tuple[list[Key], list[Key]]]] = {
    "question": _Walk._up_question,
    "element": _Walk._up_element,
    "criterion": _Walk._edges_criterion,
    "protocol": _Walk._edges_protocol,
    "query": _Walk._edges_query,
    "run": _Walk._edges_run,
    "page": _Walk._edges_page,
    "record": _Walk._edges_record,
    "merge": _Walk._edges_merge,
    "work": _Walk._edges_work,
    "attempt": _Walk._edges_attempt,
    "document": _Walk._edges_document,
    "conversion": _Walk._edges_conversion,
    "anchor": _Walk._edges_anchor,
    "decision": _Walk._edges_decision,
    "extraction": _Walk._edges_extraction,
    "claim": _Walk._edges_claim,
    "appraisal": _Walk._edges_appraisal,
    "relation": _Walk._edges_relation,
    "idea": _Walk._edges_idea,
    "cites": _Walk._edges_cites,
    "quote": _Walk._edges_quote,
    "cell": _Walk._edges_cell,
    "resolution": _Walk._edges_resolution,
    "audit": _Walk._edges_audit,
    "seed": _Walk._edges_seed,
    "chase_round": _Walk._edges_chase_round,
    "reference_extraction": _Walk._edges_reference_extraction,
    "snowball_round": _Walk._edges_snowball_round,
    "inbox_item": _Walk._edges_inbox_item,
    "import": _Walk._edges_import,
    "import_record": _Walk._edges_import_record,
    "notice": _Walk._edges_notice,
    "version": _Walk._edges_version,
    "preference": _Walk._edges_preference,
    "briefing": _Walk._edges_briefing,
    "served": _Walk._edges_served,
    "session": _Walk._edges_session,
}
