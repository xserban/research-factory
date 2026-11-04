from sqlalchemy import MetaData

from factory.events.blobs import BlobStore
from factory.index.chase import chase_handlers, chase_tables
from factory.index.dedup import dedup_handlers, dedup_tables
from factory.index.document import document_handlers, document_tables
from factory.index.extraction import extraction_handlers, extraction_tables
from factory.index.fulltext import fulltext_handlers, fulltext_tables
from factory.index.imports import import_handlers, import_tables
from factory.index.inbox import inbox_handlers, inbox_tables
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

# Bump on any change to the tables or handlers below; the index is then rebuilt.
PROJECTION_VERSION = "26"


def default_projection(blobs: BlobStore | None = None) -> Projection:
    """A fresh projection: core tables plus the project, task, search, dedup, question, seed,
    probe, protocol, screening, chase, full-text, extraction, document, reference, import and
    inbox tables. `blobs` is the project's blob store, which the import handlers read records
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
    }
    return Projection(version=PROJECTION_VERSION, metadata=metadata, handlers=handlers)
