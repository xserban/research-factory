"""Grey literature (plan SG, PD-7 provisional): what the protocol declares and what was found.

Grey methods are provenance methods appended after `library-import`, so no existing PRISMA count
moves. A work counts as grey when it carries a grey provenance method. Nothing here judges: the
counts are computed from provenance and the protocol.

Invariants:
- A project whose protocol declares no `grey_sources` reports no grey line anywhere.
- The `included` flag of a declared source only labels; it never removes a work from the corpus.
"""

from __future__ import annotations

from sqlalchemy import bindparam, text

from factory.model.grey import GreySource
from factory.model.work import ProvenanceMethod
from factory.services.context import Project
from factory.services.protocol import current_protocol

GREY_METHOD_VALUES: tuple[str, ...] = (
    ProvenanceMethod.GREY_STRUCTURED.value,
    ProvenanceMethod.GREY_WEBSITE.value,
    ProvenanceMethod.GREY_WEB_SEARCH.value,
    ProvenanceMethod.EXPERT_CONTACT.value,
)


def declared_sources(project: Project) -> tuple[GreySource, ...]:
    """The current protocol's `grey_sources`, or an empty tuple while the section is absent."""
    current = current_protocol(project)
    if current is None or current.spec.grey_sources is None:
        return ()
    return current.spec.grey_sources


def grey_work_ids(project: Project) -> frozenset[str]:
    """Every work carrying a grey provenance method (before dedup canonicalisation)."""
    project.index.sync()
    sql = text("SELECT DISTINCT work_id FROM provenance WHERE method IN :methods").bindparams(
        bindparam("methods", expanding=True)
    )
    with project.index.connect() as conn:
        rows = conn.execute(sql, {"methods": list(GREY_METHOD_VALUES)}).all()
    return frozenset(str(row[0]) for row in rows)


def grey_paragraph(sources: tuple[GreySource, ...], *, reported: int = 0, contacts: int = 0) -> str:
    """The PRISMA-S paragraph for grey sources: each declared source with its stopping rule.

    Agent web searches are reported by the agent and are not verifiable here; the paragraph
    says so."""
    parts = ["Grey literature. Sources declared in the protocol:"]
    for source in sources:
        pooled = "pooled" if source.included else "reported separately"
        parts.append(
            f" {source.method.value} ({source.target}; stopping rule: {source.stopping_rule}; "
            f"{pooled});"
        )
    body = "".join(parts).rstrip(";") + "."
    if reported or contacts:
        body += (
            f" Web searches reported by the agent: {reported}; expert contacts logged: {contacts}."
            " Reported searches were run outside the platform and are not reproducible from it."
        )
    return body
