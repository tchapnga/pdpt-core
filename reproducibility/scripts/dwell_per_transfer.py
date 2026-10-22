# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Dwell time per transfer on the unbounded cells of the factorial study (factorial study, finding (ii)).

For every run of the cells (H=1, S=2, W=inf) and (H=inf, S=inf, W=inf) of phase 7, the stored plan is re-scheduled by
the verifier and, for every transfer, the dwell (pick start minus drop end) is recorded.  Writes
results/phase7_dwell.json: per cell and size, the number of transfers, the median and mean dwell (min), and the share
of transfers with a dwell of at most 30 and at most 120 minutes.  make_tables.py turns it into
tables/phase7_dwell.tex.
"""
import json, statistics as st, sys

sys.path.insert(0, "scripts")
from job import parse_setting, job_key
from pdpt.portgen import generate
from pdpt.solution import Solution, DROP, PICK
from pdpt.verifier import verify

R = "results"
CELLS = ("yards_H1_S2_Winf", "yards_Hinf_Sinf_Winf")


def dwells(inst, sol):
    rep = verify(inst, sol)
    drops, picks = {}, {}
    for ri, route in enumerate(sol.routes):
        for vi, vis in enumerate(route.visits):
            if vis.op in (DROP, PICK) and vis.transfer_point:
                _, start, end = rep.schedule.times[(ri, vi)]
                (drops if vis.op == DROP else picks)[(vis.request, vis.transfer_point)] = (start, end)
    return [picks[k][0] - de for k, (ds, de) in drops.items() if k in picks]


def main():
    rows = [r for r in json.load(open(f"{R}/campaign_jobs.json"))["port7"] if r["setting"] in CELLS]
    out = {}
    for cell in CELLS:
        for n in (20, 30, 50):
            dw = []
            for r in rows:
                if r["setting"] != cell or r["n"] != n:
                    continue
                inst = generate(n, seed=r["seed"], **parse_setting(cell))
                sol = Solution.from_dict(json.load(open(f"{R}/jobs/{job_key(r['argv'])}.json"))["solution"])
                dw += dwells(inst, sol)
            out[f"{n}/{cell}"] = dict(transfers=len(dw), median=st.median(dw), mean=st.mean(dw),
                                      share_le_30=sum(1 for x in dw if x <= 30) / len(dw),
                                      share_le_120=sum(1 for x in dw if x <= 120) / len(dw))
            print(n, cell, {k: round(v, 2) for k, v in out[f"{n}/{cell}"].items()})
    json.dump(out, open(f"{R}/phase7_dwell.json", "w"), indent=1)


if __name__ == "__main__":
    main()
