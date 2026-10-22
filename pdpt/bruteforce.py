# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Exhaustive solver for tiny PDPTW-CT instances (reference optima for tests).

Enumerates, for each request, a custody plan (direct by vehicle k, or drop by k
at t and pick by k' ≠ k), then every interleaving of operations on each vehicle
consistent with the per-request precedence (pickup < drop, pick < delivery,
pickup < delivery), evaluates with the independent verifier and keeps the best
by the instance objective.  Exponential; intended for n ≤ 4 requests.
"""
from __future__ import annotations

import itertools

from .instance import Instance
from .solution import Solution, Route, Visit, PICKUP, DELIVERY, DROP, PICK
from .verifier import verify, Report


def _route_orders(ops: list[tuple]) -> list[list[tuple]]:
    """All orderings of ops (op, rid, node, tp) respecting per-request precedence."""
    rank = {PICKUP: 0, DROP: 1, PICK: 2, DELIVERY: 3}
    out = []
    for perm in itertools.permutations(ops):
        seen: dict[str, int] = {}
        ok = True
        for op, rid, _, _ in perm:
            if seen.get(rid, -1) >= rank[op]:
                ok = False
                break
            seen[rid] = rank[op]
        if ok:
            out.append(list(perm))
    return out


def solve(inst: Instance, max_vehicles: int | None = None) -> tuple[Solution | None, Report | None]:
    reqs = list(inst.requests.values())
    vehs = list(inst.vehicles)
    if max_vehicles:
        vehs = vehs[:max_vehicles]
    tps = list(inst.transfer_points.values())
    kappa = inst.params.max_transfers_per_request

    # custody options per request
    options = []
    for r in reqs:
        opts = [("direct", k) for k in vehs]
        if kappa >= 1:
            for t in tps:
                for k in vehs:
                    for k2 in vehs:
                        if k2 != k:
                            opts.append(("transfer", k, k2, t))
        options.append(opts)

    best, best_rep, best_key = None, None, None
    for choice in itertools.product(*options):
        ops: dict[str, list[tuple]] = {k: [] for k in vehs}
        for r, c in zip(reqs, choice):
            if c[0] == "direct":
                ops[c[1]] += [(PICKUP, r.id, r.pickup, None), (DELIVERY, r.id, r.delivery, None)]
            else:
                _, k, k2, t = c
                ops[k] += [(PICKUP, r.id, r.pickup, None), (DROP, r.id, t.node, t.id)]
                ops[k2] += [(PICK, r.id, t.node, t.id), (DELIVERY, r.id, r.delivery, None)]
        per_vehicle = [_route_orders(ops[k]) for k in vehs]
        for combo in itertools.product(*per_vehicle):
            sol = Solution(inst.name, routes=[
                Route(k, [Visit(node, op, rid, tp) for op, rid, node, tp in order])
                for k, order in zip(vehs, combo) if order])
            rep = verify(inst, sol)
            if not rep.feasible:
                continue
            key = rep.objective(inst)
            if best_key is None or key < best_key:
                best, best_rep, best_key = sol, rep, key
    return best, best_rep
