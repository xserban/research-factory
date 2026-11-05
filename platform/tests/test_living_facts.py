"""Conclusion facts from the evidence report (living-D, task 1)."""

from factory.living.facts import conclusion_facts, facts_diff
from factory.services.evidence_report import EvidenceReport, assemble_report
from factory.services.extraction_agreement import FinalField, FinalRow
from tests.evidence_helpers import ff, frow, pilot_inputs


def cost(n: str) -> FinalField:
    return ff(n, unit="count", canon=n)


def report(rows: list[FinalRow]) -> EvidenceReport:
    return assemble_report(pilot_inputs(rows))


def trio() -> list[FinalRow]:
    return [
        frow("rf:w1", "rk_000000000101", "A", "80.0", params=cost("20000000")),
        frow("rf:w2", "rk_000000000201", "B", "79.0", params=cost("30000000")),
        frow("rf:w3", "rk_000000000301", "C", "82.0", params=cost("40000000")),
    ]


def test_frontier_members_by_partition() -> None:
    facts = conclusion_facts(report(trio()), included=3)
    (group,) = facts.groups
    assert len(group.frontier) == 1
    ((key, members),) = group.frontier.items()
    assert key.startswith("params|")
    assert members == ("rk_000000000101", "rk_000000000301")
    assert group.independent_rows == 3
    assert facts.included == 3


def test_best_respects_direction() -> None:
    (group,) = conclusion_facts(report(trio()), included=3).groups
    assert group.best == ("rk_000000000301",)  # accuracy: higher is better
    assert group.best_reason is None


def test_best_undefined_without_direction() -> None:
    rows = [
        frow("rf:w1", "rk_000000000101", "A", "80.0", metric="Invented Score"),
        frow("rf:w2", "rk_000000000201", "B", "79.0", metric="Invented Score"),
    ]
    (group,) = conclusion_facts(report(rows), included=2).groups
    assert group.best is None
    assert group.best_reason == "direction-unknown"


def test_best_ties_listed() -> None:
    rows = [
        frow("rf:w2", "rk_000000000201", "B", "82.0"),
        frow("rf:w1", "rk_000000000101", "A", "82.0"),
        frow("rf:w3", "rk_000000000301", "C", "70.0"),
    ]
    (group,) = conclusion_facts(report(rows), included=3).groups
    assert group.best == ("rk_000000000101", "rk_000000000201")


def test_copied_rows_never_best() -> None:
    rows = [
        frow("rf:w1", "rk_000000000101", "A", "80.0"),
        frow("rf:w2", "rk_000000000201", "B", "95.0", cited=True),
        frow("rf:w3", "rk_000000000301", "C", "90.0", marker=True),
    ]
    (group,) = conclusion_facts(report(rows), included=3).groups
    assert group.best == ("rk_000000000101",)
    assert group.independent_rows == 1


def test_facts_sorted_and_stable() -> None:
    forward = conclusion_facts(report(trio()), included=3)
    backward = conclusion_facts(report(list(reversed(trio()))), included=3)
    assert forward.model_dump_json() == backward.model_dump_json()
    ids = [g.group_id for g in forward.groups]
    assert ids == sorted(ids)


def test_diff_detects_new_frontier_member() -> None:
    old = conclusion_facts(report(trio()), included=3)
    better = [*trio(), frow("rf:w4", "rk_000000000401", "D", "83.0", params=cost("10000000"))]
    new = conclusion_facts(report(better), included=4)
    diff = facts_diff(old, new)
    assert not diff.empty
    assert diff.included_delta == 1
    (changed,) = diff.groups
    assert changed.best_changed == (("rk_000000000301",), ("rk_000000000401",))
    assert changed.rows_delta == 1
    assert list(changed.frontier_added.values()) == [("rk_000000000401",)]
    assert facts_diff(new, new).empty
