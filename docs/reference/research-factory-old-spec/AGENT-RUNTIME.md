# The Agent Runtime

> **The `rf` CLI never calls a model. The agent in your editor is the runtime.**

Stages 00, 02, 04, 06 and 08 need judgment. Nothing in `src/rf/` will ever hold an API key,
import a model SDK, or make an inference call. Judgment happens in Copilot or Claude Code;
Python does I/O, validation and counting; **files are the interface between them.**

```
   Copilot / Claude Code          judgment: framing, criteria, verdicts, claims
            ↕  reads task files, writes answer files, runs CLI verbs
        rf CLI                    I/O, schema validation, counting, gates
            ↕
      the repository              artifacts — the only shared state
```

## Three kinds of command

Conflating these is what makes "agentic pipeline" architectures confusing, so they are kept
visibly distinct.

| Kind | Example | Who runs it | Model involved? |
| --- | --- | --- | --- |
| **Script verb** | `rf search --run`, `rf dedup`, `rf prisma` | you or the agent | no, ever |
| **Agent skill** | `/rf-frame`, `/rf-protocol`, `/rf-screen` | the agent, following a markdown SOP | yes — whichever model your editor is using |
| **Bridge verb** | `rf frame --write`, `rf screen --next`, `rf screen --record` | the agent, to read work in and write answers back | no — it validates, it does not think |

`rf frame` is not a program that interviews you. The **skill** interviews you; `rf frame
--write framing.yaml` is what validates the result, hashes it, and mints `Q@<sha>`.

## The pattern: paired verbs

Every judgment stage is a loop between two verbs — one hands work out, one takes answers back.

```bash
$ rf screen --next --batch 25 --pass A
Wrote .rf/tasks/screen-A-0007.md   (25 records, criteria P@d4e5f6 embedded)
```

The agent reads that file, applies the criteria, writes verdicts, then:

```bash
$ rf screen --record .rf/tasks/screen-A-0007.answers.yaml
✓ 25 verdicts recorded (D1204–D1228)
✗ rejected 1: criterion "EX09" does not exist in P@d4e5f6
✗ rejected 1: verdict "exclude" with no criterion cited
23 accepted · 2 returned for correction
```

**Validation at the boundary is the whole point.** An agent can invent a criterion ID, cite a
version that does not exist, or exclude something without a reason. The CLI rejects all three
before they reach the decision log. The contract is enforced by the gate, not by the prompt —
which matters, because prompts are advisory and schemas are not.

## What this architecture buys

**No credentials in the project.** Clone it, and there is nothing to configure and nothing to
leak. The only secrets `rf` knows about are an optional NCBI key and a contact email, both
read from the environment.

**Model diversity for free — and it is load-bearing.** Stage 04 requires two *independent*
screening passes, and the strongest available decorrelation is running them on different
models. Copilot's model picker provides exactly that. An architecture that called one API
would have to pay for a second vendor to get what this gets by default.

**Auditability.** Task files and answer files are artifacts on disk. When a verdict looks
wrong six months later, the exact input the agent saw is still there.

**Portability.** The same verbs work in Copilot, in Claude Code, and for a human typing YAML
by hand. That last case is not a joke: it is the fallback when a stage is too subtle to
delegate, and it costs nothing to support because the interface is a file.

## The honest limitation: scale

2,904 records × 2 passes is ~5,800 judgments. Through a chat window, that is not viable, and
no amount of architecture makes it so. What varies is how autonomously the loop can run:

| Harness | Screening loop |
| --- | --- |
| **Claude Code** | genuinely autonomous — the agent runs `rf screen --next`, judges, runs `rf screen --record`, repeats until the queue is empty |
| **Copilot agent mode** | can run terminal commands, so the same loop works; less reliable over long unattended runs |
| **Copilot chat** | manual batches. Fine for a few hundred records, painful beyond that |

The artifacts are identical in all three. Only the babysitting differs.

Two honest consequences:

- **`exploratory` mode exists partly for this reason.** Single-pass screening halves the cost,
  and the trade it names — *fewer records screened well* over *more records screened alone* —
  is the right one when the loop is manual.
- **Narrow the question rather than dropping the second pass.** Stage 01 reports the expected
  screening burden in hours precisely so this decision happens before the work, not during it.

### The escape hatch, if it is ever wanted

If unattended bulk screening becomes necessary, the shape is already there:

```bash
rf screen --via 'claude -p'        # or any command that takes a prompt on stdin
```

That shells out to a CLI **you** already have, authenticated as you, with no SDK dependency
and no key stored in the project. It is not built, and nothing depends on it. It is noted only
so that the current design is a choice rather than a corner.

## Skills

The SOPs live in `.github/skills/rf-*/SKILL.md`, alongside the ones already installed. Each
one says what to read, what to decide, which bridge verb to call, and what the gate will
reject — so a skill is closer to a job description than a prompt.

| Skill | Reads | Writes via |
| --- | --- | --- |
| `rf-frame` | your answers | `rf frame --write` |
| `rf-probe` | probe counts, harvested terms | `rf probe --write` |
| `rf-protocol` | question slots, non-goals, seeds | `rf protocol --write` |
| `rf-screen` | `rf screen --next` task files | `rf screen --record` |
| `rf-extract` | normalised full text | `rf extract --record` |
| `rf-synthesize` | the wiki and claim graph | `rf synth --write` |

They compose the skills you already have rather than replacing them — `clarifying-questions-first`
for the framing interview, `scientific-critical-thinking` for appraisal, `markitdown` for
full-text conversion.

## What this means for `rf frame` in the workflow

`spec/WORKFLOW.md` shows `rf frame` as though it were a single command. Read it as shorthand:
you invoke the **skill**, the agent interviews you, and the bridge verb commits the result.
The user-visible sequence is unchanged; what changes is that no part of it needs a key.
