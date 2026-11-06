"""The agent view of the report surfaces, shared by MCP and by the CLI of a person without the full
view (slice 5 ruling 20; decision 43).

Invariants:
- Each `*_view` is the payload the MCP tool of that name returns, so a screener's CLI and an agent
  read one thing. Withholding lives here and in the sources' agent variants; the full reports stay
  complete, and the researcher's output never passes through this module.
- Only seed records, seed ids, stated identifiers, held-out recall and label-derived rates are
  withheld. A work is never masked: `include_work_ids=False` on every surface that names works.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import JsonValue

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.project import RigorMode
from factory.services import check as check_service
from factory.services import coverage as coverage_service
from factory.services import discovery as discovery_service
from factory.services import evidence_report as evidence_report_service
from factory.services import methods as methods_service
from factory.services import passes as passes_service
from factory.services import prisma as prisma_service
from factory.services import prisma_update as prisma_update_service
from factory.services import project as project_service
from factory.services import trace as trace_service
from factory.services.context import Project
from factory.services.withholding import WITHHELD as WITHHELD
from factory.services.withholding import held_out_tokens, withhold
from factory.services.xrun_accounting import hidden_acceptances

_RECORD_KEY = re.compile(r"(imp_[0-9A-Z]{26}):[0-9]+")


def withheld(project: Project, value: JsonValue, include_work_ids: bool = True) -> JsonValue:
    """Strip every held-out seed's identifiers from an agent-facing response (R-20)."""
    return withhold(value, held_out_tokens(project, include_work_ids))


