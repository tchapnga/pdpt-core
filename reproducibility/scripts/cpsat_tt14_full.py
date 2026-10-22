# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
import json, os
from pdpt.thesis2014 import instance
from pdpt.cpsat import solve
OUT='results/cpsat_tt14_full.json'
rows=json.load(open(OUT)) if os.path.exists(OUT) else []
done={r['instance'] for r in rows}
for i in range(1,17):
    name=f"E{i}"
    if name in done: continue
    inst=instance(name, fleet_size=4, allow_transfer=True)
    r=solve(inst, time_limit=300, workers=1)
    row=dict(instance=name, status=r.status, veh=r.report.vehicles_used if r.report else None,
             dist=round(r.report.distance,2) if r.report else None, gap=r.gap, time=round(r.time,1))
    rows.append(row); print(row, flush=True)
    json.dump(rows, open(OUT,'w'), indent=1)
print("DONE")
