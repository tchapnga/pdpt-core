# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Incremental evaluation of insertions (Proposition 4.5 of the paper, the local insertion test) on top of the max-plus plan.

A `State` keeps, for every route, the earliest starts x, the latest starts l
(dual system), and the loads after each visit.  Testing an insertion then only
recomputes dates on the inserted chain and compares them with the stored l of
the first unchanged successor, instead of repropagating the whole plan.  After
an accepted move the state is rebuilt in O(n + m).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .instance import Instance, INF
from .solution import Solution, Route, Visit, PICKUP, DELIVERY, DROP, PICK
from .maxplus import MaxPlusPlan

EPS = 1e-9


@dataclass
class RouteState:
    visits: list[Visit]
    x: list[float]          # earliest start per visit
    l: list[float]          # latest start per visit
    load: list[float]       # load after visit
    x_end: float            # earliest arrival at end depot
    l_end: float            # latest arrival at end depot
    arr: dict | None = None  # numpy views for the compiled kernel (built lazily)

    def numeric(self, inst: Instance) -> dict:
        if self.arr is None:
            import numpy as np
            A = inst.arrays()
            self.arr = {
                "nodes": np.array([A["idx"][v.node] for v in self.visits], dtype=np.int64),
                "x": np.array(self.x, dtype=np.float64),
                "l": np.array(self.l, dtype=np.float64),
                "load": np.array(self.load, dtype=np.float64),
                "dur": np.array([_dur(inst, v) for v in self.visits], dtype=np.float64),
            }
        return self.arr


