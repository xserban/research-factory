"""Compact paper profiles: what every listed miner found in a work, in one short text (plan chat,
T5, section 4.2).

In the papers chat Claude reads one profile per paper in scope to decide which papers bear on a
question, before reading the chosen ones in full. The raw mined output is far larger; a profile
keeps the field values only.

Invariants:
- Read-only: nothing is written. The index is synced before reading.
- Miners included are those currently listed in the protocol's `miners` section, one entry per
  miner NAME: its highest listed registered version only (a scope has no version, so profiling two
  listed versions would read the same rows twice); rows are read from the miner's scope
  (`MinerScope(name)`).
- Held-out scrub: the title and every row value pass the same `withhold` of the held-out tokens
  (`held_out_tokens(include_work_ids=False)`) as the corpus search; the work id is not scrubbed.
- A miner's rows for a work are its final rows (`final_rows_restricted`) with status `final`.
  Final rows leave out every row until pass B of the miner has opened, so a work with no final
  row falls back to its live (not superseded) pass A rows, with status `pass-a-only`. A work with
  neither, and in a calibration sample of the listed VERSION of the miner (calibrations of other
  versions never count), takes the researcher's gold rows (status `gold`, non-empty labels of any
  such calibration), else the calibration session's rows (status `calibration`). A work with none
  of these is in `missing_miners`. GOLD-EMPTY: a work with no production row whose gold label in a
  calibration of the listed VERSION is empty (and no non-empty gold label) is a decision of the
  researcher, "this paper has none of these claims": it gets no rows, not even the calibration
  session's, and no older-version fallback; the miner is in `gold_empty`, neither in
  `missing_miners` nor a gap. Production rows (final, pass A) still win over it. Rows of the one
  status are never mixed for a work and miner.
- Versions: rows are read at the listed version of the miner (their `schema_ref`). A work with NO
  row of the listed version from any source above, that pass B has not reviewed to empty, falls
  back to the rows of the newest older version of the same miner that has rows for it, taking the
  same source order within that version (live pass A rows, then gold, then calibration; final rows
  are only known for the listed version). Every row carries the `version` served, and a profile row
  served from an older version has `older` set and is rendered with its version. One work never
  mixes versions.
- A work that pass B has reviewed (pass B opened, its passes current) and that ended with no final
  row gets no rows of the miner: its pass A rows are not served as `pass-a-only`; the miner is in
  `reviewed_empty`, not `missing_miners`.
- A work whose only live rows are of a version NEWER than the listed one gets none of them (the
  listed version is the contract); the miner is in `newer_version_only`, not `missing_miners`.
- Quote fields are omitted, except for miners in `QUOTED_MINERS`, whose quotes are kept cut to
  `QUOTE_CHARS` characters. Other values are cut to `VALUE_CHARS`.
- A category of a miner derived from a taxonomy is shown by its category name, not its id.
- Unknown work ids are refused on field `work_ids` before anything is read; the order of the
  profiles is that of the work ids given. `render_profile` is deterministic: miners by name and
  version, rows by row key, fields in the miner spec's order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.mining.spec import EnumKind, MinerSpec, QuoteKind
from factory.mining.taxonomy import TaxonomySpec, full_id
from factory.model.extraction import MinerScope
from factory.model.screening import PassLabel
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.extraction import (
    calibration_task_ids,
    live_rows,
    pass_config,
    scope_ledger,
    unit_states,
)
from factory.services.extraction_agreement import final_rows_restricted
from factory.services.miner_gold import calibration_labels
from factory.services.mining import registered_miner
from factory.services.protocol import current_protocol
from factory.services.search import get_work
from factory.services.taxonomies import registered_taxonomy
from factory.services.withholding import held_out_tokens, withhold

__all__ = [
    "PROFILE_CHARS_PER_TOKEN",
    "QUOTED_MINERS",
    "QUOTE_CHARS",
    "VALUE_CHARS",
    "MinerWorkState",
    "PaperProfile",
    "ProfileRow",
    "RawMinerRow",
    "category_names",
    "choose_rows",
    "listed_miner_versions",
    "load_miner_rows",
    "load_miner_work_report",
    "load_miner_work_rows",
    "load_miner_work_state",
    "paper_profiles",
    "profile_size",
    "render_profile",
]

QUOTED_MINERS = frozenset({"m-summary", "m-claims"})
"""Miners whose quote fields a profile keeps."""

QUOTE_CHARS = 300
VALUE_CHARS = 120
PROFILE_CHARS_PER_TOKEN = 4
"""Characters per token for `profile_size`. A rough estimate, not a tokeniser count."""

_ELLIPSIS = "…"


@dataclass(frozen=True)
class ProfileRow:
    """One row of a miner for a work: `status` is `final`, `pass-a-only`, `gold` or `calibration`;
    `fields` are `(name, short value)` pairs in the miner spec's order."""

    miner: str
    version: int
    status: str
    row_key: str
    fields: tuple[tuple[str, str], ...]
    older: bool = False
    """True when `version` is older than the listed version of the miner (see the module
    invariants)."""


