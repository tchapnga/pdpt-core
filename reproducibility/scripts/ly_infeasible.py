# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Certify the PDPTW-T instances of Lyu & Yu on which neither published MILP found a solution in 1 h.

For each such instance: the best LNS run (does it assign every request?) and the CP model with the
relaxed discretisation (`rounding="relax"`, scale 100: travel times rounded down, deadlines up), whose
INFEASIBLE answer is exact.  Writes results/ly_infeasible.json.
usage: python3 scripts/ly_infeasible.py [time_limit=1500]
"""
import glob, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pdpt.converters import lyu_yu, lyu_yu_results
from pdpt.cpsat import solve as cps

tl = float(sys.argv[1]) if len(sys.argv) > 1 else 1500.0
pub = lyu_yu_results("ext/lyuyu/Results/Results-PDPTWT.txt")
nosol = sorted(k for k, v in pub.items() if all(x[1] is None for x in v.values()))
out = {}
for nm in nosol:
    inst = lyu_yu(glob.glob(f"ext/lyuyu/PDPTW-T/*/{nm}.txt")[0])
    lns = [json.load(open(f)) for f in glob.glob(f"results/jobs/lyuyu*{nm}_*_sv2.json")]
    served = [r for r in lns if r["unassigned"] == 0 and r["feasible"]]
    row = dict(lns_feasible=bool(served), lns_best=min((r["cost"] for r in served), default=None))
    if not served:
        r = cps(inst, time_limit=tl, workers=4, scale=100, rounding="relax")
        row.update(cp_status=r.status, cp_time=round(r.time, 1))
    out[nm] = row
    print(nm, row, flush=True)
json.dump(out, open("results/ly_infeasible.json", "w"), indent=1)
