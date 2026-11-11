"""Recorded pages: the brief a model-written page is written from, the mechanical check, recording
and reading (plan site-hub, step 4).

The platform never calls a model. A page about the corpus (a synthesis of a technique, a stage, a
field or the whole corpus) is written in an agent session from a **brief** the platform computes
deterministically (statistics and a digest of quoted rows), then **recorded**. Recording runs the
check below and refuses a page that fails it:

- every `[[works/<slug>]]` names a work of the corpus;
- every quotation (double quotes, 12 characters or more) is verbatim from a recorded quote of a work
  cited in the same sentence, and has such a citation;
- every number is one of the brief's statistics, a year of the digest, or inside a quotation.

A generalisation with no number or citation is not refused but **flagged**, and the flags are
recorded with the page. The page is an interpretation, labelled model-written wherever it is shown.
It is stale when the brief it was written from has changed (new rows, a revised classification).

The event is `page.recorded` (`model.pages`); the page text, the brief's fingerprint and the check
result are in its input blob. Nothing here writes an index table.
"""

from __future__ import annotations

import collections
import hashlib
import re
from dataclasses import dataclass
from typing import Any

from pydantic import Field, JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.pages import SCOPE_RE, PageRecorded
from factory.services.context import Project
from factory.services.site_corpus import corpus_payload

MIN_QUOTE_CHARS = 12
MAX_BODY_CHARS = 30_000
DIGEST_BUDGET = 110_000
MAX_QUOTE_SHOWN = 220
PART_CHARS = 24_000
"""One part of a brief returned to an agent: a tool result must stay within the agent's limit."""
QUOTE_PRIORITY: tuple[tuple[str, str, str], ...] = (
    ("sum", "core_innovation", "innovation"),
    ("cls", "technique_primary", "technique"),
    ("sum", "headline_result", "result"),
    ("sum", "limitations", "limitation"),
    ("map", "human_position", "human"),
    ("sum", "builds_on", "builds on"),
    ("desc", "contribution", "contribution"),
)
RULES = """RULES
1. Every sentence that states something about papers ends with one or more citations of the form
   [[works/<slug>]] copied from the DIGEST, at most four per sentence.
2. A quotation is copied character for character from the quotes shown under the cited work in the
   DIGEST, in double quotes, at most 30 words. Do not quote a title.
3. Numbers: only numbers that appear in the STATS block (state counts as given; do not compute
   shares or round), years that appear in the DIGEST, or numbers inside a quotation you cite.
4. Use no outside knowledge about any paper. If the digest does not show something, say that the
   corpus record does not show it.
5. Where papers differ, say so; do not average or smooth.
6. Plain Markdown, about 500 to 800 words, sections: Summary, How the systems work, Where and for
   whom, Evidence and evaluation, Open questions the corpus leaves. Begin with "# <label>".
7. A sentence with a generalisation (most, few, often) needs a number from STATS or a citation."""


class PageIssue(StrictModel):
    kind: str
    detail: str
    sentence: str


class PageCheck(StrictModel):
    words: int
    cited_sentences: int
    quotes_checked: int
    numbers_checked: int
    stats_sentences: int
    errors: list[PageIssue] = Field(default_factory=list)
    flags: list[PageIssue] = Field(default_factory=list)


class PageInfo(StrictModel):
    page_id: str
    kind: str
    scope: str
    title: str
    recorded_at: str
    actor_kind: str
    model: str | None
    skill: str | None
    flags: int
    stale: bool
    superseded: bool
    supersedes: str | None
    words: int


@dataclass(frozen=True)
class Context:
    scope: str
    label: str
    works: list[dict[str, Any]]
    stats: str
    stat_numbers: frozenset[str]
    digest: str
    quote_text: dict[str, str]
    fingerprint: str


def _issue(field: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, message)])


def _val(w: dict[str, Any], role: str, field: str) -> str:
    return str((w[role].get(field) or {}).get("v", ""))