def without_rates(report: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """The project status for an agent: screening counts and flags only. Label-derived rates
    (sensitivity, specificity, false-exclusion) stay in the full status and the human's reports."""
    screening = report.get("screening")
    if isinstance(screening, dict):
        screening.pop("false_exclusion_rate", None)
        calibration = screening.get("calibration")
        if isinstance(calibration, dict):
            calibration.pop("per_pass", None)
    return report


def collapsed_import_rows(project: Project, data: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """While no pass is open, one search-report row per import, without reported or retrieved
    counts, runs or record tokens: the admission queries cover the held-out part, so their
    counts and key lists would give its size (decision 43)."""
    search = data.get("search")
    if coverage_service.held_out_visible(project) or not isinstance(search, dict):
        return data
    rows = search.get("rows")
    if not isinstance(rows, list):
        return data
    kept: list[JsonValue] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("purpose") != "import":
            kept.append(row)
            continue
        import_id = str(row.get("import_id"))
        if import_id in seen:
            continue
        seen.add(import_id)
        kept.append(
            {
                **row,
                "text": import_id,
                "runs": [],
                "reported": None,
                "retrieved": 0,
                "shortfall_reason": None,
                "new_after_dedup": None,
                "included": None,
            }
        )
    return {**data, "search": {**search, "rows": kept}}


def without_record_keys(value: JsonValue) -> JsonValue:
    """`value` with every import record key `imp_<ULID>:<ordinal>` cut to the import id: an
    ordinal names a record's place in the export, which names the held-out part (decision 43)."""
    if isinstance(value, str):
        return _RECORD_KEY.sub(r"\1", value)
    if isinstance(value, list):
        return [without_record_keys(item) for item in value]
    if isinstance(value, dict):
        return {key: without_record_keys(item) for key, item in value.items()}
    return value


def require_pass_opened(project: Project, field: str = "graph") -> None:
    """The graph tools name works, and before a screening pass opens an agent must not be able to
    name a held-out seed's work (decision 43). Role-blind and neutral: the same message for every
    caller, saying nothing of seeds. The full view is unaffected."""
    if not coverage_service.held_out_visible(project):
        raise FactoryValidationError([ValidationIssue(field, "not available yet")])


def scrubbed_text(project: Project, text: str) -> str:
    """Rendered text of an agent variant, as `withheld` and `without_record_keys` leave a payload.
    Rendering first leaves every model intact, whatever patterns its fields carry."""
    value = without_record_keys(withheld(project, text, include_work_ids=False))
    return value if isinstance(value, str) else text


def without_hidden_acts(report: dict[str, JsonValue], hidden: int) -> dict[str, JsonValue]:
    """The event counts for an agent, without the two events of each acceptance of a baseline whose
    verdict it may not read yet (the acceptance and its deviation; decision 94)."""
    by_type, total = report.get("events_by_type"), report.get("events_total")
    if not hidden or not isinstance(by_type, dict) or not isinstance(total, int):
        return report
    for name in ("baseline.accepted", "experiment.deviation_recorded"):
        count = by_type.get(name)
        if isinstance(count, int):
            left = max(0, count - hidden)
            total -= count - left
            if left:
                by_type[name] = left
            else:
                del by_type[name]
    report["events_total"] = total
    return report


def status_view(project: Project) -> JsonValue:
    report = project_service.project_status(project, agent=True).model_dump(mode="json")
    if passes_service.is_pass_session(project, project.session):
        report["stage"] = None  # it follows the final outcomes (decisions 37 and 43)
    hidden = hidden_acceptances(project)
    return withheld(project, without_hidden_acts(without_rates(report), hidden))


def agent_status(project: Project) -> project_service.ProjectStatus:
    """`status_view` in the status model, for text: the rates are empty, not missing."""
    report = project_service.project_status(project, agent=True)
    screening = report.screening
    blank = screening.model_copy(
        update={
            "false_exclusion_rate": None,
            "calibration": screening.calibration.model_copy(update={"per_pass": {}}),
        }
    )
    data = report.model_copy(update={"screening": blank}).model_dump(mode="json")
    data = without_hidden_acts(data, hidden_acceptances(project))
    return project_service.ProjectStatus.model_validate(withheld(project, data))


def prisma_view(project: Project, update: str | None = None) -> JsonValue:
    data: dict[str, JsonValue] = {
        "flow": prisma_service.prisma_flow(project).model_dump(mode="json"),
        "search": prisma_service.search_report(project).model_dump(mode="json"),
    }
    if update is not None:
        until = None if update == "last" else update
        flow = prisma_update_service.prisma_update(project, until=until)
        data["update"] = flow.model_dump(mode="json")
    data = collapsed_import_rows(project, data)
    return without_record_keys(withheld(project, data, include_work_ids=False))


def search_view(project: Project) -> JsonValue:
    """The search report alone, as `prisma_view` shows it."""
    data: dict[str, JsonValue] = {
        "search": prisma_service.search_report(project).model_dump(mode="json")
    }
    data = collapsed_import_rows(project, data)
    return without_record_keys(withheld(project, data, include_work_ids=False))


def methods_view(project: Project) -> JsonValue:
    full = methods_service.methods_report(project)
    report, fields = methods_service.agent_methods(project, full)
    data: dict[str, JsonValue] = {
        "report": report.model_dump(mode="json"),
        "text": methods_service.render_methods(report, withheld=fields),
    }
    return withheld(project, data, include_work_ids=False)


def methods_text(project: Project) -> str:
    """The rendered statement of `methods_view`."""
    report, fields = methods_service.agent_methods(project, methods_service.methods_report(project))
    return scrubbed_text(project, methods_service.render_methods(report, withheld=fields))


def agent_search(project: Project) -> prisma_service.SearchReport:
    """The search report of `prisma_view`, in its model."""
    view = prisma_view(project)
    search = view.get("search") if isinstance(view, dict) else None
    return prisma_service.SearchReport.model_validate(search)


def discovery_view(project: Project) -> JsonValue:
    view = discovery_service.agent_view(discovery_service.discovery_report(project))
    return withheld(project, view, include_work_ids=False)


def agent_evidence(
    project: Project, expect: Sequence[Mapping[str, str]] = (), *, without_grey: bool = False
) -> evidence_report_service.EvidenceReport:
    return evidence_report_service.agent_evidence(
        evidence_report_service.evidence_report(project, expect=expect, without_grey=without_grey)
    )


def evidence_view(
    project: Project, expect: Sequence[Mapping[str, str]] = (), *, without_grey: bool = False
) -> JsonValue:
    report = agent_evidence(project, expect, without_grey=without_grey)
    return withheld(project, report.model_dump(mode="json"), include_work_ids=False)


def agent_trace(
    project: Project,
    ref: str,
    *,
    direction: Literal["back", "forward"],
    layer: trace_service.Layer,
) -> trace_service.TraceNode:
    """The trace, or the same refusal as an unknown id for a held-out seed's own id."""
    tokens = {t.lower() for t in held_out_tokens(project, include_work_ids=False)}
    if ref.strip().lower() in tokens:
        raise FactoryValidationError([ValidationIssue("ref", "unknown id")])
    if layer == "all" or trace_service.is_region_ref(ref):
        require_pass_opened(project)
    return trace_service.agent_trace(project, ref, direction=direction, layer=layer)


def trace_view(
    project: Project,
    ref: str,
    *,
    direction: Literal["back", "forward"],
    layer: trace_service.Layer,
) -> JsonValue:
    tree = agent_trace(project, ref, direction=direction, layer=layer)
    return withheld(project, tree.model_dump(mode="json"), include_work_ids=False)


def check_view(project: Project, promote_to: RigorMode | None = None) -> JsonValue:
    report = check_service.agent_check(project, promote_to=promote_to)
    data: dict[str, JsonValue] = {
        **report.model_dump(mode="json"),
        "ok": report.ok,
        "evidence_ok": report.evidence_ok,
    }
    return withheld(project, data, include_work_ids=False)
