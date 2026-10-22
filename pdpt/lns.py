# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Large-neighbourhood matheuristic for the PDPTW-CT (version 2: incremental evaluation).

  * transfers are first-class from construction onwards (direct and transferred
    insertions compete for every request);
  * destroy: random, related (Shaw), worst-cost, route, and the transfer-native
    operators point removal, synchronisation removal, tension removal (Prop. 4);
  * repair: regret-k over direct and transferred insertions, each tested with the
    local insertion test of Proposition 4.5 (`incremental.State.try_insert_chain`);
  * simulated-annealing acceptance; lexicographic objective (vehicles, cost).

The independent verifier is run on every accepted plan and on the result.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .instance import Instance, INF
from .solution import Solution, Route, Visit, PICKUP, DELIVERY, DROP, PICK
from .verifier import verify, single_visit_ok, Report
from .maxplus import MaxPlusPlan
from .incremental import State, resource_ok, _dur


# --------------------------------------------------------------------------- plan
@dataclass
class Plan:
    inst: Instance
    routes: dict[str, list[Visit]]
    unassigned: set[str] = field(default_factory=set)
    state: State | None = None
    closed: set[str] = field(default_factory=set)      # vehicles not to be (re)opened in this repair

    def copy(self) -> "Plan":
        return Plan(self.inst, {k: list(v) for k, v in self.routes.items()}, set(self.unassigned), None, set(self.closed))

    def refresh(self) -> "State":
        self.state = State.build(self.inst, self.routes)
        return self.state

    def to_solution(self) -> Solution:
        return Solution(self.inst.name, routes=[Route(k, list(v)) for k, v in self.routes.items() if v])

    def vehicles_used(self) -> int:
        return sum(1 for v in self.routes.values() if v)

    def requests_in(self, k: str) -> set[str]:
        return {v.request for v in self.routes[k]}

    def transfers(self) -> list[tuple[str, str, str, str]]:
        drops, picks = {}, {}
        for k, visits in self.routes.items():
            for v in visits:
                if v.op == DROP:
                    drops[(v.request, v.transfer_point)] = k
                elif v.op == PICK:
                    picks[(v.request, v.transfer_point)] = k
        return [(r, t, kd, picks[(r, t)]) for (r, t), kd in drops.items() if (r, t) in picks]

    def remove_request(self, rid: str) -> None:
        for k in self.routes:
            self.routes[k] = [v for v in self.routes[k] if v.request != rid]
        self.unassigned.add(rid)
        self.state = None


_PHASE = {"fleet_first": False, "fleet_lex": True}   # fleet_lex: rank moves by (vehicles opened, delta)
# ablation switches (set by solve(variant=...)); "full" = the method of the paper
ABLATION = {"variant": "full"}
VARIANTS = ("full", "no_transfer_ops", "no_phase1", "no_noise", "python_o1", "full_reprop")


def objective_key(inst: Instance, rep: Report, unassigned: int = 0, plan: "Plan | None" = None) -> tuple:
    """Unassigned requests (request bank) dominate everything else.  In the fleet-reduction phase
    the key is (vehicles, -sum nb(r_k)^2, cost): the squared route sizes reward unbalanced plans
    whose smallest route is easy to empty (Tchapnga Takoudjou 2014, Sec. 4.2.1)."""
    bal = -sum(len(v) ** 2 for v in plan.routes.values()) if plan is not None else 0
    # benchmarks that require every vehicle to be used: missing vehicles count like unassigned requests
    short = max(0, min(inst.params.min_vehicles_used, len(inst.requests) - unassigned) - rep.vehicles_used)
    if inst.params.objective == "weighted":
        if _PHASE["fleet_first"]:
            return (unassigned + short, rep.vehicles_used, bal, round(rep.objective(inst), 6))
        return (unassigned + short, round(rep.objective(inst), 6))
    if _PHASE["fleet_first"]:
        return (unassigned + short, rep.vehicles_used, bal, round(rep.cost, 6))
    return (unassigned + short, rep.vehicles_used, round(rep.cost, 6))


