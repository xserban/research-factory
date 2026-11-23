# Runbook: the first lineage run (slice 3b) on the agentic-science pilot

Status: runbook, written 2026-11-23, not yet executed. Nothing in it has been run. Commands were checked against `platform/src/factory/cli/main.py`, `services/runner.py`, `docs/MAP.md` and the skills `rf-contributions` and `rf-lineage`; where a detail could not be verified the text says so. Ruling: `docs/design-note-serves-rq-2026-11-23.md`, part 2 (contribution passes on about ten core papers, then lineage, in separate Claude Code sessions, a dry run on a copy first; the cheaper importer from the m-summary `builds_on` rows is not built). Specification: `docs/specs/slice-3b-lineage.md`.

Notation: **[H]** is the researcher's act at the terminal or in the hub; **[A]** is a Claude Code session started by the researcher with the commands below. The platform calls no model.

## 1. Purpose and result

Fill the idea graph for the first time. The pilot has no contribution, relation or idea event, so the hub's Ideas page is empty. After this run, about ten core papers have contribution items (base idea, addition, result, limitation, each with a verified quote), relations between works are proposed from those items, and the researcher has confirmed or rejected the ones the platform could not resolve itself.

Chain, with the actor of each link:

| Step | Actor | Product |
| --- | --- | --- |
| Declare `contribution_schema` | [H] protocol amendment | schema section in the protocol |
| Pass A, pass B | [A], two sessions, two models | contribution items |
| Agreement, resolve, audit | [H] | final items |
| Lineage proposals | [A], a third session | `relation.proposed`, `idea.proposed` |
| Confirm or reject | [H] (CLI or hub) | `relation.decided`, `idea.decided` |

A relation needs a contribution item as its basis (`services/relations.py`). Its status is set by the platform: `stated` when the item's cited reference entry resolves to the proposed target, `inferred` otherwise. Only `stated` and `confirmed` edges appear in default views.

## 2. Prerequisites

