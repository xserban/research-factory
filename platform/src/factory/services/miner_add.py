"""Add a miner in one step from one declarative file (IDEA-51).

The file is JSON: `{"spec": <miner spec>, "use": {...}, "reason": "..."}`; a bare miner spec (a
file with a top-level `fields`) is accepted and takes the defaults. `use` holds the protocol use's
settings (`dual_extract_sample`, `audit_fraction`, `audit_minimum`, `imports`, `layers`,
`on_demand`, `order`); `dual_extract_sample` defaults to 1.0 (every work twice). `evidence` is
refused here, since admitting a miner as evidence is the researcher's act after a passed
calibration (`admit_miner`).

Invariants:
- Never calls a model and judges nothing about the miner's content.
- The spec, the use and the actor are validated before anything is written; invalid input writes
  nothing. Registration comes first and is idempotent; the listing is a protocol amendment (one
  event) written only if the registration succeeded. If the amendment is then refused (for
  example the protocol is not ready), the registration stays and a second call lists it.
- Adding again writes nothing (`registered` and `listed` are False). A use of the same miner name
  at another version is replaced by the new version's use (the protocol holds one use per name).
- `check_only` runs the same validation and reports what would be written, writing nothing.
- The listing amendment is semantic (it changes the protocol's miners section).
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import JsonValue, ValidationError

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.mining.compile import miner_digest
from factory.mining.spec import MinerSpec, spec_from_json
from factory.mining.validate import validate_miner
from factory.model.base import StrictModel
from factory.model.miners import MinerUse
from factory.model.protocol import ProtocolStatus
from factory.services.context import Project
from factory.services.mining import _taxonomy_issues, register_miner, registered_row
from factory.services.protocol import amend_protocol, current_protocol

__all__ = ["MinerAdded", "add_miner"]

_USE_KEYS = (
    "dual_extract_sample",
    "audit_fraction",
    "audit_minimum",
    "imports",
    "layers",
    "on_demand",
    "order",
)


class MinerAdded(StrictModel):
    """What `add_miner` did (or, with `checked_only`, would do)."""

    name: str
    version: int
    digest: str
    registered: bool
    listed: bool
    replaced_version: int | None
    page: str
    hub_page: str
    checked_only: bool


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _parse(document: JsonValue) -> tuple[JsonValue, Mapping[str, JsonValue], str | None]:
    if not isinstance(document, dict):
        raise _refuse("document", "must be a JSON object")
    if "spec" in document:
        spec = document["spec"]
        use = document.get("use", {})
        reason = document.get("reason")
        extra = sorted(set(document) - {"spec", "use", "reason"})
        if extra:
            raise _refuse("document", f"unknown key: {', '.join(extra)}")
    elif "fields" in document:
        spec, use, reason = document, {}, None
    else:
        raise _refuse("spec", "the file needs a `spec` (or is a bare miner spec with `fields`)")
    if not isinstance(use, dict):
        raise _refuse("use", "must be an object")
    if reason is not None and not isinstance(reason, str):
        raise _refuse("reason", "must be text")
    return spec, use, reason


def _use(spec: MinerSpec, settings: Mapping[str, JsonValue]) -> MinerUse:
    issues: list[ValidationIssue] = []
    for key in settings:
        if key == "evidence":
            issues.append(
                ValidationIssue("use.evidence", "admitting a miner as evidence is a separate act")
            )
        elif key not in _USE_KEYS:
            issues.append(ValidationIssue(f"use.{key}", "not a setting of a miner's protocol use"))
    if issues:
        raise FactoryValidationError(issues)
    try:
        # default: every work mined twice, as pilot and systematic modes need a dual fraction
        full: dict[str, JsonValue] = {"dual_extract_sample": 1.0, **settings}
        return MinerUse.model_validate({"name": spec.name, "version": spec.version, **full})
    except ValidationError as error:
        raise FactoryValidationError(
            [
                ValidationIssue("use." + ".".join(str(p) for p in e["loc"]), e["msg"])
                for e in error.errors()
            ]
        ) from error


def add_miner(
    project: Project,
    actor: Actor,
    document: JsonValue,
    *,
    reason: str | None = None,
    check_only: bool = False,
) -> MinerAdded:
    """Validate, register and list the miner `document` describes; return what was done.

    Refused, with nothing written: for a system actor (`actor`); a malformed file (`document`,
    `spec`, `use`, `reason`); a spec of the wrong shape or meaning or with a bad taxonomy
    reference (as `register_miner`); a use setting that is unknown or invalid, or `evidence`
    (`use.<name>`); a protocol that is not ready (`protocol`). `reason` overrides the file's."""
    if actor.kind == "system":
        raise _refuse("actor", "an agent or a human adds a miner")
    raw_spec, settings, file_reason = _parse(document)
    spec = spec_from_json(raw_spec)
    issues = validate_miner(spec) + _taxonomy_issues(project, spec)
    if issues:
        raise FactoryValidationError(issues)
    use = _use(spec, settings)
    protocol = current_protocol(project)
    if protocol is None or protocol.status is not ProtocolStatus.READY:
        raise _refuse("protocol", "the protocol is not ready; record it ready first")
    digest = miner_digest(spec)
    existing = registered_row(project, spec.name, spec.version)
    if existing is not None and existing.digest != digest:
        raise _refuse(
            "version",
            f"{spec.name} version {spec.version} is registered with another digest; "
            "a change is a new version",
        )
    uses = tuple(protocol.spec.miners or ())
    already = any((u.name, u.version) == (spec.name, spec.version) for u in uses)
    replaced = next((u.version for u in uses if u.name == spec.name and not already), None)
    page = f"miners/{spec.name}.html"
    result = MinerAdded(
        name=spec.name,
        version=spec.version,
        digest=digest,
        registered=existing is None,
        listed=not already,
        replaced_version=replaced,
        page=page,
        hub_page=f"/p/{project.paths.slug}/{page}",
        checked_only=check_only,
    )
    if check_only:
        return result
    register_miner(project, actor, raw_spec)
    if not already:
        kept = tuple(u for u in uses if u.name != spec.name)
        why = (reason or file_reason or "").strip() or (
            f"list miner {spec.name} version {spec.version}"
        )
        amend_protocol(
            project,
            actor,
            protocol.spec.model_copy(update={"miners": (*kept, use)}),
            reason=why,
            semantic=True,
            effects={},
        )
    return result