def _evaluate(inst: Instance, plan: "Plan") -> tuple[Report, tuple]:
    """Verify the assigned part of a plan and return (report, key)."""
    if plan.unassigned:
        import copy
        sub = copy.copy(inst)
        sub.requests = {r: q for r, q in inst.requests.items() if r not in plan.unassigned}
        rep = verify(sub, plan.to_solution())
    else:
        rep = verify(inst, plan.to_solution())
    if not rep.feasible and all(m.startswith("fleet:") for m in rep.violations):
        rep.feasible = True               # the fleet shortfall is carried by the key, not by feasibility
    return rep, objective_key(inst, rep, len(plan.unassigned), plan)


# --------------------------------------------------------------------------- insertion candidates
@dataclass
class Move:
    rid: str
    new_vehicle: int          # 0 or 1 (or 2 for a transfer opening two routes)
    delta: float
    changed: dict[str, list[Visit]]        # only the routes this move rewrites
    transfer_point: str | None = None

    @property
    def key(self):
        # When the fleet is not part of the objective (Lyu & Yu, Sampaio: pure distance, optional vehicles)
        # a move that opens a vehicle competes on its cost alone.
        return (self.new_vehicle if _PHASE["fleet_lex"] else 0, self.delta)

    @property
    def routes_touched(self) -> tuple:
        return tuple(sorted(self.changed))


def _positions(n: int):
    for i in range(n + 1):
        for j in range(i, n + 1):
            yield i, j


def _apply(visits: list[Visit], first: Visit, second: Visit, i: int, j: int) -> list[Visit]:
    out = list(visits)
    out.insert(i, first)
    out.insert(j + 1, second)
    return out


def _vehicle_class(inst: Instance, k: str) -> tuple:
    v = inst.vehicles[k]
    return (v.capacity, v.start_node, v.end_node, v.fixed_cost, v.cost_per_km,
            tuple(v.allowed_types) if v.allowed_types else None)


def routes_to_scan(inst: Instance, plan: Plan) -> list[str]:
    """Used routes plus ONE empty vehicle per class of identical vehicles (symmetry)."""
    out, seen = [], {}
    for k, visits in plan.routes.items():
        if visits:
            out.append(k)
    for k, visits in plan.routes.items():
        if not visits:
            if k in plan.closed:
                continue
            c = _vehicle_class(inst, k)
            if seen.get(c, 0) < 2:          # two representatives: a transfer may open two routes
                seen[c] = seen.get(c, 0) + 1
                out.append(k)
    return out


def _chain_positions(inst: Instance, st: State, k: str, first: Visit, second: Visit):
    """Positions (i, j) worth testing: stop increasing i once `first` is late at i,
    stop increasing j once `second` is late at j (dates only grow along a route)."""
    rs = st.routes[k]
    veh = inst.vehicles[k]
    n = len(rs.visits)
    b1, b2 = inst.nodes[first.node].tw_end, inst.nodes[second.node].tw_end
    for i in range(n + 1):
        t_prev = (rs.x[i - 1] + _dur(inst, rs.visits[i - 1])) if i > 0 else inst.nodes[veh.start_node].tw_start
        if t_prev > b1 + 1e-9:
            break                                  # monotone in i
        for j in range(i, n + 1):
            if j > i:
                pj = rs.visits[j - 1]
                if rs.x[j - 1] + _dur(inst, pj) > b2 + 1e-9:
                    break                          # monotone in j (dates only grow along the route)
            yield i, j


