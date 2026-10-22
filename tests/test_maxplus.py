# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
import copy
import math

import pytest

from pdpt import verify, Solution, Route, Visit, INF, PICKUP, DELIVERY, DROP, PICK
from pdpt.examples import thesis_fig32, thesis_fig32_solution_with_transfer
from pdpt.maxplus import MaxPlusPlan, NEG


def test_schedule_matches_verifier():
    inst = thesis_fig32()
    sol = thesis_fig32_solution_with_transfer()
    rep = verify(inst, sol)
    mp = MaxPlusPlan(inst, sol)
    for (ri, vi), (arr, start, end) in rep.schedule.times.items():
        if vi == -1:                       # verifier's return-to-depot key
            assert mp.start(ri, -2) == pytest.approx(arr)
        else:
            assert mp.start(ri, vi) == pytest.approx(start)
    ok, late = mp.feasible()
    assert ok and rep.feasible


def test_schedule_matches_verifier_with_handling_and_waiting():
    inst = thesis_fig32()
    tp = inst.transfer_points["t"]
    tp.transfer_time_per_unit = 0.4
    for n in "456":
        inst.nodes[n].tw_end = INF
    sol = thesis_fig32_solution_with_transfer()
    rep = verify(inst, sol)
    mp = MaxPlusPlan(inst, sol)
    assert rep.feasible
    for (ri, vi), (arr, start, end) in rep.schedule.times.items():
        if vi != -1:
            assert mp.start(ri, vi) == pytest.approx(start)
    # the pick on k3 waits for k1's drop (1.0) + handling 0.4 -> starts at 1.4, not 1.0
    assert mp.start(1, 1) == pytest.approx(1.4)
    d, p, slack = mp.transfer_slacks()[0]
    assert slack == pytest.approx(0.0)      # synchronisation is binding


def test_star_is_longest_path_and_propagation_is_linear():
    inst = thesis_fig32()
    for n in "456":
        inst.nodes[n].tw_end = INF
    sol = thesis_fig32_solution_with_transfer()
    mp = MaxPlusPlan(inst, sol)
    S = mp.star()
    k1_pick2 = mp.g.key[(0, 0)]          # k1 at node 2
    k3_del4 = mp.g.key[(1, 3)]           # k3 delivers r1 at node 4 (last)
    # path k1: 2 ->3 (0) -> t (1) --sync--> k3 pick (0) -> 5 (1) -> 4 (0)  => 2
    assert S[k1_pick2][k3_del4] == pytest.approx(2.0)
    # a delay of 0.7 at k1's first visit shifts k3's last delivery from 2.0 to 2.7
    x2 = mp.propagate(k1_pick2, 0.7)
    assert x2[k3_del4] == pytest.approx(2.7)
    # but k3's own pickup at node 1 (no path from k1) is untouched
    k3_pick1 = mp.g.key[(1, 0)]
    assert S[k1_pick2][k3_pick1] == NEG
    assert x2[k3_pick1] == pytest.approx(mp.x[k3_pick1])


def test_margin_names_the_deadline_that_breaks_first():
    inst = thesis_fig32()
    sol = thesis_fig32_solution_with_transfer()
    mp = MaxPlusPlan(inst, sol)
    k1_pick2 = mp.g.key[(0, 0)]
    m, e = mp.margin(k1_pick2)
    # downstream deadlines: node 6 at 2 (reached at 2), nodes 5/4 at 3 (reached at 2)
    assert m == pytest.approx(0.0, abs=1e-6)
    assert mp.g.events[e].node in ("2", "6")     # its own tight window, or node 6 reached at 2
    # relax the tight windows upstream: the binding deadline becomes 5 or 4 through the transfer, margin 1
    for n in ("2", "3", "6"):
        inst.nodes[n].tw_end = INF
    mp2 = MaxPlusPlan(inst, sol)
    m2, e2 = mp2.margin(k1_pick2)
    assert m2 == pytest.approx(1.0)
    assert mp2.g.events[e2].node in ("4", "5")
    # a delay above the margin is detected by propagate + deadlines, consistent with the verifier
    x = mp2.propagate(k1_pick2, 1.2)
    late = [i for i, ev in enumerate(mp2.g.events) if x[i] > ev.deadline + 1e-9]
    assert late


def test_circuit_detected():
    inst = thesis_fig32()
    # k1 drops r2 at t then picks r3 at t; k3 drops r3 at t then picks r2 at t: each waits for the other.
    sol = Solution("thesis_fig32", routes=[
        Route("k1", [Visit("2", PICKUP, "r2"), Visit("t", PICK, "r3", "t"),
                     Visit("t", DROP, "r2", "t"), Visit("6", DELIVERY, "r3")]),
        Route("k3", [Visit("3", PICKUP, "r3"), Visit("t", PICK, "r2", "t"),
                     Visit("t", DROP, "r3", "t"), Visit("5", DELIVERY, "r2"),
                     Visit("1", PICKUP, "r1"), Visit("4", DELIVERY, "r1")]),
    ])
    with pytest.raises(ValueError, match="circuit"):
        MaxPlusPlan(inst, sol)
