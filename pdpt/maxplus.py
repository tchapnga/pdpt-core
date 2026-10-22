# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Max-plus algebra of transfer-synchronised routes.

Every date in a solution of the PDPTW-T obeys one rule:
    date(e) = max over predecessors p of ( date(p) + w(p, e) ),  and  date(e) >= a_e.
This is a linear system in the (max, +) semiring:  x = A ⊗ x ⊕ b,  whose least
solution is  x = A* ⊗ b  (Kleene star).  Here A is the *event matrix* of the
plan, b the vector of release dates (time-window lower bounds), and the events
are the visits of all routes plus the depot departures and returns.  Transfers
add arcs between routes (drop → pick).

What the algebra gives for free:
  * schedule     : x = A* ⊗ b                               (earliest start of every event)
  * sensitivity  : A*[p, e] = longest path p → e;  a delay δ at p moves e to max(x_e, x_p + δ + A*[p,e])
  * margin       : m(p) = min_e ( b^max_e − x_p − A*[p,e] ) = largest delay at p that breaks no deadline
  * criticality  : the arcs on tight paths  (A*[p,e] = x_e − x_p)
  * feasibility  : the plan is consistent iff the event graph is acyclic (Proposition 4.1 of the paper;
                   a circuit of weight zero is inconsistent too, and the topological sort below raises on it)

The star is computed per source by a longest-path pass in topological order
(the event graph of a consistent plan is acyclic), O(n (n + m)).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque

from .instance import Instance, INF
from .solution import Solution, DROP, PICK

NEG = float("-inf")   # ε, the max-plus zero


@dataclass
class Event:
    kind: str                 # "start" | "visit" | "end"
    route: int
    index: int                # visit index, -1 for start, -2 for end
    node: str
    release: float            # a_e  (max-plus b)
    deadline: float           # b_e
    duration: float           # service or handling time spent at the event


@dataclass
class EventGraph:
    events: list[Event]
    arcs: dict[int, list[tuple[int, float]]]          # e -> [(succ, weight)]
    preds: dict[int, list[tuple[int, float]]]         # e -> [(pred, weight)]
    sync: list[tuple[int, int]]                       # (drop event, pick event)
    sync_tp: list[str] = field(default_factory=list)  # transfer point id per sync arc
    key: dict[tuple[int, int], int] = field(default_factory=dict)   # (route, index) -> event id


def build_event_graph(inst: Instance, sol: Solution) -> EventGraph:
    events: list[Event] = []
    key: dict[tuple[int, int], int] = {}
    arcs: dict[int, list[tuple[int, float]]] = {}
    preds: dict[int, list[tuple[int, float]]] = {}

    def add(e: Event, k: tuple[int, int]) -> int:
        events.append(e)
        i = len(events) - 1
        key[k] = i
        arcs[i], preds[i] = [], []
        return i

    def link(p: int, s: int, w: float) -> None:
        arcs[p].append((s, w))
        preds[s].append((p, w))

    drops: dict[tuple[str, str], int] = {}
    picks: dict[tuple[str, str], int] = {}
    for ri, route in enumerate(sol.routes):
        veh = inst.vehicles[route.vehicle]
        s0 = inst.nodes[veh.start_node]
        start = add(Event("start", ri, -1, veh.start_node, s0.tw_start, s0.tw_end, 0.0), (ri, -1))
        prev, prev_node = start, veh.start_node
        for vi, vis in enumerate(route.visits):
            node = inst.nodes[vis.node]
            dur = node.service
            if vis.op in (DROP, PICK):
                tp = inst.transfer_points[vis.transfer_point]
                dur = tp.transfer_time_per_unit * inst.requests[vis.request].quantity
            e = add(Event("visit", ri, vi, vis.node, node.tw_start, node.tw_end, dur), (ri, vi))
            link(prev, e, events[prev].duration + inst.time(prev_node, vis.node))
            if vis.op == DROP:
                drops[(vis.request, vis.transfer_point)] = e
            elif vis.op == PICK:
                picks[(vis.request, vis.transfer_point)] = e
            prev, prev_node = e, vis.node
        e1 = inst.nodes[veh.end_node]
        end = add(Event("end", ri, -2, veh.end_node, e1.tw_start, e1.tw_end, 0.0), (ri, -2))
        link(prev, end, events[prev].duration + inst.time(prev_node, veh.end_node))

    sync: list[tuple[int, int]] = []
    sync_tp: list[str] = []
    for k, d in drops.items():
        p = picks.get(k)
        if p is None:
            continue
        link(d, p, events[d].duration)      # pick may start once the drop handling is done
        sync.append((d, p))
        sync_tp.append(k[1])
    return EventGraph(events, arcs, preds, sync, sync_tp, key)


