# Remote MCP Connector Implementation Plan (slice 5, sub-plan deploy-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** v1 cut: Task 7 (OAuth resource server and the manual client-session test) moved to Later; personal access tokens are the v1 credential. The residual risk of spec open question 1 (a client splitting one conversation into several transport sessions) is accepted for v1 and tested when the Later task runs; deploy-C does not wait for it.

> **Dependencies.** deploy-A and teams-A merged (`Principal`, `verify_token`, `authorize`, `TOOL_PERMISSIONS`, `AccessLog`, `Project.writing()`). May run in parallel with teams-B, teams-C and teams-D; each of those adds tools whose `TOOL_PERMISSIONS` rows this plan's enforcement picks up without change.

**Goal:** Serve the factory's MCP tools over authenticated streamable HTTP to Claude Code and claude.ai, with one factory session per principal and transport session, per-tool authorisation, an elicitation channel for human acts, and the server hardening the spec lists.

**Architecture:** `build_server` stops capturing one session ULID; it takes a `CallContext` provider that yields `(principal, session)` per call. The stdio provider returns the local principal and one process session, so stdio behaviour is unchanged. `mcp/http.py` builds the HTTP app with the SDK's `MCPServer(auth=AuthSettings(...), token_verifier=...)` and `streamable_http_app()`, a `FactoryTokenVerifier` over `verify_token`, and a `SessionRegistry` keyed by `(credential, Mcp-Session-Id)`. A single wrapper, applied to every tool at registration, authorises, logs and maps refusals. Elicitation is used through `Context.elicit` when `client_capabilities` declare it.

**Tech Stack:** MCP SDK ≥ 2.3 (`mcp.server.auth`, `mcp.server.transport_security`), `uvicorn` (new optional extra `server`), `pyjwt[crypto]` (optional extra `server`, Task 7 only); `httpx` test client with ASGI transport.

**Spec:** `docs/specs/slice-5-teams-deployment.md` rulings 7, 8, 10, 11, 12; Design "Deployment topology", "Principal and actor"; security model; acceptance 2, 3, 4, 9, 14.

## Rulings made in this plan

1. **Stateful only.** The HTTP app is built with stateless mode off; a request without `Mcp-Session-Id` after initialisation is refused by the SDK; a tool call whose transport session is unknown to the registry mints a new factory session. [confirm]
2. **Session idle expiry.** A factory session whose transport session is closed or idle beyond the SDK's idle timeout is forgotten; a later call with the same transport id cannot resurrect it (the SDK issues a new id). Pass joins remain bound to the old ULID in the log, as with a closed stdio process. [confirm]
3. **Elicited human acts.** For tools with a `human-act:*` or `review:decide` permission, on HTTP: if the client declares elicitation, the server elicits a confirmation form showing the model-proposed values (verdict, criterion, decision) with accept, change or decline; the event is written with `channel = elicit` only on accept or change, using the human's values. If the client does not declare elicitation, the call proceeds as a relay (`channel = mcp`) except where ruling 11 of the spec refuses relays (`systematic` sign-offs and audit labels). [confirm]
4. **Rate limit.** Per principal, 20 tool calls per second sustained, burst 100, in memory; exceeded calls are refused and logged; limits configurable. [confirm]
5. **SSRF guard.** All outbound HTTP made by `sources/` and full-text routes passes `require_public_https(url)`; the resolved addresses must be global unicast (`ipaddress.ip_address(...).is_global`); redirects are re-checked. [confirm]

## Global Constraints

- The platform never calls a model; elicitation asks the human through the client, never a model.
- `mcp/` contains wiring only: authentication, session mapping and authorisation call `services/` functions (`verify_token`, `authorize`, `AccessLog.write`); no business rule lives in `mcp/http.py`.
- Every refusal writes no event, returns structured errors and writes one access-log line.
- stdio behaviour, tools and results are unchanged (every `test_mcp_*` passes unchanged).
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass.

## Review Focus

1. A transport session presenting a second principal's token is refused (Task 2, `test_session_bound_to_one_principal`).
2. Every tool is wrapped: a tool added without the wrapper fails `test_every_tool_is_authorised` (Task 3).
3. An agent of an owner calling `calibration_label` over HTTP without elicitation in a `systematic` project is refused; with elicitation and accept, the event has `channel = elicit` and the human's values (Task 4).
4. A fetch URL that resolves to `127.0.0.1` or `10.0.0.5` is refused before any connection (Task 5).

## File Structure

