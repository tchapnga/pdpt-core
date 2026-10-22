# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Quick start: generate a drayage day with two relay yards, solve it, verify the plan.

Run from the repository root after `pip install -e .`:  python examples/quickstart.py
"""
from pdpt.portgen import generate
from pdpt.lns import solve
from pdpt.verifier import verify

# 20 containers, two relay yards with one handling bay and two storage slots each
inst = generate(20, seed=0, S=2, H=1)

result = solve(inst, time_limit=20, seed=0)
report = verify(inst, result.solution)

print("feasible:", report.feasible)
print("trucks used:", report.vehicles_used)
print("distance:", round(report.distance, 1))
print("cost vector:", report.objective(inst))
result.solution.save("quickstart_solution.json")
print("plan written to quickstart_solution.json")
