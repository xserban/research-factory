# Provenance

The skills in this plugin adapt the research-factory-old stage documents. Commit of the source:
`7a0b682efe514273892bd9db3501337bd34b041c` (`git -C ~/Projects/research-factory-old rev-parse HEAD`).

| Skill | Source documents (vendored copies under `docs/reference/research-factory-old-spec/`, taken from research-factory-old at the SHA above) |
| --- | --- |
| `rf-frame` | `docs/reference/research-factory-old-spec/stages/00-frame.md`, `01-scope.md` (sections on slots and non-goals), `RIGOR-MODES.md` |
| `rf-probe` | `docs/reference/research-factory-old-spec/stages/01-scope.md` (seeds, probe, recall, routing) |
| `rf-protocol` | `docs/reference/research-factory-old-spec/stages/02-protocol.md`, `RIGOR-MODES.md` (amendments and deviations) |

The adaptation replaces the old `rf` commands with the factory MCP tools and CLI steps. The
rules and thresholds are kept from the source; the procedure is rewritten for the event model.

`rf-living` is written for this platform (slice 4b, plan living-D) and has no counterpart in the
old stage documents: it describes how a scheduled agent session runs the due watch cycles and
delivers the computed digest, and which acts remain the researcher's. Its reference is the hash
computed by the platform from the installed file.
