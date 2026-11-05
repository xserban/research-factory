from sqlalchemy import MetaData
from sqlalchemy.engine import Connection

from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.index.chase import chase_handlers, chase_tables
from factory.index.dedup import dedup_handlers, dedup_tables
from factory.index.document import document_handlers, document_tables
from factory.index.extraction import extraction_handlers, extraction_tables
from factory.index.fulltext import fulltext_handlers, fulltext_tables
from factory.index.imports import import_handlers, import_tables
from factory.index.inbox import inbox_handlers, inbox_tables
from factory.index.living import living_handlers, living_tables
from factory.index.notices import notice_handlers, notice_tables
from factory.index.probe import probe_handlers, probe_tables
from factory.index.project import project_created_handler, project_table
from factory.index.projection import Handler, Projection, core_tables
from factory.index.protocol import protocol_handlers, protocol_tables
from factory.index.question import question_handlers, question_tables
from factory.index.references import reference_handlers, reference_tables
from factory.index.screening import screening_handlers, screening_tables
from factory.index.search import search_handlers, search_tables
from factory.index.seeds import seed_handlers, seed_tables
from factory.index.tasks import task_handlers, tasks_table
from factory.index.watch import run_started_handler, watch_handlers, watch_tables

# Bump on any change to the tables or handlers below; the index is then rebuilt.
PROJECTION_VERSION = "31"


def _chain(first: Handler, second: Handler) -> Handler:
    def both(conn: Connection, event: Event) -> None:
        first(conn, event)
        second(conn, event)

    return both


def default_projection(blobs: BlobStore | None = None) -> Projection:
    """A fresh projection: core tables plus the project, task, search, dedup, question, seed,
    probe, protocol, screening, chase, full-text, extraction, document, reference, import, inbox
    and watch tables. `blobs` is the project's blob store, which the import handlers read records
    from; without it, folding an import event raises."""
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
    }
    # A run's start is folded by the search projection first, then linked to its watch cycle.
    handlers["search.run_started"] = _chain(
        handlers["search.run_started"], run_started_handler(watch)
    )
    return Projection(version=PROJECTION_VERSION, metadata=metadata, handlers=handlers)
