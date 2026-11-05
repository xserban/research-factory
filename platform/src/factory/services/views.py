"""The common header of the views and their canonical JSON (slice 7b, plan V-A).

Invariants:
- `as_of` is the id of the last event the projector applied, so two builds from the same log
  carry the same header; it does not scan the projection (spec ruling 1).
- `to_json` is deterministic: sorted keys, compact separators, one trailing newline.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from factory.model.base import StrictModel
from factory.model.views import ViewMeta, ViewNotice
from factory.services.context import Project


def view_meta(
    project: Project,
    view: str,
    version: int,
    flt: Mapping[str, JsonValue],
    *,
    truncated: bool = False,
    notices: Sequence[ViewNotice] = (),
) -> ViewMeta:
    return ViewMeta(
        view=view,
        version=version,
        project=project.paths.slug,
        as_of=project.index.head(),
        filter=dict(flt),
        truncated=truncated,
        notices=list(notices),
    )


def to_json(model: StrictModel) -> str:
    dumped = model.model_dump(mode="json")
    return json.dumps(dumped, sort_keys=True, separators=(",", ":")) + "\n"
