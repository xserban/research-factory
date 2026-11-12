"""Field-kind checks of registered miners, on top of plan D's verification (M-C ruling 4).

`kind_checks(spec)` is an `ExtraCheck` (G2-A): it runs on a row that already passed plan-D
verification, so quotes are verbatim in their anchors and numbers are in their quotes. It adds what
the kinds promise beyond that, each by the existing verifier and never by a copy of it:

- `citation`: `citation_markers` finds a marker in the field's verified quote.
- `anchor`: the pinned conversion's `Manifest` holds the anchor and its `AnchorKind` is listed.
- `work_ref(entry)`: the ordinal exists in the work's current G1 reference extraction pinned to the
  unit's conversion; the row stores `CitedEntry` as a contribution row does.
- `work_ref(title)`: `match_title` finds a corpus work among the candidates of the title's year
  window; an exact title resolves, a fuzzy one is accepted as `inferred`.
- `enum`: an evidence quote and anchor accompany the value (when the evidence rule asks).
- evidence rule: at least `min_quotes_per_record` fields of the row carry a verified quote.

Derived miners (spec.taxonomy set) differ in two ways and only those; every other miner is
unchanged:
- a row whose `category` is in `evidence.absence_values` is exempt from the quote rules
  (`min_quotes_per_record`, `enum_needs_quote`); every other row keeps them.
- `close_checks` also judges the unit as a whole, per work and pass, against the taxonomy and the
  work's layer (`unit_issues`): each applicable dimension has a row, `single` exactly one, `multi`
  at most `max_labels`, an absence row stands alone in its dimension, no row in a non-applicable
  dimension, no category twice.

Invariants:
- Reasons come from a fixed vocabulary (`NO_CITATION_MARKER` ...) and never carry document text.
- Issues are located `fields.<name>.<attr>`; the quote count is located `fields`.
- Title candidates are read by a bounded query (a year window of `work_title_buckets`), never the
  whole corpus.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from factory.document.anchors import Manifest
from factory.errors import ValidationIssue
from factory.extraction.citations import citation_markers
from factory.extraction.numbers import parse_printed
from factory.lineage.cited import marker_check
from factory.lineage.refs import ReferenceView
from factory.mining.spec import (
    AnchorKindRef,
    CitationKind,
    EnumKind,
    MinerSpec,
    WorkRefKind,
)
from factory.mining.taxonomy import Dimension, TaxonomySpec
from factory.model.extraction import CitedEntry, StoredField
from factory.model.references import Confidence, LinkState
from factory.model.search import QueryPurpose
from factory.references.match import Candidate, match_title
from factory.references.parse import RefFields
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.extraction import (
    CloseCheck,
    ExtraCheck,
    ExtractionRow,
    ExtraVerdict,
    UnitPin,
)
from factory.services.reference_view import reference_view_of
from factory.services.references import current_extraction
from factory.services.search import get_work

NO_CITATION_MARKER = "no-citation-marker"
ANCHOR_NOT_FOUND = "anchor-not-found"
ANCHOR_KIND = "anchor-kind"
ENTRY_NOT_FOUND = "entry-not-found"
WORK_NOT_FOUND = "work-not-found"
TOO_FEW_QUOTES = "too-few-quotes"
TAXONOMY_UNREGISTERED = "taxonomy-unregistered"
ENUM_NEEDS_QUOTE = "enum-needs-quote"
DIMENSION_UNFILLED = "dimension-unfilled"
DIMENSION_NOT_APPLICABLE = "dimension-not-applicable"
SINGLE_NEEDS_ONE = "single-dimension-needs-one-row"
TOO_MANY_LABELS = "too-many-labels"
ABSENCE_NOT_ALONE = "absence-row-not-alone"
DUPLICATE_CATEGORY = "duplicate-category"
CATEGORY_FIELD = "category"

_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
YEAR_WINDOW = 1
_EARLIEST_YEAR = 1800
"""The lowest year `_YEAR` can read: a title with no stated year is searched from here."""
_BATCH = 500
"""A title reference is looked for among works this many years either side of its quote's year."""


