"""The registry of the built modules, in declaration order (slice M, decision 55).

Invariants:
- Built once, from the production event catalog and the production projection's tables, so the
  ownership checks run against what exists.
- A plan that adds an event type, table, task kind, protocol section, check code or gate adds it
  to the declaration of the module that owns it; construction fails otherwise.
"""

from functools import lru_cache

from factory.events.catalog import default_catalog
from factory.index.default import default_projection
from factory.modules.registry import ModuleRegistry
from factory.services.modules import (
    cards,
    contradictions,
    contributions,
    conversion,
    core,
    coverage,
    dedup,
    discovery,
    evidence,
    exports,
    extraction,
    finders,
    fulltext,
    imports,
    inbox,
    intuition,
    lineage,
    living,
    matching,
    portfolio,
    references,
    retrieval,
    scoping,
    screening,
    snapshots,
    vocabulary,
)


@lru_cache(maxsize=1)
def default_modules() -> ModuleRegistry:
    """Every module of the platform. The order is the order `methods` and `factory modules` list
    them; `check` reports in rule order, which `CheckHit.seq` carries."""
    modules = [
        core, scoping, retrieval, dedup, screening, fulltext, conversion, extraction,
        contributions, cards, evidence, references, imports, inbox, living, snapshots, lineage,
        intuition, vocabulary, contradictions, discovery, coverage, finders, matching, exports,
        portfolio,
    ]  # fmt: skip
    return ModuleRegistry(
        [m.MODULE for m in modules],
        catalog_names=default_catalog().names(),
        table_names=list(default_projection().metadata.tables),
    )
