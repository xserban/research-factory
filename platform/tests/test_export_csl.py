import json
from datetime import date

from factory.exports.csl import csl_item, csl_json
from factory.model.work import Author, Dates, Identifiers, Venue, WorkType
from tests.export_helpers import make_work


def test_csl_item_shape() -> None:
    work = make_work(
        type=WorkType.CONFERENCE_PAPER,
        dates=Dates(published=date(2020, 7, 1)),
        venue=Venue(name="ICML", volume="1", issue="2", pages="3-4", publisher="PMLR"),
        identifiers=Identifiers(doi="10.1/x", url="https://e.org", isbn="123"),
    )
    it = csl_item(work, "k")
    assert it["type"] == "paper-conference" and it["id"] == "k"
    assert it["issued"] == {"date-parts": [[2020, 7, 1]]}
    assert it["container-title"] == "ICML" and it["DOI"] == "10.1/x" and it["page"] == "3-4"
    assert it["publisher"] == "PMLR" and it["ISBN"] == "123" and it["issue"] == "2"


def test_type_mapping() -> None:
    assert csl_item(make_work(type=WorkType.PREPRINT), "k")["type"] == "article"
    assert csl_item(make_work(type=WorkType.JOURNAL_ARTICLE), "k")["type"] == "article-journal"
    assert csl_item(make_work(type=WorkType.BLOG_POST), "k")["type"] == "document"


def test_absent_fields_omitted() -> None:
    it = csl_item(make_work(dates=Dates()), "k")
    assert set(it) == {"id", "type", "title"}


def test_author_name_forms() -> None:
    work = make_work(authors=[Author(name="Vaswani, Ashish"), Author(name="Noam")])
    assert csl_item(work, "k")["author"] == [
        {"family": "Vaswani", "given": "Ashish"},
        {"literal": "Noam"},
    ]


def test_csl_json_is_valid_and_ordered() -> None:
    text = "".join(csl_json([("a", make_work(title="A x")), ("b", make_work(title="B y"))]))
    assert [i["id"] for i in json.loads(text)] == ["a", "b"]
    assert text.endswith("]\n") and ",\n{" in text
    assert text == "".join(csl_json([("a", make_work(title="A x")), ("b", make_work(title="B y"))]))
    assert "".join(csl_json([])) == "[]\n"