def subset(payload: dict[str, Any], scope: str) -> tuple[list[dict[str, Any]], str]:
    """The works of a scope and its label."""
    if not re.match(SCOPE_RE, scope):
        raise _issue("scope", "use overview, technique=<value>, stage=<value> or field=<value>")
    works: list[dict[str, Any]] = payload["works"]
    if scope == "overview":
        return works, "the whole corpus"
    kind, value = scope.split("=", 1)
    if kind == "technique":
        rows = [
            w
            for w in works
            if value in (_val(w, "cls", "technique_primary"), _val(w, "cls", "technique_secondary"))
        ]
        label = f"technique {value}"
    elif kind == "stage":
        rows = [w for w in works if any(s["stage"] == value for s in w["stages"])]
        label = f"lifecycle stage {value}"
    else:
        rows = [w for w in works if _val(w, "cls", "field_primary") == value]
        label = f"field of science {value}"
    if not rows:
        raise _issue("scope", f"no work matches {scope}")
    return rows, label


def _counter(works: list[dict[str, Any]], fn: Any) -> collections.Counter[str]:
    c: collections.Counter[str] = collections.Counter()
    for w in works:
        r = fn(w)
        for x in r if isinstance(r, list) else [r]:
            if x:
                c[x] += 1
    return c


def _stats(works: list[dict[str, Any]], total: int) -> str:
    defs: dict[str, Any] = {
        "field of science": lambda w: _val(w, "cls", "field_primary"),
        "technique (primary)": lambda w: _val(w, "cls", "technique_primary"),
        "data": lambda w: _val(w, "cls", "data_primary"),
        "architecture": lambda w: _val(w, "cls", "architecture_primary"),
        "evaluation": lambda w: _val(w, "cls", "evaluation_primary"),
        "human position": lambda w: _val(w, "map", "human_position"),
        "process shape": lambda w: _val(w, "map", "process_shape"),
        "automated span": lambda w: _val(w, "map", "automated_span"),
        "idea assessment method": lambda w: _val(w, "map", "idea_assessment_method"),
        "contribution type": lambda w: _val(w, "sum", "contribution_type"),
        "validation level": lambda w: _val(w, "sum", "validation_level"),
        "claimed discovery": lambda w: _val(w, "sum", "claimed_discovery"),
        "availability": lambda w: _val(w, "sum", "availability"),
        "stages covered (any mode)": lambda w: sorted({s["stage"] for s in w["stages"]}),
        "stages automated": lambda w: sorted(
            {s["stage"] for s in w["stages"] if s["mode"] == "automated"}
        ),
        "month of publication": lambda w: w["month"],
    }
    lines = [f"Works in this subset: {len(works)} of {total} in the corpus."]
    for name, fn in defs.items():
        c = _counter(works, fn)
        if c:
            lines.append(f"- {name}: " + "; ".join(f"{a} {b}" for a, b in c.most_common(12)))
    return "\n".join(lines)


