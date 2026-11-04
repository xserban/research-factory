# Iterate backlog (MVP v1 minors)

Minor review findings parked during the v1 build, to address when iterating from real use. One line each: plan/task, finding, file:line.

- seed-recall fix: recall_held_out_admitted zeroed when withheld is indistinguishable from 0 in JSON; make it int | None (services/methods.py).
- seed-recall fix: no test for merged-group found_by_search or pre-screening withholding of admitted count; overlapping active merges overwrite in _merge_groups (services/seeds.py).
