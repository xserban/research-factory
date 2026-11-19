"""The `sources` hub payload: search and dedup, acquisition, conversion and study documents."""

from __future__ import annotations

import json

from factory.services import hub_build as hb
from factory.services import hub_sources as hs
from factory.services.context import Project
from factory.services.fulltext_status import fulltext_status
from factory.services.protocol import list_deviations
from tests.test_hub_build import world  # noqa: F401  (fixture)


def test_payload_is_json_with_every_section_and_a_method_per_view(world: Project) -> None:  # noqa: F811
    payload = hs.build(hb.HubContext(world))
    assert payload["ready"] is True
    assert set(payload) >= {"methods", "search", "acquisition", "conversion", "documents"}
    json.dumps(payload)
    for key in ("search", "yield", "dedup", "acquisition", "conversion", "survival", "documents"):
        assert payload["methods"][key].startswith("<b>What it shows</b>")


def test_acquisition_counts_are_the_services_counts(world: Project) -> None:  # noqa: F811
    acq = hs.build(hb.HubContext(world))["acquisition"]
    status = fulltext_status(world)
    assert (acq["promoted"], acq["unsought"], acq["retrieved"], acq["not_retrieved"]) == (
        status.promoted,
        status.unsought,
        status.retrieved,
        status.not_retrieved,
    )
    assert acq["unsought"] + acq["retrieved"] + acq["not_retrieved"] == acq["promoted"]
    assert len(acq["works"]) == acq["not_retrieved"]
    assert sum(acq["by_route"].values()) == sum(status.by_route.values())


def test_undeclared_works_are_those_no_deviation_affects(world: Project) -> None:  # noqa: F811
    acq = hs.build(hb.HubContext(world))["acquisition"]
    declared = {w for d in list_deviations(world) for w in d.affects}
    missing = {w["id"] for w in acq["works"]}
    assert set(acq["undeclared"]) == missing - declared
    assert acq["batch_deviation"]["affects"] == acq["undeclared"]
    assert len(acq["deviations"]) == len(list_deviations(world))
    for w in acq["works"]:
        assert (w["declared_by"] is None) == (w["id"] in acq["undeclared"])
        assert w["deviation"]["affects"] == [w["id"]]


def test_search_rows_carry_gap_runs_and_capped_skipped_records(world: Project) -> None:  # noqa: F811
    search = hs.build(hb.HubContext(world))["search"]
    assert "generated" not in search
    for q in search["queries"]:
        assert q["gap"] is None or q["gap"] == q["reported"] - q["retrieved"]
        assert len(q["skipped"]) <= hs.SKIPPED_SHOWN
        assert q["skipped_n"] >= len(q["skipped"])
    assert search["skipped_total"] == sum(search["skipped_by_reason"].values())
    assert set(search["merge_tiles"]) >= {"merges", "active", "reverted"}
    assert search["merge_tiles"]["merges"] == len(search["merges"])


def test_conversion_without_cache_reports_not_computed(world: Project) -> None:  # noqa: F811
    conv = hs.build(hb.HubContext(world))["conversion"]
    assert conv["computed"] is False
    assert conv["low"] == 0.8
    for doc in conv["documents"]:
        assert doc["recall"] is None and doc["precision"] is None
    assert conv["commands"]["coverage"].endswith("document coverage")


def test_histogram_bins_cover_the_unit_interval() -> None:
    assert hs._histogram([0.0, 0.05, 0.95, 1.0, 0.5]) == [2, 0, 0, 0, 0, 1, 0, 0, 0, 2]
    assert sum(hs._histogram([0.31, 0.32])) == 2


def test_documents_empty_state(world: Project) -> None:  # noqa: F811
    docs = hs.build(hb.HubContext(world))["documents"]
    assert docs["registered"] == 0
    assert docs["kinds"] == []
    assert docs["changed"] == 0 and docs["missing"] == 0
