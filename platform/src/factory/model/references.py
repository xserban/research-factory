"""Reference extraction, resolution and snowball rounds: value types and event payloads (slice 3a).

Invariants enforced here (validated at the boundary, before any event is written):
- No raw reference-entry text is stored (ruling 14). An entry carries its ordinal, anchor, printed
  label, the parsed fields (bounded: title <= 300, venue <= 200, first-author surname <= 100) and
  `entry_sha256`, the SHA-256 of the whitespace-normalised raw text; extra fields are refused, so
  a `text` field cannot be written. The raw text is re-derived from the pinned conversion.
- Every free string in an event is bounded, so none can carry an entry's raw text: parser and
  matcher names and versions <= 80, an unextracted reason <= 300, a round query <= 400, a
  decision rationale <= 2000 and a verified quote <= 1000.
- Entry ordinals run 1, 2, ... without gaps; anchors are unique and of the declared form (`b<n>`,
  or a paragraph anchor for `entry_anchors = paragraph`).
- A marker token is at most `MAX_MARKER` characters (ruling 9); a matched context names its entry,
  an unmatched or ambiguous one names none.
- Resolutions name each ordinal once, ascending; that they are entries of the extraction is checked
  by the service. `resolved` needs a work and an `identifier`/`title-exact` confidence;
  `unconfirmed` a work and `title-fuzzy`; `ambiguous` its candidates; `unresolved` no work and a
  reason. `confirmed` comes only from a decision.
- A binding decision (`confirm`, `reject`) names who confirmed; a proposal never does and quotes
  both the entry and the candidate. A confirmation names its work.
- A carried decision is a human's binding decision taken over by a new extraction for the entry
  with the same `entry_sha256`; it names the event that made it. An agent's decision never carries.
- Reference layers (relevance classes of cited items): a scheme version names 2 to 12 layers with
  unique slug ids; `layer_scheme_recorded` and `layer_labelled` are the researcher's (human actor,
  enforced by the projector), `layer_assigned` an agent's, with the usual provenance. Whether a
  layer or scheme version is known is the service's check, never the event's.
- A backward round goes via the document reference list and has no chase round; a forward round
  goes via source metadata and names the delegated chase round. A candidate's citers are among
  the round's source works and cite it through the round's extractions. Counts are never fields: the
  number of included works citing a candidate is derived from `cited_by`.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, Self

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

from factory.document.anchors import ANCHOR_RE
from factory.model.base import StrictModel
from factory.model.chase import CHASE_CHUNK, CHASE_ROUND_ID_RE, WorkId
from factory.model.fulltext import DOCUMENT_ID_RE, Quality
from factory.model.identity import BLOB_REF_RE, CONVERSION_ID_RE, ULID_RE
from factory.model.protocol import SnowballPlan
from factory.model.screening import NonBlank
from factory.model.work import RUN_ID_RE
from factory.model.work_ids import WORK_ID_RE

REX_ID_RE = rf"^rex_{ULID_RE}$"
SNW_ID_RE = rf"^snw_{ULID_RE}$"
ENTRY_KEY_RE = rf"^rex_{ULID_RE}:[1-9]\d*$"
"""An entry key `rex_<ULID>:<ordinal>`: a candidate with no work id yet."""
SHA256_HEX_RE = r"^[0-9a-f]{64}$"
B_ANCHOR_RE = r"^b\d+$"
PARAGRAPH_ANCHOR_RE = r"^s\d+(?:\.\d+)*\.p\d+$"

MAX_TITLE = 300
MAX_VENUE = 200
MAX_SURNAME = 100
MAX_MARKER = 80
MAX_LABEL = 20
MAX_URL = 1000
MAX_DOI = 300
MAX_ARXIV = 40
MAX_QUOTE = 1000
MAX_RATIONALE = 2000
MAX_CANDIDATES = 3
MAX_VERSION = 80
MAX_REASON = 300
MAX_QUERY = 400

ITEM_KEY_RE: Final = r"^ci-[0-9a-f]{16}$"
"""A cited item key: `ci-` and 16 hex characters of the SHA-256 of the normalised title."""
LAYER_ID_RE: Final = r"^[a-z][a-z0-9-]{0,31}$"
MIN_LAYERS: Final = 2
MAX_LAYERS: Final = 12
MAX_LAYER_NAME: Final = 80
MAX_LAYER_CRITERIA: Final = 2000
MAX_LAYER_EXAMPLE: Final = 300
MAX_LAYER_EXAMPLES: Final = 10
MAX_LAYER_RATIONALE: Final = 300
MAX_LAYER_NOTE: Final = 300

Flag = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$", max_length=64)]
Anchor = Annotated[str, StringConstraints(pattern=ANCHOR_RE.pattern)]
ExtractionId = Annotated[str, StringConstraints(pattern=REX_ID_RE)]
Ordinal = Annotated[int, Field(ge=1)]
Score = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Method = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$", max_length=40)]
VersionLabel = Annotated[NonBlank, Field(max_length=MAX_VERSION)]
"""A parser or matcher name or version: a short label, never document text."""
Query = Annotated[NonBlank, Field(max_length=MAX_QUERY)]
OPENALEX_WORK_RE = re.compile(r"^W\d{1,15}$")
"""A bare OpenAlex work id, as the OpenAlex adapter stores it (the `https://openalex.org/` prefix
stripped)."""
FORWARD_CHASE_RE = re.compile(rf"^cites:W\d{{1,15}}(\|W\d{{1,15}}){{0,{CHASE_CHUNK - 1}}}$")
"""A forward chase text as `search_chase` builds it: `cites:` and up to `CHASE_CHUNK` bare OpenAlex
work ids. A forward round records these delegated texts; the grammar bounds them, so they may
exceed `MAX_QUERY` but never carry free text."""
FORWARD_ROUND_RE = re.compile(
    rf"^(?:cites|openalex):W\d{{1,15}}(?:\|W\d{{1,15}}){{0,{CHASE_CHUNK - 1}}}"
    r"(?:,title_and_abstract\.search:[^,\x00-\x1f]{1,300})?$"
)
"""A forward round's text (slice 8). `cites:` is a forward chase text, optionally with the plan's
topic filter (`,title_and_abstract.search:` and an expression without a comma); `openalex:` names
the citing works a capped round took, at most `CHASE_CHUNK` ids and no filter. Both are bounded by
the grammar, so neither carries free text beyond the declared filter."""
RoundQuery = Annotated[NonBlank, Field(max_length=len("cites:") + CHASE_CHUNK * 17 + 330)]


class LinkState(StrEnum):
    RESOLVED = "resolved"
    UNCONFIRMED = "unconfirmed"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class Confidence(StrEnum):
    IDENTIFIER = "identifier"
    TITLE_EXACT = "title-exact"
    TITLE_FUZZY = "title-fuzzy"
    CONFIRMED = "confirmed"


class Decision(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    PROPOSE_CONFIRM = "propose-confirm"
    PROPOSE_REJECT = "propose-reject"
    CLEAR = "clear"
    """A human withdraws the human decision on an entry: the recorded link stands again and
    nothing carries to later extractions."""


BINDING_DECISIONS = frozenset({Decision.CONFIRM, Decision.REJECT, Decision.CLEAR})


class Direction(StrEnum):
    BACKWARD = "backward"
    FORWARD = "forward"


class Via(StrEnum):
    DOCUMENT_REFERENCE_LIST = "document-reference-list"
    SOURCE_METADATA = "source-metadata"


EntryAnchors = Literal["b", "paragraph"]
BblStatus = Literal["absent", "aligned", "count-mismatch"]
MarkerMethod = Literal["link", "numeric", "author-year"]
MarkerState = Literal["matched", "unmatched", "ambiguous"]
UnresolvedReason = Literal["no-identifier-no-title", "not-found", "source-error"]
ConfirmedBy = Literal["human", "second-agent"]


def _unique(values: tuple[object, ...], field: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field} must not repeat an entry")


class ReferenceEntry(StrictModel):
    """One bibliography entry as stored: parsed fields and a hash, never the raw text."""

    ordinal: Ordinal
    anchor: Anchor
    label: str | None = Field(default=None, min_length=1, max_length=MAX_LABEL)
    doi: str | None = Field(default=None, min_length=1, max_length=MAX_DOI)
    arxiv: str | None = Field(default=None, min_length=1, max_length=MAX_ARXIV)
    url: str | None = Field(default=None, min_length=1, max_length=MAX_URL)
    year: int | None = Field(default=None, ge=1900, le=2099)
    first_author: str | None = Field(default=None, min_length=1, max_length=MAX_SURNAME)
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    venue: str | None = Field(default=None, min_length=1, max_length=MAX_VENUE)
    entry_sha256: str = Field(pattern=SHA256_HEX_RE)


class BblInfo(StrictModel):
    """The `.bbl` alignment: `absent` carries nothing; otherwise the archive and its entry count."""

    status: BblStatus
    archive_blob: str | None = Field(default=None, pattern=BLOB_REF_RE)
    bbl_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.status == "absent":
            if self.archive_blob is not None or self.bbl_count is not None:
                raise ValueError("an absent bbl carries no archive and no count")
        elif self.archive_blob is None or self.bbl_count is None:
            raise ValueError("a read bbl names its archive and its entry count")
        return self


class CitationContext(StrictModel):
    """One marker occurrence: where it is, the entry it maps to (or none) and how."""

    citing_anchor: Anchor
    entry: Ordinal | None
    marker: str = Field(min_length=1, max_length=MAX_MARKER)
    method: MarkerMethod
    state: MarkerState

    @model_validator(mode="after")
    def _entry_iff_matched(self) -> Self:
        if (self.state == "matched") != (self.entry is not None):
            raise ValueError("a matched marker names its entry; any other names none")
        return self


class LinkCandidate(StrictModel):
    work_id: WorkId
    score: Score


class Resolution(StrictModel):
    """How one entry resolved. States follow the module invariants."""

    ordinal: Ordinal
    state: LinkState
    work_id: WorkId | None
    method: Method | None
    confidence: Confidence | None
    score: Score | None
    candidates: tuple[LinkCandidate, ...] = Field(default=(), max_length=MAX_CANDIDATES)
    source_blob: str | None = Field(default=None, pattern=BLOB_REF_RE)
    reason: UnresolvedReason | None = None
    no_source_record: bool = False

    @model_validator(mode="after")
    def _state_shape(self) -> Self:
        if self.confidence is Confidence.CONFIRMED:
            raise ValueError("confidence 'confirmed' comes only from a decision")
        if self.state is not LinkState.UNRESOLVED and self.reason is not None:
            raise ValueError("only an unresolved link carries a reason")
        if self.no_source_record and self.state is not LinkState.RESOLVED:
            raise ValueError("a no-source-record work is only the target of a resolved link")
        if self.state is LinkState.RESOLVED:
            if self.work_id is None or self.confidence not in (
                Confidence.IDENTIFIER,
                Confidence.TITLE_EXACT,
            ):
                raise ValueError("a resolved link needs a work and an identifier/title-exact match")
        elif self.state is LinkState.UNCONFIRMED:
            if self.work_id is None or self.confidence is not Confidence.TITLE_FUZZY:
                raise ValueError("an unconfirmed link needs a work and a title-fuzzy match")
        elif self.state is LinkState.AMBIGUOUS:
            if not self.candidates:
                raise ValueError("an ambiguous link lists its candidates")
        elif self.work_id is not None or self.reason is None:
            raise ValueError("an unresolved link has no work and states a reason")
        return self


class DecisionQuote(StrictModel):
    """A verbatim quote (ruling 14a) of the entry or of the candidate's title/author line."""

    side: Literal["entry", "candidate"]
    text: str = Field(min_length=1, max_length=MAX_QUOTE)


