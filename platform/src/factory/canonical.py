import json

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