class MaxPlusPlan:
    """Max-plus view of a plan: schedule, star matrix, margins, delay propagation."""

    def __init__(self, inst: Instance, sol: Solution):
        self.inst, self.sol = inst, sol
        self.g = build_event_graph(inst, sol)
        self.n = len(self.g.events)
        self.order = self._topological_order()          # raises on a circuit
        self.x = self._schedule()
        self._star: list[list[float]] | None = None

    # ---- structure ------------------------------------------------------
    def _topological_order(self) -> list[int]:
        indeg = {i: len(self.g.preds[i]) for i in range(self.n)}
        q = deque(i for i in range(self.n) if indeg[i] == 0)
        order = []
        while q:
            u = q.popleft()
            order.append(u)
            for v, _ in self.g.arcs[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        if len(order) != self.n:
            raise ValueError("event graph has a circuit: the transfer plan is inconsistent "
                             "(a vehicle waits, directly or not, for a load it must itself deliver)")
        return order

    # ---- x = A* ⊗ b ------------------------------------------------------
    def _schedule(self) -> list[float]:
        x = [NEG] * self.n
        for u in self.order:
            x[u] = max(x[u], self.g.events[u].release)
            for v, w in self.g.arcs[u]:
                x[v] = max(x[v], x[u] + w)
        return x

    def start(self, route: int, index: int) -> float:
        return self.x[self.g.key[(route, index)]]

    # ---- ℓ : latest starts, greatest solution of the dual (min,+) system ---
    def latest(self) -> list[float]:
        """l_u = min(beta_u, min over arcs u->v of (l_v - w_uv)); one reverse pass."""
        l = [self.g.events[u].deadline for u in range(self.n)]
        # maximum storage time W_t bounds the latest start of a pick by the drop end + W_t
        for (d, p), tp in zip(self.g.sync, self.g.sync_tp):
            W = self.inst.transfer_points[tp].max_storage_time
            if W < INF:
                l[p] = min(l[p], self.x[d] + self.g.events[d].duration + W)
        for u in reversed(self.order):
            for v, w in self.g.arcs[u]:
                if l[v] - w < l[u]:
                    l[u] = l[v] - w
        return l

    def feasible(self, eps: float = 1e-9) -> tuple[bool, list[int]]:
        late = [i for i, e in enumerate(self.g.events) if self.x[i] > e.deadline + eps]
        return (not late, late)

    # ---- A* : longest path lengths ---------------------------------------
    def star(self) -> list[list[float]]:
        if self._star is None:
            S = []
            pos = {u: k for k, u in enumerate(self.order)}
            for p in range(self.n):
                row = [NEG] * self.n
                row[p] = 0.0
                for u in self.order[pos[p]:]:
                    if row[u] == NEG:
                        continue
                    for v, w in self.g.arcs[u]:
                        if row[u] + w > row[v]:
                            row[v] = row[u] + w
                S.append(row)
            self._star = S
        return self._star

    # ---- delay propagation:  x' = x ⊕ (δ ⊗ x_p ⊗ A*[p, ·]) ----------------
    def propagate(self, p: int, delta: float) -> list[float]:
        row = self.star()[p]
        base = self.x[p] + delta
        return [max(self.x[e], base + row[e]) if row[e] > NEG else self.x[e] for e in range(self.n)]

    # ---- margin: largest delay at p that breaks no deadline ---------------
    def margin(self, p: int) -> tuple[float, int | None]:
        row = self.star()[p]
        best, arg = INF, None
        for e in range(self.n):
            if row[e] == NEG:
                continue
            dl = self.g.events[e].deadline
            if dl == INF:
                continue
            m = dl - (self.x[p] + row[e])
            if m < best:
                best, arg = m, e
        return best, arg

    def margins(self) -> list[tuple[float, int | None]]:
        return [self.margin(p) for p in range(self.n)]

    # ---- tight (critical) arcs ------------------------------------------
    def critical_arcs(self, eps: float = 1e-9) -> list[tuple[int, int]]:
        out = []
        for u in range(self.n):
            for v, w in self.g.arcs[u]:
                if abs(self.x[u] + w - self.x[v]) <= eps and self.x[v] > self.g.events[v].release + eps:
                    out.append((u, v))
        return out

    def transfer_slacks(self) -> list[tuple[int, int, float]]:
        """For each transfer (drop d, pick p): how long the pick could be advanced
        before it would wait on the drop. Zero = the synchronisation is binding."""
        return [(d, p, self.x[p] - (self.x[d] + self.g.events[d].duration)) for d, p in self.g.sync]
