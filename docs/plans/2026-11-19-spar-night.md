# Spar features: hub chat page, Ask, agentic spar v2 and extras (plan, 2026-11-19)

Status: merged (spar-night features merged into main 2026-11-20, IDEA-88/101)

Builds on IDEA-88 v1 (merged 2026-11-19: passages, keyword and vector search, claims digest, candidates, argument sheets, `rf-chat`; decisions 139, 140) and IDEA-101. Executed as one unattended night run of about 6–7 hours. Each feature has its own branch from `main`, is built, reviewed and fixed. Nothing is merged or pushed. The researcher decides the merges in the morning.

## 1. Goal

The researcher picks papers anywhere in the hub, asks a question or names a hypothesis, and gets either an answer or the case against and for. Every sentence of it rests on a verified quote, and the researcher rates it, weighs it and writes the balance.

## 2. Rulings (researcher, 2026-11-19)

1. The hub starts headless runs through the existing runner (decision 119). The platform calls no model. Follow-ups are new runs that see the earlier sheet or answer.
2. Papers can be picked from:
   - corpus and paper lists;
   - a whole layer, with includes and excludes;
   - a paper's own page ("spar with this paper");
   - search results (keyword and vector).
3. Spar and Ask are both built now.
4. The page is built on v1 now; the agentic v2 plugs in behind the same button.
5. v2 runs as headless role sessions, roughly 10–15 sessions per spar. The roles are:
   - searcher;
   - one reader per tier-1 paper;
   - separate writers for the case against and the case for;
   - critic;
   - coverage sweep.
6. The critic's verdicts are agent events, `sheet.argument_checked`, with the values holds / overreaches / misread and a reason. The researcher's ratings are separate and decide.
7. **Lead guard:** a sheet may feed a lead only if it was run in Prepare mode, where the against and for cases are written by separate sessions.
8. **Human in the loop is central.** Agent output is a proposal. The balance of the evidence is written by the researcher (`sheet.balance_recorded`, human actor only) and never computed or judged by an agent. Every page shows the full paragraph next to a quote whenever a rating is asked.
9. Night rules:
   - one branch per feature;
   - build, review, fix;
   - targeted test files only, run one at a time, never the full suite;
   - TDD with the red run reported;
   - no merge, no push;
   - Sonnet agents, 2–3 at a time.

## 3. Features

| ID | Feature | What | Main modules | Depends |
|---|---|---|---|---|
| N1 | Claim-row links | The claims digest shows each claim's row key and version. `rf-chat` passes `claim_row_key` so every argument links to its m-claims row. The sheet view and the hub show the linked claim. | `services/claims_digest.py`, skill | — |
| N2 | Ask mode | `chat.answer_recorded` (agent), holding the question, the selection digest, and sentences, each with work, anchor and verified quote. Also `chat.answer_rated` (human: sound / weak / wrong, with a note). Includes a service, MCP tools (`answer_open/record/view/list`), `rf-chat` Ask mode, a CLI view and rating. | `services/answers.py`, `index/answers.py`, skill | — |
| N3 | Runner stages `spar` and `ask` | Adds the stages `spar` and `ask` to `runner.STAGES`: skill `rf-chat`, the chat tool allow-list, model Sonnet, one unit per run. The request (selection spec, hypothesis or question, mode, earlier sheet or answer id) is passed as a recorded request (`chat.requested`, human) that the run reads with `chat_request_next`. The first version runs a single request per run. | `services/runner.py`, `services/chat_requests.py` | N2 |
| N4 | Balance and lead guard | `sheet.balance_recorded` (human only: free text plus optional lean against / mixed / for) and the lead guard: `lead_record` refuses to cite a sheet unless its mode is Prepare and both sections are closed. | `services/sheets.py`, `services/leads.py` (or wherever `lead_record` lives) | — |
| N5 | Hub chat page | A new hub v2 page `chat`:<ul><li>a basket with the four sources from ruling 2, kept in hash state;</li><li>a Spar / Ask form and live progress from Activity;</li><li>the sheet or answer, with full paragraphs;</li><li>rating and the written balance in the browser, through allow-listed write routes as researcher acts (`hub_serve` auth seam);</li><li>a list of earlier sheets and answers.</li></ul>Basket entry points go on the corpus, paper and search pages. | `hub_ui/pages/chat.*`, `services/hub_chat.py`, `hub_serve` routes | N2–N4 |
| N6 | Agentic spar v2 | A coordinator (skill `rf-spar-v2` plus a runner path) launches the role sessions in ruling 5 as separate `claude -p` processes, each with its own MCP session. It also adds the event `sheet.argument_checked`, a `readers` table of what each reader covered, and a coverage-sweep summary. Prepare mode uses separate writer sessions. The hub button picks v1 or v2. | `services/spar_v2.py`, `services/runner.py`, `plugin/skills/rf-spar-v2/`, events | N3 |
| N7 | Living sheets | A sheet becomes stale when the selection digest or the claims rows of its papers change (computed, no event). A "re-spar" request links the new sheet to the old one. A sheet diff shows arguments added, dropped and kept (matched by work and anchor), plus rating carry-over shown as a suggestion only. | `services/sheet_diff.py`, hub page | N3, N5 |
| N8 | Sheet export | A sheet or answer becomes a Markdown brief, and PDF through the existing export path if one exists. It contains the hypothesis, the researcher's balance first, the arguments with quotes and paragraphs, the ratings, and full references from the bibliography. A CLI `factory sheets export` and a hub button. | `services/sheet_export.py` | N4 |
| N9 | Precision panel | Ratings summarised, all counts computed: sound / weak / wrong by stance, source (claims, keyword, vector, researcher), strength, model, role (v2) and critic verdict against researcher rating (agreement). It is a section of the chat page and a CLI. | `services/spar_metrics.py` | N2, N6 for roles |
| N10 | Contradiction map | Contradiction pairs come from the claims digest, through a skill mode where an agent proposes pairs with two verified quotes via the existing `contradiction_propose`, and the researcher decides as today. The map is a hub view of the decided and proposed pairs by topic; a pair can seed a spar. | `services/finders.py` (reuse), hub view, skill | N5 for the seed button |

## 4. Order (waves, 2–3 agents at a time)

0. Running from the day: `empty-gold`, `mining-speed`.
1. N1, N2, N4.
2. N3, then N5 and N10's back end.
3. N6.
4. N7, N8, N9.

Each feature then gets a review (BLOCKER / SHOULD-FIX / MINOR) and a fix round.

## 5. Conflicts known in advance

- **Index version.** Each branch that adds events raises `PROJECTION_VERSION` to 89 on its own branch. At merge the versions are renumbered in the merge commit: 89, 90, … in merge order (lesson of 2026-11-19).
- **Decision numbers.** These are proposed as `N-<id>` placeholders and numbered at merge.
- **Shared files.** `mcp/server.py`, `services/access.py`, `docs/MAP.md` and `docs/backlog.md` are resolved at merge.

## 6. What must hold

- The platform calls no model. Runs are outside `claude -p` processes started by the runner.
- Every agent event carries model, skill version and `input_blob`. Researcher acts are human events, and only humans can write them, enforced in both the service and the projection.
- Quotes are verified against the pinned conversion, and paragraphs are shown with them.
- Counts are computed, never typed. No agent writes a verdict or a balance.
- Held-out handling follows decision 37.9.