@dataclass(frozen=True)
class PaperProfile:
    """Everything the listed miners found in one work. `missing_miners` are the listed
    `(name, version)` with no row at all for the work; `reviewed_empty` those whose pass B
    reviewed the work and ended with no final row (their pass A rows are not served);
    `gold_empty` those where the researcher's gold label of the listed version is empty (no
    claims, by decision; not a gap)."""

    work_id: str
    title: str
    year: str
    rows: tuple[ProfileRow, ...]
    missing_miners: tuple[tuple[str, int], ...]
    reviewed_empty: tuple[tuple[str, int], ...] = ()
    newer_version_only: tuple[tuple[str, int], ...] = ()
    """Listed miners whose only rows for the work are of a newer version than the listed one;
    not served, not counted missing."""
    gold_empty: tuple[tuple[str, int], ...] = ()


def profile_size(text: str) -> int:
    """The estimated tokens of `text` (characters over `PROFILE_CHARS_PER_TOKEN`, rounded up)."""
    return -(-len(text) // PROFILE_CHARS_PER_TOKEN)


def category_names(taxonomy: TaxonomySpec) -> dict[str, str]:
    """`dimension/category` id to category name for every category of `taxonomy`. Pure.
    Residual values and layer categories have no name here and are shown by their id."""
    return {
        full_id(d.id, c.id): c.name for d in taxonomy.dimensions for c in d.categories if c.name
    }


def _cut(value: str, limit: int) -> str:
    flat = " ".join(value.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + _ELLIPSIS


def _short(
    spec: MinerSpec, names: Mapping[str, str], field: str, value: str | int | float | bool
) -> str | None:
    """The shown value of a stored field, or None when the field is not shown."""
    definition = spec.field_named(field)
    if definition is None:
        return _cut(str(value), VALUE_CHARS)
    text = "true" if value is True else "false" if value is False else str(value)
    if isinstance(definition.kind, QuoteKind):
        return _cut(text, QUOTE_CHARS) if spec.name in QUOTED_MINERS else None
    if isinstance(definition.kind, EnumKind) and names:
        text = names.get(text, text)
    return _cut(text, VALUE_CHARS)


def _ordered(
    spec: MinerSpec, stored: Mapping[str, tuple[str | int | float | bool, str | None]]
) -> list[str]:
    declared = [f.name for f in spec.fields if f.name in stored]
    return declared + sorted(set(stored) - set(declared))


def _row(
    spec: MinerSpec,
    names: Mapping[str, str],
    status: str,
    row_key: str,
    stored: Mapping[str, tuple[str | int | float | bool, str | None]],
    version: int | None = None,
) -> ProfileRow:
    fields: list[tuple[str, str]] = []
    for field in _ordered(spec, stored):
        value, unit = stored[field]
        shown = _short(spec, names, field, value)
        if shown:
            fields.append((field, f"{shown} {unit}" if unit else shown))
    served = spec.version if version is None else version
    return ProfileRow(
        spec.name, served, status, row_key, tuple(fields), older=served < spec.version
    )


def _scrubbed(row: ProfileRow, tokens: set[str]) -> ProfileRow:
    return replace(row, fields=tuple((k, str(withhold(v, tokens))) for k, v in row.fields))


def _names_of(project: Project, spec: MinerSpec) -> dict[str, str]:
    if spec.taxonomy is None:
        return {}
    taxonomy = registered_taxonomy(project, spec.taxonomy.name, spec.taxonomy.version)
    return {} if taxonomy is None else category_names(taxonomy)


@dataclass(frozen=True)
class RawMinerRow:
    """One stored row of a miner for a work, unshortened: `status` is `final`, `pass-a-only`,
    `gold` or `calibration`; `fields` maps a field name to `(value, unit, anchor, quote)`."""

    status: str
    row_key: str
    fields: Mapping[str, tuple[str | int | float | bool, str | None, str | None, str | None]]
    version: int = 0
    """The miner version the row belongs to (its `schema_ref`); 0 when not labelled."""


def listed_miner_versions(project: Project) -> list[tuple[str, int]]:
    """The protocol's listed miners, one `(name, version)` per name sorted by name: the highest
    listed version that is registered (else the highest listed). Empty without a protocol."""
    protocol = current_protocol(project)
    versions: dict[str, list[int]] = {}
    for use in (protocol.spec.miners or ()) if protocol else ():
        versions.setdefault(use.name, []).append(use.version)
    listed: list[tuple[str, int]] = []
    for name in sorted(versions):
        ordered_versions = sorted(versions[name], reverse=True)
        chosen = next(
            (v for v in ordered_versions if registered_miner(project, name, v) is not None),
            ordered_versions[0],
        )
        listed.append((name, chosen))
    return listed


def choose_rows(
    production: list[RawMinerRow], gold: list[RawMinerRow], calibration: list[RawMinerRow]
) -> list[RawMinerRow]:
    """The rows one work contributes: its production rows when it has any, else the researcher's
    gold rows, else the calibration session's rows. Never a mixture; pure."""
    return production or gold or calibration


def _raw(status: str, row_key: str, fields: Mapping[str, Any], version: int) -> RawMinerRow:
    return RawMinerRow(
        status,
        row_key,
        {k: (f.value, f.unit, f.anchor, f.quote) for k, f in fields.items()},
        version,
    )


def _row_versions(project: Project, name: str) -> dict[str, int]:
    """The schema version (`schema_ref` `name@version`) of every live mined row of miner `name`,
    by extraction id. Read-only; the caller has synced the index."""
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT extraction_id, schema_ref FROM extraction_rows "
                "WHERE scope = :s AND superseded_by IS NULL"
            ),
            {"s": name},
        ).all()
    versions: dict[str, int] = {}
    for ident, ref in found:
        _, _, tail = str(ref).rpartition("@")
        if tail.isdigit():
            versions[str(ident)] = int(tail)
    return versions


