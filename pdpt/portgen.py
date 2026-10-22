# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""PORT generator: container drayage around a terminal with capacitated relay yards.

Units: km and minutes (speed 40 km/h in the metropolitan area).  Geometry:
terminal at the origin; customers in an annulus of radius r_min..r_max,
clustered in `n_zones` directions (industrial zones); relay yards at 3–8 km
from the terminal on the main approaches; one or two empty-container depots.

Requests (one container each):
  * import  : terminal -> customer, pickup window = terminal appointment slot
  * export  : customer -> terminal, delivery window = terminal appointment slot
Appointment slots last `slot` minutes (30–60 in practice) and are spread over
the day; customer windows are wide (half-day).  Container types 20', 40' and
reefer; vehicles carry one container (capacity 1) with chassis compatibility.

Relay yards have S_t slots, H_t handling bays, a transfer time sigma_t per
container and a handling cost h_t.  Everything is parameterised so the same
generator produces the uncapacitated case (S_t = H_t = inf).
"""
from __future__ import annotations

import math
import random

from .instance import Instance, Node, Request, TransferPoint, Vehicle, Params, INF


def generate(n_requests: int, *, seed: int = 0, n_yards: int = 2, n_zones: int = 4,
             r_min: float = 5.0, r_max: float = 60.0, slot: float = 45.0, day: float = 600.0,
             S: float = INF, H: float = INF, sigma: float = 15.0, h_cost: float = 20.0,
             W: float = INF, fleet: int | None = None, speed_kmh: float = 40.0,
             reefer_share: float = 0.15, forty_share: float = 0.5) -> Instance:
    rng = random.Random(seed)
    speed = speed_kmh / 60.0                       # km per minute
    nodes = {"terminal": Node("terminal", 0.0, 0.0, 0.0, day, 10.0),
             "depot": Node("depot", 2.0, -2.0, 0.0, day + 300.0, 0.0)}
    zones = [2 * math.pi * z / n_zones + rng.uniform(-0.2, 0.2) for z in range(n_zones)]
    requests = {}
    for i in range(n_requests):
        ang = rng.choice(zones) + rng.gauss(0, 0.25)
        rad = rng.uniform(r_min, r_max)
        cx, cy = rad * math.cos(ang), rad * math.sin(ang)
        cid = f"c{i+1}"
        kind = rng.choice(["import", "export"])
        # appointment slots must be reachable: depot -> (customer ->) terminal at speed, plus services
        d_depot_c = math.hypot(cx - 2.0, cy + 2.0) / speed
        d_c_term = rad / speed
        earliest = 5.0 + 20.0 + d_depot_c + d_c_term if kind == "export" else 5.0
        a_term = rng.uniform(earliest, max(earliest + 1.0, day - slot))
        if kind == "import":
            tid = f"T{i+1}"
            nodes[tid] = Node(tid, 0.0, 0.0, a_term, a_term + slot, 10.0)      # appointment at terminal
            nodes[cid] = Node(cid, cx, cy, 0.0, day + 60.0, 20.0)
            p, d = tid, cid
        else:
            tid = f"T{i+1}"
            nodes[cid] = Node(cid, cx, cy, 0.0, day, 20.0)
            nodes[tid] = Node(tid, 0.0, 0.0, a_term, a_term + slot, 10.0)
            p, d = cid, tid
        u = rng.random()
        ltype = "reefer" if u < reefer_share else ("40" if u < reefer_share + forty_share else "20")
        requests[f"r{i+1}"] = Request(f"r{i+1}", p, d, 1.0, ltype)
    tps = {}
    for y in range(n_yards):
        ang = zones[y % n_zones]
        rad = rng.uniform(3.0, 8.0)
        nid = f"yard{y+1}"
        nodes[nid] = Node(nid, rad * math.cos(ang), rad * math.sin(ang), 0.0, day + 120.0, 0.0)
        tps[nid] = TransferPoint(nid, nid, S, H, h_cost, sigma, W)
    k = fleet if fleet is not None else max(3, n_requests)
    vehicles = {}
    classes = [None, ["20"], ["40", "reefer"]]       # universal, 20'-only, 40'/reefer chassis
    for j in range(k):
        allowed = classes[j % 3]
        vehicles[f"k{j+1}"] = Vehicle(f"k{j+1}", 1.0, "depot", "depot", fixed_cost=150.0,
                                      cost_per_km=1.2, emission_per_km=0.9, allowed_types=allowed)
    inst = Instance(name=f"PORT-n{n_requests}-y{n_yards}-S{S}-H{H}-s{seed}", nodes=nodes, requests=requests,
                    transfer_points=tps, vehicles=vehicles,
                    params=Params(speed=speed, max_transfers_per_request=1, objective="weighted",
                                  weights={"vehicles": 0.0, "cost": 1.0, "emissions": 0.0}),
                    meta={"generator": "portgen v1", "units": "km, minutes", "speed_kmh": speed_kmh})
    inst.validate()
    return inst
