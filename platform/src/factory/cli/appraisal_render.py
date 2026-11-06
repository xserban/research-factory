"""Plain-text renderers of appraisal (plan EQ). Items are listed one by one; no line carries a
total, a weight, a grade or an order by quality (decision 42)."""

from __future__ import annotations

from factory.services.appraisal_judgements import (
    AgreementBySpan,
    AppraisalSheet,
    AppraisalStatus,
    Disagreement,
    PassAnswer,
)


def status_lines(status: AppraisalStatus) -> list[str]:
    if not status.declared:
        return ["appraisal: no instrument declared"]
    states = ", ".join(f"{k} {v}" for k, v in status.span_cells.items()) or "none"
    return [
        f"instrument: {status.instrument}",
        f"works: {status.works}",
        f"span items: {states}",
        f"judgement items: open {status.judgement_items_open}, "
        f"recorded {status.judgement_items_recorded}",
        f"stale works: {status.stale_works}",
    ]


def _passed(label: str, value: PassAnswer | None) -> list[str]:
    if value is None:
        return [f"    pass {label}: -"]
    lines = [f"    pass {label}: {value.answer.value}"]
    if value.anchor or value.quote:
        lines.append(f"      [{value.anchor or '-'}] {value.quote or ''}")
    return lines


def sheet_lines(sheet: AppraisalSheet) -> list[str]:
    lines = [f"work {sheet.work_id}  instrument {sheet.instrument}", "computed items:"]
    for platform in sheet.platform:
        where = f" at {platform.anchor}" if platform.anchor else ""
        lines.append(f"  {platform.item}: {platform.status}{where}")
    lines.append("span items:")
    for span in sheet.spans:
        final = span.answer.value if span.answer is not None else "-"
        lines.append(f"  {span.item}: {span.state} ({final})  {span.statement}")
        lines += _passed("A", span.a)
        lines += _passed("B", span.b)
    lines.append("judgement items:")
    for judgement in sheet.judgements:
        if judgement.answer is None:
            lines.append(f"  {judgement.item}: open  {judgement.statement}")
        else:
            lines.append(
                f"  {judgement.item}: {judgement.answer.value}  because {judgement.rationale}"
            )
    return lines


def agreement_lines(by_item: list[AgreementBySpan], open_: list[Disagreement]) -> list[str]:
    lines = ["agreement by item:"]
    lines += [
        f"  {a.item}: {a.agreed} of {a.compared} agree, {a.disagreed} differ" for a in by_item
    ]
    lines.append(f"open disagreements: {len(open_)}")
    lines += [f"  {d.work_id}  {d.item}  A {d.a.value}  B {d.b.value}" for d in open_]
    return lines
