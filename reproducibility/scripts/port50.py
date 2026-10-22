# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""PORT n=50, 10 seeds, 4 settings, warm start from the no-yard incumbent. Resumable."""
import json, os, sys
from pdpt.portgen import generate
from pdpt.lns import solve
from pdpt.solution import Solution

n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
tl = float(sys.argv[2]) if len(sys.argv) > 2 else 400.0
OUT = f"results/port{n}_warm.json"
res = json.load(open(OUT)) if os.path.exists(OUT) else {}
SETTINGS = [("yards_inf", dict(n_yards=2)), ("yards_H1_S2", dict(n_yards=2, H=1, S=2)),
            ("yards_H1_S1_W60", dict(n_yards=2, H=1, S=1, W=60.0))]
for seed in range(10):
    kb = f"{seed}/no_yard"
    if kb not in res:
        inst = generate(n, seed=seed, n_yards=0)
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed)
        res[kb] = dict(vehicles=r.report.vehicles_used, cost=round(r.report.cost, 1), km=round(r.report.distance, 1),
                       transfers=0, it=r.iterations, t_best=round(r.history[-1][0], 1), solution=r.solution.to_dict())
        print(kb, {k: v for k, v in res[kb].items() if k != "solution"}, flush=True)
        json.dump(res, open(OUT, "w"))
    base_sol = Solution.from_dict(res[kb]["solution"])
    for label, kw in SETTINGS:
        key = f"{seed}/{label}"
        if key in res:
            continue
        inst = generate(n, seed=seed, **kw)
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed, warm_start=base_sol)
        res[key] = dict(vehicles=r.report.vehicles_used, cost=round(r.report.cost, 1), km=round(r.report.distance, 1),
                        transfers=r.report.transfers, it=r.iterations, t_best=round(r.history[-1][0], 1))
        print(key, res[key], flush=True)
        json.dump(res, open(OUT, "w"))
print("DONE", flush=True)
