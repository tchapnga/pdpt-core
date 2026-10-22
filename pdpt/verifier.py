# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Independent verifier for PDPTW-T solutions.

Recomputes the schedule from scratch (earliest-start propagation across routes
and through transfer synchronisations), checks every constraint of the
formulation, and returns the cost vector.  Solvers never call this to build
solutions; it is the referee.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .instance import Instance, INF
from .solution import Solution, Visit, PICKUP, DELIVERY, DROP, PICK, OPS

EPS = 1e-6


@dataclass
class Schedule:
    # (route index, visit index) -> (arrival, start, end)
    times: dict[tuple[int, int], tuple[float, float, float]] = field(default_factory=dict)
    # (route index, visit index) -> load after service
    loads: dict[tuple[int, int], float] = field(default_factory=dict)


@dataclass
class Report:
    feasible: bool
    violations: list[str]
    vehicles_used: int
    distance: float
    transport_cost: float
    handling_cost: float
    emissions: float
    transfers: int
    schedule: Schedule

    @property
    def cost(self) -> float:
        return self.transport_cost + self.handling_cost

    def objective(self, inst: Instance):
        if inst.params.objective == "weighted":
            w = inst.params.weights
            return (w.get("vehicles", 0) * self.vehicles_used + w.get("cost", 1) * self.cost
                    + w.get("emissions", 0) * self.emissions)
        return (self.vehicles_used, self.cost, self.emissions)


def single_visit_ok(visits) -> bool:
    """True iff every transfer point appears in one contiguous block of operations of the route."""
    seen, prev = set(), None
    for vis in visits:
        tp = vis.transfer_point
        if tp and tp != prev:
            if tp in seen:
                return False
            seen.add(tp)
        prev = tp
    return True


