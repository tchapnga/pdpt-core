# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""CP-SAT model of the PDPTW-CT (uncapacitated or capacitated transfer points).

Used for (a) certified optima on small/medium instances and (b) lower bounds via
the solver's best bound at the time limit.  Interval-based: one optional
interval per (vehicle, visit); vehicle sequencing via NoOverlap on intervals
with travel encoded by circuit constraints is heavy, so we use the classical
"vehicle circuit" model: for each vehicle an AddCircuit over its admissible
vertices (with self-loops for unvisited vertices), MTZ-free time propagation
through literal-conditioned constraints, cumulative constraints for S_t / H_t.

Time is integer: minutes (PORT) or units*SCALE (TT-14), set by `scale`.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .instance import Instance, INF
from .solution import Solution, Route, Visit, PICKUP, DELIVERY, DROP, PICK
from .verifier import verify, Report


@dataclass
class CpResult:
    status: str
    objective: float | None
    bound: float
    gap: float | None
    solution: Solution | None
    report: Report | None
    time: float


def solve(inst: Instance, time_limit: float = 300.0, scale: float = 1.0, vehicle_weight: float | None = None,
          rounding: str = "nearest",
          workers: int = 2, log: bool = False, min_vehicles: int = 0) -> CpResult:
    t0 = time.time()
    R = list(inst.requests.values())
    T = list(inst.transfer_points.values())
    K = list(inst.vehicles)
    kappa = inst.params.max_transfers_per_request
    if vehicle_weight is None:
        if inst.params.objective == "weighted":
            vehicle_weight = inst.params.weights.get("vehicles", 0.0)
        else:
            vehicle_weight = 10 * (sum(inst.dist(r.pickup, r.delivery) for r in R) * 4 + 1)
    S = scale
    # rounding = "nearest": plain discretisation.  "relax": travel/service times and window starts
    # rounded down, window ends and storage limits up (a relaxation: INFEASIBLE / a bound is exact).
    # "restrict": the opposite (a solution found is exactly feasible).
    def I(x, kind="t"):     # to integer time/cost units; kind t = duration/travel/window start, b = deadline
        if rounding == "nearest":
            return int(round(x * S))
        down = (rounding == "relax") == (kind == "t")
        v = x * S
        return int(math.floor(v + 1e-9)) if down else int(math.ceil(v - 1e-9))

    m = cp_model.CpModel()
    # ---- vertices
    verts, node_of, kind_of, q_of, dur_of, a_of, b_of = [], {}, {}, {}, {}, {}, {}
    def addv(v, node, kind, q, dur, a, b):
        verts.append(v); node_of[v] = node; kind_of[v] = kind; q_of[v] = q; dur_of[v] = dur; a_of[v] = a; b_of[v] = b
    horizon = 0.0
    for r in R:
        for v, node, kind, q in ((("p", r.id), r.pickup, PICKUP, r.quantity), (("d", r.id), r.delivery, DELIVERY, -r.quantity)):
            n = inst.nodes[node]; addv(v, node, kind, q, n.service, n.tw_start, n.tw_end)
        for t in T:
            n = inst.nodes[t.node]; d = t.transfer_time_per_unit * r.quantity
            addv(("tm", r.id, t.id), t.node, DROP, -r.quantity, d, n.tw_start, n.tw_end)
            addv(("tp", r.id, t.id), t.node, PICK, r.quantity, d, n.tw_start, n.tw_end)
    for k in K:
        veh = inst.vehicles[k]
        n = inst.nodes[veh.start_node]; addv(("o", k), veh.start_node, "start", 0.0, 0.0, n.tw_start, n.tw_end)
        n = inst.nodes[veh.end_node]; addv(("e", k), veh.end_node, "end", 0.0, 0.0, n.tw_start, n.tw_end)
    finite_b = [b for b in b_of.values() if b < INF]
    H = max(finite_b) if finite_b else 10 * sum(inst.time(r.pickup, r.delivery) for r in R)
    H = I(H, 'b') + 1

    def allowed(k, v):
        if v[0] in ("o", "e"):
            return v[1] == k
        r = inst.requests[v[1]]
        return inst.vehicle_allows(inst.vehicles[k], r.load_type) and r.quantity <= inst.vehicles[k].capacity

    # ---- variables
    visit = {}      # (k, v) -> bool
    start = {}      # (k, v) -> int
    load = {}       # (k, v) -> int (scaled x1, quantities assumed integral or scaled)
    QS = 1
    arcs = {}       # (k, i, j) -> bool
    used = {k: m.NewBoolVar(f"u_{k}") for k in K}
    for k in K:
        veh = inst.vehicles[k]
        Vk = [v for v in verts if allowed(k, v)]
        for v in Vk:
            visit[(k, v)] = m.NewBoolVar(f"y_{k}_{v}")
            lb, ub = I(a_of[v]), min(I(b_of[v], 'b'), H) if b_of[v] < INF else H
            start[(k, v)] = m.NewIntVar(lb, max(lb, ub), f"s_{k}_{v}")
            cap = veh.capacity if veh.capacity < INF else sum(r.quantity for r in R)
            load[(k, v)] = m.NewIntVar(0, int(math.ceil(cap * QS)), f"L_{k}_{v}")
        # circuit over Vk: index map
        idx = {v: i for i, v in enumerate(Vk)}
        circuit = []
        for v in Vk:
            if v[0] in ("o", "e"):
                continue
            circuit.append((idx[v], idx[v], visit[(k, v)].Not()))     # self-loop = not visited
        # start/end must be in the circuit iff used; close the circuit e -> o
        circuit.append((idx[("e", k)], idx[("o", k)], used[k]))
        circuit.append((idx[("o", k)], idx[("o", k)], used[k].Not()))
        circuit.append((idx[("e", k)], idx[("e", k)], used[k].Not()))
        m.Add(visit[(k, ("o", k))] == used[k])
        m.Add(visit[(k, ("e", k))] == used[k])
        for i in Vk:
            for j in Vk:
                if i == j or j == ("o", k) or i == ("e", k):
                    continue
                if i == ("o", k) and j == ("e", k):
                    continue
                if kind_of[i] == DELIVERY and j[0] == "p" and j[1] == i[1]:
                    continue
                tij = inst.time(node_of[i], node_of[j])
                if a_of[i] + dur_of[i] + tij > b_of[j] + 1e-9:
                    continue
                lit = m.NewBoolVar(f"x_{k}_{i}_{j}")
                arcs[(k, i, j)] = lit
                circuit.append((idx[i], idx[j], lit))
                # time and load propagation when the arc is used
                m.Add(start[(k, j)] >= start[(k, i)] + I(dur_of[i] + tij)).OnlyEnforceIf(lit)
                m.Add(load[(k, j)] == load[(k, i)] + int(round(q_of[j] * QS))).OnlyEnforceIf(lit)
        m.AddCircuit(circuit)
        m.Add(load[(k, ("o", k))] == 0)
        # visited vertices have in-degree 1 (implied by circuit); nothing else needed
    # ---- each pickup/delivery served once; transfers matched
    y = {}
    for r in R:
        m.AddExactlyOne([visit[(k, ("p", r.id))] for k in K if (k, ("p", r.id)) in visit])
        m.AddExactlyOne([visit[(k, ("d", r.id))] for k in K if (k, ("d", r.id)) in visit])
        for t in T:
            y[(r.id, t.id)] = m.NewBoolVar(f"tr_{r.id}_{t.id}")
            m.Add(sum(visit[(k, ("tm", r.id, t.id))] for k in K if (k, ("tm", r.id, t.id)) in visit) == y[(r.id, t.id)])
            m.Add(sum(visit[(k, ("tp", r.id, t.id))] for k in K if (k, ("tp", r.id, t.id)) in visit) == y[(r.id, t.id)])
        if T:
            m.Add(sum(y[(r.id, t.id)] for t in T) <= kappa)
        # custody consistency per vehicle
        for k in K:
            if (k, ("p", r.id)) not in visit:
                continue
            lhs = visit[(k, ("p", r.id))] - visit[(k, ("d", r.id))]
            rhs = sum(visit[(k, ("tm", r.id, t.id))] - visit[(k, ("tp", r.id, t.id))] for t in T)
            m.Add(lhs == rhs)
            for t in T:
                m.Add(visit[(k, ("tm", r.id, t.id))] + visit[(k, ("tp", r.id, t.id))] <= 1)
            # precedence on the same vehicle
            m.Add(start[(k, ("d", r.id))] >= start[(k, ("p", r.id))] + I(dur_of[("p", r.id)] + inst.time(r.pickup, r.delivery))) \
                .OnlyEnforceIf([visit[(k, ("p", r.id))], visit[(k, ("d", r.id))]])
            for t in T:
                tm, tp = ("tm", r.id, t.id), ("tp", r.id, t.id)
                m.Add(start[(k, tm)] >= start[(k, ("p", r.id))] + I(dur_of[("p", r.id)] + inst.time(r.pickup, t.node))) \
                    .OnlyEnforceIf([visit[(k, ("p", r.id))], visit[(k, tm)]])
                m.Add(start[(k, ("d", r.id))] >= start[(k, tp)] + I(dur_of[tp] + inst.time(t.node, r.delivery))) \
                    .OnlyEnforceIf([visit[(k, tp)], visit[(k, ("d", r.id))]])
    # ---- synchronisation, storage time, resources
    for t in T:
        drop_intervals, pick_intervals, stored = [], [], []
        for r in R:
            tm, tp = ("tm", r.id, t.id), ("tp", r.id, t.id)
            # global (vehicle-free) drop end and pick start, for the point's constraints
            d_end = m.NewIntVar(0, H, f"dend_{r.id}_{t.id}")
            p_start = m.NewIntVar(0, H, f"pst_{r.id}_{t.id}")
            for k in K:
                if (k, tm) in visit:
                    m.Add(d_end == start[(k, tm)] + I(dur_of[tm])).OnlyEnforceIf(visit[(k, tm)])
                if (k, tp) in visit:
                    m.Add(p_start == start[(k, tp)]).OnlyEnforceIf(visit[(k, tp)])
            m.Add(p_start >= d_end).OnlyEnforceIf(y[(r.id, t.id)])
            if t.max_storage_time < INF:
                m.Add(p_start - d_end <= I(t.max_storage_time, 'b')).OnlyEnforceIf(y[(r.id, t.id)])
            if t.storage_capacity < INF:
                size = m.NewIntVar(0, H, f"stsz_{r.id}_{t.id}")
                m.Add(size == p_start - d_end).OnlyEnforceIf(y[(r.id, t.id)])
                m.Add(size == 0).OnlyEnforceIf(y[(r.id, t.id)].Not())
                iv = m.NewOptionalIntervalVar(d_end, size, p_start, y[(r.id, t.id)], f"stored_{r.id}_{t.id}")
                stored.append((iv, int(round(r.quantity * QS))))
            if t.handling_slots < INF and dur_of[tm] > 0:
                dd = I(dur_of[tm])
                d_st = m.NewIntVar(0, H, f"dst_{r.id}_{t.id}")
                m.Add(d_st == d_end - dd)
                drop_intervals.append(m.NewOptionalIntervalVar(d_st, dd, d_end, y[(r.id, t.id)], f"dropiv_{r.id}_{t.id}"))
                p_end = m.NewIntVar(0, H, f"pend_{r.id}_{t.id}")
                m.Add(p_end == p_start + dd)
                pick_intervals.append(m.NewOptionalIntervalVar(p_start, dd, p_end, y[(r.id, t.id)], f"pickiv_{r.id}_{t.id}"))
        if t.storage_capacity < INF and stored:
            m.AddCumulative([iv for iv, _ in stored], [q for _, q in stored], int(math.floor(t.storage_capacity * QS)))
        if t.handling_slots < INF and (drop_intervals or pick_intervals):
            ops = drop_intervals + pick_intervals
            m.AddCumulative(ops, [1] * len(ops), int(t.handling_slots))
    if min_vehicles:
        m.Add(sum(used.values()) >= min_vehicles)
    # ---- objective (scaled cost)
    terms = []
    for (k, i, j), lit in arcs.items():
        c = inst.vehicles[k].cost_per_km * inst.dist(node_of[i], node_of[j])
        if c:
            terms.append(I(c) * lit)
    for k in K:
        terms.append(I(vehicle_weight + inst.vehicles[k].fixed_cost) * used[k])
    for (rid, tid), lit in y.items():
        c = inst.transfer_points[tid].handling_cost * inst.requests[rid].quantity
        if c:
            terms.append(I(c) * lit)
    m.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    solver.parameters.log_search_progress = log
    st = solver.Solve(m)
    status = solver.StatusName(st)
    bound = solver.BestObjectiveBound() / S
    obj = solver.ObjectiveValue() / S if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    sol, rep = None, None
    if obj is not None:
        routes = []
        for k in K:
            if solver.Value(used[k]) == 0:
                continue
            cur = ("o", k)
            vis = []
            guard = 0
            while cur != ("e", k) and guard < len(verts) + 2:
                guard += 1
                nxt = None
                for (kk, i, j), lit in arcs.items():
                    if kk == k and i == cur and solver.Value(lit):
                        nxt = j
                        break
                if nxt is None:
                    break
                if nxt[0] in ("p", "d"):
                    vis.append(Visit(node_of[nxt], kind_of[nxt], nxt[1]))
                elif nxt[0] in ("tm", "tp"):
                    vis.append(Visit(node_of[nxt], kind_of[nxt], nxt[1], nxt[2]))
                cur = nxt
            if vis:
                routes.append(Route(k, vis))
        sol = Solution(inst.name, routes=routes)
        rep = verify(inst, sol)
    gap = None if obj is None else (obj - bound) / max(abs(obj), 1e-9)
    return CpResult(status, obj, bound, gap, sol, rep, time.time() - t0)
