import re
from dataclasses import dataclass

from factory.model.appraisal_events import (
    AppraisalAuditLabelled,
    AppraisalAuditSampled,
    AppraisalJudged,
    AppraisalRecorded,
    AppraisalResolved,
)
from factory.model.base import StrictModel
from factory.model.budgets import BudgetSet
from factory.model.cards import (
    AssertionDecided,
    CardAsserted,
    CardCreated,
    CardImported,
    PropertyDecided,
    PropertyMerged,
    PropertyProposed,
    PropertyUnmerged,
)
from factory.model.chase import ChaseRoundStarted, SampleExtended, SeedAdmitted
from factory.model.conclusions import ConclusionRegistered, ConclusionRetired
from factory.model.core_works import WorkMarkedCore, WorkUnmarkedCore
from factory.model.curation import CurationDecided, CurationProposed
from factory.model.decisions import DecisionSelected, DecisionSuggested
from factory.model.dedup import DedupMerged, DedupReverted, PairDecided
from factory.model.develop import DocumentRendered
from factory.model.digest import DigestGenerated
from factory.model.directions import DirectionClosed
from factory.model.document import ConversionFailed, Converted
from factory.model.drafts import (
    DraftAuditDrawn,
    DraftAudited,
    DraftCreated,
    DraftOutlineRepinned,
    DraftReleased,
    DraftReordered,
    SentenceRecorded,
    SentenceVerified,
    SentenceWithdrawn,
)
from factory.model.experiments import (
    BaselineAccepted,
    BaselineEvaluated,
    ExperimentAmended,
    ExperimentDesigned,
    ExperimentDeviationRecorded,
    ExperimentFrozen,
    ExperimentUnlocked,
    XrunRegistered,
    XrunReported,
)
from factory.model.extraction import (
    ClaimRecorded,
    ExtractionAuditLabelled,
    ExtractionAuditSampled,
    ExtractionClosed,
    ExtractionPassJoined,
    ExtractionPassOpened,
    ExtractionRecorded,
    ExtractionRejected,
    ExtractionResolved,
)
from factory.model.feed import FeedConfigured, FeedFetched, FeedRanked, FeedReacted, FeedSent
from factory.model.files import FileRegistered
from factory.model.findings import ContradictionDecided, ContradictionProposed
from factory.model.fulltext import (
    Attempted,
    DocumentAdded,
    FetchStarted,
    SourceChanged,
    SourceResolved,
)
from factory.model.gate_audit import GateAuditLabelled, GateAuditSampled
from factory.model.grey import GreyContactLogged, GreySearchReported
from factory.model.hosting import ProjectHosted
from factory.model.hypotheses import (
    HypothesisAbandoned,
    HypothesisConcluded,
    HypothesisDrafted,
    HypothesisEvaluated,
    HypothesisRegistered,
    HypothesisReviewed,
    LeadDecided,
    LeadRecorded,
    ModelCutoffDeclared,
)
from factory.model.imports import (
    ImportAdmissionPlanned,
    ImportAttachmentLinked,
    ImportRecordDescribed,
    ImportRecorded,
    ImportResolutionDecided,
    ImportResolved,
    ImportSplitDrawn,
)
from factory.model.inbox import (
    InboxLinkAdded,
    InboxLinkResolved,
    InboxLinkWithdrawn,
    InboxPrioritised,
)
from factory.model.intuition import (
    ConceptDefined,
    ConceptLinkDecided,
    ConceptLinkProposed,
    ConceptMerged,
    ConceptReviewed,
    ConceptSourceDecided,
    ConceptUnmerged,
    InterpretationRecorded,
    InterpretationReviewed,
)
from factory.model.lab_library import FulltextAdopted, SourceConfirmed
from factory.model.labels import (
    ConsolidationDecided,
    ConsolidationPassCompleted,
    ConsolidationPassStarted,
    ConsolidationProposed,
    LabelApplicationDecided,
    LabelApplied,
    LabelMerged,
    LabelUnmerged,
    LabelWithdrawn,
    TermPromoted,
    TermRetired,
    TermRevised,
)
from factory.model.ledger import LedgerConfirmed
from factory.model.lineage import (
    IdeaDecided,
    IdeaMerged,
    IdeaProposed,
    IdeaUnmerged,
    RelationDecided,
    RelationProposed,
)
from factory.model.living import SnapshotRecorded
from factory.model.manuscripts import (
    CitationDecided,
    CitationResolved,
    ManuscriptAdded,
    ManuscriptAuditDrawn,
    ManuscriptAudited,
    ManuscriptSegmented,
    ManuscriptVerified,
    UnitClosed,
)
from factory.model.members import MemberGranted, MemberRevoked
from factory.model.mine_imports import MineImported
from factory.model.miner_calibration import MinerCalibrationDrawn, MinerCalibrationLabelled
from factory.model.miners import MinerRegistered, MinerRetired
from factory.model.notices import NoticeAssessed, NoticeObserved
from factory.model.pages import PageRecorded
from factory.model.probe import ProbeFailed, ProbeMeasured, ProbePageArchived
from factory.model.project import ProjectCreated, ProjectVisibilitySet
from factory.model.protocol import (
    DeviationRecorded,
    PressConfirmed,
    PressReviewed,
    ProtocolAmended,
    ProtocolRecorded,
)
from factory.model.question import GoalStated, QuestionRecorded
from factory.model.ranking import RankingComputed
from factory.model.references import (
    CitationContextsRecorded,
    LayerAssigned,
    LayerLabelled,
    LayerSchemeRecorded,
    ReferenceExtracted,
    ReferenceReResolved,
    ReferenceResolutionDecided,
    ReferenceResolved,
    SnowballRoundStarted,
)
from factory.model.regions import (
    RegionAdopted,
    RegionDefined,
    RegionLinked,
    RegionMemberDecided,
    RegionMemberProposed,
    RegionReviewed,
    RegionSnapshotTaken,
)
from factory.model.reviews import ReviewDecided, ReviewRequested
from factory.model.runner import PipelineFinished, PipelineStarted, RunnerFinished, RunnerStarted
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
from factory.model.screening_check import CheckDrawn, CheckLabelled
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
from factory.model.taxonomies import (
    MiningRequested,
    TaxonomyChangeProposed,
    TaxonomyRegistered,
    WorkLayerSet,
)
from factory.model.versions import DocumentPreferred, VersionLinked, VersionObserved
from factory.model.views import BriefingServed
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
    catalog.register(EventType("project.hosted", ProjectHosted, 1))
    catalog.register(EventType("member.granted", MemberGranted, 1))
    catalog.register(EventType("member.revoked", MemberRevoked, 1))
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
    catalog.register(EventType("dedup.pair_decided", PairDecided, 1))
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
    catalog.register(EventType("check.drawn", CheckDrawn, 1))
    catalog.register(EventType("check.labelled", CheckLabelled, 1))
    catalog.register(EventType("gate.audit_sampled", GateAuditSampled, 1))
    catalog.register(EventType("gate.audit_labelled", GateAuditLabelled, 1))
    catalog.register(EventType("miner.registered", MinerRegistered, 1))
    catalog.register(EventType("miner.retired", MinerRetired, 1))
    catalog.register(EventType("taxonomy.registered", TaxonomyRegistered, 1))
    catalog.register(EventType("taxonomy.change_proposed", TaxonomyChangeProposed, 1))
    catalog.register(EventType("mining.requested", MiningRequested, 1))
    catalog.register(EventType("work.layer_set", WorkLayerSet, 1))
    catalog.register(EventType("page.recorded", PageRecorded, 1))
    catalog.register(EventType("file.registered", FileRegistered, 1))
    catalog.register(EventType("miner.calibration_drawn", MinerCalibrationDrawn, 1))
    catalog.register(EventType("miner.calibration_labelled", MinerCalibrationLabelled, 1))
    catalog.register(EventType("mine.imported", MineImported, 1))
    catalog.register(EventType("fulltext.fetch_started", FetchStarted, 1))
    catalog.register(EventType("fulltext.attempted", Attempted, 1))
    catalog.register(EventType("fulltext.document_added", DocumentAdded, 1))
    catalog.register(EventType("fulltext.source_changed", SourceChanged, 1))
    catalog.register(EventType("fulltext.source_resolved", SourceResolved, 1))
    catalog.register(EventType("fulltext.adopted", FulltextAdopted, 1))
    catalog.register(EventType("library.source_confirmed", SourceConfirmed, 1))
    catalog.register(EventType("extraction.pass_opened", ExtractionPassOpened, 1))
    catalog.register(EventType("extraction.pass_joined", ExtractionPassJoined, 1))
    catalog.register(EventType("extraction.recorded", ExtractionRecorded, 1))
    catalog.register(EventType("extraction.claim_recorded", ClaimRecorded, 1))
    catalog.register(EventType("extraction.closed", ExtractionClosed, 1))
    catalog.register(EventType("extraction.rejected", ExtractionRejected, 1))
    catalog.register(EventType("extraction.resolved", ExtractionResolved, 1))
    catalog.register(EventType("extraction.audit_sampled", ExtractionAuditSampled, 1))
    catalog.register(EventType("extraction.audit_labelled", ExtractionAuditLabelled, 1))
    catalog.register(EventType("appraisal.recorded", AppraisalRecorded, 1))
    catalog.register(EventType("appraisal.judged", AppraisalJudged, 1))
    catalog.register(EventType("appraisal.resolved", AppraisalResolved, 1))
    catalog.register(EventType("appraisal.audit_sampled", AppraisalAuditSampled, 1))
    catalog.register(EventType("appraisal.audit_labelled", AppraisalAuditLabelled, 1))
    catalog.register(EventType("document.converted", Converted, 1))
    catalog.register(EventType("document.conversion_failed", ConversionFailed, 1))
    catalog.register(EventType("reference.extracted", ReferenceExtracted, 1))
    catalog.register(EventType("citation.contexts_recorded", CitationContextsRecorded, 1))
    catalog.register(EventType("reference.resolved", ReferenceResolved, 1))
    catalog.register(EventType("reference.re_resolved", ReferenceReResolved, 1))
    catalog.register(EventType("reference.resolution_decided", ReferenceResolutionDecided, 1))
    catalog.register(EventType("reference.layer_scheme_recorded", LayerSchemeRecorded, 1))
    catalog.register(EventType("reference.layer_assigned", LayerAssigned, 1))
    catalog.register(EventType("reference.layer_labelled", LayerLabelled, 1))
    catalog.register(EventType("snowball.round_started", SnowballRoundStarted, 1))
    catalog.register(EventType("import.recorded", ImportRecorded, 1))
    catalog.register(EventType("import.split_drawn", ImportSplitDrawn, 1))
    catalog.register(EventType("import.resolved", ImportResolved, 1))
    catalog.register(EventType("import.admission_planned", ImportAdmissionPlanned, 1))
    catalog.register(EventType("import.attachment_linked", ImportAttachmentLinked, 1))
    catalog.register(EventType("import.resolution_decided", ImportResolutionDecided, 1))
    catalog.register(EventType("import.record_described", ImportRecordDescribed, 1))
    catalog.register(EventType("inbox.link_added", InboxLinkAdded, 1))
    catalog.register(EventType("grey.search_reported", GreySearchReported, 1))
    catalog.register(EventType("grey.contact_logged", GreyContactLogged, 1))
    catalog.register(EventType("inbox.link_withdrawn", InboxLinkWithdrawn, 1))
    catalog.register(EventType("inbox.prioritised", InboxPrioritised, 1))
    catalog.register(EventType("inbox.link_resolved", InboxLinkResolved, 1))
    catalog.register(EventType("relation.proposed", RelationProposed, 1))
    catalog.register(EventType("relation.decided", RelationDecided, 1))
    catalog.register(EventType("idea.proposed", IdeaProposed, 1))
    catalog.register(EventType("idea.decided", IdeaDecided, 1))
    catalog.register(EventType("idea.merged", IdeaMerged, 1))
    catalog.register(EventType("idea.unmerged", IdeaUnmerged, 1))
    catalog.register(EventType("watch.cycle_started", WatchCycleStarted, 1))
    catalog.register(EventType("watch.cycle_finished", WatchCycleFinished, 1))
    catalog.register(EventType("living.snapshot_recorded", SnapshotRecorded, 1))
    catalog.register(EventType("ranking.computed", RankingComputed, 1))
    catalog.register(EventType("feed.configured", FeedConfigured, 1))
    catalog.register(EventType("feed.fetched", FeedFetched, 1))
    catalog.register(EventType("feed.ranked", FeedRanked, 1))
    catalog.register(EventType("feed.reacted", FeedReacted, 1))
    catalog.register(EventType("feed.sent", FeedSent, 1))
    catalog.register(EventType("runner.started", RunnerStarted, 1))
    catalog.register(EventType("runner.finished", RunnerFinished, 1))
    catalog.register(EventType("runner.pipeline_started", PipelineStarted, 1))
    catalog.register(EventType("runner.pipeline_finished", PipelineFinished, 1))
    catalog.register(EventType("work.marked_core", WorkMarkedCore, 1))
    catalog.register(EventType("work.unmarked_core", WorkUnmarkedCore, 1))
    catalog.register(EventType("notice.observed", NoticeObserved, 1))
    catalog.register(EventType("notice.assessed", NoticeAssessed, 1))
    catalog.register(EventType("version.observed", VersionObserved, 1))
    catalog.register(EventType("version.linked", VersionLinked, 1))
    catalog.register(EventType("document.preferred", DocumentPreferred, 1))
    catalog.register(EventType("conclusion.registered", ConclusionRegistered, 1))
    catalog.register(EventType("conclusion.retired", ConclusionRetired, 1))
    catalog.register(EventType("digest.generated", DigestGenerated, 1))
    catalog.register(EventType("vocabulary.property_proposed", PropertyProposed, 1))
    catalog.register(EventType("vocabulary.property_decided", PropertyDecided, 1))
    catalog.register(EventType("vocabulary.property_merged", PropertyMerged, 1))
    catalog.register(EventType("vocabulary.property_unmerged", PropertyUnmerged, 1))
    catalog.register(EventType("card.created", CardCreated, 1))
    catalog.register(EventType("card.asserted", CardAsserted, 1))
    catalog.register(EventType("card.assertion_decided", AssertionDecided, 1))
    catalog.register(EventType("card.imported", CardImported, 1))
    catalog.register(EventType("interpretation.recorded", InterpretationRecorded, 1))
    catalog.register(EventType("interpretation.reviewed", InterpretationReviewed, 1))
    catalog.register(EventType("concept.defined", ConceptDefined, 1))
    catalog.register(EventType("concept.source_decided", ConceptSourceDecided, 1))
    catalog.register(EventType("concept.reviewed", ConceptReviewed, 1))
    catalog.register(EventType("concept.link_proposed", ConceptLinkProposed, 1))
    catalog.register(EventType("concept.link_decided", ConceptLinkDecided, 1))
    catalog.register(EventType("concept.merged", ConceptMerged, 1))
    catalog.register(EventType("concept.unmerged", ConceptUnmerged, 1))
    catalog.register(EventType("contradiction.proposed", ContradictionProposed, 1))
    catalog.register(EventType("contradiction.decided", ContradictionDecided, 1))
    catalog.register(EventType("region.defined", RegionDefined, 1))
    catalog.register(EventType("region.snapshot_taken", RegionSnapshotTaken, 1))
    catalog.register(EventType("region.reviewed", RegionReviewed, 1))
    catalog.register(EventType("region.member_decided", RegionMemberDecided, 1))
    catalog.register(EventType("region.member_proposed", RegionMemberProposed, 1))
    catalog.register(EventType("region.linked", RegionLinked, 1))
    catalog.register(EventType("region.adopted", RegionAdopted, 1))
    catalog.register(EventType("decision.suggested", DecisionSuggested, 1))
    catalog.register(EventType("decision.selected", DecisionSelected, 1))
    catalog.register(EventType("document.rendered", DocumentRendered, 1))
    catalog.register(EventType("lead.recorded", LeadRecorded, 1))
    catalog.register(EventType("lead.decided", LeadDecided, 1))
    catalog.register(EventType("hypothesis.drafted", HypothesisDrafted, 1))
    catalog.register(EventType("hypothesis.abandoned", HypothesisAbandoned, 1))
    catalog.register(EventType("hypothesis.concluded", HypothesisConcluded, 1))
    catalog.register(EventType("hypothesis.evaluated", HypothesisEvaluated, 1))
    catalog.register(EventType("direction.closed", DirectionClosed, 1))
    catalog.register(EventType("curation.proposed", CurationProposed, 1))
    catalog.register(EventType("curation.decided", CurationDecided, 1))
    catalog.register(EventType("hypothesis.reviewed", HypothesisReviewed, 1))
    catalog.register(EventType("hypothesis.registered", HypothesisRegistered, 1))
    catalog.register(EventType("model.cutoff_declared", ModelCutoffDeclared, 1))
    catalog.register(EventType("label.applied", LabelApplied, 1))
    catalog.register(EventType("label.withdrawn", LabelWithdrawn, 1))
    catalog.register(EventType("label.application_decided", LabelApplicationDecided, 1))
    catalog.register(EventType("label.merged", LabelMerged, 1))
    catalog.register(EventType("label.unmerged", LabelUnmerged, 1))
    catalog.register(EventType("term.promoted", TermPromoted, 1))
    catalog.register(EventType("term.revised", TermRevised, 1))
    catalog.register(EventType("term.retired", TermRetired, 1))
    catalog.register(EventType("consolidation.pass_started", ConsolidationPassStarted, 1))
    catalog.register(EventType("consolidation.proposed", ConsolidationProposed, 1))
    catalog.register(EventType("consolidation.decided", ConsolidationDecided, 1))
    catalog.register(EventType("consolidation.pass_completed", ConsolidationPassCompleted, 1))
    catalog.register(EventType("experiment.designed", ExperimentDesigned, 1))
    catalog.register(EventType("experiment.amended", ExperimentAmended, 1))
    catalog.register(EventType("experiment.frozen", ExperimentFrozen, 1))
    catalog.register(EventType("experiment.unlocked", ExperimentUnlocked, 1))
    catalog.register(EventType("experiment.deviation_recorded", ExperimentDeviationRecorded, 1))
    catalog.register(EventType("xrun.registered", XrunRegistered, 1))
    catalog.register(EventType("xrun.reported", XrunReported, 1))
    catalog.register(EventType("baseline.evaluated", BaselineEvaluated, 1))
    catalog.register(EventType("baseline.accepted", BaselineAccepted, 1))
    catalog.register(EventType("draft.created", DraftCreated, 1))
    catalog.register(EventType("draft.outline_repinned", DraftOutlineRepinned, 1))
    catalog.register(EventType("draft.sentence_recorded", SentenceRecorded, 1))
    catalog.register(EventType("draft.sentence_withdrawn", SentenceWithdrawn, 1))
    catalog.register(EventType("draft.reordered", DraftReordered, 1))
    catalog.register(EventType("draft.verified", SentenceVerified, 1))
    catalog.register(EventType("briefing.served", BriefingServed, 1))
    catalog.register(EventType("draft.audit_drawn", DraftAuditDrawn, 1))
    catalog.register(EventType("draft.audited", DraftAudited, 1))
    catalog.register(EventType("draft.released", DraftReleased, 1))
    catalog.register(EventType("manuscript.added", ManuscriptAdded, 1))
    catalog.register(EventType("manuscript.segmented", ManuscriptSegmented, 1))
    catalog.register(EventType("manuscript.citation_resolved", CitationResolved, 1))
    catalog.register(EventType("manuscript.citation_decided", CitationDecided, 1))
    catalog.register(EventType("manuscript.unit_closed", UnitClosed, 1))
    catalog.register(EventType("manuscript.verified", ManuscriptVerified, 1))
    catalog.register(EventType("manuscript.audit_drawn", ManuscriptAuditDrawn, 1))
    catalog.register(EventType("manuscript.audited", ManuscriptAudited, 1))
    catalog.register(EventType("project.visibility_set", ProjectVisibilitySet, 1))
    catalog.register(EventType("review.requested", ReviewRequested, 1))
    catalog.register(EventType("review.decided", ReviewDecided, 1))
    catalog.register(EventType("ledger.confirmed", LedgerConfirmed, 1))
    catalog.register(EventType("budget.set", BudgetSet, 1))
    return catalog
