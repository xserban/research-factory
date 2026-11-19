from sqlalchemy import MetaData

from factory.events.blobs import BlobStore
from factory.index.answers import answer_handlers, answer_tables
from factory.index.appraisal import appraisal_handlers, appraisal_tables
from factory.index.briefings import briefing_handlers, briefing_tables
from factory.index.budgets import (
    budget_handlers,
    budget_tables,
    consumption_after,
    consumption_before,
)
from factory.index.cards import card_handlers, card_tables
from factory.index.chase import chase_handlers, chase_tables
from factory.index.chat_requests import chat_request_handlers, chat_request_tables
from factory.index.conclusions import conclusion_handlers, conclusion_tables
from factory.index.core_works import core_work_handlers, core_work_tables
from factory.index.curation import curation_handlers, curation_tables
from factory.index.decisions import decision_handlers, decision_tables
from factory.index.dedup import dedup_handlers, dedup_tables
from factory.index.develop import develop_handlers, develop_tables
from factory.index.directions import chain_derived, direction_handlers, direction_tables
from factory.index.document import document_handlers, document_tables
from factory.index.drafts import draft_handlers, draft_tables
from factory.index.evaluation import evaluation_handlers, evaluation_tables
from factory.index.experiments import experiment_handlers, experiment_tables
from factory.index.extraction import extraction_handlers, extraction_tables
from factory.index.feed import feed_handlers, feed_tables
from factory.index.files import file_handlers, file_tables
from factory.index.findings import finding_handlers, finding_tables
from factory.index.fulltext import fulltext_handlers, fulltext_tables
from factory.index.gates import gate_handlers, gate_tables
from factory.index.graph import graph_handlers, graph_tables
from factory.index.grey import grey_handlers, grey_tables
from factory.index.hypotheses import hypothesis_handlers, hypothesis_tables
from factory.index.imports import import_handlers, import_tables
from factory.index.inbox import inbox_handlers, inbox_tables
from factory.index.intuition import intuition_handlers, intuition_tables
from factory.index.labels import label_handlers, label_tables
from factory.index.ledger import ledger_handlers, ledger_tables
from factory.index.library import library_handlers, library_tables
from factory.index.lineage import lineage_handlers, lineage_tables
from factory.index.living import digest_handlers, digest_tables, living_handlers, living_tables
from factory.index.manuscripts import manuscript_handlers, manuscript_tables
from factory.index.members import member_handlers, member_tables
from factory.index.mine_imports import mine_import_handlers, mine_import_tables
from factory.index.mine_reopen import mine_reopen_handlers, mine_reopen_tables
from factory.index.miners import miner_handlers, miner_tables
from factory.index.notices import notice_handlers, notice_tables
from factory.index.probe import probe_handlers, probe_tables
from factory.index.project import (
    project_created_handler,
    project_hosted_handler,
    project_hosts_table,
    project_table,
    project_visibility_handler,
    project_visibility_table,
)
from factory.index.projection import Handler, Projection, chain, core_tables
from factory.index.protocol import protocol_handlers, protocol_tables
from factory.index.question import question_handlers, question_tables
from factory.index.ranking import ranking_handlers, ranking_tables
from factory.index.references import reference_handlers, reference_tables
from factory.index.regions import region_handlers, region_tables
from factory.index.reviews import protocol_guards, review_handlers, review_tables
from factory.index.runner import runner_handlers, runner_tables
from factory.index.screening import screening_handlers, screening_tables
from factory.index.search import search_handlers, search_tables
from factory.index.seeds import seed_handlers, seed_tables
from factory.index.sheets import sheet_handlers, sheet_tables
from factory.index.tasks import task_handlers, tasks_table
from factory.index.taxonomies import taxonomy_handlers, taxonomy_tables
from factory.index.watch import run_started_handler, watch_handlers, watch_tables

# Bump on any change to the tables or handlers below; the index is then rebuilt.
PROJECTION_VERSION = "92"


