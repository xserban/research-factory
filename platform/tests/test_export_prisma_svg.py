import itertools
import xml.etree.ElementTree as ET
from typing import Any

from factory.exports.prisma_svg import PRISMA_TEMPLATE_VERSION, prisma_svg
from factory.services.prisma import FullTextBoxes, PrismaFlow

NS = "{http://www.w3.org/2000/svg}"


def flow(**kw: Any) -> PrismaFlow:
    base: dict[str, Any] = {
        "identified_databases": {"openalex": 420, "arxiv": 80},
        "identified_other": {"citation-chase": 10, "seed-admission": 0, "hand-search": 0},
        "duplicates_removed": 60,
        "excluded": {"C1": 300, "C2": 40},
        "pending": 0,
        "included": 110,
        "provisional": False,
        "protocol_id": "proto_x",
    }
    base.update(kw)
    if "screened" not in kw:
        identified = sum(base["identified_databases"].values()) + sum(
            base["identified_other"].values()
        )
        base["screened"] = identified - base["duplicates_removed"]
        if "included" not in kw:
            base["included"] = base["screened"] - sum(base["excluded"].values()) - base["pending"]
    return PrismaFlow(**base)


def texts(f: PrismaFlow) -> str:
    return " ".join(t.text or "" for t in ET.fromstring(prisma_svg(f)).iter(f"{NS}text"))


def ran_boxes() -> FullTextBoxes:
    return FullTextBoxes(
        sought=100,
        not_retrieved=10,
        not_retrieved_reasons={"unsought": 4, "unconverted": 6},
        eligible=90,
        assessed=90,
        excluded={"C3": 30},
        pending=0,
        included=60,
        stage_run=True,
        provisional=False,
    )


def test_template_version() -> None:
    assert PRISMA_TEMPLATE_VERSION == 1


def test_svg_parses_and_has_boxes() -> None:
    root = ET.fromstring(prisma_svg(flow()))
    assert len(root.findall(f".//{NS}rect")) >= 9


def test_svg_numbers_equal_flow() -> None:
    f = flow()
    out = texts(f)
    assert "openalex (n = 420)" in out and "arxiv (n = 80)" in out
    assert "citation-chase (n = 10)" in out
    assert "Duplicate records removed (n = 60)" in out
    assert f"Records screened (n = {f.screened})" in out
    assert f"Records excluded (n = {f.excluded_total})" in out


def test_excluded_reasons_listed_per_criterion() -> None:
    out = texts(flow())
    assert "C1 (n = 300)" in out and "C2 (n = 40)" in out


def test_full_text_not_run_boxes() -> None:
    out = texts(flow())
    assert "not run" in out
    assert "Reports assessed for eligibility" in out


def test_full_text_boxes_when_run() -> None:
    f = flow(full_text=ran_boxes(), included_in_review=60)
    out = texts(f)
    assert "not run" not in out
    assert "Reports sought for retrieval (n = 100)" in out
    assert "Reports not retrieved (n = 10)" in out and "unconverted (n = 6)" in out
    assert "Reports assessed for eligibility (n = 90)" in out
    assert "Reports excluded (n = 30)" in out and "C3 (n = 30)" in out
    assert "Studies included in review (n = 60)" in out


def test_provisional_banner() -> None:
    f = flow(pending=3, provisional=True, excluded={"C1": 300})
    assert "Provisional: 3 records pending" in prisma_svg(f)
    assert "Provisional" not in prisma_svg(flow())


def test_full_text_pending_banner() -> None:
    boxes = ran_boxes().model_copy(
        update={"assessed": 80, "pending": 10, "provisional": True, "included": 50}
    )
    assert "Provisional: 10 reports pending" in prisma_svg(flow(full_text=boxes))


def test_long_source_names_wrap_and_shift() -> None:
    long = "a-very-long-source-name-" * 6
    f = flow(identified_databases={long: 480})
    root = ET.fromstring(prisma_svg(f))
    rects = [
        (int(r.get("y", "0")), int(r.get("height", "0")), int(r.get("x", "0")))
        for r in root.findall(f".//{NS}rect")
    ]
    first = rects[0]
    assert first[1] > 2 * 8 + 14 * 3
    left = [r for r in rects if r[2] == 20]
    for earlier, later in itertools.pairwise(left):
        assert later[0] > earlier[0] + earlier[1]


def test_deterministic() -> None:
    assert prisma_svg(flow()) == prisma_svg(flow())


def test_text_escaped() -> None:
    f = flow(identified_databases={"a<b&c": 500})
    svg = prisma_svg(f)
    assert "a&lt;b&amp;c (n = 500)" in svg
    assert "a<b" not in svg
    ET.fromstring(svg)


def test_non_ascii_wraps_wider() -> None:
    f = flow(identified_databases={"日本語" * 20: 500})
    root = ET.fromstring(prisma_svg(f))
    assert len(root.findall(f".//{NS}text")) > 10


def test_awaiting_classification_box_prints_and_identities_hold() -> None:
    import pytest

    from factory.cli.render import prisma_markdown

    boxes = FullTextBoxes(
        sought=100,
        not_retrieved=10,
        not_retrieved_reasons={"unsought": 10},
        eligible=90,
        assessed=85,
        excluded={"C3": 30},
        pending=0,
        included=55,
        stage_run=True,
        provisional=True,
        awaiting_classification=5,
    )
    f = flow(full_text=boxes)
    assert "Awaiting classification (n = 5)" in texts(f)
    assert "Provisional: 0 reports pending, 5 awaiting classification" in texts(f)
    assert "- awaiting classification: 5" in prisma_markdown(f)
    assert "awaiting classification." in prisma_markdown(f)  # the provisional note
    assert "awaiting_classification" not in ran_boxes().model_dump()
    assert "awaiting classification" not in prisma_markdown(flow(full_text=ran_boxes()))
    with pytest.raises(ValueError):
        FullTextBoxes(**{**boxes.model_dump(), "awaiting_classification": 4})
    with pytest.raises(ValueError, match="pending or awaiting"):
        FullTextBoxes(**{**boxes.model_dump(), "provisional": False})
