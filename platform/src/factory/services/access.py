"""Who may do what (slice 5 rulings 9 and 10; the spec's permissions table).

`authorize` decides; `mcp/authz.py` and `services/cli_access.py` enforce.

Invariants:
- Deny by default: a role not listed holds nothing, and a principal with no role holds nothing.
- An agent acts for its principal and holds at most the principal's permissions, minus
  `HUMAN_ONLY`, whatever the role. A `system` actor is held to the same limit.
- `GATED_AGENT_ACTS` lifts that subtraction for an agent on those tools alone, never the cap: the
  principal's role must still hold the permission, so an agent never does what its person cannot.
- `lab:admin` comes from the lab `admin` role alone, never from a project role, and needs a lab.
- With a lab given, a principal the registry does not hold as active holds nothing.
- A refusal writes nothing and is one issue on field `permission`.
- A `private` project is read by its members alone. On a `lab` project an active lab member
  with no grant is an `observer`; that needs the lab, so it is never so without one.
- A project is `governed` once it is hosted or a grant has counted. Before that whoever runs
  the process is the user, so a service's role check passes (stage 0, acceptance 1).
"""

from collections.abc import Iterator, Mapping
from enum import StrEnum
from functools import cache
from typing import Final

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, ActorKind
from factory.index import members as member_index
from factory.index.members import MEMBER_TABLES
from factory.index.project import latest_visibility
from factory.model.lab import LabRole
from factory.model.members import ProjectRole
from factory.model.project import ProjectVisibilitySet, Visibility
from factory.services.context import Principal, Project
from factory.services.lab import Lab, lab_exists, open_lab, payload_of, refuse, user_record
from factory.services.members import roles_of


class Permission(StrEnum):
    PROJECT_READ = "project:read"
    WORK_RUN = "work:run"
    PASS_JOIN_HUMAN = "pass:join-human"
    PROTOCOL_CHANGE = "protocol:change"
    HUMAN_LABEL = "human-act:label"
    HUMAN_CONFIRM = "human-act:confirm"
    REVIEW_DECIDE = "review:decide"
    PROJECT_GOVERN = "project:govern"
    LAB_ADMIN = "lab:admin"


HUMAN_ONLY: frozenset[Permission] = frozenset(
    {
        Permission.HUMAN_LABEL,
        Permission.HUMAN_CONFIRM,
        Permission.REVIEW_DECIDE,
        Permission.PROJECT_GOVERN,
        Permission.PASS_JOIN_HUMAN,
        Permission.LAB_ADMIN,
    }
)
"""What an agent never holds, on any project."""

AGENT_PROPOSES_ONLY: frozenset[Permission] = frozenset({Permission.PROTOCOL_CHANGE})
"""The spec's table gives an agent `protocol:change` as "proposes only", so on a hosted project an
agent is refused it. Unhosted, it keeps the protocol tools it has always had (acceptance 1)."""

GATED_AGENT_ACTS: frozenset[str] = frozenset(
    {"mine_resolve", "reference_decide", "lead_decide", "hypothesis_register", "miner_register"}
)
"""Tools through which an agent acts at a decision gate of slices 6 and M: the gate policy says when
it may, so the human permission is not subtracted. The caller names the tool to `authorize`."""

OPEN_WITHOUT_LAB: frozenset[str] = frozenset({"cli:init"})
"""What a person may do on a root with no lab registry, where nobody can hold `lab:admin`: stage 0
creates its projects freely. On a lab server the row applies, so the caller passes the lab."""

SYSTEM_JOBS: frozenset[str] = frozenset({"cli:commit"})
"""Scheduled jobs of the server, which run as a `system` actor and not for a person (ruling 5). The
row applies when a person runs one."""

_READ = frozenset({Permission.PROJECT_READ})
_CONTRIBUTE = _READ | {Permission.WORK_RUN}
_MAINTAIN = _CONTRIBUTE | {
    Permission.PASS_JOIN_HUMAN,
    Permission.PROTOCOL_CHANGE,
    Permission.HUMAN_LABEL,
    Permission.HUMAN_CONFIRM,
    Permission.REVIEW_DECIDE,
}

_FULL_VIEW_ROLES = frozenset({ProjectRole.OWNER, ProjectRole.MAINTAINER})

ROLE_PERMISSIONS: Mapping[ProjectRole, frozenset[Permission]] = {
    ProjectRole.OWNER: _MAINTAIN | {Permission.PROJECT_GOVERN},
    ProjectRole.MAINTAINER: _MAINTAIN,
    ProjectRole.CONTRIBUTOR: _CONTRIBUTE,
    ProjectRole.SCREENER: _READ | {Permission.PASS_JOIN_HUMAN},
    ProjectRole.OBSERVER: _READ,
}


EXPORT_WORKS_PDFS: Final = "cli:export works --pdfs"
"""The `TOOL_PERMISSIONS` key of an export of works that includes the stored PDFs."""