def _digest(works: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    """The digest text and, per work, all recorded quote text (what a quotation is checked on)."""
    lines: list[str] = []
    check_text: dict[str, str] = {}
    share = DIGEST_BUDGET // max(1, len(works))
    for w in sorted(works, key=lambda x: x["published"]):
        stages = ", ".join(f"{s['stage']}({s['mode']})" for s in w["stages"])
        head = (
            f"[[works/{w['slug']}]] | {w['month']} | {w['title'][:100]} | field "
            f"{_val(w, 'cls', 'field_primary')} | human {_val(w, 'map', 'human_position')} | "
            f"process {_val(w, 'map', 'process_shape')} | stages {stages}"
        )
        room = share - len(head)
        quotes: list[str] = []
        for role, field, label in QUOTE_PRIORITY:
            o = w[role].get(field)
            if not o or not o["q"] or room < 60:
                continue
            shown = o["q"][: min(MAX_QUOTE_SHOWN, room - 20)]
            quotes.append(f'    {label}: "{shown}"')
            room -= len(shown) + len(label) + 8
        lines.append("\n".join([head, *quotes]))
        pieces = [o["q"] for r in ("cls", "map", "sum", "desc") for o in w[r].values() if o["q"]]
        pieces += [s["quote"] for s in w["stages"] if s["quote"]]
        check_text[w["slug"]] = " ".join([*pieces, w["title"]])
    return "\n".join(lines), check_text


def context(project: Project, scope: str, payload: dict[str, Any] | None = None) -> Context:
    """The brief of a scope, computed from the recorded rows."""
    data = payload or corpus_payload(project)
    works, label = subset(data, scope)
    stats = _stats(works, len(data["works"]))
    digest, quote_text = _digest(works)
    fp = hashlib.sha256((stats + "\n" + digest).encode()).hexdigest()[:16]
    return Context(
        scope,
        label,
        works,
        stats,
        frozenset(re.findall(r"\d+(?:\.\d+)?", stats)),
        digest,
        quote_text,
        fp,
    )


def brief(project: Project, scope: str, part: int = 0) -> dict[str, JsonValue]:
    """The brief an agent writes a page from. `part` pages through the digest: part 0 also
    carries the statistics and the rules."""
    ctx = context(project, scope)
    chunks: list[str] = []
    cur = ""
    for line in ctx.digest.split("\n"):
        if len(cur) + len(line) + 1 > PART_CHARS and cur:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    chunks.append(cur)
    if not 0 <= part < len(chunks):
        raise _issue("part", f"this brief has {len(chunks)} part(s), numbered from 0")
    out: dict[str, JsonValue] = {
        "scope": scope,
        "label": ctx.label,
        "works": len(ctx.works),
        "fingerprint": ctx.fingerprint,
        "part": part,
        "parts": len(chunks),
        "digest": chunks[part],
    }
    if part == 0:
        out["stats"] = ctx.stats
        out["rules"] = RULES.replace("<label>", ctx.label)
    return out


_NORM = re.compile(r"\s+")


def _norm(value: str) -> str:
    return _NORM.sub(" ", value.replace("“", '"').replace("”", '"')).strip().lower()


def check_page(ctx: Context, body: str) -> PageCheck:
    """The mechanical check of a page against its brief (see the module docstring)."""
    years = set(re.findall(r"20\d\d", ctx.digest + ctx.stats))
    errors: list[PageIssue] = []
    flags: list[PageIssue] = []
    cited = quotes = numbers = stats_only = 0
    for raw in re.split(r"(?<=[.!?])\s+|\n+", body):
        sent = raw.strip()
        if not sent or sent.startswith("#"):
            continue
        sent = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", sent)
        cites = re.findall(r"\[\[works/([^\]|]+)", sent)
        for c in cites:
            if c not in ctx.quote_text:
                errors.append(PageIssue(kind="unknown work", detail=c, sentence=sent[:140]))
        cited += bool(cites)
        cited_text = _norm(" ".join(ctx.quote_text.get(c, "") for c in cites))
        plain = sent.replace("“", '"').replace("”", '"')
        for qt in re.findall(rf'"([^"]{{{MIN_QUOTE_CHARS},}})"', plain):
            quotes += 1
            if not cites:
                errors.append(
                    PageIssue(
                        kind="quotation without citation", detail=qt[:100], sentence=sent[:100]
                    )
                )
            elif _norm(qt) not in cited_text:
                errors.append(
                    PageIssue(
                        kind="quotation not verbatim in a cited work",
                        detail=qt[:100],
                        sentence=sent[:100],
                    )
                )
        prose = re.sub(r'"[^"]*"', "", re.sub(r"\[\[[^\]]*\]\]", "", plain))
        bad = False
        for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?%?", prose):
            numbers += 1
            n0 = n.rstrip("%")
            if n0 not in ctx.stat_numbers and n0 not in years:
                bad = True
                errors.append(
                    PageIssue(kind="number not in the statistics", detail=n, sentence=sent[:120])
                )
        words = prose.split()
        has_num = bool(re.search(r"\d", prose))
        if len(words) > 10 and not cites:
            if not has_num and re.search(r"\b(papers?|works?|systems?|corpus)\b", prose):
                flags.append(
                    PageIssue(
                        kind="generalisation without a number or citation",
                        detail="",
                        sentence=sent[:140],
                    )
                )
            elif has_num and not bad:
                stats_only += 1
    return PageCheck(
        words=len(body.split()),
        cited_sentences=cited,
        quotes_checked=quotes,
        numbers_checked=numbers,
        stats_sentences=stats_only,
        errors=errors,
        flags=flags,
    )


def record_page(
    project: Project,
    actor: Actor,
    scope: str,
    title: str,
    body: str,
    supersedes: str | None = None,
) -> tuple[PageRecorded, PageCheck]:
    """Record a synthesis page. Refused, with nothing written: for a system actor; an empty or
    over-long page; a `supersedes` that is not a page of the same scope; a page that fails the
    check (the issues name the sentence)."""
    if actor.kind == "system":
        raise _issue("actor", "an agent or a human records a page")
    body = body.strip()
    if not body or len(body) > MAX_BODY_CHARS:
        raise _issue("body", f"a page has 1 to {MAX_BODY_CHARS} characters")
    if not title.strip() or len(title) > 200:
        raise _issue("title", "a title has 1 to 200 characters")
    previous: dict[str, Any] | None = None
    if supersedes is not None:
        previous = read_page(project, supersedes)
        if previous["scope"] != scope:
            raise _issue("supersedes", "a revision keeps the scope of the page it replaces")
    ctx = context(project, scope)
    result = check_page(ctx, body)
    if result.errors:
        raise FactoryValidationError(
            [
                ValidationIssue("body", f"{e.kind}: {e.detail} | {e.sentence}")
                for e in result.errors[:20]
            ]
        )
    page_id = project.ids.new("pg")
    blob = project.blobs.put_json(
        {
            "page_id": page_id,
            "kind": "synthesis",
            "scope": scope,
            "label": ctx.label,
            "title": title.strip(),
            "body": body,
            "fingerprint": ctx.fingerprint,
            "supersedes": supersedes,
            "stats": ctx.stats,
            "check": result.model_dump(mode="json"),
        }
    )
    payload = PageRecorded(
        page_id=page_id,
        kind="synthesis",
        scope=scope,
        title=title.strip(),
        body_sha256=hashlib.sha256(body.encode()).hexdigest(),
        flags=len(result.flags),
        supersedes=supersedes,
    )
    with project.index.exclusive():
        event = project.events.make(
            "page.recorded", payload, actor, refs=(page_id,), input_blob=blob
        )
        project.record([event])
    return payload, result


def _rows(
    project: Project,
) -> list[tuple[str, str, str, str | None, str | None, str, dict[str, Any]]]:
    project.index.sync()
    out = []
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT id, ts, actor_kind, model, skill, input_blob FROM events "
                "WHERE type = 'page.recorded' ORDER BY id"
            )
        ).all()
    for eid, ts, kind, model, skill, blob in found:
        if blob:
            loaded = project.blobs.get_json(blob)
            assert isinstance(loaded, dict)
            out.append((str(eid), str(ts), str(kind), model, skill, str(blob), loaded))
    return out


