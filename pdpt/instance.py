# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Data model and JSON format for PDPTW-T instances.

An instance is a plain, versioned JSON document.  Every hypothesis of the
problem (number of transfers, storage, handling slots, fleet, compatibility)
is a field of the instance, never a code path, so that published benchmark
sets with different assumptions live in one format.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from typing import Optional

FORMAT_VERSION = "0.1"
INF = float("inf")


@dataclass
class Node:
    id: str
    x: float
    y: float
    tw_start: float = 0.0
    tw_end: float = INF
    service: float = 0.0


@dataclass
class Request:
    id: str
    pickup: str          # node id
    delivery: str        # node id
    quantity: float = 1.0
    load_type: str = "default"


@dataclass
class TransferPoint:
    id: str
    node: str                              # node id
    storage_capacity: float = INF          # S_t  (units simultaneously stored)
    handling_slots: int | float = INF      # H_t  (simultaneous operations)
    handling_cost: float = 0.0             # h_t  per unit moved (drop + pick counted once)
    transfer_time_per_unit: float = 0.0    # sigma_t
    max_storage_time: float = INF          # W_t


@dataclass
class Vehicle:
    id: str
    capacity: float
    start_node: str
    end_node: str
    fixed_cost: float = 0.0
    cost_per_km: float = 1.0
    emission_per_km: float = 0.0
    allowed_types: Optional[list[str]] = None   # None = all load types


@dataclass
class Params:
    max_transfers_per_request: int = 1     # kappa
    objective: str = "lexicographic"       # "lexicographic" | "weighted"
    weights: dict = field(default_factory=lambda: {"vehicles": 1e6, "cost": 1.0, "emissions": 0.0})
    speed: float = 1.0                     # used when travel is euclidean
    distance_rounding: Optional[int] = None
    min_vehicles_used: int = 0             # benchmarks that require every vehicle to serve a request
    single_visit_per_point: bool = False   # benchmarks where a vehicle visits a transfer point at most once
    cost_constant: float = 0.0             # added to the transport cost (e.g. deadhead trips of unused vehicles)


