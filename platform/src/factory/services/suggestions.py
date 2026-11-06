"""Computed cross-project suggestions (plan XL task 3; proposed decision PD-9, option a).

A suggestion is a read-only hint with a stated reason. It is computed on request, never stored, and
writes nothing in either project. A work enters the target only when the researcher adds it to the
inbox, through that project's protocol. No embeddings (decision 9 stays open).

Signals, each with a fixed reason template:
- `included-elsewhere`: a work of the target corpus that another project included and this one has
  not (matched by a shared strong identifier).
- `reviewed-region`: a work of another project's corpus, absent here, that is a member of the
  latest version of a region a human reviewed there (a region withheld from agents is never read).
- `cited-by-included`: a work of another project's corpus, absent here, that a live reference
  entry of one of this project's included works cites by DOI or arXiv id.

Invariants:
- Only corpus works and reviewed, non-withheld regions are read; no seed record, seed id, stated
  identifier or held-out rate is read, so none can leave a project through a suggestion. A reason
  names the other project and the signal, never a title, a quotation or a count of seeds.
- Opening another project may refresh its rebuildable index, and appends no event. A project that
  cannot be read is skipped, and so is a `private` project (teams-A) in which the reader holds no
  role: its works are never named to a non-member.
- The result is deterministic: sorted by project slug, signal order, work id, and capped.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from factory.errors import FactoryError
from factory.model.base import StrictModel
from factory.model.identity import IdGenerator
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project, list_projects, open_project
from factory.services.region_adoption import source_readable
from factory.services.regions import region_withheld
from factory.services.search import corpus_work_ids

__all__ = ["DEFAULT_CAP", "REASONS", "Suggestion", "suggestions"]

DEFAULT_CAP = 100
Signal = Literal["included-elsewhere", "reviewed-region", "cited-by-included"]
SIGNALS: tuple[Signal, ...] = ("included-elsewhere", "reviewed-region", "cited-by-included")
REASONS: dict[Signal, str] = {
    "included-elsewhere": "also in the corpus of {project}, where it is included",
    "reviewed-region": "a member of a reviewed region of {project}",
    "cited-by-included": "cited by an included work here; held in the corpus of {project}",
}
Key = tuple[str, str]


class Suggestion(StrictModel):
    """`work` is the work id in the project that holds it: this project for `included-elsewhere`,
    `from_project` otherwise. `identifier` is its first strong identifier, `kind:value`, to
    form an inbox link; None when it has none."""

    work: str
    from_project: str
    signal: Signal
    reason: str
    identifier: str | None = None


def _keys(project: Project, works: set[str]) -> dict[str, list[Key]]:
    """The strong identifier keys of each work, by work id."""
    found: dict[str, list[Key]] = {}
    with project.index.connect() as conn:
        for work, kind, value in conn.execute(
            text("SELECT work_id, kind, value FROM work_keys ORDER BY work_id, kind, value")
        ):
            if str(work) in works:
                found.setdefault(str(work), []).append((str(kind), str(value)))
    return found


def _by_key(keys: dict[str, list[Key]]) -> dict[Key, str]:
    return {key: work for work, listed in sorted(keys.items(), reverse=True) for key in listed}


def _included(project: Project) -> set[str]:
    return {w for w, o in final_outcomes(project).items() if o is Outcome.INCLUDED}


def _reviewed_region_works(source: Project) -> set[str]:
    """The work members of the latest version of each human-reviewed region that is not withheld
    from agents."""
    with source.index.connect() as conn:
        regions = [
            (str(r[0]), str(r[1]))
            for r in conn.execute(
                text(
                    "SELECT s.region_id, s.version FROM region_snapshots s WHERE s.event_id = "
                    "(SELECT MAX(x.event_id) FROM region_snapshots x WHERE x.region_id = "
                    "s.region_id) AND COALESCE((SELECT r.state FROM region_reviews r WHERE "
                    "r.version = s.version ORDER BY r.event_id DESC LIMIT 1), '') = 'reviewed' "
                    "ORDER BY s.region_id"
                )
            )
        ]
    works: set[str] = set()
    for region_id, _version in regions:
        if region_withheld(source, region_id):
            continue
        with source.index.connect() as conn:
            works.update(
                str(r[0])
                for r in conn.execute(
                    text(
                        "SELECT member FROM region_members WHERE region_id = :r "
                        "AND member_type = 'work'"
                    ),
                    {"r": region_id},
                )
            )
    return works


def _cited_keys(project: Project, included: set[str]) -> set[Key]:
    """The `("doi" | "arxiv", value)` keys cited by live reference entries of included works."""
    cited: set[Key] = set()
    with project.index.connect() as conn:
        for work, doi, arxiv in conn.execute(
            text(
                "SELECT x.work_id, e.doi, e.arxiv FROM reference_entries e JOIN "
                "reference_extractions x ON x.extraction_id = e.extraction_id WHERE x.live = 1"
            )
        ):
            if str(work) not in included:
                continue
            if doi:
                cited.add(("doi", str(doi)))
            if arxiv:
                cited.add(("arxiv", str(arxiv)))
    return cited


def _label(keys: Iterable[Key]) -> str | None:
    first = next(iter(keys), None)
    return None if first is None else f"{first[0]}:{first[1]}"


def _from_source(
    source: Project,
    own: dict[str, list[Key]],
    own_included: set[str],
    cited: set[Key],
) -> list[Suggestion]:
    slug = source.paths.slug
    held = _by_key(own)
    theirs_ids = corpus_work_ids(source)
    theirs = _keys(source, theirs_ids)
    out: list[Suggestion] = []

    def made(signal: Signal, work: str, keys: list[Key]) -> Suggestion:
        return Suggestion(
            work=work,
            from_project=slug,
            signal=signal,
            reason=REASONS[signal].format(project=slug),
            identifier=_label(keys),
        )

    included = _included(source)
    matched = {
        held[key]
        for work in included
        for key in theirs.get(work, [])
        if key in held and held[key] not in own_included
    }
    out += [made("included-elsewhere", work, own[work]) for work in sorted(matched)]
    held_keys = set(held)
    for work in sorted(_reviewed_region_works(source) & theirs_ids):
        keys = theirs.get(work, [])
        if keys and not held_keys.intersection(keys):
            out.append(made("reviewed-region", work, keys))
    for work in sorted(theirs_ids):
        keys = theirs.get(work, [])
        if cited.intersection(keys) and not held_keys.intersection(keys):
            out.append(made("cited-by-included", work, keys))
    return out


def suggestions(
    project: Project, *, cap: int = DEFAULT_CAP, sources: Iterable[str] | None = None
) -> list[Suggestion]:
    """Up to `cap` suggestions for `project` from the other projects under its root (or only
    `sources`), in the order of the module docstring. Writes nothing in any project."""
    project.index.sync()
    own_ids = corpus_work_ids(project)
    own = _keys(project, own_ids)
    own_included = _included(project)
    cited = _cited_keys(project, own_included)
    slugs = sorted(set(list_projects(project.settings) if sources is None else sources))
    found: list[Suggestion] = []
    for slug in slugs:
        if slug == project.paths.slug:
            continue
        try:
            source = open_project(
                project.settings,
                slug,
                session=IdGenerator(project.clock).ulid(),
                clock=project.clock,
                principal=project.principal,
            )
            if not source_readable(source, project.principal.user):
                continue
            source.index.sync()
            found += _from_source(source, own, own_included, cited)
        except (FactoryError, OSError, SQLAlchemyError):
            continue
    order = {signal: i for i, signal in enumerate(SIGNALS)}
    found.sort(key=lambda s: (s.from_project, order[s.signal], s.work))
    return found[:cap]