1. **Runtime.** Run the CLI and every MCP server on the shared runtime worktree, never on `main` or a feature checkout: `RUNTIME=/home/obd/Documents/Projects/research-factory/.claude/worktrees/runtime`. Its commit must contain slice 3b (G2-A to G2-E) and the hub Ideas page. Check with `git -C "$RUNTIME" log -1 --format=%h` and `git -C "$RUNTIME" merge-base --is-ancestor <commit of the G2-E merge> HEAD`. The G2-E merge commit was not looked up for this runbook.
2. **Nothing else running.** No wave, hub build or miner session on the project (index rebuild guard, `docs/runbook-living.md`, "One code line per pilot").
3. **Converted full text and reference extractions** for the chosen papers. `factory document status` and `factory references status` show them. The proposed ten (Appendix A) all appear in the reference-extraction citation list at `ops/technique-trial-2026-11-14/night/shallow/cites-core.json` and in `night/core.txt` with a pinned conversion; this was read from files, not from the live index.
4. **A `contribution_schema` in the protocol.** The current protocol has none (no protocol event read for this runbook contains one). Recording is refused until it is declared (step 3). This is a human act and is the first event of the run.
5. **The ten papers are approved** by the researcher (Appendix A, 2026-11-23).
6. **Work selection by allow-list (PR #46, merged).** The contribution schema carries an optional `works` list of work ids; absent means every included work (the old behaviour). `contribution_next`, pass B, the audit, `check` and lineage all read the same restricted population, and `contribution_status` / `contribution_next` report the list (`listed`, `eligible`, `not_eligible`). `FACTORY_UNIT_CAP` and `--cap N` still apply within the list. Setting or changing the list is a protocol amendment (step 3).
7. Held-out rule: do not open `docs/pilot/heldout-seeds.md` or the project's `ops/private/`. A reflink copy of the project contains `ops/private/`; the rule applies to the copy too.

## 3. Environment (set explicitly in every shell)

The shell may carry stale `FACTORY_ROOT` and `FACTORY_PLUGIN_DIR`. Set them in each terminal and before every `claude -p`.

```
export RUNTIME=/home/obd/Documents/Projects/research-factory/.claude/worktrees/runtime
export LIVE_ROOT=/home/obd/Documents/Projects/research-factory/data
export DRY_ROOT=$HOME/Documents/research-factory-dryrun-lineage      # on /home (btrfs): reflink works
export FACTORY_PLUGIN_DIR=$RUNTIME/plugin
export PYTHONPATH=$RUNTIME/platform/src
export FACTORY_PROJECT=agentic-science

# choose one per terminal: the dry run first, the live run after it
export FACTORY_ROOT=$DRY_ROOT          # dry run
# export FACTORY_ROOT=$LIVE_ROOT       # live run

factory() { uv run --project "$RUNTIME/platform" factory "$@"; }
echo "root=$FACTORY_ROOT plugin=$FACTORY_PLUGIN_DIR"
```

`--root` and `--project` are the global options (`FACTORY_ROOT`, `FACTORY_PROJECT` are their environment forms); no command below needs another form. Print the two variables before each step of the live run; a command run with the wrong root writes to the wrong project.

## 4. Dry run on a copy

Aim: see every step, the real output of both passes and of lineage, and the cost, without a live event. The copy is discarded afterwards.

**D1 [H] Copy.**

```
cp --reflink=auto -r "$LIVE_ROOT" "$DRY_ROOT"
du -sh "$DRY_ROOT"
```

The live project is 6.3 GB; with reflink the copy is near zero until written. If `du` of the new tree reads like a full copy, stop and check the filesystem. Do not copy to `/tmp` (small tmpfs). The copy's MCP configs and the runner use `FACTORY_ROOT=$DRY_ROOT`, because `queue process` builds its MCP config from the project's settings (`runner.mcp_config`). For a hand-started session, write the config yourself (section 5, step 4).

**D2 [H] Baseline** (with `FACTORY_ROOT=$DRY_ROOT`). Time-box it: an index rebuild once hung.

```
timeout 900 factory check
factory contributions status
factory graph status
factory references status
```

Record the output. `check` before the run must show no `contribution-schema-missing` that you did not expect.

**D3 [H] Declare the schema** (section 5, step 3, same file, on the copy).

**D4 [A] Pass A**, **D5 [A] Pass B**, **D6 [H] agreement and resolution**, **D7 [A] lineage**, **D8 [H] confirmation**: the steps of section 5, on the copy.

**D9 [H] Read the output.** For each of the ten papers: `factory contributions list --work WORK_ID`; compare the quotes with the paper. Read every `inferred` relation and its note. Decide what the live run changes: schema fields, batch size, the ten papers, the models. Note the cost reported per run (`factory --project agentic-science costs`, `docs/runbook-living.md`).

**D10 [H] Discard.** After the findings are written down:

```
rm -rf "$DRY_ROOT"
```

Check `git status` of the repository and `factory --root "$LIVE_ROOT" --project agentic-science status` are untouched: the dry run writes only under `$DRY_ROOT`. Do not run `factory check` on the live project to verify this; compare `ls -l "$LIVE_ROOT"/projects/agentic-science/events/*/` timestamps instead.

## 5. Live run (and, on the copy, the dry run)

Set `FACTORY_ROOT` as in section 3. Each pass runs in its own `claude -p` process: one MCP server serves one session and its subagents, which share a session id, so subagents never give independence (`docs/ARCHITECTURE.md`, section 6).

**Step 1 [H] Pre-flight.**

```
factory check
factory contributions status
```

**Step 2 [H] Approve the ten works.** Fix the list (Appendix A) in a file `lineage-ten.txt` next to this run's notes, one work id per line. Step 3 puts exactly these ids into the schema's `works` list, so this file is the source for that amendment.

**Step 3 [H] Declare the contribution schema.** Pack `contribution` version 1; fields as in `platform/src/factory/packs/contribution.py`: `item_kind`, `absent_kind`, `name`, `statement`, `compared_to`, `cited_entry`, `metric`, `value`, `result_row`. `claims` is false for this scope; `dual_extract_sample` 1.0 makes every served work a pass B unit (None also means every work); `audit_fraction` and `audit_minimum` are the schema's own settings (defaults 0.02 and 50: with ten papers the minimum exceeds the population, so the researcher must choose a value and say why; see O4).

The amendment file has four keys, `spec`, `reason`, `semantic`, `effects`, as in `ops/screeners/amend-core-exploratory-2026-11-19.json`. `spec` is the whole current spec with one new key. The latest amendment file may be older than the live protocol (the log shows an amendment on 2026-11-20); take the spec from the live protocol and confirm it with `factory protocol show` before recording. This runbook did not verify that `protocol show --json` returns a directly reusable `spec`; if it does not, edit the latest amendment file by hand.

```
# CUR.json: the current spec in the amendment file format
jq --rawfile ids lineage-ten.txt '.spec.contribution_schema = {
      "pack": "contribution", "pack_version": 1,
      "fields": ["item_kind","absent_kind","name","statement","compared_to","cited_entry","metric","value","result_row"],
      "comparability_keys": [], "dual_extract_sample": 1.0,
      "audit_fraction": 0.2, "audit_minimum": 10, "claims": false,
      "works": ($ids | split("\n") | map(select(length>0)) | sort) }
    | .reason = "Declare the contribution schema (slice 3b) for the first lineage run on ten core papers. Criteria and screening unchanged. Researcher ruling 2026-11-23."
    | .semantic = true | .effects = {}' CUR.json > amend-contribution.json
factory protocol amend --file amend-contribution.json
factory protocol show
```

`audit_fraction` 0.2 and `audit_minimum` 10 in the snippet are placeholders for the researcher to set, not recommendations. `semantic` is true because setting `contribution_schema.works` is a field change, which the amendment rule treats as semantic (the allow-list's own tests amend with `semantic=True`); `effects` may need an entry per the command's message, so read its output. An id that does not exist is refused at the amendment; an id that exists but is not an included work with a pinned conversion is accepted and reported as `not_eligible`, so check `contribution_status` after the amendment and before pass A. Whether a review request (`--review`) is required in the project's present mode was not checked.

**Step 4 [A] Pass A**, Sonnet. The runner has a stage for it:

```
factory queue process --stage contributions --cap 10 --wait
```

The cap is the number of works the run may serve (`FACTORY_UNIT_CAP`). The run uses the skill `rf-contributions` (text embedded in the prompt), model Sonnet, only `contribution_next`, `contribution_record`, `document_read` and `project_status`, and records `runner.started` and `runner.finished` with its log in `projects/agentic-science/runs/<run_id>/`. `factory queue runs` lists runs. With the allow-list in place, the run serves only the listed works; confirm `contribution_status` shows `listed` 10 and the expected `eligible` count first.

**Step 5 [A] Pass B**, a different session and a different model (Haiku, as the evidence pass B stage `extract-b` does). The runner has no stage for contribution pass B (checked in `services/runner.py`); start it by hand. The prompt is built like the runner's: parameters, skill text, limit.

```
# one config, root and plugin dir set explicitly, cap 10
cat > "$PWD/mcp-pass-b.json" <<EOF
{"mcpServers":{"factory":{"command":"$RUNTIME/platform/.venv/bin/factory","args":["serve"],
 "env":{"PYTHONPATH":"$RUNTIME/platform/src","FACTORY_PLUGIN_DIR":"$RUNTIME/plugin",
        "FACTORY_ROOT":"$FACTORY_ROOT","FACTORY_UNIT_CAP":"10"}}}}
EOF
{ printf '%s\n' "You are pass B of stage \`contributions\` for the Research Factory project \`agentic-science\`. Work through the factory MCP tools and follow exactly the skill below (you are pass \`B\`)." \
  "Parameters for every factory call: project \`agentic-science\`, pass_label \`B\`, role \`second contributor\`, model \`claude-haiku-5-5\`, skill \`rf-contributions\`." \
  "Limit: stop after 10 units or when the queue is empty. A unit is one work read for contributions. Use no other tools. Finally print how many units you handled and any blocked text or error verbatim." \
  "=== SKILL rf-contributions ==="; cat "$RUNTIME/plugin/skills/rf-contributions/SKILL.md"; } > prompt-pass-b.txt
claude -p "$(cat prompt-pass-b.txt)" --model claude-haiku-5-5 --strict-mcp-config --mcp-config "$PWD/mcp-pass-b.json" \
  --allowedTools mcp__factory__contribution_next mcp__factory__contribution_record mcp__factory__document_read mcp__factory__project_status \
  --disallowedTools Bash Edit Write Read Glob Grep --permission-mode dontAsk --output-format stream-json --verbose > pass-b.log
```

This mirrors `runner.build_command` (flags, tool list, embedded skill) but was not executed for this runbook; the `--disallowedTools` list in the runner is `BUILTIN_TOOLS` (read the constant before relying on the abbreviation above). `$RUNTIME/platform/.venv/bin/factory` is the path in the pilot's existing `ops/screeners/factory-mcp.json`; use the same executable your pass A used. The platform refuses a session that has joined pass A, and refuses pass B the same model as pass A (as stated in the skill; the exact refusal rules are in the extraction service). The session must not be one that read pass A items, agreement, audit labels or reports.

**Step 6 [H] Agreement, resolution, audit.**

```
factory contributions status
factory contributions agreement
factory contributions resolve WORK ROW_KEY --choice a|b|neither --reason "..." [--field FIELD]
factory contributions audit sample
factory contributions audit label AUDIT_ID WORK ROW_KEY FIELD --correct|--incorrect [--note "..."]
factory contributions audit report
```

Resolve every disagreement before lineage: a base-idea or addition item still disputed between the passes is refused as a basis. Audit labels and the agreement are human acts and are not to be shown to any later agent session. `check` reports `contribution-error-ceiling` to the human view only.

**Step 7 [A] Lineage proposals**, a third session that has run no contribution, extraction or screening pass and has seen no label. The runner's `understand` stage is conductor-only; start it by hand with the same pattern as step 5: skill `rf-lineage`, model Sonnet, role `proposer`, tools `project_status`, `document_read`, `contribution_status`, `relation_list`, `relation_propose`, `idea_list`, `idea_propose` (the runner's own list for that stage), no `FACTORY_UNIT_CAP` (the stage uses a fixed cap of 1 unit, a step; for a hand run, bound the work in the prompt: "cover the base-idea and addition items of the ten works in `lineage-ten.txt` and stop"). The agent proposes; it sets no status and confirms nothing. It reports the inferred relations with their reasons.

```
factory relations list --status stated --status inferred
factory graph build
factory graph status
```

**Step 8 [H] Confirmation.** See section 6.

**Step 9 [H] Checks.** See section 7.

## 6. How the researcher confirms relations

Two routes, same service and same rule: a human act, a rationale required, applied to `inferred` relations only (`relations.decide_relation`); an agent session has no tool for it.

**CLI.**

```
factory relations list --status inferred               # id, source, target, type, reason, basis item, agent-note
factory relations confirm REL_ID --rationale "why it holds"
factory relations reject  REL_ID --rationale "why it does not hold"
factory ideas list --all
factory ideas candidates --origin WORK --name "NAME"
factory ideas confirm IDA_ID --rationale "..."
factory ideas reject  IDA_ID --rationale "..."
factory ideas merge FROM_ID INTO_ID --reason "..."      # naming variants; reversible with `ideas unmerge FROM_ID --reason`
```

**Hub, Ideas page.** Serve the hub from the runtime on the project and open the Ideas page:

```
factory site serve
```

(`factory site serve` serves on 127.0.0.1 and accepts writes only from the page it served; options were not read for this runbook, see `factory site serve --help`.) The page lists each relation with its status, its basis item's quote and anchor, who proposed it and any `agent-note`, and carries four acts, each recorded as the researcher through the CLI's authorisation:

| Page act | Same as | Event |
| --- | --- | --- |
| `/ui/act/ideas-relation-confirm` | `relations confirm` | `relation.decided` (confirm) |
| `/ui/act/ideas-relation-reject` | `relations reject` | `relation.decided` (reject) |
| `/ui/act/ideas-idea-confirm` | `ideas confirm` | `idea.decided` (confirm) |
| `/ui/act/ideas-idea-reject` | `ideas reject` | `idea.decided` (reject) |

Each takes the id and a rationale. Read the quote against the paper before confirming; an `inferred` relation is a proposal until then. For a dry run serve the copy (`FACTORY_ROOT=$DRY_ROOT`), never the live root.

## 7. What to check afterwards

```
factory check                          # expect no error; read every contribution-*, relation-*, idea-* line
factory contributions status           # units by state, items by kind, not-stated count, no-references works
factory contributions audit report     # counts and error rate, against the ceiling
factory graph status                   # nodes and edges by type and status
factory graph query no_stated_base     # included works without a stated or confirmed base, with the reason
factory graph query ancestors --node WORK --depth 3
factory trace REL_ID                   # relation to quote, anchor, document version, run, protocol, question
factory trace EXT_ID                   # the contribution item
```

`check` codes in scope: `contribution-missing-extraction`, `contribution-stale`, `contribution-schema-missing`, `contribution-closed-without-items`, `contribution-error-ceiling`, `relation-stale`, `relation-unconfirmed`, `relation-uncited-base`, `relation-without-basis` (an error), `idea-unconfirmed`, `graph-extraction-missing`. `contribution-missing-extraction` will list every included work outside the ten as a warning in pilot mode; this is expected while the run covers ten papers (see O1).

Pass criteria for the dry run (the researcher's to adjust): every accepted item has a quote that is verbatim in the paper; no `relation-without-basis`; the audit error rate is stated; at least one stated or confirmed `builds-on` edge exists between two of the ten.

## 8. Rollback

Events are append-only and are never edited or deleted. There is no undo command.

| Situation | Action |
| --- | --- |
| Dry run goes wrong | Discard the copy: `rm -rf "$DRY_ROOT"`. The live project was not written. |
| A wrong item | A new item that passes `supersedes` (objects keyed by index of the call's `items`; skill step 10). A `not-stated` item that proves wrong is superseded by the item it denied. |
| A wrong disagreement choice | A later `contributions resolve` on the same row supersedes it (not verified for this runbook; confirm with the service before relying on it). |
| A wrong relation decision | A later `relations confirm` or `reject` supersedes the earlier decision; a rejected relation stays in the log and leaves default views. Re-proposing with another basis supersedes unless a human rejected it. |
| A wrong idea | `ideas reject`; naming variants by `ideas merge`, undone with `ideas unmerge`. |
| A wrong schema | Another protocol amendment; affected rows become stale (`contribution-stale`) and are hidden from default views, never deleted. |
| A whole pass is unusable | Leave its events; start a corrected pass under an amendment. The first items stay as history. |
| Live run started on the wrong root | Stop. Do not edit files. Record the fact in `docs/pilot/log.md` and ask which events landed (`factory runs list`, the run folders). |

Never edit `events/`, the SQLite index or the run folders to repair a mistake. A rebuild of the index from the log is the only repair of a projection (`factory rebuild`; run it on the runtime and only when no other process holds the index).

## 9. Expected cost and time (estimate)

Labelled estimate, not a measurement. Basis: the pilot's run-cost baseline (`experiments/run-costs/pilot-baseline-2026-11-11.md`: 763 finished runs, mean $0.31 per run and 37.5 turns; mining units $0.02 to $0.17 each; the API-equivalent price the CLI reports, not a subscription charge), scaled up because a contribution unit reads a whole paper and writes 10 to 25 quoted items, which the baseline's mining and screening units do not. No contribution run has been measured.

| Part | Per work | For ten works |
| --- | --- | --- |
| Pass A (Sonnet) | about $0.50 to $1.50, 10 to 25 minutes | about $5 to $15, 2 to 4 hours |
| Pass B (Haiku) | about $0.20 to $0.60 | about $2 to $6 |
| Lineage (Sonnet) | n/a | about $1 to $3, about 30 to 60 minutes |
| Dry run | all of the above again | double the totals |

Researcher time is larger than agent time: agreement resolution, the audit and confirmation of inferred relations need reading quotes against papers; plan about 2 to 4 hours for ten papers. The first dry run measures the real figures: read them with `factory costs --stage contributions` (stage key and flag as in `docs/runbook-living.md`; not run).

## 10. Open points

- **O1 (resolved).** The work selector was built as an allow-list in the contribution schema (PR #46); see prerequisite 6 and step 3. Remaining caveats: `items_by_kind` still counts items recorded earlier for a work later taken off the list, and a relation source must be on the list because lineage reads the restricted population.
- **O2.** No contribution pass B stage exists in the runner (steps 5 and 7 are hand-started `claude -p` commands, unexecuted). Whether to add `contributions-b` and a lineage stage is a backlog question, not part of this run.
- **O3.** The exact pass B and lineage `claude -p` flags above mirror `runner.build_command` and were not run; the first dry run is their test.
- **O4.** Audit size: the schema's `audit_minimum` default (50) exceeds ten papers' agreed values; the value to declare, and what error rate is acceptable, are the researcher's to set. The quality bar for "agreed" with Haiku as pass B is untested.
- **O5.** Whether the amendment needs a review request in the project's current mode, and whether `semantic` is false, were not checked against the protocol service.
- **O6.** Citations resolve only for the part of the reference list G1 resolved (about 60 percent of 18,384 references at the last count in the project notes). A relation whose target is not in the corpus or not resolved is `inferred` and needs the researcher. The proposed ten were chosen from in-corpus citation edges, so most `builds-on` edges among them should resolve; the first dry run shows the real ratio.
- **O7.** Edges among the ten in the citation data come from reference extraction, not from contribution items. Whether a paper's own words state the dependence (the condition for `builds-on`) is what the passes will show; some edges in Appendix A may produce no `builds-on` item.
- **O8.** Token and time figures are estimates (section 9).
- **O9.** `factory site serve` options and the hub path of the Ideas page were not read; follow its own help.

## Appendix A. The ten core papers (proposed by the runbook author; approved one by one by the researcher on 2026-11-23)

Status: all ten approved without change. The list is kept in `ops/lineage-ten.txt` of the project (one work id per line) and is the source for the `works` list of step 3. Checked read-only on 2026-11-23: all ten are works in the live index with a live reference extraction on a converted document (docling for rows 1, 3, 4, 7; latexml-html for the others). Row 1's docling conversion yielded only 4 reference markers, so its outgoing edges will be few. Inclusion status is not checked here: `contribution_status` reports it (`eligible`, `not_eligible`) after the amendment.


Derived without running any model, from files already on disk: the 95-paper core list (`ops/technique-trial-2026-11-14/night/core.txt`), the in-corpus citation edges among core papers from reference extraction (`night/shallow/cites-core.json`, 185 edges), and the lineage statements in the technique notes and codebook (`night/codebook-ideation-v1.md`, agent-written and unverified). Selection rule: cover the research lifecycle (hypothesis generation and ranking, experiment and data analysis, review and verification, the surrounding agent systems), and make the graph non-trivial by choosing papers with citation edges among them. Titles are as printed in the technique notes.

| # | Work id | Short title | Why |
| --- | --- | --- | --- |
| 1 | `rf:gottweis2026-accelerating-scientific-discovery-71fbb6f8` | Co-Scientist: Accelerating scientific discovery with Co-Scientist | Hub of the set: cited by most of the others below (36 in-corpus citations from core papers); hypothesis generation, debate and ranking. |
| 2 | `rf:schmidgall2026-accelerating-scientific-research-34d2ee0d` | Accelerating Scientific Research with Gemini in the Real-World | The notes describe it as an extension of Co-Scientist that adds rating methods; cites AutoDiscovery in the citation data. Expected `builds-on` and `improves-on` source. |
| 3 | `rf:agarwal2025-autodiscovery-open-ended-9acf0589` | AutoDiscovery: Open-ended Scientific Discovery via Bayesian Surprise | Reward-driven hypothesis search; the base of a three-paper chain (rows 4 and 5). |
| 4 | `rf:gao2026-when-surprise-is-c3bba965` | When Surprise Is Not Enough: Validation-Aware Rewards for LLM-Guided Scientific Discovery | The notes read it as a critique of AutoDiscovery's reward: an `improves-on` candidate. |
| 5 | `rf:agarwal2026-evidence-informed-llm-dda09a7f` | Evidence-Informed LLM Beliefs for Continual Scientific Discovery | Successor of AutoDiscovery; cites Co-Scientist and Kosmos (in-corpus edges). |
| 6 | `rf:mitchener2025-kosmos-ai-scientist-51ed59b1` | Kosmos: An AI Scientist for Autonomous Discovery | Data analysis and long-running discovery; cited by 16 core papers; cites Co-Scientist. |
| 7 | `rf:keyu2025-deep-ideation-designing-90cc9416` | Deep Ideation: Designing LLM Agents to Generate Novel Research Ideas on Scientific Concept Network | Ideation from a concept network; the codebook records OmniScientist reusing it. |
| 8 | `rf:shao2025-omniscientist-co-evolving-6aa16b25` | OmniScientist: Toward a Co-evolving Ecosystem of Human and AI Scientists | Ecosystem and platform end of the lifecycle; reuses Deep Ideation (codebook); cites Co-Scientist. |
| 9 | `rf:liu2026-autoresearchclaw-self-reinforcing-9b991377` | AutoResearchClaw: Self-Reinforcing Autonomous Research with Human-AI Collaboration | Experiment execution and paper writing; contrasts Co-Scientist explicitly (codebook) and cites OmniScientist. |
| 10 | `rf:trehan2026-why-llms-aren-daa24e02` | Why LLMs Aren't Scientists Yet: Lessons from Four Autonomous Research Attempts | Review and verification, failure analysis; uses Co-Scientist as one of four reviewers (codebook). |

Citation edges among the ten, from `cites-core.json` (citing to cited, counted as listed there): agarwal2026 to gottweis2026 and to mitchener2025; mitchener2025 to gottweis2026; shao2025 to gottweis2026; liu2026 to gottweis2026 (two entries) and to shao2025; trehan2026 to gottweis2026; schmidgall2026 to agarwal2025 and to mitchener2025. Lineage statements without a citation edge in that file (Co-Scientist to schmidgall2026, AutoDiscovery to gao2026, Deep Ideation to shao2025) come from the agent-written notes and are what the contribution passes must show or fail to show. About ten distinct graph edges are expected at most; rows 7 and 4 may remain isolated if their papers do not state the dependence.

Not verified: that all ten have a current reference extraction and a pinned conversion in the live index (the files read are earlier extracts); that none is excluded or merged in the present corpus; that the included population contains them (the run takes included works at the last declared stage); the exact title strings of rows 2 and 6 beyond the notes' first lines.