TOOL_PERMISSIONS: Mapping[str, Permission] = {
    # MCP tools that only read.
    "project_status": Permission.PROJECT_READ,
    "gate_status": Permission.PROJECT_READ,
    "gate_audit_pending": Permission.PROJECT_READ,
    "watch_status": Permission.PROJECT_READ,
    "feed_list": Permission.PROJECT_READ,
    "feed_status": Permission.PROJECT_READ,
    "notice_list": Permission.PROJECT_READ,
    "conclusion_status": Permission.PROJECT_READ,
    "digest_get": Permission.PROJECT_READ,
    "seed_list": Permission.PROJECT_READ,
    "screen_agreement": Permission.PROJECT_READ,
    "report_prisma": Permission.PROJECT_READ,
    "flow_works": Permission.PROJECT_READ,
    "flow_skipped": Permission.PROJECT_READ,
    "flow_trail": Permission.PROJECT_READ,
    "report_methods": Permission.PROJECT_READ,
    "inbox_list": Permission.PROJECT_READ,
    "report_discovery": Permission.PROJECT_READ,
    "report_evidence": Permission.PROJECT_READ,
    "export_bibliography": Permission.PROJECT_READ,
    "trace": Permission.PROJECT_READ,
    "check": Permission.PROJECT_READ,
    "fulltext_status": Permission.PROJECT_READ,
    "document_read": Permission.PROJECT_READ,
    "extract_agreement": Permission.PROJECT_READ,
    "mine_status": Permission.PROJECT_READ,
    "miner_list": Permission.PROJECT_READ,
    "taxonomy_view": Permission.PROJECT_READ,
    "taxonomy_list": Permission.PROJECT_READ,
    "taxonomy_diff": Permission.PROJECT_READ,
    "taxonomy_coverage": Permission.PROJECT_READ,
    "taxonomy_proposals": Permission.PROJECT_READ,
    "taxonomy_agreement": Permission.PROJECT_READ,
    "page_list": Permission.PROJECT_READ,
    "page_brief": Permission.PROJECT_READ,
    "mine_disagreements": Permission.PROJECT_READ,
    "import_status": Permission.PROJECT_READ,
    "import_coverage": Permission.PROJECT_READ,
    "references_status": Permission.PROJECT_READ,
    "references_list": Permission.PROJECT_READ,
    "reference_layer_status": Permission.PROJECT_READ,
    "snowball_compare": Permission.PROJECT_READ,
    "snowball_core_list": Permission.PROJECT_READ,
    "graph_status": Permission.PROJECT_READ,
    "graph_query": Permission.PROJECT_READ,
    "graph_export": Permission.PROJECT_READ,
    "technique_landscape": Permission.PROJECT_READ,
    "technique_view": Permission.PROJECT_READ,
    "technique_neighbors": Permission.PROJECT_READ,
    "technique_gaps": Permission.PROJECT_READ,
    "technique_combinations": Permission.PROJECT_READ,
    "technique_challenges": Permission.PROJECT_READ,
    "lead_candidates": Permission.PROJECT_READ,
    "lead_queue": Permission.PROJECT_READ,
    "lead_stats": Permission.PROJECT_READ,
    "card_view": Permission.PROJECT_READ,
    "interpretation_list": Permission.PROJECT_READ,
    "match_query": Permission.PROJECT_READ,
    "finder_contradictions": Permission.PROJECT_READ,
    "finder_gaps": Permission.PROJECT_READ,
    "library_adoptable": Permission.PROJECT_READ,
    "region_status": Permission.PROJECT_READ,
    "region_query": Permission.PROJECT_READ,
    "hypothesis_view": Permission.PROJECT_READ,
    "decision_list": Permission.PROJECT_READ,
    "decision_view": Permission.PROJECT_READ,
    "develop_render": Permission.PROJECT_READ,
    "progress_status": Permission.PROJECT_READ,
    "selection_resolve": Permission.PROJECT_READ,
    "corpus_search": Permission.PROJECT_READ,
    "chat_verify": Permission.PROJECT_READ,
    "chat_sections": Permission.PROJECT_READ,
    "paper_profiles": Permission.PROJECT_READ,
    "claims_digest": Permission.PROJECT_READ,
    "chat_candidates": Permission.PROJECT_READ,
    "sheet_list": Permission.PROJECT_READ,
    "sheet_view": Permission.PROJECT_READ,
    "answer_list": Permission.PROJECT_READ,
    "answer_view": Permission.PROJECT_READ,
    "chat_request_view": Permission.PROJECT_READ,
    "spar_readings_view": Permission.PROJECT_READ,
    "term_list": Permission.PROJECT_READ,
    "view_onion": Permission.PROJECT_READ,
    "view_coverage": Permission.PROJECT_READ,
    "view_timeline": Permission.PROJECT_READ,
    "view_horizon": Permission.PROJECT_READ,
    "experiment_view": Permission.PROJECT_READ,
    "xrun_list": Permission.PROJECT_READ,
    "whoami": Permission.PROJECT_READ,
    "review_list": Permission.PROJECT_READ,
    "ledger_view": Permission.PROJECT_READ,
    "budget_status": Permission.PROJECT_READ,
    "appraisal_status": Permission.PROJECT_READ,
    # MCP tools that run work. A tool an agent acts through at a gate is here too, a decision
    # included: the gate policy, not this table, says when an agent may pass it.
    "search_run": Permission.WORK_RUN,
    "search_chase": Permission.WORK_RUN,
    "search_slice": Permission.WORK_RUN,
    "dedup_run": Permission.WORK_RUN,
    "ranking_compute": Permission.WORK_RUN,
    "watch_run": Permission.WORK_RUN,
    "feed_run": Permission.WORK_RUN,
    "question_record": Permission.WORK_RUN,
    "seed_add": Permission.WORK_RUN,
    "probe_run": Permission.WORK_RUN,
    "protocol_press_review": Permission.WORK_RUN,
    "screen_next": Permission.WORK_RUN,
    "screen_record": Permission.WORK_RUN,
    "inbox_add": Permission.WORK_RUN,
    "inbox_resolve": Permission.WORK_RUN,
    "grey_search_report": Permission.WORK_RUN,
    "fulltext_fetch": Permission.WORK_RUN,
    "extract_next": Permission.WORK_RUN,
    "extract_record": Permission.WORK_RUN,
    "appraisal_next": Permission.WORK_RUN,
    "appraisal_record": Permission.WORK_RUN,
    "mine_next": Permission.WORK_RUN,
    "mine_record": Permission.WORK_RUN,
    "taxonomy_propose": Permission.WORK_RUN,
    "contribution_next": Permission.WORK_RUN,
    "contribution_record": Permission.WORK_RUN,
    "gate_audit_label": Permission.WORK_RUN,
    "references_extract": Permission.WORK_RUN,
    "reference_layer_next": Permission.WORK_RUN,
    "reference_layer_record": Permission.WORK_RUN,
    "snowball_round": Permission.WORK_RUN,
    "relation_propose": Permission.WORK_RUN,
    "idea_propose": Permission.WORK_RUN,
    "vocabulary_propose": Permission.WORK_RUN,
    "card_create": Permission.WORK_RUN,
    "card_assert": Permission.WORK_RUN,
    "intuition_next": Permission.WORK_RUN,
    "interpretation_record": Permission.WORK_RUN,
    "page_record": Permission.WORK_RUN,
    "sheet_open": Permission.WORK_RUN,
    "sheet_argue": Permission.WORK_RUN,
    "sheet_close": Permission.WORK_RUN,
    "answer_record": Permission.WORK_RUN,
    "chat_request_next": Permission.WORK_RUN,
    "spar_role_next": Permission.WORK_RUN,
    "spar_reading_record": Permission.WORK_RUN,
    "sheet_check": Permission.WORK_RUN,
    "spar_coverage_record": Permission.WORK_RUN,
    "concept_propose": Permission.WORK_RUN,
    "concept_link": Permission.WORK_RUN,
    "contradiction_propose": Permission.WORK_RUN,
    "library_adopt": Permission.WORK_RUN,
    "region_propose": Permission.WORK_RUN,
    "region_propose_member": Permission.WORK_RUN,
    "region_snapshot": Permission.WORK_RUN,
    "lead_record": Permission.WORK_RUN,
    "decision_suggest": Permission.WORK_RUN,
    "hypothesis_draft": Permission.WORK_RUN,
    "hypothesis_review_next": Permission.WORK_RUN,
    "hypothesis_review": Permission.WORK_RUN,
    "label_apply": Permission.WORK_RUN,
    "consolidation_next": Permission.WORK_RUN,
    "consolidation_propose": Permission.WORK_RUN,
    "experiment_design": Permission.WORK_RUN,
    "xrun_register": Permission.WORK_RUN,
    # `GATED_AGENT_ACTS`: the person's permission, which an agent needs its principal to hold.
    "mine_resolve": Permission.HUMAN_LABEL,
    "reference_decide": Permission.HUMAN_CONFIRM,
    "lead_decide": Permission.HUMAN_CONFIRM,
    "hypothesis_register": Permission.HUMAN_CONFIRM,
    "miner_register": Permission.PROTOCOL_CHANGE,
    "review_request": Permission.WORK_RUN,
    # Refused to an agent on a hosted project (`AGENT_PROPOSES_ONLY`).
    "protocol_record": Permission.PROTOCOL_CHANGE,
    "protocol_amend": Permission.PROTOCOL_CHANGE,
    "protocol_deviation": Permission.PROTOCOL_CHANGE,
    # A person's act relayed over MCP: these tools write a human actor.
    "calibration_label": Permission.HUMAN_LABEL,
    "audit_sample": Permission.HUMAN_LABEL,
    "audit_record": Permission.HUMAN_LABEL,
    "screen_check_draw": Permission.HUMAN_LABEL,
    "screen_check_label": Permission.HUMAN_CONFIRM,
    "screen_check_example": Permission.HUMAN_CONFIRM,
    "screen_check_report": Permission.PROJECT_READ,
    "extract_audit_sample": Permission.HUMAN_LABEL,
    "extract_audit_record": Permission.HUMAN_LABEL,
    "miner_calibration_label": Permission.HUMAN_LABEL,
    "notice_assess": Permission.HUMAN_CONFIRM,
    "decision_select": Permission.HUMAN_CONFIRM,
    # Tools added after teams-A was planned, wired at landing.
    "benchmark_ledger_view": Permission.PROJECT_READ,
    "briefing_get": Permission.PROJECT_READ,
    "card_list": Permission.PROJECT_READ,
    "concept_list": Permission.PROJECT_READ,
    "contribution_status": Permission.PROJECT_READ,
    "dedup_merges": Permission.PROJECT_READ,
    "lessons_list": Permission.PROJECT_READ,
    "curation_propose": Permission.WORK_RUN,
    "document_status": Permission.PROJECT_READ,
    "draft_list": Permission.PROJECT_READ,
    "draft_status": Permission.PROJECT_READ,
    "draft_render": Permission.PROJECT_READ,
    "experiment_list": Permission.PROJECT_READ,
    "extraction_status": Permission.PROJECT_READ,
    "hypothesis_list": Permission.PROJECT_READ,
    "idea_list": Permission.PROJECT_READ,
    "lead_list": Permission.PROJECT_READ,
    "manuscript_read": Permission.PROJECT_READ,
    "protocol_view": Permission.PROJECT_READ,
    "question_view": Permission.PROJECT_READ,
    "registry_query": Permission.PROJECT_READ,
    "relation_list": Permission.PROJECT_READ,
    "report_search": Permission.PROJECT_READ,
    "writing_outline": Permission.PROJECT_READ,
    "draft_create": Permission.WORK_RUN,
    "draft_next": Permission.WORK_RUN,
    "draft_reorder": Permission.WORK_RUN,
    "draft_repin": Permission.WORK_RUN,
    "draft_write": Permission.WORK_RUN,
    "draft_verify_next": Permission.WORK_RUN,
    "draft_verify_record": Permission.WORK_RUN,
    "draft_release": Permission.WORK_RUN,
    "manuscript_verify_next": Permission.WORK_RUN,
    "manuscript_verify_record": Permission.WORK_RUN,
    "merge_revert": Permission.WORK_RUN,
    "task_release": Permission.WORK_RUN,
    "mine_import": Permission.HUMAN_CONFIRM,
    "mine_reopen": Permission.HUMAN_CONFIRM,
    "review_decide": Permission.REVIEW_DECIDE,
    # Mutating CLI commands, as `cli:<group> <command>`. Read-only commands have no row, but for
    # the three lists of the admin groups, which are authorised like the rest of those groups.
    "cli:init": Permission.LAB_ADMIN,
    "cli:commit": Permission.LAB_ADMIN,
    "cli:server init": Permission.LAB_ADMIN,
    "cli:user add": Permission.LAB_ADMIN,
    "cli:user deactivate": Permission.LAB_ADMIN,
    "cli:user reactivate": Permission.LAB_ADMIN,
    "cli:user link": Permission.LAB_ADMIN,
    "cli:user list": Permission.LAB_ADMIN,
    "cli:token issue": Permission.LAB_ADMIN,
    "cli:token revoke": Permission.LAB_ADMIN,
    "cli:token list": Permission.LAB_ADMIN,
    "cli:project visibility": Permission.PROJECT_GOVERN,
    "cli:review request": Permission.WORK_RUN,
    "cli:review decide": Permission.REVIEW_DECIDE,
    # Needs no role (plan ruling 4); the service holds it to the requester.
    "cli:review withdraw": Permission.PROJECT_READ,
    "cli:protocol record": Permission.PROTOCOL_CHANGE,
    "cli:protocol amend": Permission.PROTOCOL_CHANGE,
    "cli:protocol deviation": Permission.PROTOCOL_CHANGE,
    "cli:member grant": Permission.PROJECT_GOVERN,
    "cli:member revoke": Permission.PROJECT_GOVERN,
    "cli:member list": Permission.PROJECT_READ,
    "cli:ledger confirm": Permission.PROJECT_READ,
    "cli:ledger confirm-for": Permission.PROJECT_GOVERN,
    "cli:budget set": Permission.PROJECT_GOVERN,
    "cli:inbox add": Permission.WORK_RUN,
    "cli:inbox resolve": Permission.WORK_RUN,
    "cli:inbox withdraw": Permission.WORK_RUN,
    "cli:search chase": Permission.WORK_RUN,
    "cli:dedup pair": Permission.HUMAN_CONFIRM,
    "cli:dedup pairs": Permission.PROJECT_READ,
    "cli:references extract": Permission.WORK_RUN,
    "cli:references scheme record": Permission.HUMAN_CONFIRM,
    "cli:references layers label": Permission.HUMAN_LABEL,
    "cli:snowball run": Permission.WORK_RUN,
    "cli:snowball core mark": Permission.HUMAN_CONFIRM,
    "cli:snowball core unmark": Permission.HUMAN_CONFIRM,
    "cli:snowball core list": Permission.PROJECT_READ,
    "cli:fulltext import": Permission.WORK_RUN,
    "cli:fulltext fetch": Permission.WORK_RUN,
    "cli:fulltext restore": Permission.WORK_RUN,
    "cli:library adopt": Permission.WORK_RUN,
    "cli:library consolidate": Permission.WORK_RUN,
    "cli:library confirm-source": Permission.HUMAN_CONFIRM,
    "cli:library push": Permission.WORK_RUN,
    "cli:project host": Permission.LAB_ADMIN,
    "cli:document convert": Permission.WORK_RUN,
    "cli:watch run": Permission.WORK_RUN,
    "cli:feed run": Permission.WORK_RUN,
    "cli:feed configure": Permission.HUMAN_CONFIRM,
    "cli:feed react": Permission.HUMAN_CONFIRM,
    "cli:feed send": Permission.HUMAN_CONFIRM,
    "cli:feed add": Permission.HUMAN_CONFIRM,
    "cli:feed show": Permission.PROJECT_READ,
    "cli:feed status": Permission.PROJECT_READ,
    "cli:queue": Permission.PROJECT_READ,
    "cli:costs": Permission.PROJECT_READ,
    "cli:runs adopt": Permission.WORK_RUN,
    "cli:queue runs": Permission.PROJECT_READ,
    "cli:queue process": Permission.WORK_RUN,
    "cli:queue advance": Permission.WORK_RUN,
    "cli:conductor start": Permission.WORK_RUN,
    "cli:conductor advance": Permission.WORK_RUN,
    "cli:queue resume": Permission.WORK_RUN,
    "cli:resume": Permission.WORK_RUN,
    "cli:activity": Permission.PROJECT_READ,
    "cli:living snapshot": Permission.WORK_RUN,
    "cli:digest": Permission.WORK_RUN,
    "cli:import bib": Permission.WORK_RUN,
    "cli:import csl": Permission.WORK_RUN,
    "cli:import pdfs": Permission.WORK_RUN,
    "cli:import ris": Permission.WORK_RUN,
    "cli:grey capture": Permission.WORK_RUN,
    "cli:grey contact": Permission.WORK_RUN,
    "cli:import resolve": Permission.WORK_RUN,
    "cli:import admit": Permission.WORK_RUN,
    "cli:import attach": Permission.WORK_RUN,
    "cli:ideas define": Permission.WORK_RUN,
    "cli:interpretations write": Permission.WORK_RUN,
    "cli:cards assert": Permission.WORK_RUN,
    "cli:regions define": Permission.WORK_RUN,
    "cli:regions revise": Permission.WORK_RUN,
    "cli:regions snapshot": Permission.WORK_RUN,
    "cli:runs record": Permission.WORK_RUN,
    "cli:labels apply": Permission.WORK_RUN,
    "cli:labels withdraw": Permission.WORK_RUN,
    "cli:consolidation start": Permission.WORK_RUN,
    # The seed commands name held-out seeds, so they stay with those who may see them (ruling 20).
    "cli:seeds split": Permission.PROTOCOL_CHANGE,
    "cli:seeds explain": Permission.PROTOCOL_CHANGE,
    "cli:seeds admit": Permission.PROTOCOL_CHANGE,
    "cli:protocol confirm-press": Permission.PROTOCOL_CHANGE,
    "cli:miner register": Permission.PROTOCOL_CHANGE,
    "cli:miner retire": Permission.PROTOCOL_CHANGE,
    "cli:miner admit": Permission.PROTOCOL_CHANGE,
    "cli:taxonomy register": Permission.PROTOCOL_CHANGE,
    "cli:taxonomy view": Permission.PROJECT_READ,
    "cli:taxonomy list": Permission.PROJECT_READ,
    "cli:taxonomy diff": Permission.PROJECT_READ,
    "cli:taxonomy agreement": Permission.PROJECT_READ,
    "cli:taxonomy coverage": Permission.PROJECT_READ,
    "cli:taxonomy proposals": Permission.PROJECT_READ,
    "cli:taxonomy derive": Permission.PROJECT_READ,
    "cli:experiments deviation": Permission.PROTOCOL_CHANGE,
    "cli:review deferred list": Permission.PROJECT_READ,
    "cli:review deferred decide": Permission.HUMAN_LABEL,
    "cli:gate audit sample": Permission.HUMAN_LABEL,
    "cli:gate audit label": Permission.HUMAN_LABEL,
    "cli:calibrate draw": Permission.HUMAN_LABEL,
    "cli:calibrate label": Permission.HUMAN_LABEL,
    "cli:screen join": Permission.PASS_JOIN_HUMAN,
    "cli:screen next": Permission.PASS_JOIN_HUMAN,
    "cli:screen record": Permission.PASS_JOIN_HUMAN,
    "cli:screen resolve": Permission.HUMAN_LABEL,
    "cli:audit sample": Permission.HUMAN_LABEL,
    "cli:screen-check band": Permission.HUMAN_LABEL,
    "cli:screen-check tuning": Permission.HUMAN_LABEL,
    "cli:screen-check measure": Permission.HUMAN_LABEL,
    "cli:screen-check label": Permission.HUMAN_CONFIRM,
    "cli:screen-check example": Permission.HUMAN_CONFIRM,
    "cli:audit label": Permission.HUMAN_LABEL,
    "cli:miner calibrate draw": Permission.HUMAN_LABEL,
    "cli:miner calibrate label": Permission.HUMAN_LABEL,
    "cli:mine resolve": Permission.HUMAN_LABEL,
    "cli:mine audit sample": Permission.HUMAN_LABEL,
    "cli:mine audit label": Permission.HUMAN_LABEL,
    "cli:mine request": Permission.HUMAN_CONFIRM,
    "cli:miner reopen": Permission.HUMAN_CONFIRM,
    "cli:layers move": Permission.HUMAN_CONFIRM,
    "cli:extract resolve": Permission.HUMAN_LABEL,
    "cli:extract audit-sample": Permission.HUMAN_LABEL,
    "cli:extract audit-label": Permission.HUMAN_LABEL,
    "cli:appraisal audit-sample": Permission.HUMAN_LABEL,
    "cli:appraisal audit-label": Permission.HUMAN_LABEL,
    "cli:contributions resolve": Permission.HUMAN_LABEL,
    "cli:contributions audit sample": Permission.HUMAN_LABEL,
    "cli:contributions audit label": Permission.HUMAN_LABEL,
    "cli:references decide": Permission.HUMAN_CONFIRM,
    "cli:decide select": Permission.HUMAN_CONFIRM,
    "cli:curation decide": Permission.HUMAN_CONFIRM,
    "cli:curation lessons": Permission.PROJECT_READ,
    "cli:appraisal status": Permission.PROJECT_READ,
    "cli:appraisal sheet": Permission.PROJECT_READ,
    "cli:appraisal agreement": Permission.PROJECT_READ,
    "cli:appraisal audit-report": Permission.PROJECT_READ,
    "cli:curation list": Permission.PROJECT_READ,
    "cli:performance": Permission.PROJECT_READ,
    "cli:pack": Permission.PROJECT_READ,
    "cli:suggest": Permission.PROJECT_READ,
    "cli:inbox prioritise": Permission.HUMAN_CONFIRM,
    "cli:notices check": Permission.WORK_RUN,
    "cli:cards import": Permission.HUMAN_CONFIRM,
    "cli:regions adopt": Permission.HUMAN_CONFIRM,
    "cli:notices assess": Permission.HUMAN_CONFIRM,
    "cli:versions prefer": Permission.HUMAN_CONFIRM,
    "cli:conclusions register": Permission.HUMAN_CONFIRM,
    "cli:conclusions retire": Permission.HUMAN_CONFIRM,
    "cli:import confirm": Permission.HUMAN_CONFIRM,
    "cli:import reject": Permission.HUMAN_CONFIRM,
    "cli:relations confirm": Permission.HUMAN_CONFIRM,
    "cli:relations reject": Permission.HUMAN_CONFIRM,
    "cli:ideas confirm": Permission.HUMAN_CONFIRM,
    "cli:ideas reject": Permission.HUMAN_CONFIRM,
    "cli:ideas merge": Permission.HUMAN_CONFIRM,
    "cli:ideas unmerge": Permission.HUMAN_CONFIRM,
    "cli:interpretations review": Permission.HUMAN_CONFIRM,
    "cli:sheets rate": Permission.HUMAN_CONFIRM,
    "cli:answers rate": Permission.HUMAN_CONFIRM,
    "cli:sheets balance": Permission.HUMAN_CONFIRM,
    "cli:chat request spar": Permission.HUMAN_CONFIRM,
    "cli:chat request ask": Permission.HUMAN_CONFIRM,
    "cli:chat advance": Permission.WORK_RUN,
    "cli:interpretations supersede": Permission.HUMAN_CONFIRM,
    "cli:concepts define": Permission.HUMAN_CONFIRM,
    "cli:concepts source": Permission.HUMAN_CONFIRM,
    "cli:concepts approve": Permission.HUMAN_CONFIRM,
    "cli:concepts reject-source": Permission.HUMAN_CONFIRM,
    "cli:concepts review": Permission.HUMAN_CONFIRM,
    "cli:concepts merge": Permission.HUMAN_CONFIRM,
    "cli:concepts unmerge": Permission.HUMAN_CONFIRM,
    "cli:concept-links confirm": Permission.HUMAN_CONFIRM,
    "cli:concept-links reject": Permission.HUMAN_CONFIRM,
    "cli:vocabulary approve": Permission.HUMAN_CONFIRM,
    "cli:vocabulary reject": Permission.HUMAN_CONFIRM,
    "cli:vocabulary merge": Permission.HUMAN_CONFIRM,
    "cli:vocabulary unmerge": Permission.HUMAN_CONFIRM,
    "cli:cards confirm": Permission.HUMAN_CONFIRM,
    "cli:cards reject": Permission.HUMAN_CONFIRM,
    "cli:contradictions confirm": Permission.HUMAN_CONFIRM,
    "cli:contradictions reject": Permission.HUMAN_CONFIRM,
    "cli:regions review": Permission.HUMAN_CONFIRM,
    "cli:regions add": Permission.HUMAN_CONFIRM,
    "cli:regions remove": Permission.HUMAN_CONFIRM,
    "cli:regions reject": Permission.HUMAN_CONFIRM,
    "cli:regions link": Permission.HUMAN_CONFIRM,
    "cli:leads promote": Permission.HUMAN_CONFIRM,
    "cli:leads park": Permission.HUMAN_CONFIRM,
    "cli:leads discard": Permission.HUMAN_CONFIRM,
    "cli:hypotheses register": Permission.HUMAN_CONFIRM,
    "cli:hypotheses abandon": Permission.HUMAN_CONFIRM,
    "cli:hypotheses conclude": Permission.HUMAN_CONFIRM,
    "cli:models cutoff": Permission.HUMAN_CONFIRM,
    "cli:experiments freeze": Permission.HUMAN_CONFIRM,
    "cli:experiments unlock": Permission.HUMAN_CONFIRM,
    "cli:experiments accept-baseline": Permission.HUMAN_CONFIRM,
    "cli:labels confirm": Permission.HUMAN_CONFIRM,
    "cli:labels reject": Permission.HUMAN_CONFIRM,
    "cli:labels merge": Permission.HUMAN_CONFIRM,
    "cli:labels unmerge": Permission.HUMAN_CONFIRM,
    "cli:terms promote": Permission.HUMAN_CONFIRM,
    "cli:terms revise": Permission.HUMAN_CONFIRM,
    "cli:terms retire": Permission.HUMAN_CONFIRM,
    "cli:consolidation decide": Permission.HUMAN_CONFIRM,
    "cli:consolidation complete": Permission.HUMAN_CONFIRM,
    "cli:appraisal judge": Permission.HUMAN_CONFIRM,
    "cli:appraisal resolve": Permission.HUMAN_CONFIRM,
    # Markdown-only file export: read-only, the researcher's own copy (decisions 43 and 81).
    "cli:export works": Permission.PROJECT_READ,
    # With --pdfs it copies licensed files out of the library: a human confirmation, like a layer
    # move; `authorize_export_works` applies it.
    EXPORT_WORKS_PDFS: Permission.HUMAN_CONFIRM,
}
"""One permission per MCP tool and per mutating CLI command (ruling 10). A tool with no row is a
tool the server refuses to start with."""


