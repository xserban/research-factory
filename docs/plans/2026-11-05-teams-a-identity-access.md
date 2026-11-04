# Identity, Roles and Access Control Implementation Plan (slice 5, sub-plan teams-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** `TOOL_PERMISSIONS` covers every tool of every slice built before it (3d, 4a, 4b, 6, 7a, 7b, M), not only slices 1–3. Bumps `PROJECTION_VERSION` by one from the value it finds; the lab index has its own version.

> **Dependencies.** deploy-A merged (`Project.writing()`, `project.hosted`, `Settings.host_id`). deploy-B, teams-B, teams-C, teams-D and deploy-C consume this plan's Interfaces blocks exactly. Ends with every earlier test passing unchanged except the `PROJECTION_VERSION` pin.

**Goal:** Give the platform people: a lab registry of users and credentials, a `Principal` from which every actor is built, project roles granted by events, one permission table for every tool, and an access log for reads and refusals.

**Architecture:** The lab registry is a second event log at `<root>/lab/` with its own catalog and projection, reusing `EventWriter`, `Index` and `EventFactory` unchanged; its envelope `project` is the reserved slug `lab`. Credentials' secrets live in a git-ignored SQLite file under `<root>/.server/`, outside the event model (they are secrets, not research facts). `Principal` is threaded through `Project`; on stdio and the local CLI it is built from `Settings.user`, so stage 0 is unchanged. `services/access.py` holds `Permission`, `ROLE_PERMISSIONS`, `TOOL_PERMISSIONS` and `authorize`; enforcement in the MCP server is deploy-B's.

**Tech Stack:** as slice 2; `secrets`, `hashlib`, `sqlite3` (stdlib) for credentials.

**Spec:** `docs/specs/slice-5-teams-deployment.md` rulings 6, 7 (tokens), 9, 10, 12; permissions table; acceptance 1, 2 (service level), 3 (table level), 14, 15.

## Rulings made in this plan

1. **Reserved slug.** `lab` is refused by `slug_issues` for projects; the lab log uses `project = "lab"`. [confirm]
2. **Implicit owner of unhosted projects.** A project with no `member.granted` event treats `Settings.user` as `owner`, so stage 0 needs no grants. Once any grant exists, only grants count. `factory project host` (deploy-C) writes the first grant. [confirm]
3. **Last owner.** Revoking the last `owner` grant is refused. [confirm]
4. **Token format.** `rf_pat_` + 43 URL-safe base64 characters (256 bits); stored as `sha256(token)`; the credential id `crd_<ULID>` is returned with the token once. Expiry default 90 days, maximum 365. [confirm]
5. **Access log line.** `{"ts", "principal", "credential", "session", "channel", "tool", "project", "outcome": "ok|refused|error", "fields": [..]}`; never argument values. [confirm]

## Global Constraints

- The platform never calls a model. No secret, token or token hash in any event, blob, log line or git-tracked path.
- Events are the source of truth; projections are written only by the projector; rebuild is deterministic for the project and lab indexes.
- Business logic in `services/`; `mcp/` and `cli/` parse and format only.
- Every old log validates and replays unchanged (`Actor.credential` optional).
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90% for `services/` and `model/`.

## Review Focus

1. An agent whose principal is `owner` is refused every `human-act:*`, `review:decide` and `project:govern` permission (Task 5, `test_agent_never_holds_human_acts`).
2. Every tool registered by `build_server` has a `TOOL_PERMISSIONS` row (Task 5, `test_every_tool_has_a_permission`).
3. No token or hash appears in the lab log or index (Task 2, `test_no_secret_in_events_or_index`).
4. Role at time *t*: a revoked grant stops counting from its revoke event (Task 4, `test_roles_follow_grants_over_time`).

## File Structure

- Create `model/lab.py`, `model/members.py`, `services/lab.py`, `services/credentials.py`, `services/members.py`, `services/access.py`, `services/access_log.py`, `index/lab.py`, `index/members.py`.
- Modify `events/envelope.py` (`Actor.credential`), `events/catalog.py`, `services/context.py` (`Principal`, `Project.principal`, reserved slug), `mcp/conventions.py` (`make_agent_actor`), `index/default.py`, `cli/main.py`.
- Tests: `tests/test_lab.py`, `tests/test_credentials.py`, `tests/test_principal.py`, `tests/test_members.py`, `tests/test_access.py`, `tests/test_access_log.py`.

---

### Task 1: Lab registry

*Tier: critical.*

**Files:** Create `model/lab.py`, `index/lab.py`, `services/lab.py`; Modify `services/context.py`; Test `tests/test_lab.py`.