class CitingEntry(StrictModel):
    """One source work's entry that cites a candidate, with the anchors that cite it."""

    work_id: WorkId
    extraction_id: ExtractionId
    ordinal: Ordinal
    anchors: tuple[Anchor, ...] = ()


class SnowballCandidate(StrictModel):
    work_key: str = Field(pattern=rf"(?:{WORK_ID_RE})|(?:{ENTRY_KEY_RE})")
    cited_by: tuple[CitingEntry, ...] = Field(min_length=1)
    no_source_record: bool = False


class Unextracted(StrictModel):
    work_id: WorkId
    reason: Annotated[NonBlank, Field(max_length=MAX_REASON)]


# --- Event payloads (schema 1). Written by `factory.services.references`,
# `factory.services.reference_resolve` and `factory.services.snowball`; folded by
# `factory.index.references`.


class ReferenceExtracted(StrictModel):
    extraction_id: ExtractionId
    work_id: WorkId
    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    conversion_id: str = Field(pattern=CONVERSION_ID_RE)
    parser: VersionLabel
    parser_version: VersionLabel
    entry_anchors: EntryAnchors
    source_quality: Quality
    entries: tuple[ReferenceEntry, ...]
    marker_count: int = Field(ge=0)
    flags: tuple[Flag, ...]
    bbl: BblInfo

    @model_validator(mode="after")
    def _entries_shape(self) -> Self:
        if [e.ordinal for e in self.entries] != list(range(1, len(self.entries) + 1)):
            raise ValueError("entry ordinals must run 1, 2, ... without gaps")
        _unique(tuple(e.anchor for e in self.entries), "entry anchors")
        form = re.compile(B_ANCHOR_RE if self.entry_anchors == "b" else PARAGRAPH_ANCHOR_RE)
        if any(not form.match(e.anchor) for e in self.entries):
            raise ValueError(f"entry anchors must have the {self.entry_anchors!r} form")
        _unique(self.flags, "flags")
        count = self.bbl.bbl_count
        if self.bbl.status == "aligned" and count != len(self.entries):
            raise ValueError("an aligned bbl has as many entries as the bibliography")
        if self.bbl.status == "count-mismatch" and count == len(self.entries):
            raise ValueError("a count mismatch has a different bbl entry count")
        return self