@dataclass
class State:
    inst: Instance
    routes: dict[str, RouteState]
    drop_end: dict[tuple[str, str], tuple[str, float]] = field(default_factory=dict)   # (rid,t) -> (k, end of drop)
    pick_l: dict[tuple[str, str], float] = field(default_factory=dict)                # (rid,t) -> latest start of pick

    # ------------------------------------------------------------------ build
    @classmethod
    def build(cls, inst: Instance, routes: dict[str, list[Visit]]) -> "State":
        order = [k for k, v in routes.items() if v]
        sol = Solution(inst.name, routes=[Route(k, routes[k]) for k in order])
        st = cls(inst, {})
        if order:
            mp = MaxPlusPlan(inst, sol)
            l = mp.latest()
            for ri, k in enumerate(order):
                vs = routes[k]
                xs = [mp.x[mp.g.key[(ri, vi)]] for vi in range(len(vs))]
                ls = [l[mp.g.key[(ri, vi)]] for vi in range(len(vs))]
                st.routes[k] = RouteState(list(vs), xs, ls, _loads(inst, vs),
                                          mp.x[mp.g.key[(ri, -2)]], l[mp.g.key[(ri, -2)]])
                for vi, v in enumerate(vs):
                    if v.op == DROP:
                        st.drop_end[(v.request, v.transfer_point)] = (k, xs[vi] + _dur(inst, v))
                    elif v.op == PICK:
                        st.pick_l[(v.request, v.transfer_point)] = ls[vi]
        for k in inst.vehicles:
            if k not in st.routes:
                veh = inst.vehicles[k]
                st.routes[k] = RouteState([], [], [], [], inst.nodes[veh.start_node].tw_start,
                                          inst.nodes[veh.end_node].tw_end)
        return st

    # ------------------------------------------------------------------ padded arrays for batched kernels
    _pad: dict | None = None

    def padded(self) -> dict:
        """Padded per-route arrays over ALL vehicles (row = vehicle index), built once per state."""
        if self._pad is None:
            import numpy as np
            inst = self.inst
            A = inst.arrays()
            keys = list(inst.vehicles)
            Lmax = max(1, max(len(self.routes[k].visits) for k in keys))
            Kn = len(keys)
            NODES = np.zeros((Kn, Lmax), np.int64); X = np.zeros((Kn, Lmax)); Lm = np.zeros((Kn, Lmax))
            LOAD = np.zeros((Kn, Lmax)); DUR = np.zeros((Kn, Lmax)); N = np.zeros(Kn, np.int64)
            START = np.zeros(Kn, np.int64); END = np.zeros(Kn, np.int64); START_TW = np.zeros(Kn); L_END = np.zeros(Kn)
            CAP = np.zeros(Kn); COSTKM = np.zeros(Kn); FIXED = np.zeros(Kn)
            for r, k in enumerate(keys):
                rs = self.routes[k]; veh = inst.vehicles[k]
                R = rs.numeric(inst); n = len(rs.visits)
                NODES[r, :n] = R["nodes"]; X[r, :n] = R["x"]; Lm[r, :n] = R["l"]; LOAD[r, :n] = R["load"]; DUR[r, :n] = R["dur"]
                N[r] = n; START[r] = A["idx"][veh.start_node]; END[r] = A["idx"][veh.end_node]
                START_TW[r] = inst.nodes[veh.start_node].tw_start; L_END[r] = rs.l_end
                CAP[r] = veh.capacity; COSTKM[r] = veh.cost_per_km; FIXED[r] = veh.fixed_cost
            self._pad = {"keys": keys, "row": {k: r for r, k in enumerate(keys)}, "NODES": NODES, "X": X, "L": Lm,
                         "LOAD": LOAD, "DUR": DUR, "N": N, "START": START, "END": END, "START_TW": START_TW,
                         "L_END": L_END, "CAP": CAP, "COSTKM": COSTKM, "FIXED": FIXED}
        return self._pad

    # ------------------------------------------------------------------ resources
    def resources_ok(self) -> bool:
        """Sweep-line check of S_t and H_t at every capacitated point on the
        stored schedule x (dates of drops and picks may have moved after ANY move)."""
        inst = self.inst
        for t_id, tp in inst.transfer_points.items():
            if tp.storage_capacity == INF and tp.handling_slots == INF:
                continue
            drops, picks, ops = {}, {}, []
            for k, rs in self.routes.items():
                for vi, v in enumerate(rs.visits):
                    if v.op in (DROP, PICK) and v.transfer_point == t_id:
                        s = rs.x[vi]
                        e = s + _dur(inst, v)
                        ops.append((s, e))
                        (drops if v.op == DROP else picks)[v.request] = (s, e)
            if tp.storage_capacity < INF:
                ev = []
                for r, (s, e) in drops.items():
                    if r in picks:
                        q = inst.requests[r].quantity
                        ev.append((e, +q))
                        ev.append((picks[r][0], -q))
                ev.sort(key=lambda z: (z[0], z[1]))
                st = 0.0
                for _, dq in ev:
                    st += dq
                    if st > tp.storage_capacity + EPS:
                        return False
            if tp.handling_slots < INF:
                ev = []
                for s, e in ops:
                    if e > s:
                        ev.append((s, +1))
                        ev.append((e, -1))
                ev.sort(key=lambda z: (z[0], z[1]))
                busy = 0
                for _, d in ev:
                    busy += d
                    if busy > tp.handling_slots:
                        return False
        return True

    # ------------------------------------------------------------------ queries
    def feasible_schedule(self) -> bool:
        return all(x <= l + EPS for rs in self.routes.values() for x, l in zip(rs.x, rs.l)) and \
            all(rs.x_end <= rs.l_end + EPS for rs in self.routes.values())

    def cost(self) -> float:
        inst = self.inst
        c = inst.params.cost_constant
        for k, rs in self.routes.items():
            if not rs.visits:
                continue
            veh = inst.vehicles[k]
            c += veh.fixed_cost
            prev = veh.start_node
            for v in rs.visits:
                c += veh.cost_per_km * inst.dist(prev, v.node)
                if v.op == DROP:
                    c += inst.transfer_points[v.transfer_point].handling_cost * inst.requests[v.request].quantity
                prev = v.node
            c += veh.cost_per_km * inst.dist(prev, veh.end_node)
        return c

    # ------------------------------------------------------------------ insertion tests
    def try_insert_chain(self, k: str, i: int, j: int, first: Visit, second: Visit,
                         extra_release: dict[int, float] | None = None) -> tuple[bool, float, list[float]]:
        """Insert `first` before position i and `second` before position j (j >= i) of route k.

        Returns (feasible, cost delta, earliest starts of the new sequence i..j+1).
        `extra_release` maps a position in the NEW sequence to an additional release
        date (the drop-end a pick must wait for).  Only the chain i..j is recomputed;
        the first unchanged successor is checked against its stored latest start.
        """
        inst, rs = self.inst, self.routes[k]
        veh = inst.vehicles[k]
        req = inst.requests[first.request]
        if not inst.vehicle_allows(veh, req.load_type):
            return False, 0.0, []
        # capacity: load on [i, j) increases by q
        q = req.quantity if first.op in (PICKUP, PICK) else -req.quantity
        base_load = rs.load[i - 1] if i > 0 else 0.0
        if base_load + q > veh.capacity + EPS or base_load + q < -EPS:
            return False, 0.0, []
        for pos in range(i, j):
            if rs.load[pos] + q > veh.capacity + EPS:
                return False, 0.0, []
        # new sequence between positions i-1 and j (exclusive) of the old route
        seq = [first] + rs.visits[i:j] + [second]
        prev_node = rs.visits[i - 1].node if i > 0 else veh.start_node
        t = (rs.x[i - 1] + _dur(inst, rs.visits[i - 1])) if i > 0 else inst.nodes[veh.start_node].tw_start
        xs = []
        for pos, v in enumerate(seq):
            node = inst.nodes[v.node]
            arr = t + inst.time(prev_node, v.node)
            start = max(arr, node.tw_start)
            if extra_release and pos in extra_release:
                start = max(start, extra_release[pos])
            if start > node.tw_end + EPS:
                return False, 0.0, []
            # a pick's own latest start may be bounded by a stored l (if it exists in state)
            xs.append(start)
            t = start + _dur(inst, v)
            prev_node = v.node
        # junction with the first unchanged successor
        if j < len(rs.visits):
            nxt = rs.visits[j]
            arr = t + inst.time(prev_node, nxt.node)
            if arr > rs.l[j] + EPS:
                return False, 0.0, []
        else:
            arr = t + inst.time(prev_node, veh.end_node)
            if arr > rs.l_end + EPS:
                return False, 0.0, []
        # drops inserted on this route must respect the latest start of an existing pick
        for pos, v in enumerate(seq):
            if v.op == DROP:
                lp = self.pick_l.get((v.request, v.transfer_point))
                if lp is not None and xs[pos] + _dur(inst, v) > lp + EPS:
                    return False, 0.0, []
        # cost delta (distances + handling)
        old_prev = rs.visits[i - 1].node if i > 0 else veh.start_node
        old_next = rs.visits[j].node if j < len(rs.visits) else veh.end_node
        delta = 0.0
        if i == j:
            delta += inst.dist(old_prev, first.node) + inst.dist(first.node, second.node) + \
                inst.dist(second.node, old_next) - inst.dist(old_prev, old_next)
        else:
            a, b = rs.visits[i].node, rs.visits[j - 1].node
            delta += inst.dist(old_prev, first.node) + inst.dist(first.node, a) - inst.dist(old_prev, a)
            delta += inst.dist(b, second.node) + inst.dist(second.node, old_next) - inst.dist(b, old_next)
        delta *= veh.cost_per_km
        if not rs.visits:
            delta += veh.fixed_cost
        for v in (first, second):
            if v.op == DROP:
                delta += inst.transfer_points[v.transfer_point].handling_cost * req.quantity
        return True, delta, xs


