# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Sensitivity of the dwell axis to the earliest-start policy (added after the campaign, not pre-registered).

The search, the verifier and the exact models of the paper schedule every operation at its earliest date; a
plan whose storage at a transfer point exceeds W_t is rejected even when a vehicle could wait before the drop
and shorten the storage (Section 4.5 of the method paper).  This script measures what that policy costs on the
dwell axis of phase 7 without a new campaign:

  * a second feasibility check `feasible_with_waiting(inst, sol)` allows deliberate waiting: the event graph
    of the plan receives, for every transfer (drop d, pick p) at a point with finite W_t, a backward arc
    p -> d of weight -(delta_d + W_t) (the drop may start no earlier than x_p - delta_d - W_t), the least
    solution of the resulting system is computed by Bellman-Ford (a positive circuit means infeasible),
    time windows are checked on it, and S_t / H_t are checked on that schedule by the verifier's sweeps;
  * the pool closure of phase 7 is recomputed for every cell of the dwell axis with this check in place of
    the verifier: every yard run of the day may donate its plan to the cell if the plan is feasible under
    the cell's limits once waiting is allowed.

Outputs: results/phase7_waiting.json, tables/phase7_waiting.tex.
"""
import json, os, sys, statistics as st
from collections import defaultdict

sys.path.insert(0, "scripts")
from job import parse_setting, job_key
from pdpt.instance import INF
from pdpt.portgen import generate
from pdpt.solution import Solution, PICKUP, DELIVERY, DROP, PICK
from pdpt.verifier import verify

R, OUT = "results", "tables"
EPS = 1e-6


def feasible_with_waiting(inst, sol):
    """Feasibility of a plan when a vehicle may wait before a drop to respect W_t.  Returns (feasible, reason)."""
    rep = verify(inst, sol)
    if rep.feasible:
        return True, "earliest"
    structural = [m for m in rep.violations if not any(k in m for k in ("stored", "starts", "returns", "storage", "simultaneous", "picked", "circuit"))]
    if structural:
        return False, "structure"          # custody, capacity or compatibility: no schedule repairs these
    # windows, storage, S_t and H_t are re-evaluated on the schedule with waiting below
    # ---- event graph: nodes (ri, vi) and (ri, -1) for the return; arcs with weights
    nodes, arcs, release, deadline, dur = [], [], {}, {}, {}
    for ri, route in enumerate(sol.routes):
        veh = inst.vehicles[route.vehicle]
        prev, prev_node = None, veh.start_node
        for vi, vis in enumerate(route.visits):
            u = (ri, vi); nodes.append(u)
            node = inst.nodes[vis.node]
            d = node.service
            if vis.op in (DROP, PICK):
                d = inst.transfer_points[vis.transfer_point].transfer_time_per_unit * inst.requests[vis.request].quantity
            dur[u] = d
            release[u] = max(node.tw_start, inst.nodes[veh.start_node].tw_start + inst.time(veh.start_node, vis.node) if prev is None else -INF)
            deadline[u] = node.tw_end
            if prev is not None:
                arcs.append((prev, u, dur[prev] + inst.time(prev_node, vis.node)))
            prev, prev_node = u, vis.node
        u = (ri, -1); nodes.append(u); dur[u] = 0.0
        release[u] = -INF if prev is not None else inst.nodes[veh.start_node].tw_start
        deadline[u] = inst.nodes[veh.end_node].tw_end
        if prev is not None:
            arcs.append((prev, u, dur[prev] + inst.time(prev_node, veh.end_node)))
    # ---- transfers: match drops to picks as the verifier does (same point, another route, custody order)
    seen = defaultdict(lambda: defaultdict(list))
    for ri, route in enumerate(sol.routes):
        for vi, vis in enumerate(route.visits):
            seen[vis.request][vis.op].append((ri, vi))
    for rid in inst.requests:
        s = seen[rid]
        start = s[PICKUP][0]
        drops, picks = sorted(s[DROP]), sorted(s[PICK])
        while True:
            r0, i0 = start
            same = [d for d in drops if d[0] == r0 and d[1] > i0]
            if not same:
                break
            d = min(same, key=lambda p: p[1]); drops.remove(d)
            tp = sol.routes[d[0]].visits[d[1]].transfer_point
            cands = [p for p in picks if sol.routes[p[0]].visits[p[1]].transfer_point == tp and p[0] != r0]
            if not cands:
                return False, "structure"
            p = cands[0]; picks.remove(p)
            arcs.append((d, p, dur[d]))                                   # pick after drop end
            W = inst.transfer_points[tp].max_storage_time
            if W < INF:
                arcs.append((p, d, -(dur[d] + W)))                        # drop no earlier than pick - delta - W
            start = p
    # ---- least solution by Bellman-Ford on x_v = max(a_v, max_u x_u + w_uv)
    x = {v: release[v] for v in nodes}
    for it in range(len(nodes) + 1):
        changed = False
        for u, v, w in arcs:
            if x[u] > -INF and x[u] + w > x[v] + EPS:
                x[v] = x[u] + w; changed = True
        if not changed:
            break
    else:
        return False, "positive circuit"
    for v in nodes:
        if x[v] > deadline[v] + EPS:
            return False, "window"
    # ---- resources on this schedule (same sweeps as the verifier)
    times = {v: (x[v], x[v], x[v] + dur[v]) for v in nodes}
    for tpid, tp in inst.transfer_points.items():
        ev, hv = [], []
        # rebuild sync pairs from arcs with positive forward transfer weight: (d, p) pairs are those with w == dur[d] and d, p on different routes at a point
        for u, v, w in arcs:
            if u[1] >= 0 and v[1] >= 0 and u[0] != v[0] and w >= 0 and sol.routes[u[0]].visits[u[1]].op == DROP and sol.routes[v[0]].visits[v[1]].op == PICK \
               and sol.routes[u[0]].visits[u[1]].transfer_point == tpid:
                q = inst.requests[sol.routes[u[0]].visits[u[1]].request].quantity
                ev.append((times[u][2], +q)); ev.append((times[v][1], -q))
        if tp.storage_capacity < INF:
            ev.sort(key=lambda e: (e[0], e[1])); stored = 0.0
            for t_, dq in ev:
                stored += dq
                if stored > tp.storage_capacity + EPS:
                    return False, "storage"
        if tp.handling_slots < INF:
            for ri, route in enumerate(sol.routes):
                for vi, vis in enumerate(route.visits):
                    if vis.op in (DROP, PICK) and vis.transfer_point == tpid and dur[(ri, vi)] > 0:
                        hv.append((times[(ri, vi)][1], +1)); hv.append((times[(ri, vi)][2], -1))
            hv.sort(key=lambda e: (e[0], e[1])); busy = 0
            for t_, d in hv:
                busy += d
                if busy > tp.handling_slots:
                    return False, "handling"
    return True, "waiting"


def main():
    jobs = json.load(open(f"{R}/campaign_jobs.json"))["port7"]
    rows = defaultdict(dict)
    for r in jobs:
        rows[(r["n"], r["seed"])][r["setting"]] = r
    plans = {}
    def plan(r):
        k = job_key(r["argv"])
        if k not in plans:
            plans[k] = Solution.from_dict(json.load(open(f"{R}/jobs/{k}.json"))["solution"])
        return plans[k]
    W_CELLS = [f"yards_H{h}_S{s_}_W{w}" for h in ("1", "inf") for s_ in ("1", "2", "3", "inf") for w in ("30", "60", "120")] + ["yards_H1_S2_W240"]
    out, lines = {}, []
    for n in (20, 30, 50):
        for cell in W_CELLS:
            pool, wait, gained, reasons = [], [], 0, defaultdict(int)
            for day in range(20):
                S = rows[(n, day)]
                ctrl = S["no_yard_warm"]["cost"]
                inst = generate(n, seed=day, **parse_setting(cell))
                cands = sorted((S[s] for s in S if s.startswith("yards_")), key=lambda r: r["cost"])
                best_pool = best_wait = None
                for d in cands:
                    sol = plan(d)
                    if best_pool is None and verify(inst, sol).feasible:
                        best_pool = d["cost"]
                    if best_wait is None:
                        ok, why = feasible_with_waiting(inst, sol)
                        if ok:
                            best_wait = d["cost"]; reasons[why] += 1
                    if best_pool is not None and best_wait is not None:
                        break
                pool.append(100 * (best_pool / ctrl - 1)); wait.append(100 * (best_wait / ctrl - 1))
                if best_wait < best_pool - 1e-9:
                    gained += 1
            out[f"{n}/{cell}"] = dict(pool_mean=st.mean(pool), waiting_mean=st.mean(wait), days_cheaper=gained,
                                      days_from_waiting=reasons.get("waiting", 0), max_gain_points=max(p - w for p, w in zip(pool, wait)))
            lab = cell.replace("yards_", "").replace("_", ", ").replace("H", "$H_t{=}").replace("S", "$S_t{=}").replace("W", "$W_t{=}").replace("inf", "\\infty").replace(", ", "$, ") + "$"
            lines.append(f"{n} & {lab} & {st.mean(pool):+.2f} & {st.mean(wait):+.2f} & {gained} & {max(p - w for p, w in zip(pool, wait)):.2f} \\\\")
            print(n, cell, f"pool {st.mean(pool):+.2f} waiting {st.mean(wait):+.2f} cheaper on {gained} days", dict(reasons))
    json.dump(out, open(f"{R}/phase7_waiting.json", "w"), indent=1)
    open(f"{OUT}/phase7_waiting.tex", "w").write("\n".join(lines) + "\n")                       # all 75 cells (supplement)
    axis = [l for l in lines if "$H_t{=}1$, $S_t{=}2$" in l]
    open(f"{OUT}/phase7_waiting_axis.tex", "w").write("\n".join(axis) + "\n")                  # dwell axis (paper)


if __name__ == "__main__":
    main()
