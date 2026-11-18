"""Static checks over the hub page scripts (plan 2026-11-18-hub-ui, step 10).

Pages are read as text from ``factory/hub_ui/pages``; nothing is executed. Known violations that the
fix round must remove are listed in ``KNOWN`` as strict xfails: the test turns red when a page is
fixed, which is the cue to delete its entry.
"""

from __future__ import annotations

import re
from importlib import resources

import pytest

from factory.services import hub_build, hub_ui

PAGES = sorted(hub_ui.PAGES)
URL_ALLOW = (
    "http://www.w3.org/2000/svg",  # SVG namespace string, never fetched
    "https://arxiv.org/abs/",
    "https://doi.org/",
    "http://arxiv.org/abs/",
    "http://doi.org/",
)
BANNED = (
    "from the brief",
    "not in prototype",
    "prototype data",
    "nothing is sent anywhere",
    "mined works",
    "not classified",
    "human position",
)
# page -> {check: reason}; each is a strict xfail (see module docstring).
KNOWN: dict[tuple[str, str], str] = {
    (
        "explore",
        "colour",
    ): "explore.js:104 box-shadow rgba(0,0,0,.35) literal; use a kit shadow token",
    (
        "lenses",
        "colour",
    ): "lenses.js:449 literal #fff / #101114 for label contrast; derive from tokens",
    (
        "explore",
        "digits",
    ): "explore.js:735 'Compare 0 of 4 pinned' types 0 and 4; take the limit from a constant",
}


def source(page: str) -> str:
    rel = hub_ui.PAGES[page].script.split("/")
    return resources.files("factory.hub_ui").joinpath(*rel).read_text(encoding="utf-8")


def code_only(text: str) -> str:
    """Blank block comments, keeping newlines so offsets still map to line numbers."""
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _marked(page: str, check: str) -> object:
    reason = KNOWN.get((page, check))
    return pytest.param(
        page,
        marks=[pytest.mark.xfail(strict=True, reason=reason)] if reason else [],
        id=page,
    )


def params(check: str) -> list[object]:
    return [_marked(p, check) for p in PAGES]


def test_every_page_has_its_script() -> None:
    for spec in hub_ui.PAGES.values():
        assert spec.script in hub_ui.ASSETS, spec.id
        assert source(spec.id).strip(), spec.id


@pytest.mark.parametrize("page", PAGES)
def test_scripts_reference_only_registered_payloads(page: str) -> None:
    text = code_only(source(page))
    names = {
        n
        for m in re.finditer(r"HUB\.load\(\s*\[([^\]]*)\]", text)
        for n in re.findall(r"'([^']+)'", m.group(1))
    }
    for n in names:
        assert n in hub_build.BUILDERS or n.startswith("grid-") or n == hub_build.GRID_FAMILY, (
            page,
            n,
        )
    # a page may load only payloads its spec declares (grid payloads excepted)
    declared = set(hub_ui.PAGES[page].payloads)
    assert {n for n in names if not n.startswith("grid-")} <= declared, (page, names, declared)


@pytest.mark.parametrize("page", params("url"))
def test_no_external_url_but_paper_links(page: str) -> None:
    text = code_only(source(page))
    bad = []
    for m in re.finditer(r"https?://[^\s'\"`)<>]*", text):
        if not m.group(0).startswith(URL_ALLOW):
            bad.append((line_of(text, m.start()), m.group(0)))
    assert not bad, (page, bad)


_COLOUR = re.compile(
    r"(?<![\w&/#-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])|\brgba?\(\s*\d|\bhsla?\(\s*\d"
)


@pytest.mark.parametrize("page", params("colour"))
def test_no_literal_colour_values(page: str) -> None:
    """Colours come from kit tokens; computed ones (`rgb(` of mixed tokens, `hsl(${hue}`) pass."""
    text = code_only(source(page))
    hits = []
    for m in _COLOUR.finditer(text):
        before = text[max(0, m.start() - 3) : m.start()]
        if m.group(0).startswith("#") and re.search(
            r"""[$(]\(?['"]$|querySelector\(?['"]$""", before
        ):
            continue  # a CSS id selector such as $('#abc')
        hits.append((line_of(text, m.start()), m.group(0)))
    assert not hits, (page, hits)


@pytest.mark.parametrize("page", params("banned"))
def test_banned_phrases_are_absent(page: str) -> None:
    """The kit page quotes the banned phrases in its copy-rules table, so it is exempt."""
    if page == "kit":
        pytest.skip("kit documents the banned phrases")
    low = code_only(source(page)).lower()
    hits = [(line_of(low, low.find(p)), p) for p in BANNED if p in low]
    assert not hits, (page, hits)


def _template_literals(text: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(1)) for m in re.finditer(r"`((?:\\.|[^`\\])*)`", text, flags=re.S)]


def _strip_interpolations(s: str) -> str:
    """Remove `${...}` with brace balancing (nested templates and arrow bodies included)."""
    out: list[str] = []
    i = 0
    while i < len(s):
        if s.startswith("${", i):
            depth, i = 1, i + 2
            while i < len(s) and depth:
                depth += {"{": 1, "}": -1}.get(s[i], 0)
                i += 1
            out.append(" ")
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


_WORDS = re.compile(r"\b(papers?|records?|works)\b", re.I)
_DIGIT = re.compile(r"(?<![\w#.-])(?:[2-9]|\d{2,})(?![\w%.-])(?!\s*·)")


@pytest.mark.parametrize("page", params("digits"))
def test_no_digits_typed_in_sentence_templates(page: str) -> None:
    """Pragmatic: a template that talks about papers or records takes its numbers from `${}`.

    Text inside tags and style rules is skipped by looking only at prose after removing markup."""
    if page == "kit":
        pytest.skip("kit shows example sentences")
    text = code_only(source(page))
    hits = []
    for pos, body in _template_literals(text):
        flat = _strip_interpolations(body)
        if re.search(r"[{};]\s*[.#a-z]", flat) and "<" not in flat:
            continue  # CSS block
        prose = re.sub(r"<[^>]*>", " ", flat)
        if _WORDS.search(prose) and _DIGIT.search(prose):
            hits.append((line_of(text, pos), prose.strip()[:70]))
    assert not hits, (page, hits)