class CitationContextsRecorded(StrictModel):
    extraction_id: ExtractionId
    contexts: tuple[CitationContext, ...]


class CarriedDecision(StrictModel):
    """A human's binding decision on an earlier extraction's entry, applied to `ordinal` of this
    one, which has the same `entry_sha256`. `decided_event` is the human's own event."""

    ordinal: Ordinal
    decision: Decision
    work_id: WorkId | None
    from_extraction: ExtractionId
    from_ordinal: Ordinal
    decided_event: str = Field(pattern=rf"^ev_{ULID_RE}$")

    @model_validator(mode="after")
    def _binding(self) -> Self:
        if self.decision not in (Decision.CONFIRM, Decision.REJECT):
            raise ValueError("only a confirmation or a rejection carries")
        if self.decision is Decision.CONFIRM and self.work_id is None:
            raise ValueError("a carried confirmation names its work")
        return self


class ReferenceResolved(StrictModel):
    extraction_id: ExtractionId
    resolutions: tuple[Resolution, ...]
    matcher_version: VersionLabel
    lookup_runs: tuple[Annotated[str, StringConstraints(pattern=RUN_ID_RE)], ...] = ()
    carried: tuple[CarriedDecision, ...] = ()

    @model_validator(mode="after")
    def _ordinals(self) -> Self:
        ordinals = [r.ordinal for r in self.resolutions]
        if ordinals != sorted(set(ordinals)):
            raise ValueError("resolutions name each ordinal once, in ascending order")
        _unique(self.lookup_runs, "lookup_runs")
        _unique(tuple(c.ordinal for c in self.carried), "carried")
        return self


