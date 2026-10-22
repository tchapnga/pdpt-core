# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
from pdpt import verify, Solution, Route, Visit, PICKUP, DELIVERY, DROP, PICK
from pdpt.converters import li_lim, add_transfer_points

SAMPLE = """2 10 1
0 0 0 0 0 100 0 0 0
1 2 0 5 0 50 1 0 2
2 4 0 -5 0 60 1 1 0
3 0 3 4 0 50 1 0 4
4 0 6 -4 0 70 1 3 0
"""


def test_li_lim_round_trip(tmp_path):
    p = tmp_path / "lc_sample.txt"
    p.write_text(SAMPLE)
    inst = li_lim(p)
    assert set(inst.requests) == {"r1", "r3"}
    assert inst.requests["r1"].delivery == "2"
    assert len(inst.vehicles) == 2 and inst.vehicles["v0"].capacity == 10
    assert not inst.transfer_points
    sol = Solution(inst.name, routes=[
        Route("v0", [Visit("1", PICKUP, "r1"), Visit("2", DELIVERY, "r1")]),
        Route("v1", [Visit("3", PICKUP, "r3"), Visit("4", DELIVERY, "r3")]),
    ])
    rep = verify(inst, sol)
    assert rep.feasible, rep.violations
    assert rep.vehicles_used == 2 and rep.distance == 8 + 12


def test_add_transfer_points_makes_transfer_feasible(tmp_path):
    p = tmp_path / "lc_sample.txt"
    p.write_text(SAMPLE)
    inst = add_transfer_points(li_lim(p), [("hub", 2.0, 3.0)], handling_cost=1.0)
    sol = Solution(inst.name, routes=[
        Route("v0", [Visit("1", PICKUP, "r1"), Visit("tp_hub", DROP, "r1", "hub"),
                     Visit("3", PICKUP, "r3"), Visit("4", DELIVERY, "r3")]),
        Route("v1", [Visit("tp_hub", PICK, "r1", "hub"), Visit("2", DELIVERY, "r1")]),
    ])
    rep = verify(inst, sol)
    assert rep.feasible, rep.violations
    assert rep.transfers == 1 and rep.handling_cost == 5.0


def test_lyu_yu_conventions_reproduce_published_optima():
    """Deadhead + single-visit conventions: the LNS must hit the published PDP-T optima exactly."""
    import os, pytest
    from pdpt.converters import lyu_yu
    from pdpt.lns import solve
    base = "reproducibility/ext/lyuyu/PDP-T"
    if not os.path.isdir(base):
        pytest.skip("Lyu & Yu archive not extracted (reproducibility/ext_archives -> reproducibility/ext/lyuyu)")
    for f, pub in [("PDPT-R5-K3-T3/PDPT-R5-K3-T3-Q100-0.txt", 352.84),
                   ("PDPT-R10-K2-T1/PDPT-R10-K2-T1-Q100-0.txt", 649.36)]:
        inst = lyu_yu(f"{base}/{f}")
        assert inst.params.cost_constant > 0 and all(v.fixed_cost < 0 for v in inst.vehicles.values())
        rep = verify(inst, solve(inst, time_limit=20, max_iter=10**6, seed=0).solution)
        assert rep.feasible and abs(rep.cost - pub) < 0.01, (inst.name, rep.cost, pub)
