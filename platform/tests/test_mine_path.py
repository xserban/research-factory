"""The mine path: miner scopes through the extraction engine, then `mine_next`/`mine_record`
(M-C, tasks 5 and 7)."""

import pytest

from factory.errors import FactoryValidationError
from factory.model.extraction import (
    ExtractionClosed,
    ExtractionPassJoined,
    ExtractionPassOpened,
    ExtractionRecorded,
    ExtractionResolved,
    MinerScope,
    Scope,
    StoredField,
    pack_tag,
    scope_from_value,
    scope_of_pack,
    scope_of_schema_ref,
)
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project
from factory.services.extraction import (
    join_extraction_pass,
    session_scope,
)
from factory.services.stages import MINE_KINDS, is_mine_kind, kinds_for, scope_of_kind
from tests.extraction_helpers import (
    CNV,
    DOC,
    PROTOCOL,
    ROW,
    SESSION_A,
    SESSION_B,
    TASK,
    WORK,
    _extractor,
    _record,
    _rows,
)

M = "m-vision-result"


# --- Task 5: scope ---


def test_scope_key_value_is_name() -> None:
    scope = MinerScope(M)
    assert scope.value == M
    assert scope == MinerScope(M) and scope != MinerScope("m-other")
    assert scope != Scope.EVIDENCE and scope != Scope.CONTRIBUTION
    assert scope_of_pack(M) == scope
    assert scope_of_schema_ref(f"{M}@3") == scope
    assert scope_from_value(M) == scope and scope_from_value("evidence") is Scope.EVIDENCE
    assert pack_tag(scope) == M and pack_tag(Scope.EVIDENCE) is None


@pytest.mark.parametrize("pack", ["vision-result", "ml-benchmark", "m-", "contributions", "M-x"])
def test_names_outside_the_namespace_stay_evidence(pack: str) -> None:
    assert scope_of_pack(pack) is Scope.EVIDENCE


def test_mine_kinds_belong_to_no_fixed_scope() -> None:
    assert set(MINE_KINDS) == {PassLabel.A, PassLabel.B}
    assert kinds_for(MinerScope(M)) is MINE_KINDS
    for kind in MINE_KINDS.values():
        assert is_mine_kind(kind) and scope_of_kind(kind) is None
    assert not is_mine_kind("extract_a") and not is_mine_kind("screen_a")


def test_m_pack_projects_to_miner_scope(project: Project) -> None:
    _record(
        project,
        "extraction.pass_opened",
        ExtractionPassOpened(pass_label=PassLabel.A, random_seed=1, field_order="schema", pack=M),
    )
    _record(
        project,
        "extraction.pass_joined",
        ExtractionPassJoined(pass_label=PassLabel.A, session="s1", model="m", pack=M),
    )
    _record(
        project,
        "extraction.recorded",
        ExtractionRecorded(
            extraction_id="ext_01HZX3K4M5N6P7Q8R9S0TVWXYA",
            work_id=WORK,
            pass_label=PassLabel.A,
            task_id=TASK,
            protocol_id=PROTOCOL,
            schema_ref=f"{M}@1",
            document_id=DOC,
            conversion_id=CNV,
            row_key=ROW,
            fields={"v": StoredField(value="1", copy_marker=False)},
            supersedes=None,
            verifier=1,
        ),
        agent=True,
    )
    _record(
        project,
        "extraction.closed",
        ExtractionClosed(
            work_id=WORK,
            pass_label=PassLabel.A,
            task_id=TASK,
            rows=1,
            claims=0,
            reason=None,
            pack=M,
        ),
    )
    _record(
        project,
        "extraction.resolved",
        ExtractionResolved(
            work_id=WORK,
            row_key=ROW,
            field="v",
            choice="a",
            reason="r",
            channel=Channel.CLI,
            protocol_id=PROTOCOL,
            pack=M,
        ),
    )
    project.index.sync()
    assert _rows(project, "SELECT scope, pass_label FROM extraction_passes") == [(M, "A")]
    assert _rows(project, "SELECT scope, model FROM extraction_sessions") == [(M, "m")]
    assert _rows(project, "SELECT scope, pack FROM extraction_rows") == [(M, M)]
    assert _rows(project, "SELECT scope FROM extraction_closures") == [(M,)]
    assert _rows(project, "SELECT scope FROM extraction_resolutions") == [(M,)]
    assert (
        _rows(project, "SELECT DISTINCT scope FROM extraction_rows WHERE scope = 'evidence'") == []
    )


