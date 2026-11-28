"""Unit tests of hub_ui/scope.js (HS-10 to HS-12), run under Node over JSON fixtures.

The module is pure (no DOM), so Node loads it directly. Skipped when `node` is not on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")

_SCOPE = Path(str(resources.files("factory").joinpath("hub_ui", "scope.js")))


def js(expr: str) -> Any:
    """Evaluate a JS expression with `S` bound to the scope module; return its JSON value."""
    code = f"const S=require({json.dumps(str(_SCOPE))});console.log(JSON.stringify({expr}));"
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_parse_reads_keys_and_ignores_others() -> None:
    got = js("S.parse('#tab=x&scope.from=2026-07&scope.to=2026-09&scope.set=s%201')")
    assert got == {"from": "2026-07", "to": "2026-09", "set": "s 1"}
    assert js("S.parse('')") == {"from": None, "to": None, "set": None}
    assert js("S.parse(undefined)") == {"from": None, "to": None, "set": None}


@pytest.mark.parametrize("bad", ["2026", "2026-13", "2026-00", "2026-7", "abc", "2026-07-01", ""])
def test_parse_drops_malformed_months(bad: str) -> None:
    assert js(f"S.parse('#scope.from={bad}')")["from"] is None


def test_format_round_trips_and_omits_empty() -> None:
    assert js("S.format({from:'2026-07',to:'2026-09',set:'a'})") == (
        "scope.from=2026-07&scope.to=2026-09&scope.set=a"
    )
    assert js("S.format({from:'2026-07',to:null,set:null})") == "scope.from=2026-07"
    assert js("S.format({})") == ""
    assert js("S.format(null)") == ""
    assert js("S.format({from:'junk'})") == ""
    assert js("S.parse(S.format({from:'2025-01',to:'2025-12',set:'x y'}))") == {
        "from": "2025-01",
        "to": "2025-12",
        "set": "x y",
    }


CASES = [
    # (published, from, to, expected class)
    ("2026-07-15", "2026-07", "2026-09", "in"),
    ("2026-06-30", "2026-07", "2026-09", "out"),
    ("2026-10-01", "2026-07", "2026-09", "out"),
    ("2026-07", "2026-07", "2026-09", "in"),
    ("2026-10", "2026-07", "2026-09", "out"),
    ("2026-07-31T10:00:00Z", "2026-07", "2026-07", "in"),
    ("2026-07-15", "2026-07", "2026-07", "in"),  # boundary: from = to
    ("2026-08-15", "2026-07", "2026-07", "out"),
    ("2026", "2026-01", "2026-12", "in"),  # whole year inside
    ("2026", "2025-06", "2027-06", "in"),
    ("2026", "2026-02", "2026-12", "year-only"),
    ("2026", "2026-01", "2026-11", "year-only"),
    ("2026", "2026-07", "2026-09", "year-only"),
    ("2026", "2026-01", None, "in"),  # open end
    ("2026", None, "2026-12", "in"),
    ("2026", "2027-01", None, "year-only"),
    ("2025-12", "2026-01", None, "out"),
    ("", "2026-01", "2026-12", "undated"),
    (None, "2026-01", "2026-12", "undated"),
    ("n.d.", "2026-01", "2026-12", "undated"),
    ("2026-13", "2026-01", "2026-12", "undated"),
    ("2026-07-15", None, None, "in"),
    ("2026-07-15", "2026-09", "2026-07", "out"),  # to before from: empty scope
    ("2026", "2026-09", "2026-07", "out"),
]


@pytest.mark.parametrize(("published", "lo", "hi", "want"), CASES)
def test_classify(published: str | None, lo: str | None, hi: str | None, want: str) -> None:
    scope = {"from": lo, "to": hi}
    got = js(f"S.classify({json.dumps(published)}, {json.dumps(scope)})")
    assert got == want
    assert js(f"S.inRange({json.dumps(published)}, {json.dumps(scope)})") is (want == "in")


def test_to_before_from_is_empty_not_swapped() -> None:
    assert js("S.empty({from:'2026-09',to:'2026-07'})") is True
    assert js("S.empty({from:'2026-07',to:'2026-07'})") is False
    assert js("S.empty({from:'2026-07'})") is False
    assert js("S.parse('#scope.from=2026-09&scope.to=2026-07')") == {
        "from": "2026-09",
        "to": "2026-07",
        "set": None,
    }
    res = js(
        "S.apply([{d:'2026-08-01'},{d:''}], r=>r.d, {from:'2026-09',to:'2026-07'}, "
        "{includeUndated:false})"
    )
    assert res["n"] == 0
    assert res["N"] == 2


ROWS = [
    {"id": "a", "d": "2026-07-15"},
    {"id": "b", "d": "2026-05"},
    {"id": "c", "d": "2026"},
    {"id": "d", "d": ""},
    {"id": "e", "d": "2026-08"},
    {"id": "f", "d": None},
]


def ids(rows: list[dict[str, Any]]) -> list[str]:
    return [r["id"] for r in rows]


def test_apply_excludes_undated_by_default() -> None:
    res = js(
        f"S.apply({json.dumps(ROWS)}, r=>r.d, {{from:'2026-07',to:'2026-09'}}, "
        "{includeUndated:false})"
    )
    assert ids(res["inScope"]) == ["a", "e"]
    assert ids(res["outOfScope"]) == ["b", "c"]
    assert ids(res["yearOnly"]) == ["c"]
    assert ids(res["undated"]) == ["d", "f"]
    assert (res["n"], res["N"]) == (2, 6)


def test_apply_include_undated_adds_them_to_scope() -> None:
    res = js(
        f"S.apply({json.dumps(ROWS)}, r=>r.d, {{from:'2026-07',to:'2026-09'}}, "
        "{includeUndated:true})"
    )
    assert ids(res["inScope"]) == ["a", "d", "e", "f"]
    assert ids(res["undated"]) == ["d", "f"]
    assert (res["n"], res["N"]) == (4, 6)


def test_apply_without_bounds_keeps_everything_and_defaults_options() -> None:
    res = js(f"S.apply({json.dumps(ROWS)}, r=>r.d, {{set:'s1'}})")
    assert res["n"] == res["N"] == 6
    assert res["outOfScope"] == []
    assert ids(res["undated"]) == ["d", "f"]
    assert js("S.apply(null, r=>r, {}, {})")["N"] == 0


def test_apply_whole_year_in_scope() -> None:
    res = js(
        f"S.apply({json.dumps(ROWS)}, r=>r.d, {{from:'2026-01',to:'2026-12'}}, "
        "{includeUndated:false})"
    )
    assert ids(res["inScope"]) == ["a", "b", "c", "e"]
    assert res["yearOnly"] == []


def test_module_has_no_dom_access() -> None:
    src = _SCOPE.read_text(encoding="utf-8")
    for token in ("document.", "querySelector", "location", "localStorage"):
        assert token not in src.replace("window.", "").replace("typeof window", "")
