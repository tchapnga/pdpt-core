# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
import copy
import math

import pytest

from pdpt import (Instance, Solution, Route, Visit, verify, INF,
                  PICKUP, DELIVERY, DROP, PICK)
from pdpt.examples import (thesis_fig32, thesis_fig32_solution_without_transfer,
                           thesis_fig32_solution_with_transfer)


@pytest.fixture
def inst():
    return thesis_fig32()


def test_round_trip_json(inst, tmp_path):
    p = tmp_path / "i.json"
    inst.save(p)
    back = Instance.load(p)
    assert back.to_dict() == inst.to_dict()
    assert back.vehicles["k1"].capacity == INF


def test_without_transfer_optimum(inst):
    rep = verify(inst, thesis_fig32_solution_without_transfer())
    assert rep.feasible, rep.violations
    assert rep.vehicles_used == 3
    assert rep.distance == pytest.approx(4 + math.sqrt(2))
    assert rep.transfers == 0


def test_with_transfer_optimum(inst):
    rep = verify(inst, thesis_fig32_solution_with_transfer())
    assert rep.feasible, rep.violations
    assert rep.vehicles_used == 2
    assert rep.distance == pytest.approx(4.0)
    assert rep.transfers == 1
    assert rep.objective(inst) < verify(inst, thesis_fig32_solution_without_transfer()).objective(inst)


def test_pick_before_drop_is_infeasible(inst):
    # k3 arrives at t at time 1; make k1 slower to reach t by sending it to 6 first.
    sol = Solution("thesis_fig32", routes=[
        Route("k1", [Visit("2", PICKUP, "r2"), Visit("3", PICKUP, "r3"),
                     Visit("6", DELIVERY, "r3"), Visit("t", DROP, "r2", "t")]),
        Route("k3", [Visit("1", PICKUP, "r1"), Visit("t", PICK, "r2", "t"),
                     Visit("5", DELIVERY, "r2"), Visit("4", DELIVERY, "r1")]),
    ])
    rep = verify(inst, sol)
    # synchronisation forces k3 to wait at t until k1 drops (time 3), then 5 at 4 > tw_end 3
    assert not rep.feasible
    assert any("tw_end" in v for v in rep.violations)
    t_pick = rep.schedule.times[(1, 1)][1]
    t_drop_end = rep.schedule.times[(0, 3)][2]
    assert t_pick >= t_drop_end - 1e-9


def test_same_vehicle_drop_and_pick_rejected(inst):
    sol = Solution("thesis_fig32", routes=[
        Route("k1", [Visit("2", PICKUP, "r2"), Visit("t", DROP, "r2", "t"),
                     Visit("t", PICK, "r2", "t"), Visit("5", DELIVERY, "r2")]),
        Route("k2", [Visit("3", PICKUP, "r3"), Visit("6", DELIVERY, "r3")]),
        Route("k3", [Visit("1", PICKUP, "r1"), Visit("4", DELIVERY, "r1")]),
    ])
    rep = verify(inst, sol)
    assert not rep.feasible
    assert any("another vehicle" in v for v in rep.violations)


def test_kappa_zero_forbids_transfer(inst):
    i2 = copy.deepcopy(inst)
    i2.params.max_transfers_per_request = 0
    rep = verify(i2, thesis_fig32_solution_with_transfer())
    assert not rep.feasible and any("kappa" in v for v in rep.violations)


def test_capacity_and_compatibility(inst):
    i2 = copy.deepcopy(inst)
    i2.vehicles["k1"].capacity = 1.0           # k1 carries r2 and r3 together -> load 2
    rep = verify(i2, thesis_fig32_solution_with_transfer())
    assert not rep.feasible and any("capacity" in v for v in rep.violations)
    i3 = copy.deepcopy(inst)
    i3.requests["r1"].load_type = "reefer"
    i3.vehicles["k3"].allowed_types = ["default"]
    rep = verify(i3, thesis_fig32_solution_with_transfer())
    assert not rep.feasible and any("cannot carry" in v for v in rep.violations)


def test_handling_slots_and_storage(inst):
    # Two transfers at t with 1 handling slot and non-zero transfer time must not overlap.
    i2 = copy.deepcopy(inst)
    i2.transfer_points["t"].handling_slots = 1
    i2.transfer_points["t"].transfer_time_per_unit = 0.5
    i2.transfer_points["t"].storage_capacity = 1.0
    i2.nodes["6"].tw_end = INF
    i2.nodes["4"].tw_end = INF
    i2.nodes["5"].tw_end = INF
    # k1 drops r2 [1,1.5] and r3 [1.5,2] at t.  k3 delivers r1 first, reaches t at 3 and
    # picks r2 [3,3.5] then r3 [3.5,4]: no handling overlap, but r2 and r3 are both stored
    # during [2,3] -> 2 units > S=1 -> storage violation only.
    sol = Solution("thesis_fig32", routes=[
        Route("k1", [Visit("2", PICKUP, "r2"), Visit("3", PICKUP, "r3"),
                     Visit("t", DROP, "r2", "t"), Visit("t", DROP, "r3", "t")]),
        Route("k3", [Visit("1", PICKUP, "r1"), Visit("4", DELIVERY, "r1"),
                     Visit("t", PICK, "r2", "t"), Visit("t", PICK, "r3", "t"),
                     Visit("5", DELIVERY, "r2"), Visit("6", DELIVERY, "r3")]),
    ])
    rep = verify(i2, sol)
    assert not rep.feasible
    assert any("storage" in v for v in rep.violations)
    assert not any("simultaneous operations" in v for v in rep.violations)
    # Picking r2 while k1 is still dropping r3 overlaps two operations on one slot.
    sol_overlap = Solution("thesis_fig32", routes=[
        Route("k1", [Visit("2", PICKUP, "r2"), Visit("3", PICKUP, "r3"),
                     Visit("t", DROP, "r2", "t"), Visit("t", DROP, "r3", "t")]),
        Route("k3", [Visit("1", PICKUP, "r1"), Visit("t", PICK, "r2", "t"), Visit("t", PICK, "r3", "t"),
                     Visit("5", DELIVERY, "r2"), Visit("4", DELIVERY, "r1"), Visit("6", DELIVERY, "r3")]),
    ])
    assert any("simultaneous operations" in v for v in verify(i2, sol_overlap).violations)
    i2.transfer_points["t"].storage_capacity = INF
    rep = verify(i2, sol)
    assert rep.feasible, rep.violations
    assert rep.handling_cost == 0.0
    i2.transfer_points["t"].handling_cost = 2.5
    assert verify(i2, sol).handling_cost == pytest.approx(5.0)
