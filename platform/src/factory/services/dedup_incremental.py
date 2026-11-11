"""Incremental deduplication of newly arrived works, by indexed key lookups (slice 4b, ruling 7).

`dedup_new` applies the same cascade as `dedup_run` and writes the same `dedup.merged` and
`dedup.reverted` events, but only for groups that contain one of the given new works. It reads
candidates by primary key, never the corpus: strong identifiers through `work_keys`, titles by
streaming the year-window rows of `work_title_buckets` in batches of at most `DEDUP_BATCH` and
scoring them with the cascade's own threshold and first-surname rule.

Invariant it relies on: the corpus was reconciled before the new works arrived (by an earlier
`dedup_new` or `dedup_run`). Pairs of old works that were never compared are `dedup_run`'s to
find. Over a corpus built only through `dedup_new`, a following `dedup_run` writes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from itertools import islice

from rapidfuzz import fuzz
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from factory.model.dedup import DedupMerged, MergeStatus
from factory.model.dedup_keys import strong_keys, title_bucket_key
from factory.model.work import Work
from factory.services.context import Project
from factory.services.dedup import (
    DedupSummary,
    alias_keys,
    blocked_pairs,
    joined_pairs,
    matching_merge,
    write_reconciliation,
)
from factory.services.dedup_cascade import (
    TITLE_SIMILARITY_THRESHOLD,
    YEAR_WINDOW,
    CascadeMerge,
    dedup,
)
from factory.services.search import corpus_size, works_by_ids

DEDUP_BATCH = 2_000
"""The most new works compared per round, and the rows fetched per read of a title bucket."""

_ID_CHUNK = 500


def dedup_new(project: Project, work_ids: Sequence[str]) -> DedupSummary:
    """Merge the given new works into the corpus. Writes only what `dedup_run` would write.

    The index's write lock is held from the first read to the last write. `works` in the summary
    counts the works considered (new, candidates and members of their merges), not the corpus.
    """
    ids = sorted(set(work_ids))
    created: list[str] = []
    reverted: list[str] = []
    unchanged = works = 0
    with project.index.exclusive():
        project.index.sync()
        for batch in _batches(ids, DEDUP_BATCH):
            part = _reconcile_batch(project, batch)
            created.extend(part.created)
            reverted.extend(part.reverted)
            unchanged += part.unchanged
            works += part.works
        return DedupSummary(
            created=created,
            reverted=reverted,
            unchanged=unchanged,
            records=corpus_size(project)[1],
            works=works,
            canonical=_canonical_count(project),
        )


def considered_works(project: Project, work_ids: Sequence[str]) -> list[Work]:
    """The works a batch is compared with: the new works that are in the corpus, the candidates
    they could match, and every member of the active merges that touch either."""
    project.index.sync()
    new = works_by_ids(project, work_ids)
    return _considered(project, new, {w.id for w in new})[0]


def _batches(ids: list[str], size: int) -> Iterator[list[str]]:
    it = iter(ids)
    while batch := list(islice(it, size)):
        yield batch


def _reconcile_batch(project: Project, batch: Sequence[str]) -> DedupSummary:
    new = works_by_ids(project, batch)
    new_ids = {w.id for w in new}
    if not new:
        return DedupSummary(created=[], reverted=[], unchanged=0, records=0, works=0, canonical=0)
    works, active = _considered(project, new, new_ids)
    result = dedup(
        works,
        blocked=blocked_pairs(project),
        joined=joined_pairs(project),
        aliases=alias_keys(project, [w.id for w in works]),
    )
    # Only groups that contain a new work are ours to reconcile; identity collapses absorb nothing.
    groups = [g for g in result.merges if g.absorbed and new_ids & {g.primary, *g.absorbed}]
    touched = new_ids | {m for g in groups for m in (g.primary, *g.absorbed)}
    relevant = [m for m in active if touched & {m.primary, *m.absorbed}]

    kept: set[str] = set()
    fresh: list[CascadeMerge] = []
    for group in groups:
        match = matching_merge(relevant, group)
        if match is None:
            fresh.append(group)
        else:
            kept.add(match.merge_id)
    stale = [m for m in relevant if m.merge_id not in kept]
    created = write_reconciliation(project, stale, fresh)
    return DedupSummary(
        created=created,
        reverted=[m.merge_id for m in stale],
        unchanged=len(kept),
        records=0,
        works=len(works),
        canonical=0,
    )


def _considered(
    project: Project, new: Sequence[Work], new_ids: set[str]
) -> tuple[list[Work], list[DedupMerged]]:
    """New works plus candidates plus merge members, and the active merges that touch them."""
    with project.index.connect() as conn:
        candidate_ids = (
            _key_candidates(conn, new) | _title_candidates(conn, new) | _joined_partners(conn, new)
        )
        touching = _active_merges_touching(conn, new_ids | candidate_ids)
    member_ids = {m for merge in touching for m in (merge.primary, *merge.absorbed)}
    works = works_by_ids(project, sorted(new_ids | candidate_ids | member_ids))
    return works, touching


def alias_map(conn: Connection, work_ids: Sequence[str]) -> dict[str, list[tuple[str, str]]]:
    statement = text(
        "SELECT work_id, kind, value FROM work_aliases WHERE work_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    found: dict[str, list[tuple[str, str]]] = {}
    ids = sorted(set(work_ids))
    for start in range(0, len(ids), _ID_CHUNK):
        for work_id, kind, value in conn.execute(
            statement, {"ids": ids[start : start + _ID_CHUNK]}
        ):
            found.setdefault(str(work_id), []).append((str(kind), str(value)))
    return found


def _key_candidates(conn: Connection, new: Sequence[Work]) -> set[str]:
    found: set[str] = set()
    statement = text("SELECT work_id FROM work_keys WHERE kind = :kind AND value = :value")
    aliases = alias_map(conn, [w.id for w in new])
    for work in new:
        # A linked work's published identifiers are in `work_keys` under it, so a new work finds
        # it by them; its own aliases find the works that carry those identifiers.
        for kind, value in [*strong_keys(work), *aliases.get(work.id, ())]:
            found.update(str(r[0]) for r in conn.execute(statement, {"kind": kind, "value": value}))
    return found


def _joined_partners(conn: Connection, new: Sequence[Work]) -> set[str]:
    """The other side of every pair the researcher ruled `same` that has a new work on one side."""
    found: set[str] = set()
    ids = sorted({w.id for w in new})
    for column, other in (("work_a", "work_b"), ("work_b", "work_a")):
        statement = text(
            f"SELECT {other} FROM dedup_pair_decisions WHERE decision = 'same' AND {column} IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        for start in range(0, len(ids), _ID_CHUNK):
            found.update(
                str(r[0]) for r in conn.execute(statement, {"ids": ids[start : start + _ID_CHUNK]})
            )
    return found


def _title_candidates(conn: Connection, new: Sequence[Work]) -> set[str]:
    """Works whose year is within `YEAR_WINDOW` of a new work's, with the same first surname and
    a title scoring at least the cascade threshold. `None` years pair only with `None`."""
    keys = [(w.id, *title_bucket_key(w)) for w in new]
    keys = [k for k in keys if k[3]]  # a missing first surname never matches
    found: set[str] = set()
    for year in _window_years({k[1] for k in keys}):
        wanted = [k for k in keys if _near(k[1], year)]
        by_surname: dict[str, list[tuple[str, str]]] = {}
        for work_id, _year, title, surname in wanted:
            by_surname.setdefault(surname, []).append((work_id, title))
        for rows in _bucket_rows(conn, year):
            for other_id, other_title, other_surname in rows:
                for work_id, title in by_surname.get(other_surname, ()):
                    if other_id != work_id and (
                        fuzz.token_sort_ratio(title, other_title) >= TITLE_SIMILARITY_THRESHOLD
                    ):
                        found.add(other_id)
    return found


def _near(year: int | None, other: int | None) -> bool:
    if year is None or other is None:
        return year is other
    return abs(year - other) <= YEAR_WINDOW


def _window_years(years: set[int | None]) -> list[int | None]:
    out: set[int | None] = set()
    for year in years:
        if year is None:
            out.add(None)
        else:
            out.update(range(year - YEAR_WINDOW, year + YEAR_WINDOW + 1))
    return sorted(out, key=lambda y: (y is None, y or 0))


def _bucket_rows(conn: Connection, year: int | None) -> Iterator[list[tuple[str, str, str]]]:
    where = "year IS NULL" if year is None else "year = :year"
    params = {} if year is None else {"year": year}
    result = conn.execute(
        text(f"SELECT work_id, title_norm, surname FROM work_title_buckets WHERE {where}"), params
    )
    while rows := result.fetchmany(DEDUP_BATCH):
        yield [(str(a), str(b), str(c)) for a, b, c in rows]


def _active_merges_touching(conn: Connection, work_ids: set[str]) -> list[DedupMerged]:
    statement = text(
        'SELECT DISTINCT m.merge_id, m."primary", m.absorbed, m.rule, m.records '
        "FROM merges m JOIN merge_members mm ON mm.merge_id = m.merge_id "
        "WHERE m.status = :active AND mm.work_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    merges: dict[str, DedupMerged] = {}
    ids = sorted(work_ids)
    for start in range(0, len(ids), _ID_CHUNK):
        chunk = ids[start : start + _ID_CHUNK]
        for merge_id, primary, absorbed, rule, records in conn.execute(
            statement, {"active": MergeStatus.ACTIVE.value, "ids": chunk}
        ):
            merges[str(merge_id)] = DedupMerged(
                merge_id=str(merge_id),
                primary=str(primary),
                absorbed=tuple(str(x) for x in json.loads(str(absorbed))),
                rule=str(rule),
                records=int(records),
            )
    return [merges[k] for k in sorted(merges)]


def _canonical_count(project: Project) -> int:
    """Corpus works minus the works absorbed by active merges, counted in SQL."""
    with project.index.connect() as conn:
        members, merges = conn.execute(
            text(
                "SELECT COUNT(*), COUNT(DISTINCT mm.merge_id) FROM merge_members mm "
                "JOIN merges m ON m.merge_id = mm.merge_id WHERE m.status = :active"
            ),
            {"active": MergeStatus.ACTIVE.value},
        ).one()
    return corpus_size(project)[0] - (int(members) - int(merges))