def scan_route(inst: Instance, st: State, k: str, first: Visit, second: Visit,
               extra_release: float = float("-inf"), use_kernel: bool = True) -> list[tuple[int, int, float, float]]:
    """Feasible insertions of the chain (first, second) in route k: [(i, j, delta, x_second)].
    Uses the compiled kernel; `use_kernel=False` runs the reference Python test (for checks)."""
    rs = st.routes[k]
    veh = inst.vehicles[k]
    req = inst.requests[first.request]
    if not inst.vehicle_allows(veh, req.load_type) or req.quantity > veh.capacity:
        return []
    if not use_kernel:
        out = []
        er = {0: extra_release} if extra_release > float("-inf") else None
        for i, j in _chain_positions(inst, st, k, first, second):
            ok, delta, xs = st.try_insert_chain(k, i, j, first, second, extra_release=er)
            if ok:
                out.append((i, j, delta, xs[-1]))
        return out
    from .kernel import scan_chain
    A = inst.arrays()
    R = rs.numeric(inst)
    n = len(rs.visits)
    q = req.quantity if first.op in (PICKUP, PICK) else -req.quantity
    hc = 0.0
    for v in (first, second):
        if v.op == DROP:
            hc += inst.transfer_points[v.transfer_point].handling_cost * req.quantity
    max_out = (n + 1) * (n + 2) // 2
    cnt, I, J, DL, XL = scan_chain(
        R["nodes"], R["x"], R["l"], R["load"], R["dur"], n,
        A["idx"][veh.start_node], A["idx"][veh.end_node], inst.nodes[veh.start_node].tw_start, rs.l_end,
        A["idx"][first.node], A["idx"][second.node], _dur(inst, first), _dur(inst, second), q,
        first.op == PICK, extra_release, veh.capacity, veh.cost_per_km, veh.fixed_cost, hc,
        A["D"], A["T"], A["a"], A["b"], max_out)
    return [(int(I[c]), int(J[c]), float(DL[c]), float(XL[c])) for c in range(cnt)]


def scan_routes_batched(inst: Instance, st: State, keys: list[str], first: Visit, second: Visit,
                        extra_release: float = float("-inf")) -> list[tuple[str, int, int, float, float]]:
    """Batched version of scan_route over several routes: [(k, i, j, delta, x_second)]."""
    import numpy as np
    from .kernel import scan_routes
    P = st.padded()
    A = inst.arrays()
    req = inst.requests[first.request]
    ALLOWED = np.array([1 if inst.vehicle_allows(inst.vehicles[k], req.load_type) else 0 for k in P["keys"]], np.int64)
    rows = np.array([P["row"][k] for k in keys], np.int64)
    q = req.quantity if first.op in (PICKUP, PICK) else -req.quantity
    hc = 0.0
    for v in (first, second):
        if v.op == DROP:
            hc += inst.transfer_points[v.transfer_point].handling_cost * req.quantity
    cnt, K, I, J, DL, XL = scan_routes(rows, P["NODES"], P["X"], P["L"], P["LOAD"], P["DUR"], P["N"], P["START"], P["END"],
                                       P["START_TW"], P["L_END"], P["CAP"], P["COSTKM"], P["FIXED"], ALLOWED,
                                       A["idx"][first.node], A["idx"][second.node], _dur(inst, first), _dur(inst, second),
                                       q, first.op == PICK, extra_release, hc, A["D"], A["T"], A["a"], A["b"])
    keys_ = P["keys"]
    return [(keys_[int(K[c])], int(I[c]), int(J[c]), float(DL[c]), float(XL[c])) for c in range(cnt)]


