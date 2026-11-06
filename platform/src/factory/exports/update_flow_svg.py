"""The PRISMA 2020 update flow ("identification of new studies via databases, registers and other
sources") as SVG (slice 7b Later; plan XL task 6).

The same fixed template as `prisma_svg`, over an `UpdateFlow`: the boxes show only the records new
in the update window, and a last box carries the totals (previously included, newly included, the
total, and the previously included studies a correction touched). Every number is read from the
flow; the renderer does no arithmetic on counts (R-05). The output is a pure function of the flow.
"""

from factory.exports.prisma_svg import (
    NOT_RUN,
    Row,
    _count,
    _lines,
    _reasons,
    render_rows,
)
from factory.services.prisma_update import UpdateFlow

UPDATE_TEMPLATE_VERSION = 1


def update_flow_svg(flow: UpdateFlow) -> str:
    """The update flow as an SVG document. Deterministic for equal flows."""
    boxes = flow.full_text
    ran = boxes.stage_run
    banner: str | None = None
    if flow.pending:
        banner = f"Provisional: {flow.pending} records pending"
    elif boxes.provisional:
        banner = f"Provisional: {boxes.pending} reports pending"

    databases = _lines(
        "New records identified from databases",
        _reasons(flow.identified_databases) or ["none"],
    )
    other = _lines(
        "New records identified from other methods",
        _reasons(flow.identified_other) or ["none"],
    )
    duplicates = _lines(_count("Duplicate records removed", flow.duplicates_removed), [])
    screened = _lines(_count("Records screened", flow.screened), [])
    excluded = _lines(_count("Records excluded", flow.excluded_total), _reasons(flow.excluded))
    sought = _lines(_count("Reports sought for retrieval", boxes.sought), [])
    not_retrieved = _lines(
        _count("Reports not retrieved", boxes.not_retrieved),
        _reasons(boxes.not_retrieved_reasons),
    )
    if ran:
        assessed = _lines(_count("Reports assessed for eligibility", boxes.assessed), [])
        ft_excluded = _lines(
            _count("Reports excluded", boxes.excluded_total), _reasons(boxes.excluded)
        )
        new_included = _lines(_count("New studies included in review", boxes.included), [])
    else:
        assessed = _lines("Reports assessed for eligibility", [NOT_RUN])
        ft_excluded = _lines("Reports excluded", [NOT_RUN])
        new_included = _lines("New studies included in review", [NOT_RUN])
    totals = _lines(
        _count("Total studies included in review", flow.total_included),
        [
            _count("Included in the previous version", flow.previous_included),
            _count("Previous studies with changes", len(flow.changed_previous)),
        ],
    )
    rows: list[Row] = [
        (databases, other),
        (duplicates, None),
        (screened, excluded),
        (sought, not_retrieved),
        (assessed, ft_excluded),
        (new_included, None),
        (totals, None),
    ]
    return render_rows(rows, banner)
