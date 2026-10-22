# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Converters from published benchmark formats to the PDPTW-T JSON format.

Each published set keeps its own hypotheses, encoded in the instance (not in
code).  A converter never silently changes a hypothesis: what it assumes is
written in `meta`.
"""
from __future__ import annotations

from pathlib import Path
import dataclasses

from .instance import Instance, Node, Request, TransferPoint, Vehicle, Params, INF


def li_lim(path: str | Path, name: str | None = None, fleet_size: int | None = None) -> Instance:
    """Li & Lim (2001) PDPTW benchmark, SINTEF text format.

    Header: `vehicles capacity speed`.  Then one line per node:
    `id x y demand tw_start tw_end service pickup_idx delivery_idx`
    (demand > 0 is a pickup whose delivery_idx names its delivery node).
    Node 0 is the depot.  No transfer points: T is empty, so the instance is a
    plain PDPTW; it becomes a PDPTW-T by adding transfer points afterwards.
    """
    path = Path(path)
    lines = [ln.split() for ln in path.read_text().splitlines() if ln.strip()]
    n_veh, capacity, speed = int(lines[0][0]), float(lines[0][1]), float(lines[0][2])
    if speed <= 0:
        speed = 1.0
    rows = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]),
             float(r[6]), int(r[7]), int(r[8])) for r in lines[1:]]
    nodes: dict[str, Node] = {}
    requests: dict[str, Request] = {}
    for nid, x, y, dem, a, b, s, pi, di in rows:
        nodes[str(nid)] = Node(str(nid), x, y, a, b, s)
    for nid, x, y, dem, a, b, s, pi, di in rows:
        if dem > 0:
            requests[f"r{nid}"] = Request(f"r{nid}", pickup=str(nid), delivery=str(di), quantity=dem)
    k = fleet_size if fleet_size is not None else (n_veh if n_veh > 0 else len(requests))
    vehicles = {f"v{i}": Vehicle(f"v{i}", capacity, "0", "0") for i in range(k)}
    inst = Instance(name=name or path.stem, nodes=nodes, requests=requests, transfer_points={},
                    vehicles=vehicles, params=Params(speed=speed, max_transfers_per_request=1),
                    meta={"source": "Li & Lim 2001 (SINTEF)", "file": path.name,
                          "assumptions": "homogeneous fleet, single depot, no transfer points"})
    inst.validate()
    return inst


def add_transfer_points(inst: Instance, points: list[tuple[str, float, float]], *,
                        storage_capacity: float = INF, handling_slots: int | float = INF,
                        handling_cost: float = 0.0, transfer_time_per_unit: float = 0.0,
                        max_storage_time: float = INF, tw: tuple[float, float] = (0.0, INF)) -> Instance:
    """Return a copy of `inst` with transfer points added at the given (id, x, y)."""
    import copy
    out = copy.deepcopy(inst)
    for tid, x, y in points:
        nid = f"tp_{tid}"
        out.nodes[nid] = Node(nid, x, y, tw[0], tw[1], 0.0)
        out.transfer_points[tid] = TransferPoint(tid, nid, storage_capacity, handling_slots,
                                                 handling_cost, transfer_time_per_unit, max_storage_time)
    out.validate()
    return out


def lyu_yu(path: str | Path, name: str | None = None, all_vehicles_used: bool = False) -> Instance:
    """Lyu & Yu (2023) PDPT / PDPTW-T instances (Mendeley w925jygjct).

    Header `nr nv nt capacity`, then `node x y a b load` rows: p<i>/d<i> pickup and
    delivery of request i, o<k>/e<k> start and end depot of vehicle k, t<j> transfer
    station j.  Conventions of the paper (and of Avgerinos et al. 2025 on the same
    files): objective = total Euclidean distance, no fixed vehicle cost, vehicles need
    not be used, travel time = distance (unit speed), zero service and transfer times,
    unlimited storage and waiting at stations (S_t = H_t = W_t = inf, sigma_t = h_t = 0).
    Every vehicle travels from o_k to e_k: an unused vehicle pays its direct trip (checked on
    PDPT-R5-K3-T3-Q100-0: published 352.84 = two-vehicle plan 322.8 + direct trip 30.0 of the third;
    on PDPT-R10-K2-T1-Q100-0 the same rule makes the two-vehicle plan 649.36 optimal).  For the
    PDPTW-T set o_k = e_k, so the rule is void and vehicles are simply optional.  `all_vehicles_used`
    (legacy) forces every vehicle to serve a request instead.
    kappa = 1 and a vehicle visits a given station at most once (their station vertex is unique per
    vehicle): without that rule the search found plans below their certified optima (e.g.
    PDPT-R10-K2-T1-Q100-1: 714.92 < 716.40 with two visits of t0 by one vehicle).
    """
    path = Path(path)
    lines = [ln.split() for ln in path.read_text().splitlines() if ln.strip()]
    nr, nv, nt, cap = int(lines[1][0]), int(lines[1][1]), int(lines[1][2]), float(lines[1][3])
    rows = [r for r in lines[2:] if r[0] != "node"]
    nodes: dict[str, Node] = {}
    load: dict[str, float] = {}
    for nid, x, y, a, b, q in rows:
        nodes[nid] = Node(nid, float(x), float(y), float(a), float(b), 0.0)
        load[nid] = float(q)
    requests = {f"r{i}": Request(f"r{i}", f"p{i}", f"d{i}", load[f"p{i}"]) for i in range(nr)}
    # Convention of their model (verified on PDPT-R5-K3-T3-Q100-0, optimum 352.84 = 322.8 + 30.0): every
    # vehicle travels from its origin to its destination depot; an unused vehicle pays the direct trip.
    # Encoded as fixed_cost = -d(o_k, e_k) per used vehicle plus the constant sum of all direct trips.
    import math as _m
    dead = {k: _m.hypot(nodes[f"o{k}"].x - nodes[f"e{k}"].x, nodes[f"o{k}"].y - nodes[f"e{k}"].y) for k in range(nv)}
    vehicles = {f"k{k}": Vehicle(f"k{k}", cap, f"o{k}", f"e{k}", fixed_cost=-dead[k], cost_per_km=1.0)
                for k in range(nv)}
    tps = {f"t{j}": TransferPoint(f"t{j}", f"t{j}") for j in range(nt)}
    inst = Instance(name=name or path.stem, nodes=nodes, requests=requests, transfer_points=tps,
                    vehicles=vehicles,
                    params=Params(speed=1.0, max_transfers_per_request=1, objective="weighted",
                                  weights={"vehicles": 0.0, "cost": 1.0, "emissions": 0.0},
                                  min_vehicles_used=0, single_visit_per_point=True,
                                  cost_constant=sum(dead.values())),
                    meta={"source": "Lyu & Yu 2023 (Mendeley w925jygjct v4)", "file": path.name,
                          "assumptions": "total distance; unit speed; no service/transfer time; "
                                         "unbounded stations; vehicles optional; kappa=1"})
    inst.validate()
    return inst


def lyu_yu_results(path: str | Path) -> dict[str, dict]:
    """Parse a Results/*.txt file of the archive: {instance stem: {model: (status, ub, gap, time)}}."""
    out: dict[str, dict] = {}
    for ln in Path(path).read_text().splitlines():
        parts = ln.split("\t")
        if len(parts) < 6 or parts[1] not in ("OPTIMAL", "TIMEOUT"):
            continue
        stem = parts[0].replace("\\", "/").split("/")[-1].replace("data", "", 1) if parts[0].startswith("data") and "/" not in parts[0] and "\\" not in parts[0] else parts[0].replace("\\", "/").split("/")[-1]
        stem = stem[:-4] if stem.endswith(".txt") else stem
        ub = float(parts[2]) if parts[2] != "inf" else None
        gap = float(parts[3]) if parts[3] != "inf" else None
        out.setdefault(stem, {})[parts[5].strip()] = (parts[1], ub, gap, float(parts[4]))
    return out


def sampaio(path: str | Path, name: str | None = None, vehicles_per_depot: int | None = None,
            capacity: float = INF, integer_times: bool = False):
    """Sampaio, Savelsbergh, Veelenturf & Van Woensel (2020) PDPTW-T instances (Mendeley pywzcgyzrv).

    JSON with `requests` (p/d: id, x, y, window [l, u]; q), `depots` (id, x, y, window = driver
    availability), `transfers` (id, x, y, no window) and `routes` (an initial PDPTW solution).
    Conventions of the paper (Networks 76(2), 2020, Sec. 3 and 5.1): minimise total distance
    (one distance unit = one time unit), unlimited drivers at each of four depots, each driver
    within its depot shift window, capacity never restricting, a single transfer per request,
    short-term storage and waiting allowed at transfer locations, no service or transfer time.
    The paper also assumes a vehicle visits a given transfer location at most once; the search
    does not impose it, and the campaign script counts revisits so the deviation is reported.

    integer_times=True rounds every Euclidean distance (and hence travel time) UP to the next integer:
    this is the metric of the published values.  The published cost of the shipped PDPTW plans
    (their Tables 5-8) equals the cost of the shipped routes under this rounding on every 50-request
    class (to 0.1 on sixteen of eighteen, within 0.9 on the other two), and every shipped plan is
    feasible under the rounded times, whereas plans optimised with exact distances generally are
    not (they use the shift to the last minute).  A comparison with the published values is on equal
    terms only under integer_times=True; the default keeps the exact Euclidean metric.
    Returns (instance, warm_start_solution_or_None)."""
    import json as _json
    from .solution import Solution, Route, Visit, PICKUP, DELIVERY
    path = Path(path)
    d = _json.loads(path.read_text())
    nodes: dict[str, Node] = {}
    requests: dict[str, Request] = {}
    byid: dict[str, str] = {}
    for rid, r in d["requests"].items():
        p, q = r["p"], r["d"]
        pid, did = f"p{p['id']}", f"d{q['id']}"
        nodes[pid] = Node(pid, float(p["x"]), float(p["y"]), float(p["l"]), float(p["u"]), 0.0)
        nodes[did] = Node(did, float(q["x"]), float(q["y"]), float(q["l"]), float(q["u"]), 0.0)
        requests[rid] = Request(rid, pid, did, float(r.get("q", 1)))
        byid[str(p["id"])] = pid; byid[str(q["id"])] = did
    tps = {}
    for tid, t in d["transfers"].items():
        nid = f"t{t['id']}"
        nodes[nid] = Node(nid, float(t["x"]), float(t["y"]), 0.0, INF, 0.0)
        tps[tid] = TransferPoint(tid, nid)
    n = len(requests)
    vpd = vehicles_per_depot if vehicles_per_depot is not None else n   # 'unlimited' drivers per depot
    vehicles = {}
    for dep, v in d["depots"].items():
        nid = f"depot_{dep}"
        nodes[nid] = Node(nid, float(v["x"]), float(v["y"]), float(v["l"]), float(v["u"]), 0.0)
        for j in range(vpd):
            vehicles[f"{dep}_{j}"] = Vehicle(f"{dep}_{j}", capacity, nid, nid, fixed_cost=0.0, cost_per_km=1.0)
    inst = Instance(name=name or f"SA-{path.parent.parent.parent.name}-{path.parent.name}-{path.stem}",
                    nodes=nodes, requests=requests, transfer_points=tps, vehicles=vehicles,
                    params=Params(speed=1.0, max_transfers_per_request=1, objective="weighted",
                                  weights={"vehicles": 0.0, "cost": 1.0, "emissions": 0.0},
                                  single_visit_per_point=True),
                    meta={"source": "Sampaio et al. 2020 (Mendeley pywzcgyzrv v1)", "file": str(path),
                          "factor": d.get("factor"),
                          "assumptions": "total distance; unit speed; no service/transfer time; unbounded "
                                         f"transfer points; {vpd} optional drivers per depot; kappa=1"})
    if integer_times:
        import math as _math
        ids = list(nodes)
        dm = {i: {j: float(_math.ceil(_math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y) - 1e-9))
                  for j in ids} for i in ids}
        inst = dataclasses.replace(inst, travel="matrix", dist_matrix=dm, time_matrix=dm)
        inst.meta["assumptions"] += "; distances and times rounded up to the integer (published metric)"
    inst.validate()
    # warm start: the PDPTW routes shipped with the instance
    warm = None
    if d.get("routes"):
        routes = []
        counters = {dep: 0 for dep in d["depots"]}
        for rk, seq in d["routes"].items():
            dep = seq[0]
            if dep not in counters or counters[dep] >= vpd:
                warm = None
                break
            visits = []
            for s in seq[1:-1]:
                nid = byid.get(str(s))
                if nid is None:
                    break
                rid = next(r for r, rq in requests.items() if rq.pickup == nid or rq.delivery == nid)
                visits.append(Visit(nid, PICKUP if nid.startswith("p") else DELIVERY, rid))
            routes.append(Route(f"{dep}_{counters[dep]}", visits))
            counters[dep] += 1
        else:
            warm = Solution(inst.name, routes)
    return inst, warm
