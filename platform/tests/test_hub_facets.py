"""Per-project hub facets (HS-60 to HS-65): the `hub.facets_set` act, the default rule and the
payloads that carry the facets."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_typed
from factory.mining.spec import EnumKind, MinerField, MinerSpec, QuoteKind, spec_to_json
from factory.model.hub_facets import FacetPick, HubFacetsSet
from factory.model.protocol import TaxonomyUse
from factory.services import hub_build as hb
from factory.services import hub_facets as hf
from factory.services import hub_payloads as hp
from factory.services import site_corpus
from factory.services.context import Project
from factory.services.mining import register_miner
from factory.services.protocol import amend_protocol, current_protocol
from tests.cli_helpers import _env
from tests.fulltext_helpers import _ft_world
from tests.helpers import SourcesFor
from tests.miner_helpers import list_miner, use
from tests.test_hub_mining import _insert_field, _insert_row, mk_spec
from tests.test_hub_ui_scope_bar import run_chromium

# The first pilot's dims as site_corpus.DEFAULT_DIMS held them before facets were per project.
OLD_DEFAULT_DIMS = (
    ("technique", "Technique", "cls", "technique_primary"),
    ("field", "Field of science", "cls", "field_primary"),
    ("data", "Data", "cls", "data_primary"),
    ("architecture", "Architecture", "cls", "architecture_primary"),
    ("evaluation", "Evaluation", "cls", "evaluation_primary"),
    ("human", "Human position", "map", "human_position"),
    ("process", "Process shape", "map", "process_shape"),
    ("span", "Automated span", "map", "automated_span"),
    ("assess", "Idea assessment", "map", "idea_assessment_method"),
    ("year", "Month", "meta", "month"),
)


def _enum(name: str, *values: str, description: str = "") -> MinerField:
    return MinerField(name, "g", EnumKind(values), description=description)


def _spec(name: str, *fields: MinerField) -> MinerSpec:
    base = mk_spec(name, 1)
    return replace(
        base,
        fields=(MinerField("topic", "g", QuoteKind(), required=True), *fields, base.fields[-1]),
        row_key_fields=("topic",),
    )


@pytest.fixture
def base(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    _ft_world(project, agent, human, mock_sources)
    return project


@pytest.fixture
def arch(base: Project, agent: Actor) -> Project:
    """Two listed miners of a project that is not the first pilot, with rows on two works."""
    list_miner(
        base,
        agent,
        _spec(
            "m-arch",
            _enum("projector", "mlp", "linear", description="How vision reaches the LLM."),
            _enum("llm_size", "small", "large"),
        ),
    )
    list_miner(base, agent, _spec("m-model", _enum("vision_input", "slice", "volume")))
    first, second = sorted(hp.load_flow_data(base).sets.included)[:2]
    for eid, work, field_, value in (
        ("a1", first, "projector", "mlp"),
        ("a2", second, "projector", "linear"),
        ("b1", first, "vision_input", "volume"),
    ):
        schema = "m-arch@1" if field_ == "projector" else "m-model@1"
        _insert_row(base, eid, work, "A", schema)
        _insert_field(base, eid, field_, value, "a quote")
    return base


def _events(project: Project) -> int:
    return len(read_typed(project.paths.events_dir, project.catalog, [hf.EVENT_TYPE]))


def test_default_is_the_enum_fields_of_listed_miners_month_last(arch: Project) -> None:
    keys = [f.key for f in hf.facets_of(arch)]
    assert keys == [
        "m-arch.projector",
        "m-arch.llm_size",
        "m-model.vision_input",
    ]
    first = hf.facets_of(arch)[0]
    assert first.label == "Projector" and first.description == "How vision reaches the LLM."
    profile = site_corpus.load_profile(arch)
    assert [d[0] for d in profile.dims] == [*keys, "year"]
    assert profile.dims[-1] == ("year", "Month", "meta", "month")
    assert [f["key"] for f in hf.facets_payload(arch)] == [*keys, "year"]


def test_default_is_breadth_first_and_bounded(base: Project, agent: Actor) -> None:
    many = tuple(_enum(f"f{i}", "a", "b") for i in range(9))
    list_miner(base, agent, _spec("m-one", *many))
    list_miner(base, agent, _spec("m-two", *many))
    list_miner(base, agent, _spec("m-three", *many))
    keys = [f.key for f in hf.facets_of(base)]
    assert len(keys) == hf.DEFAULT_MAX == 12
    # breadth first: four fields of each miner, shown miner by miner
    assert keys == [f"{m}.f{i}" for m in ("m-one", "m-two", "m-three") for i in range(4)]


def test_alike_labels_name_their_miner(base: Project, agent: Actor) -> None:
    list_miner(base, agent, _spec("m-one", _enum("scale", "a", "b")))
    list_miner(base, agent, _spec("m-two", _enum("scale", "a", "b")))
    assert [f.label for f in hf.facets_of(base)] == ["Scale (m-one)", "Scale (m-two)"]


def test_first_pilot_shape_reproduces_the_old_dims(base: Project, agent: Actor) -> None:
    # no miner listed at all: the old default, as before
    assert site_corpus.load_profile(base).dims == OLD_DEFAULT_DIMS
    classification = tuple(
        _enum(f, "x", "y") for f in ("technique_primary", "field_primary", "data_primary")
    ) + tuple(_enum(f, "x") for f in ("architecture_primary", "evaluation_primary"))
    mapping = tuple(
        _enum(f, "x")
        for f in ("human_position", "process_shape", "automated_span", "idea_assessment_method")
    )
    list_miner(base, agent, _spec("m-classification", *classification))
    list_miner(base, agent, _spec("m-mapping", *mapping))
    profile = site_corpus.load_profile(base)
    assert profile.dims == OLD_DEFAULT_DIMS
    assert profile.roles == site_corpus.DEFAULT_ROLES
    assert site_corpus.DEFAULT_ROLES == {
        "cls": "m-classification",
        "map": "m-mapping",
        "sum": "m-summary",
        "desc": "m-descriptors",
        "stages": "m-stages",
        "design": "m-design-approach",
    }
    # the payload keeps the old src and field of every dim
    dims = {d["key"]: d for d in site_corpus.corpus_payload(base)["dims"]}
    assert (dims["technique"]["src"], dims["technique"]["field"]) == ("cls", "technique_primary")
    assert (dims["human"]["src"], dims["human"]["field"]) == ("map", "human_position")
    assert (dims["year"]["src"], dims["year"]["field"]) == ("meta", "month")


def test_first_pilot_with_one_role_miner_keeps_only_its_dims(base: Project, agent: Actor) -> None:
    list_miner(base, agent, _spec("m-mapping", _enum("human_position", "x")))
    assert [d[0] for d in site_corpus.load_profile(base).dims] == [
        "human",
        "process",
        "span",
        "assess",
        "year",
    ]


def test_setting_overrides_order_and_labels_and_latest_wins(arch: Project, human: Actor) -> None:
    hf.set_facets(arch, human, [FacetPick(miner="m-model", field="vision_input")])
    hf.set_facets(
        arch,
        human,
        [
            FacetPick(miner="m-model", field="vision_input", label="Input"),
            FacetPick(miner="m-arch", field="llm_size"),
        ],
    )
    got = hf.facets_of(arch)
    assert [(f.key, f.label) for f in got] == [
        ("m-model.vision_input", "Input"),
        ("m-arch.llm_size", "Llm size"),
    ]
    assert [d[0] for d in site_corpus.load_profile(arch).dims] == [
        "m-model.vision_input",
        "m-arch.llm_size",
        "year",
    ]


def test_setting_may_name_a_pilot_field_under_its_old_key(
    base: Project, agent: Actor, human: Actor
) -> None:
    list_miner(base, agent, _spec("m-classification", _enum("technique_primary", "x")))
    hf.set_facets(
        base,
        human,
        [FacetPick(miner="m-classification", field="technique_primary", label="Method")],
    )
    assert [d[:3] for d in site_corpus.load_profile(base).dims[:1]] == [
        ("technique", "Method", "cls")
    ]


def test_non_human_actor_is_refused_and_nothing_is_written(arch: Project, agent: Actor) -> None:
    before = _events(arch)
    with pytest.raises(FactoryValidationError) as err:
        hf.set_facets(arch, agent, [FacetPick(miner="m-arch", field="projector")])
    assert err.value.issues[0].field == "actor"
    assert _events(arch) == before


@pytest.mark.parametrize(
    ("pick", "needle"),
    [
        (FacetPick(miner="m-nope", field="projector"), "not a listed"),
        (FacetPick(miner="m-arch", field="nope"), "no enum field"),
        (FacetPick(miner="m-arch", field="evidence"), "no enum field"),  # a quote field
    ],
)
def test_unknown_miner_or_non_enum_field_is_refused(
    arch: Project, human: Actor, pick: FacetPick, needle: str
) -> None:
    before = _events(arch)
    with pytest.raises(FactoryValidationError) as err:
        hf.set_facets(arch, human, [FacetPick(miner="m-arch", field="projector"), pick])
    assert needle in err.value.issues[0].reason and err.value.issues[0].field == "facets[1]"
    assert _events(arch) == before


def test_empty_and_repeated_lists_are_refused(arch: Project, human: Actor) -> None:
    before = _events(arch)
    with pytest.raises(FactoryValidationError):
        hf.set_facets(arch, human, [])
    twice = FacetPick(miner="m-arch", field="projector")
    with pytest.raises(FactoryValidationError):
        hf.set_facets(arch, human, [twice, twice])
    assert _events(arch) == before


def test_a_hand_written_event_failing_a_guard_changes_nothing(arch: Project) -> None:
    hf.set_facets(arch, arch.human_actor(), [FacetPick(miner="m-model", field="vision_input")])
    forged = arch.events.make(
        hf.EVENT_TYPE,
        HubFacetsSet(facets=(FacetPick(miner="m-arch", field="llm_size"),)),
        arch.system_actor(),
    )
    arch.record([forged])
    assert [f.key for f in hf.facets_of(arch)] == ["m-model.vision_input"]


def test_a_pick_that_no_longer_resolves_is_skipped_on_read(arch: Project) -> None:
    ghost = HubFacetsSet(
        facets=(FacetPick(miner="m-gone", field="x"), FacetPick(miner="m-arch", field="llm_size"))
    )
    arch.record([arch.events.make(hf.EVENT_TYPE, ghost, arch.human_actor())])
    assert [f.key for f in hf.facets_of(arch)] == ["m-arch.llm_size"]


def test_corpus_payload_carries_facets_values_and_descriptions(arch: Project) -> None:
    payload = site_corpus.corpus_payload(arch)
    dims = {d["key"]: d for d in payload["dims"]}
    projector = dims["m-arch.projector"]
    assert projector["src"] == "facets" and projector["field"] == "m-arch.projector"
    assert projector["description"] == "How vision reaches the LLM."
    by_id = {w["id"]: w for w in payload["works"]}
    first, second = sorted(by_id)[:2] if len(by_id) >= 2 else (None, None)
    assert len(by_id) == 2, "only the works the listed miners read are in the corpus"
    values = sorted(w["facets"]["m-arch.projector"]["v"] for w in by_id.values())
    assert values == ["linear", "mlp"]
    assert first and second


def test_shell_and_explore_payloads_carry_facets_labels_and_slot_fields(arch: Project) -> None:
    ctx = hb.HubContext(arch)
    shell = hb.build_shell(ctx)
    assert [f["key"] for f in shell["facets"]] == [
        "m-arch.projector",
        "m-arch.llm_size",
        "m-model.vision_input",
        "year",
    ]
    # the DNA slots stand for the project's first facets, labelled with its own names
    assert shell["fields"][:2] == [["technique", "Projector"], ["architecture", "Llm size"]]
    explore = hb.build_explore(ctx)
    assert explore["facets"] == shell["facets"] and explore["fields"] == shell["fields"]
    cells = ctx.role_cells("technique")
    assert sorted(v[0] for v in cells.values() if v) == ["linear", "mlp"]


def test_pilot_shell_keeps_its_four_fields_unless_the_researcher_sets_facets(
    base: Project,
) -> None:
    assert "fields" not in hb.facet_shell(base)


def test_derived_category_names_label_the_values(base: Project, agent: Actor) -> None:
    from factory.mining.derive import derive_miner
    from factory.mining.spec import MinerRegime, Population, Selector
    from factory.mining.taxonomy import Category, Dimension, TaxonomySpec, taxonomy_to_json
    from factory.services.taxonomies import register_taxonomy

    taxonomy = TaxonomySpec(
        name="t-stage",
        version=1,
        dimensions=(
            Dimension(
                "stage",
                "Stage",
                "Which stage?",
                "single",
                tuple(Category(i, i.title() + " stage", f"The {i}.") for i in ("plan", "run")),
            ),
        ),
    )
    register_taxonomy(base, base.human_actor(), taxonomy_to_json(taxonomy))
    spec = derive_miner(
        taxonomy,
        ("stage",),
        name="m-stage",
        version=1,
        selector=Selector(Population.INCLUDED_FT),
        regime=MinerRegime(),
    )
    register_miner(base, agent, spec_to_json(spec))
    current = current_protocol(base)
    assert current is not None
    amend_protocol(
        base,
        agent,
        current.spec.model_copy(
            update={
                "miners": (*(current.spec.miners or ()), use(spec)),
                "taxonomies": (TaxonomyUse(name="t-stage", version=1),),
            }
        ),
        reason="list the derived miner",
        semantic=True,
        effects={},
    )
    facet = hf.facets_of(base)[0]
    assert facet.key == "m-stage.category"
    assert facet.values == {"stage/plan": "Plan stage", "stage/run": "Run stage"}
    assert hb.facet_labels(base)["stage/plan"] == "Plan stage"


def test_payload_fingerprints_follow_the_facet_event() -> None:
    for name in ("shell", "explore", "corpus"):
        assert hb.reads(name, "hub.facets_set")
    from factory.services.site import EXPLORER_EVENTS

    assert "hub.%" in EXPLORER_EVENTS


def test_cli_sets_and_shows_the_facets(arch: Project, settings: Settings) -> None:
    runner = CliRunner()
    env = _env(settings.root)
    args = ["--project", arch.paths.slug]
    bad = runner.invoke(app, [*args, "hub", "facets", "set", "--facet", "m-arch:evidence"], env=env)
    assert bad.exit_code != 0
    ok = runner.invoke(
        app,
        [
            *args,
            "hub",
            "facets",
            "set",
            "--facet",
            "m-model:vision_input=Input",
            "--facet",
            "m-arch:llm_size",
        ],
        env=env,
    )
    assert ok.exit_code == 0, ok.output
    shown = runner.invoke(app, [*args, "hub", "facets", "show"], env=env)
    assert shown.output.splitlines() == [
        "m-model.vision_input\tInput\tm-model:vision_input",
        "m-arch.llm_size\tLlm size\tm-arch:llm_size",
    ]


@pytest.mark.browser
def test_built_corpus_page_lists_the_projects_own_miner_fields(
    arch: Project, human: Actor, tmp_path: Path
) -> None:
    import shutil

    if shutil.which("chromium") is None:
        pytest.skip("chromium is not on PATH")
    hf.set_facets(
        arch,
        human,
        [
            FacetPick(miner="m-arch", field="projector", label="Vision projector"),
            FacetPick(miner="m-model", field="vision_input"),
        ],
    )
    ui = tmp_path / "ui"
    report = hb.build_static(arch, ui)
    assert not report.errors, report.errors
    tmp = tmp_path / "run"
    tmp.mkdir()
    import html

    dom = html.unescape(run_chromium(f"file://{ui}/corpus.html", tmp))
    heads = re.findall(r'<div class="fh">(.*?)(?:<|$)', dom)
    assert "Vision projector" in heads and "Vision input" in heads
    assert "Technique" not in heads and "Field of science" not in heads
    assert re.search(r'data-d="m-arch\.projector" data-v="mlp"', dom)
    payload = json.loads((ui / "data/corpus.json").read_text(encoding="utf-8"))
    assert [d["key"] for d in payload["dims"]][:2] == ["m-arch.projector", "m-model.vision_input"]