@dataclass(frozen=True)
class TitleRef:
    """A corpus work a title reference resolved to, and whether the title was an exact match
    (`stated`) or a fuzzy one (`inferred`)."""

    work_id: str
    state: Literal["stated", "inferred"]


def title_candidates(project: Project, lo: int, hi: int) -> list[Candidate]:
    """The corpus works with a year in `[lo, hi]`, by work id, as the reference resolver sees the
    corpus: only works with a non-probe provenance row, the `list_works` definition (a probe-only
    work is not a candidate and is never revealed; no work is filtered by role), and every
    active merge collapsed to its primary (an arXiv
    copy and its published copy are one candidate, so an exact title resolves instead of being
    ambiguous). A merge's members that differ in title stay as separate candidates for the same
    primary. The read is streamed in batches, bounded by the year window."""
    from factory.services.dedup import active_merges  # dedup imports the search services

    project.index.sync()
    primary = {a: m.primary for m in active_merges(project) for a in m.absorbed}
    found: dict[tuple[str, str], Candidate] = {}
    with project.index.connect() as conn:
        result = conn.execute(
            text(
                "SELECT work_id, title_norm, surname, year FROM work_title_buckets "
                "WHERE year BETWEEN :lo AND :hi AND work_id IN (SELECT work_id FROM provenance "
                "WHERE query_id NOT IN (SELECT query_id FROM queries WHERE purpose = :probe)) "
                "ORDER BY work_id"
            ),
            {"lo": lo, "hi": hi, "probe": QueryPurpose.PROBE.value},
        )
        while rows := result.fetchmany(_BATCH):
            for work, title, surname, year in rows:
                canonical = primary.get(str(work), str(work))
                found.setdefault(
                    (canonical, str(title)),
                    Candidate(
                        canonical,
                        str(title),
                        str(surname) or None,
                        None if year is None else int(year),
                        str(title),
                    ),
                )
    return sorted(found.values(), key=lambda c: (c.work_id, c.title))


def title_ref(
    project: Project, title: str, quote: str | None, citing_year: int | None = None
) -> TitleRef | None:
    """The corpus work `title` names, or None. The year comes from the quote, and candidates are
    the works within `YEAR_WINDOW` years of it. A quote that states no year widens the window to
    everything up to the citing work's year (`citing_year`), and the match is then only inferred;
    with no year from either, the title is not found."""
    found = _YEAR.search(quote or "")
    if found is None and citing_year is None:
        return None
    if found is None:
        assert citing_year is not None
        year = None
        lo, hi = _EARLIEST_YEAR, citing_year + YEAR_WINDOW
    else:
        year = int(found.group(1))
        lo, hi = year - YEAR_WINDOW, year + YEAR_WINDOW
    candidates = title_candidates(project, lo, hi)
    match = match_title(RefFields(None, None, None, year, None, title, None), candidates)
    if match.work_id is None:
        return None
    if match.state is LinkState.RESOLVED and match.confidence is Confidence.TITLE_EXACT:
        return TitleRef(match.work_id, "stated" if year is not None else "inferred")
    if match.state is LinkState.UNCONFIRMED:
        return TitleRef(match.work_id, "inferred")
    return None


def entry_link_state(project: Project, cited: CitedEntry) -> Literal["stated", "inferred"]:
    """`stated` when the cited entry's link is resolved (by identifier, exact title or a human's
    confirmation), `inferred` when it is unconfirmed, ambiguous or unresolved."""
    view = reference_view_of(project, cited.reference_extraction_id)
    entry = None if view is None else view.entry(cited.ordinal)
    return "stated" if entry is not None and entry.link_state is LinkState.RESOLVED else "inferred"


def _quotes(fields: Mapping[str, StoredField]) -> int:
    return sum(1 for f in fields.values() if f.quote is not None)