@dataclass
class Instance:
    name: str
    nodes: dict[str, Node]
    requests: dict[str, Request]
    transfer_points: dict[str, TransferPoint]
    vehicles: dict[str, Vehicle]
    params: Params = field(default_factory=Params)
    travel: str = "euclidean"              # "euclidean" | "matrix"
    dist_matrix: Optional[dict[str, dict[str, float]]] = None
    time_matrix: Optional[dict[str, dict[str, float]]] = None
    meta: dict = field(default_factory=dict)

    # ---- travel ---------------------------------------------------------
    _dm: Optional[dict] = field(default=None, repr=False, compare=False)
    _tm: Optional[dict] = field(default=None, repr=False, compare=False)

    def _build_tables(self) -> None:
        """Cache full distance and time tables (dict of dicts) on first use."""
        ids = list(self.nodes)
        if self.travel == "matrix":
            dm = {i: dict(self.dist_matrix[i]) for i in ids}
            tm = {i: dict(self.time_matrix[i]) for i in ids} if self.time_matrix is not None \
                else {i: {j: dm[i][j] / self.params.speed for j in ids} for i in ids}
        else:
            r = self.params.distance_rounding
            dm = {}
            for i in ids:
                a = self.nodes[i]
                row = {}
                for j in ids:
                    b = self.nodes[j]
                    d = math.hypot(a.x - b.x, a.y - b.y)
                    row[j] = round(d, r) if r is not None else d
                dm[i] = row
            sp = self.params.speed
            tm = {i: {j: dm[i][j] / sp for j in ids} for i in ids}
        self._dm, self._tm = dm, tm

    _arr: Optional[dict] = field(default=None, repr=False, compare=False)

    def arrays(self) -> dict:
        """Numeric views for compiled kernels: node index map, D, T, a, b, service."""
        if self._arr is None:
            import numpy as np
            if self._dm is None:
                self._build_tables()
            ids = list(self.nodes)
            idx = {nid: k for k, nid in enumerate(ids)}
            n = len(ids)
            D = np.empty((n, n)); Tm = np.empty((n, n))
            for i, ni in enumerate(ids):
                di, ti = self._dm[ni], self._tm[ni]
                for j, nj in enumerate(ids):
                    D[i, j] = di[nj]; Tm[i, j] = ti[nj]
            a = np.array([self.nodes[i].tw_start for i in ids])
            b = np.array([min(self.nodes[i].tw_end, 1e300) for i in ids])
            serv = np.array([self.nodes[i].service for i in ids])
            self._arr = {"idx": idx, "D": D, "T": Tm, "a": a, "b": b, "serv": serv}
        return self._arr

    def dist(self, i: str, j: str) -> float:
        if self._dm is None:
            self._build_tables()
        return self._dm[i][j]

    def time(self, i: str, j: str) -> float:
        if self._tm is None:
            self._build_tables()
        return self._tm[i][j]

    # ---- helpers --------------------------------------------------------
    def vehicle_allows(self, v: Vehicle, load_type: str) -> bool:
        return v.allowed_types is None or load_type in v.allowed_types

    # ---- (de)serialisation ---------------------------------------------
    def to_dict(self) -> dict:
        d = {
            "format_version": FORMAT_VERSION,
            "name": self.name,
            "meta": self.meta,
            "travel": self.travel,
            "params": asdict(self.params),
            "nodes": [asdict(n) for n in self.nodes.values()],
            "requests": [asdict(r) for r in self.requests.values()],
            "transfer_points": [asdict(t) for t in self.transfer_points.values()],
            "vehicles": [asdict(v) for v in self.vehicles.values()],
        }
        if self.travel == "matrix":
            d["dist_matrix"] = self.dist_matrix
            d["time_matrix"] = self.time_matrix
        return _encode_inf(d)

    @classmethod
    def from_dict(cls, d: dict) -> "Instance":
        d = _decode_inf(d)
        if d.get("format_version") != FORMAT_VERSION:
            raise ValueError(f"unsupported format_version {d.get('format_version')!r}")
        nodes = {n["id"]: Node(**n) for n in d["nodes"]}
        requests = {r["id"]: Request(**r) for r in d["requests"]}
        tps = {t["id"]: TransferPoint(**t) for t in d.get("transfer_points", [])}
        vehicles = {v["id"]: Vehicle(**v) for v in d["vehicles"]}
        params = Params(**d.get("params", {}))
        inst = cls(name=d["name"], nodes=nodes, requests=requests, transfer_points=tps,
                   vehicles=vehicles, params=params, travel=d.get("travel", "euclidean"),
                   dist_matrix=d.get("dist_matrix"), time_matrix=d.get("time_matrix"),
                   meta=d.get("meta", {}))
        inst.validate()
        return inst

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=1)

    @classmethod
    def load(cls, path: str) -> "Instance":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    # ---- structural validation -----------------------------------------
    def validate(self) -> None:
        self._dm, self._tm, self._arr = None, None, None
        for r in self.requests.values():
            for n in (r.pickup, r.delivery):
                if n not in self.nodes:
                    raise ValueError(f"request {r.id}: unknown node {n}")
            if r.quantity <= 0:
                raise ValueError(f"request {r.id}: quantity must be positive")
        for t in self.transfer_points.values():
            if t.node not in self.nodes:
                raise ValueError(f"transfer point {t.id}: unknown node {t.node}")
        for v in self.vehicles.values():
            for n in (v.start_node, v.end_node):
                if n not in self.nodes:
                    raise ValueError(f"vehicle {v.id}: unknown node {n}")
        if self.travel == "matrix":
            if self.dist_matrix is None:
                raise ValueError("travel=matrix requires dist_matrix")
            for i in self.nodes:
                for j in self.nodes:
                    if j not in self.dist_matrix.get(i, {}):
                        raise ValueError(f"dist_matrix missing ({i},{j})")
        elif self.travel != "euclidean":
            raise ValueError(f"unknown travel mode {self.travel}")


def _encode_inf(o):
    if isinstance(o, dict):
        return {k: _encode_inf(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_encode_inf(v) for v in o]
    if isinstance(o, float) and math.isinf(o):
        return "inf"
    return o


def _decode_inf(o):
    if isinstance(o, dict):
        return {k: _decode_inf(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_decode_inf(v) for v in o]
    if o == "inf":
        return INF
    return o