- Create `mcp/http.py`, `mcp/sessions.py`, `mcp/authz.py`, `sources/guard.py`.
- Modify `mcp/server.py` (session provider; wrapper at registration; elicitation hook for human-act tools), `model/screening.py` (`Channel.ELICIT`), `sources/http.py` (guard), `cli/main.py` (`serve --http`), `pyproject.toml` (extra `server`).
- Tests: `tests/test_mcp_http.py`, `tests/test_mcp_sessions.py`, `tests/test_mcp_authz.py`, `tests/test_mcp_elicit.py`, `tests/test_source_guard.py`, `tests/test_oidc.py`.

---

### Task 1: Call context provider (refactor, no behaviour change)

*Tier: critical.*

**Files:** Modify `mcp/server.py`; Create `mcp/sessions.py`; Test `tests/test_mcp_sessions.py`.

**Interfaces:**
- Produces: `CallContext(principal: Principal, session: str)`; `ContextProvider = Callable[[Context | None], CallContext]`; `stdio_provider(settings, clock) -> ContextProvider` (one ULID per process, local principal, `Channel.MCP`); `build_server(settings, clock=..., sources=..., fulltext_routes=..., context: ContextProvider | None = None)`; every tool body obtains `(principal, session)` from the provider instead of the closed-over `session`.

- [ ] **Step 1: Tests.** `test_stdio_provider_one_session_per_process`, `test_build_server_default_is_stdio` (the existing `test_mcp_server.py` suite passes unchanged — run it).
- [ ] **Step 2–4:** Fail, refactor, pass; full suite.
- [ ] **Step 5:** Commit `refactor(mcp): per-call principal and session provider`.

### Task 2: HTTP app, token verifier, session registry

*Tier: critical.*

**Files:** Create `mcp/http.py`; Modify `mcp/sessions.py`; Test `tests/test_mcp_http.py`, `tests/test_mcp_sessions.py`.

**Interfaces:**
- Produces: `FactoryTokenVerifier(lab_opener: Callable[[], Lab], clock)` implementing the SDK `TokenVerifier.verify_token(token) -> AccessToken | None` with `subject = user`, `client_id = credential_id`, `scopes = ["factory"]`; `SessionRegistry(ids: IdGenerator)` with `session_for(credential_id: str, user: str, transport_session: str) -> str` (raises `SessionPrincipalMismatch` when the transport session is bound to another user), `forget(transport_session)`; `http_provider(registry, lab_opener) -> ContextProvider` reading `get_access_token()` and the `mcp-session-id` header from `Context.headers`; `build_http_app(settings, *, issuer_url: str, resource_url: str, allowed_hosts: list[str], allowed_origins: list[str]) -> Starlette`.

- [ ] **Step 1: Tests** (ASGI client, no network).
```python
async def test_no_token_401(app): assert (await post_initialize(app, token=None)).status_code == 401
async def test_revoked_token_401(app, lab): ...
async def test_two_transport_sessions_two_factory_sessions(app, token_a): ...
async def test_session_bound_to_one_principal(app, token_a, token_b):
    sid = await initialize(app, token_a); r = await call_tool(app, token_b, sid, "project_status", {"project": "p"})
    assert r.error_field == "session"
async def test_events_carry_credential(app, token_a): ...  # actor.credential == crd of token_a
```
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(mcp): streamable HTTP with token auth and session binding`.

### Task 3: Per-tool authorisation wrapper

*Tier: critical.*

**Files:** Create `mcp/authz.py`; Modify `mcp/server.py`; Test `tests/test_mcp_authz.py`.

**Interfaces:**
- Produces: `authorised(name: str, provider: ContextProvider, opener: ProjectOpener, log: AccessLog | None) -> Callable[[ToolFn], ToolFn]` applied by a registration helper `_tool(server, fn)` that replaces bare `@server.tool()`; it looks up `TOOL_PERMISSIONS[name]` (KeyError at build time → server start fails), calls `authorize(project, principal, "agent", permission)` for agent-parameterised tools and `"human"` for human-act tools, writes one access-log line per call, and returns the existing `fail(...)` shape on refusal.

- [ ] **Step 1: Tests.** `test_every_tool_is_authorised` (introspect: each registered tool's function is wrapped), `test_unknown_tool_name_fails_build`, `test_observer_refused_mutations` (parametrised over all mutating tools), `test_refusal_writes_no_event_and_one_log_line`, `test_stdio_unhosted_owner_allowed` (implicit owner; existing suite unaffected).
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(mcp): deny-by-default per-tool authorisation`.

### Task 4: Elicitation channel for human acts

*Tier: critical.*

**Files:** Modify `model/screening.py` (`Channel.ELICIT = "elicit"`), `mcp/server.py` (the human-act tools that exist today, `calibration_label`, `audit_record` and `extract_audit_record`, plus teams-B `review_decide`; resolutions and PRESS confirmation are CLI-only today and stay so), `services/calibration.py`, `services/audit.py`, `services/agreement.py`, `services/extraction_agreement.py`, `services/extraction_audit.py` (accept `Channel.ELICIT`; systematic relay refusal); Test `tests/test_mcp_elicit.py`.

