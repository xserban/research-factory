"""The Landscape payloads of hub v2 (IDEA-78 in the hub-ui architecture): structure, determinism,
agreement with the technique service, the lazy evidence rows, the cache key and the page script.

The payloads are pure functions of `technique_graph.Inputs`, so most tests build the inputs
directly. Nothing here runs the pilot read (26 to 60 s)."""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any

import pytest

from factory.model.screening import Channel
from factory.model.search import QueryKind, QuerySpec
from factory.model.technique_graph import NOTICE, Lens
from factory.services import hub_build as hb
from factory.services import hub_landscape as hl
from factory.services import hub_serve, hub_ui
from factory.services import inbox as inbox_service
from factory.services import technique_graph as tg
from factory.services import technique_rank as rank
from factory.services.context import Project
from factory.services.search import register_query
from factory.services.technique_graph import Inputs, RawRow, StageInfo, WorkMeta

CATALOGUE = {
    "ide-01": ("ideation", "Tournament ranking", "Ranks ideas by pairwise matches."),
    "ide-02": ("ideation", "Debate", "Agents argue."),
    "ide-03": ("ideation", "Novelty search", "Searches prior work."),
    "exp-01": ("experiment", "Tree search", "Searches code variants."),
    "exp-02": ("experiment", "Sandbox", "Runs code in a sandbox."),
}
LAYERS: dict[str, str | None] = {
    "a": "core",
    "b": "core",
    "c": "core",
    "d": "core",
    "e": "core",
    "f": "core",
}
LAYERS |= {"g": "core", "h": "applied", "i": "benchmark", "j": None}
WORKS = {
    f"rf:{k}": WorkMeta(
        f"Paper {k.upper()} </script><b>",
        f"202{n % 5}-0{1 + n % 9}-01" if k != "j" else None,
        2020 + n % 5 if k != "j" else None,
        v,
    )
    for n, (k, v) in enumerate(LAYERS.items())
}


def row(
    work: str,
    approach: str,
    *,
    status: str | None = "core",
    evidence: str | None = "own-ablation",
    n: int = 1,
    quote: str | None = None,
) -> RawRow:
    return RawRow(
        approach=approach,
        stage=CATALOGUE[approach][0],
        work_id=f"rf:{work}",
        extraction_id=f"rex-{work}-{approach}-{n}",
        status=status,
        evidence=evidence,
        described_as=f"{work} variant",
        quote=quote if quote is not None else f"quote {work} {approach}",
        anchor="s1.p1",
        parameters=None,
    )


ROWS = [
    # ide-01 and ide-02 are well used and used together; ide-03 and exp-01 never meet them
    *[row(w, "ide-01") for w in "abcdh"],
    *[row(w, "ide-02", evidence="asserted-only") for w in "abc"],
    *[row(w, "ide-03", evidence="independent-test") for w in "defg"],
    *[row(w, "exp-01", status="reused-cited") for w in "abci"],
    row("d", "exp-02", evidence=None),
    row("e", "exp-02", evidence="reported-failure"),
    row("j", "ide-01"),
    row("a", "ide-01", n=2),
]
CITES = (("rf:b", "rf:a", "lnk-1"),)


def data(rows: list[RawRow] | None = None) -> Inputs:
    return Inputs(
        catalogue=CATALOGUE,
        rows=tuple(ROWS if rows is None else rows),
        stages=(
            StageInfo("experiment", "m-tech-experiment", 1, 2, None, None),
            StageInfo("ideation", "m-tech-ideation", 1, 1, 0.4, 0.6),
        ),
        works=WORKS,
        cites=CITES,
    )


@pytest.fixture(scope="module")
def built() -> tuple[dict[str, Any], dict[str, Any]]:
    return hl.landscape_payloads(data())


def counts(
    payload: dict[str, Any], *, layer: str = "core", ev: str = "", st: str = ""
) -> dict[str, tuple[int, int, dict[str, int]]]:
    """Per approach (distinct works, rows, evidence mix) under a lens, from the payload rows only:
    what the page script does."""
    out: dict[str, tuple[set[int], int, dict[str, int]]] = {}
    for ai, wi, ei, si in payload["rows"]:
        w = payload["works"][wi]
        e, s = payload["evidence_all"][ei], payload["statuses"][si]
        if (layer != "all" and w["layer"] != layer) or (ev and e != ev) or (st and s != st):
            continue
        works, n, mix = out.setdefault(payload["catalogue"][ai]["id"], (set(), 0, {}))
        works.add(wi)
        mix[e] = mix.get(e, 0) + 1
        out[payload["catalogue"][ai]["id"]] = (works, n + 1, mix)
    return {a: (len(w), n, dict(sorted(m.items()))) for a, (w, n, m) in out.items()}