RE_RESOLVE_STATES = frozenset(
    {
        "source-error",
        "not-found",
        "no-identifier-no-title",
        LinkState.RESOLVED.value,
        LinkState.UNCONFIRMED.value,
        LinkState.AMBIGUOUS.value,
    }
)
"""What `re_resolve` selects by: a reason for an unresolved link, the state for any other."""


def re_resolvable(
    *,
    reason: str | None,
    link_matcher: str,
    matcher: str,
    decision: str | None,
    proposal: str | None,
) -> bool:
    """Whether a link may take a new resolution from `matcher`, on the same extraction.

    Retried: a lookup that failed (`source-error`), or a link recorded by another matcher version.
    Never a link holding a binding decision or a proposal: both were made on what it names now.
    The service selects by this and the fold refuses by it, so neither can drift from the other.
    """
    if decision is not None or proposal is not None:
        return False
    return reason == "source-error" or link_matcher != matcher


class ReferenceReResolved(StrictModel):
    """New resolutions for links of a live extraction, whose id and entries stay (plan PF).

    `carried` holds the human decisions that apply to the new links, as in `ReferenceResolved`.
    """

    extraction_id: ExtractionId
    resolutions: tuple[Resolution, ...] = Field(min_length=1)
    matcher_version: VersionLabel
    lookup_runs: tuple[Annotated[str, StringConstraints(pattern=RUN_ID_RE)], ...] = ()
    carried: tuple[CarriedDecision, ...] = ()

    @model_validator(mode="after")
    def _ordinals(self) -> Self:
        ordinals = [r.ordinal for r in self.resolutions]
        if ordinals != sorted(set(ordinals)):
            raise ValueError("resolutions name each ordinal once, in ascending order")
        _unique(self.lookup_runs, "lookup_runs")
        _unique(tuple(c.ordinal for c in self.carried), "carried")
        if not {c.ordinal for c in self.carried} <= set(ordinals):
            raise ValueError("a carried decision names a re-resolved ordinal")
        return self