**Interfaces:**
- Produces: `elicit_confirmation(ctx: Context, title: str, proposed: Mapping[str, str], choices: Mapping[str, Sequence[str]]) -> ElicitOutcome(accepted: bool, values: dict[str, str])`; `require_human_channel(project, channel, act: Literal["sign-off", "audit-label", "label", "resolve"]) -> None` in `services/access.py` (refuses `Channel.MCP` for `sign-off` and `audit-label` in `systematic`); decision 37 session rule applies to `ELICIT` exactly as to `MCP` (`_is_label_session` reads both).

- [ ] **Step 1: Tests** (stub `Context` with and without elicitation capability). `test_elicit_accept_records_human_values`, `test_elicit_decline_writes_nothing`, `test_relay_refused_for_systematic_audit_label`, `test_relay_allowed_in_pilot_and_counted` (methods count of `channel = mcp` human acts), `test_elicited_session_cannot_join_pass`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(mcp): elicitation channel for human acts`.

### Task 5: Outbound guard and hardening

*Tier: standard.*

**Files:** Create `sources/guard.py`; Modify `sources/http.py`, `mcp/http.py`; Test `tests/test_source_guard.py`, `tests/test_mcp_http.py`.

**Interfaces:**
- Produces: `require_public_https(url: str, resolve: Callable[[str], list[str]] = default_resolve) -> None` (ruling 5); a redirect hook re-checking each `Location`; `RateLimiter(rate: float, burst: int, clock)` used by the wrapper of Task 3; `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=..., allowed_origins=...)`; request body limit at the SDK default.

- [ ] **Step 1: Tests.** `test_private_addresses_refused` (parametrised: `127.0.0.1`, `10.0.0.5`, `169.254.169.254`, `::1`, `fc00::1`), `test_http_scheme_refused`, `test_redirect_to_private_refused`, `test_rate_limit_refuses_and_logs`, `test_foreign_host_header_refused`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(security): outbound guard, rate limit, transport security`.

### Task 6: `factory serve --http`

*Tier: standard.*

**Files:** Modify `cli/main.py`, `pyproject.toml`; Test `tests/test_cli.py` (new tests only).

**Interfaces:**
- Produces: `factory serve --http --host 127.0.0.1 --port 8765 --issuer-url URL --resource-url URL --allowed-host H…`; refuses to start without a lab registry, without `host_id`, when `server_check` reports an error, or when `--host` is not loopback and `--insecure-direct` is absent (TLS terminates at the reverse proxy). Runs `uvicorn` on `build_http_app`.

- [ ] **Step 1: Tests.** `test_serve_http_refuses_without_lab`, `test_serve_http_refuses_public_bind_without_flag`, `test_serve_http_builds_app` (no socket opened; the app factory is called with the parsed settings).
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(cli): serve over HTTP`.

## Later (not v1)

Moved here by the v1 cut of 2026-11-04 (decision 74); built after the v1 plans of the build order (`2026-11-05-build-order.md`), in the order listed. Task text is unchanged; references to "Task N" inside a moved task use the plan's original numbering.

### Later L1 (was Task 7): OAuth resource server (OIDC tokens) and client session test

*Tier: standard.*

**Files:** Create `mcp/oidc.py`; Modify `mcp/http.py`; Test `tests/test_oidc.py`; Create `docs/runbook-lab-server.md` only if the researcher asks for it (otherwise the procedure below is recorded in the plan's completion notes).

**Interfaces:**
- Produces: `OidcTokenVerifier(issuer: str, audience: str, jwks: JwksSource, lab_opener)` verifying signature, `iss`, `aud`, `exp`, then mapping `(iss, sub)` through `user_for_subject`; unknown subjects are refused (no auto-registration); `CompositeVerifier(pat: FactoryTokenVerifier, oidc: OidcTokenVerifier | None)` trying the `rf_pat_` prefix first.

- [ ] **Step 1: Tests** (keys generated in the test; JWKS stubbed). `test_valid_jwt_maps_to_user`, `test_wrong_audience_refused`, `test_unlinked_subject_refused`, `test_expired_jwt_refused`, `test_pat_and_jwt_coexist`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5 (manual, `network`):** with a test server, connect Claude Code (two conversations, one with a subagent) and claude.ai (two chats); record in the plan completion notes the number of distinct factory sessions observed per conversation and per subagent (spec open question 1). If a client splits a conversation into several transport sessions, stop and raise a ruling before deploy-C.
- [ ] **Step 6:** Verification `uv run pytest -m "not network and not slow" -q && uv run mypy --strict src && uv run ruff check .`; commit `feat(mcp): OIDC resource-server tokens`.
