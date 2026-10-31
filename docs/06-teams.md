# Teams

Collaboration happens where two people's regions connect. Example: PhD A on PINNs, PhD B on TAVI, joint project on PINNs for TAVI.

## Ownership
| Region | Owner | Their agents mainly do |
| --- | --- | --- |
| PINN and neural-operator methods | PhD A (methods) | Track methods, write method cards, maintain reusable code |
| TAVI, aortic stenosis, CFD/FSI of the valve | PhD B (application) | Track clinical and simulation literature, write problem descriptions, curate validation cases and data |
| PINNs for TAVI (joint focus) | A and B | Joint hypotheses, experiments, papers |

Code-owners rule for knowledge: anyone can propose changes to a region; its owner reviews before merge into the shared graph. Each person works in their own workspace (branch).

## Interfaces between people
- Application side publishes **problem descriptions** (inputs, constraints, latency, clinical metrics).
- Method side publishes **method cards** (properties, assumptions, inputs, maturity, code).
- The factory matches them and proposes joint hypotheses, stating which properties drove each match.

## Coordination
- **Cross-project CI:** the application owner's validation cases run automatically on every new method from the method owner.
- **Region subscriptions:** alerts when a depended-on region changes.
- **Shared backlog** across projects with dependencies and blockers.
- **Design docs** for each joint hypothesis, reviewed by both before experiments.

## Routines the factory prepares
- Weekly digest per person (own regions + dependencies).
- Lab-meeting brief (progress, blockers, new matches).
- Opportunity report (unexploited matches between people's work).
- Journal-club picks (papers relevant across several regions).

## Credit
Provenance records which human and which agents created every node, claim, experiment and result → separable thesis contributions, authorship decisions, joint vs. individual work.

## Subscriptions in a team
- Each researcher runs agents on their own seat (a Claude Team plan gives seats, shared Projects with permissions, admin-added connectors). Don't share one subscription.
- The factory server is shared via one connector.
- Budgets per person plus agreed priorities for joint work.

## Disagreements
Conflicting claims become explicit nodes with both sides' evidence; resolved by owners or by a pre-agreed decisive test (adversarial collaboration), never by last write.

## Build implications
From day one: users, ownership and permissions on regions/nodes/edges; per-person workspaces merging into the shared graph.
