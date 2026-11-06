"""Adopting a reviewed region version from another project (slice 3d ruling 4; plan XL task 1).

Invariants:
- Adoption is a human act (gate `regions.adopt`) reached from the CLI only.
- The source project is opened without a write path: no event is appended to it, and its event
  files are only read. Reading it may refresh its rebuildable index, as the portfolio does.
- Only a version a human has reviewed (its latest review is `reviewed`) is adopted; the copied
  member list must hash to the version's `members_hash`. A region the source withholds from agents
  (it reaches an import's `all` part or a barred run purpose) is never adopted: its members would
  carry held-out structure into this project.
- Adoption changes no corpus count: the members are recorded, never admitted.
- A `private` source (teams-A) is read by its members alone: a person who holds no role there
  gets the refusal of an unreadable source, so a private project is not told apart from none.
- The source's blobs are read before the write lock is taken; nothing is read from the network.
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

from sqlalchemy import text

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.identity import IdGenerator
from factory.model.regions import RegionAdopted
from factory.model.screening import Channel
from factory.regions.rules import MemberType
from factory.regions.version import member_lines, members_hash
from factory.services.access import visibility
from factory.services.context import Project, open_project
from factory.services.gates import gate_issues
from factory.services.human_channel import require_human_channel
from factory.services.members import roles_of
from factory.services.regions import latest_adoptions, region_withheld

__all__ = ["adopt_region", "adoption_outdated", "open_source", "source_readable"]


def _refuse(*issues: ValidationIssue) -> FactoryValidationError:
    return FactoryValidationError(list(issues))


def source_readable(source: Project, user: str) -> bool:
    """Whether `user` may read `source`: any project not marked `private`, else a member of it."""
    return visibility(source) != "private" or bool(roles_of(source, user))


def open_source(project: Project, source_root: Path) -> Project:
    """Open the project directory `source_root` (`<root>/projects/<slug>`) as a reader, under a
    fresh session. Refused (field `source`) when it is not a project directory or is this one."""
    path = source_root.resolve()
    if path.parent.name != "projects" or not (path / "events").is_dir():
        raise _refuse(ValidationIssue("source", "source-not-a-project"))
    if path == project.paths.dir.resolve():
        raise _refuse(ValidationIssue("source", "source-is-this-project"))
    settings = project.settings.model_copy(update={"root": path.parent.parent})
    session = IdGenerator(project.clock).ulid()
    try:
        source = open_project(
            settings,
            path.name,
            session=session,
            clock=project.clock,
            principal=project.principal,
        )
        readable = source_readable(source, project.principal.user)
    except FactoryError as exc:
        raise _refuse(ValidationIssue("source", "source-unreadable")) from exc
    if not readable:
        raise _refuse(ValidationIssue("source", "source-unreadable"))
    return source


def _reviewed(source: Project, version: str) -> bool:
    with source.index.connect() as conn:
        state = conn.execute(
            text(
                "SELECT state FROM region_reviews WHERE version = :v ORDER BY event_id DESC LIMIT 1"
            ),
            {"v": version},
        ).scalar_one_or_none()
    return state == "reviewed"


def _text_of(blob: bytes) -> bytes | None:
    """The member text, normalised to plain lines, or None when a line has no known type."""
    try:
        lines = member_lines(blob)
    except (ValueError, EOFError, zlib.error):
        return None
    kinds = {m.value for m in MemberType}
    if any("\t" not in line or line.partition("\t")[0] not in kinds for line in lines):
        return None
    return "".join(f"{line}\n" for line in lines).encode()


def adopt_region(
    project: Project,
    actor: Actor,
    source_root: Path,
    version: str,
    channel: Channel = Channel.CLI,
) -> str:
    """Adopt the reviewed `version` (R@) of a region of the project at `source_root`; return the
    event id. A re-adoption of the latest adopted version writes nothing and returns the earlier
    event id. Refused with nothing written (fields `actor`, `source`, `version`, `blob`): not a
    human, an unreadable or identical source, an unknown or unreviewed version, a withheld region,
    a missing or tampered member list."""
    issues = gate_issues(project, actor, "regions.adopt")
    if actor.kind != "human" and not issues:
        issues.append(ValidationIssue("actor", "only a human adopts a region"))
    if issues:
        raise _refuse(*issues)
    source = open_source(project, source_root)
    source.index.sync()
    with source.index.connect() as conn:
        snap = (
            conn.execute(
                text(
                    "SELECT region_id, members_blob, members_hash, counts FROM region_snapshots "
                    "WHERE version = :v ORDER BY event_id DESC LIMIT 1"
                ),
                {"v": version},
            )
            .mappings()
            .first()
        )
    if snap is None:
        raise _refuse(ValidationIssue("version", "version-unknown"))
    if not _reviewed(source, version):
        raise _refuse(ValidationIssue("version", "version-not-reviewed"))
    region_id = str(snap["region_id"])
    if region_withheld(source, region_id):
        raise _refuse(ValidationIssue("version", "region-unavailable"))
    try:
        data = _text_of(source.blobs.get(str(snap["members_blob"])))
    except (FactoryError, OSError) as exc:
        raise _refuse(ValidationIssue("blob", "member-list-missing")) from exc
    if data is None or members_hash(data) != str(snap["members_hash"]):
        raise _refuse(ValidationIssue("blob", "member-list-tampered"))
    counts = {MemberType(k): int(v) for k, v in json.loads(str(snap["counts"])).items()}
    with project.writing():
        require_human_channel(project, actor, channel, "sign-off")
        for row in latest_adoptions(project):
            if (
                row["source_project"] == source.paths.slug
                and row["source_region"] == region_id
                and row["version"] == version
            ):
                return str(row["event_id"])
        payload = RegionAdopted(
            source_project=source.paths.slug,
            source_region=region_id,
            version=version,
            members_blob=project.blobs.put(data),
            members_hash=str(snap["members_hash"]),
            counts=counts,
        )
        event = project.events.make("region.adopted", payload, actor, refs=[region_id, version])
        project.record([event])
        return event.id


def adoption_outdated(project: Project) -> list[tuple[str, str]]:
    """`(adopted version, newer reviewed version)` for each adopted region whose source, read from
    the same root, now holds a later reviewed version. An unreadable source is skipped."""
    project.index.sync()
    found: list[tuple[str, str]] = []
    for row in latest_adoptions(project):
        try:
            source = open_project(
                project.settings,
                str(row["source_project"]),
                session=IdGenerator(project.clock).ulid(),
                clock=project.clock,
                principal=project.principal,
            )
            if not source_readable(source, project.principal.user):
                continue
            source.index.sync()
            with source.index.connect() as conn:
                versions = [
                    str(r[0])
                    for r in conn.execute(
                        text(
                            "SELECT version FROM region_snapshots WHERE region_id = :r "
                            "ORDER BY event_id DESC"
                        ),
                        {"r": row["source_region"]},
                    )
                ]
            newer = next((v for v in versions if _reviewed(source, v)), None)
        except FactoryError:
            continue
        if newer is not None and newer != row["version"]:
            found.append((str(row["version"]), newer))
    return found
