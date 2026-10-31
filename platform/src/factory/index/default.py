from sqlalchemy import MetaData

from factory.index.project import project_created_handler, project_table
from factory.index.projection import Handler, Projection, core_tables
from factory.index.tasks import task_handlers, tasks_table

# Bump on any change to the tables or handlers below; the index is then rebuilt.
PROJECTION_VERSION = "2"


def default_projection() -> Projection:
    """A fresh projection: the core tables plus the `project` and `tasks` tables."""
    metadata = MetaData()
    core_tables(metadata)
    project = project_table(metadata)
    tasks = tasks_table(metadata)
    handlers: dict[str, Handler] = {
        "project.created": project_created_handler(project),
        **task_handlers(tasks),
    }
    return Projection(version=PROJECTION_VERSION, metadata=metadata, handlers=handlers)
