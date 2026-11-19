"""DB-3: the old per-tab help paragraphs reach the `methods` of the matching payloads."""

from __future__ import annotations

from factory.services import (
    dashboard_page,
    hub_costs,
    hub_mining,
    hub_protocol,
    hub_screening,
    hub_sources,
)
from factory.services.hub_tab_help import TAB_HELP

_TARGETS = {
    "protocol": (hub_protocol.METHODS, "tab_protocol"),
    "decisions": (hub_protocol.METHODS, "tab_decisions"),
    "press": (hub_protocol.METHODS, "tab_press"),
    "probes": (hub_protocol.METHODS, "tab_probes"),
    "search": (hub_sources.METHODS, "tab_search"),
    "conversion": (hub_sources.METHODS, "tab_conversion"),
    "screening": (hub_screening.METHODS, "tab_screening"),
    "miners": (hub_mining.METHODS, "tab_miners"),
    "cost": (hub_costs.METHODS, "tab_cost"),
}


def test_every_ported_tab_is_in_its_payload_methods() -> None:
    for tab, (methods, key) in _TARGETS.items():
        assert methods[key] == TAB_HELP[tab], tab


def test_text_is_verbatim_from_the_old_dashboard() -> None:
    src = dashboard_page.PAGE
    for tab, text in TAB_HELP.items():
        old = text.replace("’", "\\u2019")
        assert old in src, tab
