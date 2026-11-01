import hashlib
import json
from collections.abc import Iterable

from pydantic import JsonValue


def canonical_json(value: JsonValue) -> bytes:
    """The one JSON encoding used for hashing and for writing event lines."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def population_digest(pairs: Iterable[tuple[str, str]]) -> str:
    """SHA-256 of the canonical JSON of the sorted `(work id, verdict)` pairs of an agreed set.

    Equal sets give equal digests whatever order they are supplied in; the projector and the audit
    service both compute it, so the two agree on what an audit's population was.
    """
    body: list[JsonValue] = [[work, verdict] for work, verdict in sorted(pairs)]
    return hashlib.sha256(canonical_json(body)).hexdigest()