FULL_VIEW_COMMANDS: frozenset[str] = frozenset(
    {
        "cli:seeds",
        "cli:gates",
        "cli:gate audit report",
        "cli:audit report",
        "cli:screen disagreements",
        "cli:extract agreement",
        "cli:extract audit-report",
        "cli:appraisal agreement",
        "cli:appraisal audit-report",
        "cli:mine agreement",
        "cli:mine audit report",
        "cli:miner calibrate report",
        "cli:contributions agreement",
        "cli:contributions audit report",
        "cli:snowball compare",
        "cli:snowball core list",
        "cli:import list",
        "cli:import show",
        "cli:import coverage",
        "cli:export bibtex",
        "cli:export csl",
        "cli:export prisma",
        "cli:living prisma-update",
        "cli:view onion",
        "cli:regions list",
        "cli:regions show",
        "cli:regions diff",
        "cli:regions export",
        "cli:experiments show",
    }
)
"""Reading commands that state seeds, held-out figures or label-derived rates and have no agent
rendering at the command line: refused without the full view (ruling 20). Status, report, trace
and check render the agent view instead."""


@cache
def _team_gates() -> dict[str, ProjectRole]:
    from factory.services.modules.default import default_modules  # the registry imports services

    return default_modules().team_gates()


class _TeamGates(Mapping[str, ProjectRole]):
    """Read from the registry on first use, because the registry imports services."""

    def __getitem__(self, gate_id: str) -> ProjectRole:
        return _team_gates()[gate_id]

    def __iter__(self) -> Iterator[str]:
        return iter(_team_gates())

    def __len__(self) -> int:
        return len(_team_gates())


