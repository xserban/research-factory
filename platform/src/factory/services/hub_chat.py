"""Payload and researcher acts of the hub Chat page (night feature N5; ruling 8: an agent proposes,
the researcher rates and writes the balance).

Invariants:
- Reads write nothing and call no model. Every count is computed from the folded rows; the balance
  is never computed, only shown (the researcher's own text, or an empty box).
- The basket is a `SelectionSpec` (layers, include, exclude) resolved through `selection`: works
  with their titles and `est_tokens`, and the works left out with the reason.
- A sheet or answer view shows, for every quote, the FULL paragraph of its anchor read from the
  conversion the quote was verified against, and `mark`, the quote's span in the shown text (or
  None). An unreadable conversion gives an empty paragraph, never a guessed one. The balance comes
  before the arguments in the payload: the researcher's text first, or an empty box.
- Request state is the one `chat_requests` derives (`open`, `taken`, `done`, `failed`), with the
  run state of the taking run when there is one.
- The acts (`order_chat`, `rate_argument_act`, `rate_sentence_act`, `balance_act`) are the
  researcher's: the caller supplies a human actor, the services refuse any other, and each act
  validates its body first and writes nothing on invalid input. The hub starts the run of a new
  request through the runner (`runner.start_run`, decision 119); a refused start keeps the request
  and returns the command that starts it by hand.
"""

from __future__ import annotations

import copy
import logging
import threading
from typing import TYPE_CHECKING, Any, Final

from factory.document.quotes import quote_span
from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.mining.spec import Population
from factory.services import answers as answers_service
from factory.services import chat_requests
from factory.services import runner as runner_service
from factory.services import sheets as sheets_service
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.mining import population_works
from factory.services.search import get_work
from factory.services.selection import (
    SelectionSpec,
    event_log_signature,
    resolve_selection,
    resolve_selection_cached,
)

_LOG: Final = logging.getLogger(__name__)

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

__all__ = [
    "answer_view",
    "balance_act",
    "basket_payload",
    "build",
    "chat_payload",
    "live",
    "order_chat",
    "parse_spec",
    "rate_argument_act",
    "rate_sentence_act",
    "sheet_view",
]

METHODS: dict[str, str] = {
    "basket": (
        "The papers a chat reads: the layers you pick, plus the papers you add, minus the papers "
        "you remove. The size is the characters of each paper's stored text divided by four."
    ),
    "proposal": (
        "An agent proposes every argument and sentence below and quotes the paper; the platform "
        "checked each quote against its paragraph. A verified quote is not a verified reading. "
        "Nothing is a verdict until you rate it, and the balance is yours to write."
    ),
}
_REQUEST_FIELDS = ("kind", "hypothesis", "question", "mode", "parent", "note", "selection")
_RUNS_SHOWN = 200


def _issue(field: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, message)])


# ---------------------------------------------------------------- the basket


def _csv(value: object) -> list[str]:
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def parse_spec(query: dict[str, str]) -> tuple[SelectionSpec, bool]:
    """The basket from query values `layers`, `include` and `exclude` (comma lists) and `only`
    (`1`: the papers listed in `include` and nothing else)."""
    spec = SelectionSpec(
        layers=_csv(query.get("layers")),
        include=_csv(query.get("include")),
        exclude=_csv(query.get("exclude")),
    )
    return spec, query.get("only") == "1"


def narrow(project: Project, spec: SelectionSpec) -> SelectionSpec:
    """The open-form "only the papers in `include`": every population work not listed excluded
    explicitly. Used for the UI's count of papers not picked only; the recorded spec for "only
    these papers" is the closed form (`closed` true, `include`), which a later work cannot enter."""
    keep = set(spec.include)
    out = set(spec.exclude)
    for work in population_works(project, spec.population):
        if work not in keep:
            out.add(work)
    return spec.model_copy(update={"exclude": sorted(out)})


def _title(project: Project, work_id: str) -> str:
    found = get_work(project, work_id)
    return "" if found is None else str(found.title)


