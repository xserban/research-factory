"""Exports from events only: the bibliography of a scope of works and the PRISMA flow as SVG.

Read-only and byte-deterministic: works are selected by id, sorted by id, read from the
projection in pages of `PAGE` and serialised as they stream; nothing here touches the library
(R-47) or writes an event. A merged work is exported as its canonical record (the merge of its
members), as `canonical_works` would give it.

Invariants:
- Every refusal is a FactoryValidationError raised before the first character is produced.
- Exactly one of `scope` and `ids` selects works; an unknown or absorbed id is refused.
"""

from collections.abc import Iterator, Sequence
from typing import Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.exports.bibtex import bibtex
from factory.exports.csl import csl_json
from factory.exports.keys import assign_keys
from factory.exports.prisma_svg import prisma_svg
from factory.model.protocol import ScreeningStage
from factory.model.search import QueryPurpose
from factory.model.work import Work
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.dedup_cascade import merge_works
from factory.services.prisma import has_full_text_plan, prisma_flow
from factory.services.search import load_works

BibScope = Literal["included", "corpus"]
BibFormat = Literal["bibtex", "csl"]
PAGE = 500


def _issue(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _corpus_ids(project: Project) -> list[str]:
    """Work ids with non-probe provenance, sorted; one streamed query."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT work_id FROM provenance WHERE query_id NOT IN "
                "(SELECT query_id FROM queries WHERE purpose = :probe) ORDER BY work_id"
            ),
            {"probe": QueryPurpose.PROBE.value},
        ).all()
    return [str(row[0]) for row in rows]


def _canonical_ids(project: Project) -> list[str]:
    """Corpus ids less those absorbed by an active merge whose primary is in the corpus."""
    corpus = _corpus_ids(project)
    present = set(corpus)
    absorbed = {
        wid
        for merge in active_merges(project)
        if merge.primary in present
        for wid in merge.absorbed
        if wid != merge.primary
    }
    return [wid for wid in corpus if wid not in absorbed]


def select_works(
    project: Project, scope: BibScope | str | None = None, ids: Sequence[str] = ()
) -> list[str]:
    """Canonical work ids (sorted) of a scope, or the explicit `ids` validated against them.

    `included` is the final outcome INCLUDED at the last declared screening stage: full text when
    the protocol declares a plan, else title/abstract.
    """
    if (scope is None) == (not ids):
        raise _issue("scope", "give exactly one of a scope and a list of ids")
    canonical = _canonical_ids(project)
    if ids:
        known = set(canonical)
        unknown = sorted({wid for wid in ids if wid not in known})
        if unknown:
            raise _issue("ids", f"not canonical works of this project: {', '.join(unknown)}")
        return sorted(set(ids))
    if scope == "corpus":
        return canonical
    if scope == "included":
        stage = (
            ScreeningStage.FULL_TEXT
            if has_full_text_plan(project)
            else ScreeningStage.TITLE_ABSTRACT
        )
        outcomes = final_outcomes(project, stage=stage)
        return [wid for wid in canonical if outcomes.get(wid) is Outcome.INCLUDED]
    raise _issue("scope", f"unknown scope {scope!r}; use included or corpus")


def iter_works(project: Project, work_ids: Sequence[str]) -> Iterator[Work]:
    """The canonical works of `work_ids`, in the order given, read in pages of `PAGE`."""
    for _, work in _iter_pairs(project, work_ids):
        yield work


def _iter_pairs(project: Project, work_ids: Sequence[str]) -> Iterator[tuple[str, Work]]:
    """(selected id, canonical work) pairs; the id keys the entry even if a merge re-ranks."""
    members = {merge.primary: merge.absorbed for merge in active_merges(project)}
    for start in range(0, len(work_ids), PAGE):
        page = list(work_ids[start : start + PAGE])
        wanted = list(dict.fromkeys(page + [a for wid in page for a in members.get(wid, ())]))
        loaded = {work.id: work for work in load_works(project, wanted)}
        for wid in page:
            group = [loaded[m] for m in (wid, *members.get(wid, ())) if m in loaded]
            if len(group) > 1:
                yield wid, merge_works(group)
            elif group:
                yield wid, group[0]


def export_bibliography(
    project: Project,
    fmt: BibFormat | str,
    *,
    scope: BibScope | str | None = None,
    ids: Sequence[str] = (),
    ascii_only: bool = False,
) -> Iterator[str]:
    """The bibliography text, streamed. With no `ids`, `scope` defaults to `included`.

    Selection and validation happen before this returns, so a refusal yields nothing.
    """
    if scope is None and not ids:
        scope = "included"
    return render_bibliography(
        project, fmt, select_works(project, scope, ids), ascii_only=ascii_only
    )


def render_bibliography(
    project: Project, fmt: BibFormat | str, work_ids: Sequence[str], *, ascii_only: bool = False
) -> Iterator[str]:
    """The bibliography text of already-selected canonical `work_ids`, streamed. An unknown
    `fmt` is refused before anything is produced."""
    if fmt not in ("bibtex", "csl"):
        raise _issue("format", f"unknown format {fmt!r}; use bibtex or csl")
    keys = assign_keys(work_ids)

    def entries() -> Iterator[tuple[str, Work]]:
        for wid, work in _iter_pairs(project, work_ids):
            yield keys[wid], work

    if fmt == "csl":
        return csl_json(entries())
    return bibtex(entries(), ascii_only=ascii_only)


def export_prisma_svg(project: Project) -> str:
    """The PRISMA 2020 flow of the project as SVG."""
    return prisma_svg(prisma_flow(project))


__all__ = [
    "PAGE",
    "BibFormat",
    "BibScope",
    "export_bibliography",
    "export_prisma_svg",
    "iter_works",
    "render_bibliography",
    "select_works",
]
