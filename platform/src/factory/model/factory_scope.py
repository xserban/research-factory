"""The factory event scope's reserved slug and allow-list (decision 169, proposed).

General reactions and the general feed ranker belong to the researcher, not to one project, so they
live in a log of their own at `<root>/factory/`, laid out as a project directory. This module is
pure: the names only. `services/factory_scope.py` writes the log and `index/factory_scope.py`
folds it.

Invariants:
- `_factory` is the envelope `project` of that log. It cannot match the project slug pattern, so
  no project can take it; the services also name it in their refusal.
- Only the `feed.*` types below may be written to it; any other type is refused at the boundary.
"""

FACTORY_SLUG = "_factory"
FACTORY_DIR = "factory"
FACTORY_EVENT_TYPES: tuple[str, ...] = ("feed.reacted", "feed.ranked", "feed.ranker_trained")
