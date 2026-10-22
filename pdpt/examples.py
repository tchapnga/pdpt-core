# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Small hand-built instances with known optima, used as regression tests.

`thesis_fig32` reproduces the example of Mitrović-Minić & Laporte (2006)
reused in Tchapnga Takoudjou (2014), figure 3.2: three requests, a transfer
point at the origin; without transfer 3 vehicles and distance 4 + sqrt(2),
with transfer 2 vehicles and distance 4.
"""
from __future__ import annotations

import math

from .instance import Instance, Node, Request, TransferPoint, Vehicle, Params, INF
from .solution import Solution, Route, Visit, PICKUP, DELIVERY, DROP, PICK


def thesis_fig32() -> Instance:
    # Geometry: requests (1,4), (2,5), (3,6).  2 and 3 share a location, 4 and 5 too.
    # Vehicle k1 starts at node 2, k2 at node 3, k3 at node 1; all end anywhere (free end
    # modelled by a dedicated end node at the last stop, cost 0 via tw).  To keep the example
    # exact we give each vehicle its own end node co-located with its last planned stop.
    s2 = math.sqrt(2) / 2
    nodes = {
        "1": Node("1", -1.0, 0.0, 0.0, 1.0 + 1e-9),      # pickup of r1, tight window
        "2": Node("2", 0.0, 1.0, 0.0, 0.0 + 1e-9),       # pickup of r2
        "3": Node("3", 0.0, 1.0, 0.0, 0.0 + 1e-9),       # pickup of r3 (same place as 2)
        "4": Node("4", 1.0, 0.0, 0.0, 3.0),              # delivery of r1
        "5": Node("5", 1.0, 0.0, 0.0, 3.0),              # delivery of r2
        "6": Node("6", 0.0, -1.0, 0.0, 2.0 + 1e-9),      # delivery of r3
        "t": Node("t", 0.0, 0.0, 0.0, INF),              # transfer point
        "e": Node("e", 0.0, 0.0, 0.0, INF),              # dummy free end (see below)
    }
    requests = {
        "r1": Request("r1", "1", "4", 1.0),
        "r2": Request("r2", "2", "5", 1.0),
        "r3": Request("r3", "3", "6", 1.0),
    }
    tps = {"t": TransferPoint("t", "t")}
    # Free end: each vehicle ends where it stops; we emulate this with a matrix where
    # the distance to "e" is 0 from every node.  Hence travel="matrix".
    ids = list(nodes)
    dist = {i: {j: (0.0 if j == "e" else math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y))
                for j in ids} for i in ids}
    vehicles = {
        "k1": Vehicle("k1", INF, "2", "e"),
        "k2": Vehicle("k2", INF, "3", "e"),
        "k3": Vehicle("k3", INF, "1", "e"),
    }
    return Instance(name="thesis_fig32", nodes=nodes, requests=requests, transfer_points=tps,
                    vehicles=vehicles, params=Params(speed=1.0), travel="matrix",
                    dist_matrix=dist, time_matrix=dist,
                    meta={"source": "Mitrović-Minić & Laporte 2006; Tchapnga 2014 fig. 3.2",
                          "optimum_without_transfer": {"vehicles": 3, "distance": 4 + math.sqrt(2)},
                          "optimum_with_transfer": {"vehicles": 2, "distance": 4.0}})


def thesis_fig32_solution_without_transfer() -> Solution:
    return Solution("thesis_fig32", routes=[
        Route("k1", [Visit("2", PICKUP, "r2"), Visit("5", DELIVERY, "r2")]),
        Route("k2", [Visit("3", PICKUP, "r3"), Visit("6", DELIVERY, "r3")]),
        Route("k3", [Visit("1", PICKUP, "r1"), Visit("4", DELIVERY, "r1")]),
    ])


def thesis_fig32_solution_with_transfer() -> Solution:
    return Solution("thesis_fig32", routes=[
        Route("k1", [Visit("2", PICKUP, "r2"), Visit("3", PICKUP, "r3"),
                     Visit("t", DROP, "r2", "t"), Visit("6", DELIVERY, "r3")]),
        Route("k3", [Visit("1", PICKUP, "r1"), Visit("t", PICK, "r2", "t"),
                     Visit("5", DELIVERY, "r2"), Visit("4", DELIVERY, "r1")]),
    ])
