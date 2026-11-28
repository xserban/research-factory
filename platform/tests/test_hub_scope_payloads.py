"""Phase-1 hub scope (P1-02): every work-bearing payload row carries its work id and the work's
`published` string (HS-10, the value of `ctx.publication`; "" when undated), and a payload grows
only by those date strings."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from factory.services import hub_build as hb
from factory.services import hub_findings as hf
from factory.services import hub_landscape as hl
from factory.services import hub_lenses
from factory.services import hub_mining as hm
from factory.services.context import Project
from tests import test_hub_findings as tf
from tests import test_hub_landscape as tl
from tests.test_hub_build import _payload, mined_world, world  # noqa: F401  (fixtures)
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)

DATE_MAX = 32  # an ISO date or datetime; nothing bigger may ride along


def _at(payload: Any, path: str) -> Any:
    """`a.b[].c` style: dicts by key; `[]` flattens a list (or the values of a dict)."""
    nodes = [payload]
    for part in path.split("."):
        nxt: list[Any] = []
        for n in nodes:
            if part.endswith("[]"):
                got = n[part[:-2]]
                nxt.extend(got if isinstance(got, list) else got.values())
            else:
                nxt.append(n[part])
        nodes = nxt
    return nodes


def _rows(payload: Any, path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n in _at(payload, path):
        out.extend(n)
    return out


def _published_keys(o: Any) -> Iterator[dict[str, Any]]:
    """Every dict holding a `published` key."""
    if isinstance(o, dict):
        if "published" in o:
            yield o
        for v in o.values():
            yield from _published_keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _published_keys(v)


def assert_rows(
    rows: Sequence[Mapping[str, Any]], id_key: str, expected: Mapping[str, str]
) -> None:
    assert rows, "the fixture must exercise this panel"
    for r in rows:
        assert isinstance(r.get("published"), str), r
        assert r["published"] == expected.get(r[id_key], ""), r


def assert_grows_only_by_dates(payload: Any) -> None:
    """A `published` key sits only on a work-bearing row and holds a date-sized string."""
    for d in _published_keys(payload):
        assert "id" in d or "work" in d, d
        assert isinstance(d["published"], str) and len(d["published"]) <= DATE_MAX


def _expected(w: Project) -> dict[str, str]:
    ctx = hb.HubContext(w)
    exp = {k: v[1] for k, v in ctx.publication.items()}
    assert any(exp.values()), "the fixture needs a dated work"
    return exp


def test_shell_works_carry_published(world: Project, tmp_path: Path) -> None:  # noqa: F811
    p = _payload(world, tmp_path, "shell")
    assert_rows(_rows(p, "works"), "id", _expected(world))
    assert_grows_only_by_dates(p)


def test_explore_works_carry_published(world: Project, tmp_path: Path) -> None:  # noqa: F811
    p = _payload(world, tmp_path, "explore")
    assert_rows(_rows(p, "works"), "id", _expected(world))
    assert_grows_only_by_dates(p)


def test_overview_most_cited_carry_published(world: Project, tmp_path: Path) -> None:  # noqa: F811
    p = _payload(world, tmp_path, "overview")
    assert_rows(_rows(p, "most_cited"), "id", _expected(world))
    assert_grows_only_by_dates(p)


def test_corpus_works_carry_published(world: Project, tmp_path: Path) -> None:  # noqa: F811
    p = _payload(world, tmp_path, "corpus")
    assert_rows(_rows(p, "works"), "id", _expected(world))
    assert_grows_only_by_dates(p)


def test_corpus_citation_rows_carry_published() -> None:
    class W:
        def __init__(self, i: str, rate: float | None) -> None:
            self.work_id, self.per_year, self.year = i, rate, 2024
            self.cited_by, self.self_cited_by, self.external = 3, 0, 3

    out = hub_lenses.citation_rate(
        [W("rf:a", 2.0), W("rf:b", 1.0), W("rf:c", 0.5)],
        ["rf:a", "rf:b", "rf:c"],
        extractions=1,
        entries=1,
        resolved_links=1,
        works_total=3,
        as_of_year=2026,
        published={"rf:a": "2024-05-01", "rf:b": "2023"},
    )
    assert_rows(out["rows"], "id", {"rf:a": "2024-05-01", "rf:b": "2023"})
    assert [r["published"] for r in out["rows"]] == ["2024-05-01", "2023", ""]
    assert_grows_only_by_dates(out)


def test_lenses_influence_items_carry_published(world: Project, tmp_path: Path) -> None:  # noqa: F811
    p = _payload(world, tmp_path, "lenses")
    assert_rows(_rows(p, "influence.items"), "id", _expected(world))
    assert_grows_only_by_dates(p)


def test_mining_rows_carry_published(mined_world: Project, tmp_path: Path) -> None:  # noqa: F811
    p = _payload(mined_world, tmp_path, "mining")
    exp = _expected(mined_world)
    assert_rows(_rows(p, "miners.miners[].examples"), "work", exp)
    holes = _rows(p, "holes.works")
    if holes:
        assert_rows(holes, "id", exp)
    assert_grows_only_by_dates(p)


def test_every_grid_row_carries_published(mined_world: Project, tmp_path: Path) -> None:  # noqa: F811
    out = tmp_path / "ui"
    from factory.services import hub_build

    report = hub_build.build_static(mined_world, out, only={"mining", "grid"})
    assert report.errors == {}
    exp = _expected(mined_world)
    names = [n for n in report.payloads if n.startswith("grid-")]
    assert names
    for n in names:
        g = json.loads((out / "data" / f"{n}.json").read_text(encoding="utf-8"))
        assert_rows(g["rows"], "id", exp)
        assert_grows_only_by_dates(g)


def test_the_paged_data_table_rows_carry_published() -> None:
    d = dataclasses.replace(tf.fixture_data(), published={"w01": "2024-02-01"})
    rows = hm.data_grid(d, None, 1, 50)["rows"]
    assert_rows(rows, "id", {"w01": "2024-02-01"})
    assert next(r for r in rows if r["id"] == "w02")["published"] == ""


def test_findings_evidence_rows_carry_published() -> None:
    pub = {w: f"2024-0{1 + i % 9}-01" for i, w in enumerate(tf.W)}
    d = dataclasses.replace(tf.fixture_data(), published=pub)
    p = hf.findings_from(d, layers=tf.LAYERS, rank=tf.RANK)
    ev = [e for c in p["cards"] for e in c["evidence"]]
    assert_rows(ev, "work", pub)
    assert_grows_only_by_dates(p)


def test_landscape_works_and_uses_carry_published() -> None:
    land, uses = hl.landscape_payloads(tl.data())
    exp = {w: (m.date or "") for w, m in tl.WORKS.items()}
    assert "" in exp.values() and any(exp.values())
    assert_rows(land["works"], "id", exp)
    assert_rows([u for a in uses["approaches"].values() for u in a["uses"]], "work", exp)
    assert_grows_only_by_dates(land)
    assert_grows_only_by_dates(uses)