def _calibration_versions(project: Project, name: str) -> set[int]:
    with project.index.connect() as conn:
        found = conn.execute(
            text("SELECT DISTINCT version FROM miner_calibrations WHERE name = :n"), {"n": name}
        ).all()
    return {int(v) for (v,) in found}


def _calibration_units(
    project: Project, name: str, version: int, work_ids: Sequence[str]
) -> dict[str, list[str]]:
    """For each work of `work_ids` in a calibration sample of miner `name` at `version`, the
    ids of the calibrations of that version that drew it, oldest first."""
    wanted = set(work_ids)
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT u.work_id, c.calibration_id FROM miner_calibration_units u "
                "JOIN miner_calibrations c ON c.calibration_id = u.calibration_id "
                "WHERE c.name = :n AND c.version = :v ORDER BY c.event_id"
            ),
            {"n": name, "v": version},
        ).all()
    units: dict[str, list[str]] = {}
    for w, c in found:
        if str(w) in wanted:
            units.setdefault(str(w), []).append(str(c))
    return units


def _gold_and_calibration(
    project: Project, name: str, version: int, scope: MinerScope, work_ids: Sequence[str]
) -> tuple[dict[str, list[RawMinerRow]], dict[str, list[RawMinerRow]], set[str]]:
    """The researcher's gold rows and the calibration session's rows of the works that are in a
    calibration sample of `name` at `version` (calibrations of other versions are ignored), each
    read once for all of them. Within the matching calibrations the latest one with gold (or rows)
    for a work gives that work's rows. The third part is the works with an EMPTY gold label and no
    non-empty one: the researcher's "no claims" (see `GOLD-EMPTY` in the module invariants)."""
    units = _calibration_units(project, name, version, work_ids)
    gold: dict[str, list[RawMinerRow]] = {}
    plain: dict[str, list[RawMinerRow]] = {}
    empty: set[str] = set()
    if not units:
        return gold, plain, empty
    order: list[str] = []
    for cids in units.values():
        order.extend(c for c in cids if c not in order)
    for cid in order:
        mine = {w for w, cids in units.items() if cid in cids}
        for work, labelled in calibration_labels(project, cid).items():
            if work in mine and labelled:
                gold[work] = [_raw("gold", r.row_key, r.fields, version) for r in labelled]
            elif work in mine:
                empty.add(work)
        apart = calibration_task_ids(project, scope, cid)
        fresh: dict[str, list[RawMinerRow]] = {}
        for row in live_rows(project, None, scope=scope, calibration=True):
            if row.work_id in mine and row.task_id in apart:
                fresh.setdefault(row.work_id, []).append(
                    _raw("calibration", row.row_key, row.fields, version)
                )
        plain.update(fresh)
    return gold, plain, empty - set(gold)


