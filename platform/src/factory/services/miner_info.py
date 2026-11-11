"""A miner described for a person: its registered spec, its use in the protocol and its versions.

Read-only and cheap (no row is read): the spec comes from the registered blob, the use from the
current protocol. The dashboard's Miners tab and the hub's Miners product both show this.
"""

from __future__ import annotations

from typing import Any

from factory.mining.spec import spec_to_json
from factory.services import mining as mining_service
from factory.services.context import Project
from factory.services.protocol import current_protocol


def miner_detail(project: Project, name: str, version: int) -> dict[str, Any]:
    """The spec (fields with kinds and allowed values, selector, row key, evidence rule, regime),
    the protocol's use of the miner, and every registered version of the same name."""
    spec = mining_service.registered_miner(project, name, version)
    protocol = current_protocol(project)
    use: dict[str, Any] | None = None
    for u in (protocol.spec.miners or ()) if protocol else ():
        if (u.name, u.version) == (name, version):
            use = u.model_dump(mode="json")
    versions = [
        {"version": m.version, "digest": m.digest, "listed": m.listed, "proposer": m.proposer_kind}
        for m in mining_service.miner_listing(project)
        if m.name == name
    ]
    return {
        "spec": spec_to_json(spec) if spec is not None else None,
        "use": use,
        "versions": versions,
    }
