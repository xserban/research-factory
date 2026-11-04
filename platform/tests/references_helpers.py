"""Manifest builders for the reference-parsing tests."""

from factory.document.anchors import Anchor, AnchorKind, Manifest


def manifest(
    entries: list[str], body: list[str], *, b_anchors: bool = True, heading: str = "References"
) -> Manifest:
    """A document with one body section of paragraphs `body` and a bibliography section.

    With `b_anchors` the entries are `b1…`; otherwise paragraphs `s2.p<k>` of a section `s2`.
    """
    anchors = [
        Anchor("s1", AnchorKind.SECTION, None, "## 1 Intro"),
        *(Anchor(f"s1.p{i}", AnchorKind.PARAGRAPH, "s1", t) for i, t in enumerate(body, start=1)),
        Anchor("s2", AnchorKind.SECTION, None, f"## {heading}"),
    ]
    for i, t in enumerate(entries, start=1):
        anchors.append(
            Anchor(f"b{i}", AnchorKind.BIBLIOGRAPHY_ENTRY, "s2", t)
            if b_anchors
            else Anchor(f"s2.p{i}", AnchorKind.PARAGRAPH, "s2", t)
        )
    return Manifest(tuple(anchors))