TEAM_GATES: Mapping[str, ProjectRole] = _TeamGates()
"""The project role each gate needs, computed from the module registry (slice 5, reconciliation
item 1): `GateSpec.required_role` of every decision gate, and every `RoleGate`."""


def _holds(
    project: Project | None,
    principal: Principal,
    actor_kind: ActorKind,
    permission: Permission,
    lab: Lab | None,
    tool: str | None,
) -> bool:
    if actor_kind == "system" and tool in SYSTEM_JOBS:
        return True
    if actor_kind == "human" and lab is None and tool in OPEN_WITHOUT_LAB:
        return True
    gated = (
        actor_kind == "agent"
        and tool in GATED_AGENT_ACTS
        and TOOL_PERMISSIONS.get(tool or "") == permission
    )
    if actor_kind != "human" and permission in HUMAN_ONLY and not gated:
        return False
    lab_roles: tuple[LabRole, ...] = ()
    if lab is not None:
        record = user_record(lab, principal.user)
        if record is None or not record.active:
            return False
        lab_roles = record.lab_roles
    if permission is Permission.LAB_ADMIN:
        return LabRole.ADMIN in lab_roles
    if project is None:
        return False
    if (
        actor_kind != "human"
        and permission in AGENT_PROPOSES_ONLY
        and not gated
        and project.is_hosted()
    ):
        return False
    roles = roles_of(project, principal.user)
    if not roles and lab is not None and visibility(project) == "lab":
        roles = frozenset({ProjectRole.OBSERVER})
    return any(permission in ROLE_PERMISSIONS[role] for role in roles)


