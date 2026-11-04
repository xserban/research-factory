"""BibTeX serialiser. Pure; an absent field on the work is an absent line, never a placeholder.

Output is deterministic: fields are written in a fixed order and entries in the order given.
"""

import unicodedata
from collections.abc import Iterable, Iterator

from factory.model.work import Author, Work, WorkType

_TYPES: dict[WorkType, str] = {
    WorkType.JOURNAL_ARTICLE: "article",
    WorkType.CONFERENCE_PAPER: "inproceedings",
    WorkType.BOOK_CHAPTER: "incollection",
    WorkType.THESIS: "phdthesis",
    WorkType.TECH_REPORT: "techreport",
}
_VENUE_FIELD: dict[str, str] = {
    "article": "journal",
    "inproceedings": "booktitle",
    "incollection": "booktitle",
    "phdthesis": "school",
    "techreport": "institution",
    "misc": "howpublished",
}
_SPECIAL: dict[str, str] = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "%": r"\%",
    "&": r"\&",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
}
_ACCENT: dict[str, str] = {
    "̀": "`",
    "́": "'",
    "̂": "^",
    "̃": "~",
    "̈": '"',
    "̄": "=",
    "̇": ".",
}
_ACCENT_ALPHA: dict[str, str] = {"̧": "c", "̌": "v", "̊": "r", "̆": "u"}
_LETTERS: dict[str, str] = {
    "ß": r"{\ss}",
    "ø": r"{\o}",
    "Ø": r"{\O}",
    "æ": r"{\ae}",
    "Æ": r"{\AE}",
    "œ": r"{\oe}",
    "Œ": r"{\OE}",
    "å": r"{\aa}",
    "Å": r"{\AA}",
    "ł": r"{\l}",
    "Ł": r"{\L}",
    "ı": r"{\i}",  # noqa: RUF001
}


def _ascii_escape(char: str) -> str:
    if char in _LETTERS:
        return _LETTERS[char]
    decomposed = unicodedata.normalize("NFD", char)
    if len(decomposed) == 2 and decomposed[0].isascii() and decomposed[0].isalpha():
        base, mark = decomposed[0], decomposed[1]
        if mark in _ACCENT:
            return "{\\" + _ACCENT[mark] + base + "}"
        if mark in _ACCENT_ALPHA:
            return "{\\" + _ACCENT_ALPHA[mark] + " " + base + "}"
    return f'{{\\char"{ord(char):04X}}}'


def escape(text: str, *, ascii_only: bool = False) -> str:
    """Escape LaTeX specials; with `ascii_only`, also every non-ASCII character."""
    out: list[str] = []
    for char in text:
        if char in _SPECIAL:
            out.append(_SPECIAL[char])
        elif ascii_only and not char.isascii():
            out.append(_ascii_escape(char))
        else:
            out.append(char)
    return "".join(out)


def _author(author: Author, ascii_only: bool) -> str:
    name = escape(author.name.strip(), ascii_only=ascii_only)
    return name if "," in name else "{" + name + "}"


def bibtex_entry(work: Work, key: str, *, ascii_only: bool = False) -> str:
    """One BibTeX entry for `work` under `key`."""
    kind = _TYPES.get(work.type, "misc")
    fields: list[tuple[str, str]] = []

    def add(name: str, value: str | None, *, raw: bool = False) -> None:
        if value:
            text = value if raw else escape(value, ascii_only=ascii_only)
            fields.append((name, text))

    add("title", "{" + escape(work.title, ascii_only=ascii_only) + "}", raw=True)
    if work.authors:
        add("author", " and ".join(_author(a, ascii_only) for a in work.authors), raw=True)
    add("year", None if work.dates.year is None else str(work.dates.year))
    venue = work.venue
    ids = work.identifiers
    if venue is not None:
        if work.type is not WorkType.DATASET:
            add(_VENUE_FIELD[kind], venue.name)
        add("volume", venue.volume)
        add("number", venue.issue)
        add("pages", venue.pages)
        add("publisher", venue.publisher)
    add("doi", ids.doi)
    add("url", ids.url)
    add("isbn", ids.isbn)
    if work.type is WorkType.PREPRINT and ids.arxiv:
        add("eprint", ids.arxiv)
        add("archivePrefix", "arXiv")
    if work.type is WorkType.DATASET:
        add("howpublished", "Dataset")
    lines = [f"@{kind}{{{key},"]
    lines.extend(f"  {name} = {{{value}}}," for name, value in fields)
    lines.append("}")
    return "\n".join(lines)


def bibtex(entries: Iterable[tuple[str, Work]], *, ascii_only: bool = False) -> Iterator[str]:
    """Yield entries in the order given, each followed by a blank line separator."""
    first = True
    for key, work in entries:
        entry = bibtex_entry(work, key, ascii_only=ascii_only)
        yield entry + "\n" if first else "\n" + entry + "\n"
        first = False
