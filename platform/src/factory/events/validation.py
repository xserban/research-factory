from pydantic import ValidationError

from factory.errors import ValidationIssue
from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog
from factory.events.envelope import Event


def validate_event(
    event: Event, *, catalog: EventCatalog, blobs: BlobStore, project: str
) -> list[ValidationIssue]:
    """Check an event against the catalog, the project and the blob store."""
    issues: list[ValidationIssue] = []
    if event.type not in catalog:
        issues.append(ValidationIssue("type", f"unknown event type {event.type!r}"))
    else:
        event_type = catalog.get(event.type)
        if event.schema_version != event_type.schema:
            issues.append(
                ValidationIssue(
                    "schema",
                    f"expected schema {event_type.schema}, got {event.schema_version}",
                )
            )
        try:
            event_type.payload.model_validate(event.payload)
        except ValidationError as exc:
            for error in exc.errors():
                location = ".".join(str(part) for part in error["loc"])
                field = f"payload.{location}" if location else "payload"
                issues.append(ValidationIssue(field, error["msg"]))
    if event.project != project:
        issues.append(
            ValidationIssue("project", f"expected project {project!r}, got {event.project!r}")
        )
    if event.input_blob is not None and not blobs.exists(event.input_blob):
        issues.append(ValidationIssue("input_blob", f"no blob stored for {event.input_blob}"))
    return issues
