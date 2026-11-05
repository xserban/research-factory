"""RO-Crate 1.1 metadata and the library manifest. Pure: values in, JSON text out.

Invariants (plan X-B, rulings 2 and 3; spec ruling 20):
- `crate_metadata` lists every file it is given in `hasPart`, and only those. The descriptor
  `ro-crate-metadata.json` describes the crate and is not a member of it.
- A file with `produced_by` is a generated report: it has one `CreateAction`, whose instrument is
  the factory version and whose object is the log position.
- Dates come from the last event, keys are sorted and `@graph` is sorted by `@id`, so equal input
  gives equal bytes.
- The manifest holds metadata and hashes of library documents, never their content.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote

RO_CRATE = "https://w3id.org/ro/crate/1.1"
CONTEXT = f"{RO_CRATE}/context"
DESCRIPTOR = "ro-crate-metadata.json"
MANIFEST = "library-manifest.json"
FACTORY_ID = "#factory"
LOG_ID = "#log"


@dataclass(frozen=True)
class CrateFile:
    """One member of the crate; `produced_by` names the report it is, for a generated file."""

    path: str
    sha256: str
    encoding_format: str
    produced_by: str | None


@dataclass(frozen=True)
class AgentEntry:
    """A (model, skill reference) found in agent events, with its count of events."""

    model: str
    skill: str
    events: int


@dataclass(frozen=True)
class ConversionEntry:
    """A conversion of a library document: its converter and the hashes it produced."""

    conversion_id: str
    converter: str
    converter_version: str
    markdown_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class ManifestEntry:
    """A library document as the full-text events state it (ruling 2). `url` is the attempt's
    redacted URL; a researcher-supplied document has none."""

    document_id: str
    work_id: str
    sha256: str
    route: str
    url: str | None
    source_version: str
    licence: str | None
    licence_status: str | None
    retrieved_at: str | None
    conversions: tuple[ConversionEntry, ...]


def _ref(entity_id: str) -> dict[str, str]:
    return {"@id": entity_id}


def _file_id(path: str) -> str:
    return quote(path, safe="/")


def _file(file: CrateFile) -> dict[str, Any]:
    return {
        "@id": _file_id(file.path),
        "@type": "File",
        "encodingFormat": file.encoding_format,
        "name": file.path,
        "sha256": file.sha256,
    }


def _action(file: CrateFile, name: str, last_ts: str, person_id: str) -> dict[str, Any]:
    return {
        "@id": f"#create/{_file_id(file.path)}",
        "@type": "CreateAction",
        "agent": _ref(person_id),
        "endTime": last_ts,
        "instrument": _ref(FACTORY_ID),
        "name": name,
        "object": _ref(LOG_ID),
        "result": _ref(_file_id(file.path)),
    }


def _agent(entry: AgentEntry) -> list[dict[str, Any]]:
    key = hashlib.sha256(f"{entry.model}\0{entry.skill}".encode()).hexdigest()[:16]
    count_id = f"#agent-{key}-n-events"
    return [
        {
            "@id": f"#agent-{key}",
            "@type": "SoftwareApplication",
            "additionalProperty": _ref(count_id),
            "name": entry.model,
            "version": entry.skill,
        },
        {"@id": count_id, "@type": "PropertyValue", "name": "n-events", "value": entry.events},
    ]


def crate_metadata(
    *,
    slug: str,
    description: str,
    last_event: str,
    last_ts: str,
    licence: str | None,
    person: str,
    orcid: str | None,
    factory_version: str,
    files: Sequence[CrateFile],
    agents: Sequence[AgentEntry],
) -> str:
    """The `ro-crate-metadata.json` text. `orcid` is the researcher's ORCID IRI when configured."""
    person_id = orcid or f"#user-{quote(person, safe='')}"
    root: dict[str, Any] = {
        "@id": "./",
        "@type": "Dataset",
        "author": _ref(person_id),
        "datePublished": last_ts,
        "description": description,
        "hasPart": [_ref(_file_id(f.path)) for f in sorted(files, key=lambda f: f.path)],
        "isBasedOn": _ref(LOG_ID),
        "name": slug,
    }
    if licence is not None:
        root["license"] = licence
    graph: list[dict[str, Any]] = [
        {
            "@id": DESCRIPTOR,
            "@type": "CreativeWork",
            "about": _ref("./"),
            "conformsTo": _ref(RO_CRATE),
        },
        root,
        {
            "@id": FACTORY_ID,
            "@type": "SoftwareApplication",
            "name": "Research Factory",
            "version": factory_version,
        },
        {
            "@id": LOG_ID,
            "@type": "CreativeWork",
            "description": "Scope: the whole project log, up to and including this event.",
            "identifier": last_event,
            "name": "Event log position",
        },
        {"@id": person_id, "@type": "Person", "name": person},
    ]
    for file in files:
        graph.append(_file(file))
        if file.produced_by is not None:
            graph.append(_action(file, file.produced_by, last_ts, person_id))
    for entry in agents:
        graph.extend(_agent(entry))
    document = {"@context": CONTEXT, "@graph": sorted(graph, key=lambda e: str(e["@id"]))}
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def manifest_json(entries: Sequence[ManifestEntry]) -> str:
    """The `library-manifest.json` text: one entry per library document, by document id."""
    documents = [asdict(e) for e in sorted(entries, key=lambda e: e.document_id)]
    return json.dumps({"documents": documents}, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


__all__ = [
    "CONTEXT",
    "DESCRIPTOR",
    "MANIFEST",
    "RO_CRATE",
    "AgentEntry",
    "ConversionEntry",
    "CrateFile",
    "ManifestEntry",
    "crate_metadata",
    "manifest_json",
]
