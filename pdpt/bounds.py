# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Lower bounds for the PDPTW-CT that scale beyond the full MILP.

Bound A — vehicle-count bound.  Minimum number of vehicles needed, from a
*conflict graph*: two requests conflict when no single vehicle can serve both
in either order within time windows and capacity.  Any feasible plan without
transfers needs at least the clique-cover number; with transfers a request may
be split, so we use the weaker but valid bound: the maximum clique among
requests whose *pickups* pairwise conflict (a pickup is served by exactly one
vehicle whatever the transfers).  Max clique is solved exactly by MILP (HiGHS).

Bound B — cost bound by assignment relaxation.  Each request is served either
directly (cost of the cheapest insertion skeleton: a vehicle doing depot ->
p -> d -> depot divided over the requests it could share with) or through a
transfer point.  We relax routing to a lower bound on marginal cost: for every
request r, LB_r = min over admissible chains of the *shortest connecting arcs*
that any route must contain to visit the chain, i.e. the cheapest incoming arc
to p_r plus the cheapest arc out of d_r (or through t), each counted once per
visited vertex, from the standard "half of the two cheapest incident arcs"
argument.  Summed with the vehicle fixed costs of Bound A this gives a
certified lower bound on total cost; it is loose but valid for any n.

Bound C — LP relaxation of the full three-index model (milp.py) with the
integrality dropped; tighter than B for n <= 30 and solved in seconds.

All bounds are stated for the weighted or lexicographic objective in the same
cost units as the verifier.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import highspy

from .instance import Instance, INF


# --------------------------------------------------------------------------- conflicts
def _can_chain(inst: Instance, veh, r1, r2) -> bool:
    """Can one vehicle serve r1 then r2 (p1 d1 p2 d2 or p1 p2 d1 d2 or p1 p2 d2 d1) within windows & capacity?"""
    nodes = inst.nodes
    orders = [
        [r1.pickup, r1.delivery, r2.pickup, r2.delivery],
        [r1.pickup, r2.pickup, r1.delivery, r2.delivery],
        [r1.pickup, r2.pickup, r2.delivery, r1.delivery],
    ]
    q = {r1.pickup: r1.quantity, r1.delivery: -r1.quantity, r2.pickup: r2.quantity, r2.delivery: -r2.quantity}
    for seq in orders:
        t = nodes[veh.start_node].tw_start
        prev = veh.start_node
        load = 0.0
        ok = True
        for v in seq:
            t = max(t + inst.time(prev, v), nodes[v].tw_start)
            if t > nodes[v].tw_end + 1e-9:
                ok = False
                break
            load += q[v]
            if load > veh.capacity + 1e-9:
                ok = False
                break
            t += nodes[v].service
            prev = v
        if ok and t + inst.time(prev, veh.end_node) <= nodes[veh.end_node].tw_end + 1e-9:
            return True
    return False


def pickup_conflict_graph(inst: Instance) -> dict[str, set[str]]:
    """r1 ~ r2 iff no vehicle can perform pickup r1 and pickup r2 in one route (either order),
    even ignoring the deliveries.  Pickups are never split by transfers, so a clique of this
    graph forces as many vehicles as its size."""
    R = list(inst.requests.values())
    nodes = inst.nodes
    adj = {r.id: set() for r in R}
    for i in range(len(R)):
        for j in range(i + 1, len(R)):
            a, b = R[i], R[j]
            feasible = False
            for veh in inst.vehicles.values():
                if not (inst.vehicle_allows(veh, a.load_type) and inst.vehicle_allows(veh, b.load_type)):
                    continue
                if a.quantity + b.quantity > veh.capacity + 1e-9 and True:
                    # the two pickups could still be in one route if a is delivered before b is picked;
                    # only the pickups' time windows matter for the conflict, so skip capacity here
                    pass
                for x, y in ((a, b), (b, a)):
                    t = nodes[veh.start_node].tw_start + inst.time(veh.start_node, x.pickup)
                    t = max(t, nodes[x.pickup].tw_start)
                    if t > nodes[x.pickup].tw_end + 1e-9:
                        continue
                    t += nodes[x.pickup].service + inst.time(x.pickup, y.pickup)
                    t = max(t, nodes[y.pickup].tw_start)
                    if t <= nodes[y.pickup].tw_end + 1e-9:
                        feasible = True
                        break
                if feasible:
                    break
            if not feasible:
                adj[a.id].add(b.id)
                adj[b.id].add(a.id)
    return adj


def max_clique(adj: dict[str, set[str]], time_limit: float = 30.0) -> list[str]:
    ids = list(adj)
    if not ids:
        return []
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", time_limit)
    idx = {v: i for i, v in enumerate(ids)}
    for v in ids:
        h.addVar(0, 1)
        h.changeColCost(idx[v], -1.0)
        h.changeColIntegrality(idx[v], highspy.HighsVarType.kInteger)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if ids[j] not in adj[ids[i]]:
                h.addRow(-INF, 1, 2, [i, j], [1.0, 1.0])
    h.run()
    x = h.getSolution().col_value
    return [v for v in ids if x[idx[v]] > 0.5]


# --------------------------------------------------------------------------- Bound B
def arc_cost_bound(inst: Instance) -> float:
    """Valid lower bound on total transport cost of any feasible plan (any number of transfers).

    Every customer vertex is entered once and left once by some vehicle.  With c_min the
    cheapest per-km cost over vehicles allowed for the request, the arcs incident to vertex v
    contribute at least (min_in(v) + min_out(v)) / 2 to the total, where min_in/min_out range
    over all other vertices (customers, depots, transfer points).  Transfer vertices add
    non-negative cost, so omitting them keeps the bound valid.  Plus fixed costs of the
    minimum fleet (Bound A) when fixed costs are uniform.
    """
    V = set()
    for r in inst.requests.values():
        V.add(r.pickup); V.add(r.delivery)
    others = set(V)
    for v in inst.vehicles.values():
        others.add(v.start_node); others.add(v.end_node)
    for t in inst.transfer_points.values():
        others.add(t.node)
    total = 0.0
    for r in inst.requests.values():
        cmin = min(v.cost_per_km for v in inst.vehicles.values() if inst.vehicle_allows(v, r.load_type))
        for node in (r.pickup, r.delivery):
            cands = [inst.dist(node, o) for o in others if o != node and inst.dist(node, o) > 0] or [0.0]
            cands_in = [inst.dist(o, node) for o in others if o != node and inst.dist(o, node) > 0] or [0.0]
            total += cmin * (min(cands) + min(cands_in)) / 2.0
    return total


@dataclass
class BoundReport:
    min_vehicles: int
    clique: list[str]
    cost_lb: float
    fixed_lb: float
    total_lb: float


def lower_bound(inst: Instance, time_limit: float = 30.0) -> BoundReport:
    adj = pickup_conflict_graph(inst)
    clique = max_clique(adj, time_limit)
    k = max(1, len(clique))
    # fixed costs: the k cheapest fixed costs among vehicles (valid since at least k are used)
    fixed = sorted(v.fixed_cost for v in inst.vehicles.values())[:k]
    fixed_lb = sum(fixed)
    cost_lb = arc_cost_bound(inst)
    return BoundReport(k, clique, cost_lb, fixed_lb, cost_lb + fixed_lb)
