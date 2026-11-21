"""The evidence note of a brief (plan tiers-and-autonomy, lane L9): the computed part.

`brief_note(project)` gathers what a cited note may rest on, from existing builders only: the
question, the PRISMA flow (`prisma_flow`), the included works with their final extracted rows and
the extracted claims (`evidence_report`), the claim contradictions of the finder, the tier's caps
(`factory.tiers.plan_for`), the report label and the level statement. The agent writes at most a
short synthesis around it; the platform computes counts and the quote table only.

Invariants:
- Read-only; nothing is written. No counts or quotes are typed: every number is a computed field.
- A claim is a finding only when its quote is `accepted` by `chat_verify` (the same check as the
  chat tool). Every other claim is listed as unverified, with the verifier's status, and never
  appears among the findings.
- A project with no included works or rows renders an honest empty note, not an error.
- The label is `report_label(tier)` ('' for `pilot`, `systematic` and a legacy project), and the
  level statement is always present.
"""

from __future__ import annotations

from collections.abc import Sequence

from factory.model.base import StrictModel
from factory.model.levels import Tier
from factory.services import agent_view
from factory.services.chat_read import VerifyItem, chat_verify
from factory.services.context import Project
from factory.services.evidence_report import (
    ClaimEntry,
    EvidenceReport,
    EvidenceRow,
    evidence_report,
)
from factory.services.finders import list_contradictions
from factory.services.level_statement import level_statement, render_level_statement
from factory.services.prisma import PrismaFlow, prisma_flow
from factory.services.project import project_levels
from factory.services.question import current_question, goals
from factory.tiers import plan_for, report_label

ACCEPTED = "accepted"
"""The `chat_verify` status of a quote found in its anchor."""

NO_FINDINGS = "No claim has a verified quote, so the note states no finding."


class NoteRow(StrictModel):
    """One final extracted row of an included work, as the evidence report shows it."""

    row_key: str
    method: str | None
    variant: str | None
    value: str
    unit: str | None
    status: str
    anchor: str | None
    quote: str | None


class NoteWork(StrictModel):
    work_id: str
    title: str
    rows: tuple[NoteRow, ...]


class NoteClaim(StrictModel):
    """A claim with the outcome of its quote check; `verified` is `status == accepted`."""

    claim_id: str
    work_id: str
    title: str
    claim_type: str
    evidence_type: str
    strength: str
    statement: str
    anchor: str
    quote: str
    verified: bool
    status: str


class NoteContradiction(StrictModel):
    contradiction_id: str
    work_a: str
    work_b: str
    state: str


class NoteCap(StrictModel):
    """One cap of the tier's plan (a stage cap or a run limit)."""

    label: str
    value: int


class BriefNote(StrictModel):
    project: str
    tier: Tier | None
    label: str
    question: str | None
    flow: PrismaFlow
    works: tuple[NoteWork, ...]
    verified_claims: tuple[NoteClaim, ...]
    unverified_claims: tuple[NoteClaim, ...]
    contradictions: tuple[NoteContradiction, ...]
    caps: tuple[NoteCap, ...]
    limits: tuple[str, ...]
    provisional: bool
    level_lines: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not self.works and not self.verified_claims and not self.unverified_claims


def _question(project: Project) -> str | None:
    current = current_question(project)
    if current is not None:
        return current.spec.primary_question
    stated = goals(project)
    return stated[-1].text if stated else None


def _rows(report: EvidenceReport) -> list[EvidenceRow]:
    rows = [r for g in report.groups for r in g.rows]
    return [*rows, *report.ungrouped]


def _note_row(row: EvidenceRow) -> NoteRow:
    return NoteRow(
        row_key=row.row_key,
        method=row.method_name,
        variant=row.variant,
        value=str(row.value.value),
        unit=row.value.unit,
        status=row.status,
        anchor=row.value.anchor,
        quote=row.value.quote,
    )


def _works(rows: Sequence[EvidenceRow]) -> tuple[NoteWork, ...]:
    by_work: dict[str, list[EvidenceRow]] = {}
    for row in rows:
        by_work.setdefault(row.work_id, []).append(row)
    return tuple(
        NoteWork(
            work_id=work_id,
            title=group[0].title,
            rows=tuple(_note_row(r) for r in sorted(group, key=lambda r: r.row_key)),
        )
        for work_id, group in sorted(by_work.items())
    )


def _claims(
    project: Project, report: EvidenceReport, titles: dict[str, str]
) -> tuple[list[NoteClaim], list[NoteClaim]]:
    entries: list[ClaimEntry] = sorted(
        (c for group in report.claims.values() for c in group), key=lambda c: c.claim_id
    )
    results = chat_verify(project, [VerifyItem(c.work_id, c.anchor, c.quote) for c in entries])
    good: list[NoteClaim] = []
    bad: list[NoteClaim] = []
    for entry, result in zip(entries, results, strict=True):
        claim = NoteClaim(
            claim_id=entry.claim_id,
            work_id=entry.work_id,
            title=titles.get(entry.work_id, ""),
            claim_type=entry.claim_type.value,
            evidence_type=entry.evidence_type.value,
            strength=entry.strength.value,
            statement=entry.statement,
            anchor=entry.anchor,
            quote=entry.quote,
            verified=result.status == ACCEPTED,
            status=result.status,
        )
        (good if claim.verified else bad).append(claim)
    return good, bad


