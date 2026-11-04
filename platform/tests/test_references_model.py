"""Reference and snowball event payloads: shapes, bounds and the no-raw-text rule (ruling 14)."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from factory.model.protocol import SnowballPlan
from factory.model.references import (
    REX_ID_RE,
    SNW_ID_RE,
    CitationContextsRecorded,
    Confidence,
    Decision,
    Direction,
    LinkState,
    ReferenceEntry,
    ReferenceExtracted,
    ReferenceResolutionDecided,
    ReferenceResolved,
    SnowballRoundStarted,
    Via,
)

REX = "rex_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
SNW = "snw_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
CHS = "chs_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
DOC = "doc_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
CNV = "cnv_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
RUN = "run_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
WORK = "rf:jones2021-sparse-1e2f3a4b"
CITED = "rf:smith2019-kernels-0a1b2c3d"
BLOB = "sha256:" + "ab" * 32


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def entry(ordinal: int, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ordinal": ordinal,
        "anchor": f"b{ordinal}",
        "label": f"[{ordinal}]",
        "doi": None,
        "arxiv": None,
        "url": None,
        "year": 2019,
        "first_author": "Smith",
        "title": "An invented title about kernels",
        "venue": "Invented Proceedings",
        "entry_sha256": sha(f"invented entry {ordinal}"),
    }
    base.update(kw)
    return base


def extracted(entries: list[dict[str, Any]] | None = None, **kw: Any) -> ReferenceExtracted:
    base: dict[str, Any] = {
        "extraction_id": REX,
        "work_id": WORK,
        "document_id": DOC,
        "conversion_id": CNV,
        "parser": "refparse",
        "parser_version": "1",
        "entry_anchors": "b",
        "source_quality": "latex",
        "entries": entries if entries is not None else [entry(1), entry(2)],
        "marker_count": 2,
        "flags": [],
        "bbl": {"status": "absent", "archive_blob": None, "bbl_count": None},
    }
    base.update(kw)
    return ReferenceExtracted.model_validate(base)


def resolution(ordinal: int = 1, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ordinal": ordinal,
        "state": "resolved",
        "work_id": CITED,
        "method": "corpus-identifier",
        "confidence": "identifier",
        "score": 1.0,
        "candidates": [],
        "source_blob": None,
        "reason": None,
        "no_source_record": False,
    }
    base.update(kw)
    return base


def resolved(resolutions: list[dict[str, Any]], **kw: Any) -> ReferenceResolved:
    base: dict[str, Any] = {
        "extraction_id": REX,
        "resolutions": resolutions,
        "matcher_version": "1",
        "lookup_runs": [RUN],
    }
    base.update(kw)
    return ReferenceResolved.model_validate(base)


def test_id_patterns() -> None:
    import re

    assert re.match(REX_ID_RE, REX) and re.match(SNW_ID_RE, SNW)
    assert not re.match(REX_ID_RE, SNW)


def test_vocabularies() -> None:
    assert {s.value for s in LinkState} == {"resolved", "unconfirmed", "ambiguous", "unresolved"}
    assert {c.value for c in Confidence} == {
        "identifier",
        "title-exact",
        "title-fuzzy",
        "confirmed",
    }
    assert {d.value for d in Decision} == {
        "confirm",
        "reject",
        "propose-confirm",
        "propose-reject",
    }
    assert {d.value for d in Direction} == {"backward", "forward"}
    assert {v.value for v in Via} == {"document-reference-list", "source-metadata"}


def test_extraction_valid_and_empty_allowed() -> None:
    assert len(extracted().entries) == 2
    empty = extracted(entries=[], marker_count=0, flags=["no-bibliography"])
    assert empty.entries == ()


def test_entry_has_no_text_field_and_caps_and_ordinals() -> None:
    assert "text" not in ReferenceEntry.model_fields
    with pytest.raises(ValidationError):
        extracted(entries=[entry(1, text="Smith, J. (2019). An invented title.")])
    with pytest.raises(ValidationError):  # any extra field is refused
        extracted(entries=[entry(1, raw="x")])
    for bad in ("abc", "AB" * 32, "a" * 63, "g" * 64):
        with pytest.raises(ValidationError):
            extracted(entries=[entry(1, entry_sha256=bad)])
    extracted(entries=[entry(1, title="t" * 300, venue="v" * 200, first_author="S" * 100)])
    for field, size in (("title", 301), ("venue", 201), ("first_author", 101)):
        with pytest.raises(ValidationError):
            extracted(entries=[entry(1, **{field: "x" * size})])
    for ordinals in ([2], [1, 3], [1, 1], [2, 1]):
        with pytest.raises(ValidationError):
            extracted(entries=[entry(n) for n in ordinals])


def test_entry_anchor_form_matches_entry_anchors() -> None:
    with pytest.raises(ValidationError):
        extracted(entries=[entry(1, anchor="s9.p1")])
    para = extracted(entries=[entry(1, anchor="s9.p1")], entry_anchors="paragraph")
    assert para.entries[0].anchor == "s9.p1"
    with pytest.raises(ValidationError):
        extracted(entries=[entry(1), entry(2, anchor="b1")])  # anchors unique


def test_bbl_shape() -> None:
    with pytest.raises(ValidationError):  # absent carries nothing
        extracted(bbl={"status": "absent", "archive_blob": BLOB, "bbl_count": 2})
    aligned = extracted(bbl={"status": "aligned", "archive_blob": BLOB, "bbl_count": 2})
    assert aligned.bbl.bbl_count == 2
    with pytest.raises(ValidationError):  # aligned means equal counts
        extracted(bbl={"status": "aligned", "archive_blob": BLOB, "bbl_count": 3})
    extracted(bbl={"status": "count-mismatch", "archive_blob": BLOB, "bbl_count": 3})
    with pytest.raises(ValidationError):
        extracted(bbl={"status": "count-mismatch", "archive_blob": BLOB, "bbl_count": 2})
    with pytest.raises(ValidationError):
        extracted(bbl={"status": "aligned", "archive_blob": None, "bbl_count": 2})


def test_flags_unique() -> None:
    with pytest.raises(ValidationError):
        extracted(flags=["marker-gap", "marker-gap"])


def test_contexts_marker_bounds_and_state() -> None:
    ok = CitationContextsRecorded.model_validate(
        {
            "extraction_id": REX,
            "contexts": [
                {
                    "citing_anchor": "s1.p2",
                    "entry": 1,
                    "marker": "[1]",
                    "method": "numeric",
                    "state": "matched",
                },
                {
                    "citing_anchor": "s1.p2",
                    "entry": None,
                    "marker": "[9]",
                    "method": "numeric",
                    "state": "unmatched",
                },
            ],
        }
    )
    assert len(ok.contexts) == 2
    bad_contexts: list[dict[str, Any]] = [
        {"marker": "x" * 81},
        {"entry": None},  # matched needs an entry
        {"state": "unmatched"},  # unmatched names no entry
        {"citing_anchor": "nope"},
        {"entry": 0},
    ]
    for override in bad_contexts:
        ctx = {
            "citing_anchor": "s1.p2",
            "entry": 1,
            "marker": "[1]",
            "method": "numeric",
            "state": "matched",
        }
        ctx.update(override)
        with pytest.raises(ValidationError):
            CitationContextsRecorded.model_validate({"extraction_id": REX, "contexts": [ctx]})


def test_resolved_needs_work_and_confidence() -> None:
    with pytest.raises(ValidationError):
        resolved([resolution(work_id=None)])
    with pytest.raises(ValidationError):
        resolved([resolution(confidence=None)])
    with pytest.raises(ValidationError):  # confirmed comes only from a decision
        resolved([resolution(confidence="confirmed")])
    with pytest.raises(ValidationError):  # a resolved link carries no reason
        resolved([resolution(reason="not-found")])


def test_unresolved_needs_reason_and_no_work() -> None:
    ok = resolved(
        [
            resolution(
                state="unresolved", work_id=None, confidence=None, score=None, reason="not-found"
            )
        ]
    )
    assert ok.resolutions[0].state is LinkState.UNRESOLVED
    with pytest.raises(ValidationError):
        resolved(
            [resolution(state="unresolved", work_id=CITED, confidence=None, reason="not-found")]
        )
    with pytest.raises(ValidationError):
        resolved([resolution(state="unresolved", work_id=None, confidence=None, reason=None)])
    with pytest.raises(ValidationError):  # no-source-record only on a resolved link
        resolved(
            [
                resolution(
                    state="unresolved",
                    work_id=None,
                    confidence=None,
                    reason="not-found",
                    no_source_record=True,
                )
            ]
        )


def test_unconfirmed_and_ambiguous_shapes() -> None:
    cand = [{"work_id": CITED, "score": 0.91}]
    resolved([resolution(state="unconfirmed", confidence="title-fuzzy", candidates=cand)])
    with pytest.raises(ValidationError):
        resolved([resolution(state="unconfirmed", confidence="identifier", candidates=cand)])
    two = [{"work_id": CITED, "score": 0.9}, {"work_id": WORK, "score": 0.89}]
    resolved([resolution(state="ambiguous", work_id=None, confidence=None, candidates=two)])
    with pytest.raises(ValidationError):  # ambiguous lists its candidates
        resolved([resolution(state="ambiguous", work_id=None, confidence=None, candidates=[])])
    four = [{"work_id": CITED, "score": 0.5}] * 4
    with pytest.raises(ValidationError):
        resolved([resolution(state="ambiguous", work_id=None, confidence=None, candidates=four)])
    with pytest.raises(ValidationError):
        resolved([resolution(score=1.5)])


def test_resolution_ordinals_unique_and_ascending() -> None:
    resolved([resolution(1), resolution(3)])  # a subset; the service checks membership
    for ordinals in ([1, 1], [2, 1], [0]):
        with pytest.raises(ValidationError):
            resolved([resolution(n) for n in ordinals])


def decided(**kw: Any) -> ReferenceResolutionDecided:
    base: dict[str, Any] = {
        "extraction_id": REX,
        "ordinal": 1,
        "decision": "confirm",
        "work_id": CITED,
        "rationale": "Same title, authors and year.",
        "quotes": [],
        "confirmed_by": "human",
    }
    base.update(kw)
    return ReferenceResolutionDecided.model_validate(base)


def test_decision_shapes() -> None:
    assert decided().decision is Decision.CONFIRM
    decided(decision="reject", work_id=None)
    decided(confirmed_by="second-agent")
    quotes = [
        {"side": "entry", "text": "An invented title about kernels"},
        {"side": "candidate", "text": "An Invented Title About Kernels"},
    ]
    decided(decision="propose-confirm", confirmed_by=None, quotes=quotes)
    with pytest.raises(ValidationError):  # a confirmation names its work
        decided(work_id=None)
    with pytest.raises(ValidationError):  # a binding decision names who confirmed
        decided(confirmed_by=None)
    with pytest.raises(ValidationError):  # a proposal is never a confirmation
        decided(decision="propose-confirm", confirmed_by="human", quotes=quotes)
    with pytest.raises(ValidationError):  # a proposal quotes both entries
        decided(decision="propose-reject", confirmed_by=None, quotes=quotes[:1])
    with pytest.raises(ValidationError):
        decided(rationale=" ")


def round_payload(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "round_id": SNW,
        "direction": "backward",
        "via": "document-reference-list",
        "round_no": 1,
        "sources": [WORK],
        "extraction_ids": [REX],
        "candidates": [
            {
                "work_key": CITED,
                "cited_by": [
                    {"work_id": WORK, "extraction_id": REX, "ordinal": 1, "anchors": ["s1.p2"]}
                ],
                "no_source_record": False,
            },
            {
                "work_key": f"{REX}:2",
                "cited_by": [{"work_id": WORK, "extraction_id": REX, "ordinal": 2, "anchors": []}],
                "no_source_record": True,
            },
        ],
        "queries": ["doi:10.9999/invented.1"],
        "chase_round_id": None,
        "rule": {"max_backward_rounds": 2, "max_forward_rounds": 0},
        "unextracted": [],
    }
    base.update(kw)
    return base


def test_round_valid_and_rule_none() -> None:
    r = SnowballRoundStarted.model_validate(round_payload())
    assert r.direction is Direction.BACKWARD and isinstance(r.rule, SnowballPlan)
    assert SnowballRoundStarted.model_validate(round_payload(rule="none")).rule == "none"
    assert "cited_by_included" not in SnowballRoundStarted.model_fields  # counts are derived


def test_round_direction_via_and_chase_link() -> None:
    fwd = round_payload(
        direction="forward", via="source-metadata", chase_round_id=CHS, candidates=[], queries=[]
    )
    SnowballRoundStarted.model_validate(fwd)
    for bad in (
        round_payload(via="source-metadata"),
        round_payload(chase_round_id=CHS),
        {**fwd, "chase_round_id": None},
        {**fwd, "via": "document-reference-list"},
        round_payload(round_no=0),
        round_payload(sources=[WORK, WORK]),
        round_payload(extraction_ids=[REX, REX]),
    ):
        with pytest.raises(ValidationError):
            SnowballRoundStarted.model_validate(bad)


def test_round_candidate_keys_and_citers() -> None:
    p = round_payload()
    dup = [p["candidates"][0], p["candidates"][0]]
    with pytest.raises(ValidationError):
        SnowballRoundStarted.model_validate(round_payload(candidates=dup))
    bad_key = [{**p["candidates"][0], "work_key": "not-a-key"}]
    with pytest.raises(ValidationError):
        SnowballRoundStarted.model_validate(round_payload(candidates=bad_key))
    stranger = {"work_id": CITED, "extraction_id": REX, "ordinal": 1, "anchors": []}
    foreign = [{**p["candidates"][0], "cited_by": [stranger]}]
    with pytest.raises(ValidationError):  # a citer is one of the round's sources
        SnowballRoundStarted.model_validate(round_payload(candidates=foreign))
    with pytest.raises(ValidationError):
        SnowballRoundStarted.model_validate(
            round_payload(unextracted=[{"work_id": CITED, "reason": " "}])
        )
