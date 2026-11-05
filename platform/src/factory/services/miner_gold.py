"""Gold labels of a miner calibration (slice M, M-D ruling 3).

Invariants:
- A gold row is verified exactly as an agent's row is (plan D's verification, then the miner's
  kind checks), against the unit's pinned conversion; a row that fails is refused with the
  verifier's reason.
- Only a human labels (gate `miner.calibration_label`); a relay over MCP is refused to a session in
  any pass and to an agent proposer's session. Nothing here computes a score.
- A later label of a unit supersedes the earlier one; both stay in the log.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.mining.compile import compile_miner
from factory.mining.kinds import kind_checks
from factory.model.extraction import ExtractedRowInput, MinerScope
from factory.model.miner_calibration import GoldRow, MinerCalibrationLabelled
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project
from factory.services.conversions import conversion_document, conversion_manifest
from factory.services.extraction import UnitPin
from factory.services.extraction_verify import verify_row_in
from factory.services.gates import gate_issues
from factory.services.miners import _registered, calibration_by_id, proposer
from factory.services.mining import require_listed
from factory.services.protocol import miner_extraction_schema
from factory.services.search import list_works

__all__ = ["LABEL_GATE", "calibration_labels", "label_miner_calibration"]

LABEL_GATE = "miner.calibration_label"


def calibration_labels(project: Project, calibration_id: str) -> dict[str, tuple[GoldRow, ...]]:
    """The latest gold label of each labelled unit of a calibration: its rows (none for an empty
    unit). A unit without a label is absent."""
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT work_id, rows_json FROM miner_calibration_labels "
                "WHERE calibration_id = :c ORDER BY work_id"
            ),
            {"c": calibration_id},
        ).all()
    return {
        str(work): tuple(GoldRow.model_validate(row) for row in json.loads(str(rows)))
        for work, rows in found
    }


def label_miner_calibration(
    project: Project,
    actor: Actor,
    calibration_id: str,
    work_id: str,
    rows: Sequence[ExtractedRowInput],
    *,
    empty: bool = False,
    channel: Channel,
) -> str:
    """Record a human's gold label of one unit of a calibration and return the event id (ruling
    3). Each row is verified exactly as an agent's row is: plan D's verification, then the miner's
    kind checks, against the unit's pinned conversion. A later label of the unit supersedes the
    earlier one (latest wins; both stay in the log).

    Refused, with nothing written: by the gate `miner.calibration_label` (`actor` for a
    non-human; `channel` for a relay from a session in a pass; `session` for a relay by an agent
    proposer's session); an unknown calibration (`calibration_id`); a retired miner (`miner`); a
    unit outside the sample (`work_id`); rows given with `empty`, or neither rows nor `empty`
    (`rows`); a row that fails verification (`rows.<i>.fields...`, the verifier's reason); two
    rows with one key (`rows.<i>`)."""
    with project.index.exclusive():
        project.index.sync()
        calibration = calibration_by_id(project, calibration_id)
        if calibration is None:
            raise FactoryValidationError(
                [ValidationIssue("calibration_id", "is not a calibration of this project")]
            )
        owner = proposer(project, calibration.name, calibration.version)
        relayed = actor.kind != "human" or channel is Channel.MCP
        issues = gate_issues(
            project,
            actor,
            LABEL_GATE,
            channel=channel,
            proposer_session=owner.session if owner.kind == "agent" and relayed else None,
            agent_text="gold labels are a human act",
        )
        if issues:
            raise FactoryValidationError(issues)
        _, use, spec = require_listed(project, calibration.name, calibration.version)
        if _registered(project, calibration.name, calibration.version).retired:
            raise FactoryValidationError(
                [ValidationIssue("miner", f"miner {calibration.name} is retired")]
            )
        unit = next((u for u in calibration.units if u.work_id == work_id), None)
        if unit is None:
            raise FactoryValidationError(
                [ValidationIssue("work_id", "is not a unit of this calibration")]
            )
        if empty and rows:
            raise FactoryValidationError(
                [ValidationIssue("rows", "an empty unit has no gold rows")]
            )
        if not empty and not rows:
            raise FactoryValidationError(
                [ValidationIssue("rows", "give the gold rows, or mark the unit empty")]
            )
        schema = miner_extraction_schema(use, tuple(f.name for f in spec.fields))
        pack = compile_miner(spec)
        manifest = conversion_manifest(project, unit.conversion_id)
        corpus = {w.id for w in list_works(project)}
        pin = UnitPin(
            task_id="",
            work_id=work_id,
            pass_label=PassLabel.A,
            scope=MinerScope(calibration.name),
            document_id=conversion_document(project, unit.conversion_id) or "",
            conversion_id=unit.conversion_id,
        )
        check = kind_checks(spec)
        gold: list[GoldRow] = []
        problems: list[ValidationIssue] = []
        for index, row in enumerate(rows):
            verdict = verify_row_in(
                pack, schema.fields, row.fields, unit.conversion_id, manifest, corpus
            )
            found = list(verdict.issues)
            if not found and verdict.fields is not None and verdict.row_key is not None:
                found = check(project, pin, verdict.fields, ()).issues
            if not found and verdict.fields is not None and verdict.row_key is not None:
                if verdict.row_key in {g.row_key for g in gold}:
                    found = [ValidationIssue("", "a gold row with this key is already given")]
                else:
                    gold.append(GoldRow(row_key=verdict.row_key, fields=verdict.fields))
            problems.extend(
                ValidationIssue(f"rows.{index}.{i.field}".rstrip("."), i.reason) for i in found
            )
        if problems:
            raise FactoryValidationError(problems)
        payload = MinerCalibrationLabelled(
            calibration_id=calibration_id,
            work_id=work_id,
            rows=tuple(gold),
            empty=empty,
            channel=channel,
        )
        event = project.events.make("miner.calibration_labelled", payload, actor)
        project.record([event])
    return event.id
