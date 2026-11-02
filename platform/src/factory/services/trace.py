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
- A reference that names no row is shown as a node with an empty `event_id`, so a broken link is
  visible rather than hidden.
- An identifier that names no row raises `FactoryValidationError([ValidationIssue("ref",
  "unknown id")])`; nothing is written.
"""

import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Event
from factory.events.reader import read_all
from factory.model.base import StrictModel
from factory.model.chase import CHASE_ROUND_ID_RE
from factory.model.dedup import MERGE_ID_RE
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.protocol import PROTOCOL_ID_RE, ProtocolSpec
from factory.model.question import QUESTION_ID_RE, QuestionSpec
from factory.model.screening import AUDIT_ID_RE, DECISION_ID_RE, QUALIFIED_CRITERION_RE
from factory.model.seed import SEED_ID_RE
from factory.model.work import QUERY_ID_RE, RUN_ID_RE
from factory.model.work_ids import WORK_ID_RE
from factory.services.context import Project

KINDS: tuple[str, ...] = (
    "question",
    "element",
    "criterion",
    "protocol",
    "query",
    "run",
    "page",
    "record",
    "merge",
    "work",
    "decision",
    "resolution",
    "audit",
    "seed",
    "chase_round",
)
"""Node kinds in chain order. Sibling nodes are listed in this order (reversed for back traces, so
the work branch of a decision comes before its cited criterion)."""

_RANK = {kind: rank for rank, kind in enumerate(KINDS)}
_NO_EVENT = ""
_MISSING = "no such row"

_ELEMENT_RE = r"^(Q@[0-9a-f]{8})/(slot:.+|NG\d{2})$"
_RECORD_RE = rf"^(run_{ULID_RE})/(rf:.+)$"
_AUDIT_ITEM_RE = rf"^(aud_{ULID_RE})/(rf:.+)$"
_RESOLUTION_RE = r"^res:(rf:.+)$"
_PATTERNS: tuple[tuple[str, str], ...] = (
    (QUESTION_ID_RE, "question"),
    (PROTOCOL_ID_RE, "protocol"),
    (QUALIFIED_CRITERION_RE, "criterion"),
    (_ELEMENT_RE, "element"),
    (QUERY_ID_RE, "query"),
    (RUN_ID_RE, "run"),
    (MERGE_ID_RE, "merge"),
    (DECISION_ID_RE, "decision"),
    (AUDIT_ID_RE, "audit"),
    (_AUDIT_ITEM_RE, "audit"),
    (CHASE_ROUND_ID_RE, "chase_round"),
    (SEED_ID_RE, "seed"),
    (BLOB_REF_RE, "page"),
    (WORK_ID_RE, "work"),
    (_RECORD_RE, "record"),
    (_RESOLUTION_RE, "resolution"),
)

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


def trace(
    project: Project, ref: str, *, direction: Literal["back", "forward"] = "back"
) -> TraceNode:
    """The chain from `ref`, as a tree rooted at that node.

    `back` follows the nodes `ref` was derived from, `forward` the nodes derived from it. The kind
    of `ref` is given by its prefix. Raises `FactoryValidationError` for an identifier that names
    no row.

    Each node is shown once, under the first branch that reaches it (a visited set). So a back
    trace from a decision claims the protocol and the question under the work branch (through the
    query), and the criterion branch may then end at the element. Criteria lead upward to their
    protocol and element, never to queries: queries are downstream of protocols.
    """
    if direction not in ("back", "forward"):
        raise ValueError(f"direction must be 'back' or 'forward', not {direction!r}")
    key = _parse(ref)
    project.index.sync()
    with project.index.connect() as conn:
        walk = _Walk(project, conn)
        described = None if key is None else walk.describe(key)
        if key is None or described is None:
            raise FactoryValidationError([ValidationIssue("ref", "unknown id")])
        return _build(walk, key, described, direction, {key})


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


def _parse(ref: str) -> Key | None:
    for pattern, kind in _PATTERNS:
        if re.fullmatch(pattern, ref):
            return (kind, ref)
    return None


def _build(
    walk: "_Walk", key: Key, described: _Described | None, direction: str, visited: set[Key]
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
            if neighbour in visited:
                continue
            visited.add(neighbour)
            children.append(_build(walk, neighbour, walk.describe(neighbour), direction, visited))
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

    def __init__(self, project: Project, conn: Connection) -> None:
        self._project = project
        self._conn = conn
        self._questions: dict[str, _QuestionRow] | None = None
        self._protocols: dict[str, _ProtocolRow] | None = None
        self._scanned: dict[tuple[str, str], str] | None = None
        self._chase: tuple[dict[str, str], dict[str, list[str]]] | None = None
        self._describers: dict[str, Callable[[str], _Described | None]] = {
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
            "decision": self._decision,
            "resolution": self._resolution,
            "audit": self._audit,
            "seed": self._seed,
            "chase_round": self._chase_round,
        }

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

        A query belongs to the latest round, recorded before the query, whose text it ran. Both
        identifiers are time-ordered ULIDs, so the comparison is on their ULID parts.

        Assumption: `chase.round_started` is recorded before the round's queries are registered
        (`services.chase.search_chase` does this). Two rounds with identical texts are then told
        apart by order: each query links to the latest earlier round, never to a later one.
        """
        if self._chase is None:
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
                earlier = [
                    round_id
                    for round_id in rounds.get(str(query_text), [])
                    if round_id[len("chs_") :] < str(query_id)[len("qry_") :]
                ]
                if earlier:
                    chosen = max(earlier)
                    query_round[str(query_id)] = chosen
                    round_queries.setdefault(chosen, []).append(str(query_id))
            self._chase = (query_round, round_queries)
        return self._chase

    # --- Describing one node ---

    def describe(self, key: Key) -> _Described | None:
        """The label and creating event of a node, or None when no row names it."""
        return self._describers[key[0]](key[1])

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

    def _page(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT ordinal FROM pages WHERE raw_blob = :b ORDER BY run_id, ordinal LIMIT 1",
            b=ident,
        )
        if not rows:
            return None
        label = f"archived raw page, ordinal {rows[0][0]}"
        return _Described(label, self._event_for("search.page_archived", ident))

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
            return None
        title = json.loads(str(rows[0][0]))["title"]
        return _Described(str(title), str(rows[0][1]))

    def _decision(self, ident: str) -> _Described | None:
        rows = self._all(
            "SELECT pass_label, phase, verdict, criterion, superseded_by, event_id "
            "FROM decisions WHERE decision_id = :d",
            d=ident,
        )
        if not rows:
            return None
        pass_label, phase, verdict, criterion, superseded_by, event_id = rows[0]
        label = f"pass {pass_label}, {phase}: {verdict}"
        if criterion is not None:
            label += f" under {str(criterion).rsplit(':', 1)[-1]}"
        if superseded_by is not None:
            label += " (superseded)"
        return _Described(label, str(event_id))

    def _resolution(self, ident: str) -> _Described | None:
        work_id = ident[len("res:") :]
        rows = self._all(
            "SELECT verdict, criterion, event_id FROM resolutions WHERE work_id = :w", w=work_id
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

    # --- Neighbours: upstream (derived from) and downstream (derived into) ---

    def edges(self, key: Key) -> tuple[list[Key], list[Key]]:
        """The upstream and downstream neighbours of a node, as keys. A key may name no row; the
        walk shows such a key as a missing node."""
        kind, ident = key
        handler = _EDGES[kind]
        return handler(self, ident)

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
            ("resolution", f"res:{w}")
            for w in self._column("SELECT work_id FROM resolutions WHERE criterion = :c", c=ident)
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
        down: list[Key] = [
            ("run", r) for r in self._column("SELECT run_id FROM runs WHERE query_id = :q", q=ident)
        ]
        return up, down

    def _edges_run(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("query", q)
            for q in self._column("SELECT query_id FROM runs WHERE run_id = :r", r=ident)
        ]
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
                "SELECT run_id, work_id FROM provenance WHERE raw_blob = :b", b=ident
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
            for r in self._column("SELECT run_id FROM provenance WHERE work_id = :w", w=ident)
        ]
        up += [
            ("merge", m)
            for m in self._column('SELECT merge_id FROM merges WHERE "primary" = :w', w=ident)
        ]
        up += [
            ("seed", s)
            for s in self._column(
                "SELECT seed_id FROM seeds WHERE work_id = :w "
                "UNION SELECT seed_id FROM seed_admissions WHERE work_id = :w",
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
            ("decision", d)
            for d in self._column("SELECT decision_id FROM decisions WHERE work_id = :w", w=ident)
        ]
        down += [
            ("resolution", f"res:{w}")
            for w in self._column("SELECT work_id FROM resolutions WHERE work_id = :w", w=ident)
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
        return up, down

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
        down: list[Key] = [
            ("decision", d)
            for d in self._column(
                "SELECT decision_id FROM decisions WHERE supersedes = :d", d=ident
            )
        ]
        down += [
            ("resolution", f"res:{w}")
            for w in self._column(
                "SELECT r.work_id FROM resolutions r JOIN decisions d ON d.work_id = r.work_id "
                "WHERE d.decision_id = :d",
                d=ident,
            )
        ]
        return up, down

    def _edges_resolution(self, ident: str) -> tuple[list[Key], list[Key]]:
        work_id = ident[len("res:") :]
        up: list[Key] = [("work", work_id)]
        up += [
            ("criterion", c)
            for c in self._column(
                "SELECT criterion FROM resolutions WHERE work_id = :w AND criterion IS NOT NULL",
                w=work_id,
            )
        ]
        up += [
            ("decision", d)
            for d in self._column("SELECT decision_id FROM decisions WHERE work_id = :w", w=work_id)
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

    def _edges_chase_round(self, ident: str) -> tuple[list[Key], list[Key]]:
        up: list[Key] = [
            ("work", w)
            for w in self._column(
                "SELECT j.value FROM chase_rounds r, json_each(r.from_works) j "
                "WHERE r.round_id = :c",
                c=ident,
            )
        ]
        down: list[Key] = [("query", q) for q in self._chase_assignment()[1].get(ident, [])]
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
    "decision": _Walk._edges_decision,
    "resolution": _Walk._edges_resolution,
    "audit": _Walk._edges_audit,
    "seed": _Walk._edges_seed,
    "chase_round": _Walk._edges_chase_round,
}
