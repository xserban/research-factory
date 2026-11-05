"""The keys deduplication matches on (pure).

Shared by the cascade (`services.dedup_cascade`), which compares works, and by the projection of
indexed lookup tables (`index.search`), which stores the keys so incremental deduplication can
find candidates without loading the corpus. Both read the same functions, so they cannot disagree
about which works could match.
"""

from __future__ import annotations

from factory.model.work import Identifiers, Work
from factory.model.work_ids import arxiv_id_from_doi, normalize_title


def strong_keys(work: Work) -> list[tuple[str, str]]:
    """Exact-match keys, strongest first. A shared key is conclusive."""
    return identifier_keys(work.identifiers)


def identifier_keys(ids: Identifiers) -> list[tuple[str, str]]:
    """The exact-match keys of a set of identifiers; also the keys of a work's published aliases."""
    keys: list[tuple[str, str]] = []

    # An arXiv DOI and a bare arXiv id denote the same preprint; fold them into one key so
    # the OpenAlex record and the arXiv record meet.
    arxiv = ids.arxiv or (arxiv_id_from_doi(ids.doi) if ids.doi else None)
    if ids.doi and not arxiv_id_from_doi(ids.doi):
        keys.append(("doi", ids.doi))
    if arxiv:
        keys.append(("arxiv", arxiv))
    if ids.pmid:
        keys.append(("pmid", ids.pmid))
    if ids.pmcid:
        keys.append(("pmcid", ids.pmcid))
    if ids.openalex:
        keys.append(("openalex", ids.openalex))
    return keys


def first_surname(work: Work) -> str:
    """The normalised last token of the first author's name, or "" without one."""
    if not work.authors:
        return ""
    return normalize_title(work.authors[0].name).split()[-1] if work.authors[0].name else ""


def title_bucket_key(work: Work) -> tuple[int | None, str, str]:
    """`(year, normalised title, first surname)`: what the title rule compares.

    Two works can be joined by title only when their years are equal or adjacent (`None` pairs
    only with `None`), their titles score above the cascade threshold and their surnames agree.
    """
    return (work.dates.year, normalize_title(work.title), first_surname(work))
