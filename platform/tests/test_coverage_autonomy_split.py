"""The agent view of coverage counts only the visible parts' decisions (M-B re-review, 4)."""

# ruff: noqa: F811
from pathlib import Path

from factory.events.envelope import Actor
from factory.imports.model import ImportFormat
from factory.model.imports import ImportRole
from factory.model.references import Decision
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.coverage import agent_coverage, coverage_report
from factory.services.import_resolve import decide_import, resolve_import
from factory.services.imports import list_import_records, record_import
from factory.services.screening import open_pass
from tests.helpers import SourcesFor, ready_protocol
from tests.import_helpers import bib_entry
from tests.references_service_helpers import Lookups, oa_item, second_agent

WHY = "Same paper; the export adds a version suffix."


WORDS = [
    "Alder", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Ginkgo", "Hazel", "Ironwood", "Juniper",
    "Larch", "Maple",
]  # fmt: skip


def _title(k: int) -> str:
    return f"{WORDS[k - 1]} canopy sensing under drift {k * 37}"


def _fuzzy_split_import(project: Project, tmp_path: Path, n: int = 12) -> str:
    entries = [
        bib_entry(f"z{k}", f"{_title(k)} v2", year=2018, author="Kim, Ana") for k in range(1, n + 1)
    ]
    path = tmp_path / "fuzzy.bib"
    path.write_text("".join(entries))
    summary = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=7
    )
    lookups = Lookups(
        openalex=[oa_item(_title(k), "Ana Kim", 2018, f"W7{k:02d}") for k in range(1, n + 1)]
    )
    resolve_import(project, summary.import_id, sources=lookups.sources())
    return summary.import_id


def _second_agent_confirms(project: Project, agent: Actor, imp: str, ordinal: int) -> None:
    decide_import(project, agent, imp, ordinal, Decision.PROPOSE_CONFIRM, rationale=WHY)
    decide_import(project, second_agent(agent), imp, ordinal, Decision.CONFIRM, rationale=WHY)


def test_agent_view_counts_visible_parts_only(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, tmp_path: Path
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    imp = _fuzzy_split_import(project, tmp_path)
    held = [r.ordinal for r in list_import_records(project, imp, view="held-out")]
    dev = [r.ordinal for r in list_import_records(project, imp, view="development")]
    assert held and dev
    _second_agent_confirms(project, agent, imp, held[0])
    full = coverage_report(project, imp)
    assert full.autonomy == {"human": 0, "audited-agent": 0, "agent": 1}
    # before a pass opens, the held-out part is withheld: its agent act must not show
    assert agent_coverage(project, imp).autonomy == {}
    _second_agent_confirms(project, agent, imp, dev[0])
    assert agent_coverage(project, imp).autonomy == {"human": 0, "audited-agent": 0, "agent": 1}
    assert coverage_report(project, imp).autonomy["agent"] == 2
    # once screening has started the held-out part is visible, as figures only
    open_pass(project, agent, PassLabel.A)
    assert agent_coverage(project, imp).autonomy == full.model_copy().autonomy | {"agent": 2}
