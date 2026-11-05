# ruff: noqa: F401, F811
"""The `factory labels`, `terms` and `consolidation` commands (slice 3d, plan Regions-C, task 5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.regions.rules import MemberType
from factory.services.context import Project
from factory.services.import_resolve import resolve_import
from factory.services.labels import labels_of
from tests.cli_helpers import _env
from tests.import_helpers import admission_records, admit_lookups, bib_entry, import_bib
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, screened, world

runner = CliRunner()


def run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_labels_commands(settings: Settings, project: Project, iw: IWorld) -> None:
    root = settings.root
    code, out, err = run(root, "labels", "apply", "Performer", "--target", iw.source)
    assert code == 0, err
    first = out.split()[-1]
    assert first.startswith("lbl_")
    assert run(root, "labels", "apply", "FAVOR+", "--target", iw.source)[0] == 0
    code, _, err = run(root, "labels", "apply", "x" * 61, "--target", iw.source)
    assert code == 1 and "over-60-characters" in err
    code, out, _ = run(root, "labels", "list")
    assert "'performer'" in out and "'favor+'" in out and "class organisation" in out
    code, out, err = run(root, "labels", "merge", "performer", "favor+", "--reason", "same method")
    assert code == 0, err
    merge_event = out.strip().split()[-1]
    code, out, _ = run(root, "labels", "list", "--key", "performer")
    assert "-> 'performer'" in out
    code, _, err = run(root, "labels", "merge", "favor+", "performer", "--reason", "back")
    assert code == 1 and "merge-cycle" in err
    assert run(root, "labels", "unmerge", merge_event, "--reason", "undo")[0] == 0
    assert run(root, "labels", "withdraw", first, "--reason", "mistaken")[0] == 0
    assert [v.key for v in labels_of(project, MemberType.WORK, iw.source)] == ["favor+"]
    code, _, err = run(root, "labels", "withdraw", first, "--reason", "again")
    assert code == 1 and "already-withdrawn" in err


def test_confirm_and_reject(settings: Settings, project: Project, iw: IWorld) -> None:
    from factory.services.labels import LabelInput, apply_labels

    root = settings.root
    [one, two] = apply_labels(
        project,
        iw.writer,
        [
            LabelInput(target_type=MemberType.WORK, target=iw.source, text="kernel"),
            LabelInput(target_type=MemberType.WORK, target=iw.source, text="softmax"),
        ],
    ).written
    assert run(root, "labels", "confirm", one)[0] == 0
    assert run(root, "labels", "reject", two)[0] == 0
    _, out, _ = run(root, "labels", "list")
    assert "'kernel'" in out and "confirmed" in out and "'softmax'" not in out


def test_terms_commands(settings: Settings, project: Project, iw: IWorld) -> None:
    root = settings.root
    for target in (iw.source, iw.other, iw.third):
        assert run(root, "labels", "apply", "performer", "--target", target)[0] == 0
    code, out, _ = run(root, "terms", "suggest")
    assert "'performer'  3 targets" in out
    code, out, err = run(
        root,
        "terms",
        "promote",
        "Performer",
        "--definition",
        "A random-feature attention.",
        "--applies-to",
        "work",
        "--alias",
        "favor+",
    )
    assert code == 0, err
    term = out.split()[-1]
    code, out, _ = run(root, "terms", "list")
    assert term in out and "3 confirmed" in out and "aliases: favor+" in out
    assert (
        "(none)" not in run(root, "terms", "suggest")[1]
        and "0 suggestion" in run(root, "terms", "suggest")[1]
    )
    code, _, err = run(
        root, "terms", "promote", "favor+", "--definition", "d", "--applies-to", "work"
    )
    assert code == 1 and "key-taken" in err
    code, _, err = run(
        root,
        "terms",
        "revise",
        term,
        "--name",
        "Performer",
        "--definition",
        "Revised.",
        "--applies-to",
        "work",
    )
    assert code == 0, err
    assert "v2" in run(root, "terms", "list")[1]
    assert run(root, "terms", "retire", term, "--reason", "folded")[0] == 0
    assert "0 term(s)" in run(root, "terms", "list")[1]
    assert term in run(root, "terms", "list", "--retired")[1]


def test_consolidation_commands(settings: Settings, project: Project, iw: IWorld) -> None:
    root = settings.root
    for text in ("Performer", "FAVOR+"):
        for target in (iw.source, iw.other, iw.third):
            assert run(root, "labels", "apply", text, "--target", target)[0] == 0
    code, out, _ = run(root, "consolidation", "status")
    assert "due: no" in out and "open pass: -" in out
    code, out, err = run(root, "consolidation", "start")
    assert code == 0 and "cluster(s)" in out, err
    pass_id = out.split()[1].rstrip(":")
    assert run(root, "consolidation", "start")[0] == 1
    code, out, _ = run(root, "consolidation", "list")
    rows_ = [line.split() for line in out.splitlines() if "undecided" in line]
    index = {r[1]: r[0] for r in rows_}  # kind -> cluster index
    assert "label  undecided  favor+, performer" in out and set(index) == {"label", "idea"}
    code, _, err = run(root, "consolidation", "complete", pass_id)
    assert code == 1 and "undecided:2" in err
    code, out, err = run(
        root,
        "consolidation",
        "decide",
        pass_id,
        index["label"],
        "merge",
        "--into",
        "performer",
        "--reason",
        "same method",
    )
    assert code == 0, err
    assert "-> 'performer'" in run(root, "labels", "list")[1]
    keep = ("consolidation", "decide", pass_id, index["idea"], "keep", "--reason", "distinct")
    assert run(root, *keep)[0] == 0
    assert run(root, "consolidation", "complete", pass_id)[0] == 0
    assert "open pass: -" in run(root, "consolidation", "status")[1]


def test_import_resolve_applies_tags(
    project: Project,
    corpus: None,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factory.services.dedup import canonical_works

    doi = next(w.identifiers.doi for w in canonical_works(project) if w.identifiers.doi)
    entries = admission_records(str(doi))
    entries[0] = entries[0].replace("}\n", ", keyword={sedge; mapping}}\n", 1)
    imp = import_bib(project, tmp_path, entries)
    monkeypatch.setattr("factory.cli.main.default_sources", admit_lookups().sources)
    code, out, err = run(settings.root, "import", "resolve", imp)
    assert code == 0, err
    assert "tags applied as labels: 2" in out
    again = run(settings.root, "import", "resolve", imp)[1]
    assert "tags applied" not in again  # idempotent: the tags are already labels
    _, listed, _ = run(settings.root, "labels", "list")
    assert "'sedge'" in listed and "'mapping'" in listed and "import-tag" in listed
