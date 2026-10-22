#!/bin/bash
# Run the whole campaign on N cores.  usage: scripts/run_campaign.sh [N=$(nproc)] [phases="1 2 3"]
# A phase may carry a number of days/seeds after a colon, e.g. "7a:1 7b:1" (pilot) or "7a:20 7b:20".
# Re-runnable: finished jobs are skipped.  Pushes results to git after each phase if a remote exists.
set -u
cd "$(dirname "$0")/.."
[ -f ../.venv/bin/activate ] && . ../.venv/bin/activate
N=${1:-$(nproc)}
PHASES=${2:-"1 2 3 4"}
mkdir -p results/jobs results/logs
for spec in $PHASES; do
  ph=${spec%%:*}                      # phase name (used for the log and the commit)
  days=${spec#*:}; [ "$days" = "$spec" ] && days=""   # optional number of days/seeds: "7a:1", "7b:20"
  echo "== phase $ph${days:+ ($days days)} on $N cores: $(date)"
  python3 scripts/joblist.py $ph $days | xargs -P "$N" -L 1 -I{} sh -c 'python3 scripts/job.py {} >> results/logs/phase'"$ph"'.log 2>&1'
  python3 scripts/collect.py
  if git remote | grep -q origin; then
    git add results/jobs results/*.json && git commit -qm "campaign: phase $ph results $(date +%F)" || true
    # resynchronise before pushing: other commits may have landed on main during the phase
    git pull -q --rebase -X ours origin main || git rebase --abort
    git push -q origin HEAD || echo "push failed (will be retried at the next phase)"
  fi
  echo "== phase $ph done: $(date)"
done
echo "CAMPAIGN DONE $(date)"
