# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Sampaio et al. (2020) PDPTW-T sets, warm-started from the shipped PDPTW routes. Resumable.
usage: python3 scripts/sampaio.py <archive root> [seeds=1] [tl=300] [sizes=50,75,100]"""
import glob, json, os, sys
from pdpt.converters import sampaio
from pdpt.lns import solve
from pdpt.verifier import verify
root = sys.argv[1]
seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 1
tl = float(sys.argv[3]) if len(sys.argv) > 3 else 300.0
sizes = (sys.argv[4] if len(sys.argv) > 4 else "50,75,100").split(",")
OUT = "results/sampaio.json"
rows = json.load(open(OUT)) if os.path.exists(OUT) else {}
jobs = []
if "50" in sizes:
    for sub in ("5T_rpk", "4T_rpk"):
        for f in sorted(glob.glob(f"{root}/50/50/json/50/50/json/{sub}/*/*.json")):
            jobs.append((f, f"SA50-{sub[:2]}-{f.split('/')[-2]}-{f.split('/')[-1][:-5]}"))
if "75" in sizes:
    for f in sorted(glob.glob(f"{root}/75/75/json/*/*.json")):
        jobs.append((f, f"SA75-5T-{f.split('/')[-2]}-{f.split('/')[-1][:-5]}"))
if "100" in sizes:
    for f in sorted(glob.glob(f"{root}/100/json/*/*.json")):
        jobs.append((f, f"SA100-5T-{f.split('/')[-2]}-{f.split('/')[-1][:-5]}"))
for f, name in jobs:
    inst, warm = sampaio(f, name=name)
    wrep = verify(inst, warm) if warm else None
    for seed in range(seeds):
        key = f"{name}/{seed}"
        if key in rows:
            continue
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed, warm_start=warm)
        rep = verify(inst, r.solution)
        revisits = 0
        for rt in r.solution.routes:
            seen, prev = set(), None
            for v in rt.visits:
                tp = v.transfer_point
                if tp and tp != prev:
                    if tp in seen:
                        revisits += 1
                    seen.add(tp)
                prev = tp if tp else None
        rows[key] = dict(instance=name, tp_revisits=revisits, seed=seed, n=len(inst.requests), cost=round(rep.cost, 2), feasible=rep.feasible,
                         unassigned=len(r.operator_stats["unassigned"]), drivers=rep.vehicles_used, transfers=rep.transfers,
                         it=r.iterations, t_best=round(r.history[-1][0], 1),
                         warm_cost=wrep and round(wrep.cost, 2), warm_drivers=wrep and wrep.vehicles_used,
                         warm_unassigned=len(inst.requests) - (len({v.request for rt in warm.routes for v in rt.visits}) if warm else 0),
                         saving_pct=(wrep and wrep.cost and round(100 * (1 - rep.cost / wrep.cost), 2)))
        print(key, rows[key], flush=True)
        json.dump(rows, open(OUT, "w"), indent=1)
print("DONE", flush=True)