def not_held(permission: Permission) -> FactoryValidationError:
    """The one refusal: it says nothing of why, so a project that does not exist reads the same."""
    return FactoryValidationError([ValidationIssue("permission", f"{permission} not held")])


def authorize(
    project: Project | None,
    principal: Principal,
    actor_kind: ActorKind,
    permission: Permission,
    *,
    lab: Lab | None = None,
    tool: str | None = None,
) -> None:
    """Return when the principal, acting as `actor_kind`, holds `permission`; else refuse. `tool`
    is the `TOOL_PERMISSIONS` key of the call, which the per-tool wrapper passes."""
    if not _holds(project, principal, actor_kind, permission, lab, tool):
        raise not_held(permission)


def authorize_command(project: Project, principal: Principal, tool: str) -> None:
    """Authorise a command by its `TOOL_PERMISSIONS` row, as a person (ruling 10). Every gate's
    command has a row whose permission only the gate's role holds. A command with no row reads, so
    it needs `project:read` on a `private` project. On a `lab` project no role binds yet, every
    command runs as it always has (acceptance 1)."""
    if tool in FULL_VIEW_COMMANDS and not full_view_allowed(project, principal):
        raise FactoryValidationError([ValidationIssue("permission", "full view not held")])
    private = visibility(project) == "private"
    permission = TOOL_PERMISSIONS.get(tool) or (Permission.PROJECT_READ if private else None)
    if permission is None or not (private or governed(project)):
        return
    authorize(project, principal, "human", permission, lab=lab_of(project))