**Interfaces:**
- Produces (`model/lab.py`): `UserRegistered(user: str, display_name: str, email_hash: str | None, lab_roles: tuple[LabRole, ...])`, `LabRole(StrEnum)`: `ADMIN`, `MEMBER`; `IdentityLinked(user, issuer: str, subject: str)`; `UserDeactivated(user, reason)`, `UserReactivated(user, reason)`, `LabRoleSet(user, lab_roles)`.
- Produces (`services/lab.py`): `@dataclass Lab(paths, settings, session, clock, ids, events, writer, index)`; `init_lab(settings, *, session, clock) -> Lab` (creates `<root>/lab/events`), `open_lab(...) -> Lab`; `register_user(lab, actor, user, display_name, email: str | None, lab_roles) -> None` (refused when the user exists, ever); `deactivate_user`, `reactivate_user`, `set_lab_roles`, `link_identity(lab, actor, user, issuer, subject)` (refused when `(issuer, subject)` is linked to another user); `user_record(lab, user) -> UserRecord | None` with `active: bool`, `lab_roles`; `user_for_subject(lab, issuer, subject) -> str | None`.
- Lab tables: `users`, `identities`, `lab_roles`.

- [ ] **Step 1: Tests.** `test_register_and_read_user`, `test_user_id_never_reused` (register, deactivate, register again: refused), `test_identity_linked_once`, `test_email_is_hashed` (`email_hash == sha256(email.lower())`, no address in the log), `test_lab_rebuild_deterministic`, `test_project_slug_lab_refused`.
- [ ] **Step 2–4:** Fail, implement, pass; full suite.
- [ ] **Step 5:** Commit `feat(lab): lab registry log for users and identities`.

### Task 2: Credentials

*Tier: critical.*

**Files:** Create `services/credentials.py`; Modify `model/lab.py`; Test `tests/test_credentials.py`.

**Interfaces:**
- Produces: events `credential.issued` `CredentialIssued(credential_id, user, kind: Literal["token"], expires: datetime)`, `credential.revoked` `CredentialRevoked(credential_id, reason)` in the lab log.
- Produces: `issue_token(lab, actor, user, *, days: int = 90) -> IssuedToken(credential_id, token, expires)`; `verify_token(lab, token, now) -> VerifiedCredential(credential_id, user) | None` (None when unknown, expired, revoked, or the user is inactive; constant-time compare via `hmac.compare_digest` on hashes); `revoke(lab, actor, credential_id, reason)`; the secret store `<root>/.server/credentials.sqlite` with table `token_hashes(credential_id PRIMARY KEY, sha256)`, created with mode 0600.

- [ ] **Step 1: Tests.** `test_issue_and_verify`, `test_expired_token_refused`, `test_revoked_token_refused`, `test_inactive_user_token_refused`, `test_no_secret_in_events_or_index` (grep the lab events dir, blobs and lab index for the token and its hash: absent), `test_store_file_mode_0600`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(lab): personal access tokens with hashed secret store`.

### Task 3: `Principal` and `Actor.credential`

*Tier: critical.*

**Files:** Modify `events/envelope.py`, `services/context.py`, `mcp/conventions.py`, `mcp/server.py` (callers only), `cli/main.py` (callers only); Test `tests/test_principal.py`, `tests/test_envelope.py` (new tests only).

**Interfaces:**
- Produces: `Actor.credential: str | None = Field(default=None, pattern=rf"^crd_{ULID_RE}$")`; `Channel` gains nothing here (deploy-B adds `ELICIT`).
- Produces: `@dataclass(frozen=True) Principal(user: str, credential: str | None, channel: Channel)`; `Principal.local(settings, channel) -> Principal`; `build_project(..., principal: Principal | None = None)` and `open_project(...)` (default `Principal.local(settings, Channel.CLI)`); `Project.principal`; `human_actor()` and `system_actor()` use `principal.user` and `principal.credential`; `make_agent_actor(settings, session, role, model, skill, principal: Principal | None = None)` (default local).

- [ ] **Step 1: Tests.** `test_old_actor_lines_validate` (fixture lines without `credential`), `test_human_actor_from_principal`, `test_agent_actor_user_is_principal`, `test_local_principal_matches_settings_user`, `test_credential_on_events` (a principal with `crd_…` produces events carrying it).
- [ ] **Step 2–4:** Fail, implement, pass; full suite unchanged.
- [ ] **Step 5:** Commit `feat(identity): principal threading and actor credential`.

### Task 4: Project roles and grants

*Tier: critical.*

**Files:** Create `model/members.py`, `index/members.py`, `services/members.py`; Modify `events/catalog.py`, `index/default.py`; Test `tests/test_members.py`.

**Interfaces:**
- Produces: `ProjectRole(StrEnum)`: `OWNER`, `MAINTAINER`, `CONTRIBUTOR`, `SCREENER`, `OBSERVER`; events `member.granted` `MemberGranted(user, role, reason)`, `member.revoked` `MemberRevoked(user, role, reason)`; table `member_events(event_id, user, role, granted: bool)`.
- Produces: `grant(project, actor, user, role, reason)` (actor must hold `project:govern`, checked through `access.authorize`; the user must be active in the lab registry when a lab exists), `revoke(...)` (ruling 3), `roles_of(project, user) -> frozenset[ProjectRole]` (ruling 2 for unhosted projects without grants), `members(project) -> dict[str, frozenset[ProjectRole]]`.

- [ ] **Step 1: Tests.** `test_implicit_owner_without_grants`, `test_grants_replace_implicit_owner`, `test_roles_follow_grants_over_time`, `test_last_owner_cannot_be_revoked`, `test_grant_requires_govern`, `test_grant_unknown_user_refused`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(members): project roles granted by events`.

