"""The hub's agreement table shows the all-rows and the aligned platform rates, each labelled."""

# ruff: noqa: F811
from pathlib import Path
from types import SimpleNamespace

import pytest

from factory.events.envelope import Actor
from factory.mining.spec import spec_to_json
from factory.services import site_agreement
from factory.services.context import Project
from factory.services.miner_add import add_miner
from factory.services.site_agreement import GLOSSARY, build_agreement
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import VISION_NAME, method_vision


def test_both_platform_rates_are_shown_with_their_values(
    project: Project,
    human: Actor,
    world: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_miner(project, human, {"spec": spec_to_json(method_vision())})
    status = SimpleNamespace(name=VISION_NAME, agreement=0.625, agreement_aligned=0.875)
    monkeypatch.setattr(site_agreement.mining_service, "mine_status", lambda _p: [status])
    out = tmp_path / "agreement"
    out.mkdir()
    build_agreement(project, out)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "<th>platform: all rows</th><th>platform: aligned rows</th>" in html
    assert "<td>0.625</td><td>0.875</td>" in html
    assert "platform measure" not in html
    described = dict(GLOSSARY)
    assert "all rows" in described["platform: all rows"]
    assert "aligned" in described["platform: aligned rows"]
