import re
from dataclasses import dataclass

from factory.model.base import StrictModel
from factory.model.chase import ChaseRoundStarted, SampleExtended, SeedAdmitted
from factory.model.dedup import DedupMerged, DedupReverted
from factory.model.document import ConversionFailed, Converted
from factory.model.extraction import (
    ClaimRecorded,
    ExtractionAuditLabelled,
    ExtractionAuditSampled,
    ExtractionClosed,
    ExtractionPassJoined,
    ExtractionPassOpened,
    ExtractionRecorded,
    ExtractionResolved,
)
from factory.model.fulltext import Attempted, DocumentAdded, FetchStarted, SourceChanged
from factory.model.imports import ImportRecorded, ImportResolved, ImportSplitDrawn
from factory.model.inbox import InboxLinkAdded, InboxLinkResolved, InboxLinkWithdrawn
from factory.model.probe import ProbeFailed, ProbeMeasured, ProbePageArchived
from factory.model.project import ProjectCreated
from factory.model.protocol import (
    DeviationRecorded,
    PressConfirmed,
    PressReviewed,
    ProtocolAmended,
    ProtocolRecorded,
)
from factory.model.question import GoalStated, QuestionRecorded
from factory.model.references import (
    CitationContextsRecorded,
    ReferenceExtracted,
    ReferenceResolutionDecided,
    ReferenceResolved,
    SnowballRoundStarted,
)
from factory.model.screening import (
    AuditLabelled,
    AuditSampled,
    CalibrationDrawn,
    CalibrationLabelled,
    DecisionRecorded,
    DisagreementResolved,
    PassJoined,
    PassOpened,
)
from factory.model.search import (
    QueryRegistered,
    SearchPageArchived,
    SearchRecordsParsed,
    SearchRunFinished,
    SearchRunStarted,
)
from factory.model.seed import (
    SeedAdded,
    SeedMissExplained,
    SeedResolved,
    SeedSplitDrawn,
    SeedUnresolved,
)
from factory.model.task import TaskClaimed, TaskCompleted, TaskCreated, TaskReleased
from factory.model.watch import WatchCycleFinished, WatchCycleStarted

_NAME_RE = re.compile(r"[a-z][a-z_]*\.[a-z][a-z_]*")


@dataclass(frozen=True)
class EventType:
    name: str
    payload: type[StrictModel]
    schema: int


class EventCatalog:
    """Registry of event types: name -> payload model and schema version."""

    def __init__(self) -> None:
        self._types: dict[str, EventType] = {}

    def register(self, event_type: EventType) -> None:
        if _NAME_RE.fullmatch(event_type.name) is None:
            raise ValueError(f"invalid event type name: {event_type.name!r}")
        if event_type.name in self._types:
            raise ValueError(f"event type already registered: {event_type.name!r}")
        self._types[event_type.name] = event_type

    def get(self, name: str) -> EventType:
        return self._types[name]

    def __contains__(self, name: object) -> bool:
        return name in self._types

    def names(self) -> list[str]:
        return sorted(self._types)


