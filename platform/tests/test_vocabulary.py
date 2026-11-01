"""Vocabulary suggestions, ported from the old project's probe module, offline."""

from __future__ import annotations

from factory.model.probe import TermSuggestion
from factory.model.work import Provenance, Work
from factory.services.vocabulary import suggest_terms


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
