"""CSL-JSON serialiser. Pure; absent fields are omitted, keys sorted, output streamed."""

import json
from collections.abc import Iterable, Iterator

from pydantic import JsonValue

from factory.model.work import Author, Work, WorkType

_TYPES: dict[WorkType, str] = {
    WorkType.JOURNAL_ARTICLE: "article-journal",
    WorkType.CONFERENCE_PAPER: "paper-conference",
    WorkType.BOOK_CHAPTER: "chapter",
    WorkType.THESIS: "thesis",
    WorkType.TECH_REPORT: "report",
    WorkType.PREPRINT: "article",
    WorkType.DATASET: "dataset",
}


def _name(author: Author) -> dict[str, JsonValue]:
    name = author.name.strip()
    if "," in name:
        family, given = (part.strip() for part in name.split(",", 1))
        return {"family": family, "given": given}
    return {"literal": name}


def csl_item(work: Work, key: str) -> dict[str, JsonValue]:
    """One CSL-JSON item for `work` under `key`."""
    item: dict[str, JsonValue] = {
        "id": key,
        "type": _TYPES.get(work.type, "document"),
        "title": work.title,
    }
    if work.authors:
        item["author"] = [_name(a) for a in work.authors]
    published = work.dates.published
    if published is not None:
        item["issued"] = {"date-parts": [[published.year, published.month, published.day]]}
    ids = work.identifiers
    optional: dict[str, str | None] = {"DOI": ids.doi, "URL": ids.url, "ISBN": ids.isbn}
    if work.venue is not None:
        optional |= {
            "container-title": work.venue.name,
            "volume": work.venue.volume,
            "issue": work.venue.issue,
            "page": work.venue.pages,
            "publisher": work.venue.publisher,
        }
    for name, value in optional.items():
        if value:
            item[name] = value
    return item


def csl_json(items: Iterable[tuple[str, Work]]) -> Iterator[str]:
    """Stream a JSON array: `[`, items joined by `,\\n`, `]\\n`; deterministic."""
    yield "["
    first = True
    for key, work in items:
        body = json.dumps(csl_item(work, key), sort_keys=True, separators=(",", ":"))
        yield body if first else ",\n" + body
        first = False
    yield "]\n"