def scan_routes_full(inst: Instance, plan: Plan, keys: list[str], first: Visit, second: Visit,
                     extra_release: float = float("-inf")) -> list[tuple[str, int, int, float, float]]:
    """Ablation baseline: test every position by rebuilding the whole schedule (fixed point over all
    routes coupled by transfers), as the PDPT heuristics of the literature do.  Same output as the
    batched kernel scan, without the local test of Proposition 4.5."""
    out = []
    req = inst.requests[first.request]
    base_cost = plan.state.cost() if plan.state else State.build(inst, plan.routes).cost()
    for k in keys:
        veh = inst.vehicles[k]
        if not inst.vehicle_allows(veh, req.load_type):
            continue
        visits = plan.routes[k]
        st0 = plan.state or plan.refresh()
        for i, j in _chain_positions(inst, st0, k, first, second):   # same window pruning as the kernel
                new_route = _apply(visits, first, second, i, j)
                routes = dict(plan.routes); routes[k] = new_route
                try:
                    st = State.build(inst, routes)
                except ValueError:
                    continue
                if not st.feasible_schedule():
                    continue
                # pick must not start before the matching drop end (extra_release) and loads must fit
                rs = st.routes[k]
                if extra_release > float("-inf") and rs.x[i] + 1e-9 < extra_release:
                    continue
                if any(ld > veh.capacity + 1e-9 for ld in rs.load):
                    continue
                out.append((k, i, j, st.cost() - base_cost, rs.x[j + 1]))
    return out


def _scan(inst: Instance, plan: Plan, st: State, keys: list[str], first: Visit, second: Visit, extra_release=float("-inf")):
    if ABLATION["variant"] == "full_reprop":
        return scan_routes_full(inst, plan, keys, first, second, extra_release)
    if ABLATION["variant"] == "python_o1":          # the local test in pure Python (no compiled kernel; this version also applies condition (d))
        out = []
        for k in keys:
            for i, j, delta, xs in scan_route(inst, st, k, first, second, extra_release, use_kernel=False):
                out.append((k, i, j, delta, xs))
        return out
    return scan_routes_batched(inst, st, keys, first, second, extra_release)


def candidate_moves(inst: Instance, plan: Plan, rid: str, radius: float | None, top_first: int = 3,
                    only: set[str] | None = None) -> list[Move]:
    """All feasible insertions of `rid`. With `only`, restrict to moves that touch at least
    one route in `only` (used to refresh a cache after those routes changed)."""
    st = plan.state or plan.refresh()
    req = inst.requests[rid]
    p = Visit(req.pickup, PICKUP, rid)
    d = Visit(req.delivery, DELIVERY, rid)
    moves: list[Move] = []
    scan = routes_to_scan(inst, plan)
    scan_first = [k for k in scan if only is None or k in only]
    # direct
    for k, i, j, delta, _ in _scan(inst, plan, st, scan_first, p, d):
        rs = st.routes[k]
        moves.append(Move(rid, int(not rs.visits), delta, {k: _apply(rs.visits, p, d, i, j)}))
    # transferred
    direct_len = inst.dist(req.pickup, req.delivery)
    for t in inst.transfer_points.values():
        if radius is not None and inst.dist(req.pickup, t.node) + inst.dist(t.node, req.delivery) - direct_len > radius:
            continue
        drop = Visit(t.node, DROP, rid, t.id)
        pick = Visit(t.node, PICK, rid, t.id)
        firsts = []
        for k, i, j, delta, x_drop in _scan(inst, plan, st, scan, p, drop):
            rs = st.routes[k]
            firsts.append((delta + (1e9 if not rs.visits else 0), k, i, j, x_drop + _dur(inst, drop), delta))
        firsts.sort(key=lambda z: z[0])
        for _, k, i, j, drop_end, delta1 in firsts[:top_first]:
            rs = st.routes[k]
            seconds = [k2 for k2 in scan if k2 != k and not (only is not None and k not in only and k2 not in only)]
            if not seconds:
                continue
            for k2, i2, j2, delta2, _ in _scan(inst, plan, st, seconds, pick, d, extra_release=drop_end):
                rs2 = st.routes[k2]
                if True:
                    # storage-time limit: the pick starts at max(arrival, drop_end); checked by the
                    # kernel's XLAST through W only at acceptance, so filter here on the pick start
                    pass_w = True
                    if t.max_storage_time < INF:
                        # recompute the pick start cheaply: it is XLAST of the *first* visit, not returned;
                        # fall back to the Python test for this rare constraint
                        ok2, _, xs2 = st.try_insert_chain(k2, i2, j2, pick, d, extra_release={0: drop_end})
                        pass_w = ok2 and xs2[0] - drop_end <= t.max_storage_time + 1e-9
                    if not pass_w:
                        continue
                    nv = int(not rs.visits) + int(not rs2.visits)
                    moves.append(Move(rid, nv, delta1 + delta2,
                                      {k: _apply(rs.visits, p, drop, i, j), k2: _apply(rs2.visits, pick, d, i2, j2)}, t.id))
    return moves


