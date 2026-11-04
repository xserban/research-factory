"""R-20: the agent-facing bibliography never shows a held-out seed's work (fix round 1)."""

from collections.abc import Callable, Mapping

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.exports.keys import bib_key
from factory.services.context import Project
from factory.services.dedup import active_merges, dedup_run
from factory.services.exports import (
    export_bibliography,
    render_bibliography,
    select_works,
)
from factory.services.search import get_work
from factory.services.seeds import SeedRole, all_seeds
from factory.sources.registry import SourceFactory
from tests.helpers import open_session
from tests.test_chase_service import _corpus, _settle
from tests.test_prisma import _merge_items

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


@pytest.mark.anyio
async def test_mcp_export_hides_held_out_works(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    pid = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, pid)
    [held] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.work_id is not None
    work = get_work(project, held.work_id)
    assert work is not None
    everyone = select_works(project, "corpus")
    assert held.work_id in everyone
    rest = [w for w in everyone if w != held.work_id]
    unfiltered = "".join(export_bibliography(project, "bibtex", scope="corpus"))
    assert work.title in unfiltered  # the CLI view stays unfiltered
    async with open_session(settings, clock) as session:
        body = await session.call("export_bibliography", project="demo", scope="corpus")
        included = await session.call("export_bibliography", project="demo")
        named = await session.call("export_bibliography", project="demo", ids=[held.work_id])
        unknown = await session.call(
            "export_bibliography", project="demo", ids=["rf:nope-00000000"]
        )
    text = body["data"]["text"]
    assert body["data"]["count"] == len(rest)
    assert work.title not in text and bib_key(held.work_id) not in text
    assert (
        held.work_id not in included["data"]["text"] and work.title not in included["data"]["text"]
    )
    assert included["data"]["count"] == len(rest)
    assert text.count("@") == len(rest)
    assert named["ok"] is False and named["errors"][0]["field"] == "ids"
    held_msg = named["errors"][0]["reason"].replace(held.work_id, "X")
    assert held_msg == unknown["errors"][0]["reason"].replace("rf:nope-00000000", "X")
    # Byte-identical to the export of the same works without it (identifier scrub aside).
    expected = "".join(render_bibliography(project, "bibtex", rest))
    assert len(text.splitlines()) == len(expected.splitlines())


def test_service_exclusion_is_byte_identical_to_absence(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources, extra=_merge_items())
    dedup_run(project)
    [merge] = active_merges(project)
    ids = select_works(project, "corpus")
    hidden = frozenset({merge.absorbed[0]})  # a member of a merge hides the merged work
    kept = select_works(project, "corpus", exclude_work_ids=hidden)
    assert merge.primary not in kept
    assert kept == [w for w in ids if w != merge.primary]
    text = "".join(export_bibliography(project, "bibtex", scope="corpus", exclude_work_ids=hidden))
    assert text == "".join(render_bibliography(project, "bibtex", kept))
    with pytest.raises(FactoryValidationError):
        select_works(project, ids=[merge.primary], exclude_work_ids=hidden)