def default_projection(blobs: BlobStore | None = None) -> Projection:
    """A fresh projection: core tables plus the project, task, search, dedup, question, seed,
    probe, protocol, screening, chase, full-text, extraction, document, reference, import, inbox
    watch, relation, idea, graph, card, contradiction, region and label tables. `blobs` is the
    project blob store the import and region handlers read from; without it, folding such an event
    raises."""
    metadata = MetaData()
    core_tables(metadata)
    project = project_table(metadata)
    project_hosts = project_hosts_table(metadata)
    project_visibility = project_visibility_table(metadata)
    members = member_tables(metadata)
    reviews = review_tables(metadata)
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
    library = library_tables(metadata)
    extraction = extraction_tables(metadata)
    conversions, conversion_failures = document_tables(metadata)
    references = reference_tables(metadata)
    imports = import_tables(metadata)
    inbox = inbox_tables(metadata)
    files = file_tables(metadata)
    grey = grey_tables(metadata)
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
    rankings = ranking_tables(metadata)
    core_works = core_work_tables(metadata)
    feed = feed_tables(metadata)
    runner = runner_tables(metadata)
    miners = miner_tables(metadata)
    taxonomies = taxonomy_tables(metadata)
    mine_imports = mine_import_tables(metadata)
    mine_reopen = mine_reopen_tables(metadata)
    hypotheses = hypothesis_tables(metadata, protocol.protocols, project)
    labels = label_tables(metadata)
    decisions = decision_tables(metadata)
    renders = develop_tables(metadata)
    briefings = briefing_tables(metadata)
    experiments = experiment_tables(
        metadata, protocol.protocols, project, hypotheses.hypotheses, hypotheses.registrations
    )
    appraisals = appraisal_tables(metadata, protocol.protocols)
    evaluations = evaluation_tables(metadata)
    directions = direction_tables(metadata)
    curation = curation_tables(metadata)
    drafts = draft_tables(metadata, protocol.protocols, project)
    manuscripts = manuscript_tables(metadata)
    ledger = ledger_tables(metadata)
    budgets = budget_tables(metadata)
    sheets = sheet_tables(metadata)
    answers = answer_tables(metadata)
    chat_requests = chat_request_tables(metadata)
    handlers: dict[str, Handler] = {
        "project.created": project_created_handler(project),
        "project.hosted": project_hosted_handler(project_hosts),
        "project.visibility_set": project_visibility_handler(project_visibility, members),
        **member_handlers(members),
        **review_handlers(reviews, members, blobs),
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
        **library_handlers(library, members, fulltext.documents),
        **extraction_handlers(extraction),
        **document_handlers(conversions, conversion_failures),
        **reference_handlers(references),
        **import_handlers(imports, blobs),
        **inbox_handlers(inbox),
        **file_handlers(files),
        **grey_handlers(grey),
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
        **ranking_handlers(rankings, blobs),
        **core_work_handlers(core_works),
        **feed_handlers(feed, blobs),
        **runner_handlers(runner),
        **miner_handlers(miners),
        **taxonomy_handlers(taxonomies),
        **mine_import_handlers(mine_imports, extraction, conversions, fulltext, miners),
        **mine_reopen_handlers(mine_reopen, extraction, miners),
        **hypothesis_handlers(hypotheses),
        **label_handlers(labels),
        **decision_handlers(decisions),
        **develop_handlers(renders),
        **experiment_handlers(experiments),
        **appraisal_handlers(appraisals),
        **evaluation_handlers(evaluations),
        **direction_handlers(directions),
        **curation_handlers(curation),
        **draft_handlers(drafts, blobs),
        **briefing_handlers(briefings, blobs),
        **manuscript_handlers(manuscripts, blobs),
        **ledger_handlers(ledger, members),
        **budget_handlers(budgets, members),
        **sheet_handlers(sheets),
        **answer_handlers(answers),
        **chat_request_handlers(chat_requests),
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
    # Consumption asks what a claim or a completion finds, and what a run's own fold took.
    for event_type, handler in consumption_before(budgets, tasks).items():
        handlers[event_type] = chain(handler, handlers[event_type])
    for event_type, handler in consumption_after(budgets, search).items():
        own = handlers.get(event_type)  # a probe's page has no fold of its own
        handlers[event_type] = handler if own is None else chain(own, handler)
    # Last: an event the guards refuse reaches nothing chained after the protocol's own fold.
    handlers.update(protocol_guards(reviews, members, blobs, handlers))
    return Projection(version=PROJECTION_VERSION, metadata=metadata, handlers=handlers)
