# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Lyu & Yu (2023) sets: PDPTW-T (vehicles optional) and PDP-T (every vehicle used). Resumable.
usage: python3 scripts/lyuyu.py <root of the Mendeley archive> [seeds=1] [tl_pdptwt=20] [tl_pdpt=60]"""
import glob, json, os, sys, time
from pdpt.converters import lyu_yu, lyu_yu_results
from pdpt.lns import solve
from pdpt.verifier import verify
root = sys.argv[1]
seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 1
tl1 = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0
tl2 = float(sys.argv[4]) if len(sys.argv) > 4 else 60.0
OUT = "results/lyuyu.json"
rows = json.load(open(OUT)) if os.path.exists(OUT) else {}
pub = lyu_yu_results(f"{root}/Results/Results-PDPTWT.txt"); pub.update(lyu_yu_results(f"{root}/Results/Gurobi-PDPT-Lyu.txt"))
jobs = [(f, False, tl1) for f in sorted(glob.glob(f"{root}/PDPTW-T/*/*.txt"))] + \
       [(f, True, tl2) for f in sorted(glob.glob(f"{root}/PDP-T/*/*.txt"))]
for f, avu, tl in jobs:
    inst = lyu_yu(f, all_vehicles_used=avu)
    for seed in range(seeds):
        key = f"{inst.name}/{seed}"
        if key in rows:
            continue
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed)
        rep = verify(inst, r.solution)
        p = pub.get(inst.name, {}).get("lyu")
        rows[key] = dict(instance=inst.name, seed=seed, set="PDPT" if avu else "PDPTW-T", cost=round(rep.cost, 2),
                         feasible=rep.feasible, unassigned=len(r.operator_stats["unassigned"]), vehicles=rep.vehicles_used,
                         transfers=rep.transfers, t_best=round(r.history[-1][0], 2), it=r.iterations,
                         pub_status=p and p[0], pub_value=p and p[1] and round(p[1], 2),
                         gap=(None if not p or p[1] is None or rep.cost is None else round(100 * (rep.cost / p[1] - 1), 2)))
        print(key, rows[key], flush=True)
        json.dump(rows, open(OUT, "w"), indent=1)
print("DONE", flush=True)
