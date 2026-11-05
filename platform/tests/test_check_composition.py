"""`check` is composed from the module declarations and reports exactly what it did before.

The reference is the report order of the rules as `_hits` wrote it before slice M: the rule
functions called one after the other. The composed report must equal it hit for hit, finding for
finding, in every rigour mode."""

import pytest

from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.modules.contract import CheckHit
from factory.services import check as check_module
from factory.services.agreement import final_outcomes
from factory.services.context import Project
from factory.services.modules import default_modules
from tests.helpers import SourcesFor, _setup
from tests.screening_helpers import _calibrate, _corpus, _partial_corpus, _screen_ordinary


def _legacy_hits(project: Project) -> list[CheckHit]:
    """The rules in the order `_hits` called them before the modules composed it."""
    c = check_module
    project.index.sync()
    outcomes = final_outcomes(project)
    hits: list[CheckHit] = []
    hits += c._broken_links(project)
    hits += c._missing_provenance(project)
    hits += c._shortfalls(project)
    hits += c._seeds(project)
    hits += c._protocol_gates(project)
    hits += c._screening(project, outcomes)
    hits += c._calibration_and_agreement(project)
    hits += c._audit(project)
    hits += c._chase(project, outcomes)
    hits += c._checklist(project)
    hits += c._merge_conflicts(project, outcomes)
    hits += c._fulltext(project)
    hits += c._extraction(project)
    hits += c._evidence(project)
    hits += c._references(project)
    hits += c._snowball(project, outcomes)
    hits += c._inbox(project, outcomes)
    hits += c._imports(project)
    hits += c._living(project)
    hits += c._notices(project, outcomes)
    hits += c._conclusions(project)
    hits += c._lineage(project)
    hits += c._layer(project)
    return hits


def _plain(hits: list[CheckHit]) -> list[tuple[object, ...]]:
    return [(h.code, h.refs, h.message, h.role, h.severity) for h in hits]


def _assert_identical(project: Project) -> None:
    legacy = _legacy_hits(project)
    assert _plain(check_module._hits(project)) == _plain(legacy)
    for mode in RigorMode:
        expected = [
            (h.code, h.refs, h.message, h.role)
            for h in legacy
            if check_module._severity(h, mode) is not None
        ]
        got = [
            (f.code, tuple(f.refs), f.message, f.role)
            for f in check_module._findings_as(project, mode)
        ]
        assert got == expected, mode


def test_check_identical_on_a_corpus_with_pending_work(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources)
    codes = {h.code for h in check_module._hits(project)}
    assert {"screening-pending", "snowball-plan-missing"} <= codes
    _assert_identical(project)


def test_check_identical_on_a_screened_corpus(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _partial_corpus(project, agent, human, mock_sources)
    _calibrate(project, agent, human, protocol_id)
    _screen_ordinary(project, agent, protocol_id)
    assert check_module._hits(project)
    _assert_identical(project)


def test_check_identical_on_a_project_with_a_protocol_only(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    _assert_identical(project)


def test_check_identical_on_an_empty_project(project: Project) -> None:
    _assert_identical(project)


def test_each_module_returns_only_its_own_codes(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources)
    registry = default_modules()
    everything = check_module._hits(project)
    seen: list[CheckHit] = []
    for module in registry.modules():
        for hit in module.hits(project):
            assert registry.owner_of_check(hit.code) == module.spec.name, hit.code
            seen.append(hit)
    assert sorted(seen, key=lambda h: h.seq) == everything


def test_check_rules_run_once(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _corpus(project, agent, human, mock_sources)
    calls: list[int] = []
    real = check_module.final_outcomes

    def spy(p: Project):  # type: ignore[no-untyped-def]
        calls.append(1)
        return real(p)

    monkeypatch.setattr(check_module, "final_outcomes", spy)
    check_module.check(project)
    assert len(calls) == 1


def test_a_hit_with_no_owner_is_an_error(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    ghost = CheckHit("zzz-ghost", (), "no module declares this")
    monkeypatch.setattr(check_module, "_run_rules", lambda p: [ghost])
    with pytest.raises(KeyError, match="zzz-ghost"):
        check_module._hits(project)


def test_levels_come_from_the_declarations() -> None:
    assert default_modules().levels() == check_module.LEVELS
    assert check_module.LEVELS["screening-pending"] == ("warning", "warning", "warning")


def test_order_inside_a_rule_group_survives_mixed_owners(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One rule can yield codes of several modules; the report keeps the rule's own order."""
    groups = {
        "_fulltext": ["library-missing", "fulltext-decision-stale-document", "source-changed"],
        "_living": ["watch-plan-missing", "calibration-model-drift", "watch-overdue"],
        "_lineage": ["contribution-error-ceiling", "graph-extraction-missing", "relation-stale"],
    }
    for name, codes in groups.items():
        monkeypatch.setattr(
            check_module,
            name,
            lambda p, *a, _c=codes: [CheckHit(c, (), c) for c in _c],  # type: ignore[misc]
        )
    expected = [c for codes in groups.values() for c in codes]
    mine = set(expected)
    assert [h.code for h in _legacy_hits(project) if h.code in mine] == expected
    assert [h.code for h in check_module._hits(project) if h.code in mine] == expected
    assert _plain(check_module._hits(project)) == _plain(_legacy_hits(project))


def test_layer_hits_keep_their_place_after_lineage(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = ["layer-leak", "concept-cycle", "layer-scan-incomplete"]
    monkeypatch.setattr(check_module, "_layer", lambda p: [CheckHit(c, (), c) for c in layer])
    monkeypatch.setattr(check_module, "_lineage", lambda p: [CheckHit("relation-stale", (), "r")])
    got = [h.code for h in check_module._hits(project)]
    assert got[-4:] == ["relation-stale", *layer]
    assert [h.code for h in _legacy_hits(project)][-4:] == got[-4:]
