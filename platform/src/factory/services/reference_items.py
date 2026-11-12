"""Cited items: reference entries of all live extractions grouped into items (rules version 4).

Invariants: read-only (writes no event, only syncs the index); deterministic for a given index;
ordering (by citing count, then key) never judges relevance. A cited item is computed on read,
never stored.

Rules version 4:
1. Identifier wins. An entry with a DOI or arXiv id and a title known for it takes that title
   instead of its parsed one, flagged or not, in this order: the work its live link resolves to; a
   work record with the same identifier; the most common usable (unflagged) parsed title among the
   entries with the same identifier (ties to the shortest, then lexicographic). A borrowed title
   must itself pass `flags_for`. No source is called. An entry without an identifier keeps its
   parsed title; if that is flagged it is unassessable with its reasons.
2. Merge. Entries are united (union-find) when they share a DOI (case-folded) or an arXiv id
   (version suffix stripped); when their titles are equal after `strip_title_notes`; or when their
   stripped titles of at least five words have `fuzz.ratio` >= 95 and years within one of each
   other (see `_fuzzy_pairs`). Each union is an item.
3. The item title is the identifier-known title if any member has one, else the most common member
   title, preferring members whose title carries no strippable note. The key is
   `item_key(normalise_title(title))`, deterministic for a given index.
4. `CitedItem.aliases` holds the keys rules version 3 gave to the members and the item's own key.

`ItemsReport.borrowed` counts entries by where their identifier title came from; `replaced` counts
entries with a usable parsed title that the identifier title changed (after normalisation);
`merged` is the number of distinct normalised titles before step 2 minus the number of items.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Final

from rapidfuzz import fuzz, process
from sqlalchemy import text

from factory.services.context import Project

ITEM_RULES_VERSION: Final = "4"
"""2: titles borrowed for identifier-only entries. 3: display titles HTML-unescaped before flags
and normalisation; flag `et-al`; `author-list` also matches four or more single-surname parts and
"Name Name and Name Name". 4: identifier titles replace parsed ones for every entry with an
identifier; merged items; `aliases`."""

_MIN_WORDS: Final = 3
_MIN_CHARS: Final = 12
_NOISE_START: Final = "[](){}.,;:-"
_NAME_SPLIT: Final = re.compile(r"\s*(?:,|;|&|\band\b)\s*", re.IGNORECASE)
_NAME_TOKEN: Final = re.compile(r"^(?:[A-Z]\.?|[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*\.?)$")
_INITIAL: Final = re.compile(r"^[A-Z]\.?$")
_ET_AL: Final = re.compile(r"\bet\s+al\b", re.IGNORECASE)
_SURNAME: Final = re.compile(r"^[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*$")
_TITLE_WORD_TEXT: Final = (
    "a an the and of for in on to with by from at as into via using towards toward "
    "learning machine deep data mining science sciences research scientific systems system "
    "model models modeling modelling network networks neural language large artificial "
    "intelligence agent agents automated automatic discovery knowledge reasoning "
    "computing computational analysis design optimization optimisation generation "
    "algorithms algorithm methods method theory theories experiments experimental "
    "natural processing vision graph graphs quantum chemistry physics biology materials "
    "software engineering information scientists scientist laboratory laboratories"
)
_TITLE_WORDS: Final = frozenset(_TITLE_WORD_TEXT.split())
"""Common title words: a two-name pair containing one is not read as two authors."""


def clean_title(title: str) -> str:
    """The display title: HTML entities unescaped (`&amp;` to `&`)."""
    return html.unescape(title)


def normalise_title(title: str) -> str:
    """NFKC, case-folded, punctuation removed (letters and digits kept), spaces collapsed."""
    folded = unicodedata.normalize("NFKC", title).casefold()
    kept = "".join(c if (c.isalnum() or c.isspace()) else " " for c in folded)
    return " ".join(kept.split())


def item_key(normalised: str) -> str:
    """`ci-` plus the first 16 hex characters of the SHA-256 of the normalised title."""
    return "ci-" + hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _looks_like_author_list(raw: str) -> bool:
    """Conservative: the raw title splits on `,` `;` `&` or `and` into parts, every part is a
    personal name, and one of these holds:
    - two or more names, each of 2 to 4 capitalised tokens (initials allowed), three or more of
      them or containing an initial ("M. Smith, J. Doe"; "Dylan M Anstine and Olexandr Isayev");
    - four or more parts that are each one capitalised word ("Yang, Hu, Zhou, Liu, Shi, Li");
    - exactly two names of two plain tokens joined by `and` or `&`, none a common title word
      ("Yatao Li and Jianfeng Zhan").
    Known limits: two plain full names ("Machine Learning, Deep Learning") are not flagged; a
    title that is a bare list of four or more single capitalised words ("Python, Java, Rust, Go")
    is; a pair of names made only of words outside the stop list ("Graph Theory and Quantum
    Gravity" is protected, "Bayesian Inference and Gaussian Processes" is not)."""
    parts = [p for p in _NAME_SPLIT.split(raw.strip()) if p]
    if len(parts) < 2:
        return False
    if len(parts) >= 4 and all(_SURNAME.match(p) for p in parts):
        return True
    if len(parts) == 2 and re.search(r"\s(?:and|&)\s", raw, re.IGNORECASE):
        pair = [p.split() for p in parts]
        if all(
            len(t) == 2 and all(_SURNAME.match(w) and w.casefold() not in _TITLE_WORDS for w in t)
            for t in pair
        ):
            return True
    has_initial = False
    for part in parts:
        tokens = part.split()
        if not 2 <= len(tokens) <= 4:
            return False
        if not all(_NAME_TOKEN.match(t) for t in tokens):
            return False
        has_initial = has_initial or any(_INITIAL.match(t) for t in tokens)
    return has_initial or len(parts) >= 3


def flags_for(title: str | None) -> tuple[str, ...]:
    """Computed clean-up flags, sorted: author-list, et-al, leading-noise, no-title, too-short."""
    if title is None or not title.strip():
        return ("no-title",)
    flags: set[str] = set()
    norm = normalise_title(title)
    if len(norm.split()) < _MIN_WORDS or len(norm) < _MIN_CHARS:
        flags.add("too-short")
    raw = title.strip()
    if raw[0] in _NOISE_START:
        flags.add("leading-noise")
    if _looks_like_author_list(raw):
        flags.add("author-list")
    if _ET_AL.search(raw):
        flags.add("et-al")
    return tuple(sorted(flags))


@dataclass(frozen=True)
class ItemEntry:
    extraction_id: str
    ordinal: int
    work_id: str


@dataclass(frozen=True)
class CitedItem:
    key: str
    title: str
    normalised: str
    citing_works: tuple[str, ...]
    entries: tuple[ItemEntry, ...]
    year: int | None
    dois: tuple[str, ...]
    arxivs: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    """Item keys the members had under rules version 3 (one per distinct member title, parsed or
    borrowed), so assignments and labels keyed by an earlier rules version can be found again."""

    @property
    def citing_count(self) -> int:
        return len(self.citing_works)


@dataclass
class Unassessable:
    extraction_id: str
    ordinal: int
    work_id: str
    reasons: tuple[str, ...]
    doi: str | None
    arxiv: str | None


@dataclass
class ItemsReport:
    items: list[CitedItem] = field(default_factory=list)
    unassessable: list[Unassessable] = field(default_factory=list)
    entries_total: int = 0
    rules_version: str = ITEM_RULES_VERSION
    borrowed: dict[str, int] = field(default_factory=dict)
    """Entries whose title came from an identifier, by source: `resolved-link`, `work-record`,
    `entry`."""
    replaced: int = 0
    """Entries with a usable parsed title that the identifier title changed (normalised)."""
    merged: int = 0
    """Distinct normalised titles before merging minus the number of items."""


_MONTHS: Final = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_VENUES: Final = (
    "neurips|nips|icml|iclr|acl|emnlp|naacl|aaai|ijcai|cvpr|iccv|eccv|kdd|www|sigir|colm|"
    "tmlr|jmlr|nature|science"
)
_YEAR: Final = r"(?:(?:" + _MONTHS + r")\.?\s+)?(?:19|20)\d\d"
_NOTE_PATTERNS: Final = (
    # In: ... / Proceedings of ... after the title (a separator is required, so a title that
    # starts with these words is untouched).
    re.compile(r"[\s,.;:]+(?:in:|in\s+proceedings\b|proceedings\s+of\b).*$", re.IGNORECASE),
    # arXiv preprint arXiv:2401.00001 / arXiv:2401.00001v2 / arXiv preprint
    re.compile(
        r"[\s,.;:(\[]+arxiv(?:\s+preprint)?[\s:]*(?:arxiv[\s:]*)?(?:\d{4}\.\d{4,5}(?:v\d+)?)?"
        r"[\s)\]]*$",
        re.IGNORECASE,
    ),
    # bracketed or separated preprint / technical report notes
    re.compile(
        r"(?:[\s]*[\[(]\s*(?:preprint|technical report|tech\.? report)\s*[\])]"
        r"|[,.;:]\s*(?:preprint|technical report|tech\.? report))[\s.]*$",
        re.IGNORECASE,
    ),
    # venue with optional year, only after a separator or in brackets
    re.compile(
        r"(?:[,.;:]\s*|\s*[\[(]\s*)(?:" + _VENUES + r")\s*['\u2019]?\d{0,4}\s*[\])]?[\s.]*$",
        re.IGNORECASE,
    ),
    # year note: ", 2024", ", September 2024", "(2024)", "[2024]", ". 2024"
    re.compile(
        r"(?:[,.;:]\s*" + _YEAR + r"|\s*[\[(]\s*" + _YEAR + r"\s*[\])])[\s.]*$",
        re.IGNORECASE,
    ),
    # a parenthesised year inside the title
    re.compile(r"\s*\(\s*(?:19|20)\d\d\s*\)", re.IGNORECASE),
    # trailing punctuation
    re.compile(r"[\s,.;:/-]+$"),
)
"""Patterns removed by `strip_title_notes`, each replaced by the empty string."""


def strip_title_notes(title: str) -> str:
    """The title without trailing or embedded notes that are not part of it: year notes
    (", 2024", "(2024)", ", September 2024"), "arXiv preprint arXiv:...", "[Preprint]",
    ", preprint", "technical report" in brackets or after a separator, venue notes after a
    separator ("In: ...", "Proceedings of ...", ", NeurIPS 2024") and trailing punctuation.
    Patterns (`_NOTE_PATTERNS`) are applied until nothing changes. Words inside the title proper
    are never removed: every note needs a separator or brackets before it. A result of fewer than
    three words is discarded and the clean title returned."""
    out = title.strip()
    for _ in range(6):
        before = out
        for pattern in _NOTE_PATTERNS:
            out = pattern.sub("", out)
        if out == before:
            break
    return out if len(normalise_title(out).split()) >= _MIN_WORDS else title.strip()


_FUZZY_MIN_WORDS: Final = 5
_FUZZY_CUTOFF: Final = 95.0
_ARTICLES: Final = frozenset({"the", "a", "an"})


def _digit_tokens(norm: str) -> list[str]:
    """Sorted words containing a digit: titles that differ in a number ("Claude Opus 4.6" and
    "4.8", "GPT-4" and "GPT-5") are different works whatever the edit similarity."""
    return sorted(w for w in norm.split() if any(c.isdigit() for c in w))


def _fuzzy_pairs(stripped: dict[str, set[int]]) -> list[tuple[str, str]]:
    """Pairs of normalised stripped titles to merge. `fuzz.ratio` (order-sensitive edit
    similarity) is used rather than `token_sort_ratio`: re-ordered words usually name another
    work, and the cutoff of 95 on at least five words allows about one character in twenty
    to differ ("The AI Scientist-v2: ..." stays apart from "The AI Scientist: ..."). Both titles
    need a known year, the two within one, and the same numeric words. Candidates are blocked by
    the first non-article word and by the last word, so a title meets few others."""
    cands = sorted(t for t, ys in stripped.items() if ys and len(t.split()) >= _FUZZY_MIN_WORDS)
    blocks: dict[tuple[str, str], list[str]] = defaultdict(list)
    for t in cands:
        words = t.split()
        first = next((w for w in words if w not in _ARTICLES), words[0])
        blocks[("f", first)].append(t)
        blocks[("l", words[-1])].append(t)
    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []
    for members in blocks.values():
        if len(members) < 2:
            continue
        for a in members:
            for b, _score, _idx in process.extract(
                a, members, scorer=fuzz.ratio, score_cutoff=_FUZZY_CUTOFF, limit=None
            ):
                if b <= a or (a, b) in seen:
                    continue
                seen.add((a, b))
                if _digit_tokens(a) == _digit_tokens(b) and any(
                    abs(x - y) <= 1 for x in stripped[a] for y in stripped[b]
                ):
                    pairs.append((a, b))
    return pairs


def _most_common(titles: list[str]) -> str:
    counts = Counter(titles)
    return min(counts, key=lambda t: (-counts[t], len(t), t))


def _arxiv_base(arxiv: str) -> str:
    """The arXiv id without a trailing version suffix (`v2`)."""
    return re.sub(r"v\d+$", "", str(arxiv).strip())


def _usable(title: object) -> str | None:
    if not isinstance(title, str):
        return None
    cleaned = clean_title(title)
    return cleaned.strip() if not flags_for(cleaned) else None


class _Union:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


@dataclass
class _Member:
    entry: ItemEntry
    title: str
    year: int | None
    doi: str | None
    arxiv: str | None
    known: bool  # title came from an identifier
    alias: str | None  # the key rules version 3 gave this entry


def cited_items(project: Project) -> ItemsReport:
    """Group live entries into cited items; flagged entries are unassessable."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT e.extraction_id, e.ordinal, x.work_id, e.title, e.year, e.doi, e.arxiv "
                "FROM reference_entries e JOIN reference_extractions x "
                "ON x.extraction_id = e.extraction_id WHERE x.live = 1 "
                "ORDER BY e.extraction_id, e.ordinal"
            )
        ).all()
        linked = {
            (str(e), int(o)): str(w)
            for e, o, w in conn.execute(
                text(
                    "SELECT l.extraction_id, l.ordinal, l.work_id FROM reference_links l "
                    "JOIN reference_extractions x ON x.extraction_id = l.extraction_id "
                    "WHERE x.live = 1 AND l.state = 'resolved' AND l.work_id IS NOT NULL"
                )
            ).all()
        }
        work_rows = conn.execute(
            text(
                "SELECT work_id, json_extract(data, '$.title'), "
                "lower(json_extract(data, '$.identifiers.doi')), "
                "json_extract(data, '$.identifiers.arxiv') FROM works"
            )
        ).all()
    work_title: dict[str, str] = {}
    by_id: dict[str, str] = {}
    for wid, wtitle, wdoi, warxiv in sorted(work_rows, key=lambda r: str(r[0])):
        usable = _usable(wtitle)
        if usable is None:
            continue
        work_title[str(wid)] = usable
        for ident in (
            f"doi:{wdoi}" if wdoi else None,
            f"arxiv:{_arxiv_base(warxiv)}" if warxiv else None,
        ):
            if ident:
                by_id.setdefault(ident, usable)
    seen: dict[str, list[str]] = defaultdict(list)
    for _, _, _, title, _, doi, arxiv in rows:
        usable = _usable(title)
        if usable is None:
            continue
        if doi:
            seen[f"doi:{str(doi).lower()}"].append(usable)
        if arxiv:
            seen[f"arxiv:{_arxiv_base(arxiv)}"].append(usable)
    by_entry = {ident: _most_common(titles) for ident, titles in seen.items()}

    def borrow(
        eid: str, ordinal: int, doi: str | None, arxiv: str | None
    ) -> tuple[str, str] | None:
        wid = linked.get((eid, ordinal))
        if wid is not None and wid in work_title:
            return work_title[wid], "resolved-link"
        idents = [
            i
            for i in (
                f"doi:{doi.lower()}" if doi else None,
                f"arxiv:{_arxiv_base(arxiv)}" if arxiv else None,
            )
            if i
        ]
        for ident in idents:
            if ident in by_id:
                return by_id[ident], "work-record"
        for ident in idents:
            if ident in by_entry:
                return by_entry[ident], "entry"
        return None

    report = ItemsReport(entries_total=len(rows))
    members: list[_Member] = []
    for eid, ordinal, wid, title, year, doi, arxiv in rows:
        parsed = clean_title(title) if isinstance(title, str) else title
        flags = flags_for(parsed)
        got = borrow(eid, ordinal, doi, arxiv) if (doi or arxiv) else None
        if got is None:
            if flags:
                report.unassessable.append(Unassessable(eid, ordinal, wid, flags, doi, arxiv))
                continue
            assert isinstance(parsed, str)
            members.append(
                _Member(
                    ItemEntry(eid, ordinal, wid),
                    parsed.strip(),
                    year,
                    doi,
                    arxiv,
                    False,
                    item_key(normalise_title(parsed)),
                )
            )
            continue
        new_title, source = got
        report.borrowed[source] = report.borrowed.get(source, 0) + 1
        if flags:
            v3_key = item_key(normalise_title(new_title))
        else:
            assert isinstance(parsed, str)
            v3_key = item_key(normalise_title(parsed))
            if normalise_title(parsed) != normalise_title(new_title):
                report.replaced += 1
        members.append(
            _Member(ItemEntry(eid, ordinal, wid), new_title.strip(), year, doi, arxiv, True, v3_key)
        )

    uf = _Union(len(members))
    first_by_ident: dict[str, int] = {}
    stripped_of: list[str] = []
    first_by_stripped: dict[str, int] = {}
    stripped_years: dict[str, set[int]] = defaultdict(set)
    for i, m in enumerate(members):
        for ident in (
            f"doi:{m.doi.lower()}" if m.doi else None,
            f"arxiv:{_arxiv_base(m.arxiv)}" if m.arxiv else None,
        ):
            if ident:
                uf.union(i, first_by_ident.setdefault(ident, i))
        st = normalise_title(strip_title_notes(m.title))
        stripped_of.append(st)
        uf.union(i, first_by_stripped.setdefault(st, i))
        if m.year is not None:
            stripped_years[st].add(int(m.year))
    for a, b in _fuzzy_pairs(stripped_years):
        uf.union(first_by_stripped[a], first_by_stripped[b])

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(members)):
        clusters[uf.find(i)].append(i)
    pre_merge = len({normalise_title(m.title) for m in members})
    by_key: dict[str, list[_Member]] = defaultdict(list)
    chosen: dict[str, str] = {}
    for idxs in clusters.values():
        group = [members[i] for i in idxs]
        known = [m.title for m in group if m.known]
        if known:
            title = _most_common(known)
        else:
            plain = [
                m.title
                for m in group
                if normalise_title(strip_title_notes(m.title)) == normalise_title(m.title)
            ]
            title = _most_common(plain or [m.title for m in group])
        key = item_key(normalise_title(title))
        by_key[key].extend(group)
        chosen.setdefault(key, title)
    for key, group in by_key.items():
        title = chosen[key]
        years = [m.year for m in group if m.year is not None]
        aliases = {key} | {m.alias for m in group if m.alias}
        report.items.append(
            CitedItem(
                key=key,
                title=title,
                normalised=normalise_title(title),
                citing_works=tuple(sorted({m.entry.work_id for m in group})),
                entries=tuple(
                    sorted((m.entry for m in group), key=lambda e: (e.extraction_id, e.ordinal))
                ),
                year=min(years) if years else None,
                dois=tuple(sorted({m.doi for m in group if m.doi})),
                arxivs=tuple(sorted({m.arxiv for m in group if m.arxiv})),
                aliases=tuple(sorted(aliases)),
            )
        )
    report.merged = pre_merge - len(report.items)
    report.items.sort(key=lambda i: (-i.citing_count, i.key))
    return report
