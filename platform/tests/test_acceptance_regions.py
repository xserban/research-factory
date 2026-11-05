# ruff: noqa: F401, F811, E501
"""Slice-3d regions acceptance (spec criteria 1 to 10 and 17, region part; plan Regions-C, task 6).

Each criterion is covered by the named tests of the plan that built it, imported here under an
`acceptance` name so that one file lists the criteria; the criteria Regions-C owns also have new
tests below. The `slow` ones keep their marker (`pytest -m "not network"` runs them).

Adoption (6) is a Later task of Regions-B and stays a skipped test.
"""

from __future__ import annotations

import pytest

from factory.model.project import RigorMode
from factory.services.context import Project
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, rows, screened, world
from tests.region_helpers import RWorld, region_project
from tests.test_consolidation_service import cw

# 8. Consolidation
from tests.test_consolidation_service import (
    test_clusters_name_signals_and_are_identical_across_runs as test_acceptance_08_clusters_identical,
)
from tests.test_consolidation_service import (
    test_due_counts_new_nodes as test_acceptance_08_due_nodes,
)
from tests.test_consolidation_service import (
    test_due_counts_reset_on_completion as test_acceptance_08_due_labels,
)
from tests.test_consolidation_service import (
    test_merge_unmerge_restores_state_hash as test_acceptance_08_merge_unmerge_restores,
)
from tests.test_consolidation_signals import (
    test_no_all_pairs as test_acceptance_08_no_all_pairs_scan,
)
from tests.test_consolidation_signals import (
    test_overlap_signal_without_string_similarity as test_acceptance_08_overlap_pairs,
)

# 7. Labels
from tests.test_labels import (
    test_agent_quote_with_key_stated as test_acceptance_07_agent_quote_stated,
)
from tests.test_labels import (
    test_agent_without_quote_inferred as test_acceptance_07_agent_without_quote_inferred,
)
from tests.test_labels import (
    test_human_application_confirmed as test_acceptance_07_human_confirmed,
)
from tests.test_labels import (
    test_labels_not_in_graph_tables as test_acceptance_07_not_in_graph_tables,
)
from tests.test_labels import (
    test_non_verbatim_quote_rejected_batch_partial as test_acceptance_07_non_verbatim_rejected,
)
from tests.test_organisation_separation import (
    populate_organisation,
)

# 10. Separation
from tests.test_organisation_separation import (
    test_architecture_no_organisation_imports as test_acceptance_10_architecture,
)
from tests.test_organisation_separation import (
    test_differential_evidence_identical as test_acceptance_10_differential,
)
from tests.test_organisation_separation import (
    test_organisation_leak_fires_on_constructed_leak as test_acceptance_10_leak_fires,
)
from tests.test_organisation_separation import (
    test_trace_of_organisation_ids as test_acceptance_17_trace_organisation_ids,
)

# 5. Focus
from tests.test_region_check_trace import (
    test_focus_slot_missing_finding as test_acceptance_05_slot_missing_finding,
)

# 17. Rebuild and trace
from tests.test_region_check_trace import (
    test_trace_member_basis as test_acceptance_17_trace_region_member,
)

# 1. Rule determinism
from tests.test_region_evaluate import (
    test_basis_lists_rule_indices as test_acceptance_01_basis_lists_rule_indices,
)
from tests.test_region_evaluate import (
    test_cites_min_k as test_acceptance_01_cites_rule,
)
from tests.test_region_evaluate import (
    test_corpus_included as test_acceptance_01_corpus_rule,
)
from tests.test_region_evaluate import (
    test_exclude_and_within as test_acceptance_01_exclude_and_within,
)
from tests.test_region_evaluate import (
    test_idea_rule_includes_idea_node_and_members as test_acceptance_01_idea_rule,
)
from tests.test_region_evaluate import (
    test_lineage_ancestors_stated_only as test_acceptance_01_lineage_rule,
)
from tests.test_region_evaluate import (
    test_region_rule_reads_pinned_version as test_acceptance_01_pinned_region_unaffected,
)
from tests.test_region_evaluate import (
    test_text_rule_and_of_ors as test_acceptance_01_text_rule,
)

# 2. Bounds
from tests.test_region_evaluate import (
    test_truncated_lineage_refuses as test_acceptance_02_truncated_lineage_refuses,
)
from tests.test_region_focus import (
    test_focus_needs_existing_slot as test_acceptance_05_focus_needs_existing_slot,
)
from tests.test_region_focus import (
    test_focus_slot_missing_after_question_change as test_acceptance_05_slot_missing,
)
from tests.test_region_focus import (
    test_second_focus_on_slot_refused as test_acceptance_05_second_focus_refused,
)

# 4 (proposals half, Regions-B)
from tests.test_region_members import (
    test_member_quote_must_verify as test_acceptance_04_unverifiable_proposal_rejected,
)
from tests.test_region_members import (
    test_proposal_absent_until_added as test_acceptance_04_undecided_proposal_absent,
)

# 4. Review (the proposals half is Regions-B)
from tests.test_region_review import (
    test_agent_cannot_review as test_acceptance_04_agent_cannot_review,
)
from tests.test_region_rules import (
    test_canonical_order_independent as test_acceptance_01_order_independent,
)
from tests.test_region_scale import test_region_scale as test_acceptance_02_scale
from tests.test_region_snapshot import (
    test_agent_cannot_decide_a_member as test_acceptance_04_agent_cannot_decide_a_member,
)

# 3. Snapshot
from tests.test_region_snapshot import (
    test_drift_after_new_inclusion as test_acceptance_03_drift,
)
from tests.test_region_snapshot import test_rebuild_identical as test_acceptance_17_rebuild_regions
from tests.test_region_snapshot import (
    test_snapshot_replays_from_the_event_prefix as test_acceptance_03_replay_to_as_of,
)
from tests.test_region_snapshot import (
    test_version_hash_sensitivity as test_acceptance_03_version_hash_sensitivity,
)

# 9. Promotion
from tests.test_terms import (
    test_agent_cannot_promote as test_acceptance_09_agent_cannot_promote,
)
from tests.test_terms import (
    test_term_applications_classified as test_acceptance_09_applications_classified,
)
from tests.test_terms import (
    test_term_rule_excludes_inferred as test_acceptance_09_term_rule_excludes_inferred,
)
from tests.test_terms import tw


def test_acceptance_17_rebuild_with_organisation_gives_identical_state(
    project: Project, iw: IWorld
) -> None:
    populate_organisation(project, iw)
    project.index.sync()
    before = project.index.state_hash()
    assert project.index.rebuild() == before
    assert rows(project, "SELECT COUNT(*) FROM labels") != [(0,)]
    assert rows(project, "SELECT COUNT(*) FROM consolidation_passes") == [(1,)]


# --- Interfaces of plan Regions-B: the controller replaces each skip once B is merged ---


@pytest.mark.skip(reason="controller: needs Regions-B adoption (Later task)")
def test_acceptance_06_adoption_regions_b() -> None:
    """An adopted snapshot's blob hash is verified; adoption changes no corpus count; an
    unreviewed source version is refused."""
