"""Nanopublications of claims and lineage edges, as graphs of terms. Pure: no I/O, no clock.

One-way and unsigned (decision 72, spec ruling 21). Each nanopublication has exactly the four named
graphs `Head`, `assertion`, `provenance` and `pubinfo`, under a base beneath the temporary IRI that
nanopub tooling replaces when signing.

Invariants:
- Quote text appears only with `with_quotes`; otherwise only its `sha256` does (spec ruling 21).
- The agent's `strength` is written on the agent as its judgement, as `rfv:agentStrength`, never on
  the assertion as a strength of the evidence (spec ruling 21).
- A work without a DOI or arXiv id gives no nanopublication (`None`); nothing else stands in.
- An edge is written only when `builds-on` or `improves-on` and `stated` or `confirmed`.
- Every nanopublication names its scope and log position in `pubinfo` (spec ruling 22).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

from factory.exports.rdf import IRI, PREFIXES, RDF_TYPE, XSD_DATETIME, Literal_, Triple, iri
from factory.model.lineage import EdgeStatus, EdgeType

if TYPE_CHECKING:  # services import this module, so these stay out of the runtime import graph
    from factory.lineage.graph import GraphEdge
    from factory.model.work import Work
    from factory.services.extraction import ClaimRow

TEMP_BASE = "http://purl.org/nanopub/temp/"
CLAIM_SCOPE = "live pass A claims of included works"
EDGE_SCOPE = "stated and confirmed lineage edges"

_NP = PREFIXES["np"]
_PROV = PREFIXES["prov"]
_DCTERMS = PREFIXES["dcterms"]
_LABEL = IRI(f"{PREFIXES['rdfs']}label")
_CITES_AS_EVIDENCE = IRI(f"{PREFIXES['cito']}citesAsEvidence")
_DERIVED_FROM = IRI(f"{_PROV}wasDerivedFrom")
_ATTRIBUTED_TO = IRI(f"{_PROV}wasAttributedTo")
_IRI_SAFE = "/:;()._-~!$&'*+,=@"
_RELATIONS = {EdgeType.BUILDS_ON: "buildsOn", EdgeType.IMPROVES_ON: "improvesOn"}
_EXPORTED_STATUSES = (EdgeStatus.STATED, EdgeStatus.CONFIRMED)

Nanopub = dict[IRI, list[Triple]]


@dataclass(frozen=True)
class Attribution:
    """Who wrote a claim: the extraction event and its actor; `model` and `skill` for an agent."""

    event_id: str
    actor: str
    model: str | None
    skill: str | None


def work_iri(work: Work) -> IRI | None:
    """The DOI IRI of `work`, else its arXiv IRI, else None. A DOI may hold `<`, `>` or spaces, so
    the identifier is percent-encoded."""
    if work.identifiers.doi:
        return iri(f"https://doi.org/{quote(work.identifiers.doi, safe=_IRI_SAFE)}")
    if work.identifiers.arxiv:
        return iri(f"https://arxiv.org/abs/{quote(work.identifiers.arxiv, safe=_IRI_SAFE)}")
    return None


def base_iri(slug: str, ident: str) -> str:
    """The base of the nanopublication of `ident`, under the temporary IRI."""
    return f"{TEMP_BASE}{slug}/{ident}/"


def prefixes(base: str, vocab: str) -> dict[str, str]:
    """The fixed prefixes with `sub` set to this nanopublication and `rfv` to the vocabulary."""
    return {**PREFIXES, "sub": base, "rfv": vocab}


def _publication(
    base: str,
    *,
    assertion: list[Triple],
    provenance: list[Triple],
    creator: IRI | Literal_,
    created: str,
    log_position: str,
    scope: str,
    vocab: str,
) -> Nanopub:
    """The four graphs around `assertion` and `provenance`."""
    np = IRI(f"{base}np")
    head, body = IRI(f"{base}Head"), IRI(f"{base}assertion")
    source, info = IRI(f"{base}provenance"), IRI(f"{base}pubinfo")
    return {
        head: [
            (np, RDF_TYPE, IRI(f"{_NP}Nanopublication")),
            (np, IRI(f"{_NP}hasAssertion"), body),
            (np, IRI(f"{_NP}hasProvenance"), source),
            (np, IRI(f"{_NP}hasPublicationInfo"), info),
        ],
        body: assertion,
        source: provenance,
        info: [
            (np, IRI(f"{_DCTERMS}creator"), creator),
            (np, IRI(f"{_DCTERMS}created"), Literal_(created, XSD_DATETIME)),
            (np, IRI(f"{vocab}logPosition"), Literal_(log_position)),
            (np, IRI(f"{vocab}scope"), Literal_(scope)),
        ],
    }


def claim_nanopub(
    claim: ClaimRow,
    work: Work,
    *,
    slug: str,
    creator: IRI | Literal_,
    created: str,
    log_position: str,
    conversion_sha256: str | None,
    quote_sha256: str,
    attribution: Attribution,
    with_quotes: bool,
    vocab: str,
) -> Nanopub | None:
    """The nanopublication of one claim; None when `work` has no DOI or arXiv id.
    `conversion_sha256` is None only for a claim naming a conversion the log does not hold."""
    target = work_iri(work)
    if target is None:
        return None
    base = base_iri(slug, claim.claim_id)
    subject, body, agent = IRI(f"{base}claim"), IRI(f"{base}assertion"), IRI(f"{base}agent")
    assertion: list[Triple] = [
        (subject, RDF_TYPE, IRI(f"{vocab}Claim")),
        (subject, _LABEL, Literal_(claim.statement)),
        (subject, IRI(f"{vocab}claimType"), IRI(f"{vocab}{claim.claim_type.value}")),
        (subject, IRI(f"{vocab}evidenceType"), IRI(f"{vocab}{claim.evidence_type.value}")),
        (subject, _CITES_AS_EVIDENCE, target),
    ]
    provenance: list[Triple] = [
        (body, _DERIVED_FROM, target),
        (body, IRI(f"{vocab}anchor"), Literal_(claim.anchor)),
        (body, IRI(f"{vocab}quoteSha256"), Literal_(quote_sha256)),
        (body, IRI(f"{vocab}extractionEvent"), Literal_(attribution.event_id)),
        (body, _ATTRIBUTED_TO, agent),
        (agent, IRI(f"{vocab}agentStrength"), Literal_(claim.strength.value)),
        (agent, IRI(f"{vocab}actor"), Literal_(attribution.actor)),
    ]
    if conversion_sha256 is not None:
        provenance.append((body, IRI(f"{vocab}conversionSha256"), Literal_(conversion_sha256)))
    if attribution.model is not None:
        provenance.append((agent, IRI(f"{vocab}model"), Literal_(attribution.model)))
    if attribution.skill is not None:
        provenance.append((agent, IRI(f"{vocab}skill"), Literal_(attribution.skill)))
    if with_quotes:
        provenance.append((body, IRI(f"{vocab}quote"), Literal_(claim.quote)))
    return _publication(
        base,
        assertion=assertion,
        provenance=provenance,
        creator=creator,
        created=created,
        log_position=log_position,
        scope=CLAIM_SCOPE,
        vocab=vocab,
    )


def edge_nanopub(
    edge: GraphEdge,
    source: Work,
    target: Work,
    *,
    basis_quote_sha256: str | None,
    slug: str,
    creator: IRI | Literal_,
    created: str,
    log_position: str,
    vocab: str,
) -> Nanopub | None:
    """The nanopublication of one lineage edge; None when either work has no DOI or arXiv id, or
    the edge is not an exported kind (see the module invariants)."""
    relation = _RELATIONS.get(edge.edge_type)
    from_work, to_work = work_iri(source), work_iri(target)
    if (
        relation is None
        or edge.status not in _EXPORTED_STATUSES
        or from_work is None
        or to_work is None
    ):
        return None
    base = base_iri(slug, edge.edge_id)
    body = IRI(f"{base}assertion")
    status = edge.status.value if isinstance(edge.status, EdgeStatus) else edge.status
    provenance: list[Triple] = [
        (body, _DERIVED_FROM, from_work),
        (body, IRI(f"{vocab}status"), Literal_(status)),
        (body, IRI(f"{vocab}edge"), Literal_(edge.edge_id)),
    ]
    if basis_quote_sha256 is not None:
        provenance.append((body, IRI(f"{vocab}quoteSha256"), Literal_(basis_quote_sha256)))
    return _publication(
        base,
        assertion=[(from_work, IRI(f"{vocab}{relation}"), to_work)],
        provenance=provenance,
        creator=creator,
        created=created,
        log_position=log_position,
        scope=EDGE_SCOPE,
        vocab=vocab,
    )


__all__ = [
    "CLAIM_SCOPE",
    "EDGE_SCOPE",
    "TEMP_BASE",
    "Attribution",
    "Nanopub",
    "base_iri",
    "claim_nanopub",
    "edge_nanopub",
    "prefixes",
    "work_iri",
]
