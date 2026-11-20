# Gate tests: registry-driven refusal and floor (pilot 2, layer 1)

Status: unknown (not verified 2026-11-20)

Date: 2026-11-14. Scope: the first two items of layer 1 of `2026-11-14-pilot-2.md` section 3. Tests only; no product code changes. Testing is paused, so the new tests are written without being run.

## What exists (survey, 2026-11-14)

The registry holds 41 decision gates (`default_modules().gates()`). `TEAM_GATES` is computed from it.

| Question | Existing coverage |
|---|---|
| Agent-actor refusal | `test_gates_service.py::test_require_gate_refuses_agent_at_human_gate`: every gate whose registry floor is human, through `require_gate` (field `actor`, exact reason). It does not call any gate's own act. Per-service refusals are hand-written in each service's own test file (cards, notices, regions, terms, ...) and cover the services they were written for. |
| System-actor refusal | None for any gate's act. `system_actor()` appears in tests only to forge events for fold guards (`test_directions.py`, `test_experiments.py`) and to write system events. |
| Human without prerequisite | Ad hoc per service. Named in the pilot-2 plan: question without a selection (`test_decision_binding.py`), screening without a ready protocol (`test_screening_next.py`), extraction without a schema (`test_extraction_next.py`, `test_extraction_scope.py`), production mining without a passed calibration (`test_miner_calibration_guard.py`), full-text cannot-assess kept out of extraction (`test_fulltext_resolve_cannot_assess.py`). All five guards exist in code. |
| "Nothing written" asserted | Yes for the first four above (event count before and after) and for `require_gate`. The cannot-assess case asserts the extraction population, which is a read. No existing test compares the event files byte for byte. |
| Registry-driven or hand-listed | `require_gate` test and `test_gate_presets.py` are registry-driven (parametrised over the registry). The per-service refusals are hand-listed. No test fails when a gate is added without a refusal test. |
| Floor test against the slice-M table | `test_gate_presets.py::test_preset_table_is_recorded_behaviour` checks `preset(mode, gate)` for every decision gate against `EXPECTED`, a hand-written dict that is "recorded behaviour" and not the slice-M table; `test_registry_ownership.py::test_gate_floors_reproduce_the_decided_entries` checks floors for 15 gates only. Neither reads the resolved policy of a project (`effective_policy`) per mode. |

## Gaps

1. No gate's own act is attempted as an agent or as a system actor, across the registry.
2. No byte-for-byte check that a refused act leaves the event log unchanged.
3. No test fails when a new gate has no act entry.
4. No floor test that lists the slice-M table (floor, exploratory, pilot, systematic) per gate and compares it with the resolved policy of a project in each mode.

The five prerequisite cases of the pilot-2 step table are covered; they are not repeated.

## Tests to add

All in `platform/tests/`.

- `test_gate_acts_refuse_non_humans.py`
  - A table `GATE_ACTS` mapping every registry gate to a callable that attempts the gate's act through the service with a given actor (or to a marker for gates whose pilot policy is not human). A test asserts every registry gate has an entry, with a message naming the missing gate.
  - A parametrised test over the registry gates whose pilot preset is human, for an agent actor and a system actor: the call raises `FactoryValidationError`, the issues include field `actor` unless the entry is marked as checking a prerequisite first, and the event files are byte-identical before and after. A gate marked "not human in pilot" fails the test if its pilot policy has become human (the table must then be updated).
  - A parametrised test over the registry, the three modes and both actor kinds: `require_gate` refuses at every gate whose effective policy is human, field `actor`, log unchanged.
- `test_gate_floor_table.py`
  - The slice-M table written out literally (floor and the three modes per gate; gates declared after slice M listed apart as human in every mode). Tests: every registry gate is in the table; the floor equals the registry floor; `effective_policy` of a project in each mode equals the table.

Services that check a prerequisite before the actor (the target of an unknown id, no protocol, no schema) cannot show the actor refusal without a built world; their table entries are marked and assert refusal and an unchanged log only. They are reported as weak coverage.
