"""The extraction gates of the human queue: unresolved disagreements and an unlabelled audit."""

from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.extraction_agreement import extraction_agreement
from factory.services.extraction_audit import extraction_audit_sample
from factory.services.human_queue import Gate, human_queue
from tests import test_extraction_agreement as ea
from tests.test_extraction_agreement import _both, _r

# Re-export the fixtures under their own names so pytest finds them in this module.
ext_a = ea.ext_a
ext_b = ea.ext_b
screened = ea.screened
world = ea.world


def test_extraction_disagreements_counted(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _both(
        project,
        ext_a,
        ext_b,
        a=lambda w: [_r(), _r("2", "t1.r3.c3")] if w == odd else [_r()],
        b=lambda w: [_r(task="detection")] if w == odd else [_r()],
    )
    expected = len(extraction_agreement(project, human).disagreements)
    assert expected > 0
    (item,) = [i for i in human_queue(project).items if i.gate is Gate.EXTRACTION_DISAGREEMENTS]
    assert item.count == expected
    assert item.stage is None
    assert item.command == "factory --project demo extract agreement"


def test_extraction_audit_unlabelled(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    sampled = extraction_audit_sample(project, human, random_seed=3)
    (item,) = [i for i in human_queue(project).items if i.gate is Gate.EXTRACTION_AUDIT]
    assert item.count == len(sampled.items) > 0
    assert item.command == (
        "factory --project demo extract audit-label <audit-id> <work> <row-key> <field>"
        " --correct|--incorrect"
    )
    assert Gate.EXTRACTION_DISAGREEMENTS not in {i.gate for i in human_queue(project).items}


def test_no_extraction_gate_without_a_schema(project: Project) -> None:
    gates = {i.gate for i in human_queue(project).items}
    assert not gates & {Gate.EXTRACTION_DISAGREEMENTS, Gate.EXTRACTION_AUDIT}