def test_legacy_log_replays_identically(project: Project) -> None:
    """A log without `m-` packs projects to the same extraction tables after a full rebuild, and
    its rows keep a null `pack`."""
    _record(
        project,
        "extraction.pass_opened",
        ExtractionPassOpened(pass_label=PassLabel.A, random_seed=1, field_order="schema"),
    )
    _record(
        project,
        "extraction.recorded",
        ExtractionRecorded(
            extraction_id="ext_01HZX3K4M5N6P7Q8R9S0TVWXYB",
            work_id=WORK,
            pass_label=PassLabel.A,
            task_id=TASK,
            protocol_id=PROTOCOL,
            schema_ref="ml-benchmark@1",
            document_id=DOC,
            conversion_id=CNV,
            row_key=ROW,
            fields={"v": StoredField(value="1", copy_marker=False)},
            supersedes=None,
            verifier=1,
        ),
        agent=True,
    )
    project.index.sync()
    tables = ("extraction_passes", "extraction_rows", "extraction_fields", "extraction_sessions")
    before = {t: _rows(project, f"SELECT * FROM {t} ORDER BY 1, 2") for t in tables}
    project.index.rebuild()
    assert {t: _rows(project, f"SELECT * FROM {t} ORDER BY 1, 2") for t in tables} == before
    assert _rows(project, "SELECT scope, pack FROM extraction_rows") == [("evidence", None)]


def test_session_cannot_cross_miner_scopes(project: Project) -> None:
    """G2-A ruling 2 as decision 129 amends it: a session joins one pass across evidence and
    contribution; across miners it may hold one label (so a second miner's pass A is allowed),
    never another label, never evidence or contribution."""
    first, other = MinerScope(M), MinerScope("m-other-thing")
    a = _extractor(SESSION_A, "claude-opus-5-5")
    join_extraction_pass(project, a, PassLabel.A, scope=first)
    assert session_scope(project, a.session) == first
    join_extraction_pass(project, a, PassLabel.A, scope=first)  # idempotent
    for scope in (Scope.EVIDENCE, Scope.CONTRIBUTION):
        with pytest.raises(FactoryValidationError) as raised:
            join_extraction_pass(project, a, PassLabel.A, scope=scope)
        assert raised.value.issues[0].field == "pass"
    with pytest.raises(FactoryValidationError) as raised:
        join_extraction_pass(project, a, PassLabel.B, scope=first)
    assert raised.value.issues[0].field == "pass"
    with pytest.raises(FactoryValidationError) as raised:
        join_extraction_pass(project, a, PassLabel.B, scope=other)  # another label, another miner
    assert raised.value.issues[0].field == "pass"
    join_extraction_pass(project, a, PassLabel.A, scope=other)  # the same label of another miner


def test_model_independence_is_per_miner_scope(project: Project) -> None:
    a = _extractor(SESSION_A, "claude-opus-5-5")
    b_same_model = _extractor(SESSION_B, "claude-opus-5-5")
    join_extraction_pass(project, a, PassLabel.A, scope=MinerScope(M))
    with pytest.raises(FactoryValidationError) as raised:
        join_extraction_pass(project, b_same_model, PassLabel.B, scope=MinerScope(M))
    assert raised.value.issues[0].field == "model"
    join_extraction_pass(project, b_same_model, PassLabel.B, scope=MinerScope("m-other-thing"))
    assert session_scope(project, b_same_model.session) == MinerScope("m-other-thing")
