Q1. index/screening.py (handler `_decision`), table `decisions`.
Q2. (a) bump PROJECTION_VERSION in index/default.py; (b) add table to OMITTED_WHEN_EMPTY in index/index.py. (Bonus: ownership in services/modules/<m>.py.)
Q3. services/skills.py (`skill_ref`); `name@<first 8 hex of sha256 of SKILL.md>`.
Q4. Gate `writing.release`; pilot preset = agent; modules/presets.py.
Q5. Module `screening`; the notices projection (index/notices.py).
Q6. 30 minutes; TASK_LEASE in model/task.py.
Q7. Index._sync (index/index.py) -> _rebuilt when: no db file / no stored meta; projection version differs; a known session file is missing; a file shrank below its offset; a new event sorts before the last applied event. (Score: >=3 of 5 = full.)
Q8. require_gate (also gate_issues), services/gates.py.
Q9. screen_next; services/screening.py.
Q10. services/withholding.py, `withhold` (with held_out_tokens); applied in mcp/server.py `_reply` (via `_withheld` / `_held_out_tokens`).
Q11. Docling; document/registry.py (`default_converters`, decision 49).
Q12. ProtocolAmended in model/protocol.py.
Q13. rf-run; project_status.
Q14. model/work_ids.py, `work_id`.
Q15. tests/test_forged_events.py, tests/test_experiments_forged.py, tests/test_literature_forged.py (any 2 = full).
