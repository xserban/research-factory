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
  neither, and in the miner's calibration sample, takes the researcher's gold rows (status `gold`,
  non-empty labels), else the calibration session's rows (status `calibration`). A work with none
  of these is in `missing_miners`. Rows of the one status are never mixed for a work and miner.
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
from factory.services.extraction import calibration_task_ids, live_rows, scope_ledger
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
    "PaperProfile",
    "ProfileRow",
    "RawMinerRow",
    "category_names",
    "choose_rows",
    "listed_miner_versions",
    "load_miner_rows",
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


@dataclass(frozen=True)
class PaperProfile:
    """Everything the listed miners found in one work. `missing_miners` are the listed
    `(name, version)` with no row at all for the work."""

    work_id: str
    title: str
    year: str
    rows: tuple[ProfileRow, ...]
    missing_miners: tuple[tuple[str, int], ...]


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
) -> ProfileRow:
    fields: list[tuple[str, str]] = []
    for field in _ordered(spec, stored):
        value, unit = stored[field]
        shown = _short(spec, names, field, value)
        if shown:
            fields.append((field, f"{shown} {unit}" if unit else shown))
    return ProfileRow(spec.name, spec.version, status, row_key, tuple(fields))


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


def _raw(status: str, row_key: str, fields: Mapping[str, Any]) -> RawMinerRow:
    return RawMinerRow(
        status, row_key, {k: (f.value, f.unit, f.anchor, f.quote) for k, f in fields.items()}
    )


def _calibration_units(
    project: Project, name: str, work_ids: Sequence[str]
) -> dict[str, tuple[str, int]]:
    """For each work of `work_ids` in a calibration sample of miner `name`, the
    `(calibration_id, version)` of the highest version that drew it."""
    wanted = set(work_ids)
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT u.work_id, c.calibration_id, c.version FROM miner_calibration_units u "
                "JOIN miner_calibrations c ON c.calibration_id = u.calibration_id "
                "WHERE c.name = :n ORDER BY c.version, c.event_id"
            ),
            {"n": name},
        ).all()
    return {str(w): (str(c), int(v)) for w, c, v in found if str(w) in wanted}


def _gold_and_calibration(
    project: Project, name: str, scope: MinerScope, work_ids: Sequence[str]
) -> tuple[dict[str, list[RawMinerRow]], dict[str, list[RawMinerRow]]]:
    """The researcher's gold rows and the calibration session's rows of the works that are in a
    calibration sample of `name`, each read once for all of them. An empty gold label is no gold."""
    units = _calibration_units(project, name, work_ids)
    gold: dict[str, list[RawMinerRow]] = {}
    plain: dict[str, list[RawMinerRow]] = {}
    if not units:
        return gold, plain
    for cid in {c for c, _ in units.values()}:
        mine = {w for w, (c, _) in units.items() if c == cid}
        for work, labelled in calibration_labels(project, cid).items():
            if work in mine and labelled:
                gold[work] = [_raw("gold", r.row_key, r.fields) for r in labelled]
        apart = calibration_task_ids(project, scope, cid)
        for row in live_rows(project, None, scope=scope, calibration=True):
            if row.work_id in mine and row.task_id in apart:
                plain.setdefault(row.work_id, []).append(
                    _raw("calibration", row.row_key, row.fields)
                )
    return gold, plain


def load_miner_rows(
    project: Project, name: str, work_ids: Sequence[str]
) -> dict[str, list[RawMinerRow]]:
    """The rows of miner `name` for each work of `work_ids` (every work a key), read in batches,
    not per work. A work's rows are, in this order: its final rows (`final_rows_restricted`);
    else its live pass A rows (`pass-a-only`); else, for a work in the miner's calibration sample,
    the researcher's gold rows (`gold`, a non-empty label); else the calibration session's rows
    (`calibration`). The sources are never mixed for one work (`choose_rows`). Unscrubbed,
    unsorted beyond the reader's order. Read-only; the caller has synced the index."""
    unique = list(dict.fromkeys(work_ids))
    scope = MinerScope(name)
    finals: dict[str, list[RawMinerRow]] = {w: [] for w in unique}
    for final in final_rows_restricted(
        project, unique, scope=scope, ledger=scope_ledger(project, scope)
    ):
        finals[final.work_id].append(_raw("final", final.row_key, final.fields))
    lacking = [w for w in unique if not finals[w]]
    live: dict[str, list[RawMinerRow]] = {}
    if lacking:
        wanted = set(lacking)
        for row in live_rows(project, PassLabel.A, scope=scope):
            if row.work_id in wanted:
                live.setdefault(row.work_id, []).append(
                    _raw("pass-a-only", row.row_key, row.fields)
                )
    needy = [w for w in lacking if not live.get(w)]
    gold, plain = _gold_and_calibration(project, name, scope, needy) if needy else ({}, {})
    return {
        w: choose_rows(finals[w] or live.get(w, []), gold.get(w, []), plain.get(w, []))
        for w in unique
    }


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
    for name, version in listed:
        spec = registered_miner(project, name, version)
        if spec is None:
            continue
        names = _names_of(project, spec)
        for work_id, raw_rows in load_miner_rows(project, name, unique).items():
            if raw_rows:
                rows[work_id].extend(
                    _row(
                        spec,
                        names,
                        r.status,
                        r.row_key,
                        {k: (v[0], v[1]) for k, v in r.fields.items()},
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
                tuple(m for m in listed if m not in seen[work_id]),
            )
        )
    return profiles


def render_profile(profile: PaperProfile) -> str:
    """The profile as plain text: a header line `work_id · year · title`, then one line per miner
    (and status) `miner [status]: field=value; field=value | next row`, ordered by miner name,
    then version; a line `missing: ...` lists the listed miners without rows. Pure."""
    lines = [f"{profile.work_id} · {profile.year or 'n.d.'} · {profile.title}"]
    groups: dict[tuple[str, int, str], list[ProfileRow]] = {}
    for row in sorted(profile.rows, key=lambda r: (r.miner, r.version, r.row_key)):
        groups.setdefault((row.miner, row.version, row.status), []).append(row)
    for (miner, _version, status), members in sorted(groups.items()):
        body = " | ".join("; ".join(f"{k}={v}" for k, v in m.fields) for m in members)
        lines.append(f"{miner} [{status}]: {body}")
    if profile.missing_miners:
        lines.append("missing: " + ", ".join(n for n, _ in profile.missing_miners))
    return "\n".join(lines)
