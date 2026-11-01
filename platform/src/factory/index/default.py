from sqlalchemy import MetaData

from factory.index.dedup import dedup_handlers, dedup_tables
from factory.index.probe import probe_handlers, probe_tables
from factory.index.project import project_created_handler, project_table
from factory.index.projection import Handler, Projection, core_tables
from factory.index.question import question_handlers, question_tables
from factory.index.search import search_handlers, search_tables
from factory.index.seeds import seed_handlers, seed_tables
from factory.index.tasks import task_handlers, tasks_table

# Bump on any change to the tables or handlers below; the index is then rebuilt.
PROJECTION_VERSION = "10"


def default_projection() -> Projection:
    """A fresh projection: core tables plus the project, task, search, dedup, question and seed
    tables."""
    metadata = MetaData()
    core_tables(metadata)
    project = project_table(metadata)
    tasks = tasks_table(metadata)
    search = search_tables(metadata)
    dedup = dedup_tables(metadata)
    question = question_tables(metadata)
    seeds = seed_tables(metadata)
    probes = probe_tables(metadata)
    handlers: dict[str, Handler] = {
        "project.created": project_created_handler(project),
        **task_handlers(tasks),
        **search_handlers(search),
        **dedup_handlers(dedup),
        **question_handlers(question),
        **seed_handlers(seeds),
        **probe_handlers(probes),
    }
    return Projection(version=PROJECTION_VERSION, metadata=metadata, handlers=handlers)
