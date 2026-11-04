# Slice M — Stage modules, gate policies and miners

Status: draft — rulings recommended; awaiting the researcher's review before any build.

Builds on [00-system.md](00-system.md), slices 1, 2, 3a, 3b and 3c; must satisfy [01-rigour.md](01-rigour.md) R-01–R-05, R-13–R-16, R-33–R-37, R-40, R-44–R-47, R-51, R-52, plus the requirements proposed below. Implements backlog IDEA-38 (stage modules and gate policies), IDEA-37 (miners with verifiable field kinds) and IDEA-36 (reuse of mined records across projects, folded into IDEA-37 as its shared mining layer). Vocabulary: [docs/10-abstractions.md](../10-abstractions.md) (artifact, event family, stage module, gate, gate policy, miner, field kind, verifier, quality regime, builder); its section 5 lists the misfits this slice resolves and its section 6 the questions it answers. Every ruling is marked **[confirm]** with a recommended option, so that the researcher can accept them in bulk.

Depends on: plans 2C, 2D, 2E (built); G1 (references and snowballing; in progress); G2-A (pack discriminator; Task 3 committed at `06b4f40`). Plans M-C to M-E require G2-A merged. G2-B to G2-E and G3 may land before or after this slice: the contribution module is declared when its code exists (migration step 6).

## Goal

Give every step of the factory one declared contract, so that (1) the quality code that screening and extraction duplicate becomes one implementation; (2) who may pass each binding decision is a declared, hashed policy rather than a scatter of `RigorMode` tests; (3) new kinds of mined records are added as data (a registered miner whose fields are verifiable), not as new services; and (4) records mined in one project can be reused in another without being copied silently. All of this happens without renaming an event type, removing a payload field or changing what an existing log replays to.

Acceptance pilot: the existing slice-1, slice-2 and G1 acceptance suites pass unedited after each plan; a registered, agent-authored miner on the linear-attention corpus ("does the paper report a vision benchmark result with resolution?", fields `task` enum, `resolution` number, `evidence` quote) runs dual passes, passes a human calibration sample, and is admitted as evidence by amendment; its records are then imported into a second project and re-verified there.

## Non-goals

- No change to screening's verdict model, PRISMA accounting or R-15 blast radius (ruling 3).
- No loosening of any gate that a *Decided* entry or an adopted slice ruling assigns to a human (decision 37 item 6; decision 42 item 2; slice-3b ruling 3; slice-3c review rules). The policy model can express such a loosening; making one requires a new decision.
- No shared library of literature between projects (00-system §11, slice 5). The shared mining store holds records and digests, never document text.
- No hypothesis or validation module (R-50, R-52, R-53); the contract is checked against it only on paper (open question 3).
- No embeddings, ranking or automatic miner proposal by the platform. The platform never calls a model.

## User flow

