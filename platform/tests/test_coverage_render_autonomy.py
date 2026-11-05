"""The researcher's coverage text prints autonomy counts only when there are any (re-review 3)."""

from factory.cli.render import import_coverage_lines
from factory.services.coverage import CoverageReport


def _report(autonomy: dict[str, int]) -> CoverageReport:
    return CoverageReport(
        import_id="imp_X",
        label="post-search",
        parts=[],
        included_not_in_library=3,
        suggestions=[],
        protocol_id=None,
        as_of="ev_0",
        autonomy=autonomy,
    )


def test_text_is_unchanged_when_autonomy_is_empty() -> None:
    lines = import_coverage_lines(_report({}))
    assert not any("autonomy" in line for line in lines)
    assert lines[-1] == "included works absent from the library: 3"


def test_counts_are_printed_per_level() -> None:
    plain = import_coverage_lines(_report({}))
    shown = import_coverage_lines(
        _report({"human": 2, "audited-agent": 0, "agent": 1}),
    )
    assert shown[: len(plain)] == plain
    assert shown[len(plain) :] == [
        "resolution decisions by autonomy: human 2, audited-agent 0, agent 1"
    ]
