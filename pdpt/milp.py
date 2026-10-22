# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Mixed-integer formulation of the PDPTW-T on request-specific transfer vertices
(Section 5 of the paper, uncapacitated points: S_t = H_t = inf), solved with HiGHS.

Used for certified optima / lower bounds on small instances.  Three-index arc
variables x[k,i,j]; custody consistency through visit variables; big-M timing
with per-vehicle positions (MTZ) to cut zero-length subtours among co-located
vertices; synchronisation and storage-time constraints per request and point;
load propagation; compatibility by variable fixing.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import highspy

from .instance import Instance, INF
from .solution import Solution, Route, Visit, PICKUP, DELIVERY, DROP, PICK
from .verifier import verify, Report


@dataclass
class MilpResult:
    status: str
    objective: float | None
    bound: float
    gap: float | None
    solution: Solution | None
    report: Report | None
    time: float
    n_vars: int
    n_rows: int


def solve(inst: Instance, time_limit: float = 600.0, vehicle_weight: float | None = None,
          mip_gap: float = 1e-6, verbose: bool = False, relax: bool = False,
          min_vehicles: int = 0, sync_eps: float = 0.0) -> MilpResult:
    """relax=True solves the LP relaxation (Bound C); min_vehicles adds sum u_k >= value.

    sync_eps > 0 adds eps to every synchronisation constraint (pick start >= drop end + eps).  With
    sigma_t = 0 and no service time, two vehicles that exchange two loads at one point at one instant
    satisfy every constraint with equal dates although neither drop precedes the pick that collects it
    (a circuit of zero weight in the event graph); the position variables only exclude circuits inside
    one vehicle.  A positive eps excludes such vectors.  With eps = 0 the model is a relaxation of the
    problem (it admits such vectors, and the verifier rejects their decodings); with eps > 0 it is a
    restriction (a pick tight against its deadline may be cut).  The paper reports both on TT-14
    (eps = 0.01 and eps = 0); where the two optimal values agree the common value is the optimum.  Every
    returned solution is re-verified.

    Note on finite W_t: the time constraints are inequalities, so the model may delay a drop on purpose
    to respect W_t; for finite W_t it is a relaxation of the earliest-start problem of the paper (bounds
    and infeasibility proofs remain valid).  All MILP runs of the paper have W_t = inf.
    """
    t0 = time.time()
    h = highspy.Highs()
    h.setOptionValue("output_flag", verbose)
    h.setOptionValue("time_limit", float(time_limit))
    h.setOptionValue("mip_rel_gap", mip_gap)

    R = list(inst.requests.values())
    T = list(inst.transfer_points.values())
    K = list(inst.vehicles)
    kappa = inst.params.max_transfers_per_request
    if vehicle_weight is None:
        if inst.params.objective == "weighted":
            vehicle_weight = inst.params.weights.get("vehicles", 0.0)
        else:
            tot = sum(inst.dist(r.pickup, r.delivery) for r in R) * 4 + 1
            vehicle_weight = 10 * tot            # lexicographic by weight

    # ---- vertices: ("p", r) ("d", r) ("tm", r, t) ("tp", r, t) ("o", k) ("e", k)
    verts = []
    node_of, kind_of, q_of, dur_of, a_of, b_of = {}, {}, {}, {}, {}, {}
    def addv(v, node, kind, q, dur, a, b):
        verts.append(v); node_of[v] = node; kind_of[v] = kind; q_of[v] = q; dur_of[v] = dur; a_of[v] = a; b_of[v] = b
    for r in R:
        n = inst.nodes[r.pickup]; addv(("p", r.id), r.pickup, PICKUP, r.quantity, n.service, n.tw_start, n.tw_end)
        n = inst.nodes[r.delivery]; addv(("d", r.id), r.delivery, DELIVERY, -r.quantity, n.service, n.tw_start, n.tw_end)
        for t in T:
            n = inst.nodes[t.node]
            addv(("tm", r.id, t.id), t.node, DROP, -r.quantity, t.transfer_time_per_unit * r.quantity, n.tw_start, n.tw_end)
            addv(("tp", r.id, t.id), t.node, PICK, r.quantity, t.transfer_time_per_unit * r.quantity, n.tw_start, n.tw_end)
    cust = list(verts)
    for k in K:
        v = inst.vehicles[k]
        n = inst.nodes[v.start_node]; addv(("o", k), v.start_node, "start", 0.0, 0.0, n.tw_start, n.tw_end)
        n = inst.nodes[v.end_node]; addv(("e", k), v.end_node, "end", 0.0, 0.0, n.tw_start, n.tw_end)
    horizon = max(b for b in b_of.values() if b < INF) if any(b < INF for b in b_of.values()) else 1e6
    Bmax = min(horizon, 1e6)

    def allowed(k, v):
        if v[0] in ("o", "e"):
            return v[1] == k
        r = inst.requests[v[1]]
        return inst.vehicle_allows(inst.vehicles[k], r.load_type) and r.quantity <= inst.vehicles[k].capacity

    # ---- variables
    col = {}
    ncol = 0
    def var(name, lb, ub, cost, integer):
        nonlocal ncol
        h.addVar(lb, ub)
        h.changeColCost(ncol, cost)
        if integer and not relax:
            h.changeColIntegrality(ncol, highspy.HighsVarType.kInteger)
        col[name] = ncol
        ncol += 1
        return ncol - 1

    arcs = {}
    for k in K:
        veh = inst.vehicles[k]
        Vk = [v for v in cust if allowed(k, v)] + [("o", k), ("e", k)]
        for i in Vk:
            for j in Vk:
                if i == j or j == ("o", k) or i == ("e", k):
                    continue
                if i == ("o", k) and j == ("e", k):
                    continue
                if kind_of[i] == DELIVERY and j[0] == "p" and j[1] == i[1]:
                    continue        # delivery then pickup of the same request on one vehicle
                ni, nj = node_of[i], node_of[j]
                if a_of[i] + dur_of[i] + inst.time(ni, nj) > min(b_of[j], Bmax) + 1e-9:
                    continue
                c = veh.cost_per_km * inst.dist(ni, nj)
                arcs[(k, i, j)] = var(("x", k, i, j), 0, 1, c, True)
    u = {k: var(("u", k), 0, 1, vehicle_weight + inst.vehicles[k].fixed_cost, True) for k in K}
    y = {(r.id, t.id): var(("y", r.id, t.id), 0, 1, t.handling_cost * r.quantity, True) for r in R for t in T}
    s = {(k, v): var(("s", k, v), a_of[v], min(b_of[v], Bmax), 0.0, False) for k in K for v in verts if allowed(k, v)}
    L = {(k, v): var(("L", k, v), 0.0, inst.vehicles[k].capacity, 0.0, False) for k in K for v in verts if allowed(k, v)}
    nV = len(verts)
    pos = {(k, v): var(("pi", k, v), 0.0, nV, 0.0, False) for k in K for v in verts if allowed(k, v)}

    nrow = 0
    def row(lb, ub, terms):
        nonlocal nrow
        idx = [col[n] if isinstance(n, tuple) else n for n, _ in terms]
        vals = [float(c) for _, c in terms]
        h.addRow(lb, ub, len(idx), idx, vals)
        nrow += 1

    def out_arcs(k, i):
        return [a for (kk, ii, jj), a in arcs.items() if kk == k and ii == i]
    def in_arcs(k, j):
        return [a for (kk, ii, jj), a in arcs.items() if kk == k and jj == j]
    outs = {(k, i): out_arcs(k, i) for k in K for i in verts if allowed(k, i)}
    ins = {(k, j): in_arcs(k, j) for k in K for j in verts if allowed(k, j)}

    # ---- degree / flow
    for k in K:
        row(0, 0, [(a, 1) for a in outs[(k, ("o", k))]] + [(("u", k), -1)])
        row(0, 0, [(a, 1) for a in ins[(k, ("e", k))]] + [(("u", k), -1)])
        for v in cust:
            if allowed(k, v):
                row(0, 0, [(a, 1) for a in outs[(k, v)]] + [(a, -1) for a in ins[(k, v)]])
    for r in R:
        for kind in ("p", "d"):
            row(1, 1, [(a, 1) for k in K if allowed(k, (kind, r.id)) for a in outs[(k, (kind, r.id))]])
        for t in T:
            for kind in ("tm", "tp"):
                row(0, 0, [(a, 1) for k in K if allowed(k, (kind, r.id, t.id)) for a in outs[(k, (kind, r.id, t.id))]]
                    + [(("y", r.id, t.id), -1)])
        row(0, kappa, [(("y", r.id, t.id), 1) for t in T])
    # ---- custody consistency
    for r in R:
        for k in K:
            if not allowed(k, ("p", r.id)):
                continue
            terms = [(a, 1) for a in outs[(k, ("p", r.id))]] + [(a, -1) for a in outs[(k, ("d", r.id))]]
            for t in T:
                terms += [(a, -1) for a in outs[(k, ("tm", r.id, t.id))]] + [(a, 1) for a in outs[(k, ("tp", r.id, t.id))]]
            row(0, 0, terms)
            for t in T:
                row(-INF, 1, [(a, 1) for a in outs[(k, ("tm", r.id, t.id))]] + [(a, 1) for a in outs[(k, ("tp", r.id, t.id))]])
    # ---- time, load, position on arcs
    for (k, i, j), a in arcs.items():
        tij = inst.time(node_of[i], node_of[j])
        M = (min(b_of[i], Bmax) + dur_of[i] + tij - a_of[j])
        if M > 0:
            row(-INF, M - dur_of[i] - tij, [(("s", k, i), 1), (("s", k, j), -1), (a, M)])
        Q = inst.vehicles[k].capacity
        row(-INF, Q - q_of[j], [(("L", k, i), 1), (("L", k, j), -1), (a, Q)])
        row(-INF, Q + q_of[j], [(("L", k, j), 1), (("L", k, i), -1), (a, Q)])
        row(-INF, nV - 1, [(("pi", k, i), 1), (("pi", k, j), -1), (a, nV)])
    for k in K:
        h.changeColBounds(col[("L", k, ("o", k))], 0.0, 0.0)
    # ---- precedence within a vehicle (both vertices visited by k)
    def prec(k, i, j, extra=0.0):
        """s_j >= s_i + dur_i + t_ij when k visits both i and j."""
        M = min(b_of[i], Bmax) + dur_of[i] + inst.time(node_of[i], node_of[j]) + extra - a_of[j]
        if M <= 0:
            return
        vi = [(a, 1) for a in outs[(k, i)]]
        vj = [(a, 1) for a in outs[(k, j)]]
        # s_i + dur + t - s_j <= M (2 - v_i - v_j)  <=>  s_i - s_j + M v_i + M v_j <= 2M - dur - t - extra
        row(-INF, 2 * M - dur_of[i] - inst.time(node_of[i], node_of[j]) - extra,
            [(("s", k, i), 1), (("s", k, j), -1)] + [(a, M) for a, _ in vi] + [(a, M) for a, _ in vj])
    for r in R:
        for k in K:
            if not allowed(k, ("p", r.id)):
                continue
            prec(k, ("p", r.id), ("d", r.id))
            for t in T:
                prec(k, ("p", r.id), ("tm", r.id, t.id))
                prec(k, ("tp", r.id, t.id), ("d", r.id))
    # ---- synchronisation and storage time across vehicles
    for r in R:
        for t in T:
            tm, tp = ("tm", r.id, t.id), ("tp", r.id, t.id)
            for k in K:
                if not allowed(k, tm):
                    continue
                for k2 in K:
                    if k2 == k or not allowed(k2, tp):
                        continue
                    M = min(b_of[tm], Bmax) + dur_of[tm] + sync_eps - a_of[tp]
                    if M > 0:
                        row(-INF, 2 * M - dur_of[tm] - sync_eps,
                            [(("s", k, tm), 1), (("s", k2, tp), -1)] + [(a, M) for a in outs[(k, tm)]] + [(a, M) for a in outs[(k2, tp)]])
                    if t.max_storage_time < INF:
                        M2 = min(b_of[tp], Bmax) - a_of[tm] - dur_of[tm] - t.max_storage_time
                        if M2 > 0:
                            row(-INF, 2 * M2 + dur_of[tm] + t.max_storage_time,
                                [(("s", k2, tp), 1), (("s", k, tm), -1)] + [(a, M2) for a in outs[(k, tm)]] + [(a, M2) for a in outs[(k2, tp)]])

    if min_vehicles > 0:
        row(min_vehicles, INF, [(("u", k), 1) for k in K])
    # valid inequality: each request's pickup is served, so sum over k of u_k >= 1
    row(1, INF, [(("u", k), 1) for k in K])
    h.run()
    st = h.getModelStatus()
    info = h.getInfo()
    status = h.modelStatusToString(st)
    bound = info.objective_function_value if relax else info.mip_dual_bound
    obj = info.objective_function_value if info.primal_solution_status == 2 or status == "Optimal" else None
    sol, rep = None, None
    if obj is not None and not relax:
        x = h.getSolution().col_value
        routes = []
        for k in K:
            cur = ("o", k)
            visits = []
            guard = 0
            while cur != ("e", k) and guard < nV + 2:
                guard += 1
                nxt = None
                for (kk, i, j), a in arcs.items():
                    if kk == k and i == cur and x[a] > 0.5:
                        nxt = j
                        break
                if nxt is None:
                    break
                if nxt[0] in ("p", "d"):
                    visits.append(Visit(node_of[nxt], kind_of[nxt], nxt[1]))
                elif nxt[0] in ("tm", "tp"):
                    visits.append(Visit(node_of[nxt], kind_of[nxt], nxt[1], nxt[2]))
                cur = nxt
            if visits:
                routes.append(Route(k, visits))
        sol = Solution(inst.name, routes=routes)
        rep = verify(inst, sol)
        # objective in the instance's own terms is rep; the MILP objective includes vehicle_weight
    gap = None if obj is None else (obj - bound) / max(abs(obj), 1e-9)
    return MilpResult(status, obj, bound, gap, sol, rep, time.time() - t0, ncol, nrow)