def _accept_move(inst: Instance, plan: Plan, mv: Move) -> Plan | None:
    """Apply a move; verify resources at the point if capacitated and the whole
    plan by the max-plus schedule (cheap); return the new plan or None."""
    routes = dict(plan.routes)
    routes.update(mv.changed)
    new = Plan(inst, routes, plan.unassigned - {mv.rid}, None, set(plan.closed))
    try:
        st = new.refresh()
    except ValueError:            # circuit
        return None
    if not st.feasible_schedule():
        return None
    if not st.resources_ok():     # S_t / H_t are cumulative, not max-plus linear: checked on every move
        return None
    if inst.params.single_visit_per_point and any(not single_visit_ok(routes[k]) for k in mv.changed):
        return None               # benchmark convention: one visit per transfer point and vehicle
    return new


# --------------------------------------------------------------------------- repair
def regret_repair(inst: Instance, plan: Plan, rng: random.Random, radius: float | None,
                  k_regret: int = 2, noise: float = 0.0, deadline: float | None = None,
                  retries: int = 2) -> Plan:
    """Regret-k repair.  If requests remain in the bank, the repair is retried from the input
    plan with those requests inserted first (a cheap ejection substitute that matters on
    small instances, where a greedy first insertion can lock the only feasible vehicle)."""
    start = plan
    priority: set[str] = set()
    for attempt in range(retries + 1):
        out = _regret_repair_once(inst, start, rng, radius, k_regret, noise, deadline, priority)
        if not out.unassigned or (deadline and time.time() > deadline):
            return out
        if attempt == 0:
            best = out
        elif len(out.unassigned) < len(best.unassigned):
            best = out
        if out.unassigned <= priority:
            break
        priority = priority | set(out.unassigned)
    return best


