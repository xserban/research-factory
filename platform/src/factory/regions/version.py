"""Canonical form and hashes of a region (slice 3d rulings 1 and 5; plan Regions-A rulings 1-2).

Invariants:
- A rule is canonical after list parameters are sorted and defaults dropped; a rule set sorts its
  include and exclude lists by canonical text and removes duplicates, so reordering rules never
  changes `rules_hash`.
- `region_version` takes no definition text, name or author: they never reach `R@`.
- `compress` is byte-deterministic (gzip level 9, `mtime = 0`). New member blobs are plain text, so
  they reach a clone through `factory commit`; `member_lines` reads both, so old logs still fold.
"""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Iterable, Sequence

from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.model.regions import Facet
from factory.regions.rules import MemberType, Rule, RuleSet

_GZIP_MAGIC = b"\x1f\x8b"


def canonical_rule(rule: Rule) -> JsonValue:
    body = rule.model_dump(mode="json", exclude_defaults=True, exclude={"kind"})
    return {"kind": rule.kind, **body}


def _listed(items: Sequence[Rule]) -> JsonValue:
    by_text = {canonical_json(c).decode(): c for c in (canonical_rule(r) for r in items)}
    return [by_text[key] for key in sorted(by_text)]


def canonical_rules(rules: RuleSet) -> JsonValue:
    return {
        "include": _listed(rules.include),
        "exclude": _listed(rules.exclude),
        "within": None if rules.within is None else canonical_rule(rules.within),
    }


def rules_hash(rules: RuleSet) -> str:
    return hashlib.sha256(canonical_json(canonical_rules(rules))).hexdigest()


def members_text(members: Iterable[tuple[MemberType, str]]) -> bytes:
    lines = sorted({f"{kind.value}\t{member}" for kind, member in members})
    return "".join(f"{line}\n" for line in lines).encode()


def members_hash(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()


def member_lines(blob: bytes) -> list[str]:
    """The lines of a snapshot's member blob: plain text, or gzip in a log written before."""
    data = gzip.decompress(blob) if blob.startswith(_GZIP_MAGIC) else blob
    return data.decode().splitlines()


def compress(text: bytes) -> bytes:
    return gzip.compress(text, compresslevel=9, mtime=0)


def region_version(
    region_id: str,
    kind: str,
    facet: Facet | None,
    rules_hash: str,
    decisions: Sequence[str],
    members_hash: str,
) -> str:
    decided: list[JsonValue] = [*sorted(decisions)]
    payload: JsonValue = {
        "region": region_id,
        "kind": kind,
        "facet": None if facet is None else facet.model_dump(mode="json"),
        "rules_hash": rules_hash,
        "decisions": decided,
        "members_hash": members_hash,
    }
    return "R@" + hashlib.sha256(canonical_json(payload)).hexdigest()[:8]
