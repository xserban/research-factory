"""An `m-claims` miner over the fixture document, for the chat tests (plan chat T6)."""

from __future__ import annotations

from dataclasses import replace

from factory.mining.spec import EnumKind, MinerField, MinerSpec, QuoteKind
from factory.model.extraction import ExtractedRowInput, FieldInput
from tests.miner_helpers import method_vision

CLAIMS = "m-claims"
TYPES = (
    "limitation",
    "negative-result",
    "failure-analysis",
    "finding",
    "mechanism",
    "no-limitation-stated",
)
QUOTES = ("Lorem ipsum", "dolor sit", "amet")


def claims_spec() -> MinerSpec:
    """The fixture miner under the name `m-claims`, with the claim fields of the real one."""
    spec = method_vision(name=CLAIMS)
    return replace(
        spec,
        fields=(
            MinerField("claim_type", "result", EnumKind(TYPES), required=True),
            MinerField("about", "result", EnumKind(("a", "b"))),
            MinerField("direction", "result", EnumKind(("higher", "lower"))),
            MinerField("evidence_type", "result", EnumKind(("empirical", "theory"))),
            MinerField("strength", "result", EnumKind(("strong", "weak"))),
            MinerField("claim_quote", "evidence", QuoteKind(), required=True),
            MinerField("conditions", "evidence", QuoteKind(), compared=False),
        ),
        row_key_fields=("claim_quote",),
    )


def claim_row(
    claim_type: str, quote: str = QUOTES[0], *, direction: str = "higher", conditions: bool = False
) -> ExtractedRowInput:
    def enum(value: str) -> FieldInput:
        return FieldInput(value=value, anchor="s3.p1", quote="Lorem ipsum")

    fields = {
        "claim_type": enum(claim_type),
        "about": enum("a"),
        "direction": enum(direction),
        "evidence_type": enum("empirical"),
        "strength": enum("strong"),
        "claim_quote": FieldInput(value=quote, anchor="s3.p1", quote=quote),
    }
    if conditions:
        fields["conditions"] = FieldInput(value="sit amet", anchor="s3.p1", quote="sit amet")
    return ExtractedRowInput(fields=fields)
