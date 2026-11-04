"""Builders for evidence-report tests (plan E).

Two kinds of world:

- A synthetic, pilot-shaped set of final rows (`pilot_inputs`) fed to the pure `assemble_report`:
  included works w1-w6; group G1 = imagenet-1k / top-1 accuracy / 224 / none with rows of four
  works (two own, one declared cited, one own with a citation marker), a 384 group whose two
  own rows disagree on one method, a single-paper ADE20K group, a copied-only CIFAR-100 group, a
  row missing `split`, a row without `value`, an unresolved and a stale row, and w6 with no row.
- A service world (`run_pass`) on the synthetic conversion of plan D's tests, for the paths that
  read the projection.

Values are invented identifiers and numbers; no literature text.
"""

from collections.abc import Callable, Sequence

from factory.events.envelope import Actor
from factory.model.extraction import (
    ClaimInput,
    ClaimType,
    EvidenceType,
    ExtractedRowInput,
    ReportedIn,
    Strength,
)
from factory.model.screening import PassLabel
from factory.packs import ML_BENCHMARK_V1
from factory.services.context import Project
from factory.services.evidence_report import ReportInputs
from factory.services.extraction import ClaimRow, extract_next, extract_record
from factory.services.extraction_agreement import (
    AgreementOverall,
    FieldDisagreement,
    FinalField,
    FinalRow,
    group_rows,
)

PACK = ML_BENCHMARK_V1
KEYS = ("task", "dataset", "split", "metric", "input_resolution", "pretraining_data")
POPULATION = ("rf:w1", "rf:w2", "rf:w3", "rf:w4", "rf:w5", "rf:w6")
TITLES = {w: f"Title {w[-1]}" for w in POPULATION}


def ff(
    value: str | bool,
    *,
    unit: str | None = None,
    canon: str | None = None,
    cited: bool = False,
    marker: bool = False,
    extraction_id: str = "ext_0001",
    quote: str | None = None,
) -> FinalField:
    """A final field. A marker makes the field effectively cited, as `final_field` does."""
    return FinalField(
        value=value,
        unit=unit,
        canonical=canon,
        anchor="t1",
        cell="t1.r3.c2",
        quote=quote if quote is not None else (value if isinstance(value, str) else None),
        reported_in=ReportedIn.CITED if cited or marker else ReportedIn.OWN,
        copy_marker=marker,
        reproduced=False,
        cited_work=None,
        extraction_id=extraction_id,
    )


def frow(
    work: str,
    key: str,
    method: str,
    value: str | None,
    *,
    dataset: str = "ImageNet-1K",
    metric: str = "Top-1 Accuracy",
    resolution: str = "224",
    split: str | None = "val",
    task: str = "image classification",
    pretraining: str = "none",
    cited: bool = False,
    marker: bool = False,
    status: str = "agreed",
    **extra: FinalField,
) -> FinalRow:
    fields: dict[str, FinalField] = {
        "method_name": ff(method),
        "task": ff(task),
        "dataset": ff(dataset),
        "metric": ff(metric),
        "input_resolution": ff(resolution),
        "pretraining_data": ff(pretraining),
        **extra,
    }
    if split is not None:
        fields["split"] = ff(split)
    if value is not None:
        fields["value"] = ff(
            value,
            unit="%",
            canon=value,
            cited=cited,
            marker=marker,
            extraction_id=f"ext_{work[-1]}{key[-2:]}",
        )
    return FinalRow.model_validate(
        {
            "work_id": work,
            "document_id": f"doc_{work[-1]}",
            "conversion_id": f"cnv_{work[-1]}",
            "row_key": key,
            "status": status,
            "fields": fields,
            "independent": value is not None and not (cited or marker),
        }
    )