def read_page(project: Project, page_id: str) -> dict[str, Any]:
    """One recorded page: its text, scope, fingerprint, check and provenance."""
    for eid, ts, kind, model, skill, _blob, data in _rows(project):
        if data["page_id"] == page_id:
            return {
                **data,
                "event_id": eid,
                "recorded_at": ts,
                "actor_kind": kind,
                "model": model,
                "skill": skill,
            }
    raise _issue("page_id", f"no page {page_id}")


def list_pages(project: Project, *, current_only: bool = True) -> list[PageInfo]:
    """The recorded pages, oldest first; with `current_only` the latest page of each scope. A page
    is stale when the brief of its scope has changed since it was written."""
    rows = _rows(project)
    latest: dict[str, str] = {}
    for _eid, _ts, _k, _m, _s, _b, data in rows:
        latest[data["scope"]] = data["page_id"]
    payload = corpus_payload(project)
    fingerprints: dict[str, str] = {}
    out: list[PageInfo] = []
    for _eid, ts, kind, model, skill, _blob, data in rows:
        superseded = latest[data["scope"]] != data["page_id"]
        if current_only and superseded:
            continue
        if data["scope"] not in fingerprints:
            try:
                fingerprints[data["scope"]] = context(project, data["scope"], payload).fingerprint
            except FactoryValidationError:
                fingerprints[data["scope"]] = ""
        out.append(
            PageInfo(
                page_id=data["page_id"],
                kind=data["kind"],
                scope=data["scope"],
                title=data["title"],
                recorded_at=ts,
                actor_kind=kind,
                model=model,
                skill=skill,
                flags=len(data["check"]["flags"]),
                stale=fingerprints[data["scope"]] != data["fingerprint"],
                superseded=superseded,
                supersedes=data.get("supersedes"),
                words=data["check"]["words"],
            )
        )
    return out
