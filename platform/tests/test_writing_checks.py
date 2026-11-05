"""Pure write-time checks (slice 7b, plan W-A, task 3; spec rulings 9 and 11)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from factory.model.drafts import SentenceClass, SentenceFlag, SupportKind, SupportRef
from factory.services.supports import ResolvedSupport
from factory.writing.checks import (
    COMPARATIVES,
    QUANTIFIERS,
    CheckOutcome,
    DraftContext,
    check_sentence,
    is_single_sentence,
)

CLAIM, SYNTH = SentenceClass.CLAIM, SentenceClass.SYNTHESIS
INTERP, STRUCT = SentenceClass.INTERPRETIVE, SentenceClass.STRUCTURAL
ULID = "01JZ9Q3K5M7N8P0R2S4T6V8W00"
NOCTX = DraftContext()


def sup(
    kind: SupportKind = SupportKind.CLAIM,
    ref: str | None = None,
    *,
    spans: tuple[str, ...] = (),
    numbers: tuple[Decimal, ...] = (),
    works: tuple[str, ...] = ("rf:a",),
    groups: tuple[str, ...] = (),
    authors: tuple[str, ...] = (),
    years: tuple[int, ...] = (),
    stat: int | None = None,
    eligible: bool = True,
    reason: str | None = None,
    methods: tuple[str, ...] = (),
) -> ResolvedSupport:
    refs = {
        SupportKind.CLAIM: f"clm_{ULID}",
        SupportKind.CELL: "rk_0123456789ab/value",
        SupportKind.ITEM: f"ext_{ULID}",
        SupportKind.EDGE: f"rel_{ULID}",
        SupportKind.GROUP: "grp_0123456789ab",
        SupportKind.STAT: "included-works",
        SupportKind.INTERP: f"int_{ULID}",
    }
    return ResolvedSupport(
        ref=SupportRef(kind=kind, ref=ref or refs[kind]),
        eligible=eligible,
        reason=reason,
        work_ids=works,
        spans=spans,
        numbers=numbers,
        group_ids=groups,
        stat_value=stat,
        first_authors=authors,
        years=years,
        method_names=methods,
    )


def run(
    text: str,
    cls: SentenceClass,
    *supports: ResolvedSupport,
    ctx: DraftContext = NOCTX,
    outline: frozenset[str] | None = None,
) -> CheckOutcome:
    return check_sentence(text, cls, supports, draft_context=ctx, outline_refs=outline)


def reasons(outcome: CheckOutcome) -> list[str]:
    return [i.reason for i in outcome.refusals]


def test_number_check() -> None:  # Review Focus 2
    s = sup(spans=("reaches 85.2 % top-1",))
    assert not run("X reaches 85.2% top-1 accuracy", CLAIM, s).refusals
    assert not run("X reaches 85.2 top-1 accuracy", CLAIM, s).refusals
    refused = run("X reaches 85.3% top-1 accuracy", CLAIM, s)
    assert reasons(refused) == ["number-unsupported"]
    assert refused.refusals[0].field == "text.numbers[0]"


def test_number_check_does_not_normalise_further() -> None:
    s = sup(spans=("reaches 0.852 top-1",))
    assert reasons(run("X reaches 85.2% top-1 accuracy", CLAIM, s)) == ["number-unsupported"]


def test_year_of_support_work_allowed() -> None:
    s = sup(spans=("a quote",), years=(2020,))
    assert not run("The method appeared in 2020", CLAIM, s).refusals
    assert reasons(run("The method appeared in 2019", CLAIM, s)) == ["number-unsupported"]


def test_stat_value_supports_number() -> None:
    s = sup(SupportKind.STAT, stat=12, numbers=(Decimal(12),), works=())
    assert not run("Twelve works remain, 12 in all", SYNTH, s, sup(SupportKind.GROUP)).refusals
    assert reasons(run("13 works remain", SYNTH, s, sup(SupportKind.GROUP))) == [
        "number-unsupported"
    ]


def test_cell_numbers_support_the_value() -> None:
    s = sup(SupportKind.CELL, numbers=(Decimal("85.2"), Decimal("0.852")))
    assert not run("It scores 85.2 on the benchmark", CLAIM, s).refusals


def test_two_sentences_refused() -> None:
    s = sup()
    assert reasons(run("A works. B fails.", CLAIM, s)) == ["more-than-one-sentence"]
    assert reasons(run("Is it so? Yes it is", CLAIM, s)) == ["more-than-one-sentence"]
    assert reasons(run("It works. 3 trials failed", CLAIM, s))[0] == "more-than-one-sentence"


@pytest.mark.parametrize(
    "text",
    [
        "Katharopoulos et al. show that it scales",
        "Several models, e.g. Performer, scale linearly",
        "That is, i.e. the kernel, scales",
        "See Fig. 3 and Eq. 2 for the setting",
        "J. Smith and K. Jones report a gain",
        "It beats the baseline vs. the original",
        "The score is 85.2 on the benchmark.",
    ],
)
def test_abbreviations_do_not_split(text: str) -> None:
    assert is_single_sentence(text)


def test_structural_refusals() -> None:  # Review Focus 3
    ctx = DraftContext(
        first_authors=frozenset({"choromanski", "performer"}), method_names=frozenset({"performer"})
    )
    assert "structural-number" in reasons(run("Section 3 follows", STRUCT, ctx=ctx))
    assert "structural-citation" in reasons(run("This follows [12] closely", STRUCT, ctx=ctx))
    assert "structural-author-year" in reasons(
        run("Choromanski et al. in 2021 changed this", STRUCT, ctx=ctx)
    )
    both = reasons(run("Performer (2021) is discussed next", STRUCT, ctx=ctx))
    assert "structural-author-year" in both and "structural-method-name" in both
    assert "structural-method-name" in reasons(run("Next we turn to Performer", STRUCT, ctx=ctx))
    assert not run("Next we turn to the open questions", STRUCT, ctx=ctx).refusals
    assert not run("Next we turn to Performer", STRUCT).refusals  # no context, no refusal


def test_structural_with_support_refused() -> None:
    assert "structural-has-support" in reasons(run("Next we turn to scope", STRUCT, sup()))


def test_interpretive_without_numbers() -> None:
    interp = sup(SupportKind.INTERP, works=())
    assert not run("This reads as a sign of a capacity limit", INTERP, interp).refusals
    assert reasons(run("This reads as a 2 point limit", INTERP, interp)) == [
        "interpretive-has-number"
    ]


def test_claim_needs_support_synthesis_needs_stat_or_group() -> None:
    assert "claim-needs-support" in reasons(run("It works", CLAIM))
    assert "synthesis-needs-stat-or-group" in reasons(run("Most work", SYNTH, sup()))
    assert not run("Several works", SYNTH, sup(SupportKind.GROUP, works=("rf:a", "rf:b"))).refusals


def test_ineligible_support_is_a_refusal_with_its_reason() -> None:
    bad = sup(eligible=False, reason="superseded")
    out = run("It works", CLAIM, sup(), bad)
    assert [(i.field, i.reason) for i in out.refusals] == [("supports[1]", "superseded")]


def test_citation_mismatch_flag() -> None:
    s = sup(spans=("a",), authors=("katharopoulos",), years=(2020,))
    assert (
        SentenceFlag.CITATION_MISMATCH in run("Choromanski et al. (2020) show it", CLAIM, s).flags
    )
    assert (
        SentenceFlag.CITATION_MISMATCH
        not in run("Katharopoulos et al. (2020) show it", CLAIM, s).flags
    )
    assert SentenceFlag.CITATION_MISMATCH in run("It was shown [12]", CLAIM, s).flags


def test_quantifier_flag_and_stat_clears_it() -> None:
    s = sup()
    assert SentenceFlag.QUANTIFIER_WITHOUT_STATISTIC in run("Most methods scale", CLAIM, s).flags
    assert (
        SentenceFlag.QUANTIFIER_WITHOUT_STATISTIC in run("It is state-of-the-art", CLAIM, s).flags
    )
    stat = sup(SupportKind.STAT, stat=3, works=())
    assert (
        SentenceFlag.QUANTIFIER_WITHOUT_STATISTIC
        not in run("Most methods scale", CLAIM, s, stat).flags
    )
    assert SentenceFlag.QUANTIFIER_WITHOUT_STATISTIC not in run("Mostly fine", CLAIM, s).flags
    assert (
        SentenceFlag.QUANTIFIER_WITHOUT_STATISTIC not in run("Calling all cars", SYNTH, stat).flags
    )


def test_quantifier_list_is_closed() -> None:
    assert set(QUANTIFIERS) == {
        "all", "every", "none", "always", "never", "consistently", "most", "majority", "best",
        "state-of-the-art", "outperforms all",
    }  # fmt: skip
    assert "better" in COMPARATIVES


def test_cross_group_flag() -> None:
    a = sup(SupportKind.CELL, groups=("grp_aaaaaaaaaaaa",))
    b = sup(SupportKind.CELL, "rk_ffffffffffff/value", groups=("grp_bbbbbbbbbbbb",))
    assert SentenceFlag.CROSS_GROUP in run("A is better than B", CLAIM, a, b).flags
    assert SentenceFlag.CROSS_GROUP not in run("A and B differ", CLAIM, a, b).flags
    assert SentenceFlag.CROSS_GROUP not in run("A is better than B", CLAIM, a).flags


def test_single_source_generalisation_flag() -> None:
    group = sup(SupportKind.GROUP, works=("rf:a",))
    assert SentenceFlag.SINGLE_SOURCE_GENERALISATION in run("Works scale", SYNTH, group).flags
    many = sup(SupportKind.GROUP, works=("rf:a", "rf:b"))
    assert SentenceFlag.SINGLE_SOURCE_GENERALISATION not in run("Works scale", SYNTH, many).flags
    assert SentenceFlag.SINGLE_SOURCE_GENERALISATION not in run("It scales", CLAIM, group).flags


def test_off_outline_flag() -> None:
    s = sup()
    assert SentenceFlag.OFF_OUTLINE in run("It works", CLAIM, s, outline=frozenset()).flags
    assert (
        SentenceFlag.OFF_OUTLINE
        not in run("It works", CLAIM, s, outline=frozenset({s.ref.text})).flags
    )
    assert SentenceFlag.OFF_OUTLINE not in run("It works", CLAIM, s, outline=None).flags
    cell = sup(SupportKind.CELL, groups=("grp_0123456789ab",))
    assert (
        SentenceFlag.OFF_OUTLINE
        not in run("It works", CLAIM, cell, outline=frozenset({"group:grp_0123456789ab"})).flags
    )
    stat = sup(SupportKind.STAT, stat=1, works=())
    assert (
        SentenceFlag.OFF_OUTLINE
        not in run(
            "One",
            SYNTH,
            stat,
            sup(SupportKind.GROUP),
            outline=frozenset({"group:grp_0123456789ab"}),
        ).flags
    )


def test_no_text_in_issues() -> None:
    secret = "zebra-quote-xyzzy"
    s = sup(spans=(secret,))
    out = run(f"{secret} reaches 77 on a thing. Second {secret} sentence", CLAIM, s)
    assert out.refusals
    for issue in out.refusals:
        assert secret not in issue.field and secret not in issue.reason
        assert "77" not in issue.field and "77" not in issue.reason
