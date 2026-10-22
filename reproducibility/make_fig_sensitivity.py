# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Figure: delay-sensitivity column A*[., p] drawn on a PORT plan with relay yards.
Writes figures/sens.tex (TikZ) and figures/sens.json (data)."""
import json, os, sys, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdpt.portgen import generate
from pdpt.lns import solve
from pdpt.maxplus import MaxPlusPlan
from pdpt.verifier import verify

n, seed, tl = 20, 9, float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
inst = generate(n, seed=seed, n_yards=2, H=1, S=2)
import os
from pdpt.solution import Solution
SOLF = "figures/sens_solution.json"
if os.path.exists(SOLF):
    sol = Solution.from_dict(json.load(open(SOLF)))
else:
    sol = solve(inst, time_limit=tl, max_iter=10**6, seed=seed).solution
    json.dump(sol.to_dict(), open(SOLF, "w"))
rep = verify(inst, sol)
mp = MaxPlusPlan(inst, sol)
g = mp.g
star = mp.star()
x = mp.x
# choose the source: the pickup event whose sensitivity reaches the most events on other routes
best = None
for e_id, ev in enumerate(g.events):
    if ev.kind != "visit":
        continue
    v = sol.routes[ev.route].visits[ev.index]
    if v.op != "pickup":
        continue
    reached = [(f, star[e_id][f]) for f in range(len(g.events)) if star[e_id][f] > float("-inf") and g.events[f].kind == "visit" and g.events[f].route != ev.route]
    if best is None or len(reached) > len(best[1]):
        best = (e_id, reached)
p, reached = best
mu, breaker = mp.margin(p)
src = g.events[p]
# collect drawing data
routes = []
for ri, rt in enumerate(sol.routes):
    pts = []
    veh = inst.vehicles[rt.vehicle]
    pts.append((inst.nodes[veh.start_node].x, inst.nodes[veh.start_node].y, "depot", None, None, 0.0, veh.start_node, -1))
    for i, v in enumerate(rt.visits):
        e = g.key[(ri, i)]
        lag = star[p][e] if star[p][e] > float("-inf") else None
        pts.append((inst.nodes[v.node].x, inst.nodes[v.node].y, v.op, lag, e == p, x[e], v.node, e))
    pts.append((inst.nodes[veh.end_node].x, inst.nodes[veh.end_node].y, "depot", None, None, 0.0, veh.end_node, -2))
    routes.append(dict(vehicle=rt.vehicle, pts=pts))
yards = [(inst.nodes[t.node].x, inst.nodes[t.node].y, t.id) for t in inst.transfer_points.values()]
data = dict(n=n, seed=seed, syncs=[(a, b) for a, b in g.sync], breaker_event=breaker, source_event=p, cost=rep.cost, vehicles=rep.vehicles_used, transfers=rep.transfers, source=dict(node=src.node, route=sol.routes[src.route].vehicle, x=x[p]),
            margin=mu, breaker=None if breaker is None else g.events[breaker].node, n_reached=len(reached), routes=routes, yards=yards)
json.dump(data, open("figures/sens.json", "w"), indent=1, default=float)

maxlag = max([pt[3] for rt in routes for pt in rt["pts"] if pt[3] is not None] or [1])
# ---------- TikZ: time lanes (one per truck), events at their earliest date x_e
W = 13.0            # cm for the time axis
tmax = max(pt[5] for rt in routes for pt in rt["pts"] if pt[2] != "depot") + 20
X = lambda t: t / tmax * W
used = [rt for rt in routes if len(rt["pts"]) > 2]
lane = {rt["vehicle"]: k for k, rt in enumerate(used)}
Y = lambda k: -1.25 * k
evpos = {}
out = [r"\begin{tikzpicture}[>={Stealth[length=4pt]},font=\scriptsize]"]
for rt in used:
    k = lane[rt["vehicle"]]
    out.append(rf"\draw[gray!50] (0,{Y(k):.2f}) -- ({W:.2f},{Y(k):.2f});")
    out.append(rf"\node[anchor=east,font=\scriptsize\sffamily] at (-0.15,{Y(k):.2f}) {{truck {rt['vehicle'].replace('k','')}}};")
    flip = 0
    for (a, b, op, lag, is_src, t, node, e) in rt["pts"]:
        if op == "depot":
            continue
        evpos[e] = (X(t), Y(k))
        shape = "rectangle" if node.startswith("T") else ("diamond" if node.startswith("yard") else "circle")
        if is_src:
            out.append(rf"\node[star,star points=5,draw=ink,fill=accent,inner sep=2.6pt] at ({X(t):.2f},{Y(k):.2f}) {{}};")
            out.append(rf"\node[below=3pt,font=\tiny\bfseries] at ({X(t):.2f},{Y(k):.2f}) {{$p$ ({node}, {t:.0f} min)}};")
        elif lag is None:
            out.append(rf"\node[{shape},draw=gray!70,fill=white,inner sep=1.6pt] at ({X(t):.2f},{Y(k):.2f}) {{}};")
        else:
            shade = int(20 + 80 * (1 - lag / maxlag))
            ring = ",line width=1pt,draw=accent" if e == data["breaker_event"] else ",draw=accent!70!black"
            out.append(rf"\node[{shape},fill=accent!{shade}!white{ring},inner sep=1.8pt] at ({X(t):.2f},{Y(k):.2f}) {{}};")
            pos = "above=2pt" if flip % 2 == 0 else "below=2pt"
            flip += 1
            out.append(rf"\node[{pos},font=\tiny] at ({X(t):.2f},{Y(k):.2f}) {{{lag:.0f}}};")
for a, b in data["syncs"]:
    if a in evpos and b in evpos:
        (xa, ya), (xb, yb) = evpos[a], evpos[b]
        out.append(rf"\draw[accent2,dashed,thick,->] ({xa:.2f},{ya:.2f}) -- ({xb:.2f},{yb:.2f});")
# axis
yb = Y(len(used) - 1) - 0.7
out.append(rf"\draw[->] (0,{yb:.2f}) -- ({W:.2f},{yb:.2f}) node[right,font=\tiny] {{min}};")
for tick in range(0, int(tmax), 60):
    out.append(rf"\draw ({X(tick):.2f},{yb-0.06:.2f}) -- ({X(tick):.2f},{yb+0.06:.2f}); \node[below,font=\tiny] at ({X(tick):.2f},{yb-0.06:.2f}) {{{tick}}};")
# legend
ly = yb - 0.75
out.append(rf"\node[circle,draw=gray!70,fill=white,inner sep=1.6pt] at (0.2,{ly:.2f}) {{}}; \node[right,font=\tiny] at (0.3,{ly:.2f}) {{customer}};")
out.append(rf"\node[rectangle,draw=gray!70,fill=white,inner sep=1.6pt] at (2.2,{ly:.2f}) {{}}; \node[right,font=\tiny] at (2.3,{ly:.2f}) {{terminal appointment}};")
out.append(rf"\node[diamond,draw=gray!70,fill=white,inner sep=1.6pt] at (5.4,{ly:.2f}) {{}}; \node[right,font=\tiny] at (5.5,{ly:.2f}) {{relay-yard operation}};")
out.append(rf"\draw[accent2,dashed,thick,->] (8.3,{ly:.2f}) -- (8.9,{ly:.2f}); \node[right,font=\tiny] at (8.9,{ly:.2f}) {{transfer arc}};")
out.append(rf"\node[circle,fill=accent!60!white,draw=accent!70!black,inner sep=1.8pt] at (10.6,{ly:.2f}) {{}}; \node[right,font=\tiny] at (10.7,{ly:.2f}) {{reached event, lag in min}};")
out.append(r"\end{tikzpicture}")
open("figures/sens.tex", "w").write("\n".join(out))
print(json.dumps({k: v for k, v in data.items() if k not in ("routes","syncs")}, default=float)[:400])
print("reached", len(reached), "routes with reached events", len({g.events[f].route for f, _ in reached}))
