# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
import json, os
from pdpt.portgen import generate
from pdpt.cpsat import solve
best={(r['seed'],r['setting']):r for r in json.load(open('results/port20_capacity_v4.json'))}
OUT='results/cpsat_port20.json'
rows=json.load(open(OUT)) if os.path.exists(OUT) else []
done={(r['seed'],r['setting']) for r in rows}
for seed in range(10):
    for label, kw in [('no_yard', dict(n_yards=0))]:
        if (seed,label) in done: continue
        inst = generate(20, seed=seed, **kw)
        r = solve(inst, time_limit=240, scale=1, workers=1)
        h = best[(seed,label)]
        row=dict(seed=seed, setting=label, status=r.status, cp_cost=None if r.report is None else round(r.report.cost,1), cp_feasible=None if r.report is None else r.report.feasible, bound=round(r.bound,1), lns_cost=h['cost'], gap_lns_vs_bound=round(100*(h['cost']-r.bound)/h['cost'],1), time=round(r.time))
        rows.append(row); print(row, flush=True)
        json.dump(rows, open(OUT,'w'), indent=1)
print('DONE')