def _caps(tier: Tier | None) -> tuple[NoteCap, ...]:
    if tier is None:
        return ()
    plan = plan_for(tier)
    caps: list[NoteCap] = []
    if plan.limits is not None:
        caps += [
            NoteCap(label="papers", value=plan.limits.max_papers),
            NoteCap(label="minutes", value=plan.limits.max_minutes),
            NoteCap(label="runs", value=plan.limits.max_runs),
        ]
    for stage in plan.stages:
        if not stage.skipped:
            caps += [
                NoteCap(label=f"{stage.label}: {name}", value=value)
                for name, value in stage.caps.items()
            ]
    return tuple(caps)


def brief_note(project: Project, *, full: bool = True) -> BriefNote:
    """The note of `project`. `full=False` is the agent variant of the evidence report (no
    label-derived audit rate); the caller scrubs the rendered text as the other reports do."""
    tier = project_levels(project).tier
    report = evidence_report(project) if full else agent_view.agent_evidence(project)
    rows = _rows(report)
    works = _works(rows)
    titles = {w.work_id: w.title for w in works}
    verified, unverified = _claims(project, report, titles)
    contradictions = tuple(
        NoteContradiction(
            contradiction_id=c.contradiction_id,
            work_a=c.work_a,
            work_b=c.work_b,
            state=c.state,
        )
        for c in list_contradictions(project, states=("confirmed", "inferred"))
    )
    return BriefNote(
        project=project.paths.slug,
        tier=tier,
        label=report_label(tier) if tier is not None else "",
        question=_question(project),
        flow=prisma_flow(project),
        works=works,
        verified_claims=tuple(verified),
        unverified_claims=tuple(unverified),
        contradictions=contradictions,
        caps=_caps(tier),
        limits=tuple(x.text for x in report.limits),
        provisional=report.provisional,
        level_lines=tuple(render_level_statement(level_statement(project)).splitlines()),
    )


def _flat(text: str) -> str:
    return " ".join(text.split())


def render_brief_note(note: BriefNote) -> str:
    """The note as Markdown in the plain style of the other reports. Verified quotes come first
    and are the only findings; unverified claims are listed apart and marked."""
    flow = note.flow
    out = ["# Evidence note", ""]
    if note.label:
        out += [f"**{_flat(note.label)}**", ""]
    out += ["## Level", ""]
    out += [f"- {line}" for line in note.level_lines]
    out += ["", "## Question", "", note.question or "No question recorded.", ""]
    out += ["## Search and screening", ""]
    identified = sum(flow.identified_databases.values()) + sum(flow.identified_other.values())
    out += [
        f"- records identified: {identified}",
        f"- duplicates removed: {flow.duplicates_removed}",
        f"- screened: {flow.screened}",
        f"- excluded: {sum(flow.excluded.values())}",
        f"- pending: {flow.pending}",
        f"- included at title and abstract: {flow.included}",
    ]
    if flow.included_in_review is not None:
        out.append(f"- included in the review: {flow.included_in_review}")
    if flow.provisional:
        out.append("- provisional: screening is not complete")
    out += ["", "## Limits", ""]
    out += [f"- cap {c.label}: {c.value}" for c in note.caps]
    out += [f"- {_flat(x)}" for x in note.limits]
    if not note.caps and not note.limits:
        out.append("- none stated")
    out += ["", "## Included works and extracted rows", ""]
    if not note.works:
        out += ["No included work has a final extracted row.", ""]
    for work in note.works:
        out += [f"### {work.work_id}: {_flat(work.title)}", ""]
        for row in work.rows:
            unit = f" {row.unit}" if row.unit else ""
            what = ", ".join(x for x in (row.method, row.variant) if x) or row.row_key
            cite = f' [{row.anchor}] "{_flat(row.quote)}"' if row.anchor and row.quote else ""
            out.append(f"- {_flat(what)}: {_flat(row.value)}{unit} ({row.status}){cite}")
        out.append("")
    out += ["## Findings with verified quotes", ""]
    if note.verified_claims:
        for c in note.verified_claims:
            out.append(
                f"- {c.claim_id} ({c.work_id}, {c.evidence_type}, {c.strength}): "
                f'{_flat(c.statement)} [{_flat(c.anchor)}] "{_flat(c.quote)}"'
            )
    else:
        out.append(NO_FINDINGS)
    out.append("")
    if note.unverified_claims:
        out += ["## Unverified claims (not findings)", ""]
        for c in note.unverified_claims:
            out.append(
                f"- UNVERIFIED {c.claim_id} ({c.work_id}): {_flat(c.statement)} "
                f"(quote check: {c.status})"
            )
        out.append("")
    out += ["## Contradictions", ""]
    for x in note.contradictions:
        out.append(f"- {x.contradiction_id}: {x.work_a} against {x.work_b} ({x.state})")
    if not note.contradictions:
        out.append("None recorded.")
    out.append("")
    return "\n".join(out)