def _reviewed_by_pass_b(project: Project, scope: MinerScope, work_ids: Sequence[str]) -> set[str]:
    """The works of `work_ids` whose production extraction is complete once pass B has opened:
    pass A is current for the work and either it is outside the dual sample (it has no pass B
    unit) or its pass B unit is current. Such a work with no final row was reviewed to empty."""
    if pass_config(project, PassLabel.B, scope=scope) is None:
        return set()
    states = unit_states(project, scope=scope, ledger=scope_ledger(project, scope))
    a_current = {s.work_id for s in states if s.pass_label is PassLabel.A and s.state == "current"}
    b_state = {s.work_id: s.state for s in states if s.pass_label is PassLabel.B}
    return {w for w in work_ids if w in a_current and b_state.get(w, "current") == "current"}


def load_miner_work_rows(
    project: Project, name: str, version: int, work_ids: Sequence[str]
) -> tuple[dict[str, list[RawMinerRow]], frozenset[str]]:
    """`load_miner_work_report` without its third part."""
    rows, emptied, _newer = load_miner_work_report(project, name, version, work_ids)
    return rows, emptied


@dataclass(frozen=True)
class MinerWorkState:
    """What `load_miner_work_state` found: `rows` of every work, and the works `emptied` (pass B
    reviewed to empty), `newer` (only rows of a newer version) and `gold_empty` (the researcher's
    empty gold label of the listed version: no claims, by decision). The three sets are disjoint
    and every work in them has no rows."""

    rows: dict[str, list[RawMinerRow]]
    emptied: frozenset[str]
    newer: frozenset[str]
    gold_empty: frozenset[str]


def load_miner_work_report(
    project: Project, name: str, version: int, work_ids: Sequence[str]
) -> tuple[dict[str, list[RawMinerRow]], frozenset[str], frozenset[str]]:
    """`load_miner_work_state` without its `gold_empty` part."""
    state = load_miner_work_state(project, name, version, work_ids)
    return state.rows, state.emptied, state.newer


