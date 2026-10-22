# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Regression: the LNS must reach the known optima of the 2014 thesis instances."""
import pytest

from pdpt.thesis2014 import instance, all_instances, OPT_WITH_TRANSFER_DIST, KNOWN_OPTIMA
from pdpt.lns import solve
from pdpt.bruteforce import solve as exact
from pdpt.verifier import verify


@pytest.mark.parametrize("name", ["E1", "E2", "E3", "E7", "E10", "E16"])
def test_lns_reaches_optimum_with_transfer(name):
    inst = instance(name, fleet_size=4, allow_transfer=True)
    r = solve(inst, time_limit=20, max_iter=300, seed=3)
    assert r.report.vehicles_used == 2
    assert r.report.distance == pytest.approx(OPT_WITH_TRANSFER_DIST, abs=1e-2)
    assert verify(inst, r.solution).feasible


@pytest.mark.parametrize("name,dist", [("E1", 1585.24), ("E3", 1546.62), ("E5", 1300.37), ("E9", 1314.85)])
def test_lns_matches_exact_without_transfer(name, dist):
    inst = instance(name, fleet_size=3, allow_transfer=False)
    _, rep = exact(inst)
    assert rep.distance == pytest.approx(dist, abs=1e-2)
    r = solve(inst, time_limit=10, max_iter=200, seed=0)
    assert r.report.vehicles_used == rep.vehicles_used
    assert r.report.distance == pytest.approx(rep.distance, abs=1e-6)


def test_all_thesis_instances_load_and_validate():
    insts = all_instances()
    assert len(insts) == 16
    assert [len(i.requests) for i in insts] == [3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6, 7, 7, 7, 8]
    assert all(i.name.split("-")[1] in KNOWN_OPTIMA for i in insts)


def test_storage_time_limit_respected_on_port_instance():
    from pdpt.portgen import generate
    inst = generate(20, seed=0, n_yards=2, H=1, S=1, W=60.0)
    r = solve(inst, time_limit=15, max_iter=200, seed=0)   # asserts feasibility internally
    assert verify(inst, r.solution).feasible


def test_storage_capacity_respected_on_port_instance():
    from pdpt.portgen import generate
    inst = generate(20, seed=0, n_yards=2, H=1, S=2)
    r = solve(inst, time_limit=20, max_iter=300, seed=0)
    assert verify(inst, r.solution).feasible


def test_warm_start_is_never_worse():
    from pdpt.portgen import generate
    base = generate(20, seed=2, n_yards=0)
    r0 = solve(base, time_limit=8, max_iter=300, seed=2)
    with_yards = generate(20, seed=2, n_yards=2, H=1, S=1, W=60.0)
    r1 = solve(with_yards, time_limit=8, max_iter=300, seed=2, warm_start=r0.solution)
    assert r1.report.feasible
    assert r1.key <= (0, r0.report.objective(base) + 1e-6) or r1.report.objective(with_yards) <= r0.report.objective(base) + 1e-6