class ReferenceResolutionDecided(StrictModel):
    """A decision on one link; it supersedes the previous decision for the entry."""

    extraction_id: ExtractionId
    ordinal: Ordinal
    decision: Decision
    work_id: WorkId | None
    rationale: Annotated[NonBlank, Field(max_length=MAX_RATIONALE)]
    quotes: tuple[DecisionQuote, ...] = Field(default=(), max_length=2)
    confirmed_by: ConfirmedBy | None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        sides = [q.side for q in self.quotes]
        _unique(tuple(sides), "quote sides")
        if self.decision in BINDING_DECISIONS:
            if self.confirmed_by is None:
                raise ValueError("a binding decision names who confirmed it")
        else:
            if self.confirmed_by is not None:
                raise ValueError("a proposal is never a confirmation")
            if sorted(sides) != ["candidate", "entry"]:
                raise ValueError("a proposal quotes both the entry and the candidate")
        if self.decision in (Decision.CONFIRM, Decision.PROPOSE_CONFIRM) and self.work_id is None:
            raise ValueError("a confirmation names its work")
        return self


class CoreSelection(StrictModel):
    """What a capped forward round did for one core work: `matched` citing works found,
    `in_corpus` of them already held, `taken` of the rest put into the round. The number not taken
    is derived (R-05), never stored."""

    work_id: WorkId
    matched: int = Field(ge=0)
    in_corpus: int = Field(ge=0)
    taken: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts(self) -> Self:
        if self.in_corpus + self.taken > self.matched:
            raise ValueError("held and taken works are among the matched ones")
        return self

    @property
    def not_taken(self) -> int:
        return self.matched - self.in_corpus - self.taken


