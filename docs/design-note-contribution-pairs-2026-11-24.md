# Design note: candidate pairs for unmatched contribution rows (IDEA-140)

**Problem.** The contribution pack keys a row by the anchor of its first anchored field plus
`item_kind`, `absent_kind`, `name` and `metric`. Two passes that read the same item in different
paragraphs get different keys and stay unmatched. A dry run on ten works gave 97 items and 15
aligned rows; re-keying by (kind, name) or (kind, entry) lifted alignment to about half only, since
names are free text (`Itti and Baldi` against `Itti & Baldi [2005]`).

**Decision.** Keys and the pack stay as they are (existing events keep their keys). The platform
computes, without a model, a ranked list of candidate pairs between an unmatched pass-A row and an
unmatched pass-B row of the same work. The list is a proposal read by the human; it writes nothing.

**Scoring** (`factory/extraction/pairing.py`, pure). Required: same work, same `item_kind`; a
`not-stated` row needs the same `absent_kind` (score 0.5). Otherwise a candidate needs name or
citation evidence; the anchor alone never makes one.

| signal | weight |
| --- | --- |
| name tokens (casefolded alphanumeric; `et`, `al`, `and` and years dropped; the metric stands in for a missing name): shared / union | 0.6 x Jaccard |
| same year token in both names (tiebreak only) | 0.05 |
| same `cited_entry`, both present | 0.2 |
| same canonical `value` (result rows) | 0.2 |
| same section of the anchor (`s2.1.p3` and `s2.1.p7`), else same top-level section | 0.15, else 0.075 |

Statements and quotes are never compared. Pairs below `--min-score` (default 0.3) are dropped.
Assignment is greedy and one-to-one: by score, ties by (work, A key, B key); each row is proposed at
most once. Rows left over are listed as `no candidate`. Counts (pairs, unmatched A and B, without
candidate) are computed.

**Confirmation.** Only a human confirms, with the existing `contributions resolve`: whole-row
choice `a` or `b` on the row to keep and `neither` on its twin. No new event type, no new gate; an
agent or script never resolves. A pair accepted this way is a disagreement resolved, not an alignment:
the agreement's rates stay computed on the keys.

**Interface.** `factory contributions pairs [--work W] [--min-score X] [--json]` (read-only, derived
on each call). A hub view can read the same service later.

**Limits.** Aliases (`AutoDS` against `AUTODISCOVERY`) and paraphrased names share no token and get
no candidate; a model-free score cannot judge them and the human still sees them in `agreement`.
Weights are a first setting to be judged on the dry-run examples, not calibrated.
