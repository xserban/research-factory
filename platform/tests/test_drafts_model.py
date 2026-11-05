"""Draft, sentence and support models and their events (slice 7b, plan W-A, task 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.events.catalog import default_catalog
from factory.events.envelope import Actor
from factory.model.drafts import (
    MAX_SUPPORTS,
    SENTENCE_MAX_CHARS,
    SentenceClass,
    SentenceRecorded,
    SupportKind,
    SupportRef,
    parse_support,
)
from factory.services.context import Project

ULID = "01JZ9Q3K5M7N8P0R2S4T6V8W00"
CLAIM = f"clm_{ULID}"
EXT = f"ext_{ULID}"
REL = f"rel_{ULID}"
REX = f"rex_{ULID}"
ROW = "rk_0123456789ab"


@pytest.mark.parametrize(
    ("text", "kind", "ref"),
    [
        (f"claim:{CLAIM}", SupportKind.CLAIM, CLAIM),
        (f"cell:{ROW}/metric", SupportKind.CELL, f"{ROW}/metric"),
        (f"cell:{ROW}", SupportKind.CELL, f"{ROW}/value"),
        (ROW, SupportKind.CELL, f"{ROW}/value"),
        (f"item:{EXT}", SupportKind.ITEM, EXT),
        (f"edge:{REL}", SupportKind.EDGE, REL),
        (f"edge:cit:{REX}:3", SupportKind.EDGE, f"cit:{REX}:3"),
        ("group:grp_0123456789ab", SupportKind.GROUP, "grp_0123456789ab"),
        ("stat:ideas-confirmed", SupportKind.STAT, "ideas-confirmed"),
        ("stat:group-works:grp_0123456789ab", SupportKind.STAT, "group-works:grp_0123456789ab"),
        ("stat:records:grp_0123456789ab:2021", SupportKind.STAT, "records:grp_0123456789ab:2021"),
        (f"interp:int_{ULID}", SupportKind.INTERP, f"int_{ULID}"),
        (f"interp:cpt_{ULID}", SupportKind.INTERP, f"cpt_{ULID}"),
    ],
)
def test_parse_support_grammar(text: str, kind: SupportKind, ref: str) -> None:
    parsed = parse_support(text)
    assert (parsed.kind, parsed.ref) == (kind, ref)
    assert parse_support(parsed.text) == parsed


@pytest.mark.parametrize(
    "text",
    [
        "",
        "clm_nothing",
        "claim:nope",
        f"claim:{EXT}",
        "cell:rk_short/value",
        f"cell:{ROW}/Bad Field",
        "edge:cit:rex_x:0",
        "group:grp_xyz",
        "stat:",
        "stat:Upper:case",
        f"interp:{CLAIM}",
        "unknown:thing",
        f"{CLAIM}",
    ],
)
def test_malformed_support_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_support(text)


def _sentence(**over: object) -> SentenceRecorded:
    body: dict[str, object] = {
        "sentence_id": f"snt_{ULID}",
        "draft_id": f"drf_{ULID}",
        "section_id": "sec_01",
        "order": 0,
        "cls": SentenceClass.CLAIM,
        "text": "Method X reaches the stated score.",
        "supports": [parse_support(f"claim:{CLAIM}")],
        "stats_version": 1,
        "author": "human",
    }
    body.update(over)
    return SentenceRecorded.model_validate(body)


def test_text_bounds() -> None:
    assert _sentence(text="x" * SENTENCE_MAX_CHARS)
    with pytest.raises(ValidationError):
        _sentence(text="x" * (SENTENCE_MAX_CHARS + 1))
    with pytest.raises(ValidationError):
        _sentence(text="   ")


def test_supports_bounds() -> None:
    many = [
        SupportRef(kind=SupportKind.STAT, ref=f"records:grp_0123456789ab:{2000 + i}")
        for i in range(MAX_SUPPORTS + 1)
    ]
    values = {s.ref: i for i, s in enumerate(many)}
    with pytest.raises(ValidationError):
        _sentence(supports=many, stat_values=values)
    assert _sentence(supports=many[:MAX_SUPPORTS], stat_values={s.ref: 1 for s in many[:6]})


def test_structural_has_no_supports() -> None:
    assert _sentence(cls=SentenceClass.STRUCTURAL, supports=[])
    with pytest.raises(ValidationError):
        _sentence(cls=SentenceClass.STRUCTURAL)


def test_interp_support_only_in_interpretive() -> None:
    interp = [parse_support(f"interp:int_{ULID}")]
    assert _sentence(cls=SentenceClass.INTERPRETIVE, supports=interp)
    with pytest.raises(ValidationError):
        _sentence(cls=SentenceClass.CLAIM, supports=interp)


def test_stat_values_match_stat_supports() -> None:
    stat = [parse_support("stat:ideas-confirmed")]
    assert _sentence(cls=SentenceClass.SYNTHESIS, supports=stat, stat_values={"ideas-confirmed": 2})
    with pytest.raises(ValidationError):
        _sentence(cls=SentenceClass.SYNTHESIS, supports=stat)
    with pytest.raises(ValidationError):
        _sentence(stat_values={"ideas-confirmed": 2})


def test_duplicate_supports_refused() -> None:
    one = parse_support(f"claim:{CLAIM}")
    with pytest.raises(ValidationError):
        _sentence(supports=[one, one])


def test_catalog_registers_types() -> None:
    names = default_catalog().names()
    for name in (
        "draft.created",
        "draft.outline_repinned",
        "draft.sentence_recorded",
        "draft.sentence_withdrawn",
        "draft.reordered",
    ):
        assert name in names


def test_agent_event_requires_provenance(project: Project, agent: Actor) -> None:
    payload = _sentence(author="agent")
    with pytest.raises(ValueError):
        project.events.make("draft.sentence_recorded", payload, agent)  # no input_blob
    blob = project.blobs.put_json({"task": "x"})
    event = project.events.make("draft.sentence_recorded", payload, agent, input_blob=blob)
    assert event.actor.model is not None and event.actor.skill is not None