def verify(inst: Instance, sol: Solution) -> Report:
    v: list[str] = []
    sched = Schedule()

    # ---- 1. structure: every request served once, chains consistent ------
    seen: dict[str, dict[str, list[tuple[int, int]]]] = {}
    for ri, route in enumerate(sol.routes):
        if route.vehicle not in inst.vehicles:
            v.append(f"route {ri}: unknown vehicle {route.vehicle}")
            continue
        for vi, vis in enumerate(route.visits):
            if vis.op not in OPS:
                v.append(f"route {ri} visit {vi}: unknown op {vis.op}")
                continue
            if vis.request not in inst.requests:
                v.append(f"route {ri} visit {vi}: unknown request {vis.request}")
                continue
            req = inst.requests[vis.request]
            if vis.op == PICKUP and vis.node != req.pickup:
                v.append(f"request {req.id}: pickup at wrong node {vis.node}")
            if vis.op == DELIVERY and vis.node != req.delivery:
                v.append(f"request {req.id}: delivery at wrong node {vis.node}")
            if vis.op in (DROP, PICK):
                if vis.transfer_point not in inst.transfer_points:
                    v.append(f"request {req.id}: unknown transfer point {vis.transfer_point}")
                    continue
                if vis.node != inst.transfer_points[vis.transfer_point].node:
                    v.append(f"request {req.id}: transfer visit at wrong node {vis.node}")
            seen.setdefault(vis.request, {}).setdefault(vis.op, []).append((ri, vi))

    for rid, req in inst.requests.items():
        s = seen.get(rid, {})
        if len(s.get(PICKUP, [])) != 1:
            v.append(f"request {rid}: pickup served {len(s.get(PICKUP, []))} times")
        if len(s.get(DELIVERY, [])) != 1:
            v.append(f"request {rid}: delivery served {len(s.get(DELIVERY, []))} times")
        drops, picks = s.get(DROP, []), s.get(PICK, [])
        if len(drops) != len(picks):
            v.append(f"request {rid}: {len(drops)} drops but {len(picks)} picks")
        if len(drops) > inst.params.max_transfers_per_request:
            v.append(f"request {rid}: {len(drops)} transfers > kappa={inst.params.max_transfers_per_request}")
    if v:
        return _report(inst, sol, False, v, sched)

    # Build the chain of custody per request: pickup -> (drop, pick)* -> delivery.
    # Each leg (pickup..drop | pick..drop | pick..delivery) must be on ONE route,
    # in order, and the drop of leg i and pick of leg i+1 must share a transfer point.
    chains: dict[str, list[tuple[int, int, int]]] = {}   # rid -> list of (route, start_vi, end_vi)
    sync: list[tuple[tuple[int, int], tuple[int, int], str, str]] = []   # (drop pos, pick pos, tp, rid)
    for rid in inst.requests:
        s = seen[rid]
        (rp, vp), = s[PICKUP]
        (rd, vd), = s[DELIVERY]
        drops = sorted(s.get(DROP, []))
        picks = sorted(s.get(PICK, []))
        legs = []
        # leg starting at pickup
        start = (rp, vp)
        # Order drops by route-then-position is not meaningful across routes; instead
        # follow custody: from current start, the drop must be on the same route, after start.
        remaining_drops = list(drops)
        remaining_picks = list(picks)
        ok = True
        while True:
            r0, i0 = start
            same_route_drops = [d for d in remaining_drops if d[0] == r0 and d[1] > i0]
            if same_route_drops:
                d = min(same_route_drops, key=lambda p: p[1])
                remaining_drops.remove(d)
                legs.append((r0, i0, d[1]))
                tp = sol.routes[d[0]].visits[d[1]].transfer_point
                # matching pick at the same transfer point, on another route
                cands = [p for p in remaining_picks
                         if sol.routes[p[0]].visits[p[1]].transfer_point == tp and p[0] != r0]
                if not cands:
                    v.append(f"request {rid}: drop at {tp} has no matching pick on another vehicle")
                    ok = False
                    break
                p = cands[0]
                remaining_picks.remove(p)
                sync.append((d, p, tp, rid))
                start = p
            else:
                if (rd, vd)[0] != r0 or vd <= i0:
                    v.append(f"request {rid}: delivery not on the vehicle holding the load, or before it")
                    ok = False
                    break
                legs.append((r0, i0, vd))
                break
        if ok and (remaining_drops or remaining_picks):
            v.append(f"request {rid}: unmatched transfer visits")
            ok = False
        if ok:
            chains[rid] = legs
    if v:
        return _report(inst, sol, False, v, sched)

    # ---- 2. compatibility and capacity along each route -----------------
    for ri, route in enumerate(sol.routes):
        veh = inst.vehicles[route.vehicle]
        load = 0.0
        for vi, vis in enumerate(route.visits):
            req = inst.requests[vis.request]
            if not inst.vehicle_allows(veh, req.load_type):
                v.append(f"vehicle {veh.id} cannot carry type {req.load_type} (request {req.id})")
            if vis.op in (PICKUP, PICK):
                load += req.quantity
            else:
                load -= req.quantity
            if load > veh.capacity + EPS:
                v.append(f"vehicle {veh.id}: load {load:.3f} > capacity {veh.capacity} at visit {vi}")
            if load < -EPS:
                v.append(f"vehicle {veh.id}: negative load at visit {vi}")
            sched.loads[(ri, vi)] = load
        if abs(load) > EPS:
            v.append(f"vehicle {veh.id}: ends with load {load:.3f}")

    # ---- 3a. consistency: the event graph (route arcs + transfer arcs drop -> pick) must be acyclic.
    # The fixed point below only detects circuits of positive weight (no convergence); a circuit of
    # zero weight (sigma = 0 and no service time, as in the public sets) converges and would pass.
    succ: dict[tuple[int, int], list[tuple[int, int]]] = {}
    indeg: dict[tuple[int, int], int] = {}
    for ri, route in enumerate(sol.routes):
        for vi in range(len(route.visits)):
            indeg.setdefault((ri, vi), 0)
            if vi + 1 < len(route.visits):
                succ.setdefault((ri, vi), []).append((ri, vi + 1))
                indeg[(ri, vi + 1)] = indeg.get((ri, vi + 1), 0) + 1
    for d, p, tp, rid in sync:
        succ.setdefault(d, []).append(p)
        indeg[p] = indeg.get(p, 0) + 1
    order = [u for u, k in indeg.items() if k == 0]
    done = 0
    while order:
        u = order.pop()
        done += 1
        for w in succ.get(u, []):
            indeg[w] -= 1
            if indeg[w] == 0:
                order.append(w)
    if done != len(indeg):
        v.append("inconsistent plan: the event graph has a circuit (a vehicle waits, directly or through transfers, for a load it must itself deliver)")
        return _report(inst, sol, False, v, sched)

    # ---- 3b. schedule with synchronisation (fixed point over a DAG) -------
    # earliest pick start >= drop end (drop end already includes sigma*q handling)
    pick_lb: dict[tuple[int, int], float] = {}
    for _ in range(len(sync) + 2):
        changed = False
        for ri, route in enumerate(sol.routes):
            veh = inst.vehicles[route.vehicle]
            prev_node, t = veh.start_node, inst.nodes[veh.start_node].tw_start
            for vi, vis in enumerate(route.visits):
                node = inst.nodes[vis.node]
                arrival = t + inst.time(prev_node, vis.node)
                start = max(arrival, node.tw_start, pick_lb.get((ri, vi), 0.0))
                dur = node.service
                if vis.op in (DROP, PICK):
                    tp = inst.transfer_points[vis.transfer_point]
                    dur = tp.transfer_time_per_unit * inst.requests[vis.request].quantity
                end = start + dur
                old = sched.times.get((ri, vi))
                if old is None or abs(old[1] - start) > EPS:
                    changed = True
                sched.times[(ri, vi)] = (arrival, start, end)
                prev_node, t = vis.node, end
            # return to end depot
            sched.times[(ri, -1)] = (t + inst.time(prev_node, veh.end_node),) * 3
        for d, p, tp, rid in sync:
            lb = sched.times[d][2]
            if lb > pick_lb.get(p, 0.0) + EPS:
                pick_lb[p] = lb
                changed = True
        if not changed:
            break
    else:
        v.append("synchronisation graph has a cycle (no fixed point)")

    # ---- 4. time windows, storage time, precedence ----------------------
    for ri, route in enumerate(sol.routes):
        veh = inst.vehicles[route.vehicle]
        for vi, vis in enumerate(route.visits):
            node = inst.nodes[vis.node]
            _, start, _ = sched.times[(ri, vi)]
            if start > node.tw_end + EPS:
                v.append(f"vehicle {veh.id}: starts {vis.op} of {vis.request} at {start:.2f} > tw_end {node.tw_end}")
        ret = sched.times[(ri, -1)][0]
        if ret > inst.nodes[veh.end_node].tw_end + EPS:
            v.append(f"vehicle {veh.id}: returns at {ret:.2f} > depot tw_end")
    for d, p, tp, rid in sync:
        drop_end, pick_start = sched.times[d][2], sched.times[p][1]
        if pick_start < drop_end - EPS:
            v.append(f"request {rid}: picked at {tp} before it was dropped")
        W = inst.transfer_points[tp].max_storage_time
        if pick_start - drop_end > W + EPS:
            v.append(f"request {rid}: stored {pick_start - drop_end:.2f} > W={W} at {tp}")

    # ---- 5. resources at transfer points (sweep lines) ------------------
    for tpid, tp in inst.transfer_points.items():
        if tp.storage_capacity < INF:
            events = []
            for d, p, t_, rid in sync:
                if t_ != tpid:
                    continue
                q = inst.requests[rid].quantity
                events.append((sched.times[d][2], +q))
                events.append((sched.times[p][1], -q))
            events.sort(key=lambda e: (e[0], e[1]))   # removals before additions at ties
            stored = 0.0
            for t_, dq in events:
                stored += dq
                if stored > tp.storage_capacity + EPS:
                    v.append(f"transfer point {tpid}: storage {stored:.3f} > S={tp.storage_capacity} at t={t_:.2f}")
                    break
        if tp.handling_slots < INF:
            events = []
            for ri, route in enumerate(sol.routes):
                for vi, vis in enumerate(route.visits):
                    if vis.op in (DROP, PICK) and vis.transfer_point == tpid:
                        _, s, e = sched.times[(ri, vi)]
                        if e > s:
                            events.append((s, +1))
                            events.append((e, -1))
            events.sort(key=lambda e: (e[0], e[1]))
            busy = 0
            for t_, d in events:
                busy += d
                if busy > tp.handling_slots:
                    v.append(f"transfer point {tpid}: {busy} simultaneous operations > H={tp.handling_slots} at t={t_:.2f}")
                    break

    return _report(inst, sol, not v, v, sched)


