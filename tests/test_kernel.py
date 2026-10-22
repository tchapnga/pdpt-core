# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""The compiled insertion scan must agree with the reference Python test on random states."""
import random

import pytest

from pdpt import Visit, PICKUP, DELIVERY, DROP, PICK
from pdpt.portgen import generate
from pdpt.lns import solve, Plan, scan_route
from pdpt.incremental import State


def _states():
    for seed in range(3):
        inst = generate(16, seed=seed, n_yards=2, H=1, S=2, W=90.0)
        r = solve(inst, time_limit=4, max_iter=60, seed=seed)
        routes = {k: [] for k in inst.vehicles}
        for rt in r.solution.routes:
            routes[rt.vehicle] = list(rt.visits)
        # take two requests out to have something to insert
        rng = random.Random(seed)
        rids = rng.sample(list(inst.requests), 2)
        for rid in rids:
            for k in routes:
                routes[k] = [v for v in routes[k] if v.request != rid]
        yield inst, State.build(inst, routes), rids


@pytest.mark.parametrize("extra", [False, True])
def test_kernel_matches_python(extra):
    checked = 0
    for inst, st, rids in _states():
        t = next(iter(inst.transfer_points.values()))
        for rid in rids:
            req = inst.requests[rid]
            chains = [(Visit(req.pickup, PICKUP, rid), Visit(req.delivery, DELIVERY, rid), float("-inf")),
                      (Visit(req.pickup, PICKUP, rid), Visit(t.node, DROP, rid, t.id), float("-inf"))]
            if extra:
                chains.append((Visit(t.node, PICK, rid, t.id), Visit(req.delivery, DELIVERY, rid), 300.0))
            for first, second, er in chains:
                for k in inst.vehicles:
                    ref = scan_route(inst, st, k, first, second, extra_release=er, use_kernel=False)
                    ker = scan_route(inst, st, k, first, second, extra_release=er, use_kernel=True)
                    ref_set = {(i, j): (round(d, 6), round(x, 6)) for i, j, d, x in ref}
                    ker_set = {(i, j): (round(d, 6), round(x, 6)) for i, j, d, x in ker}
                    assert ref_set == ker_set, (k, first.op, second.op, ref_set ^ ker_set if False else (ref_set, ker_set))
                    checked += len(ref)
    assert checked > 50
