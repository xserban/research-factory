#!/bin/bash
# Copy the pilot into the factory's data folder (plan 2026-11-11-one-roof). NOTHING is moved or deleted:
# the pilot stays as it is until the researcher removes it. Default is a DRY RUN that only lists.
#   scripts/migrate_pilot_to_data.sh              dry run
#   scripts/migrate_pilot_to_data.sh --run        copy
#   scripts/migrate_pilot_to_data.sh --verify     compare the copy with the pilot (read-only)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PILOT="${PILOT:-$HOME/Documents/research-factory-pilot}"
SLUG="${SLUG:-agentic-science}"
DATA="$REPO/data"
P="$DATA/projects/$SLUG"
MODE="${1:---dry}"

# (source, destination) pairs: the data root as it is, then the researcher's files into the project
copy() { # src dst
  local flags=(-a --human-readable); [ "$MODE" = "--run" ] && flags+=(--info=stats1) || flags+=(--dry-run --itemize-changes)
  [ "$MODE" = "--run" ] && mkdir -p "$2"
  rsync "${flags[@]}" "$1" "$2"
}
verify() { # src dst
  local n; n=$(rsync -anc --itemize-changes "$1" "$2" | grep -c '^>f' || true)
  echo "  $2: $n files differ or are missing"; [ "$n" = 0 ]
}

if [ "$MODE" = "--verify" ]; then
  ok=1
  verify "$PILOT/root/" "$DATA/" || ok=0
  verify "$PILOT/staging-pdfs/" "$P/inputs/staging-pdfs/" || ok=0
  verify "$PILOT/validation/" "$P/validation/" || ok=0
  verify "$PILOT/screeners/" "$P/ops/screeners/" || ok=0
  echo "events: pilot $(cat "$PILOT"/root/projects/$SLUG/events/*/*.jsonl | wc -l), data $(cat "$P"/events/*/*.jsonl | wc -l)"
  [ "$ok" = 1 ] && echo "VERIFIED: the copy matches the pilot" || { echo "NOT VERIFIED"; exit 1; }
  exit 0
fi

echo "== preconditions"
if pgrep -f "claude -p" >/dev/null || pgrep -f "autopilot[0-9]*.sh" >/dev/null || pgrep -f "factory .*site serve" >/dev/null; then
  echo "STOP: a miner session, an autopilot script or the hub server is running. Wait for it to finish."; exit 1
fi
grep -qx '/data/' "$REPO/.gitignore" || { echo "STOP: add '/data/' to .gitignore first"; exit 1; }
[ "$MODE" = "--run" ] || echo "(dry run: nothing is copied)"

echo "== 1. the data root (events, blobs, library, site, taxonomy) -> data/"
copy "$PILOT/root/" "$DATA/"
echo "== 2. the researcher's documents -> project docs/"
for f in research-plan.md research-plan.pdf research-plan-v1-draft.md research-plan-v2-draft.md research-plan-v3-rejected.md research-plan-v3-rejected.pdf research-questions.md research-questions.pdf review-protocol.md review-protocol.pdf goal-definition.md goal-definition.pdf rf-plan-draft.md develop-part-a.md demo-log.md STATUS-2026-11-09.md; do
  [ -e "$PILOT/$f" ] && copy "$PILOT/$f" "$P/docs/"
done
echo "== 3. inputs and evidence"
for d in staging-7 staging-13 staging-named staging-pdfs pdfs; do [ -d "$PILOT/$d" ] && copy "$PILOT/$d/" "$P/inputs/$d/"; done
[ -d "$PILOT/validation" ] && copy "$PILOT/validation/" "$P/validation/"
[ -e "$PILOT/validation-cases.json" ] && copy "$PILOT/validation-cases.json" "$P/validation/"
echo "== 4. run history and tooling -> ops/ (until factory mine run replaces them)"
copy "$PILOT/screeners/" "$P/ops/screeners/"
echo "== 5. old product copies and backfill -> archive/ (superseded by the hub)"
for d in explorer dashboard superseded backfill; do [ -d "$PILOT/$d" ] && copy "$PILOT/$d/" "$P/archive/$d/"; done
echo "root-backup-2026-11-07 is left where it is (a backup: archive it outside the tree)."

if [ "$MODE" = "--run" ]; then
  cat <<N

Copied. NEXT, by hand (not done by this script):
  1. scripts/migrate_pilot_to_data.sh --verify
  2. FACTORY_ROOT=$DATA factory --project $SLUG check ; factory --project $SLUG mine status   (compare with the pilot)
  3. FACTORY_ROOT=$DATA factory --project $SLUG site build --force   (links inside site/ are machine paths)
  4. point FACTORY_ROOT, factory-mcp.json and hub.sh at $DATA
  5. keep the pilot read-only for a week, then archive it; never delete before 1-3 pass.
N
fi