### Task 5: Permissions and `authorize`

*Tier: critical.*

**Files:** Create `services/access.py`; Test `tests/test_access.py`.

**Interfaces:**
- Produces: `Permission(StrEnum)`: `PROJECT_READ = "project:read"`, `WORK_RUN = "work:run"`, `PASS_JOIN_HUMAN = "pass:join-human"`, `PROTOCOL_CHANGE = "protocol:change"`, `HUMAN_LABEL = "human-act:label"`, `HUMAN_CONFIRM = "human-act:confirm"`, `REVIEW_DECIDE = "review:decide"`, `PROJECT_GOVERN = "project:govern"`, `LAB_ADMIN = "lab:admin"`; `HUMAN_ONLY: frozenset[Permission]` (`HUMAN_LABEL`, `HUMAN_CONFIRM`, `REVIEW_DECIDE`, `PROJECT_GOVERN`, `PASS_JOIN_HUMAN`, `LAB_ADMIN`); `ROLE_PERMISSIONS: Mapping[ProjectRole, frozenset[Permission]]` (spec table); `TOOL_PERMISSIONS: Mapping[str, Permission]` covering every current MCP tool name and every mutating CLI command (key `cli:<group> <command>`); `authorize(project: Project | None, principal: Principal, actor_kind: ActorKind, permission: Permission, *, lab: Lab | None = None) -> None` raising `FactoryValidationError([ValidationIssue("permission", "<permission> not held")])`.

- [ ] **Step 1: Tests.**
```python
def test_every_tool_has_a_permission(settings):
    names = tool_names(build_server(settings))   # test helper: awaits the SDK's list_tools() and returns the names
    assert names <= TOOL_PERMISSIONS.keys()
@pytest.mark.parametrize("perm", sorted(HUMAN_ONLY))
def test_agent_never_holds_human_acts(owner_project, perm):
    with pytest.raises(FactoryValidationError): authorize(owner_project, owner_principal, "agent", perm)
def test_observer_reads_only(...): ...
def test_role_table_matches_spec(...): ...   # literal copy of the spec table rows
```
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(access): permission table and authorize`.

### Task 6: Access log and admin CLI

*Tier: standard.*

**Files:** Create `services/access_log.py`; Modify `cli/main.py`; Test `tests/test_access_log.py`, `tests/test_cli.py` (new tests only).

**Interfaces:**
- Produces: `AccessEntry` (ruling 5); `AccessLog(root: Path).write(entry: AccessEntry) -> None` (append, fsync, daily file `<root>/.server/access/<YYYY-MM-DD>.jsonl`, mode 0600); `prune(root, keep_days: int = 365) -> int`.
- Produces CLI: `factory server init [--host-id ID]` (creates the lab registry with the calling OS user registered as lab `admin`, `<root>/.server/` with mode 0700 and `host_id`, and the `.gitignore` entries `library/`, `.index/`, `.server/`), `factory user add|deactivate|reactivate|link|list`, `factory token issue|revoke|list`, `factory member grant|revoke|list`; each mutating command authorised through `authorize` with the local principal and logged.

- [ ] **Step 1: Tests.** `test_entry_has_no_argument_values`, `test_refusal_logged`, `test_prune_keeps_recent`, `test_cli_token_issue_prints_once` (second `list` shows id and expiry, never the token).
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Verification `uv run pytest -m "not network and not slow" -q && uv run mypy --strict src && uv run ruff check .`; commit `feat(access): access log and admin commands`.

## Later (not v1)

None: every task of this plan is in v1.
