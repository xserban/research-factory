from datetime import date

import bibtexparser  # type: ignore[import-untyped]

from factory.exports.bibtex import bibtex, bibtex_entry
from factory.model.work import Author, Dates, Identifiers, Venue, WorkType
from tests.export_helpers import make_work


def test_article_entry_round_trips() -> None:
    work = make_work(
        type=WorkType.JOURNAL_ARTICLE,
        venue=Venue(name="JMLR", volume="21", issue="3", pages="1--9"),
        identifiers=Identifiers(doi="10.1/x"),
        authors=[Author(name="Vaswani, Ashish"), Author(name="Noam")],
    )
    entry = bibtexparser.loads(bibtex_entry(work, "k")).entries[0]
    assert entry["ENTRYTYPE"] == "article" and entry["ID"] == "k"
    assert entry["journal"] == "JMLR" and entry["volume"] == "21" and entry["number"] == "3"
    assert entry["year"] == "2020" and entry["doi"] == "10.1/x"
    assert entry["author"] == "Vaswani, Ashish and {Noam}"


def test_preprint_has_eprint() -> None:
    work = make_work(type=WorkType.PREPRINT, identifiers=Identifiers(arxiv="2006.16236"))
    text = bibtex_entry(work, "k")
    assert text.startswith("@misc{k,")
    assert "eprint = {2006.16236}" in text and "archivePrefix = {arXiv}" in text


def test_dataset_is_misc_with_howpublished() -> None:
    text = bibtex_entry(make_work(type=WorkType.DATASET), "k")
    assert text.startswith("@misc{k,") and "howpublished = {Dataset}" in text


def test_type_mapping() -> None:
    pairs = {
        WorkType.CONFERENCE_PAPER: "@inproceedings",
        WorkType.BOOK_CHAPTER: "@incollection",
        WorkType.THESIS: "@phdthesis",
        WorkType.TECH_REPORT: "@techreport",
        WorkType.BLOG_POST: "@misc",
    }
    for kind, prefix in pairs.items():
        assert bibtex_entry(make_work(type=kind), "k").startswith(prefix)


def test_venue_field_by_type() -> None:
    work = make_work(type=WorkType.CONFERENCE_PAPER, venue=Venue(name="ICML"))
    assert "booktitle = {ICML}" in bibtex_entry(work, "k")


def test_absent_fields_omitted() -> None:
    text = bibtex_entry(make_work(venue=None, dates=Dates()), "k")
    for name in ("journal", "year", "doi", "url", "author", "volume"):
        assert f"{name} =" not in text


def test_special_characters_escaped() -> None:
    text = bibtex_entry(make_work(title="R&D 50% of $x_1 #a {b}"), "k")
    assert r"R\&D 50\% of \$x\_1 \#a \{b\}" in text


def test_ascii_option_escapes_accents() -> None:
    work = make_work(authors=[Author(name="Müller, A.")], title="Łódź ß 日")
    text = bibtex_entry(work, "k", ascii_only=True)
    assert r"M{\"u}ller" in text and r"{\ss}" in text and r"{\L}" in text
    assert r'{\char"65E5}' in text
    assert text.isascii()
    assert "Müller" in bibtex_entry(work, "k")


def test_title_double_braced() -> None:
    assert "title = {{Attention is all you need}}" in bibtex_entry(make_work(), "k")


def test_bibtex_stream_order_and_separation() -> None:
    a, b = make_work(title="A one"), make_work(title="B two")
    text = "".join(bibtex([("a", a), ("b", b)]))
    assert text.index("@misc{a,") < text.index("@misc{b,")
    assert "}\n\n@misc{b," in text and text.endswith("}\n")
    assert len(bibtexparser.loads(text).entries) == 2
    assert "".join(bibtex([])) == ""


def test_year_from_published() -> None:
    assert "year = {2019}" in bibtex_entry(make_work(dates=Dates(published=date(2019, 1, 2))), "k")
