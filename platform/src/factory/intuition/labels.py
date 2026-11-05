"""Labels of the intuition layer (spec ruling 7, plan ruling A9): the class token is always
`interpretation`, with the review state as a second token."""

from __future__ import annotations

from factory.model.intuition import ReviewState

LAYER_CLASS = "interpretation"
_VISIBLE = frozenset({ReviewState.UNREVIEWED, ReviewState.REVIEWED})


def layer_label(state: str) -> str:
    return f"{LAYER_CLASS} · {state}"


def interpretation_visible(state: ReviewState) -> bool:
    """Shown by default: `unreviewed` and `reviewed`; `wrong` and `superseded` are hidden."""
    return state in _VISIBLE
