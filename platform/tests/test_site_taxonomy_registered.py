"""The registered taxonomies on the taxonomy product (decision 127 item 5): empty case, listing
with pages, versions with a diff, and the per-category counts of a derived miner."""

from __future__ import annotations

from pathlib import Path

from factory.events.envelope import Actor
from factory.mining.taxonomy import Category, Dimension, Example, TaxonomySpec, taxonomy_to_json
from factory.services import site
from factory.services.context import Project
from factory.services.site_taxonomy_registered import (
    DerivedMiner,
    category_counts,
    render_index,
    render_version,
    write_registered,
)
from factory.services.taxonomies import register_taxonomy


def _spec(version: int, ids: tuple[str, ...], name: str = "t-site") -> TaxonomySpec:
    cats = tuple(
        Category(
            i,
            i.upper(),
            f"Definition of {i}.",
            examples=(Example("a <b> quote", "rf:w1", "s1.p1"),) if i == "rl" else (),
        )
        for i in ids
    )
    return TaxonomySpec(
        name=name,
        version=version,
        dimensions=(Dimension("tech", "Technique", "Which technique?", "multi", cats),),
    )


def test_no_registered_taxonomy_renders_a_note(project: Project, tmp_path: Path) -> None:
    assert "No taxonomy is registered yet" in render_index(project)
    write_registered(project, tmp_path, site.page)
    assert list(tmp_path.iterdir()) == []


def test_a_registered_taxonomy_is_listed_with_a_page_and_a_diff(
    project: Project, human: Actor, tmp_path: Path
) -> None:
    register_taxonomy(project, human, taxonomy_to_json(_spec(1, ("rl", "llm"))))
    register_taxonomy(project, human, taxonomy_to_json(_spec(2, ("rl", "llm", "gan"))))
    index = render_index(project)
    assert "t-site" in index and "v2" in index and "v1" in index
    assert index.index("v2") < index.index("v1")
    assert "1 dimensions, 2 categories" in index and "1 dimensions, 3 categories" in index
    write_registered(project, tmp_path, site.page)
    latest = (tmp_path / "t-site.html").read_text(encoding="utf-8")
    assert "no derived miner yet" in latest.lower()
    assert "Changes from version 1 to 2" in latest and "tech/gan" in latest
    assert "a &lt;b&gt; quote" in latest and "../explorer/index.html#open=w1" in latest
    first = (tmp_path / "t-site-v1.html").read_text(encoding="utf-8")
    assert "Changes from version" not in first


def test_category_counts_count_distinct_works() -> None:
    pairs = [("w1", "tech/rl"), ("w1", "tech/rl"), ("w2", "tech/rl"), ("w2", "tech/llm")]
    assert category_counts(pairs) == {"tech/rl": 2, "tech/llm": 1}


def test_a_derived_miner_shows_counts_and_links_its_page() -> None:
    body = render_version(
        _spec(1, ("rl", "llm")),
        versions=[1],
        latest=1,
        miner=DerivedMiner("m-site", 1, {"tech/rl": 2}, page=True),
        previous=None,
        open_proposals=0,
    )
    assert "../miners/m-site.html" in body
    assert "works with a current row" in body and "<td>2</td>" in body and "<td>0</td>" in body


def test_many_taxonomies_render(project: Project, human: Actor, tmp_path: Path) -> None:
    for n in range(8):
        ids = tuple(f"c{i}" for i in range(45))
        register_taxonomy(project, human, taxonomy_to_json(_spec(1, ids, name=f"t-many{n}")))
    index = render_index(project)
    assert all(f"t-many{n}" in index for n in range(8))
    write_registered(project, tmp_path, site.page)
    assert len(list(tmp_path.glob("t-many*.html"))) == 8