def _dur(inst: Instance, v: Visit) -> float:
    if v.op in (DROP, PICK):
        return inst.transfer_points[v.transfer_point].transfer_time_per_unit * inst.requests[v.request].quantity
    return inst.nodes[v.node].service


def _loads(inst: Instance, visits: list[Visit]) -> list[float]:
    out, load = [], 0.0
    for v in visits:
        q = inst.requests[v.request].quantity
        load += q if v.op in (PICKUP, PICK) else -q
        out.append(load)
    return out


def resource_ok(inst: Instance, routes: dict[str, list[Visit]], t_id: str) -> bool:
    """Sweep-line check of S_t and H_t at one point, on a full schedule (used only
    when the point is capacitated)."""
    tp = inst.transfer_points[t_id]
    if tp.storage_capacity == INF and tp.handling_slots == INF:
        return True
    order = [k for k, v in routes.items() if v]
    sol = Solution(inst.name, routes=[Route(k, routes[k]) for k in order])
    mp = MaxPlusPlan(inst, sol)
    drops, picks, ops = {}, {}, []
    for ri, k in enumerate(order):
        for vi, v in enumerate(routes[k]):
            if v.op in (DROP, PICK) and v.transfer_point == t_id:
                s = mp.x[mp.g.key[(ri, vi)]]
                e = s + _dur(inst, v)
                ops.append((s, e))
                (drops if v.op == DROP else picks)[v.request] = (s, e)
    if tp.storage_capacity < INF:
        ev = []
        for r, (s, e) in drops.items():
            if r in picks:
                q = inst.requests[r].quantity
                ev.append((e, +q))
                ev.append((picks[r][0], -q))
        ev.sort(key=lambda z: (z[0], z[1]))
        st = 0.0
        for _, dq in ev:
            st += dq
            if st > tp.storage_capacity + EPS:
                return False
    if tp.handling_slots < INF:
        ev = []
        for s, e in ops:
            if e > s:
                ev.append((s, +1))
                ev.append((e, -1))
        ev.sort(key=lambda z: (z[0], z[1]))
        busy = 0
        for _, d in ev:
            busy += d
            if busy > tp.handling_slots:
                return False
    return True
