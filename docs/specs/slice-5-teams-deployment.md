# Slice 5 — Teams and deployment

Status: draft — rulings recommended; awaiting the researcher's review before any build.

Builds on [00-system.md](00-system.md), slices 1, 2 and 3a–3c; must satisfy [01-rigour.md](01-rigour.md) R-01, R-04, R-05, R-13, R-20, R-32, R-33, R-36, R-37, R-39, R-47, R-51, plus the proposed requirements below. Implements the slice-5 row of [README.md](README.md) and backlog IDEA-11 (roles, ownership, review), IDEA-12 (human–human and human–agent screening teams) and IDEA-13 (contribution ledger); answers 00-system §11 open questions 1 (sharing the library) and 2 (identity of humans); realises deployment stage 1 of [../04-architecture.md](../04-architecture.md) §8 and the build implications of [../06-teams.md](../06-teams.md).

**Depends on:** [slice-M-modules.md](slice-M-modules.md) (stage-module contract, gate policies, shared mining layer). Every part of this slice is valid before slice M lands: team gates are a hand-written table (`TEAM_GATES`, ruling 14) and the shared library holds documents only (ruling 18). When slice M lands, `TEAM_GATES` becomes the role dimension of each module's gate policy, and the shared mining store adopts this slice's visibility and access rules unchanged.

## Goal

Let a lab of several researchers and their agents work in shared projects on one server, with every act attributed to an authenticated person, every tool call authorised by a declared role, independence rules (decision 37) enforced across people as well as sessions, credit and AI assistance derived from events, agent work bounded by declared budgets, and literature stored once per lab. The platform still never calls a model, and events stay append-only with one writer per file.

Pilot for acceptance: **two researchers (A: methods, B: application) and the PI** share one project on a lab server; A and B each run Claude Code against the remote connector; a human–agent screening pair (B as pass A, an agent as pass B) and an agent–agent pair are run on title/abstract; the PI adjudicates; the contribution ledger and the methods statement name who did what.

## Starting point (what exists)

- `Actor` (`events/envelope.py`): `kind` (`human | agent | system`), `id`, `user`, `session`, `model`, `skill`. For an agent, `id` is the role and `user` the configured human (`make_agent_actor` in `mcp/conventions.py`).
- `Settings.user` (`config.py`) comes from an argument, `FACTORY_USER` or the OS login. `Project.human_actor()` and `Project.system_actor()` (`services/context.py`) build actors from it. There is no authentication: whoever runs the process is the user.
- The session is a ULID minted once per MCP server process (`build_server`) or CLI invocation; 00-system §7 states that one process serves one Claude Code session and its subagents.
- `Channel` (`model/screening.py`): `cli | mcp`. Human acts (calibration labels, resolutions, audit labels) enter by CLI or as MCP relays with the configured human as actor (decision 37 item 6).
- Independence (decision 37): a session joins at most one pass; agreement refuses shared sessions or models; `join_pass` admits agents only; pass sessions are refused report and answer-key tools (decisions 43, 48; `_refuse_pass_session`).
- `ScreeningPlan.reviewers` declares `Reviewer(role: reviewer-of-record | assisting, actor, kind: human | agent, duties)` (R-39).
- Storage: `events/<actor.id>/<session>.jsonl` per project; `EventWriter` appends with fsync and truncates its own torn tail; `Index` serialises writers with `flock` on `.index/lock` and rebuilds when a newly read event sorts before the last applied one. Event IDs come from a per-process monotonic `IdGenerator`.
- Library: per project, git-ignored, content-addressed (decision 39); sharing deferred to this slice.

## User flow

1. **Admin sets up the server** (once): `factory server init` creates the lab registry; `factory user add` registers people; an identity provider or personal tokens are configured (rulings 6, 7). The server runs `factory serve --http` behind a TLS reverse proxy.
2. **Owner hosts a project**: `factory project host <slug>` on the server records `project.hosted`; from then on only the server writes the project (ruling 2). A stage-0 project is imported once with its events and library.
3. **Owner grants roles**: `factory member grant <slug> <user> <role>` (ruling 9). Grants are events in the project's log.
4. **Researchers connect**: Claude Code with a personal token, or claude.ai through a custom connector with OAuth. Each conversation is one factory session bound to its principal (ruling 8).
5. **Work proceeds as in slices 1–3**, with three differences: each tool call is authorised against the caller's role (ruling 10); human acts arrive by CLI or by MCP elicitation, with relays labelled (ruling 11); `*_next` refuses when a declared budget is spent (ruling 17).
6. **Review**: a contributor's protocol amendment, an inferred-relation confirmation or another team gate is filed as a review request; a holder of the required role decides it (ruling 14).
7. **Screening teams**: a human screener joins a pass through the CLI; agreement is reported per pair type; a third person adjudicates (ruling 15).
8. **Credit**: `factory ledger` derives a CRediT statement and an AI-assistance statement from events; each named person confirms their entry (ruling 16).
9. **Library**: a document acquired by any lab project is adopted by another project by hash, with a recorded event (ruling 18).