def _regret_repair_once(inst: Instance, plan: Plan, rng: random.Random, radius: float | None,
                        k_regret: int, noise: float, deadline: float | None, priority: set[str]) -> Plan:
    plan = plan.copy()
    plan.refresh()
    blocked: set[str] = set()
    cache: dict[str, list[Move]] = {}
    dirty: set[str] | None = None            # routes changed since the cache was built
    # insertion-cost noise (Ropke & Pisinger 2006): on half of the repairs the deltas are
    # perturbed by up to `noise` x the median direct length, so that repeated destroy/repair
    # cycles do not rebuild the same plan deterministically
    amp = 0.0
    random_order = False
    if noise:
        u = rng.random()
        if u < 0.4:                        # perturbed insertion costs
            lens = sorted(inst.dist(r.pickup, r.delivery) for r in inst.requests.values())
            amp = 2.0 * noise * lens[len(lens) // 2]
        elif u < 0.6:                      # random insertion order, best position each
            random_order = True
    while plan.unassigned - blocked:
        if deadline and time.time() > deadline:
            return plan
        scored = []
        used = sum(1 for v in plan.routes.values() if v)
        need_open = used < min(inst.params.min_vehicles_used, len(inst.requests))
        for rid in sorted(plan.unassigned):      # fixed order: a seed determines the run (set order is hash-randomised)
            if rid in blocked:
                continue
            if rid not in cache:
                cache[rid] = candidate_moves(inst, plan, rid, radius)
            elif dirty:
                kept = [m for m in cache[rid] if not (set(m.changed) & dirty)]
                cache[rid] = kept + candidate_moves(inst, plan, rid, radius, only=dirty)
            mvs = sorted(cache[rid], key=lambda m: m.key)
            cache[rid] = mvs
            if amp:
                mvs = sorted(mvs, key=lambda m: (m.key[0], m.delta + amp * rng.random()))
            elif random_order and len(mvs) > 1 and rng.random() < 0.3:
                j = min(len(mvs) - 1, 1 + int(rng.random() * 2))
                mvs = [mvs[j]] + mvs[:j] + mvs[j + 1:]      # second or third best move
            if need_open:                 # fleet shortfall: only moves that open a vehicle are eligible
                opening = [m for m in mvs if m.new_vehicle > 0]
                if opening:
                    mvs = opening
            if not mvs:
                blocked.add(rid)          # stays in the request bank for this repair
                continue
            best = mvs[0]
            regret = sum(mvs[m].delta - best.delta for m in range(1, min(k_regret, len(mvs))))
            regret += 1e6 * (mvs[min(k_regret - 1, len(mvs) - 1)].key[0] - best.key[0])
            if noise:
                regret *= 1 + noise * (rng.random() - 0.5)
            if random_order:
                regret = rng.random()
            if rid in priority:
                regret += 1e12
            scored.append((regret, rid, mvs))
        if not scored:
            return plan
        scored.sort(key=lambda z: -z[0])
        _, rid, mvs = scored[0]
        placed = None
        for mv in mvs:
            placed = _accept_move(inst, plan, mv)
            if placed is not None:
                break
        if placed is None:
            blocked.add(rid)
            continue
        scan_prev = set(routes_to_scan(inst, plan))
        plan = placed
        # routes changed by the move, plus empty vehicles newly exposed as representatives
        # of their symmetry class (an empty representative just became a used route)
        dirty = set(mv.changed) | (set(routes_to_scan(inst, plan)) - scan_prev)
        cache.pop(rid, None)
    plan.closed = set()
    return plan


# --------------------------------------------------------------------------- destroy
def destroy_random(inst, plan, q, rng):
    rids = [r for r in inst.requests if r not in plan.unassigned]
    for rid in rng.sample(rids, min(q, len(rids))):
        plan.remove_request(rid)


def destroy_related(inst, plan, q, rng):
    rids = [r for r in inst.requests if r not in plan.unassigned]
    if not rids:
        return
    seed = rng.choice(rids)
    def rel(a, b):
        ra, rb = inst.requests[a], inst.requests[b]
        return inst.dist(ra.pickup, rb.pickup) + inst.dist(ra.delivery, rb.delivery)
    rids.sort(key=lambda r: rel(seed, r))
    for rid in rids[:q]:
        plan.remove_request(rid)


def destroy_worst(inst, plan, q, rng):
    st = plan.state or plan.refresh()
    base = st.cost()
    gains = []
    for rid in [r for r in inst.requests if r not in plan.unassigned]:
        trial = plan.copy()
        trial.remove_request(rid)
        gains.append((base - trial.refresh().cost(), rid))
    gains.sort(reverse=True)
    for _, rid in gains[:q]:
        plan.remove_request(rid)


def destroy_route(inst, plan, q, rng):
    """Fleet-reduction move: empty one of the two smallest routes, close that vehicle for the
    coming repair (so its requests must go elsewhere), and free a few related requests to make room."""
    used = [k for k, v in plan.routes.items() if v]
    if len(used) < 2:
        return
    used.sort(key=lambda k: len(plan.routes[k]))
    k = rng.choice(used[:2])
    victims = list(plan.requests_in(k))
    for rid in victims:
        plan.remove_request(rid)
    plan.closed = {k}
    # related requests from other routes (nearest pickups to the victims)
    others = [r for r in inst.requests if r not in plan.unassigned]
    if victims and others:
        seed_r = inst.requests[victims[0]]
        others.sort(key=lambda r: inst.dist(seed_r.pickup, inst.requests[r].pickup))
        for rid in others[:max(1, q // 2)]:
            plan.remove_request(rid)


def destroy_point(inst, plan, q, rng):
    trs = plan.transfers()
    if not trs:
        return destroy_random(inst, plan, q, rng)
    t = rng.choice(trs)[1]
    for r, tp, _, _ in trs:
        if tp == t:
            plan.remove_request(r)


def destroy_sync(inst, plan, q, rng):
    trs = plan.transfers()
    if not trs:
        return destroy_random(inst, plan, q, rng)
    for r, _, _, _ in rng.sample(trs, min(q, len(trs))):
        plan.remove_request(r)


def destroy_tension(inst, plan, q, rng):
    if not plan.transfers():
        return destroy_random(inst, plan, q, rng)
    sol = plan.to_solution()
    mp = MaxPlusPlan(inst, sol)
    slacks = sorted(mp.transfer_slacks(), key=lambda s: s[2])
    for d, _, _ in slacks[:q]:
        plan.remove_request(sol.routes[mp.g.events[d].route].visits[mp.g.events[d].index].request)


DESTROY = {"random": destroy_random, "related": destroy_related, "worst": destroy_worst,
           "route": destroy_route, "point": destroy_point, "sync": destroy_sync, "tension": destroy_tension}


# --------------------------------------------------------------------------- main loop
@dataclass
class LNSResult:
    solution: Solution
    report: Report
    key: tuple
    iterations: int
    time: float
    history: list[tuple[float, tuple]] = field(default_factory=list)
    operator_stats: dict = field(default_factory=dict)


def solve(inst: Instance, *, time_limit: float = 30.0, max_iter: int = 5000, seed: int = 0,
          radius: float | None = None, destroy_frac: tuple[float, float] = (0.25, 0.5),
          temp0: float = 0.05, cooling: float | None = None, log=None,
          warm_start: Solution | None = None, variant: str = "full") -> LNSResult:
    """`warm_start`: a feasible solution of the same instance (e.g. the no-yard plan) used as
    the initial incumbent, so that offering transfer points can never worsen the result."""
    assert variant in VARIANTS, variant
    ABLATION["variant"] = variant
    ops = {n: f for n, f in DESTROY.items() if not (variant == "no_transfer_ops" and n in ("point", "sync", "tension"))}
    repair_noise = 0.0 if variant == "no_noise" else 0.1
    rng = random.Random(seed)
    t0 = time.time()
    deadline = t0 + time_limit
    if radius is None and inst.transfer_points:
        # default detour filter: a transfer may lengthen a request's path by at most
        # the median direct length (points far off the request's segment are skipped)
        lens = sorted(inst.dist(r.pickup, r.delivery) for r in inst.requests.values())
        radius = lens[len(lens) // 2]
    empty = Plan(inst, {k: [] for k in inst.vehicles}, set(inst.requests))
    cur = regret_repair(inst, empty, rng, radius, deadline=deadline)
    cur_rep, cur_key = _evaluate(inst, cur)
    ws_plan = None
    if warm_start is not None:
        routes = {k: [] for k in inst.vehicles}
        for rt in warm_start.routes:
            routes[rt.vehicle] = list(rt.visits)
        ws = Plan(inst, routes, set(inst.requests) - {v.request for rt in warm_start.routes for v in rt.visits})
        ws_rep, ws_key = _evaluate(inst, ws)
        if ws_rep.feasible:
            ws_plan = ws
            if ws_key < cur_key:
                cur, cur_rep, cur_key = ws, ws_rep, ws_key
    assert cur_rep.feasible, cur_rep.violations
    best, best_key, best_rep = cur.copy(), cur_key, cur_rep
    history = [(time.time() - t0, best_key)]
    weights = {n: 1.0 for n in ops}
    weights["route"] = 2.0
    scores = {n: 0.0 for n in ops}
    uses = {n: 0 for n in ops}
    improvements = {n: 0 for n in ops}
    T = temp0 * max(cur_rep.cost, 1.0)
    it, n = 0, len(inst.requests)
    weighted = inst.params.objective == "weighted"
    phase_switch = t0 + 0.4 * time_limit
    # the fleet-reduction phase only makes sense when fewer vehicles are rewarded
    rewards_fleet = (inst.params.objective != "weighted" or inst.params.weights.get("vehicles", 0) > 0
                     or any(v.fixed_cost > 0 for v in inst.vehicles.values()))
    _PHASE["fleet_first"] = rewards_fleet and inst.params.min_vehicles_used < len(inst.vehicles) and variant != "no_phase1"
    # Moves are ranked by (vehicles opened, cost) except when opening a vehicle is itself rewarded
    # (negative fixed cost: the deadhead convention of Lyu & Yu's PDP-T), where cost alone decides.
    _PHASE["fleet_lex"] = not any(v.fixed_cost < 0 for v in inst.vehicles.values())
    cur_rep, cur_key = _evaluate(inst, cur)
    best_key = cur_key
    while it < max_iter and time.time() < deadline:
        it += 1
        if _PHASE["fleet_first"] and time.time() >= phase_switch:
            # switch to the weighted objective from the best plan found so far
            _PHASE["fleet_first"] = False
            cur = best.copy()
            cur_rep, cur_key = _evaluate(inst, cur)
            best_key = cur_key                   # not an improvement: the history records improvements only
            T = temp0 * max(cur_rep.cost, 1.0)
        name = rng.choices(list(ops), weights=[weights[x] for x in ops])[0]
        q = max(min(2, n), int(rng.uniform(*destroy_frac) * n))
        if n <= 12 and rng.random() < 0.05:
            q = n                          # tiny instances: occasional full rebuild escapes local optima
        cand = cur.copy()
        ops[name](inst, cand, q, rng)
        cand = regret_repair(inst, cand, rng, radius, noise=repair_noise, deadline=deadline)
        uses[name] += 1
        rep, key = _evaluate(inst, cand)
        if not rep.feasible:
            continue                       # defensive: the incremental tests should prevent this
        if key < best_key:
            best, best_key, best_rep = cand.copy(), key, rep
            scores[name] += 3
            improvements[name] += 1
            history.append((time.time() - t0, key))
            if log:
                log(f"it {it} {name}: vehicles {key[0]} cost {rep.cost:.2f} transfers {rep.transfers}")
        elif key < cur_key:
            scores[name] += 1
        worse = key[-1] - cur_key[-1]
        accept = key < cur_key or (key[:-1] <= cur_key[:-1] and rng.random() < math.exp(-max(0.0, worse) / T))
        if accept:
            cur, cur_key, cur_rep = cand, key, rep
        if it == 100 and cooling is None:
            # time-based schedule: estimate the iteration budget and cool so that T ends at 0.2 % of T0
            est = max(200, int(100 * time_limit / max(1e-6, time.time() - t0)))
            cooling = 0.002 ** (1.0 / est)
        T *= (cooling if cooling is not None else 1.0)
        if it % 50 == 0:
            for x in ops:
                if uses[x]:
                    weights[x] = max(0.3, 0.8 * weights[x] + 0.2 * (scores[x] / uses[x] + 0.1))
                scores[x], uses[x] = 0.0, 0
    _PHASE["fleet_first"] = False
    _PHASE["fleet_lex"] = True
    ABLATION["variant"] = "full"
    rep, best_key = _evaluate(inst, best)
    if ws_plan is not None:                      # the warm start is a valid candidate in the final metric
        ws_rep, ws_key = _evaluate(inst, ws_plan)
        if ws_key < best_key:
            best, rep, best_key = ws_plan, ws_rep, ws_key
    sol = best.to_solution()
    assert rep.feasible, rep.violations
    stats = {"improvements": improvements, "unassigned": sorted(best.unassigned)}
    return LNSResult(sol, rep, best_key, it, time.time() - t0, history, stats)