def _report(inst: Instance, sol: Solution, feasible: bool, v: list[str], sched: Schedule) -> Report:
    used, dist, tcost, hcost, emis, ntr = 0, 0.0, 0.0, 0.0, 0.0, 0
    for route in sol.routes:
        if not route.visits or route.vehicle not in inst.vehicles:
            continue
        veh = inst.vehicles[route.vehicle]
        used += 1
        tcost += veh.fixed_cost
        prev = veh.start_node
        for vis in route.visits:
            d = inst.dist(prev, vis.node)
            dist += d
            tcost += veh.cost_per_km * d
            emis += veh.emission_per_km * d
            if vis.op == DROP:
                ntr += 1
                tp = inst.transfer_points.get(vis.transfer_point)
                if tp and vis.request in inst.requests:
                    hcost += tp.handling_cost * inst.requests[vis.request].quantity
            prev = vis.node
        d = inst.dist(prev, veh.end_node)
        dist += d
        tcost += veh.cost_per_km * d
        emis += veh.emission_per_km * d
    tcost += inst.params.cost_constant
    if inst.params.single_visit_per_point:
        for rt in sol.routes:
            if not single_visit_ok(rt.visits):
                v.append(f"vehicle {rt.vehicle} visits a transfer point more than once (single-visit convention)")
                feasible = False
    if used < inst.params.min_vehicles_used and len(inst.requests) >= inst.params.min_vehicles_used:
        v.append(f"fleet: only {used} vehicles used, instance requires at least {inst.params.min_vehicles_used}")
        feasible = False
    return Report(feasible, v, used, dist, tcost, hcost, emis, ntr, sched)
