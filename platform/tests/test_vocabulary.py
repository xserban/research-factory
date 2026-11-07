"""Vocabulary suggestions, ported from the old project's probe module, offline."""

from __future__ import annotations

from factory.model.probe import TermSuggestion
from factory.model.work import Provenance, Work
from factory.services.vocabulary import GENERIC_ACADEMIC, suggest_terms


def _paper(prov: Provenance, title: str, abstract: str = "") -> Work:
    return Work.build(title=title, abstract=abstract or None, provenance=[prov])


def _terms(rows: list[TermSuggestion]) -> list[str]:
    return [row.term for row in rows]


def test_suggests_phrase_shared_by_missed_seeds(prov: Provenance) -> None:
    missed = [
        _paper(prov, "Alpha", "we study vessel segmentation in fundus images"),
        _paper(prov, "Beta", "vessel segmentation with few labels"),
    ]
    other = _paper(prov, "Unrelated", "protein folding dynamics")
    rows = suggest_terms(missed, [*missed, other], "all:retina")

    assert "vessel segmentation" in _terms(rows)
    row = next(r for r in rows if r.term == "vessel segmentation")
    assert row.seeds == 2
    assert row.holders == (missed[0].id, missed[1].id)


def test_ignores_terms_already_in_query(prov: Provenance) -> None:
    missed = [
        _paper(prov, "Study", "vessel segmentation of fundus imaging"),
        _paper(prov, "Study two", "vessel segmentation of fundus imaging"),
    ]
    query = 'ti:vessel AND all:"fundus imaging" OR all:retina'
    terms = _terms(suggest_terms(missed, missed, query))

    assert not any(t in terms for t in ("vessel", "fundus imaging"))
    for artefact in ("ti", "all", "and", "or", "not"):
        assert artefact not in terms


def test_single_paper_terms_are_not_suggested(prov: Provenance) -> None:
    lone = _paper(prov, "Lone", "rarephrase appears in only this abstract")
    bystander = _paper(prov, "Bystander", "nothing relevant here")
    assert not any("rarephrase" in t for t in _terms(suggest_terms([lone], [lone, bystander], "x")))


def test_more_specific_phrase_wins(prov: Provenance) -> None:
    missed = [
        _paper(prov, "A", "retinal vessel segmentation benchmark"),
        _paper(prov, "B", "retinal vessel segmentation dataset"),
    ]
    terms = _terms(suggest_terms(missed, missed, "all:unrelated"))

    assert "retinal vessel segmentation" in terms
    assert "vessel segmentation" not in terms


def test_noise_words_dropped(prov: Provenance) -> None:
    missed = [
        _paper(prov, "Alpha", "novel approach method results"),
        _paper(prov, "Beta", "novel approach method results"),
    ]
    assert suggest_terms(missed, missed, "all:unrelated") == []


def test_no_missed_seeds_no_suggestions(prov: Provenance) -> None:
    seeds = [
        _paper(prov, "Shared", "vessel segmentation"),
        _paper(prov, "Shared 2", "vessel segmentation"),
    ]
    assert suggest_terms([], seeds, "all:unrelated") == []


def test_generic_academic_words_are_not_suggested(prov: Provenance) -> None:
    text = "we introduce a driven framework and demonstrate experiments across each task"
    missed = [_paper(prov, "Alpha", text), _paper(prov, "Beta", text)]
    assert suggest_terms(missed, missed, "all:unrelated") == []


def test_phrases_edged_by_a_generic_word_are_dropped_but_content_words_stay(
    prov: Provenance,
) -> None:
    missed = [
        _paper(prov, "Alpha", "we propose human feedback calibration"),
        _paper(prov, "Beta", "we propose human feedback calibration"),
    ]
    terms = _terms(suggest_terms(missed, missed, "all:unrelated"))

    assert "feedback calibration" in terms
    assert not any(
        t.split()[0] in GENERIC_ACADEMIC or t.split()[-1] in GENERIC_ACADEMIC for t in terms
    )
    assert "human feedback" not in terms
    assert "propose" not in terms


def test_generic_list_documents_the_pilot_words() -> None:
    pilot = {"introduce", "driven", "accelerating", "demonstrate", "experiments", "framework"}
    pilot |= {"across", "task", "human", "propose", "present", "show", "results", "method"}
    pilot |= {"approach", "novel", "paper", "study"}
    assert pilot <= GENERIC_ACADEMIC
