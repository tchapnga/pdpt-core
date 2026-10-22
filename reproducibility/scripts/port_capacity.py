# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Campaign: value of transfers on PORT instances under capacity settings."""
import json
import sys

from pdpt.portgen import generate
from pdpt.lns import solve

n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
tl = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0
SETTINGS = [("no_yard", dict(n_yards=0)), ("yards_inf", dict(n_yards=2)),
            ("yards_H1_S2", dict(n_yards=2, H=1, S=2)), ("yards_H1_S1_W60", dict(n_yards=2, H=1, S=1, W=60.0))]
import os
out = f"results/port{n}_capacity_v4.json"
rows = json.load(open(out)) if os.path.exists(out) else []
done = {(r["seed"], r["setting"]) for r in rows}
for seed in range(seeds):
    for label, kw in SETTINGS:
        if (seed, label) in done:
            continue
        inst = generate(n, seed=seed, **kw)
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed)
        row = dict(seed=seed, setting=label, unassigned=len(r.operator_stats["unassigned"]),
                   vehicles=r.report.vehicles_used, cost=round(r.report.cost, 1), km=round(r.report.distance, 1),
                   transfers=r.report.transfers, it=r.iterations, t_best=round(r.history[-1][0], 1))
        rows.append(row)
        print(row, flush=True)
        json.dump(rows, open(out, "w"), indent=1)