def basket_payload(project: Project, spec: SelectionSpec, only: bool = False) -> dict[str, Any]:
    """The works a chat with `spec` would read, with titles and token estimates. With `only` the
    basket is the listed `include` papers and nothing else (see `narrow`); the papers not picked
    are counted, not listed. Read-only; `FactoryValidationError` for an unknown layer or work id."""
    shown = spec
    if only:
        spec = spec.model_copy(update={"closed": True})
    chosen = resolve_selection_cached(project, spec)
    asked = set(shown.exclude)
    works = [
        {
            "work_id": w.work_id,
            "title": _title(project, w.work_id),
            "chars": w.chars,
            "est_tokens": w.chars // 4,
        }
        for w in chosen.works
    ]
    return {
        "spec": {
            "layers": shown.layers,
            "include": shown.include,
            "exclude": shown.exclude,
            "closed": spec.closed,
        },
        "only": only,
        "count": len(works),
        "works": works,
        "left_out": [
            {"work_id": w, "title": _title(project, w), "reason": why} for w, why in chosen.excluded
        ],
        "not_picked": len(set(narrow(project, shown).exclude) - asked) if only else 0,
        "chars": chosen.chars,
        "est_tokens": chosen.est_tokens,
        "digest": chosen.digest,
        "method": METHODS["basket"],
    }


# ---------------------------------------------------------------- requests and lists


def _requests(project: Project) -> list[chat_requests.ChatRequestInfo]:
    return chat_requests.list_requests(project)


def _run_states(project: Project) -> dict[str, dict[str, Any]]:
    """The runs of the project by id (status as `runner.run_status` names it). Reads only."""
    return {
        r.run_id: {"run_id": r.run_id, "status": r.status, "exit_status": r.exit_status}
        for r in runner_service.run_status(project, reconcile=False, limit=_RUNS_SHOWN)
    }