class ForwardSelection(StrictModel):
    """How a capped forward round chose its citing works (slice 8, IDEA-43): at most
    `max_per_work` per core work, by maximum cosine to the development seed references with the
    recorded model. `probe_runs` are the runs that fetched the citing works' metadata."""

    model_id: Annotated[NonBlank, Field(max_length=MAX_VERSION)]
    weights_hash: str = Field(pattern=SHA256_HEX_RE)
    software: Annotated[NonBlank, Field(max_length=200)]
    max_per_work: int = Field(ge=1)
    topic_filter: str | None = Field(default=None, max_length=300)
    cores: tuple[CoreSelection, ...] = Field(min_length=1)
    probe_runs: tuple[Annotated[str, StringConstraints(pattern=RUN_ID_RE)], ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> Self:
        _unique(tuple(c.work_id for c in self.cores), "cores")
        _unique(self.probe_runs, "probe_runs")
        if any(c.taken > self.max_per_work for c in self.cores):
            raise ValueError("a core work gives at most max_per_work works")
        return self


class SnowballRoundStarted(StrictModel):
    round_id: str = Field(pattern=SNW_ID_RE)
    direction: Direction
    via: Via
    round_no: int = Field(ge=1)
    sources: tuple[WorkId, ...]
    extraction_ids: tuple[ExtractionId, ...]
    candidates: tuple[SnowballCandidate, ...]
    queries: tuple[RoundQuery, ...]
    """Backward: the round's own texts, each at most `MAX_QUERY`. Forward: the delegated chase
    round's texts, each a `FORWARD_CHASE_RE` text."""
    chase_round_id: str | None = Field(default=None, pattern=CHASE_ROUND_ID_RE)
    rule: SnowballPlan | Literal["none"]
    unextracted: tuple[Unextracted, ...] = ()
    selection: ForwardSelection | None = None
    """How a capped forward round chose its works; absent for any other round."""

    @model_serializer(mode="wrap")
    def _omit_empty_selection(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """A round without a selection serialises exactly as it did before capped rounds."""
        data: dict[str, Any] = handler(self)
        if self.selection is None:
            data.pop("selection", None)
        return data

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.selection is not None and self.direction is not Direction.FORWARD:
            raise ValueError("only a forward round has a selection")
        if self.direction is Direction.BACKWARD:
            if self.via is not Via.DOCUMENT_REFERENCE_LIST or self.chase_round_id is not None:
                raise ValueError("a backward round goes via the reference list, without a chase")
            if any(len(q) > MAX_QUERY for q in self.queries):
                raise ValueError(f"a backward round's query is at most {MAX_QUERY} characters")
        else:
            if self.via is not Via.SOURCE_METADATA or self.chase_round_id is None:
                raise ValueError(
                    "a forward round goes via source metadata and names its chase round"
                )
            if any(FORWARD_ROUND_RE.fullmatch(q) is None for q in self.queries):
                raise ValueError(
                    "a forward round's queries are its chase round's cites: or openalex: texts"
                )
        _unique(self.sources, "sources")
        _unique(self.extraction_ids, "extraction_ids")
        _unique(tuple(c.work_key for c in self.candidates), "candidate work keys")
        _unique(tuple(u.work_id for u in self.unextracted), "unextracted")
        sources = set(self.sources)
        extractions = set(self.extraction_ids)
        for candidate in self.candidates:
            if any(c.work_id not in sources for c in candidate.cited_by):
                raise ValueError("a candidate is cited only by the round's source works")
            if any(c.extraction_id not in extractions for c in candidate.cited_by):
                raise ValueError("a candidate is cited only through the round's extractions")
        return self


ItemKey = Annotated[str, StringConstraints(pattern=ITEM_KEY_RE)]
LayerId = Annotated[str, StringConstraints(pattern=LAYER_ID_RE)]
LayerExample = Annotated[NonBlank, Field(max_length=MAX_LAYER_EXAMPLE)]
LayerStage = Literal["title", "abstract"]


class LayerDef(StrictModel):
    """One layer of a scheme: its id, name, ring, flags, criteria and example titles.

    `ring` orders layers from the inner core (0) outwards. `snowball`: items of this layer are
    snowball candidates. `abstract`: items given this layer at the title stage go on to the
    abstract stage."""

    id: LayerId
    ring: int = Field(ge=0, le=20)
    snowball: bool = False
    abstract: bool = False
    name: Annotated[NonBlank, Field(max_length=MAX_LAYER_NAME)]
    criteria: Annotated[NonBlank, Field(max_length=MAX_LAYER_CRITERIA)]
    include_examples: tuple[LayerExample, ...] = Field(default=(), max_length=MAX_LAYER_EXAMPLES)
    exclude_examples: tuple[LayerExample, ...] = Field(default=(), max_length=MAX_LAYER_EXAMPLES)


MAX_INNER_SAMPLE: Final = 50
"""Most items an inner sample may add to the calibration sample."""


class InnerSample(StrictModel):
    """Extra calibration items drawn from an earlier scheme's agent title-stage layers:
    `draw` maps a layer id of scheme `from_version` to how many items to draw from it.

    Invariants: every count at least 1, the total at most `MAX_INNER_SAMPLE`, at least one layer.
    Whether the earlier scheme exists and has the layers is checked by the service."""

    from_version: int = Field(ge=1)
    draw: dict[LayerId, Annotated[int, Field(ge=1)]] = Field(min_length=1)
    seed_version: int | None = Field(default=None, ge=1)
    """When set, the whole calibration draw (base and inner) uses the draw order of this earlier
    scheme version instead of the scheme's own, so a revised scheme keeps the same sample and the
    researcher's labels can be recorded again under it. Below `version`."""

    @model_validator(mode="after")
    def _total(self) -> Self:
        if sum(self.draw.values()) > MAX_INNER_SAMPLE:
            raise ValueError(f"an inner sample draws at most {MAX_INNER_SAMPLE} items")
        return self


class LayerSchemeRecorded(StrictModel):
    """The researcher's layer scheme, version `version`; first write wins per version.

    Invariants: ids unique, rings unique, at least one snowball layer. `precursor_before_year`
    is the cutoff for the computed precursor status: an item whose year is known and earlier is
    a precursor (never a judged layer)."""

    version: int = Field(ge=1)
    layers: tuple[LayerDef, ...] = Field(min_length=MIN_LAYERS, max_length=MAX_LAYERS)
    precursor_before_year: int | None = Field(default=None, ge=1900, le=2099)
    inner_sample: InnerSample | None = None
    """Optional inner stratum of the calibration sample (`from_version` below `version`)."""

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [layer.id for layer in self.layers]
        if len(set(ids)) != len(ids):
            raise ValueError("layer ids must be unique")
        rings = [layer.ring for layer in self.layers]
        if len(set(rings)) != len(rings):
            raise ValueError("layer rings must be unique")
        if not any(layer.snowball for layer in self.layers):
            raise ValueError("at least one layer must have snowball=true")
        if self.inner_sample is not None and self.inner_sample.from_version >= self.version:
            raise ValueError("an inner sample draws from an earlier scheme version")
        seed = None if self.inner_sample is None else self.inner_sample.seed_version
        if seed is not None and seed >= self.version:
            raise ValueError("an inner sample's seed_version is an earlier scheme version")
        return self


class LayerAssigned(StrictModel):
    """An agent's layer for a cited item at a stage, with a short rationale."""

    item_key: ItemKey
    scheme_version: int = Field(ge=1)
    stage: LayerStage
    layer: LayerId
    rationale: Annotated[NonBlank, Field(max_length=MAX_LAYER_RATIONALE)]


class LayerLabelled(StrictModel):
    """The researcher's own layer for a cited item (the calibration sample)."""

    item_key: ItemKey
    scheme_version: int = Field(ge=1)
    layer: LayerId
    note: str | None = Field(default=None, max_length=MAX_LAYER_NOTE)