def load_miner_work_state(
    project: Project, name: str, version: int, work_ids: Sequence[str]
) -> MinerWorkState:
    """`load_miner_rows` and, besides, the works that pass B reviewed to empty: those with no
    final row although pass B has opened and the work's passes are current. Such a work has no
    rows (its pass A rows, which pass B did not confirm, and the calibration rows are not
    served, and no older version is tried).

    A work with no row of `version` from any source, and not reviewed to empty, gets the rows of
    the newest older version of the miner that has rows for it (live pass A rows, else gold, else
    calibration of that version; final rows of an older version are not computed). Each row
    carries the version it belongs to; one work never mixes versions.

    The third part lists the works left with no row whose only live rows are of a version newer
    than `version`: they are not served (the listed version is the reader's contract) and are
    reported, so a caller states the gap instead of calling the work unmined.

    The fourth part (`gold_empty`) is the works, with no final or live pass A row of `version`,
    whose gold label in a calibration of `version` is empty and which have no non-empty gold label
    there. The researcher recorded that the paper has none of these claims: it is served no rows
    (not the calibration session's) and the older-version fallback is not applied to it. It is
    not a gap of the unknown kind. Production rows win over it, as over any gold."""
    unique = list(dict.fromkeys(work_ids))
    scope = MinerScope(name)
    finals: dict[str, list[RawMinerRow]] = {w: [] for w in unique}
    for final in final_rows_restricted(
        project, unique, scope=scope, ledger=scope_ledger(project, scope)
    ):
        finals[final.work_id].append(_raw("final", final.row_key, final.fields, version))
    lacking = [w for w in unique if not finals[w]]
    emptied = frozenset(_reviewed_by_pass_b(project, scope, lacking)) if lacking else frozenset()
    open_works = [w for w in lacking if w not in emptied]
    live: dict[int, dict[str, list[RawMinerRow]]] = {}
    if open_works:
        wanted = set(open_works)
        labels = _row_versions(project, name)
        for row in live_rows(project, PassLabel.A, scope=scope):
            if row.work_id in wanted:
                found = labels.get(row.extraction_id, version)
                live.setdefault(found, {}).setdefault(row.work_id, []).append(
                    _raw("pass-a-only", row.row_key, row.fields, found)
                )
    rows: dict[str, list[RawMinerRow]] = {
        w: finals[w] or list(live.get(version, {}).get(w, [])) for w in unique
    }
    rows.update({w: [] for w in emptied})
    older = sorted(
        {v for v in set(live) | _calibration_versions(project, name) if v < version}, reverse=True
    )
    gold_empty: set[str] = set()
    for tried in [version, *older]:
        needy = [w for w in open_works if not rows[w] and w not in gold_empty]
        if not needy:
            break
        if tried != version:
            for w in needy:
                rows[w] = list(live.get(tried, {}).get(w, []))
            needy = [w for w in needy if not rows[w]]
        if needy:
            gold, plain, empty = _gold_and_calibration(project, name, tried, scope, needy)
            for w in needy:
                if tried == version and w in empty:
                    gold_empty.add(w)
                    continue
                rows[w] = choose_rows([], gold.get(w, []), plain.get(w, []))
    newer = frozenset(
        w
        for w in open_works
        if not rows[w] and w not in gold_empty and any(v > version and w in live[v] for v in live)
    )
    return MinerWorkState(rows, emptied, newer, frozenset(gold_empty))


def load_miner_rows(
    project: Project, name: str, version: int, work_ids: Sequence[str]
) -> dict[str, list[RawMinerRow]]:
    """The rows of miner `name` for each work of `work_ids` (every work a key), read in batches,
    not per work. A work's rows are, in this order: its final rows (`final_rows_restricted`);
    else, unless pass B has reviewed the work to empty (no rows then; see `load_miner_work_rows`),
    its live pass A rows (`pass-a-only`); else, for a work in a calibration sample of `version`
    of the miner, the researcher's gold rows (`gold`, a non-empty label of any such calibration),
    else the calibration session's rows (`calibration`); an empty gold label of the listed
    version serves no rows at all (`load_miner_work_state`, `gold_empty`). The sources are never
    mixed for one work
    (`choose_rows`). Unscrubbed, unsorted beyond the reader's order. Read-only; the caller has
    synced the index."""
    return load_miner_work_rows(project, name, version, work_ids)[0]


def paper_profiles(project: Project, work_ids: Sequence[str]) -> list[PaperProfile]:
    """The profile of each work in `work_ids`, in the order given (duplicates once). Refused on
    field `work_ids`, with nothing read further, when an id is no work of the project. Read-only;
    a project without a protocol or without listed miners gives profiles without rows."""
    project.index.sync()
    with project.index.snapshot(), entering():  # one read view: no re-sync per reader
        return _paper_profiles(project, work_ids)