def _request_row(
    r: chat_requests.ChatRequestInfo, runs: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    run = runs.get(r.taken_run) if r.taken_run else None
    return {
        "request_id": r.request_id,
        "kind": r.kind,
        "hypothesis": r.hypothesis,
        "question": r.question,
        "mode": r.mode,
        "parent": r.parent,
        "note": r.note,
        "state": r.state,
        "result": r.result,
        "taken_run": r.taken_run,
        "run": None
        if run is None
        else {"status": run["status"], "exit_status": run["exit_status"]},
        "selection": r.selection,
        "ts": r.ts,
    }


_LISTS: dict[str, tuple[tuple[int, float], tuple[list[dict[str, Any]], list[dict[str, Any]]]]] = {}
_LISTS_LOCK = threading.Lock()
_LISTS_KEPT = 8


def _lists(project: Project) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The sheet and answer rows of the page, reused while the event log is unchanged (the key is
    the log signature, as `resolve_selection_cached` uses; any appended event ends it). The request
    rows and their run states are not cached: a run's state changes without an event."""
    key = str(project.paths.dir)
    signature = event_log_signature(project)
    with _LISTS_LOCK:
        hit = _LISTS.get(key)
        if hit is not None and hit[0] == signature:
            return copy.deepcopy(hit[1])
    infos = _requests(project)
    pending = {r.parent for r in infos if r.parent and r.state in ("open", "taken")}
    sheets = []
    for s in reversed(sheets_service.list_sheets(project)):
        view = sheets_service.view_sheet(project, s.sheet_id)
        sheets.append(
            {
                "sheet_id": s.sheet_id,
                "hypothesis": s.hypothesis,
                "mode": s.mode,
                "against_closed": s.against_closed,
                "for_closed": s.for_closed,
                "arguments": s.arguments,
                "unrated": view.coverage.unrated,
                "has_balance": view.balance is not None,
                "supersedes": s.supersedes,
                "ts": s.ts,
                "case_for_available": (
                    s.mode == "prepare"
                    and s.against_closed
                    and not s.for_closed
                    and s.sheet_id not in pending
                ),
            }
        )
    answers = [
        {
            "answer_id": a.answer_id,
            "question": a.question,
            "sentences": a.sentences,
            "parent": a.parent,
            "ts": a.ts,
        }
        for a in reversed(answers_service.list_answers(project))
    ]
    with _LISTS_LOCK:
        _LISTS.pop(key, None)
        _LISTS[key] = (signature, (sheets, answers))
        while len(_LISTS) > _LISTS_KEPT:
            del _LISTS[next(iter(_LISTS))]
    return copy.deepcopy((sheets, answers))


def chat_payload(project: Project) -> dict[str, Any]:
    """The Chat page data: requests (newest first, by state), earlier sheets and answers (newest
    first) and computed counts. The sheet and answer rows are cached on the event-log signature
    (`_lists`); the requests and their run states are read each time."""
    runs = _run_states(project)
    requests = [_request_row(r, runs) for r in reversed(_requests(project))]
    sheets, answers = _lists(project)
    counts = {
        s: sum(1 for r in requests if r["state"] == s) for s in ("open", "taken", "done", "failed")
    }
    return {
        "ready": True,
        "methods": dict(METHODS),
        "counts": {**counts, "sheets": len(sheets), "answers": len(answers)},
        "requests": requests,
        "sheets": sheets,
        "answers": answers,
    }


# ---------------------------------------------------------------- views


def _paragraph(
    project: Project, conversion: str, anchor: str, quote: str, cache: dict[str, Any]
) -> tuple[str, list[int] | None]:
    """The anchor's paragraph (normalised plain text) and the quote's span in it."""
    if conversion not in cache:
        try:
            cache[conversion] = conversion_manifest(project, conversion)
        except FactoryError:  # a damaged or missing conversion reads as no paragraph
            cache[conversion] = None
    manifest = cache[conversion]
    element = None if manifest is None else manifest.get(anchor)
    if element is None:
        return "", None
    shown, span = quote_span(str(element.text), quote)
    return shown, None if span is None else list(span)


def _claim(linked: Any) -> dict[str, Any] | None:
    if linked is None:
        return None
    return {
        "claim_type": linked.claim_type,
        "about": linked.about,
        "quote": linked.quote,
        "version": linked.version,
    }


def sheet_view(project: Project, sheet_id: str) -> dict[str, Any]:
    """One sheet for the page: the researcher's balance first (or an empty box), then the
    arguments, each with quote, full paragraph, linked claim and rating. Read-only."""
    view = sheets_service.view_sheet(project, sheet_id)
    cache: dict[str, Any] = {}
    arguments = []
    for a in view.arguments:
        shown, mark = _paragraph(project, a.conversion_id, a.anchor, a.quote, cache)
        arguments.append(
            {
                "argument_id": a.argument_id,
                "stance": a.stance,
                "work_id": a.work_id,
                "title": _title(project, a.work_id),
                "anchor": a.anchor,
                "quote": a.quote,
                "paragraph": shown,
                "mark": mark,
                "claim": a.claim,
                "strength": a.strength,
                "model": a.model,
                "rating": a.rating,
                "rating_note": a.rating_note or "",
                "linked_claim": _claim(a.linked_claim),
            }
        )
    b = view.balance
    both = view.info.against_closed and view.info.for_closed
    cov = view.coverage
    return {
        "kind": "sheet",
        "sheet_id": sheet_id,
        "hypothesis": view.info.hypothesis,
        "mode": view.info.mode,
        "balance": {
            "recorded": b is not None,
            "text": "" if b is None else b.text,
            "lean": None if b is None else b.lean,
            "note": None if b is None else b.note,
            "ts": None if b is None else b.ts,
            "writable": both,
            "history": view.balance_history,
        },
        "balance_label": view.balance_label,
        "against_closed": view.info.against_closed,
        "for_closed": view.info.for_closed,
        "counts": {
            "arguments": len(arguments),
            "against": cov.arguments.get("against", 0),
            "for": cov.arguments.get("for", 0),
            "ratings": dict(cov.ratings),
            "unrated": cov.unrated,
            "candidates": cov.total,
        },
        "arguments": arguments,
        "selection": view.selection,
        "method": METHODS["proposal"],
    }


def answer_view(project: Project, answer_id: str) -> dict[str, Any]:
    """One answer for the page: each sentence with quote, full paragraph and rating, and the
    answer's own rating. Read-only."""
    view = answers_service.view_answer(project, answer_id)
    cache: dict[str, Any] = {}
    sentences = []
    for s in view.sentences:
        shown, mark = _paragraph(project, s.conversion_id, s.anchor, s.quote, cache)
        sentences.append(
            {
                "index": s.index,
                "text": s.text,
                "work_id": s.work_id,
                "title": _title(project, s.work_id),
                "anchor": s.anchor,
                "quote": s.quote,
                "paragraph": shown or s.paragraph,
                "mark": mark,
                "rating": s.rating,
                "rating_note": s.rating_note or "",
            }
        )
    return {
        "kind": "answer",
        "answer_id": answer_id,
        "question": view.info.question,
        "rating": view.rating,
        "rating_note": view.rating_note or "",
        "unanswered": view.unanswered,
        "rating_label": view.rating_label,
        "counts": {
            "sentences": view.counts.sentences,
            "works": view.counts.works,
            "ratings": dict(view.counts.ratings),
            "unrated": view.counts.unrated,
        },
        "sentences": sentences,
        "selection": view.selection,
        "method": METHODS["proposal"],
    }


def live(project: Project, query: dict[str, str]) -> dict[str, Any]:
    """The read route `GET ui/chat`: `?basket=1&layers=&include=&exclude=` the basket, `?sheet=`
    or `?answer=` one view, else the page lists. Raises `FactoryValidationError` (400)."""
    if query.get("sheet"):
        return sheet_view(project, query["sheet"])
    if query.get("answer"):
        return answer_view(project, query["answer"])
    if query.get("basket"):
        spec, only = parse_spec(query)
        return basket_payload(project, spec, only)
    return chat_payload(project)


def build(ctx: HubContext) -> dict[str, Any]:
    """The payload of the `chat` page."""
    return chat_payload(ctx.project)


# ---------------------------------------------------------------- the researcher's acts


def _text(body: dict[str, Any], key: str, issues: list[ValidationIssue]) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        issues.append(ValidationIssue(key, "must be text"))
        return None
    return value


def _spec_of(body: dict[str, Any], issues: list[ValidationIssue]) -> SelectionSpec:
    raw = body.get("selection", {})
    if not isinstance(raw, dict):
        issues.append(ValidationIssue("selection", "must be an object"))
        return SelectionSpec()
    lists: dict[str, list[str]] = {}
    for key in ("layers", "include", "exclude"):
        value = raw.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            issues.append(ValidationIssue(f"selection.{key}", "must be a list of text"))
            value = []
        lists[key] = list(value)
    closed = raw.get("closed", False)
    if not isinstance(closed, bool):
        issues.append(ValidationIssue("selection.closed", "must be true or false"))
        closed = False
    population = raw.get("population")
    if population is None:
        return SelectionSpec(**lists, closed=closed)
    try:
        return SelectionSpec(**lists, closed=closed, population=Population(population))
    except ValueError:
        issues.append(ValidationIssue("selection.population", "not a known population"))
        return SelectionSpec(**lists, closed=closed)


def order_chat(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """Record the researcher's spar or ask (`chat.requested`) and start its headless run.

    `body`: `kind`, `hypothesis` or `question`, `mode`, `parent`, `note`, `selection` and `start`
    (default true). Raises `FactoryValidationError` (nothing written) for a bad body, an unknown
    layer or work in the selection, or what `request_chat` refuses. When the run cannot start
    (another run is open, no `claude` on PATH) the request stays recorded: `run_id` is None and
    `run_error` and `command` say how to start it."""
    issues: list[ValidationIssue] = []
    kind = _text(body, "kind", issues)
    texts = {
        k: _text(body, k, issues) for k in ("hypothesis", "question", "mode", "parent", "note")
    }
    spec = _spec_of(body, issues)
    only = (
        body.get("selection", {}).get("only", False)
        if isinstance(body.get("selection"), dict)
        else False
    )
    if not isinstance(only, bool):
        issues.append(ValidationIssue("selection.only", "must be true or false"))
        only = False
    start = body.get("start", True)
    if not isinstance(start, bool):
        issues.append(ValidationIssue("start", "must be true or false"))
    if kind is None and not issues:
        issues.append(ValidationIssue("kind", "must be spar or ask"))
    if issues:
        raise FactoryValidationError(issues)
    assert kind is not None
    if only:
        spec = spec.model_copy(update={"closed": True})
    # an unknown layer or work is refused before anything is written
    chosen = resolve_selection(project, spec)
    if not chosen.works:
        raise FactoryValidationError(
            [ValidationIssue("selection", "the selection resolves to no papers; pick some")]
        )
    with project.index.exclusive():  # the duplicate check and the record are one step
        _refuse_duplicate(project, kind, chosen.digest, texts)
        payload = chat_requests.request_chat(project, actor, kind, spec, **texts)
    out: dict[str, object] = {"request_id": payload.request_id, "kind": kind, "run_id": None}
    if start is False:
        return out
    try:
        out["run_id"] = runner_service.start_run(project, kind)
    except FactoryError as exc:
        out["run_error"] = "; ".join(i.reason for i in getattr(exc, "issues", [])) or str(exc)
        out["command"] = f"factory queue process --stage {kind}"
    except Exception as exc:  # the request is recorded; whatever went wrong starting the run
        _LOG.warning("chat run did not start: %r", exc, exc_info=True)
        out["run_error"] = str(exc) or type(exc).__name__
        out["command"] = f"factory queue process --stage {kind}"
    return out


def _refuse_duplicate(
    project: Project, kind: str, digest: str, texts: dict[str, str | None]
) -> None:
    """A second waiting or running request with the same kind, selection digest and text (a double
    click) is refused on field `request`; nothing is written."""
    wanted = ((texts["hypothesis"] if kind == "spar" else texts["question"]) or "").strip()
    for info in _requests(project):
        if info.state not in ("open", "taken") or info.kind != kind:
            continue
        had = ((info.hypothesis if kind == "spar" else info.question) or "").strip()
        if had != wanted:
            continue
        try:
            same = resolve_selection_cached(project, SelectionSpec.model_validate(info.selection))
        except (FactoryValidationError, ValueError):
            continue
        if same.digest == digest:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "request",
                        f"the same order is already waiting or running ({info.request_id})",
                    )
                ]
            )