**Researcher.**
1. Nothing changes for an existing project. `factory modules` lists the modules of the platform with their gates, task kinds, event family, checks and strategies; `factory gates` prints the effective gate policy of the project (the rigor-mode preset, or the protocol's `gate_policies` section) and, per gate, the number of acts passed by a human, by an agent under audit and by an agent alone.
2. To declare a policy other than the preset, the researcher amends the protocol with a `gate_policies` section. The amendment computes its blast radius over gate acts (ruling 7). `check` reports acts recorded below the policy now in force.
3. To add a kind of mined record, the researcher (or an agent) registers a miner (`miner register spec.json`): selector, fields of verifiable kinds, evidence rule, procedure skill, quality regime. The platform validates and hashes it and records `miner.registered`. The protocol then lists it (`miners` section, by amendment) before any task is served.
4. The researcher labels the calibration sample of an agent-authored miner in the CLI (`miner calibrate label`); the platform scores the calibration pass against the labels. A miner that passes may be admitted as evidence by an amendment that sets `evidence: true` on its protocol entry.
5. In a second project, `mine import --from <slug> --miner m-vision-result@1` imports records for works whose conversion the project also holds; the platform re-verifies every imported field against the project's own conversion and records `mine.imported`.

**Agent.**
1. Existing tools are unchanged. New generic tools `mine_next(miner, pass_label)` and `mine_record(task_id, records)` serve any miner the protocol lists; `extract_*` and `contribution_*` remain as the built-in miners' tools.
2. An agent may propose a miner (`miner_register`); it is then the miner's *proposer* and cannot run its calibration pass, label calibration items, resolve its disagreements or confirm its evidence status (R-51).
3. Agents see the gate policy that applies to the tool they call; a refusal names the gate and the policy, never a rate or a label (decision 37 item 14).

## Rulings

### Contract

1. **The contract is code: declarations plus a small protocol [confirm].** Options: (a) a frozen `ModuleSpec` dataclass per module (inputs, outputs, event family, task kinds, protocol sections, gates, quality regime, check rules, strategies) plus a `StageModule` protocol with three read hooks (`hits`, `methods`, `autonomy_acts`), held in a `ModuleRegistry` and checked by ownership tests; (b) abstract base classes that modules subclass and that own their service logic; (c) a documentation-only contract. *Recommended (a).* Declarations are data that tests can check exhaustively (every event type, task kind, check code and protocol section has exactly one owner); behaviour stays in `services/` as CLAUDE.md requires; (b) would move business logic out of `services/` and invite inheritance across modules; (c) is what exists today and has let the duplication of section 5 item 3 grow.

2. **Event families: keep per-module families; field miners share the plan-D family [confirm].** Options: (a) one generic `mine.*` family for every miner, with old screening, extraction and reference events upcast on read; (b) per-module families, and every new miner gets its own family and service; (c) existing families stay as they are and are *declared* by their module; every field-record miner (the evidence pack, the contribution pack, and every registered miner) writes the plan-D `extraction.*` family, discriminated by the miner on each event (`pack`, `schema_ref`), as G2-A already does for two packs; new event types exist only for what has no counterpart (miner lifecycle, calibration, import). *Recommended (c).* (a) changes what every existing log means and needs an upcasting policy that 00-system §11 leaves open; (b) costs a new service per question, which is the problem IDEA-37 names. (c) adds no record event type, keeps replay byte-identical, and reuses one engine; its cost is that the family name `extraction` is historical (documented in the module declaration). The MCP surface is generic: `mine_next`/`mine_record`.

3. **Screening is a filter module, not a miner [confirm].** Options: (a) screening becomes a miner whose record is a verdict, with an accounting add-on for PRISMA; (b) screening stays its own module kind (`filter`) that shares the quality primitives (passes, independence, calibration, audit) through the contract but keeps its record model, verdicts, criteria priorities and R-15 blast radius. *Recommended (b).* Screening's accounting is stricter than any field miner's (four verdicts, `cannot-assess` promotion, exclusion reasons in PRISMA, stage dimension); forcing it into the field-record model would either weaken that accounting or burden every miner with it. Sharing the regime is where the duplication lives, and (b) removes it.

4. **Scoping output stays `Q@` and `P@` [confirm].** Options: (a) the slice-1 question and protocol records are the scoping module's outputs, and strategies (interview `rf-frame`, probe `rf-probe`, seed-set drafting) are recorded through the skill reference already on every agent event; (b) a new richer "scope artifact". *Recommended (a)*; a new artifact would duplicate `Q@`/`P@` without a consumer.

5. **Module kinds [confirm].** `core` (exactly one module: `project.created`, the `task.*` family and the cross-cutting checks such as broken links and missing provenance), `scoping`, `retrieval`, `transform`, `filter`, `miner`, `proposal` (agent proposes, human or policy confirms: G1 links, G2 relations and ideas, G3 interpretations and concepts) and `builder`. A module has exactly one kind. *Recommended as listed*; the kind decides which contract parts are required (a builder has no gates and no event family; a miner must declare a quality regime).

### Gate policies

6. **Two kinds of gate; policies apply to decision gates [confirm].** A *decision gate* is an act by an actor that binds later stages (PRESS confirmation, calibration label, disagreement resolution, audit label, link confirmation, relation or idea confirmation, review). A *computed gate* is a condition the platform evaluates (protocol `ready`, calibration sensitivity, κ floor, audit ceiling, round sequencing). A gate policy is declared per decision gate as one of `human`, `agent_audit(fraction, minimum)` or `agent`. Computed gates keep their thresholds as platform constants (decision 37 item 4) and their enforcement (`off | advisory | enforced`) is set by the rigor-mode preset only. *Recommended.* Making thresholds protocol fields would reverse decision 37 item 4 and change every `P@`.

7. **Per protocol, hashed, amendable; tightening flags, never stales [confirm].** Options for scope: (a) per project, in the protocol; (b) per run. *Recommended (a)*: `ProtocolSpec.gate_policies: GatePolicies | None = None`, in `AMENDABLE_FIELDS` and `_OMITTED_WHEN_NONE`, so existing `P@` ids are unchanged. When absent, the effective policy is the preset of the project's rigor mode, which is fixed at `project.created`. A run that departs from the policy is a deviation (R-14). Blast radius: an amendment that tightens a gate (agent → agent_audit → human) marks earlier acts at that gate that the new policy would not have accepted as `below-policy` (computed on read; `check` finding `gate-below-policy`, error in systematic, warning otherwise); loosening stales nothing. No act becomes stale for re-screening: decision 50 holds (only R-15 stale rules cause re-screening).

8. **Floors and presets [confirm].** Each decision gate declares a *floor*, the weakest policy it may ever take. The presets reproduce today's behaviour exactly (table below). A `gate_policies` entry below the floor is a protocol error; below the mode's preset it is a readiness error in `systematic`, a gap (`check --promote-to`) in `pilot`, and allowed in `exploratory`. *Recommended.* An autonomous factory is then an exploratory project whose policy sets every gate with an agent floor to `agent`.

9. **`agent_audit` is the G1 second-agent confirmation, with its missing audit [confirm].** The pilot rule of slice-3a ruling 3 is the policy `agent_audit` on gate `reference.link_confirm`. Its audit (slice-3a open question 2) is the generic gate audit: a human labels a recorded random sample of `max(ceil(fraction·N), minimum)` agent acts at that gate (capped at N), using the `audit_size` rule of decision 37 item 3. Preset parameters: fraction 0.1, minimum 20. A missing audit is a `gate-audit-missing` finding (warning in pilot); the ceiling is `GATE_AUDIT_ERROR_CEILING = 0.05` (advisory in pilot). *Recommended.* Behaviour of `reference_resolve` is unchanged; only the new finding appears.

10. **Autonomy label is computed on read, separate from epistemic class [confirm].** Options: (a) a stored field on output events; (b) computed: an act's autonomy is `human`, `audited-agent` (agent act at a gate whose policy is `agent_audit` and whose audit sample has been drawn) or `agent`, from the act's actor kind (on every event) and the policy in force under the act's protocol version; an output's autonomy is the weakest autonomy of the acts its module declares as its basis (`autonomy_acts` hook). Reuse of slice-3c's epistemic class (c) was considered: class answers *what kind of statement* a record is, autonomy *who passed the gate*; they are orthogonal. *Recommended (b)*: no event change, and the label follows a policy amendment. Default views keep every autonomy level, but every builder statistic carries a count per level (slice-3b ruling 14 pattern), and `factory report methods` states the policy and the counts, so outputs from different levels are never mixed silently.

### Miners

11. **Miner specification [confirm].** A miner is `MinerSpec(name, version, selector, fields, evidence, procedure, regime, report)`, canonicalised and hashed (`miner_digest`, first 16 hex of SHA-256 over canonical JSON with prose removed, as `strip_prose`). Code packs (`ml-benchmark@1`, `contribution@1`) are *built-in miners*: a `MinerSpec` is derived from each `Pack` and compiling it back yields an equal `Pack` (tested). Registered miners are data recorded by `miner.registered`; their names match `^m-[a-z0-9]+(?:-[a-z0-9]+)*$`, a namespace no built-in pack uses, so the scope of an extraction event stays a pure function of its `pack` (G2-A ruling 1 extended: `None` → evidence, `contribution` → contribution, `m-…` → that miner). *Recommended.*

12. **Field kinds map onto the existing verifiers [confirm].** The menu and its verifiers:

| Field kind | Compiles to (`FieldDef`) | Verifier (existing code) |
|---|---|---|
| `number(unit_family, units)` | `kind=number`, `check=number` | `extraction/numbers.py` (`numbers_in`, `parse_printed`, `canonical`) through `extraction/verify.py::verify_field` |
| `integer` | `kind=integer`, `check=number` | as `number`, family `count` |
| `enum(values)` | `kind=text`, `check=none`, `allowed=values` | `services/extraction_verify.py` (`value-not-allowed` after `normalise_for`) |
| `quote` | `kind=text`, `check=text-in-quote` | `document/quotes.py::quote_in_element` (via `verify._text_in`) |
| `citation(patterns)` | `kind=text`, `check=text-in-quote` + kind check | `extraction/citations.py::citation_markers` on the verified quote (at least one marker) |
| `anchor(kinds)` | `kind=text`, `check=none` + kind check | the pinned conversion's `Manifest` (`document/anchors.py`): anchor exists and its `AnchorKind` is listed |
| `work_ref(entry)` | `kind=integer`, `check=none` + kind check | G1: ordinal exists in the work's current reference extraction (`services/references.py::current_extraction`); the link state decides `stated` versus `inferred` |
| `work_ref(title)` | `kind=text`, `check=text-in-quote` + kind check | `references/match.py::match_title` against corpus works: `title-exact` resolves, `title-fuzzy` is `inferred` |

Kind checks run as G2-A's `ExtraCheck` hooks. `bool` is expressed as `enum(("yes","no"))`. Free `text` with `check=none` stays legal only in built-in packs (listed as `unverified` by `factory modules`); a registered miner with such a field is refused. Every record of a registered miner carries at least one verified quote, and an `enum` field carries an evidence quote (verified verbatim; its meaning is checked by the audit, which weights enum fields first). *Recommended.*

13. **Selectors never name anchors [confirm].** A selector is `(population, elements, heading_patterns, max_units)`: a named population computed by the platform (`included-final`, `included-ta`, `included-ft`, `with-references`, `corpus`), anchor kinds to present (`AnchorKind` values; empty = whole document), and case-insensitive patterns on the normalised text of the enclosing section heading. It is evaluated on the pinned conversion, so section naming survives converter versions as long as heading text does; a new conversion makes the unit's records stale (plan-D ruling 5). Options rejected: anchor lists (change with converter version, decision 53) and agent-chosen sections (unrecorded selection). *Recommended.*

14. **Record identity [confirm].** A mined record is keyed by `(miner name, miner version, miner digest, conversion id, row_key)`. The conversion id already folds in document hash and converter version, so the key is project-independent. *Recommended.*

15. **Registration before run; protocol listing before tasks [confirm].** Options: (a) `miner.registered` (immutable; a change is a new version) and a protocol entry in a new section `miners: tuple[MinerUse, ...] | None` (`name`, `version`, `dual_extract_sample`, `audit_fraction`, `audit_minimum`, `evidence: bool`), amended in before the first task; (b) registration alone suffices for exploratory runs. *Recommended (a)*: pre-registration (I7) holds for every miner; the amendment is cheap, scoped (it touches `other_changes` only, so decision 50 stales nothing) and makes the miner part of `P@`.

16. **Calibration of agent-authored miners [confirm].** Lifecycle `registered → calibrating → calibrated | failed`, plus `retired` from any state (computed from events; R-52: failed and retired miners stay recorded and are reported). The platform draws a calibration sample (recorded seed) of `calibration_size` units from the selector population (default 10 units, floor 5 in pilot, 10 in systematic); a human records gold records for those units in the CLI; one agent pass from a session that is neither the proposer's nor a session that labelled runs the units; the platform scores record recall (gold records matched by `row_key`), per-field agreement on matched records (normalised values) and quote verification rate. Thresholds are declared in the spec (`recall_min`, `field_agreement_min`) and may not be below platform floors (0.8 and 0.9 in pilot; 0.9 and 0.95 in systematic). `evidence: true` is refused until the miner's latest calibration in this project passed. Built-in miners are exempt (their regime is plan D's dual extraction and audit). *Recommended.* Cost bound: `max_units` in the selector, and calibration runs only on the sample.

17. **Builders read exact miner versions [confirm].** Options: (a) latest version only; (b) explicit union; (c) a builder declares the `(miner, version)` pairs it reads, and records of any other version are invisible to it; `check` lists records of undeclared versions as `miner-version-unread`. *Recommended (c)*: the evidence-report rule "a statistic names the status filter it used" extended to versions.

### Shared mining layer

18. **The shared mining store is a projection across projects [confirm].** Options: (a) a read-only SQLite projection at `<root>/.mining/shared.sqlite` (git-ignored), folded by a cross-project projector from each project's `miner.*`, `extraction.*` and `mine.imported` events, incremental per event file as `Index.sync`; (b) its own event log. *Recommended (a)*: events stay per project (I1, IDEA-36 rigour notes); (b) would be a second source of truth written from several projects. The store holds keys, digests, verification results, pass identities, final status and supersession, never document text (I9).

19. **Import is an event; re-verification is mandatory [confirm].** `mine.imported` in the importing project names the source project, the source extraction ids, both pass identities and the miner digest. Import is refused unless (i) the importing project registers the same miner digest, (ii) it holds the same conversion id in its own library, and (iii) every imported field re-verifies against that conversion. Imported records count as one pass (`origin=imported`), or as agreed dual records when the source had two agreeing passes, which `independence_counts` and methods report separately. A protocol may decline imports (`MinerUse.imports: allow | deny | audit`; `audit` forces imported records into the audit population). *Recommended.*

20. **Correction in the source propagates as a flag, not a change [confirm].** When a source record is superseded or becomes stale after import, the importing project's copy is `source-superseded` on read (computed from the shared store) and `check` reports it; nothing in the importing project changes until a human or agent re-imports or re-mines. Calibration does not travel: evidence status needs a calibration recorded in the importing project. *Recommended.*

### Quality code

21. **One implementation of pass membership, agreement independence and audit lifecycle [confirm].** `_is_pass_session` (in `agreement.py` and `audit.py`), `calibration.is_pass_session`, `extraction.is_extraction_session`, `extraction.screening_session` and `screening._is_extraction_session` become one service, `services/passes.py::memberships(project, session) -> frozenset[PassMembership]` with predicates derived from module declarations; the independence refusal of `agreement._refuse_shared_sessions/_refuse_shared_models` and `extraction_agreement._refuse_shared` becomes `passes.refuse_shared(project, module, ...)`; the audit lifecycle shared by `audit.py` and `extraction_audit.py` (population digest, draw, human gate, report with ceiling and enforcement) becomes `services/audit_core.py`. Pure statistics move from `screening_stats.py` to `factory/quality/stats.py` with the old names re-exported. The task-kind tables `_KINDS` and `EXTRACT_KINDS` become a `TaskKindRegistry` built from module declarations; kind strings are unchanged. The independence decision is one pure function over the sessions and models each module collects (screening from `pass_sessions`, extraction from the log, as today), so each module keeps its own evidence of joins. Human-act surfaces ask for membership in a pass of *any* module: this extends what `extraction_audit._gate` and `mcp/server.py::_refuse_pass_session` already do to screening's calibration, resolution and audit relays, so a session that joined an extraction pass can no longer relay a screening label. *Recommended*: this is migration step 0; that tightening is its only behaviour change.

## Design

### Package layout

```
platform/src/factory/
  modules/                 pure declarations (no I/O, no service imports)
    contract.py            ModuleKind, ArtifactKind, ArtifactSpec, EventFamily, GateSpec,
                           GateKind, PolicyKind, GatePolicy, QualityRegime, CheckRule,
                           StrategySpec, ModuleSpec, StageModule (Protocol), CheckHit,
                           MethodsSection, AutonomyAct
    registry.py            ModuleRegistry, TaskKindRegistry, ownership checks
    presets.py             PRESETS: RigorMode -> GatePolicies; floors
  mining/                  pure miner model and compilation
    spec.py                FieldKindSpec variants, Selector, EvidenceRule, MinerRegime, MinerSpec
    compile.py             compile_miner(spec) -> Pack; miner_of_pack(pack) -> MinerSpec; digest
  quality/
    stats.py               cohen_kappa, kappa_by_criterion, sensitivity_specificity, audit_size,
                           draw_audit, audit_error_rates (moved from services/screening_stats.py)
  services/
    passes.py              memberships, is_pass_session, refuse_shared (dedup)
    audit_core.py          generic audit lifecycle used by audit.py, extraction_audit.py, gate audits
    gates.py               effective_policy, gate_acts, autonomy_of, below_policy, gate audit
    modules/               one declaration per built module, binding services to the contract
      __init__.py          default_modules() -> ModuleRegistry
      scoping.py search.py dedup.py screening.py fulltext.py conversion.py
      extraction.py references.py contributions.py (when G2 is built) evidence.py
    miners.py              register, lifecycle, calibration
    mining.py              mine_next, mine_record over the plan-D engine (scope = miner)
    shared_mining.py       shared store projector, import, source-superseded
```

### Core types (exact signatures; plans consume them)

```python
class ModuleKind(StrEnum): CORE, SCOPING, RETRIEVAL, TRANSFORM, FILTER, MINER, PROPOSAL, BUILDER
class GateKind(StrEnum): DECISION = "decision"; COMPUTED = "computed"
class PolicyKind(StrEnum): HUMAN = "human"; AGENT_AUDIT = "agent_audit"; AGENT = "agent"
class Autonomy(StrEnum): HUMAN = "human"; AUDITED_AGENT = "audited-agent"; AGENT = "agent"

@dataclass(frozen=True)
class GatePolicy:
    kind: PolicyKind
    fraction: float | None = None      # agent_audit only
    minimum: int | None = None         # agent_audit only

@dataclass(frozen=True)
class GateSpec:
    gate_id: str                       # "<module>.<act>", e.g. "reference.link_confirm"
    kind: GateKind
    act_events: tuple[str, ...]        # event types that record an act at this gate
    floor: PolicyKind                  # weakest policy ever permitted (decision gates)
    rigour: tuple[str, ...]            # R-ids and decisions that fix the floor

@dataclass(frozen=True)
class EventFamily:
    types: tuple[str, ...]             # exact event type names owned
    note: str = ""                     # e.g. "historical name: all field miners write it"

@dataclass(frozen=True)
class QualityRegime:
    passes: Literal[1, 2]
    independence: Literal["session-and-model", "none"]
    agreement_unit: str                # "outcome", "field-value", "link"
    calibration: Literal["human-labelled", "none"]
    audit: Literal["agreed-sample", "gate-sample", "none"]
    staleness: tuple[str, ...]         # "amendment", "document-version", "conversion", "references"

@dataclass(frozen=True)
class CheckRule:
    code: str
    levels: tuple[Severity | None, Severity | None, Severity | None]   # E, P, S

@dataclass(frozen=True)
class StrategySpec:
    name: str; version: str; skill: str | None

@dataclass(frozen=True)
class ModuleSpec:
    name: str
    kind: ModuleKind
    inputs: tuple[ArtifactKind, ...]
    outputs: tuple[ArtifactKind, ...]
    events: EventFamily
    task_kinds: tuple[str, ...]
    protocol_sections: tuple[str, ...]
    gates: tuple[GateSpec, ...]
    regime: QualityRegime | None
    checks: tuple[CheckRule, ...]
    strategies: tuple[StrategySpec, ...]

class StageModule(Protocol):
    spec: ModuleSpec
    def hits(self, project: Project) -> list[CheckHit]: ...
    def methods(self, project: Project) -> MethodsSection | None: ...
    def autonomy_acts(self, project: Project) -> Iterable[AutonomyAct]: ...
```

`ArtifactKind` enumerates the id families of 00-system §3 and the slice specs (`question`, `protocol`, `seed`, `query`, `search-run`, `work`, `merge`, `decision`, `task`, `fetch`, `attempt`, `document`, `conversion`, `record`, `claim`, `reference-extraction`, `snowball-round`, `relation`, `idea`, `interpretation`, `concept`, `miner`, `report`). `ModuleRegistry` validates on construction: unique module names; each catalog event type owned by exactly one module; each task kind, check code, protocol section and gate id owned by exactly one module; every decision gate has `act_events` registered in the catalog.

### Gate inventory and presets

Decision gates of the built and specified slices. Presets reproduce the code at `06b4f40` and the adopted rulings of 3a–3c; floors follow the Decided entries.

| Gate | Act events | Floor | Exploratory | Pilot | Systematic | Source |
|---|---|---|---|---|---|---|
| `protocol.press_confirm` | `protocol.press_confirmed` | human | human | human | human | R-61 |
| `screening.calibration_label` | `calibration.labelled` | human | human | human | human | decision 37 items 5, 6 |
| `screening.resolve` | `screening.disagreement_resolved` | human | human | human | human | decision 37 item 6 |
| `screening.audit_label` | `audit.labelled` | human | human | human | human | decision 37 item 6 |
| `extraction.resolve` | `extraction.resolved` (all field-miner scopes) | human | human | human | human | decision 51 |
| `extraction.audit_label` | `extraction.audit_labelled` | human | human | human | human | decision 51 |
| `reference.link_confirm` | `reference.resolution_decided` (binding) | agent_audit | human | agent_audit(0.1, 20) | human | slice-3a ruling 3; ruling 9 |
| `lineage.relation_confirm`, `lineage.idea_confirm` | G2-C events | human | human | human | human | slice-3b ruling 3 |
| `intuition.review`, `intuition.source_approve`, `intuition.uses_confirm` | G3 events | human | human | human | human | slice-3c |
| `miner.calibration_label` | `miner.calibration_labelled` | human | human | human | human | ruling 16 |
| `mine.resolve` (registered miners) | `extraction.resolved` with `pack` = `m-…` | agent | agent_audit(0.1, 20) | human | human | ruling 16; new |

`exploratory` may set `mine.resolve` to `agent`, the only gate today whose floor permits it. Every other autonomy beyond the table needs a new decision lowering a floor; the model is ready for it.

Computed gates and their preset enforcement: protocol `ready` (off/enforced/enforced), calibration sensitivity (none; 0.9; 0.95, as `CALIBRATION_SENSITIVITY`), κ floor (protocol's `kappa_enforced`), screening audit ceiling (off/advisory/enforced), extraction audit ceiling (off/advisory/enforced), gate audit ceiling (off/advisory/enforced), miner calibration floors (ruling 16). The constants stay where they are (`AUDIT_ERROR_CEILING`, `CALIBRATION_SENSITIVITY`, `EXTRACTION_ERROR_CEILING`); `presets.enforcement(mode, gate_id)` replaces the inline `RigorMode` tests in `audit.py`, `extraction_audit.py`, `reference_resolve.py` and `calibration.py`.

### Effective policy and autonomy (services/gates.py)

```python
def effective_policy(project: Project, gate_id: str, *, protocol_id: str | None = None) -> GatePolicy
def require_gate(project: Project, actor: Actor, gate_id: str) -> GatePolicy   # raises FactoryValidationError
def gate_acts(project: Project, gate_id: str) -> list[GateAct]                 # from act_events, ULID order
def autonomy_of(project: Project, act: GateAct) -> Autonomy
def below_policy(project: Project) -> list[GateAct]
def gate_audit_sample(project: Project, actor: Actor, gate_id: str, *, random_seed: int | None = None) -> GateAuditSampled
def gate_audit_record(project: Project, actor: Actor, audit_id: str, act_event_id: str, correct: bool, note: str | None, channel: Channel) -> str
def gate_audit_report(project: Project, gate_id: str) -> GateAuditReport | None
```

`require_gate` refuses an agent act at a `human` gate (field `actor`, reason names the gate and policy), an agent act by the proposer of the item at any gate (R-51, via the module's `proposer_of` hook where one exists), and an MCP relay of a human act from a pass session (derived from `passes.memberships`, replacing the per-tool lists of decisions 43 and 48 for gates). Existing per-service checks call `require_gate` and keep their messages; the existing tests pin the messages.

### Miner specification (factory/mining/spec.py)

```python
@dataclass(frozen=True) class NumberKind:   unit_family: UnitFamily; units: tuple[str, ...] = ()
@dataclass(frozen=True) class IntegerKind:  pass
@dataclass(frozen=True) class EnumKind:     values: tuple[str, ...]
@dataclass(frozen=True) class QuoteKind:    pass
@dataclass(frozen=True) class CitationKind: patterns: tuple[str, ...]
@dataclass(frozen=True) class AnchorKindRef: kinds: tuple[AnchorKind, ...]
@dataclass(frozen=True) class WorkRefKind:  by: Literal["entry", "title"]
@dataclass(frozen=True) class Unverified:   pass        # built-in packs only
FieldKindSpec = NumberKind | IntegerKind | EnumKind | QuoteKind | CitationKind | AnchorKindRef | WorkRefKind | Unverified

@dataclass(frozen=True) class MinerField: name: str; group: str; kind: FieldKindSpec; required: bool = False
@dataclass(frozen=True) class Selector:   population: Population; elements: tuple[AnchorKind, ...] = (); heading_patterns: tuple[str, ...] = (); max_units: int | None = None
@dataclass(frozen=True) class EvidenceRule: min_quotes_per_record: int = 1; enum_needs_quote: bool = True
@dataclass(frozen=True) class MinerRegime: passes: Literal[1, 2]; calibration_size: int; recall_min: float; field_agreement_min: float
@dataclass(frozen=True) class MinerSpec:
    name: str; version: int; selector: Selector; fields: tuple[MinerField, ...]
    row_key_fields: tuple[str, ...]; row_anchor_fields: tuple[str, ...]
    conditionals: tuple[Conditional, ...]; evidence: EvidenceRule
    procedure: str            # skill name; its reference is computed by services/skills.py
    regime: MinerRegime; rationale: str = ""    # prose, not hashed

def compile_miner(spec: MinerSpec) -> Pack
def miner_of_pack(pack: Pack, selector: Selector, regime: MinerRegime) -> MinerSpec
def miner_digest(spec: MinerSpec) -> str
def kind_checks(spec: MinerSpec) -> ExtraCheck            # G2-A hook type
```

### Generic mine path (services/mining.py)

`mine_next(project, actor, miner, label) -> ExtractNext` and `mine_record(project, actor, task_id, rows, *, finish, reason, supersedes) -> ExtractResult` wrap G2-A's `next_unit`/`record_unit` with `scope=miner`, the compiled pack and `kind_checks`. Task kinds `mine_a`, `mine_b` (the miner is in the task content; `TASK_KIND_RE` admits no digits or hyphens, so kinds per miner are not possible). The population is the selector's; the task content lists the selected anchors. Agreement, resolution, audit and staleness are plan D's by scope. `independence_counts` and every plan-E read keep reading the evidence scope only, so the evidence report is unaffected unless a builder declares a registered miner (ruling 17).

## Events (schema 1)

New types only; no existing type changes.

| Type | Payload (key fields) | Actor |
|---|---|---|
| `miner.registered` | `miner_id` (`mnr_<ULID>`), `name`, `version`, `digest`, `spec_blob`, `proposer_kind`, `imported_from: {project, digest} \| None` | agent or human |
| `miner.calibration_drawn` | `calibration_id` (`mcl_<ULID>`), `name`, `version`, `units: tuple[(work_id, conversion_id)]`, `random_seed`, `population_digest` | human |
| `miner.calibration_labelled` | `calibration_id`, `work_id`, `gold_rows` (verified as records are), `channel` | human |
| `miner.retired` | `name`, `version`, `reason` | human or agent |
| `mine.imported` | `import_id` (`imp_<ULID>`), `source_project`, `miner`, `digest`, `items`: per record the source extraction ids, `work_id`, `conversion_id`, `row_key`, the verified stored fields (values, anchors, quotes, as `extraction.recorded` stores them), the source status (`agreed`, `resolved`, `single`) and `source_passes` | human or system |

`mine.imported` is self-contained: replaying the importing project never reads another project's log, so its rows are in the event itself (quotes only, as on `extraction.recorded`; I9 holds).
| `gate.audit_sampled` | `audit_id` (`gau_<ULID>`), `gate_id`, `act_event_ids`, `random_seed`, `population`, `population_digest`, `protocol_id` | human |
| `gate.audit_labelled` | `audit_id`, `act_event_id`, `correct`, `note`, `channel` | human |

Calibration passes and scores are not events: the calibration pass is an ordinary pass on `mine_a` tasks restricted to the calibration units (tasks carry `calibration_id` in content), and the score is computed on read (R-05).

## Index tables (projector only)

`miners` (name, version, digest, miner_id, registered_by_kind, proposer_session, spec_blob, retired), `miner_calibrations` and `miner_calibration_labels`, `mine_imports` and `mine_import_items`, `gate_audits` and `gate_audit_items`. Extraction tables already carry `scope` and `pack`; registered miners use the miner name as scope key, so no column changes. `PROJECTION_VERSION` bumps in plans M-B, M-D and M-E. The shared store has its own schema and version (`SHARED_PROJECTION_VERSION`) and its own state hash.

## MCP tools and CLI

MCP: `mine_next`, `mine_record`, `mine_status` (counts per miner and status; pass sessions see their own pass only), `miner_register`, `miner_list`; refused to pass sessions as decision 43 extends: `gate_status`. Human acts are CLI-first and relayable over MCP as decision 37 item 6: `miner calibrate draw|label`, `gate audit sample|label`, `mine import`. CLI: `factory modules`, `factory gates`, `factory miner register|list|retire|calibrate`, `factory mine status|import`, `factory shared rebuild|status`.

## Check findings

`gate-below-policy` (E warning, P warning, S error); `gate-audit-missing` (none, warning, error); `gate-audit-error-high` (none, warning, error); `miner-uncalibrated-evidence` (error in all modes; cannot arise through the tools, guards replay of hand-edited logs); `miner-calibration-failed` (warning); `miner-version-unread` (warning); `mine-source-superseded` (warning, warning, error); `mine-import-unverified` (error). Each is declared by its module; `check.LEVELS` becomes the union of declared `CheckRule`s.

## Rigour requirements

Proposed additions (numbers assigned on acceptance):
- **R-xx(a) Declared autonomy.** Every decision gate has a declared policy (explicit or preset) recorded with the protocol; every output's autonomy is computable from events; methods state the policy and per-level counts.
- **R-xx(b) Verifiable miners.** A registered miner uses only verifiable field kinds; every record carries at least one verified quote; free text is refused.
- **R-xx(c) Calibrated before evidence.** A registered miner's records count as evidence only after a human-labelled calibration in the same project passed declared thresholds above platform floors; the proposer neither runs the calibration pass nor labels it.
- **R-xx(d) Reuse is recorded and re-verified.** An imported record names its source and is re-verified against the importing project's own conversion; it never counts as an independent pass it did not have.

Existing: R-04 (miner registration and imports carry provenance; agent-authored specs record the proposing session), R-05 (calibration scores, autonomy counts and import counts computed), R-13/R-45 (miners listed in the protocol before tasks), R-14/R-15 (policy and miner amendments with blast radius), R-33/R-51 (independence derived from memberships; proposer ≠ evaluator), R-44 (number kind), R-47 (no text in the shared store), R-52 (failed and retired miners reported).

## Migration path

Ordered so that each step ships working software and replays every existing log unchanged. Invariants of every step: no event type renamed; no payload field removed or made required; existing tests pass unedited except moved imports and the `PROJECTION_VERSION` pin; `factory rebuild` on the fixture logs gives the same state hash apart from new empty tables.

| Step | Plan | What moves | Why in this order |
|---|---|---|---|
| 0 | M-A | Quality dedup (ruling 21): `factory/quality/stats.py`; `services/passes.py` replacing five pass-session helpers; `services/audit_core.py` under `audit.py` and `extraction_audit.py`; `TaskKindRegistry` replacing `_KINDS`, `EXTRACT_KINDS` and the probe kinds | Pure refactor with the strongest test cover; every later step uses these |
| 1 | M-A | Contract types, `ModuleRegistry`, ownership tests. Declarations for **scoping** (question, seeds, probe, protocol) and **retrieval** (search, chase, snowball) and **dedup** | Smallest quality regimes; only checks and methods move |
| 2 | M-A | **Screening** (filter) declared; `check` and `methods` composed from module hooks with byte-identical output | Largest check surface; proves composition |
| 3 | M-A | **Full-text acquisition** and **conversion** (transform), **extraction** (miner, evidence scope), **evidence report** (builder) | Depends on step 0's audit core |
| 4 | M-B | Gate policies; **references** declared with its `link_confirm` gate | References is the first gate whose preset is not `human` |
| 5 | M-C | Miner spec; built-in packs as miners; generic `mine_*` path | Needs G2-A merged |
| 6 | M-C or later | **Contributions** (G2) and the G2/G3 proposal modules declared when their code lands; until then their specs are written against this contract and their gates appear in the preset table | Do not block G2/G3 |
| 7 | M-D | Registered, agent-authored miners and calibration | Needs the generic path |
| 8 | M-E | Shared mining store and import | Needs registered miners and digests |

## Acceptance criteria

1. **Ownership.** Every event type in `default_catalog()`, every task kind, every protocol section, every check code and every gate id is owned by exactly one registered module (`test_registry_ownership`).
2. **Dedup.** `grep` finds one definition each of pass-session membership, shared-session/model refusal, audit draw with population digest, and no `_KINDS`/`EXTRACT_KINDS` literal outside the registry; the decision-37, decision-43 and decision-48 refusal suites pass unedited.
3. **Replay.** Rebuilding the fixture logs of slices 1, 2 and G1 after each plan gives identical rows in every pre-existing table.
4. **Byte-identical reports.** `check`, `methods`, PRISMA and the evidence report render byte-identically for the existing acceptance projects after M-A and M-B.
5. **Presets.** For each rigor mode, the preset reproduces today's accept/refuse behaviour at every decision gate (parametrised test over the gate table); a protocol without `gate_policies` keeps its `P@`.
6. **Policy amendment.** Tightening `reference.link_confirm` from `agent_audit` to `human` lists earlier second-agent confirmations as `gate-below-policy` and stales no screening decision.
7. **Gate audit.** In pilot, second-agent confirmations without a gate audit raise `gate-audit-missing`; a drawn and labelled audit above the ceiling raises `gate-audit-error-high`.
8. **Autonomy.** Every row of `factory gates`, the methods text, and every builder statistic over outputs of a gate whose effective policy is not `human` carry per-autonomy counts; a link confirmed by a human after an agent proposal is `human`.
9. **Built-in round trip.** `compile_miner(miner_of_pack(p, …)) == p` for `ML_BENCHMARK_V1` and `CONTRIBUTION_V1`.
10. **Field kinds.** Each kind accepts a correct value and rejects the canonical wrong value with its verifier's reason: number not in quote, enum outside values, quote not in element, citation without marker, anchor of wrong kind, entry ordinal absent, title fuzzy (accepted as inferred).
11. **Registration.** A miner with a free-text field, an anchor in its selector, or a name outside the `m-` namespace is refused; `mine_next` before the protocol lists the miner is refused on field `miners`; a second registration of the same name and version with a different digest is refused.
12. **Calibration.** The proposer's session cannot claim a calibration task or label; a miner below its threshold is `failed` and `evidence: true` is refused; a passing miner may be admitted by amendment; failed and retired miners appear in methods.
13. **Separation.** Records of a registered miner never change `final_rows`, `grouped_rows`, `independence_counts` or the evidence report of the evidence scope.
14. **Import.** Import into a project lacking the conversion, or with a different digest, is refused; a quote altered in the source log fails re-verification; a superseded source record becomes `source-superseded` in the importer after `factory shared rebuild`.
15. **Scale (slow).** The shared projector folds 10^5 records from 20 projects incrementally (second sync applies only new files) and answers an import lookup by `(miner, version, digest, conversion_id)` through an index without a full scan; services never load all records into memory (iterators over SQL).

## Proposed decisions (numbers assigned on acceptance)

- **Stage-module contract** — rulings 1–5 and 21.
- **Gate policies and autonomy** — rulings 6–10, with the preset table as the record of today's behaviour.
- **Miners** — rulings 11–17.
- **Shared mining layer** — rulings 18–20.

## Proposed sub-plans

1. `2026-11-05-modules-a-contract-quality.md` — migration steps 0–3.
2. `2026-11-05-modules-b-gate-policies.md` — step 4.
3. `2026-11-05-modules-c-miner-spec.md` — step 5 (requires G2-A merged).
4. `2026-11-05-modules-d-authored-miners.md` — step 7.
5. `2026-11-05-modules-e-shared-store.md` — step 8.

## Open questions

1. Lowering a floor (for example letting an agent resolve screening disagreements under `agent_audit` in exploratory) is now expressible; which floors, if any, should be lowered is a decision for the researcher after the pilot measures agent error at those gates.
2. Whether a calibration recorded in one project may support evidence status in another project for the same miner digest (ruling 20 says no); revisit with data from slice 4.
3. Hypothesis registration (R-50) fits as a `proposal` module whose registration gate is `human` and whose test results are a `miner` on experiment outputs; to be checked when slice 6 is specified.
4. A builder that reads several projects' records through the shared store (cross-project evidence tables) is not in scope; it would need a decision on comparability keys across protocols (IDEA-36 open question).
