"""Payload builders for relation and idea events (slice 3b, plan G2-C)."""

from __future__ import annotations

from typing import Any

SRC = "rf:zhou2021-linear-attention-1a2b3c4d"
TGT = "rf:katharopoulos2020-transformers-0a1b2c3d"
OTHER = "rf:wang2020-linformer-9f8e7d6c"
ITEM = "ext_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
ITEM2 = "ext_01HZX3K4M5N6P7Q8R9S0TVWXZ0"
REX = "rex_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
REL = "rel_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
REL2 = "rel_01HZX3K4M5N6P7Q8R9S0TVWXZ0"
IDA = "ida_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
IDA2 = "ida_01HZX3K4M5N6P7Q8R9S0TVWXZ0"
IDA3 = "ida_01HZX3K4M5N6P7Q8R9S0TVWXZ1"


def stated(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "relation_id": REL,
        "source_work": SRC,
        "target": TGT,
        "edge_type": "builds-on",
        "basis_item": ITEM,
        "note": None,
        "status": "stated",
        "status_reason": None,
        "resolved_target": TGT,
        "reference_extraction_id": REX,
        "cited_entry": 5,
        "flags": [],
        "classifier": "1",
        "supersedes": None,
    }
    payload.update(overrides)
    return payload


def inferred(**overrides: Any) -> dict[str, Any]:
    payload = stated(
        status="inferred",
        status_reason="target-differs",
        resolved_target=OTHER,
    )
    payload.update(overrides)
    return payload


def decided(relation_id: str = REL, decision: str = "confirm", **overrides: Any) -> dict[str, Any]:
    return {
        "relation_id": relation_id,
        "decision": decision,
        "rationale": "checked",
        **overrides,
    }


def idea(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "idea_id": IDA,
        "name": "Linear attention",
        "name_item": ITEM,
        "origin": TGT,
        "members": sorted([SRC, TGT]),
        "supersedes": None,
    }
    payload.update(overrides)
    return payload


def merge(from_idea: str = IDA, into: str = IDA2, reason: str = "same method") -> dict[str, Any]:
    return {"from_idea": from_idea, "into": into, "reason": reason}
