"""MeSH suggestions from a probe's PubMed sample: pure counts, read-only."""

from __future__ import annotations

from factory.services.mesh_suggestions import mesh_suggestions


def test_counts_order_and_sampled() -> None:
    rows = mesh_suggestions(
        [("Stroke", "Thrombectomy"), ("Stroke",), ("Thrombectomy", "Brain Ischemia"), ()],
        "unrelated",
    )
    assert [(r.descriptor, r.records, r.sampled) for r in rows] == [
        ("Stroke", 2, 3),
        ("Thrombectomy", 2, 3),
        ("Brain Ischemia", 1, 3),
    ]


def test_ties_break_alphabetically_and_input_order_does_not_matter() -> None:
    a = mesh_suggestions([("B",), ("A",)], "")
    b = mesh_suggestions([("A",), ("B",)], "")
    assert a == b
    assert [r.descriptor for r in a] == ["A", "B"]


def test_check_tags_and_query_terms_are_left_out() -> None:
    rows = mesh_suggestions(
        [("Humans", "female", "Stroke", "Aged, 80 and over", "Dysphagia")],
        '"stroke"[MeSH Terms] AND swallowing',
    )
    assert [r.descriptor for r in rows] == ["Dysphagia"]


def test_a_repeated_descriptor_counts_once_per_record() -> None:
    [row] = mesh_suggestions([("Stroke", "Stroke")], "")
    assert row.records == 1


def test_limit_and_empty() -> None:
    assert mesh_suggestions([], "x") == ()
    assert mesh_suggestions([()], "x") == ()
    rows = mesh_suggestions([tuple(f"D{i:02d}" for i in range(30))], "", limit=5)
    assert len(rows) == 5
