"""Candidate pairs of unmatched contribution rows (IDEA-140): pure scoring, then the service
over the agreement's unmatched rows. Pairs are proposals; nothing is written."""

# ruff: noqa: F401, F811

from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.extraction.pairing import PairRow, name_tokens, propose_pairs, score_pair
from factory.model.extraction import ExtractedRowInput
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.contribution_pairs import contribution_pairs
from factory.services.contributions import contribution_agreement
from tests.contribution_helpers import P1, P2, ctr_a, ctr_b, item, screened, with_references, world
from tests.test_contribution_agreement import RowsFor, _drive, refs

W = "w1"


def row(
    key: str,
    kind: str = "addition",
    text: str | None = None,
    work: str = W,
    absent: str | None = None,
    entry: int | None = None,
    anchor: str | None = None,
) -> PairRow:
    return PairRow(
        work_id=work,
        row_key=key,
        item_kind=kind,
        absent_kind=absent,
        text=text,
        cited_entry=entry,
        anchor=anchor,
    )


def test_names_are_free_text_tokens_without_et_al_and_years() -> None:
    assert name_tokens("Itti and Baldi") == (frozenset({"itti", "baldi"}), frozenset())
    assert name_tokens("Itti & Baldi [2005]") == (frozenset({"itti", "baldi"}), frozenset({"2005"}))
    assert name_tokens("Majumder et al.") == (frozenset({"majumder"}), frozenset())
    assert name_tokens(None) == (frozenset(), frozenset())


def test_same_name_different_anchors_pair() -> None:
    a = row("a1", text="Itti and Baldi", anchor="s1.p1")
    b = row("b1", text="Itti & Baldi [2005]", anchor="s4.p2")
    scored = score_pair(a, b)
    assert scored is not None and scored[0] == 0.6
    got = propose_pairs([a], [b])
    assert [(c.a_key, c.b_key) for c in got.pairs] == [("a1", "b1")]
    assert got.a_without == () and got.b_without == ()


def test_different_kinds_and_works_never_pair() -> None:
    a = row("a1", "addition", "Lorem")
    assert propose_pairs([a], [row("b1", "limitation", "Lorem")]).pairs == ()
    assert propose_pairs([a], [row("b1", "addition", "Lorem", work="w2")]).pairs == ()


def test_not_stated_pairs_only_on_the_same_absent_kind() -> None:
    a = row("a1", "not-stated", absent="base-idea")
    assert propose_pairs([a], [row("b1", "not-stated", absent="limitation")]).pairs == ()
    got = propose_pairs([a], [row("b1", "not-stated", absent="base-idea")])
    assert len(got.pairs) == 1


def test_anchor_alone_or_empty_names_give_no_candidate() -> None:
    a, b = row("a1", anchor="s1.p1"), row("b1", anchor="s1.p1")
    got = propose_pairs([a], [b])
    assert got.pairs == () and got.a_without == ((W, "a1"),) and got.b_without == ((W, "b1"),)


def test_cited_entry_alone_is_a_candidate_and_section_raises_the_score() -> None:
    a = row("a1", "base-idea", "x", entry=3, anchor="s2.1.p1")
    near = score_pair(a, row("b1", "base-idea", "y", entry=3, anchor="s2.1.p4"))
    far = score_pair(a, row("b2", "base-idea", "y", entry=3, anchor="s5.p1"))
    assert near is not None and far is not None and near[0] > far[0]


def test_each_row_is_proposed_once_greedy_by_score_with_key_tiebreak() -> None:
    a1, a2 = row("a1", text="deep ideation"), row("a2", text="deep ideation framework")
    b1, b2 = row("b1", text="deep ideation framework"), row("b2", text="deep ideation")
    got = propose_pairs([a2, a1], [b2, b1])
    assert [(c.a_key, c.b_key) for c in got.pairs] == [("a1", "b2"), ("a2", "b1")]
    tie = propose_pairs([row("a1", text="x"), row("a2", text="x")], [row("b1", text="x")])
    assert [(c.a_key, c.b_key) for c in tie.pairs] == [("a1", "b1")]
    assert tie.a_without == ((W, "a2"),) and tie.b_without == ()


def test_min_score_filters() -> None:
    a, b = row("a1", text="a b"), row("b1", text="a x")
    assert propose_pairs([a], [b], 0.1).pairs and not propose_pairs([a], [b], 0.5).pairs


def test_service_pairs_the_agreements_unmatched_rows_and_writes_nothing(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    def reading(anchor: tuple[str, str], extra: str) -> RowsFor:
        def rows(work: str) -> list[ExtractedRowInput]:
            if work != refs[0]:
                return []
            return [
                item("base-idea", anchor, name="attention"),
                item("addition", P2, name=extra),
                item("limitation", P2, name="softmax attention", statement="our module is linear"),
            ]

        return rows

    _drive(project, ctr_a, PassLabel.A, reading(P1, "softmax attention"))
    _drive(project, ctr_b, PassLabel.B, reading(P2, "module"))
    agreement = contribution_agreement(project, human)
    assert agreement.rows_unmatched == 4  # a base idea at two anchors, two different additions
    before = len(read_all(project.paths.events_dir, project.catalog))
    report = contribution_pairs(project, human)
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    assert [(p.a.item_kind, p.a.name, p.b.name) for p in report.pairs] == [
        ("base-idea", "attention", "attention")
    ]
    assert report.unmatched_a == 2 and report.unmatched_b == 2
    assert sorted(u.row.name or "" for u in report.without_candidate) == [
        "module",
        "softmax attention",
    ]
    assert contribution_pairs(project, human, work_id="other").pairs == []
