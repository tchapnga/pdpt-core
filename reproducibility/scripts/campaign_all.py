# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Sequential, resumable campaign: TT-14 (10 seeds), Li & Lim (3 instances, 10 seeds), PORT n=30."""
import json
import os
import statistics as S
import sys

from pdpt.thesis2014 import instance as tt, _E, KNOWN_OPTIMA, OPT_WITH_TRANSFER_DIST
from pdpt.converters import li_lim
from pdpt.portgen import generate
from pdpt.lns import solve

OUT = "results/campaign_all.json"
res = json.load(open(OUT)) if os.path.exists(OUT) else {}


def save():
    json.dump(res, open(OUT, "w"), indent=1)


def done(key):
    return key in res


# ---- TT-14
for e in _E:
    name = e[0]
    for allow in (True, False):
        key = f"tt14/{name}/{'T' if allow else 'D'}"
        if done(key):
            continue
        runs = []
        for seed in range(10):
            inst = tt(name, fleet_size=4, allow_transfer=allow)
            r = solve(inst, time_limit=5, max_iter=400, seed=seed)
            runs.append(dict(seed=seed, veh=r.report.vehicles_used, dist=round(r.report.distance, 2),
                             tr=r.report.transfers, t_best=round(r.history[-1][0], 3)))
        res[key] = runs
        print(key, "veh", min(x["veh"] for x in runs), max(x["veh"] for x in runs),
              "dist", min(x["dist"] for x in runs), max(x["dist"] for x in runs), flush=True)
        save()

# ---- Li & Lim
base = "instances/"
for name, bk in [("lc101", (10, 828.94)), ("lr101", (19, 1650.80)), ("lrc101", (14, 1708.80))]:
    key = f"lilim/{name}"
    if done(key):
        continue
    inst = li_lim(base + name + ".txt")
    runs = []
    for seed in range(10):
        r = solve(inst, time_limit=60, max_iter=10**6, seed=seed)
        runs.append(dict(seed=seed, veh=r.report.vehicles_used, dist=round(r.report.distance, 2),
                         it=r.iterations, t_best=round(r.history[-1][0], 1)))
        print(key, runs[-1], flush=True)
    res[key] = dict(best_known=bk, runs=runs)
    save()

# ---- PORT n=30
SETTINGS = [("no_yard", dict(n_yards=0)), ("yards_inf", dict(n_yards=2)),
            ("yards_H1_S2", dict(n_yards=2, H=1, S=2)), ("yards_H1_S1_W60", dict(n_yards=2, H=1, S=1, W=60.0))]
for seed in range(10):
    for label, kw in SETTINGS:
        key = f"port30/{seed}/{label}"
        if done(key):
            continue
        inst = generate(30, seed=seed, **kw)
        r = solve(inst, time_limit=200, max_iter=10**6, seed=seed)
        res[key] = dict(unassigned=len(r.operator_stats["unassigned"]), vehicles=r.report.vehicles_used,
                        cost=round(r.report.cost, 1), km=round(r.report.distance, 1), transfers=r.report.transfers,
                        it=r.iterations, t_best=round(r.history[-1][0], 1))
        print(key, res[key], flush=True)
        save()
print("CAMPAIGN DONE", flush=True)
