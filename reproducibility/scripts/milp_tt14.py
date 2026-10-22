# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Big-M MILP certificates on TT-14 (HiGHS with its default thread setting, 600 s, fleet of $MILP_FLEET vehicles, default 3: the
lexicographic objective makes any fleet of at least two equivalent for the certificate): appends one record per instance to
results/milp_tt14.json (or $MILP_OUT); $MILP_EPS adds a margin to the synchronisation constraints (see pdpt.milp.solve);
each record says whether the decoded plan passes the verifier.  usage: python3 scripts/milp_tt14.py E1 E2 ..."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pdpt.thesis2014 import instance
from pdpt.milp import solve

path = os.environ.get("MILP_OUT", "results/milp_tt14.json")
rows = json.load(open(path)) if os.path.exists(path) else []
done = {r["instance"] for r in rows}
for name in sys.argv[1:]:
    if name in done:
        continue
    inst = instance(name, fleet_size=int(os.environ.get("MILP_FLEET", "3")), allow_transfer=True)
    r = solve(inst, time_limit=600.0, sync_eps=float(os.environ.get("MILP_EPS", "0")))
    rows.append(dict(instance=name, status="Optimal" if r.status.lower().startswith("opt") else "Time limit reached",
                     veh=r.report.vehicles_used if r.report else None, dist=round(r.report.distance, 2) if r.report else None,
                     bound=round(r.bound, 2), gap=round(r.gap, 4) if r.gap is not None else None, time=round(r.time, 1),
                     vars=r.n_vars, rows=r.n_rows, verified=bool(r.report.feasible) if r.report else None,
                     violations=r.report.violations[:2] if r.report else None))
    print(rows[-1], flush=True)
rows.sort(key=lambda r: int(r["instance"][1:]))
json.dump(rows, open(path, "w"), indent=1)