## Rulings

Every ruling is recommended, not adopted; the recommended option is marked **[confirm]**.

### Deployment and storage

1. **Server topology.** (a) one single-tenant server per lab: one factory root, one git repository, one OS service user, one MCP endpoint; (b) a multi-tenant service hosting several labs; (c) one server per person, federated. **[confirm] (a).** It keeps one sequencer per project (ruling 2), one trust boundary and no tenant isolation code; a second lab runs its own server. A lab server is a deployment of the same `platform/` package, not a fork.
2. **One writer per hosted project.** (a) the server is the only writer of a hosted project; a `project.hosted` event names the host id, and a writer whose `Settings.host_id` differs refuses to append (CLI and MCP on other machines read clones only); (b) offline writes on personal clones merged through git, as 00-system §4.1 permits. **[confirm] (a).** Append-only files merge without conflict, but the invariants that slices 1–3 enforce by check-then-write (pass joins, task claims, supersession, calibration draws, audit draws) need one serialisation point; two offline writers could each join pass A with the same model and neither would see the other. Unhosted (stage-0) projects keep today's behaviour.
3. **Event order equals append order.** Within a hosted project every event ID is minted while the project write lock is held, and the lock covers mint, append and sync. `IdGenerator` additionally starts no lower than the project's last event ID + 1, so IDs stay monotonic across processes and restarts. **[confirm].** Without this, two concurrent sessions can append an earlier ID after a later one; `Index._sync` then rebuilds the whole projection, which is correct but costs O(log size) per occurrence and becomes the dominant cost at 10^5–10^6 events. Alternative (b): a per-project single-writer actor (an in-process queue) with no lock; rejected for this slice because the CLI on the server would bypass it.
4. **Projection store.** (a) SQLite per project, as today, on the server's local disk; (b) Postgres for the team stage, as 04-architecture §1 suggests. **[confirm] (a)**, with Postgres reconsidered only on a measured need (a reproducible load test failing a stated latency). The projector code and the rebuild-determinism test are unchanged; flock requires a local file system, so the factory root must not live on NFS or a synchronised folder (checked at server start).
5. **Git on the server.** (a) the server is the only committer of hosted projects: a scheduled `factory commit` (system actor) commits new event and text-blob files per project and pushes to a private remote; commits are signed with a server key; (b) every session commits its own file. **[confirm] (a).** Durability comes from fsync at append; git is distribution, backup and tamper evidence (a rewritten history fails signature and fast-forward checks on the remote). Literature stays git-ignored (decision 39).

### Identity, authentication and sessions