def pilot_rows() -> list[FinalRow]:
    return [
        # G1: imagenet-1k / top-1 / 224 / none, four works, two own and two copied.
        frow("rf:w1", "rk_000000000101", "Ours-S", "81.2"),
        frow("rf:w2", "rk_000000000201", "DeiT-S", "79.8", resolution="224x224"),
        frow("rf:w3", "rk_000000000301", "DeiT-S", "79.8", cited=True),
        frow("rf:w4", "rk_000000000401", "DeiT-S", "79.8", marker=True),
        # 384 group: one method, two works, two own values.
        frow("rf:w1", "rk_000000000102", "Swin-T", "80.1", resolution="384"),
        frow("rf:w2", "rk_000000000202", "Swin-T", "79.8", resolution="384"),
        # Single-paper ADE20K group.
        frow(
            "rf:w5",
            "rk_000000000501",
            "Ours-Seg",
            "45.1",
            task="semantic segmentation",
            dataset="ADE20K",
            metric="mIoU",
            resolution="512",
        ),
        # Copied-only group.
        frow("rf:w3", "rk_000000000302", "ResNet-50", "77.0", dataset="CIFAR-100", cited=True),
        # Ungrouped: no split.
        frow("rf:w5", "rk_000000000502", "Ours-Seg", "44.0", split=None),
        # A final row without value (a parallel D fix makes this impossible; never crash).
        frow("rf:w4", "rk_000000000402", "DeiT-S", None),
    ]


def disagreement(work: str, key: str) -> FieldDisagreement:
    return FieldDisagreement(work_id=work, row_key=key, field="task", kind="value", a=None, b=None)


def claim(
    claim_id: str, work: str, claim_type: ClaimType, statement: str = "Statement."
) -> ClaimRow:
    return ClaimRow(
        claim_id=claim_id,
        work_id=work,
        pass_label=PassLabel.A,
        claim_type=claim_type,
        evidence_type=EvidenceType.EXPERIMENT,
        strength=Strength.MODERATE,
        statement=statement,
        anchor="s3.p1",
        quote="Lorem ipsum dolor sit amet.",
        document_id=f"doc_{work[-1]}",
        conversion_id=f"cnv_{work[-1]}",
        event_id=f"evt_{claim_id}",
    )


def pilot_inputs(
    rows: Sequence[FinalRow] | None = None,
    *,
    keys: Sequence[str] = KEYS,
    unresolved: Sequence[FieldDisagreement] = (),
    stale: Sequence[tuple[str, str]] = (),
    claims: Sequence[ClaimRow] = (),
    pass_b_open: bool = True,
    blocking: bool = False,
    population: Sequence[str] = POPULATION,
) -> ReportInputs:
    grouped = group_rows(pilot_rows() if rows is None else rows, PACK, keys)
    return ReportInputs(
        protocol_id="P@3",
        pack=PACK,
        keys=tuple(keys),
        grouped=grouped.model_copy(update={"unresolved": list(unresolved)}),
        stale=tuple(stale),
        population=tuple(population),
        titles=TITLES,
        claims=tuple(claims),
        pass_b_open=pass_b_open,
        blocking=blocking,
        agreement=AgreementOverall(
            overall=0.95, dual=4, single=2, rows_aligned=7, rows_unmatched=0
        ),
        audit=None,
        audit_outstanding=True,
    )


# --- Service world ---

RowsFor = Callable[[str], list[ExtractedRowInput]]
ClaimsFor = Callable[[str], list[ClaimInput]]


def claim_input(claim_type: ClaimType = ClaimType.FINDING) -> ClaimInput:
    return ClaimInput(
        statement="The method is described in the method section.",
        claim_type=claim_type,
        evidence_type=EvidenceType.EXPERIMENT,
        strength=Strength.MODERATE,
        anchor="s3.p1",
        quote="Lorem ipsum dolor sit amet.",
    )


def run_pass(
    project: Project,
    actor: Actor,
    label: PassLabel,
    rows_for: RowsFor,
    claims_for: ClaimsFor = lambda _w: [],
) -> None:
    """Serve every task of the pass and record `rows_for(work)` and `claims_for(work)`."""
    for _ in range(100):
        batch = extract_next(project, actor, label).batch
        if batch is None:
            return
        work = batch.records[0]["work_id"]
        rows = rows_for(work)
        claims = claims_for(work) if label is PassLabel.A else []
        res = extract_record(
            project,
            actor,
            batch.task_id,
            rows,
            claims,
            finish=True,
            reason=None if rows or claims else "no result",
        )
        assert res.completed, (res.rows.rejected, res.claims.rejected)
    raise AssertionError("too many tasks")