# ---------------------------------------------------------------- structure and labels


def test_the_payload_names_its_sets_and_is_labelled_exploratory(
    built: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    p, uses = built
    assert p["exploratory"] is True and p["notice"] == NOTICE and p["class"] == "interpretation"
    assert uses["exploratory"] is True and uses["notice"] == NOTICE
    assert p["sets"]["what"] == "works with a current pass-A row of a technique miner"
    assert p["sets"]["works"] == len({r.work_id for r in ROWS}) == len(p["works"])
    assert p["sets"]["rows"] == len(ROWS) == len(p["rows"])
    assert sum(p["sets"]["by_layer"].values()) == p["sets"]["works"]
    assert p["lens"]["layer"] == "core" and p["lens"]["rows"] == "pass-A"
    assert p["candidate_sentence"] and p["corpus"] and p["cross_stage_note"]
    for a in p["default"]["approaches"] + p["default"]["co_used"] + p["derives_from"]:
        assert a["class"] == "interpretation" and a["state"] == "exploratory"
    assert [s["stage"] for s in p["stages"]] == ["experiment", "ideation"]
    ide = next(s for s in p["stages"] if s["stage"] == "ideation")
    assert ide["agreement"] == 0.4 and ide["agreement_note"] == "exploratory, not calibrated"
    assert next(s for s in p["stages"] if s["stage"] == "experiment")["agreement"] is None
    for key in ("page", "matrix", "agreement", "candidates", "derives", "earliest"):
        assert "What it shows" in p["methods"][key]


def test_the_unlayered_work_is_named_not_dropped(
    built: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    p, _ = built
    j = next(w for w in p["works"] if w["id"] == "rf:j")
    assert j["layer"] == p["layer_unset"] and j["date"] is None
    assert p["layers"] == ["core", "benchmark", "applied"]


def test_two_builds_are_byte_identical() -> None:
    a, ua = hl.landscape_payloads(data())
    b, ub = hl.landscape_payloads(data())
    assert hb.dumps(a) == hb.dumps(b) and hb.dumps(ua) == hb.dumps(ub)


def test_no_rows_gives_a_valid_empty_payload() -> None:
    p, uses = hl.landscape_payloads(Inputs(catalogue={}, rows=(), stages=(), works={}, cites=()))
    assert p["rows"] == [] and p["catalogue"] == [] and p["stages"] == []
    assert p["candidates"]["gaps"] == [] and p["candidates"]["combinations"]["items"] == []
    assert uses["approaches"] == {} and p["exploratory"] is True
    json.dumps(p, allow_nan=False)


# ---------------------------------------------------------------- the counts equal the service


@pytest.mark.parametrize(
    "lens",
    [
        {},
        {"layer": "all"},
        {"layer": "applied"},
        {"evidence": "asserted-only"},
        {"evidence": "not-stated", "layer": "all"},
        {"status": "reused-cited"},
        {"layer": "all", "evidence": "own-ablation", "status": "core"},
    ],
)
def test_matrix_counts_from_the_rows_equal_the_service_under_every_lens(
    built: tuple[dict[str, Any], dict[str, Any]], lens: dict[str, str]
) -> None:
    p, _ = built
    service = tg.build_landscape(data(), Lens(**lens))
    mine = counts(
        p, layer=lens.get("layer", "core"), ev=lens.get("evidence", ""), st=lens.get("status", "")
    )
    assert {a.id: (a.works, a.rows, a.by_evidence) for a in service.approaches} == mine


def test_the_default_block_is_the_service_output(
    built: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    p, _ = built
    service = tg.build_landscape(data(), Lens(), max_edges=hl.MAX_EDGES)
    assert [a["id"] for a in p["default"]["approaches"]] == [a.id for a in service.approaches]
    assert {a["id"]: a["works"] for a in p["default"]["approaches"]} == {
        a: c[0] for a, c in counts(p).items()
    }
    assert [(e["source"], e["target"], e["weight"]) for e in p["default"]["co_used"]] == [
        (e.source, e.target, e.weight) for e in service.edges if e.kind == "co-used-with"
    ]
    assert p["default"]["max_edges"] == hl.MAX_EDGES == 200
    assert p["stages"] == [s.model_dump(mode="json") for s in service.stages]


def test_co_used_edges_are_capped_and_the_omission_is_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hl, "MAX_EDGES", 1)
    p, _ = hl.landscape_payloads(data())
    assert len(p["default"]["co_used"]) == 1 and p["default"]["co_used_omitted"] >= 1


def test_derives_from_filtered_by_layer_equals_the_service(
    built: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    p, _ = built
    assert p["derives_from"], "fixture has a reused-cited row and a resolved link"
    for layer in ("core", "applied", "all"):
        service = {
            (e.source, e.target, e.approach)
            for e in tg.build_landscape(data(), Lens(layer=layer)).edges
            if e.kind == "derives-from"
        }
        mine = {
            (e["source"], e["target"], e["approach"])
            for e in p["derives_from"]
            if layer == "all" or (e["source_layer"] == layer and e["target_layer"] == layer)
        }
        assert mine == service, layer


def test_earliest_per_layer_equals_the_service(
    built: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    p, _ = built
    for layer in ("all", "core", "applied"):
        land = tg.build_landscape(data(), Lens(layer=layer, min_co_works=10**9))
        mine = p["earliest"][layer]
        assert mine["by_approach"] == {
            e.source: {"work": e.target, "note": e.note}
            for e in land.edges
            if e.kind == "earliest-in-corpus"
        }
        assert mine["undated_works"] == list(land.undated_works)


# ---------------------------------------------------------------- candidates


def test_candidates_are_ranked_lists_with_components_flags_and_quotes(
    built: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    p, _ = built
    c = p["candidates"]
    assert c["lens"]["layer"] == "core" and c["label"] == p["candidate_sentence"]
    service = tg.build_combinations(
        data(),
        Lens(),
        min_works=hl.MIN_WORKS,
        max_co_works=0,
        stage=None,
        limit=hl.MAX_CANDIDATES,
        rank_by="composite",
        top=hl.MAX_CANDIDATES,
    )
    combos = c["combinations"]
    assert combos["total"] == service.total and combos["items"], "the fixture has pairs"
    assert [(i["a"]["id"], i["b"]["id"]) for i in combos["items"]] == [
        (x.a.id, x.b.id) for x in service.combinations
    ]
    assert len(combos["items"]) <= hl.MAX_CANDIDATES
    first = combos["items"][0]
    assert first["rank"] == 1 and first["label"] == p["candidate_sentence"]
    for key in ("popularity", "bridge", "composite", "weights", "flags"):
        assert key in first["score"]
    assert first["quote_a"]["quote"] and first["quote_a"]["anchor"] == "s1.p1"
    # quotes only on the first QUOTE_TOP, as the service does
    later = [i for i in combos["items"] if i["rank"] > rank.QUOTE_TOP]
    assert all(i["quote_a"] is None for i in later)
    for lst in c["gaps"]:
        assert lst["from_stage"] != lst["to_stage"] and lst["shown"] == len(lst["items"])
        assert [g["rank"] for g in lst["items"]] == list(range(1, lst["shown"] + 1))
        assert all(g["from_stage"] == lst["from_stage"] for g in lst["items"])


def test_gaps_are_one_list_per_stage_pair_never_merged(
    built: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    p, _ = built
    pairs = [(g["from_stage"], g["to_stage"]) for g in p["candidates"]["gaps"]]
    assert len(pairs) == len(set(pairs))


# ---------------------------------------------------------------- evidence rows (landscape_uses)


def test_uses_carry_the_verbatim_quote_and_anchor_and_the_layer(
    built: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _, uses = built
    ide = uses["approaches"]["ide-01"]
    assert ide["rows_total"] == ide["rows_shown"] == sum(r.approach == "ide-01" for r in ROWS)
    core_first = [u["layer"] for u in ide["uses"]]
    assert core_first == sorted(
        core_first, key=lambda x: hl.LAYER_ORDER.index(x) if x in hl.LAYER_ORDER else 99
    )
    one = next(u for u in ide["uses"] if u["work"] == "rf:b")
    assert one["quote"] == "quote b ide-01" and one["anchor"] == "s1.p1"
    assert one["evidence"] == "own-ablation" and one["layer"] == "core"
    ns = next(u for u in uses["approaches"]["exp-02"]["uses"] if u["work"] == "rf:d")
    assert ns["evidence"] == "not-stated"


def test_uses_are_cut_at_the_cap_and_the_total_is_stated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hl, "MAX_USES", 2)
    _, uses = hl.landscape_payloads(data())
    ide = uses["approaches"]["ide-01"]
    assert ide["rows_shown"] == 2 == len(ide["uses"]) and ide["rows_total"] > 2
    assert uses["max_uses"] == 2


# ---------------------------------------------------------------- escaping and no inline data


def test_hostile_text_stays_data_and_the_page_inlines_no_payload() -> None:
    hostile = '</script><img src=x onerror="alert(1)">&"\''
    p, uses = hl.landscape_payloads(data([row("a", "ide-01", quote=hostile)]))
    text = hb.dumps(uses)
    assert json.loads(text)["approaches"]["ide-01"]["uses"][0]["quote"] == hostile
    assert p["works"][0]["title"].startswith("Paper A </script>")
    # the data travels as its own file (data/<name>.js or .json), never inside the page
    spec = hub_ui.PAGES["landscape"]
    page = hub_ui.page_html(spec.id, spec.title, [spec.script], spec.payloads, "v1")
    assert "</script><img" not in page and "Paper A" not in page
    assert 'src="data/landscape.js"' in page and 'src="data/landscape_uses.js"' in page


# ---------------------------------------------------------------- registration


def test_the_page_and_payloads_are_registered() -> None:
    spec = hub_ui.PAGES["landscape"]
    assert spec.script == "pages/landscape.js" and spec.script in hub_ui.ASSETS
    assert spec.payloads == ("shell", "landscape", "landscape_uses")
    assert {"landscape", "landscape_uses"} <= set(hb.BUILDERS)
    assert hub_serve.known_name("landscape_uses")
    ids = list(hub_ui.PAGES)
    assert ids.index("ideas") == ids.index("graph") + 1  # the rail follows this order
    assert ids.index("landscape") == ids.index("ideas") + 1


def test_both_payloads_come_from_one_read(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[int] = []

    def fake(project: Project) -> Inputs:
        reads.append(1)
        return data()

    monkeypatch.setattr(hl, "load_inputs", fake)
    ctx = hb.HubContext(None)  # type: ignore[arg-type]
    a, b = hb.build_landscape(ctx), hb.build_landscape_uses(ctx)
    assert a["exploratory"] and b["exploratory"] and reads == [1]


# ---------------------------------------------------------------- the cache key


def test_event_key_reads_only_the_named_event_types() -> None:
    base = {"extraction.recorded": (3, "e9"), "feed.fetched": (5, "f9"), "page.recorded": (1, "p1")}
    key = hl.event_key(base)
    assert hl.event_key({**base, "feed.fetched": (6, "f10")}) == key
    assert (
        hl.event_key({**base, "runner.finished": (1, "r1"), "inbox.link_added": (1, "i1")}) == key
    )
    assert hl.event_key({**base, "page.recorded": (2, "p2")}) == key
    assert hl.event_key({**base, "extraction.recorded": (4, "e10")}) != key
    assert hl.event_key({**base, "work.layer_set": (1, "w1")}) != key
    assert hl.event_key({**base, "query.registered": (1, "q1")}) != key


def test_the_served_key_ignores_inbox_events_and_follows_corpus_events(
    explore_project: Project, fake_sources: Any
) -> None:
    before_land, before_all = (
        hub_serve.fingerprint(explore_project, "landscape"),
        hub_serve.fingerprint(explore_project, "overview"),
    )
    assert hub_serve.fingerprint(explore_project, "landscape_uses") == before_land
    inbox_service.add_links(
        explore_project,
        explore_project.human_actor(),
        [inbox_service.LinkInput("10.1234/new")],
        Channel.CLI,
    )
    assert (
        hub_serve.fingerprint(explore_project, "overview") != before_all
    )  # the whole-log key moves
    assert (
        hub_serve.fingerprint(explore_project, "landscape") == before_land
    )  # the Landscape key does not
    register_query(
        explore_project,
        explore_project.human_actor(),
        QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="x"),
        sources=fake_sources([[{"title": "In corpus", "authors": ["Ada Zhou"], "year": 2024}]]),
    )
    assert hub_serve.fingerprint(explore_project, "landscape") != before_land


def test_the_key_names_the_technique_code() -> None:
    assert re.fullmatch(r"[0-9a-f]{12}", hl.code_stamp())


# ---------------------------------------------------------------- the page script


def _script() -> str:
    return (
        resources.files("factory.hub_ui")
        .joinpath("pages", "landscape.js")
        .read_text(encoding="utf-8")
    )


def test_the_script_shows_the_notice_escapes_text_and_degrades() -> None:
    js = _script()
    assert "D.notice" in js and 'role="note"' in js  # the exploratory notice on the page
    assert "ls-wait" in js and "is not ready" in js  # the not-built-yet state
    assert "landscape_uses" in js  # the evidence rows load on demand
    assert "paletteExtra" in js  # Ctrl-K lists the approaches
    assert "data-paper" in js and "openDrawer" in js  # titles open the paper drawer
    # every quote, title and flag reaches the page through esc()
    for needle in (
        "esc(u.quote)",
        "esc(q.quote)",
        "esc(f)",
        "esc(g.statement)",
        "esc(title || id)",
    ):
        assert needle in js, needle
    assert "innerHTML" in js and "u.quote}" not in js and "q.quote}" not in js
    assert "http://" not in js.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in js


def test_the_script_declares_only_registered_payloads() -> None:
    js = _script()
    names = {
        n
        for m in re.finditer(r"H\.load\(\[([^\]]*)\]", js)
        for n in re.findall(r"'([^']+)'", m.group(1))
    }
    assert names <= set(hub_ui.PAGES["landscape"].payloads)
    assert {"landscape", "landscape_uses"} <= names


def test_the_shell_lists_the_page_in_the_rail_and_the_palette() -> None:
    shell = resources.files("factory.hub_ui").joinpath("shell.js").read_text(encoding="utf-8")
    assert "['landscape','Landscape','landscape.html']" in shell
    assert shell.count("landscape.html") == 2  # rail and palette
    assert "HUB.paletteExtra" in shell


# ---------------------------------------------------------------- fix round


def test_each_added_event_family_moves_the_key_and_the_excluded_ones_do_not() -> None:
    base = {"extraction.recorded": (3, "e9")}
    key = hl.event_key(base)
    for t in (
        "document.preferred",
        "fulltext.adopted",
        "fulltext.document_added",
        "import.recorded",
    ):
        assert hl.event_key({**base, t: (1, "x1")}) != key, t
    for t in (
        "seed.added",
        "snowball.round_started",
        "inbox.link_added",
        "feed.fetched",
        "runner.started",
        "page.recorded",
        "task.created",
    ):
        assert hl.event_key({**base, t: (1, "x1")}) == key, t


def test_an_off_enum_evidence_is_not_stated_and_counted_and_an_off_enum_status_is_kept() -> None:
    rows = [
        row("a", "ide-01", evidence="rather strong", status="weird-status"),
        row("b", "ide-01", evidence=""),
        row("c", "ide-01"),
    ]
    p, uses = hl.landscape_payloads(data(rows))
    assert p["evidence_unknown"] == 1  # empty is not stated, not unknown
    assert [p["evidence_all"][r[2]] for r in p["rows"]] == [
        "not-stated",
        "not-stated",
        "own-ablation",
    ]
    assert "weird-status" in p["statuses"]
    assert {u["evidence"] for u in uses["approaches"]["ide-01"]["uses"]} == {
        "not-stated",
        "own-ablation",
    }
    assert "not stated" in p["methods"]["page"]
    json.dumps(p, allow_nan=False)


def test_a_cut_keeps_a_share_of_every_layer_and_states_the_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hl, "MAX_USES", 4)
    _, uses = hl.landscape_payloads(data())
    ide = uses["approaches"]["ide-01"]
    assert ide["rows_shown"] == 4 and ide["rows_total"] == sum(r.approach == "ide-01" for r in ROWS)
    layers = {u["layer"] for u in ide["uses"]}
    assert {"core", "applied", "unlayered"} <= layers  # not only the core rows
    again = hl.landscape_payloads(data())[1]["approaches"]["ide-01"]["uses"]
    assert again == ide["uses"]


def test_the_cut_message_and_the_hash_and_focus_handling_are_in_the_script() -> None:
    js = _script()
    assert "The matching rows are beyond the" in js and "rows in total" in js
    assert "rows_shown < box.rows_total" in js
    assert (
        "lens.layer = l && layerOptions.includes(l) ? l : D.lens.layer" in js
    )  # a missing layer resets
    assert (
        "location.hash = h" in js and "H.hash.set" in js
    )  # push for navigation, replace for the lens
    assert ".focus()" in js
    assert (
        "NOTICE_TEXT" in js and js.count("noticeBox(") >= 2
    )  # the building and not-ready states keep the box
    assert "cover every layer" in js  # the note names the figures that ignore the lens
    # lens controls, drawer and palette are wired
    assert "onchange" in js and "H.openDrawer" in js and "H.paletteExtra = " in js


def test_the_script_notice_text_is_the_payload_notice() -> None:
    assert NOTICE.removeprefix("exploratory: ") in _script()


def test_the_script_has_no_colour_literals() -> None:
    js = _script()
    assert not re.search(
        r"#[0-9a-fA-F]{3,8}\b(?![-\w])", re.sub(r"href: '#a=|\$\('#\w+'\)|'#'", "", js)
    )
    assert not re.search(r"\b(?:rgba?|hsla?)\(", js)


def test_the_phone_rail_has_a_token_based_scroll_cue() -> None:
    css = resources.files("factory.hub_ui").joinpath("kit.css").read_text(encoding="utf-8")
    block = css[css.index("scroll cue") :]
    assert "overflow-x:auto" in css and "background-attachment:local,local,scroll,scroll" in block
    assert "var(--line)" in block and not re.search(r"#[0-9a-fA-F]{3,6}\b", block)


def _ego_boxes(n: int) -> list[dict[str, Any]]:
    """The label boxes of the ego graph for `n` neighbours, from the page's own `egoLayout`, run
    in node (skipped when node is absent). Box width uses a fixed character width."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    js = _script()
    code = js[js.index("/*ego-layout-begin*/") : js.index("/*ego-layout-end*/")]
    prog = code + (f"const L = egoLayout({n}); console.log(JSON.stringify({{EGO, L}}));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, check=True).stdout
    found = json.loads(out)
    e = found["EGO"]
    boxes = []
    for L in found["L"]:
        w = e["chars"] * e["cw"]
        x0, x1 = (L["tx"], L["tx"] + w) if L["anchor"] == "start" else (L["tx"] - w, L["tx"])
        boxes.append(
            {
                "x0": x0,
                "x1": x1,
                "y0": L["y"] - e["lineH"] / 2,
                "y1": L["y"] + e["lineH"] / 2,
                "L": L,
                "E": e,
            }
        )
    return boxes


@pytest.mark.parametrize("n", [1, 2, 5, 12, 16])
def test_ego_labels_do_not_overlap_and_stay_inside_the_picture(n: int) -> None:
    boxes = _ego_boxes(n)
    assert len(boxes) == n
    for b in boxes:
        e = b["E"]
        assert b["x0"] >= 0 and b["x1"] <= e["W"] and b["y0"] >= 0 and b["y1"] <= e["H"]
        # the centre box (156 x 40) is clear of every label
        cx, cy = e["W"] / 2, e["H"] / 2
        assert b["x1"] < cx - 78 or b["x0"] > cx + 78 or b["y1"] < cy - 20 or b["y0"] > cy + 20
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            apart = (
                a["x1"] <= b["x0"] or b["x1"] <= a["x0"] or a["y1"] <= b["y0"] or b["y1"] <= a["y0"]
            )
            assert apart, (n, a["L"], b["L"])


def test_the_ego_layout_is_deterministic_and_the_anchors_have_no_underline() -> None:
    assert _ego_boxes(16) == _ego_boxes(16)
    js = _script()
    assert "svg.ego a{cursor:pointer;text-decoration:none}" in js
