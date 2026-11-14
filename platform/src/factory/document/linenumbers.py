"""Margin line numbers in converted PDFs (IDEA-48).

A review-format preprint prints a number beside every line; the layout model turns each into a
paragraph of its own. This post-filter drops such paragraphs before anchors are assigned.

Rule: a paragraph is a *line number* when its whole text is 1 to 4 digits and it belongs to a run of
at least `MIN_RUN` adjacent paragraphs, each the previous number plus one. Adjacent means only blank
lines and page breaks (form feeds) lie between them. A number alone, a short run (a table of
ranks, a list of years), a run broken by any other text, and a number that does not continue the
count are all kept. The filter is deterministic and part of the docling converter version.
"""

import re
from dataclasses import dataclass

MIN_RUN = 5
PAGE_BREAK = "\f"
_NUMBER = re.compile(r"\d{1,4}")


@dataclass(frozen=True)
class Filtered:
    """`text` without line-number paragraphs; `dropped` paragraphs in `runs` runs."""

    text: str
    dropped: int
    runs: int


@dataclass
class _Block:
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def number(self) -> int | None:
        core = self.text.replace(PAGE_BREAK, "").strip()
        return int(core) if _NUMBER.fullmatch(core) else None

    @property
    def only_break(self) -> bool:
        return PAGE_BREAK in self.text and not self.text.replace(PAGE_BREAK, "").strip()


def _blocks(text: str) -> list[_Block]:
    blocks: list[_Block] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip(" \t\r") == "":
            if current:
                blocks.append(_Block(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(_Block(current))
    return blocks


def drop_line_numbers(text: str, *, min_run: int = MIN_RUN) -> Filtered:
    """Return `text` without line-number paragraphs; unchanged (same object) when none are found."""
    blocks = _blocks(text)
    drop: set[int] = set()
    runs = 0
    chain: list[int] = []  # indexes of the numbered blocks of the current run
    last: int | None = None

    def close() -> None:
        nonlocal runs, chain
        if len(chain) >= min_run:
            drop.update(chain)
            runs += 1
        chain = []

    for index, block in enumerate(blocks):
        if block.only_break:
            continue  # a page break between numbers does not end a run
        value = block.number
        if value is not None and chain and last is not None and value == last + 1:
            chain.append(index)
            last = value
            continue
        close()
        if value is not None:
            chain, last = [index], value
        else:
            last = None
    close()
    if not drop:
        return Filtered(text, 0, 0)
    kept: list[str] = []
    for index, block in enumerate(blocks):
        if index not in drop:
            kept.append(block.text)
        elif PAGE_BREAK in block.text:
            kept.append(PAGE_BREAK)
    return Filtered("\n\n".join(kept) + "\n", len(drop), runs)
