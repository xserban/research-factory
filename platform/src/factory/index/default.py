from sqlalchemy import MetaData

from factory.index.project import project_created_handler, project_table
from factory.index.projection import Projection, core_tables

# Bump on any change to the tables or handlers below; the index is then rebuilt.
PROJECTION_VERSION = "1"


def default_projection() -> Projection:
    """A fresh projection: the core tables plus the `project` table."""
    metadata = MetaData()
    core_tables(metadata)
    table = project_table(metadata)
    return Projection(
        version=PROJECTION_VERSION,
        metadata=metadata,
        handlers={"project.created": project_created_handler(table)},
    )