def default_catalog() -> EventCatalog:
    """The production catalog: every event type the platform writes."""
    catalog = EventCatalog()
    catalog.register(EventType("project.created", ProjectCreated, 1))
    catalog.register(EventType("task.created", TaskCreated, 1))
    catalog.register(EventType("task.claimed", TaskClaimed, 1))
    catalog.register(EventType("task.completed", TaskCompleted, 1))
    catalog.register(EventType("task.released", TaskReleased, 1))
    catalog.register(EventType("query.registered", QueryRegistered, 1))
    catalog.register(EventType("search.run_started", SearchRunStarted, 1))
    catalog.register(EventType("search.page_archived", SearchPageArchived, 1))
    catalog.register(EventType("search.records_parsed", SearchRecordsParsed, 1))
    catalog.register(EventType("search.run_finished", SearchRunFinished, 1))
    catalog.register(EventType("dedup.merged", DedupMerged, 1))
    catalog.register(EventType("dedup.reverted", DedupReverted, 1))
    catalog.register(EventType("question.goal_stated", GoalStated, 1))
    catalog.register(EventType("question.recorded", QuestionRecorded, 1))
    catalog.register(EventType("seed.added", SeedAdded, 1))
    catalog.register(EventType("seed.resolved", SeedResolved, 1))
    catalog.register(EventType("seed.unresolved", SeedUnresolved, 1))
    catalog.register(EventType("seed.split_drawn", SeedSplitDrawn, 1))
    catalog.register(EventType("seed.miss_explained", SeedMissExplained, 1))
    catalog.register(EventType("seed.admitted", SeedAdmitted, 1))
    catalog.register(EventType("chase.round_started", ChaseRoundStarted, 1))
    catalog.register(EventType("probe.page_archived", ProbePageArchived, 1))
    catalog.register(EventType("probe.measured", ProbeMeasured, 1))
    catalog.register(EventType("probe.failed", ProbeFailed, 1))
    catalog.register(EventType("protocol.recorded", ProtocolRecorded, 1))
    catalog.register(EventType("protocol.press_reviewed", PressReviewed, 1))
    catalog.register(EventType("protocol.press_confirmed", PressConfirmed, 1))
    catalog.register(EventType("protocol.deviation_recorded", DeviationRecorded, 1))
    catalog.register(EventType("protocol.amended", ProtocolAmended, 1))
    catalog.register(EventType("screening.pass_opened", PassOpened, 1))
    catalog.register(EventType("screening.pass_joined", PassJoined, 1))
    catalog.register(EventType("screening.sample_extended", SampleExtended, 1))
    catalog.register(EventType("screening.decision_recorded", DecisionRecorded, 1))
    catalog.register(EventType("screening.disagreement_resolved", DisagreementResolved, 1))
    catalog.register(EventType("calibration.drawn", CalibrationDrawn, 1))
    catalog.register(EventType("calibration.labelled", CalibrationLabelled, 1))
    catalog.register(EventType("audit.sampled", AuditSampled, 1))
    catalog.register(EventType("audit.labelled", AuditLabelled, 1))
    catalog.register(EventType("fulltext.fetch_started", FetchStarted, 1))
    catalog.register(EventType("fulltext.attempted", Attempted, 1))
    catalog.register(EventType("fulltext.document_added", DocumentAdded, 1))
    catalog.register(EventType("fulltext.source_changed", SourceChanged, 1))
    catalog.register(EventType("extraction.pass_opened", ExtractionPassOpened, 1))
    catalog.register(EventType("extraction.pass_joined", ExtractionPassJoined, 1))
    catalog.register(EventType("extraction.recorded", ExtractionRecorded, 1))
    catalog.register(EventType("extraction.claim_recorded", ClaimRecorded, 1))
    catalog.register(EventType("extraction.closed", ExtractionClosed, 1))
    catalog.register(EventType("extraction.resolved", ExtractionResolved, 1))
    catalog.register(EventType("extraction.audit_sampled", ExtractionAuditSampled, 1))
    catalog.register(EventType("extraction.audit_labelled", ExtractionAuditLabelled, 1))
    catalog.register(EventType("document.converted", Converted, 1))
    catalog.register(EventType("document.conversion_failed", ConversionFailed, 1))
    catalog.register(EventType("reference.extracted", ReferenceExtracted, 1))
    catalog.register(EventType("citation.contexts_recorded", CitationContextsRecorded, 1))
    catalog.register(EventType("reference.resolved", ReferenceResolved, 1))
    catalog.register(EventType("reference.resolution_decided", ReferenceResolutionDecided, 1))
    catalog.register(EventType("snowball.round_started", SnowballRoundStarted, 1))
    catalog.register(EventType("import.recorded", ImportRecorded, 1))
    catalog.register(EventType("import.split_drawn", ImportSplitDrawn, 1))
    catalog.register(EventType("import.resolved", ImportResolved, 1))
    catalog.register(EventType("inbox.link_added", InboxLinkAdded, 1))
    catalog.register(EventType("inbox.link_withdrawn", InboxLinkWithdrawn, 1))
    catalog.register(EventType("inbox.link_resolved", InboxLinkResolved, 1))
    catalog.register(EventType("watch.cycle_started", WatchCycleStarted, 1))
    catalog.register(EventType("watch.cycle_finished", WatchCycleFinished, 1))
    return catalog