6. **Users.** (a) a lab registry: an append-only log `<root>/lab/events/<actor>/<session>.jsonl` with its own small projection (`<root>/lab/.index/lab.sqlite`), holding `user.registered`, `user.identity_linked`, `user.deactivated`, `credential.issued`, `credential.revoked`; user IDs are the existing actor IDs (`ACTOR_ID_RE`), never reused; (b) users in a configuration file; (c) users per project. **[confirm] (a).** People span projects, so identity cannot live in one project's log; project roles do (ruling 9), so each project's log alone suffices for its trace and credit. Deactivation never deletes; a deactivated user's events stay attributed.
7. **Authentication.** Two credential kinds, both resolving to one registered user: (i) **personal access tokens** for Claude Code (`claude mcp add --transport http … --header "Authorization: Bearer …"`) and for scripted clients: 256-bit random, shown once, stored only as SHA-256 in a git-ignored `<root>/.server/credentials.sqlite`, with expiry (default 90 days) and revocation; (ii) **OAuth 2.1** for claude.ai custom connectors, with the factory as resource server only (the MCP SDK's `token_verifier` and `AuthSettings`), tokens issued by an external identity provider the lab already uses (institutional OIDC or GitHub), the provider's `sub` linked to a user by `user.identity_linked`. Options: (a) both, tokens first; (b) OAuth only; (c) tokens only. **[confirm] (a)**, tokens in plan deploy-B, OAuth as its last task. The factory never runs an authorisation server and never stores a password.
8. **Session binding.** For the HTTP transport a factory session is minted per (principal, MCP transport session): the first call on a new `Mcp-Session-Id` mints a ULID and records nothing; calls without a transport session are refused (the server runs in stateful mode only). A session belongs to exactly one principal; a call presenting another principal's credential on that transport session is refused. Subagents of one Claude Code session share its connection and therefore its session, as 00-system §7 states for stdio; decision 37 is unchanged. **[confirm].** Residual risk: a client that opened a new transport session per call would split one conversation into many sessions and weaken session-based independence; the model-based check of decision 37 and the per-principal rule of ruling 15 still hold. Open question 1 asks for a client test.

### Roles and authorisation

9. **Roles.** Lab roles: `admin` (server, users, credentials, hosting) and `member`. Project roles, granted by events in the project log: `owner` (the reviewer of record by default; grants roles, sets budgets, signs off), `maintainer` (amends the protocol, decides reviews, labels, resolves, audits), `contributor` (runs agents, proposes, requests review), `screener` (joins passes as a human, nothing else), `observer` (reads). Roles are sets of permissions (table below); a person may hold several. Options: (a) this fixed set; (b) roles defined per project. **[confirm] (a)**, with per-project roles a later amendment if needed.
10. **Authorisation per tool.** Every MCP tool and every mutating CLI command declares exactly one permission in a single table (`services/access.py::TOOL_PERMISSIONS`); the server refuses to start if a registered tool is missing from it (deny by default, tested). An agent acts for its principal and holds at most the principal's permissions, minus every `human-act:*` permission: an agent can never label, resolve, audit, confirm, sign off or grant, whatever its principal's role. Refusals return a structured error (`field = "permission"`) and write nothing. **[confirm].**
11. **Human acts over a remote connection.** Over MCP every call is composed by the model, so the server cannot tell a human's answer from the agent's. Options: (a) keep decision 37 item 6 relays unchanged; (b) add a channel `elicit`: the tool asks the client to collect the answer from the human through MCP elicitation (`Context.elicit`), used when `client_capabilities` declare it; relays stay possible as `channel = mcp`, are counted separately in methods, and in `systematic` mode reviewer-of-record sign-offs and audit labels require `cli` or `elicit`; (c) human acts by CLI only. **[confirm] (b).** Decision 37's session rules apply to every channel: a session that relayed or elicited a human act cannot join a pass.
12. **Audit of who did what.** `Actor` gains an optional `credential` (`crd_<ULID>`, never the secret) on events written through an authenticated channel; absent on stdio and on events written before this slice, so old events validate unchanged. Reads and refusals are not research facts and write no event; they go to a server access log (`<root>/.server/access/<date>.jsonl`, git-ignored, append-only, rotated, retained 1 year by default) recording time, principal, credential, session, tool, project, outcome and error fields, never arguments' document text. **[confirm].**

### Workspaces, ownership and review

13. **Per-person workspaces.** (a) a workspace is a view and a queue scope over the one shared log: "my sessions, my tasks, my proposals, my pending reviews, my budget"; personal sandboxes are separate `private` projects; (b) git branches of the event log per person, merged on review (06-teams); (c) forks of a project per person. **[confirm] (a).** Branches would hide one person's pass joins and task claims from another's checks, which breaks decision 37 across people; the proposal-then-confirmation pattern that slices 3a–3c already use (inferred relations, ideas, interpretations) is the review mechanism, so no second mechanism is added. Project visibility is `lab` (every member reads) or `private` (members only), set by `project.visibility_set`.
14. **Ownership and review.** A review request (`rrq_<ULID>`; distinct from the PRESS review id `prs_`) wraps a proposal that the requester may not apply alone: `review.requested` carries the kind, the target, a proposal blob (for an amendment, the full `ProtocolSpec` and reason) and the required role; `review.decided` (`approve | reject | withdraw`) by a holder of that role who is not the requester (R-51). Approval does not apply the change: the approver then runs the ordinary tool (`protocol_amend` with `review_request_id`), which validates as today, so no deferred command is ever executed. Until slice M, `TEAM_GATES` lists the gates with a role: protocol record and amendment (`maintainer`), PRESS confirmation (`maintainer`), relation and idea confirmation (`maintainer`), interpretation and concept review (`maintainer`), membership and budgets (`owner`). **[confirm].** Region ownership (IDEA-11's CODEOWNERS) waits for regions (slice 3 proper); the mechanism is the same with `target` a region id.

### Screening teams, credit, budgets, library

15. **Human and mixed screening teams (IDEA-12).** `join_pass` admits a human actor with role `screener`, `maintainer` or `owner`, by CLI or elicitation. `PassJoined.model` becomes optional and `PassJoined.actor_kind` is added (`agent` default, so old events read unchanged). Independence: the two passes must not share a session, a model (agents) or a **user** (in hosted projects, the users of a pass are its human screeners and the principals of its agents; the two sets must be disjoint, so one person cannot screen both passes in person, through an agent and in person, or through two agents; unhosted stage-0 projects keep the slice-1 rule, so a single researcher can still run both agent passes). A human pass is served the same framing and order as an agent pass (decision 37 item 2) and the agent view of the project (no seed marks, no rates; decision 43), whatever the channel. Adjudication of disagreements, calibration labelling and audit are by a person who joined neither pass. Agreement is reported per pair type (`agent–agent`, `human–agent`, `human–human`). R-32 quotes: required for a human exclusion in `systematic`, optional otherwise (proposed R-xx(h)). Options: (a) this; (b) humans only as labellers, as today. **[confirm] (a).** Human screening is CLI-only in this slice; a screening UI is IDEA-01.
16. **Contribution ledger (IDEA-13).** The ledger is a builder over events: each event type maps to at most one CRediT role in a versioned table (`CREDIT_MAP_V1`), e.g. `question.recorded` → Conceptualization, `protocol.*` → Methodology, `search.*` and screening decisions → Investigation, `dedup.*` and `fulltext.*` → Data curation, calibration, audit and resolutions → Validation, `review.decided` → Supervision. Human contributions are counted per user; agent contributions per (role, model, skill) under the delegating user and reported in a separate AI-assistance statement. Counts are computed; the statement is confirmed per person by `ledger.confirmed` (human, CLI or elicit), which pins the ledger hash; a later event changes the hash and the confirmation is shown as stale. **[confirm].** Writing roles (Writing – original draft) come from slice 7.
17. **Budgets.** The platform never calls a model, so it cannot meter tokens. Units it can count: tasks issued by `*_next` per task kind, and outbound source requests (search pages, full-text attempts). `budget.set` (owner) declares a limit per (project | project and user) × unit × period (`total | week`); `*_next` and the source-calling tools refuse with `budget-exhausted` once the computed consumption reaches the limit; consumption is never typed. Agent- or harness-reported usage (tokens, cost) may be attached to `task.completed` as `reported_usage` and is shown, labelled *reported*, never enforced. Options: (a) this; (b) enforce reported usage; (c) budgets advisory only. **[confirm] (a).**
18. **Shared library.** (a) one lab library `<root>/library/sha256/<2>/<62>`; a project's library becomes the set of hashes its own events reference, resolved through the lab library; a project obtains a document another project acquired by `fulltext.adopted` (work id, source project, source `doc_` and attempt, hash, licence status), recorded as an attempt on route `lab-library` so PRISMA "retrieved" and R-43 hold, and trace shows the source attempt; (b) storage deduplication only, every project re-acquires; (c) silent sharing. **[confirm] (a).** Adoption from a `private` project requires membership of it. Literature still never enters git (decision 39). Mined records (IDEA-36/37) are slice M's; this slice provides their storage root (`<root>/mining/`), their visibility rule (readable by a project when the source project is `lab`-visible or the reader is a member) and their attribution.
19. **Moving a stage-0 project to the server.** `factory project host` on the server imports a project's events (by git) and library (by `factory library push`, hash-verified over the authenticated HTTPS endpoint) and records `project.hosted`. A project is hosted at most once; un-hosting is a new `project.hosted` naming another host. **[confirm].**
20. **Reading roles for held-out data.** Decision 43's "CLI shows all" becomes "CLI shows all to `owner` and `maintainer`"; a `screener` or `contributor` sees the agent view by CLI as well, because a person who knows which works are held-out seeds is a contaminated screener (R-20). **[confirm].**

### Permissions by role

| Permission | owner | maintainer | contributor | screener | observer | agent (of principal) |
| --- | --- | --- | --- | --- | --- | --- |
| `project:read` | ✓ | ✓ | ✓ | ✓ (agent view) | ✓ | ✓ (agent view) |
| `work:run` (search, chase, fetch, dedup, `*_next`/`*_record` for agent passes, propose) | ✓ | ✓ | ✓ | – | – | ✓ if principal has it |
| `pass:join-human` | ✓ | ✓ | – | ✓ | – | – |
| `protocol:change` (record, amend, deviation, PRESS confirm) | ✓ | ✓ | review request | – | – | – (proposes only) |
| `human-act:label` (calibration, audit, resolve) | ✓ | ✓ | – | – | – | never |
| `human-act:confirm` (relations, ideas, interpretations, fuzzy links) | ✓ | ✓ | – | – | – | never |
| `review:decide` | ✓ | ✓ | – | – | – | never |
| `project:govern` (grant, visibility, budget, ledger sign-off of others) | ✓ | – | – | – | – | never |
| `lab:admin` (users, credentials, hosting) | lab `admin` role only | | | | | never |

## Design

### Deployment topology

```
 Researchers' Claude Code / claude.ai             Admin (SSH)
        |  HTTPS + bearer or OAuth                    |  factory CLI on the server
 +------v-------------------------------------------------------------+
 | reverse proxy (TLS)                                                |
 | factory serve --http  (one process, stateful streamable HTTP)      |
 |   auth: token verifier -> principal ; session map (principal, Mcp-Session-Id) -> ULID
 |   access: TOOL_PERMISSIONS x project role ; access log             |
 |   services/ (unchanged business logic, Principal threaded through) |
 +--------------------------------------------------------------------+
 | <root>/lab/ (registry log + index)   <root>/.server/ (credentials, access log; git-ignored)
 | <root>/projects/<slug>/events, blobs, .index   <root>/library/ (lab, git-ignored)
 | git: server-signed commits, push to private remote (scheduled)     |
 +--------------------------------------------------------------------+
```

Outbound network (OpenAlex, arXiv, OA locations) leaves from the server with the lab's `mailto`. Full-text fetches accept only `https` URLs and refuse private, loopback and link-local addresses after DNS resolution (SSRF guard), since URLs come from third-party metadata.

### Principal and actor

A `Principal(user, credential, channel)` replaces `Settings.user` as the source of actors. `Project` gains `principal`; `human_actor()` and `system_actor()` read it; `make_agent_actor` takes it. On stdio and the local CLI the principal is built from `Settings.user` with `credential = None`, so stage 0 behaves exactly as today. On the server the CLI requires `--as <user>` only for `admin` and records the OS login check; the MCP principal comes from the verified token.

### Concurrency

A hosted project has one process writing it (the server) plus the admin CLI on the same host. Both take `Index.exclusive()` (flock); ruling 3 extends its scope to ID minting via a `Project.writing()` context that holds the lock, re-reads the last event ID and seeds the generator. Services that today mint events before taking the lock (for example `claim_next`, which relies on the fold to settle races) move minting inside `writing()`; races are still settled by the fold, but no longer cause rebuilds. Tool bodies run in worker threads; the lock is per open file description, so two threads of one process exclude each other. A test runs N threads claiming tasks concurrently and asserts zero rebuilds and one holder per task.

### Review requests

`review.requested` and `review.decided` live in the project log; a review's state is folded on read. A request is `open` until decided; `approve` makes it consumable once by the tool named in its kind; consumption is recorded by the tool's own event (`ProtocolAmended.review_request_id`). A request whose target changed after it was filed (the protocol moved on) is `stale` and cannot be consumed.

### Human screening passes

`factory screen join --pass A|B [--stage …]`, `factory screen next`, `factory screen record <decision-file>|--interactive` serve and record the same batches as `screen_next`/`screen_record`, with `actor.kind = human`, `channel = cli`. Verification (criterion IDs, quote verification when given) is the agent path's. Pass-B sampling, staleness and decision 50 apply unchanged. Calibration of a human pass is optional (`ScreeningPlan.calibrate_humans: bool = False`, omitted from the hash while false), since the labeller is usually the reference standard.

### Ledger

`services/ledger.py::ledger(project) -> Ledger` folds events into per-person and per-agent-role rows (role, event counts by type, first and last date); `render_ledger` writes CRediT and AI-assistance statements as Markdown. The map version and the ledger hash appear in the output.

### Budgets

`services/budgets.py::consumption(project, scope, unit, period, now)` counts `task.claimed` events by kind (and by `actor.user`) and source-request events (`search.page_archived`, `probe.page_archived` and `fulltext.attempted`) in the period; `require_budget(project, principal, unit)` raises `budget-exhausted`. Weeks are ISO weeks in UTC.

## Events (schema 1)

| Log | Event | Payload (summary) |
| --- | --- | --- |
| lab | `user.registered` | `user`, `display_name`, `email_hash` (SHA-256 of the lower-cased address), `lab_roles` |
| lab | `user.identity_linked` | `user`, `issuer`, `subject` |
| lab | `user.deactivated` / `user.reactivated` | `user`, `reason` |
| lab | `user.lab_role_set` | `user`, `lab_roles` |
| lab | `credential.issued` / `credential.revoked` | `credential_id` (`crd_<ULID>`), `user`, `kind` (`token`), `expires`; no secret, no hash |
| project | `project.hosted` | `host_id`, `previous_host` |
| project | `project.visibility_set` | `visibility` (`lab | private`) |
| project | `member.granted` / `member.revoked` | `user`, `role`, `reason` |
| project | `review.requested` | `review_request_id`, `kind`, `target`, `target_version`, `proposal_blob`, `required_role`, `reason` |
| project | `review.decided` | `review_request_id`, `decision`, `rationale`, `channel`; human |
| project | `budget.set` | `budget_id` (`bdg_<ULID>`), `scope_user` (or null), `unit`, `limit`, `period`; supersedes earlier of the same scope and unit |
| project | `ledger.confirmed` | `user`, `ledger_hash`, `map_version`, `channel` |
| project | `fulltext.adopted` | `work_id`, `source_project`, `source_doc`, `source_attempt`, `sha256`, `licence_status` |
| changed | `screening.pass_joined` | adds `actor_kind` (default `agent`); `model` optional when `actor_kind = human` |
| changed | `protocol.amended` | adds optional `review_request_id` |
| changed | `task.completed` | adds optional `reported_usage` |
| envelope | `Actor` | adds optional `credential` |

No event is edited; corrections supersede. Old logs validate and replay unchanged (every addition is optional with a default that reproduces today's meaning); the projection version changes.

## Index tables

Lab index: `users`, `identities`, `credentials` (no secrets). Project index: `members` (live grants folded), `reviews`, `budgets`, `adoptions`; `screening_passes` gains `actor_kind` and `user`. Derived states (review status, consumption, ledger) are computed on read. Rebuild determinism holds for both indexes.

## MCP tools and CLI

| Tool | Permission | Purpose |
| --- | --- | --- |
| `whoami` | `project:read` (any) | Principal, session, roles per project, budgets left |
| `review_request` | `work:run` | File a review request with its proposal |
| `review_list` | `project:read` | Open and decided reviews (paginated) |
| `review_decide` | `review:decide` | Decide a review (elicit or relay, ruling 11) |
| `ledger_view` | `project:read` | Computed ledger (counts only) |
| `budget_status` | `project:read` | Limits and computed consumption |
| `library_adopt` | `work:run` | Adopt a lab-library document for a promoted work |
Every existing tool gains a row in `TOOL_PERMISSIONS`. Pass sessions are refused `review_*`, `ledger_view` and `budget_status` as for other report surfaces (decisions 43, 48).

CLI: `factory server init|check`, `factory user add|deactivate|link|list`, `factory token issue|revoke|list`, `factory project host|visibility`, `factory member grant|revoke|list`, `factory review list|decide`, `factory screen join|next|record` (human passes), `factory ledger [--confirm]`, `factory budget set|status`, `factory library push|adopt|status`, `factory commit`, `factory serve --http --host --port`. Services: `services/lab.py`, `services/access.py`, `services/members.py`, `services/reviews.py`, `services/ledger.py`, `services/budgets.py`, `services/lab_library.py`, `services/hosting.py`; server wiring in `mcp/http.py`. `mcp/` and `cli/` parse and format only.

## Check findings

`member-missing-reviewer-of-record` (a `ScreeningPlan.reviewers` human entry without an owner or maintainer grant; error in systematic) · `review-open` (advisory) · `review-stale` · `pass-same-user` (both passes by one person or by one person and that person's agent; error) · `human-act-relayed` (count of relayed human acts; warning in systematic) · `budget-exhausted` (advisory) · `ledger-unconfirmed` (promotion gap before export) · `adoption-source-missing` (adopted hash absent from the lab library) · `host-mismatch` (events appended by a host other than the hosting one; error).

## Rigour requirements

Existing, in scope: **R-01** (trace crosses adoption into the source project's attempt), **R-04** (agent provenance, now with the delegating user authenticated), **R-05** (ledger, consumption and per-pair κ computed), **R-13** and **R-39** (reviewers declared in the protocol and backed by grants), **R-20** (held-out view by role, ruling 20), **R-32** (rationale quotes; human variant below), **R-33**, **R-36**, **R-37** (independence and agreement across people), **R-47** (lab library outside git), **R-51** (requester ≠ reviewer; screener ≠ adjudicator).

Proposed:
- **R-xx(h) (proposed) Human screeners.** A human pass is independent of the other pass by session, user and the user's agents; it is served the agent view; exclusions carry a verified quote in `systematic`. P, S.
- **R-xx(i) (proposed) Attributed acts.** On a hosted project every event names an authenticated user (directly or as the agent's principal); acts on a human-act permission are refused to agents; relayed human acts are counted and reported. All modes.
- **R-xx(j) (proposed) Derived credit.** Contribution and AI-assistance statements are derived from events with a versioned map and confirmed by each named person; none is typed. All modes.

## Security model (summary)

| Threat | Mitigation |
| --- | --- |
| Stolen or leaked token | Hashed at rest, expiry, revocation, credential id on every event and access-log line; OAuth via the lab's provider |
| Prompt injection from literature steering an agent to harmful calls | Agents never hold `human-act:*`, `review:decide`, `project:govern`; no tool deletes or edits; budgets bound volume; every write is attributable and reversible by supersession |
| Cross-project leakage | Per-project authorisation; `private` visibility; adoption and mining reads checked against membership |
| Held-out contamination of people | Ruling 20 |
| Forged human acts by an agent | Ruling 11 (elicitation; relays labelled; systematic sign-offs refuse relays) |
| SSRF through fetched URLs | `https` only, private address ranges refused after resolution |
| DNS rebinding, oversized requests | SDK transport security settings (allowed hosts and origins), request body limit, per-principal rate limit |
| Tampering with the log | Server-only writer, host check, signed commits pushed to a remote |
| Secrets in git | Credentials and the access log live under the git-ignored `.server/` |

## Proposed decisions (number assigned on acceptance)

1. *Slice-5 deployment:* rulings 1–5 and 19; amends 00-system §1 (multi-user authentication and server deployment enter scope), §4.1 (a hosted project has one writer; ID minting under the write lock), §7 (on HTTP, the session is minted per principal and transport session) and §9 (new commands).
2. *Slice-5 identity and access:* rulings 6–12 and 20; amends decision 37 item 6 (channel `elicit`; relays labelled) and decision 43 (CLI full view by role).
3. *Slice-5 team work:* rulings 13–18; extends decision 37 items 1 and 6 to users (no person on both passes; adjudicator outside both passes) and answers 00-system §11 questions 1 and 2.

## In scope

Lab registry, users, tokens, OAuth resource-server support · principal threading through services · project roles, grants, visibility · per-tool authorisation and access log · HTTP transport with session binding · elicitation channel · single-writer hosting, lock-scoped ID minting, server commits · review requests and team gates · human screening passes, per-pair-type agreement, adjudicator rule · contribution ledger · task and request budgets · lab library and adoption · library push for migration · check findings, methods text for teams and relays.

## Out of scope

A web UI or dashboard (IDEA-01); supervision and performance views (IDEA-10); digests, routing and meeting packs (IDEA-14); regions and region ownership (slice 3 proper); cross-project CI and opportunity reports (06-teams coordination); GPU runners (deployment stage 2); multi-lab tenancy; the shared mining store's records and reuse rules (slice M); scheduled re-runs (slice 4); billing; any model call by the platform.

## Acceptance criteria

1. **Unhosted unchanged.** With no lab registry and stdio, every slice-1–3 test passes unchanged; old logs replay to identical `P@` ids and an identical state hash except the projection version.
2. **Authentication.** A call without a valid credential, with an expired or revoked token, or with a token of a deactivated user is refused with no event and one access-log line; the credential id appears on every event of an authenticated session.
3. **Deny by default.** Registering a tool without a `TOOL_PERMISSIONS` row makes server start fail; every tool is tested with an observer token (refused unless read) and with an agent of an owner (refused on every `human-act:*`).
4. **Session binding.** Two transport sessions of one principal get two factory sessions; a transport session presenting a second principal's token is refused; calls without a transport session are refused.
5. **Single writer.** On a hosted project, a writer with another `host_id` appends nothing and reports `host-mismatch`.
6. **Order.** N concurrent sessions claiming tasks on one hosted project cause zero rebuilds; every task has one holder; event IDs in each file and across files are strictly increasing in append order.
7. **Roles.** A contributor's `protocol_amend` is refused; their review request, approved by a maintainer who is not the requester, lets the maintainer amend with `review_request_id`; the requester cannot approve their own request; a stale request cannot be consumed.
8. **Human passes.** A human joins pass A by CLI; an agent of the same user cannot join pass B; another person's agent can; the same person cannot join both; a third person adjudicates and a pass member cannot; κ is reported per pair type; the human is served no seed mark.
9. **Elicitation.** On a client declaring elicitation, `review_decide` and audit labels record `channel = elicit`; in `systematic`, a relayed sign-off is refused; methods report relayed human acts by count.
10. **Ledger.** On a constructed log, the ledger's counts per person and per agent role equal hand-computed values; `ledger.confirmed` pins the hash; one later event marks the confirmation stale; nothing in the ledger is typed.
11. **Budgets.** With a limit of k `screen_next` tasks per week for a user, the (k+1)-th call is refused with `budget-exhausted` and writes nothing; another user is unaffected; reported usage is shown and never enforced.
12. **Library.** A document fetched in project P is adopted in project Q by hash; Q's PRISMA counts it retrieved; `trace` from Q's document reaches P's attempt; adoption from a `private` project by a non-member is refused; no literature file is tracked by git.
13. **Held-out by role.** A screener's CLI `report prisma` shows the agent view; an owner's shows all.
14. **Access log.** Every refused and every read call leaves one line with principal, tool, project and outcome, and no document text.
15. **Rebuild.** Deleting both indexes and rebuilding gives identical state hashes.
16. **Pilot.** The two-researcher pilot of the Goal runs end to end on a lab server; the methods statement names pair types, adjudicator, relayed-act counts and budgets; the ledger is confirmed by all three people.
17. **Quality.** `mypy --strict` and ruff pass; coverage ≥ 90% for `services/` and `model/`; TDD; access control, session binding and the write lock by subagent-driven development.

## Dependencies

| Slice / plan | Needed for |
| --- | --- |
| Slice 1 (screening, calibration, audit, decision 37) | Pass joins, agreement, human acts, `ScreeningPlan.reviewers` |
| Slice 2 plan A (acquisition) | Attempts, routes, restore; route `lab-library` |
| Slices 3a–3c | Confirmation gates listed in `TEAM_GATES` |
| [slice-M-modules.md](slice-M-modules.md) | Gate-policy role dimension (replaces `TEAM_GATES`); shared mining store under `<root>/mining/` |
| MCP SDK ≥ 2.3 | Streamable HTTP, `token_verifier`, `AuthSettings`, `Context.elicit`, transport security |

## Proposed sub-plans

| Plan | Content | Tier | Depends on |
| --- | --- | --- | --- |
| [deploy-A](../plans/2026-11-05-deploy-a-hosting-sequencer.md) | Lock-scoped ID minting, `project.hosted` and host check, `factory commit`, root checks | critical | — |
| [teams-A](../plans/2026-11-05-teams-a-identity-access.md) | Lab registry, `Principal`, credentials, project roles and grants, `TOOL_PERMISSIONS`, access log | critical | deploy-A |
| [deploy-B](../plans/2026-11-05-deploy-b-remote-mcp.md) | HTTP transport, token verifier, session binding, per-tool enforcement, elicitation channel, SSRF guard, OAuth | critical | teams-A |
| [teams-B](../plans/2026-11-05-teams-b-review-workspaces.md) | Review requests, `TEAM_GATES`, amendment by review, visibility, workspace views, held-out view by role | standard | teams-A |
| [teams-C](../plans/2026-11-05-teams-c-screening-teams.md) | Human passes, per-user independence, adjudicator rule, per-pair-type κ | critical | teams-A |
| [teams-D](../plans/2026-11-05-teams-d-ledger-budgets.md) | Contribution ledger, budgets | standard | teams-A |
| [deploy-C](../plans/2026-11-05-deploy-c-lab-library.md) | Lab library, adoption, `library push`, project hosting import, acceptance pilot | standard | deploy-A, teams-A, teams-B |

Each plan ends with every earlier test passing; teams-B, teams-C and teams-D may run in parallel after teams-A; deploy-B may run in parallel with them.

## Open questions

1. **Client session behaviour.** Do Claude Code and claude.ai each keep one MCP transport session per conversation, and do Claude Code subagents share it? Recommendation: a recorded client test before the pilot (plan deploy-B task 7); if a client splits sessions, require one declared session per conversation through a `session_open` tool.
2. **Elicitation availability.** If neither client supports elicitation, `systematic` sign-offs are CLI-only on the server (SSH). Recommendation: accept; a minimal authenticated web form is IDEA-01.
3. **Identity provider.** Which provider the lab uses (institutional OIDC, GitHub). Recommendation: decide at server set-up; tokens suffice for the pilot.
4. **Retention of the access log.** One year by default; institutional policy may require otherwise.
5. **Licence of shared researcher-supplied documents.** Sharing subscription PDFs within one lab server is usually covered by institutional licences; the researcher should confirm for the institution. Recommendation: adoption of `researcher-supplied` documents requires the adopting project's owner to confirm once per source project.
6. **Budgets across projects.** A per-person weekly budget across all projects needs the lab log. Recommendation: per project only in this slice.
