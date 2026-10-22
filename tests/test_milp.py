# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
import pytest

from pdpt.examples import thesis_fig32
from pdpt.thesis2014 import instance, OPT_WITH_TRANSFER_DIST
from pdpt.milp import solve


def test_milp_fig32_optimum():
    r = solve(thesis_fig32(), time_limit=60)
    assert r.status == "Optimal"
    assert r.report.feasible
    assert r.report.vehicles_used == 2 and r.report.distance == pytest.approx(4.0)


def test_milp_E1_certifies_known_optimum():
    r = solve(instance("E1", fleet_size=3), time_limit=120)
    assert r.status == "Optimal"
    assert r.report.feasible
    assert r.report.vehicles_used == 2
    assert r.report.distance == pytest.approx(OPT_WITH_TRANSFER_DIST, abs=1e-2)
    assert r.gap == pytest.approx(0.0, abs=1e-6)


def test_milp_without_transfer_points():
    inst = instance("E1", fleet_size=3, allow_transfer=False)
    r = solve(inst, time_limit=60)
    assert r.status == "Optimal"
    assert r.report.vehicles_used == 3 and r.report.distance == pytest.approx(1585.24, abs=1e-2)