def authorize_export_works(
    project: Project,
    principal: Principal,
    *,
    pdfs: bool,
    confirm: bool,
    actor_kind: ActorKind = "human",
) -> None:
    """Authorise `export works`. Only a person exports (any other actor is refused, with or without
    PDFs). With `pdfs` the person must also hold `human-act:confirm` and say `confirm`: licensed
    files leave the library only on an explicit confirmation, as a layer move needs one."""
    if actor_kind != "human":
        raise not_held(Permission.HUMAN_CONFIRM if pdfs else Permission.PROJECT_READ)
    authorize_command(project, principal, "cli:export works")
    if not pdfs:
        return
    if not confirm:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "confirm",
                    "PDFs are licensed files; confirm that they may be copied out of the library",
                )
            ]
        )
    authorize_command(project, principal, EXPORT_WORKS_PDFS)


def gate_role_issues(project: Project, actor: Actor, gate_id: str) -> list[ValidationIssue]:
    """Why a person may not pass `gate_id`: they lack its role. Only a person: the gate policy says
    when an agent may pass, and an agent holds no more than its principal's permissions."""
    if actor.kind != "human" or not governed(project):
        return []
    required = TEAM_GATES.get(gate_id, ProjectRole.MAINTAINER)
    if role_suffices(roles_of(project, actor.user), required):
        return []
    return [ValidationIssue("permission", f"gate {gate_id} needs {required.value}")]