def _is_absence(spec: MinerSpec, fields: Mapping[str, StoredField]) -> bool:
    """True for a row of a derived miner whose category says the text states nothing; such a row
    needs no quote. A miner without a taxonomy never has an absence row."""
    if spec.taxonomy is None:
        return False
    cell = fields.get(CATEGORY_FIELD)
    return cell is not None and str(cell.value) in spec.evidence.absence_values


def applicable_dimensions(
    taxonomy: TaxonomySpec, chosen: Sequence[str], layer: str | None
) -> list[Dimension]:
    """The chosen dimensions that apply to a work of `layer` (None: pending), in taxonomy order:
    those with empty `applies_to_layers`, or listing the layer, and always dimension zero."""
    wanted = set(chosen)
    return [
        d
        for d in taxonomy.dimensions
        if d.id in wanted
        and (
            d.layer_scheme is not None
            or not d.applies_to_layers
            or (layer is not None and layer in d.applies_to_layers)
        )
    ]


def unit_issues(
    spec: MinerSpec,
    taxonomy: TaxonomySpec,
    layer: str | None,
    rows: Sequence[ExtractionRow],
) -> list[ValidationIssue]:
    """The closing issues of one unit of a derived miner (see the module docstring). Pure; the
    reasons are fixed and located `finish.<dimension>`, never carrying document text."""
    assert spec.taxonomy is not None
    applicable = {d.id: d for d in applicable_dimensions(taxonomy, spec.taxonomy.dimensions, layer)}
    chosen = set(spec.taxonomy.dimensions)
    by_dimension: dict[str, list[str]] = {}
    issues: list[ValidationIssue] = []
    for row in rows:
        cell = row.fields.get(CATEGORY_FIELD)
        if cell is None:
            continue
        value = str(cell.value)
        dimension_id = value.split("/", 1)[0]
        if dimension_id not in chosen:
            continue
        by_dimension.setdefault(dimension_id, []).append(value)
    for dimension_id, values in by_dimension.items():
        if dimension_id not in applicable:
            issues.append(ValidationIssue(f"finish.{dimension_id}", DIMENSION_NOT_APPLICABLE))
        if len(set(values)) != len(values):
            issues.append(ValidationIssue(f"finish.{dimension_id}", DUPLICATE_CATEGORY))
    for dimension_id, dimension in applicable.items():
        values = by_dimension.get(dimension_id, [])
        where = f"finish.{dimension_id}"
        if not values:
            issues.append(ValidationIssue(where, DIMENSION_UNFILLED))
            continue
        if dimension.cardinality == "single" and len(values) != 1:
            issues.append(ValidationIssue(where, SINGLE_NEEDS_ONE))
        if (
            dimension.cardinality == "multi"
            and dimension.max_labels is not None
            and len(values) > dimension.max_labels
        ):
            issues.append(ValidationIssue(where, TOO_MANY_LABELS))
        if len(values) > 1 and any(v in spec.evidence.absence_values for v in values):
            issues.append(ValidationIssue(where, ABSENCE_NOT_ALONE))
    return issues


