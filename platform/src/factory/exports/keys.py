"""Bibliography keys derived from work ids.

Invariant: a key depends only on the set of exported work ids, never on their order; adding a
work changes only the keys that collide with it.
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

from factory.model.work_ids import WORK_ID_RE


def _ascii(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return stripped.encode("ascii", "ignore").decode()


def bib_key(work_id: str) -> str:
    """`rf:<base>-<hash8>` -> `<base>`, transliterated to ASCII."""
    if not re.match(WORK_ID_RE, work_id):
        raise ValueError(f"not a work id: {work_id!r}")
    return _ascii(work_id[3:].rsplit("-", 1)[0])


def assign_keys(work_ids: Iterable[str]) -> dict[str, str]:
    """Keys for a set of works; every member of a colliding group takes `<base>-<hash8>`."""
    groups: dict[str, list[str]] = defaultdict(list)
    for work_id in sorted(set(work_ids)):
        groups[bib_key(work_id)].append(work_id)
    keys: dict[str, str] = {}
    for base, members in groups.items():
        for work_id in members:
            keys[work_id] = base if len(members) == 1 else f"{base}-{work_id[-8:]}"
    return keys
