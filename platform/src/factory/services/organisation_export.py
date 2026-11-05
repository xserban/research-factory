"""The graph export with labels and terms beside it (slice 3d ruling 16, plan Regions-C).

Organisation rows are a separate part of the output, never merged into the evidence nodes and
edges, and every row carries `class = organisation`. The default export is untouched: only the
CLI's `--with-labels` calls this module, and no evidence service imports it.

- JSON: `{"evidence": <the export text>, "notice": NOTICE, "organisation": {"labels": [...],
  "terms": [...]}}`, sorted keys, compact, one trailing newline.
- DOT: the evidence text with a first comment line `// NOTICE` and, before its closing brace, a
  `subgraph cluster_organisation` whose nodes are dashed notes, one per label key and per term.

The rows stream in pages; labels are listed by application id and terms by term id.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from factory.services.context import Project
from factory.services.labels import PAGE, LabelView, list_labels
from factory.services.terms import TermView, list_terms

NOTICE = "organisation: labels and terms are not evidence; they select nothing until promoted"
CLASS = "organisation"


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _label_row(v: LabelView) -> dict[str, object]:
    return {
        "application_id": v.application_id,
        "class": CLASS,
        "key": v.key,
        "live_key": v.live_key,
        "origin": v.origin,
        "status": v.status,
        "target": v.target,
        "target_type": v.target_type.value,
        "text": v.text,
    }


def _term_row(v: TermView) -> dict[str, object]:
    return {
        "aliases": list(v.aliases),
        "applies_to": [t.value for t in v.applies_to],
        "class": CLASS,
        "counts": v.counts,
        "definition": v.definition,
        "name": v.name,
        "refers_to": v.refers_to,
        "retired": v.retired,
        "term_id": v.term_id,
        "version": v.version,
    }


def _labels(project: Project) -> Iterator[LabelView]:
    offset = 0
    while True:
        page = list_labels(project, limit=PAGE, offset=offset)
        yield from page
        if len(page) < PAGE:
            return
        offset += PAGE


def _terms(project: Project) -> Iterator[TermView]:
    offset = 0
    while True:
        page = list_terms(project, include_retired=True, limit=PAGE, offset=offset)
        yield from page
        if len(page) < PAGE:
            return
        offset += PAGE


def _without_tail(chunks: Iterator[str], tail: str) -> Iterator[str]:
    """The stream minus its last `len(tail)` characters, which must equal `tail`."""
    held = ""
    for chunk in chunks:
        held += chunk
        if len(held) > len(tail):
            yield held[: -len(tail)]
            held = held[-len(tail) :]
    if held != tail:
        raise ValueError(f"the export does not end with {tail!r}")


def _joined(rows: Iterator[dict[str, object]]) -> Iterator[str]:
    first = True
    for row in rows:
        yield ("" if first else ",") + _dumps(row)
        first = False


def iter_with_labels(project: Project, fmt: str, evidence: Iterator[str]) -> Iterator[str]:
    """`evidence` (the export text in chunks) with the organisation part streamed beside it."""
    if fmt == "json":
        yield '{"evidence":'
        yield from _without_tail(evidence, "\n")
        yield ',"notice":' + _dumps(NOTICE) + ',"organisation":{"labels":['
        yield from _joined(_label_row(v) for v in _labels(project))
        yield '],"terms":['
        yield from _joined(_term_row(v) for v in _terms(project))
        yield "]}}\n"
        return
    yield f"// {NOTICE}\n"
    yield from _without_tail(evidence, "}\n")
    yield '  subgraph cluster_organisation {\n    label="organisation (not evidence)";\n'
    for v in _labels(project):
        row = _dumps(_label_row(v))
        yield f'    "{v.application_id}" [shape=note, style=dashed, label={_dumps(row)}];\n'
    for t in _terms(project):
        row = _dumps(_term_row(t))
        yield f'    "{t.term_id}" [shape=note, style=dashed, label={_dumps(row)}];\n'
    yield "  }\n}\n"