def _paper_profiles(project: Project, work_ids: Sequence[str]) -> list[PaperProfile]:
    unique = list(dict.fromkeys(work_ids))
    works = {w: get_work(project, w) for w in unique}
    unknown = [w for w, work in works.items() if work is None]
    if unknown:
        raise FactoryValidationError(
            [ValidationIssue("work_ids", f"unknown work id: {', '.join(unknown)}")]
        )
    # one entry per name: the highest listed version that is registered (else the highest listed)
    listed = listed_miner_versions(project)
    rows: dict[str, list[ProfileRow]] = {w: [] for w in unique}
    seen: dict[str, set[tuple[str, int]]] = {w: set() for w in unique}
    emptied: dict[str, set[tuple[str, int]]] = {w: set() for w in unique}
    newer_only: dict[str, set[tuple[str, int]]] = {w: set() for w in unique}
    gold_empty: dict[str, set[tuple[str, int]]] = {w: set() for w in unique}
    for name, version in listed:
        spec = registered_miner(project, name, version)
        if spec is None:
            continue
        names = _names_of(project, spec)
        state = load_miner_work_state(project, name, version, unique)
        loaded, reviewed, newer = state.rows, state.emptied, state.newer
        for work_id in state.gold_empty:
            gold_empty[work_id].add((name, version))
        for work_id in reviewed:
            emptied[work_id].add((name, version))
        for work_id in newer:
            newer_only[work_id].add((name, version))
        for work_id, raw_rows in loaded.items():
            if raw_rows:
                rows[work_id].extend(
                    _row(
                        spec,
                        names,
                        r.status,
                        r.row_key,
                        {k: (v[0], v[1]) for k, v in r.fields.items()},
                        r.version,
                    )
                    for r in raw_rows
                )
                seen[work_id].add((name, version))
    tokens = held_out_tokens(project, include_work_ids=False)
    profiles: list[PaperProfile] = []
    for work_id in unique:
        work = works[work_id]
        assert work is not None
        ordered = sorted(
            (_scrubbed(r, tokens) for r in rows[work_id]),
            key=lambda r: (r.miner, r.version, r.row_key),
        )
        profiles.append(
            PaperProfile(
                work_id,
                str(withhold(work.title, tokens)),
                str(work.dates.year or ""),
                tuple(ordered),
                tuple(
                    m
                    for m in listed
                    if m not in seen[work_id]
                    and m not in emptied[work_id]
                    and m not in newer_only[work_id]
                    and m not in gold_empty[work_id]
                ),
                tuple(m for m in listed if m in emptied[work_id]),
                tuple(m for m in listed if m in newer_only[work_id]),
                tuple(m for m in listed if m in gold_empty[work_id]),
            )
        )
    return profiles


def render_profile(profile: PaperProfile) -> str:
    """The profile as plain text: a header line `work_id · year · title`, then one line per miner
    (and status) `miner [status]: field=value; field=value | next row` (`miner [status] (v1): ...`
    for rows served from an older version than the listed one), ordered by miner name,
    then version; a line `missing: ...` lists the listed miners without rows, `gold-empty: ...`
    those for which the researcher recorded no claims (no rows by decision; not missing). Pure."""
    lines = [f"{profile.work_id} · {profile.year or 'n.d.'} · {profile.title}"]
    groups: dict[tuple[str, int, str], list[ProfileRow]] = {}
    for row in sorted(profile.rows, key=lambda r: (r.miner, r.version, r.row_key)):
        groups.setdefault((row.miner, row.version, row.status), []).append(row)
    for (miner, version, status), members in sorted(groups.items()):
        body = " | ".join("; ".join(f"{k}={v}" for k, v in m.fields) for m in members)
        tag = f" (v{version})" if members[0].older else ""
        lines.append(f"{miner} [{status}]{tag}: {body}")
    if profile.missing_miners:
        lines.append("missing: " + ", ".join(n for n, _ in profile.missing_miners))
    if profile.reviewed_empty:
        lines.append("reviewed-empty: " + ", ".join(n for n, _ in profile.reviewed_empty))
    if profile.newer_version_only:
        lines.append("newer-version-only: " + ", ".join(n for n, _ in profile.newer_version_only))
    if profile.gold_empty:
        lines.append("gold-empty: " + ", ".join(n for n, _ in profile.gold_empty))
    return "\n".join(lines)
