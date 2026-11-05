from sqlalchemy import MetaData

from factory.events.blobs import BlobStore
from factory.index.cards import card_handlers, card_tables
from factory.index.chase import chase_handlers, chase_tables
from factory.index.conclusions import conclusion_handlers, conclusion_tables
from factory.index.dedup import dedup_handlers, dedup_tables
from factory.index.directions import chain_derived, direction_handlers, direction_tables
from factory.index.document import document_handlers, document_tables
from factory.index.drafts import draft_handlers, draft_tables
from factory.index.evaluation import evaluation_handlers, evaluation_tables
from factory.index.experiments import experiment_handlers, experiment_tables
from factory.index.extraction import extraction_handlers, extraction_tables
from factory.index.findings import finding_handlers, finding_tables
from factory.index.fulltext import fulltext_handlers, fulltext_tables
from factory.index.gates import gate_handlers, gate_tables
from factory.index.graph import graph_handlers, graph_tables
from factory.index.hypotheses import hypothesis_handlers, hypothesis_tables
from factory.index.imports import import_handlers, import_tables
from factory.index.inbox import inbox_handlers, inbox_tables
from factory.index.intuition import intuition_handlers, intuition_tables
from factory.index.labels import label_handlers, label_tables
from factory.index.lineage import lineage_handlers, lineage_tables
from factory.index.living import digest_handlers, digest_tables, living_handlers, living_tables
from factory.index.miners import miner_handlers, miner_tables
from factory.index.notices import notice_handlers, notice_tables
from factory.index.probe import probe_handlers, probe_tables
from factory.index.project import project_created_handler, project_table
from factory.index.projection import Handler, Projection, chain, core_tables
from factory.index.protocol import protocol_handlers, protocol_tables
from factory.index.question import question_handlers, question_tables
from factory.index.references import reference_handlers, reference_tables
from factory.index.regions import region_handlers, region_tables
from factory.index.screening import screening_handlers, screening_tables
from factory.index.search import search_handlers, search_tables
from factory.index.seeds import seed_handlers, seed_tables
from factory.index.tasks import task_handlers, tasks_table
from factory.index.watch import run_started_handler, watch_handlers, watch_tables

# Bump on any change to the tables or handlers below; the index is then rebuilt.
PROJECTION_VERSION = "49"


def default_projection(blobs: BlobStore | None = None) -> Projection:
    """A fresh projection: core tables plus the project, task, search, dedup, question, seed,
    probe, protocol, screening, chase, full-text, extraction, document, reference, import, inbox
    watch, relation, idea, graph, card, contradiction, region and label tables. `blobs` is the
    project blob store the import and region handlers read from; without it, folding such an event
    raises."""
    metadata = MetaData()
    core_tables(metadata)
    project = project_table(metadata)
    tasks = tasks_table(metadata)
    search = search_tables(metadata)
    dedup = dedup_tables(metadata)
    question = question_tables(metadata)
    seeds = seed_tables(metadata)
    probes = probe_tables(metadata)
    protocol = protocol_tables(metadata)
    screening = screening_tables(metadata)
    chase = chase_tables(metadata)
    fulltext = fulltext_tables(metadata)
    extraction = extraction_tables(metadata)
    conversions, conversion_failures = document_tables(metadata)
    references = reference_tables(metadata)
    imports = import_tables(metadata)
    inbox = inbox_tables(metadata)
    watch = watch_tables(metadata, search.runs)
    snapshots = living_tables(metadata)
    notices = notice_tables(metadata, search.work_keys, screening.label_sessions)
    lineage = lineage_tables(metadata)
    graph_tables(metadata)
    conclusions = conclusion_tables(metadata)
    digests = digest_tables(metadata)
    cards = card_tables(metadata)
    intuition = intuition_tables(metadata)
    findings = finding_tables(metadata)
    gates = gate_tables(metadata)
    regions = region_tables(metadata)
    miners = miner_tables(metadata)
    hypotheses = hypothesis_tables(metadata, protocol.protocols, project)
    labels = label_tables(metadata)
    experiments = experiment_tables(
        metadata, protocol.protocols, project, hypotheses.hypotheses, hypotheses.registrations
    )
    evaluations = evaluation_tables(metadata)
    directions = direction_tables(metadata)
    drafts = draft_tables(metadata, protocol.protocols, project)
    handlers: dict[str, Handler] = {
        "project.created": project_created_handler(project),
        **task_handlers(tasks),
        **search_handlers(search),
        **dedup_handlers(dedup),
        **question_handlers(question),
        **seed_handlers(seeds),
        **probe_handlers(probes),
        **protocol_handlers(protocol),
        **screening_handlers(screening),
        **chase_handlers(chase),
        **fulltext_handlers(fulltext),
        **extraction_handlers(extraction),
        **document_handlers(conversions, conversion_failures),
        **reference_handlers(references),
        **import_handlers(imports, blobs),
        **inbox_handlers(inbox),
        **watch_handlers(watch),
        **living_handlers(snapshots),
        **notice_handlers(notices),
        **lineage_handlers(lineage),
        **conclusion_handlers(conclusions),
        **digest_handlers(digests),
        **card_handlers(cards),
        **intuition_handlers(intuition),
        **finding_handlers(findings),
        **gate_handlers(gates),
        **region_handlers(regions, blobs),
        **miner_handlers(miners),
        **hypothesis_handlers(hypotheses),
        **label_handlers(labels),
        **experiment_handlers(experiments),
        **evaluation_handlers(evaluations),
        **direction_handlers(directions),
        **draft_handlers(drafts, blobs),
    }
    # A direction fails in the event that decides it: derived after that event's own fold.
    chain_derived(handlers, directions)
    # The graph projection reads the tables the other handlers of the same event just folded.
    for event_type, handler in graph_handlers().items():
        handlers[event_type] = chain(handlers[event_type], handler)
    # A run's start is folded by the search projection first, then linked to its watch cycle.
    handlers["search.run_started"] = chain(
        handlers["search.run_started"], run_started_handler(watch)
    )
    return Projection(version=PROJECTION_VERSION, metadata=metadata, handlers=handlers)
