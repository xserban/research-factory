"""The `protocol` hub payload: the registered plan, its versions, decisions, PRESS reviews, probes.

Invariants:
- `build` is pure over its `HubContext`, reads no network and writes nothing.
- It wraps the dashboard panels (`_protocol`, `_question`, `_decisions`, `_press`, `_probes`), the
  deviation list and the screening reasons; it never recomputes a count a service already has.
- Versions: the first recorded spec, then each amendment in recording order. A version's section
  fingerprints are the first 8 hex digits of the SHA-256 of the canonical JSON of that section of
  the spec (sorted keys, unset fields left out). A diff compares the spec in force before the
  amendment with the amended spec, section by section. Seeds never appear in any of it.
- A panel that fails is reported in `errors` under its name and replaced by an empty value; the
  others still build.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from factory.model.protocol import ProtocolSpec
from factory.services import dashboard, hub_screening, protocol
from factory.services.context import Project

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

METHODS: dict[str, str] = {
    "plan": (
        "The current protocol as the platform records it: its id is a hash of the semantic parts "
        "of the plan, so any change that matters gives a new id. Each section lists what the "
        "protocol declares; nothing is edited here. The count on a section chip is the number of "
        "decisions the researcher took about that section, grouped by the decision's level and "
        "subject."
    ),
    "criteria": (
        "Each criterion is shown as declared. The excluded counts are the distinct works whose "
        "live screening decision (calibration left out) excluded them citing that criterion, at "
        "title and abstract and at full text, as the Flow page's reasons count them. A work "
        "excluded by two passes is counted once per stage."
    ),
    "versions": (
        "Versions are the first recorded protocol and each amendment, in recording order. A "
        "section fingerprint is the first 8 hex digits of the SHA-256 of that section of the spec "
        "in canonical form; a coloured cell means the section changed in that amendment. An "
        "amendment that only rewords prose keeps the same protocol id, so it shows as a version "
        "with no changed hashed section. The diff compares the spec before the amendment with the "
        "amended spec."
    ),
    "decisions": (
        "Every decision the platform holds, read from the decision log. A decision is open until "
        "a human validates or rejects an item, selected afterwards, and superseded when a later "
        "decision replaces it. A chain follows the supersedes links from the first decision to "
        "the latest; the map places decisions by level and by order of suggestion."
    ),
    "press": (
        "A PRESS review is an independent critique of the search strategy. Each finding has a "
        "severity (major or minor) and an element it concerns; the review is confirmed once a "
        "human has answered every finding."
    ),
    "probes": (
        "A probe runs each planned query once and reports how many records it returns, how many "
        "of the development seeds it retrieved, and how many known negatives. Held-out seeds are "
        "withheld from these counts. A failed query shows its reason."
    ),
    "deviations": (
        "A deviation is a departure from the registered protocol, declared with its reason and "
        "the works or steps it affects. Deviations never change the protocol id."
    ),
}

# Sections of the hashed spec, in the order the page lists them.
_ITEM_KEYS = ("id", "name", "query_id", "key")


def build(ctx: HubContext) -> dict[str, Any]:
    """The payload of the `protocol` page; see the module docstring."""
    project = ctx.project
    errors: dict[str, str] = {}

    def guarded(name: str, make: Any, empty: Any) -> Any:
        try:
            return make()
        except Exception as exc:  # one panel must never take the page down
            errors[name] = f"{type(exc).__name__}: {str(exc)[:200]}"
            return empty

    decisions = guarded("decisions", lambda: dashboard._decisions(project), [])
    view = guarded("protocol", lambda: dashboard._protocol(project), {})
    return {
        "ready": True,
        "methods": METHODS,
        "protocol": view,
        "question": guarded("question", lambda: dashboard._question(project), {}),
        "sections": [[key, title] for key, title, _ in dashboard.SECTIONS],
        "decisions": decisions,
        "decision_sections": section_counts(decisions),
        "decision_chains": decision_chains(decisions),
        "press": guarded("press", lambda: dashboard._press(project), []),
        "probes": guarded("probes", lambda: dashboard._probes(project), []),
        "versions": guarded("versions", lambda: version_history(project), []),
        "deviations": guarded("deviations", lambda: deviations(project), []),
        "criteria_excluded": guarded("criteria_excluded", lambda: criteria_excluded(project), {}),
        "errors": errors,
    }


def section_counts(decisions: Any) -> dict[str, int]:
    """Decisions per protocol section key (`other:<level>` for those in no section)."""
    return dict(Counter(str(d.get("section")) for d in decisions if isinstance(d, dict)))


def decision_chains(decisions: Any) -> list[list[str]]:
    """Supersedes chains with at least two decisions, each from its first decision to its latest.

    A decision starts a chain when it supersedes nothing; the chain follows `superseded_by`."""
    rows = {str(d["decision_id"]): d for d in decisions if isinstance(d, dict)}
    chains: list[list[str]] = []
    for did, row in rows.items():
        if row.get("supersedes") is not None:
            continue
        chain, seen, cur = [did], {did}, row
        while cur.get("superseded_by") is not None:
            nxt = str(cur["superseded_by"])
            if nxt in seen or nxt not in rows:
                break
            chain.append(nxt)
            seen.add(nxt)
            cur = rows[nxt]
        if len(chain) > 1:
            chains.append(chain)
    return chains


def deviations(project: Project) -> list[dict[str, Any]]:
    """Every recorded deviation, in recording order (`protocol.list_deviations`)."""
    return [d.model_dump(mode="json") for d in protocol.list_deviations(project)]


def criteria_excluded(project: Project) -> dict[str, dict[str, int]]:
    """Per criterion id, the distinct works excluded citing it, per stage (the Flow page's count).

    Empty when no protocol is recorded. Criteria nobody excluded under are absent."""
    current = protocol.current_protocol(project)
    if current is None:
        return {}
    criteria = {c.id: c for c in current.spec.criteria}
    groups = hub_screening.reasons_wall(hub_screening.load_decisions(project), criteria)
    out: dict[str, dict[str, int]] = {}
    for group in groups:
        out.setdefault(group.criterion, {})[group.stage] = group.count
    return out


def fingerprint(value: Any) -> str:
    """The first 8 hex digits of the SHA-256 of the canonical JSON of `value`."""
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def _sections(spec: ProtocolSpec) -> dict[str, Any]:
    """The spec's sections as JSON-safe values; unset (None) sections are left out."""
    return spec.model_dump(mode="json", exclude_none=True)


def _item_key(items: list[Any]) -> str | None:
    if not items or not all(isinstance(i, dict) for i in items):
        return None
    for key in _ITEM_KEYS:
        if all(key in i for i in items):
            return key
    return None


def section_diff(before: Any, after: Any) -> dict[str, Any]:
    """One changed section: whole `before` and `after`, and per-item changes where the section is
    a list of keyed items (criteria, sources, queries, limits...)."""
    items: list[dict[str, Any]] | None = None
    if isinstance(before, list) and isinstance(after, list):
        key = _item_key(before + after)
        if key is not None:
            old = {str(i[key]): i for i in before}
            new = {str(i[key]): i for i in after}
            items = []
            for k in sorted(old.keys() | new.keys()):
                if k not in new:
                    items.append({"key": k, "change": "removed", "before": old[k], "after": None})
                elif k not in old:
                    items.append({"key": k, "change": "added", "before": None, "after": new[k]})
                elif old[k] != new[k]:
                    items.append({"key": k, "change": "changed", "before": old[k], "after": new[k]})
    return {"before": before, "after": after, "items": items}


def version_history(project: Project) -> list[dict[str, Any]]:
    """The first recorded protocol, then each amendment, with fingerprints and diffs (see above)."""
    project.index.sync()
    with project.index.connect() as conn:
        first = conn.execute(
            text("SELECT protocol_id, spec FROM protocols ORDER BY event_id LIMIT 1")
        ).one_or_none()
    if first is None:
        return []
    spec = _sections(ProtocolSpec.model_validate_json(str(first[1])))
    out: list[dict[str, Any]] = [
        {
            "protocol_id": str(first[0]),
            "kind": "initial",
            "amendment_id": None,
            "reason": "",
            "semantic": True,
            "changes": [],
            "other_changes": [],
            "fingerprints": {k: fingerprint(v) for k, v in spec.items()},
            "changed": [],
            "diff": {},
        }
    ]
    for amendment in protocol.list_amendments(project):
        after = _sections(amendment.spec)
        changed = sorted(k for k in spec.keys() | after.keys() if spec.get(k) != after.get(k))
        out.append(
            {
                "protocol_id": amendment.to_version,
                "from_version": amendment.from_version,
                "kind": "amendment",
                "amendment_id": amendment.amendment_id,
                "reason": amendment.reason,
                "semantic": amendment.semantic,
                "changes": [c.model_dump(mode="json") for c in amendment.changes],
                "other_changes": list(amendment.other_changes),
                "fingerprints": {k: fingerprint(v) for k, v in after.items()},
                "changed": changed,
                "diff": {k: section_diff(spec.get(k), after.get(k)) for k in changed},
            }
        )
        spec = after
    return out