def kind_checks(spec: MinerSpec) -> ExtraCheck:
    """The `ExtraCheck` of `spec` (see the module docstring). It holds no state across calls
    but a per-unit cache of the manifest and the reference view."""
    manifests: dict[str, Manifest] = {}
    views: dict[UnitPin, ReferenceView | None] = {}

    def view_of(project: Project, pin: UnitPin) -> ReferenceView | None:
        if pin not in views:
            extraction = current_extraction(project, pin.work_id)
            view = None if extraction is None else reference_view_of(project, extraction)
            views[pin] = (
                view if view is not None and view.conversion_id == pin.conversion_id else None
            )
        return views[pin]

    def check(
        project: Project,
        pin: UnitPin,
        fields: Mapping[str, StoredField],
        seen: Sequence[ExtractionRow],
    ) -> ExtraVerdict:
        del seen
        issues: list[ValidationIssue] = []
        cited: CitedEntry | None = None
        absent = _is_absence(spec, fields)
        for declared in spec.fields:
            stored = fields.get(declared.name)
            if stored is None:
                continue
            kind, where = declared.kind, f"fields.{declared.name}"
            if isinstance(kind, CitationKind):
                if not citation_markers(stored.quote or "", kind.patterns):
                    issues.append(ValidationIssue(f"{where}.quote", NO_CITATION_MARKER))
            elif isinstance(kind, AnchorKindRef):
                if pin.conversion_id not in manifests:
                    manifests[pin.conversion_id] = conversion_manifest(project, pin.conversion_id)
                anchor = manifests[pin.conversion_id].get(str(stored.value))
                if anchor is None:
                    issues.append(ValidationIssue(f"{where}.value", ANCHOR_NOT_FOUND))
                elif anchor.kind not in kind.kinds:
                    issues.append(ValidationIssue(f"{where}.value", ANCHOR_KIND))
            elif isinstance(kind, WorkRefKind) and kind.by == "entry":
                view = view_of(project, pin)
                ordinal = int(parse_printed(stored.value) or 0)
                if view is None or view.entry(ordinal) is None:
                    issues.append(ValidationIssue(f"{where}.value", ENTRY_NOT_FOUND))
                elif cited is None:
                    marker = (
                        marker_check(stored.quote, stored.anchor, ordinal, view.contexts)
                        if stored.quote is not None and stored.anchor is not None
                        else "absent"
                    )
                    cited = CitedEntry(
                        reference_extraction_id=view.extraction_id, ordinal=ordinal, marker=marker
                    )
            elif isinstance(kind, WorkRefKind):
                citing = get_work(project, pin.work_id)
                citing_year = None if citing is None else citing.dates.year
                if title_ref(project, str(stored.value), stored.quote, citing_year) is None:
                    issues.append(ValidationIssue(f"{where}.value", WORK_NOT_FOUND))
            elif (
                isinstance(kind, EnumKind)
                and spec.evidence.enum_needs_quote
                and not absent
                and (stored.quote is None or stored.anchor is None)
            ):
                issues.append(ValidationIssue(f"{where}.quote", ENUM_NEEDS_QUOTE))
        if not absent and _quotes(fields) < spec.evidence.min_quotes_per_record:
            issues.append(ValidationIssue("fields", TOO_FEW_QUOTES))
        return ExtraVerdict(cited=cited, issues=issues)

    return check


def close_checks(spec: MinerSpec) -> CloseCheck:
    """The `CloseCheck` of `spec`: every row live after a closing call carries at least
    `min_quotes_per_record` verified quotes (issue on `finish`), an absence row of a derived miner
    excepted. For a derived miner the unit is also judged by `unit_issues`, against the registered
    taxonomy and the work's layer. A taxonomy version that is not registered refuses the close
    (`taxonomy-unregistered`, located `finish`): the unit cannot be judged, so it cannot close."""

    def close(
        project: Project, pin: UnitPin, rows: Sequence[ExtractionRow], reason: str | None
    ) -> list[ValidationIssue]:
        del reason
        short = [
            r
            for r in rows
            if _quotes(r.fields) < spec.evidence.min_quotes_per_record
            and not _is_absence(spec, r.fields)
        ]
        issues = [ValidationIssue("finish", TOO_FEW_QUOTES)] if short else []
        if spec.taxonomy is not None:
            from factory.services.taxonomies import registered_taxonomy
            from factory.services.work_layers import layer_of

            taxonomy = registered_taxonomy(project, spec.taxonomy.name, spec.taxonomy.version)
            if taxonomy is None:
                issues.append(ValidationIssue("finish", TAXONOMY_UNREGISTERED))
            else:
                layer = layer_of(project, pin.work_id).layer
                issues.extend(unit_issues(spec, taxonomy, layer, rows))
        return issues

    return close