def full_view_allowed(project: Project, principal: Principal) -> bool:
    """Whether `principal` reads the project's full view at the command line (ruling 20): `owner` or
    `maintainer`, the implicit owner of an unhosted project included. Anyone else reads the agent
    view, because a person who knows which works are held-out seeds is a contaminated screener."""
    return bool(roles_of(project, principal.user) & _FULL_VIEW_ROLES)


def visibility(project: Project) -> Visibility:
    """Who reads the project: `lab` until an owner says `private` (ruling 13)."""
    project.index.sync()
    with project.index.connect() as conn:
        return latest_visibility(conn)


def set_visibility(project: Project, actor: Actor, value: Visibility) -> None:
    """Record the project's visibility. Needs `project:govern`; a person acts in their own name."""
    payload = payload_of(ProjectVisibilitySet, visibility=value)
    with project.writing():
        require_actor(project, actor, Permission.PROJECT_GOVERN)
        if visibility(project) == value:
            raise refuse("visibility", f"the project is already {value}")
        project.record([project.events.make("project.visibility_set", payload, actor)])


def governed(project: Project) -> bool:
    """Whether roles bind on this project: it is hosted, or a grant has counted."""
    if project.is_hosted():
        return True
    project.index.sync()
    with project.index.connect() as conn:
        return member_index.any_grant(conn, MEMBER_TABLES)


