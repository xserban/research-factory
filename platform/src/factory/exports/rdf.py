"""A deterministic TriG writer. Pure: terms in, text out.

Invariants (plan X-B, ruling 5):
- Graphs are written in IRI order, and the triples of a graph sorted by subject, predicate and
  object in N-Triples term form, without repeats, so equal input gives equal bytes.
- Prefixes are written in name order and only change how a term is spelled, never its order.
- A literal is escaped per Turtle: every control character is a `\\u` escape, and a lone surrogate,
  which UTF-8 cannot carry, becomes U+FFFD.
- A malformed IRI raises `ValueError` before any text is returned.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import NewType

IRI = NewType("IRI", str)


@dataclass(frozen=True)
class Literal_:
    """An RDF literal; the trailing underscore keeps it apart from `typing.Literal`."""

    value: str
    datatype: IRI | None = None


Triple = tuple[IRI, IRI, IRI | Literal_]

RDF_TYPE = IRI("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
XSD_DATETIME = IRI("http://www.w3.org/2001/XMLSchema#dateTime")

PREFIXES: Mapping[str, str] = MappingProxyType(
    {
        "cito": "http://purl.org/spar/cito/",
        "dcterms": "http://purl.org/dc/terms/",
        "np": "http://www.nanopub.org/nschema#",
        "prov": "http://www.w3.org/ns/prov#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "rfv": "https://w3id.org/research-factory/vocab#",
        "sub": "http://purl.org/nanopub/temp/",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
    }
)
"""The fixed prefixes. `rfv` and `sub` are the defaults a caller replaces per nanopublication."""

_NAMED_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_TO_ESCAPE = re.compile(r'[\\"\x00-\x1f\x7f-\x9f\ud800-\udfff]')
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_NOT_IN_IRI = re.compile(r'[\x00-\x20\x7f<>"{}|\\^`]')
_LOCAL_NAME = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?")


def _escaped(match: re.Match[str]) -> str:
    char = match.group()
    if char in _NAMED_ESCAPES:
        return _NAMED_ESCAPES[char]
    if "\ud800" <= char <= "\udfff":
        return "\\uFFFD"
    return f"\\u{ord(char):04X}"


def escape_literal(s: str) -> str:
    """`s` as the inside of a double-quoted Turtle string."""
    return _TO_ESCAPE.sub(_escaped, s)


def iri(value: str) -> IRI:
    """`value` as an IRI; `ValueError` unless it has a scheme and only characters an IRI allows."""
    if _SCHEME.match(value) is None or _NOT_IN_IRI.search(value) is not None:
        raise ValueError(f"not an IRI: {value!r}")
    return IRI(value)


def _nt(term: IRI | Literal_) -> str:
    """The N-Triples form of a term: the sort key of ruling 5."""
    if isinstance(term, Literal_):
        body = f'"{escape_literal(term.value)}"'
        return body if term.datatype is None else f"{body}^^<{iri(term.datatype)}>"
    return f"<{iri(term)}>"


def _order(triple: Triple) -> tuple[str, str, str]:
    subject, predicate, obj = triple
    return (_nt(subject), _nt(predicate), _nt(obj))


def _short(value: IRI, spaces: Sequence[tuple[str, str]]) -> str:
    """The prefixed name of `value` when its local part is a plain name, else `<value>`."""
    for name, space in spaces:
        if value.startswith(space) and _LOCAL_NAME.fullmatch(value[len(space) :]):
            return f"{name}:{value[len(space) :]}"
    return f"<{iri(value)}>"


def _written(term: IRI | Literal_, spaces: Sequence[tuple[str, str]]) -> str:
    if not isinstance(term, Literal_):
        return _short(term, spaces)
    body = f'"{escape_literal(term.value)}"'
    return body if term.datatype is None else f"{body}^^{_short(term.datatype, spaces)}"


def trig(graphs: Mapping[IRI, Sequence[Triple]], *, prefixes: Mapping[str, str]) -> str:
    """The named `graphs` as TriG text, byte-deterministic (see the module invariants)."""
    spaces = sorted(prefixes.items(), key=lambda item: (-len(item[1]), item[0]))
    lines = [f"@prefix {name}: <{iri(space)}> ." for name, space in sorted(prefixes.items())]
    for graph in sorted(graphs):
        lines += ["", f"{_short(iri(graph), spaces)} {{"]
        for subject, predicate, obj in sorted(set(graphs[graph]), key=_order):
            verb = "a" if predicate == RDF_TYPE else _short(predicate, spaces)
            lines.append(f"  {_short(subject, spaces)} {verb} {_written(obj, spaces)} .")
        lines.append("}")
    return "\n".join(lines) + "\n"


__all__ = [
    "IRI",
    "PREFIXES",
    "RDF_TYPE",
    "XSD_DATETIME",
    "Literal_",
    "Triple",
    "escape_literal",
    "iri",
    "trig",
]