def _required(body: dict[str, Any], key: str, issues: list[ValidationIssue]) -> str:
    value = _text(body, key, issues)
    if value is None or not value.strip():
        if not any(i.field == key for i in issues):
            issues.append(ValidationIssue(key, "required"))
        return ""
    return value


def rate_argument_act(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """The researcher's rating of one sheet argument (`sheet.argument_rated`)."""
    issues: list[ValidationIssue] = []
    argument_id = _required(body, "argument_id", issues)
    rating = _required(body, "rating", issues)
    note = _text(body, "note", issues) or ""
    if issues:
        raise FactoryValidationError(issues)
    sheets_service.rate_argument(project, actor, argument_id, rating, note)
    return {"argument_id": argument_id, "rating": rating}


def rate_sentence_act(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """The researcher's rating of one answer sentence, or of the whole answer when `sentence` is
    absent (`chat.answer_rated`)."""
    issues: list[ValidationIssue] = []
    answer_id = _required(body, "answer_id", issues)
    rating = _required(body, "rating", issues)
    note = _text(body, "note", issues) or ""
    sentence = body.get("sentence")
    if sentence is not None and (isinstance(sentence, bool) or not isinstance(sentence, int)):
        issues.append(ValidationIssue("sentence", "must be a whole number"))
    if issues:
        raise FactoryValidationError(issues)
    answers_service.rate_answer(project, actor, answer_id, rating, note, sentence=sentence)
    return {"answer_id": answer_id, "sentence": sentence, "rating": rating}


def balance_act(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """The researcher's written balance of a sheet (`sheet.balance_recorded`): text, optional
    lean and note. Nothing computes or suggests it."""
    issues: list[ValidationIssue] = []
    sheet_id = _required(body, "sheet_id", issues)
    balance = _required(body, "text", issues)
    lean = _text(body, "lean", issues)
    note = _text(body, "note", issues)
    if issues:
        raise FactoryValidationError(issues)
    sheets_service.record_balance(project, actor, sheet_id, balance, lean, note)
    return {"sheet_id": sheet_id}