def lab_of(project: Project) -> Lab | None:
    """The lab registry of the project's root, when one exists."""
    if not lab_exists(project.settings):
        return None
    return open_lab(project.settings, session=project.session, clock=project.clock)


def principal_of(project: Project, actor: Actor) -> Principal:
    """The principal `actor` acts for: an agent acts for its delegating user."""
    return Principal(actor.user, actor.credential, project.principal.channel)


def actor_holds(project: Project, actor: Actor, permission: Permission) -> bool:
    """Whether `actor` holds `permission`. On a project no role binds yet a person holds all, and
    an agent all but `HUMAN_ONLY`, as `Settings.user` always has."""
    if actor.kind != "human" and permission in HUMAN_ONLY:
        return False
    if not governed(project):
        return True
    principal = principal_of(project, actor)
    return _holds(project, principal, actor.kind, permission, lab_of(project), None)


def require_actor(project: Project, actor: Actor, permission: Permission) -> None:
    """`authorize` for a service: refuse an `actor` who does not hold `permission`."""
    if not actor_holds(project, actor, permission):
        raise not_held(permission)


def role_suffices(roles: frozenset[ProjectRole], required: ProjectRole) -> bool:
    """Whether `roles` pass a gate of role `required`: an owner holds all a maintainer does."""
    return required in roles or ProjectRole.OWNER in roles
