"""Source-level guard: nothing under `factory/` builds an outbound request from the contact address.

The researcher ruled (2026-11-17) that `Settings.mailto` is never sent to an outside host. The
behavioural test (`test_no_contact_address.py`) drives the clients; this one reads the source, so a
new route or client that reaches for the address fails here before it is ever run.

Flagged, by syntax tree (comments and docstrings are ignored):

- an attribute named `mailto` (`settings.mailto`, `s.mailto`);
- a keyword argument `mailto=`;
- a call to `user_agent(...)` (the retired builder of a contact User-Agent);
- a string literal that carries a query parameter `mailto=`, `email=` or `tool=`;
- a dict key or subscript `"mailto"`, `"email"` or `"tool"` (request parameters).

Only the files in `ALLOWED` may do so, and only to redact the address from what is archived or
noted, or to hand it to a source that redacts. None of them puts it in a URL or header.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import factory

SRC = Path(factory.__file__).parent
PARAM = re.compile(r"(^|[?&\s])(mailto|email|tool)=")
KEYS = {"mailto", "email", "tool"}

ALLOWED = {
    # arxiv.py, crossref.py, openalex.py, pubmed.py and fulltext/oa_pdf.py hold the address as a
    # private `_mailto` (set from a constructor parameter) only to redact it from archived text,
    # notes and URLs. They match none of the rules above, so they need no entry; a new use of
    # `.mailto` or a `mailto=` keyword in them would fail here.
    # The redactor itself (regexes for `mailto=`) and the generic clients.
    "sources/http.py",
    # Constructors that pass the address to a source for redaction only.
    "sources/registry.py",
    "sources/fulltext/registry.py",
    "cli/feed.py",
    "cli/site.py",
    # Services that redact the address from error notes before they are recorded.
    "services/fulltext.py",
    "services/probe.py",
    "services/search.py",
    # A local page payload: its "tool" dict key names an MCP tool in the capabilities matrix; it is
    # not a request parameter and nothing here is sent to a host (hub_platform.py, 2a0ab117).
    "services/hub_platform.py",
    # The settings field itself.
    "config.py",
}


def _docstrings(tree: ast.AST) -> set[int]:
    """Ids of string nodes that are bare expression statements (docstrings, notes)."""
    return {
        id(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
    }


def _findings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstrings(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Attribute) and node.attr == "mailto":
            found.append(f"{line}: attribute .mailto")
        elif isinstance(node, ast.keyword) and node.arg == "mailto":
            found.append(f"{node.value.lineno}: keyword mailto=")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name | ast.Attribute)
            and getattr(node.func, "id", getattr(node.func, "attr", "")) == "user_agent"
        ):
            found.append(f"{line}: user_agent(...)")
        elif (
            isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
        ):
            if PARAM.search(node.value):
                found.append(f"{line}: string with a mailto=/email=/tool= parameter")
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value in KEYS:
                    found.append(f"{key.lineno}: dict key {key.value!r}")
        elif isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and index.value in KEYS:
                found.append(f"{index.lineno}: subscript {index.value!r}")
    return found


def test_only_redaction_sites_touch_the_contact_address() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in ALLOWED:
            continue
        offenders += [f"{rel}:{f}" for f in _findings(path)]
    assert not offenders, (
        "The contact address (Settings.mailto) must never be sent to an outside host "
        "(ruling 2026-11-17). These sites touch it or build mailto/email/tool request "
        "parameters; remove them, or, if one only redacts the address, add its file to ALLOWED "
        "in this test with a comment:\n" + "\n".join(offenders)
    )


def test_allowlist_is_current() -> None:
    """An allowlisted file that no longer touches the address must leave the list."""
    stale = [rel for rel in sorted(ALLOWED) if not _findings(SRC / rel)]
    assert not stale, f"no longer touch the address, remove from ALLOWED: {stale}"
