# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Generate LaTeX table bodies from results/*.json (no hand-copied numbers)."""
import json, statistics as st, os
R = "results"; OUT = "tables"; os.makedirs(OUT, exist_ok=True)
def w(name, s):
    s = s.rstrip()
    if s.endswith("\\\\"): s = s[:-2].rstrip()
    open(f"{OUT}/{name}.tex", "w").write(s + "\n")
def f1(x): return f"{x:.1f}"
SET = [("no_yard", "No yard"), ("yards_inf", r"Yards, $S_t=H_t=\infty$"),
       ("yards_H1_S2", r"Yards, $H_t=1$, $S_t=2$"), ("yards_H1_S1_W60", r"Yards, $H_t=1$, $S_t=1$, $W_t=60$")]

# ---------- Table: TT-14 (LNS 10 seeds vs known optimum, thesis)
camp = json.load(open(f"{R}/tt14_campaign.json"))
ca = json.load(open(f"{R}/campaign_all.json"))
rows = []
for i in range(1, 17):
    T = next(r for r in camp if r["instance"] == f"E{i}" and r["transfer"])
    D = next(r for r in camp if r["instance"] == f"E{i}" and not r["transfer"])
    tT = [x["t_best"] for x in ca[f"tt14/E{i}/T"]]; tD = [x["t_best"] for x in ca[f"tt14/E{i}/D"]]
    note = ""
    diff = D["dist_best"] - D["known_dist"]
    if diff < -0.1: note = "improves thesis"
    elif diff > 0.1: note = "thesis $<$ optimum"
    elif abs(diff) > 0.005: note = "rounding"
    sav = 100 * (1 - T["dist_best"] / D["dist_best"])
    rows.append(f"E{i} & {T['n']} & {T['veh_best']} & {T['dist_best']:.2f} & {max(tT):.2f} & {D['veh_best']} & {D['dist_best']:.2f} & {max(tD):.2f} & {D['known_dist']:.2f} & {sav:.1f} & {note} \\\\")
w("tt14", "\n".join(rows))

# ---------- Table: certification MILP + CP-SAT on TT-14
milp = {r["instance"]: r for r in json.load(open(f"{R}/milp_tt14_eps.json"))}       # the model as stated (margin 0.01)
milp0 = {r["instance"]: r for r in json.load(open(f"{R}/milp_tt14_eps0.json"))}     # margin 0: relaxation
cp = {}
for fn in ("cpsat_tt14_full.json", "cpsat_tt14_b.json"):
    if os.path.exists(f"{R}/{fn}"):
        for r in json.load(open(f"{R}/{fn}")):
            # keep the certifying run when one exists (both runs use the same model; workers 1 or 2)
            if r["instance"] not in cp or (r["status"] == "OPTIMAL" and cp[r["instance"]]["status"] != "OPTIMAL"):
                cp[r["instance"]] = r
rows = []
def milp_cols(m):
    if not m:
        return ["--"] * 4
    ms = "optimal" if m["status"].startswith("Opt") else "time limit"
    mg = "--" if m.get("gap") is None else ("0" if m["gap"] == 0 else f"{100*m['gap']:.1f}\\%")
    mt = f"{m['time']:.0f}" if m["time"] < 600 else "600"
    v = m.get("verified")
    ok = "--" if v is None else ("yes" if v else "no")
    return [ms, mg, mt, ok]
for i in range(1, 17):
    e = f"E{i}"; c = cp.get(e)
    if c:
        cs = c["status"].lower(); ct = f"{c['time']:.0f}" if c["time"] >= 1 else "<1"
    else:
        cs = ct = "--"
    rows.append(" & ".join([e] + milp_cols(milp.get(e)) + milp_cols(milp0.get(e)) + [cs, ct]) + " \\\\")
w("certif_tt14", "\n".join(rows))

# ---------- Table: Li & Lim
rows = []
for k in ("lc101", "lr101", "lrc101"):
    d = ca[f"lilim/{k}"]; bk = d["best_known"]; runs = d["runs"]
    hits = sum(1 for r in runs if r["veh"] == bk[0] and abs(r["dist"] - bk[1]) < 0.01)
    tb = [r["t_best"] for r in runs]
    rows.append(f"{k} & {bk[0]} & {bk[1]:.2f} & {hits}/10 & {min(tb):.1f} & {st.mean(tb):.1f} & {max(tb):.1f} \\\\")
w("lilim", "\n".join(rows))

# ---------- PORT per-seed table (n=20) and summaries n=20,30,50
def load_port(n):
    jobs_ = json.load(open(f"{R}/campaign_jobs.json")) if os.path.exists(f"{R}/campaign_jobs.json") else {}
    P = {(r["seed"], r["setting"]): r for r in jobs_.get("port", []) if r["n"] == n}
    if P and all((s, k) in P for s in range(10) for k, _ in SET):
        return P                      # campaign results (all four settings present)
    if n == 20:
        rows = json.load(open(f"{R}/port20_capacity_v4.json"))
        return {(r["seed"], r["setting"]): r for r in rows}
    if n == 30:
        return {(int(k.split("/")[1]), k.split("/")[2]): v for k, v in ca.items() if k.startswith("port30/")}
    if n == 50:
        return {(int(k.split("/")[0]), k.split("/")[1]): v for k, v in json.load(open(f"{R}/port50_warm.json")).items()}
def summary(n):
    P = load_port(n); seeds = sorted({s for s, _ in P})
    out = []
    for key, lab in SET:
        tr = sum(P[(s, key)]["vehicles"] for s in seeds)
        if key == "no_yard":
            out.append(f"{lab} & {tr} & {{--}} & -- & -- & -- \\\\"); continue
        ch = [100 * (P[(s, key)]["cost"] / P[(s, "no_yard")]["cost"] - 1) for s in seeds]
        sav = sum(1 for c in ch if c < -1e-9); worse = sum(1 for c in ch if c > 1e-9)
        ntr = sum(P[(s, key)]["transfers"] for s in seeds)
        out.append(f"{lab} & {tr} & {st.mean(ch):+.1f} & ${min(ch):+.1f}$ / ${max(ch):+.1f}$ & {sav}/{len(seeds)} & {ntr} \\\\")
    return "\n".join(out), P, seeds
for n in (20, 30, 50, 100):
    s, P, seeds = summary(n); w(f"port{n}_summary", s)
    if n == 20:
        rows = []
        for sd in seeds:
            cells = [f"{sd}"]
            base = P[(sd, "no_yard")]["cost"]
            for key, _ in SET:
                r = P[(sd, key)]
                c = f"{r['vehicles']} & {r['cost']:.0f}"
                if key != "no_yard":
                    c += f" & {r['transfers']} & {100*(r['cost']/base-1):+.1f}"
                cells.append(c)
            rows.append(" & ".join(cells) + " \\\\")
        w("port20_seeds", "\n".join(rows))
# ---------- CP-SAT PORT no-yard certification vs the search (campaign: 1800 s, n = 20 and 30)
_cj = json.load(open(f"{R}/campaign_jobs.json")).get("cpsat", []) if os.path.exists(f"{R}/campaign_jobs.json") else []
if _cj:
    # two tables from the same certificates: the method paper compares them with its own no-yard runs (days 0-9, phases 1-2);
    # the factorial-study paper with the cold-start no-yard plans of the factorial study (days 0-19, phase 7), which are its reference
    _p7 = {(r["n"], r["seed"]): r for r in json.load(open(f"{R}/campaign_jobs.json")).get("port7", []) if r["setting"] == "no_yard"}
    def cp_rows(plan_of):
        rows = []
        for n in (20, 30):
            for r in sorted((r for r in _cj if r["setting"] == "no_yard" and r["n"] == n), key=lambda r: r["seed"]):
                l = plan_of(n, r["seed"])
                if l is None:
                    continue
                cp = r["cost"] if r["cost"] is not None else float("nan")
                gap = 100 * (l["cost"] - cp) / cp if r["cost"] else float("nan")
                stat = r["status"].lower() + ("" if r["status"] == "OPTIMAL" else f" ({100*(cp/r['bound']-1):.0f}\\,\\% gap)")
                rows.append(f"{n} & {r['seed']} & {stat} & {cp:.1f} & {r['time']:.0f} & {l['vehicles']} & {l['cost']:.1f} & {gap:+.1f} \\\\")
        return rows
    _PA = {n: load_port(n) for n in (20, 30)}
    w("cpsat_port20", "\n".join(cp_rows(lambda n, d: _PA[n].get((d, "no_yard")))))          # the method paper: days 0-9
    w("cpsat_port7", "\n".join(cp_rows(lambda n, d: _p7.get((n, d)))))                      # the factorial-study paper: days 0-19
elif os.path.exists(f"{R}/cpsat_port20.json"):
    P = load_port(20)
    rows = []
    for r in json.load(open(f"{R}/cpsat_port20.json")):
        if r["setting"] != "no_yard": continue
        l = P[(r["seed"], "no_yard")]
        gap = 100 * (l["cost"] - r["cp_cost"]) / r["cp_cost"] if r["cp_cost"] else float("nan")
        rows.append(f"{r['seed']} & {r['status'].lower()} & {r['cp_cost']:.1f} & {r['time']} & {l['vehicles']} & {l['cost']:.1f} & {gap:+.1f} \\\\")
    w("cpsat_port20", "\n".join(rows))
print("tables written:", sorted(os.listdir(OUT)))

# ---------- warm-start control (phase 6): no yard, warm-started with the same extra budget as the yard runs
_cj = json.load(open(f"{R}/campaign_jobs.json")) if os.path.exists(f"{R}/campaign_jobs.json") else {}
ctrl = {(r["n"], r["seed"]): r for r in _cj.get("port", []) if r["setting"] == "no_yard_warm"}
lines = []
for n in (20, 30, 50, 100):
    P = load_port(n); seeds = [d for d in range(10) if (n, d) in ctrl]
    if not seeds: continue
    base = [P[(d, "no_yard")]["cost"] for d in seeds]; c = [ctrl[(n, d)]["cost"] for d in seeds]
    dctrl = [100 * (y / x - 1) for x, y in zip(base, c)]
    cells = [f"{n} & {len(seeds)} & {st.mean(dctrl):+.2f} & {sum(1 for v in dctrl if v < -1e-9)}"]
    for key in ("yards_inf", "yards_H1_S2"):
        y = [P[(d, key)]["cost"] for d in seeds]
        dy = [100 * (a / b - 1) for a, b in zip(y, c)]           # yard run against the control
        it = st.mean(P[(d, key)]["it"] for d in seeds) / st.mean(ctrl[(n, d)]["it"] for d in seeds)
        cells.append(f"{st.mean(dy):+.2f} & {sum(1 for v in dy if v < -1e-9)}/{len(seeds)} & {it:.2f}")
    lines.append(" & ".join(cells) + " \\\\")
w("port_control", "\n".join(lines) if lines else "\\todo{phase 6 pending}" + " &" * 9 + " \\\\")

# ---------- figure data
lines = ["n setting trucks_saved_pct cost_mean"]
for n in (20, 30, 50, 100):
    P = load_port(n); seeds = sorted({s for s, _ in P})
    base = sum(P[(s, "no_yard")]["vehicles"] for s in seeds)
    for j, (key, _) in enumerate(SET[1:]):
        tr = sum(P[(s, key)]["vehicles"] for s in seeds)
        ch = st.mean(100 * (P[(s, key)]["cost"] / P[(s, "no_yard")]["cost"] - 1) for s in seeds)
        lines.append(f"{n} {j} {100*(base-tr)/base:.1f} {ch:.2f}")
w("port_fig.dat"[:-4], "\n".join(lines)); os.replace(f"{OUT}/port_fig.tex", f"{OUT}/port_fig.dat")
P = load_port(50); seeds = sorted({s for s, _ in P})
lines = ["seed inf h1s2 s1w60 trucks_base"]
for s in seeds:
    b = P[(s, "no_yard")]["cost"]
    lines.append(f"{s} " + " ".join(f"{100*(P[(s,k)]['cost']/b-1):.2f}" for k, _ in SET[1:]) + f" {P[(s,'no_yard')]['vehicles']}")
open(f"{OUT}/port50_seeds.dat", "w").write("\n".join(lines))
# per-seed table n=50
rows = []
for sd in seeds:
    base = P[(sd, "no_yard")]["cost"]; cells = [f"{sd}"]
    for key, _ in SET:
        r = P[(sd, key)]; c = f"{r['vehicles']} & {r['cost']:.0f}"
        if key != "no_yard": c += f" & {r['transfers']} & {100*(r['cost']/base-1):+.1f}"
        cells.append(c)
    rows.append(" & ".join(cells) + " \\\\")
w("port50_seeds", "\n".join(rows))

# ======================================================================= public sets (Table 3)
import re, statistics as st
jobs = json.load(open(f"{R}/campaign_jobs.json")) if os.path.exists(f"{R}/campaign_jobs.json") else {}
# ---- Lyu & Yu: prefer campaign jobs, else the sequential file
ly_rows = []
for r in jobs.get("lyuyu", []):
    ly_rows.append(dict(instance=r["instance"], set=r["set"], seed=r["seed"], cost=r["cost"], unassigned=r["unassigned"], t_best=r["t_best"]))
if not ly_rows and os.path.exists(f"{R}/lyuyu.json"):
    for r in json.load(open(f"{R}/lyuyu.json")).values():
        ly_rows.append(dict(instance=r["instance"], set=r["set"], seed=r["seed"], cost=r["cost"], unassigned=r["unassigned"], t_best=r["t_best"]))
pub = {}
if ly_rows and not os.path.exists("ext/lyuyu/Results/Results-PDPTWT.txt"):
    raise SystemExit("Lyu & Yu results present but ext/lyuyu/Results missing: extract ext_archives (scripts/remote_setup.sh)")
if os.path.exists("ext/lyuyu/Results/Results-PDPTWT.txt"):
    from pdpt.converters import lyu_yu_results
    for f in ("Results-PDPTWT.txt", "Gurobi-PDPT-Lyu.txt", "Gurobi-PDPT-Rais.txt"):
        for k, v in lyu_yu_results(f"ext/lyuyu/Results/{f}").items():
            pub.setdefault(k, {}).update(v)
def ly_group(name):
    m = re.match(r"(\d+)R-(\d)K-(\d)T-(\d+)([SML])-\d+", name)
    if m: return f"PDPTW-T {m.group(1)}R {m.group(3)}T"
    m = re.match(r"PDPT-R(\d+)-K(\d)-T(\d)-Q100-\d+", name)
    if m: return f"PDP-T R{m.group(1)} K{m.group(2)} T{m.group(3)}"
    return name
best = {}
for r in ly_rows:                               # best over seeds per instance (runs serving every request)
    if r["unassigned"]: continue
    b = best.get(r["instance"])
    if b is None or r["cost"] < b["cost"]: best[r["instance"]] = r
# per instance: certified optimum = min over models that proved optimality; else published value = min over
# models with a value (time limit); else open.  Hits and gaps are measured against the best of the seeds.
LY = dict(cert=0, hit=0, tl=0, better=0, open=0, solved=0, below=0)
groups = {}
for name, models in pub.items():
    g = groups.setdefault(ly_group(name), dict(n=0, cert=0, hit=0, tl=0, better=0, open=0, solved=0, gaps=[], t=[]))
    g["n"] += 1
    r = best.get(name)
    opt = [ub for st, ub, _, _ in models.values() if st == "OPTIMAL" and ub is not None]
    vals = [ub for st, ub, _, _ in models.values() if ub is not None]
    if r: g["t"].append(r["t_best"])
    if opt:
        g["cert"] += 1; LY["cert"] += 1
        if r:
            gap = 100 * (r["cost"] / min(opt) - 1); g["gaps"].append(gap)
            if gap < -0.05: LY["below"] += 1
            elif gap <= 0.05: g["hit"] += 1; LY["hit"] += 1
    elif vals:
        g["tl"] += 1; LY["tl"] += 1
        if r:
            gap = 100 * (r["cost"] / min(vals) - 1); g["gaps"].append(gap)
            if gap < -0.05: g["better"] += 1; LY["better"] += 1
    else:
        g["open"] += 1; LY["open"] += 1
        if r: g["solved"] += 1; LY["solved"] += 1
def gkey(k):
    m = re.findall(r"\d+", k); return (k.split()[0], [int(x) for x in m])
lines = []
for k in sorted(groups, key=gkey):
    g = groups[k]
    gm = f"{st.mean(g['gaps']):.2f}" if g["gaps"] else "{--}"; gx = f"{max(g['gaps']):.2f}" if g["gaps"] else "{--}"
    lines.append(f"{k} & {g['n']} & {g['cert']} & {g['hit']} & {g['tl']} & {g['better']} & {g['open']} & {g['solved']} & {gm} & {gx} & {st.mean(g['t']):.1f} \\\\")
w("ly_summary", "\n".join(lines) if lines else "\\todo{campaign pending}" + " &" * 10 + " \\\\")
json.dump(LY, open(f"{OUT}/ly_totals.json", "w"))
print("LY totals:", LY)
# ---- Sampaio: class means vs published Tables 5-8
# Phase 8 rows (metric "integer": distances and times rounded up, the published metric) give the paper's table;
# the phase 2-3 rows (metric "exact") give the supplement's table, kept for the record with both bases.
pubsa = json.load(open(f"{R}/published_sampaio.json")) if os.path.exists(f"{R}/published_sampaio.json") else {}
def sampaio_table(metric, both_bases):
    sa_rows = [r for r in jobs.get("sampaio", []) if r.get("metric", "exact") == metric]
    cls = {}
    for r in sa_rows:
        if r.get("unassigned"): continue
        m = re.match(r"SA(\d+)-(\dT)-(\d+)_(\w+)-(\d+)", r["instance"])
        if not m: continue
        key = f"SA{m.group(1)}-{m.group(2)}-{m.group(3)}_{m.group(4)}"
        c = cls.setdefault(key, {})
        inst = m.group(5)
        b = c.get(inst)
        if b is None or r["cost"] < b["cost"]: c[inst] = r
    lines = []
    order = sorted(cls, key=lambda k: (int(re.match(r"SA(\d+)", k).group(1)), k))
    for key in order:
        insts = cls[key]; p = pubsa.get(key)
        if not p: continue
        cost = st.mean(v["cost"] for v in insts.values())
        warmc = st.mean(v["warm_cost"] for v in insts.values()) if all(v.get("warm_cost") for v in insts.values()) else None
        partial = not key.startswith("SA50")               # 75- and 100-request files ship only part of the RP solution
        dS = 100 * (cost / warmc - 1) if warmc and not partial else None
        drivers = st.mean(v.get("drivers", v.get("vehicles")) for v in insts.values())
        tr = st.mean(v["transfers"] for v in insts.values())
        dD = 100 * (cost / p["rp_cost"] - 1); dV = 100 * (drivers / p["rp_veh"] - 1)
        cells = [key.replace("_", "-"), str(len(insts)), f"{p['rp_cost']:.1f}"]
        if both_bases:
            cells.append("{--}" if partial else f"{warmc:.1f}")
        cells += [f"{p['best_dD']:+.1f}", f"{p['avg_dD']:+.1f}", f"{dD:+.1f}"]
        if both_bases:
            cells.append("{--}" if dS is None else f"{dS:+.1f}")
        cells += [f"{p['best_dV']:+.1f}", f"{dV:+.1f}", f"{p['best_trans']:.0f}", f"{tr:.0f}"]
        lines.append(" & ".join(cells) + " \\\\")
    return lines
lines = sampaio_table("integer", False)
w("sa_summary", "\n".join(lines) if lines else "\\todo{campaign pending}" + " &" * 9 + " \\\\")
w("sa_summary_exact", "\n".join(sampaio_table("exact", True)))
# ---- ablation (Table 4)
ab = jobs.get("ablation", [])
VAR = ["full", "no_transfer_ops", "no_phase1", "no_noise", "python_o1", "full_reprop"]
LAB = {"full": "Full method", "no_transfer_ops": "No transfer-native destroy", "no_phase1": "No fleet-reduction phase",
       "no_noise": "No repair diversification", "python_o1": "Prop.~\\ref{prop:insertion} in pure Python", "full_reprop": "Full re-propagation (Python)"}
if ab:
    fams = [f for f in ("port30", "port50", "lyuyu", "sampaio") if any(r["family"] == f for r in ab)]
    ref = {}
    for r in ab:
        if r["variant"] == "full": ref.setdefault((r["family"], r["instance"]), []).append(r["cost"])
    lines = []
    for v in VAR:
        cells = [LAB[v]]
        for fam in fams:
            allr = [r for r in ab if r["variant"] == v and r["family"] == fam]
            rs = [r for r in allr if not r["unassigned"]]
            its = st.mean(r["it"] / r["tl"] for r in allr) if allr else 0.0
            gaps = [100 * (r["cost"] / st.mean(ref[(fam, r["instance"])]) - 1) for r in rs if (fam, r["instance"]) in ref]
            if len(rs) < len(allr) // 2:          # the variant did not even complete the construction
                cells.append(f"{{n/a}} & {its:.1f}"); continue
            cells.append(f"{st.mean(gaps):+.2f} & {its:.1f}")
        lines.append(" & ".join(cells) + " \\\\")
    w("ablation", "\n".join(lines)); open(f"{OUT}/ablation_fams.tex", "w").write(" & ".join(f"\\multicolumn{{2}}{{c}}{{{f}}}" for f in fams) + "\n")
else:
    w("ablation", "\\todo{phase 4 pending}" + " &" * 8 + " \\\\"); open(f"{OUT}/ablation_fams.tex", "w").write("\\multicolumn{2}{c}{PORT-30} & \\multicolumn{2}{c}{PORT-50} & \\multicolumn{2}{c}{LY PDP-T R20} & \\multicolumn{2}{c}{SA-50 long}\n")
# ---- sensitivity (phase 5): gap of each configuration to the baseline, per family
se = jobs.get("sens", [])
CONF = [((1.0, 0.25, 0.5), "Baseline: $\\rho=$ median, destroy 25--50\\,\\%"), ((0.5, 0.25, 0.5), "$\\rho=0.5\\times$ median"),
        ((2.0, 0.25, 0.5), "$\\rho=2\\times$ median"), ((1.0, 0.15, 0.4), "destroy 15--40\\,\\%"), ((1.0, 0.35, 0.6), "destroy 35--60\\,\\%")]
if se:
    fams = sorted({r["family"] for r in se})
    base = {}
    for r in se:
        if (r["rho_mult"], r["dlo"], r["dhi"]) == CONF[0][0]: base.setdefault((r["family"], r["instance"]), []).append(r["cost"])
    lines = []
    for conf, lab in CONF:
        cells = [lab]
        for fam in fams:
            rs = [r for r in se if (r["rho_mult"], r["dlo"], r["dhi"]) == conf and r["family"] == fam and not r["unassigned"]]
            gaps = [100 * (r["cost"] / st.mean(base[(fam, r["instance"])]) - 1) for r in rs if (fam, r["instance"]) in base]
            tr = st.mean(r["transfers"] for r in rs) if rs else 0
            cells.append(f"{st.mean(gaps):+.2f} & {max(gaps):+.2f} & {tr:.1f}" if gaps else "-- & -- & --")
        lines.append(" & ".join(cells) + " \\\\")
    w("sens", "\n".join(lines))
else:
    w("sens", "\\todo{phase 5 pending}" + " &" * 6 + " \\\\")
print("public-set tables written")

# ---------- phase 7 (pre-registered factorial study): corner cells against the control, and the dwell/storage curves
if os.path.exists(f"{R}/phase7_summary.json"):
    S7 = json.load(open(f"{R}/phase7_summary.json"))
    P7 = {}
    for r in json.load(open(f"{R}/campaign_jobs.json")).get("port7", []):
        P7.setdefault((r["n"], r["seed"]), {})[r["setting"]] = r
    CORNERS = [("yards_Hinf_Sinf_Winf", "$S_t=H_t=W_t=\\infty$"), ("yards_H1_S2_Winf", "$H_t=1$, $S_t=2$, $W_t=\\infty$"),
               ("yards_H1_S2_W240", "$H_t=1$, $S_t=2$, $W_t=240$"), ("yards_H1_S2_W120", "$H_t=1$, $S_t=2$, $W_t=120$"),
               ("yards_H1_S2_W60", "$H_t=1$, $S_t=2$, $W_t=60$"), ("yards_H1_S1_W60", "$H_t=1$, $S_t=1$, $W_t=60$"),
               ("yards_H1_S2_W30", "$H_t=1$, $S_t=2$, $W_t=30$")]
    for n in (20, 30, 50):
        lines = []
        days = sorted(k for (nn, k) in P7 if nn == n)
        ctrl = sum(P7[(n, k)]["no_yard_warm"]["vehicles"] for k in days)
        for key, lab in CORNERS:
            c = S7["closed"]["sizes"][str(n)]["map"][key]; w_ = S7["raw"]["sizes"][str(n)]["map"][key]
            tr = sum(P7[(n, k)]["no_yard_warm"]["vehicles"] - P7[(n, k)][key]["vehicles"] for k in days)
            tf = sum(P7[(n, k)][key]["transfers"] for k in days)
            lines.append(f"{lab} & {w_['delta_cost']:+.2f} & {w_['wins']}/{w_['days']} & {tr} & {tf} & {c['delta_cost']:+.2f} & {c['wins']}/{c['days']} & "
                         f"{c['p']:.2g} & {c['p_holm']:.2g} \\\\")
        w(f"port7_corners_{n}", "\n".join(lines))
        w(f"port7_ctrl_{n}", f"{len(days)} days, {ctrl} trucks in the control plans")
    # curves: closed Delta against the control, dwell axis at (H=1,S=2) and storage axis at (H=1,W=inf)
    out = ["w d20 d30 d50"]
    for wv in ("30", "60", "120", "240", "inf"):
        out.append(f"{wv} " + " ".join(f"{S7['closed']['sizes'][str(n)]['map'][f'yards_H1_S2_W{wv}']['delta_cost']:.3f}" for n in (20, 30, 50)))
    open(f"{OUT}/port7_dwell.dat", "w").write("\n".join(out) + "\n")
    out = ["s d20 d30 d50"]
    for sv in ("1", "2", "3", "inf"):
        out.append(f"{sv} " + " ".join(f"{S7['closed']['sizes'][str(n)]['map'][f'yards_H1_S{sv}_Winf']['delta_cost']:.3f}" for n in (20, 30, 50)))
    open(f"{OUT}/port7_storage.dat", "w").write("\n".join(out) + "\n")
    print("phase 7 tables written")
    # saturation, selected cells (dwell axis, storage axis, handling at S=inf)
    SEL = [f"yards_H1_S2_W{w_}" for w_ in ("30", "60", "120", "240", "inf")] + [f"yards_H1_S{s_}_Winf" for s_ in ("1", "3", "inf")] + ["yards_H2_Sinf_Winf", "yards_Hinf_Sinf_Winf"]
    lab = lambda s: s.replace("yards_", "").replace("_", ", ").replace("H", "$H_t{=}").replace("S", "$S_t{=}").replace("W", "$W_t{=}").replace("inf", "\\infty").replace(", ", "$, ") + "$"
    for n in (20, 30, 50):
        lines = []
        for key in SEL:
            v = S7["closed"]["sizes"][str(n)]["saturation"][key]
            lines.append(f"{lab(key)} & {v['transfers_mean']:.1f} & {v['peak_storage_mean']:.2f} & {v['peak_storage_max']:.0f} & {v['peak_handling_max']} & {v['max_dwell_mean']:.0f} & {v['max_dwell_max']:.0f} \\\\")
        w(f"phase7_saturation_sel_{n}", "\n".join(lines))
    # verdicts of the pre-registered contrasts under the three treatments (raw, pre-registered closure, pool closure)
    V = {"different": "d", "equivalent": "e", "inconclusive": "i"}
    lab = lambda s: s.replace("yards_", "").replace("_", " ").replace("inf", "$\\infty$")
    lines = []
    fam_names = {"i_handling": "i", "ii_storage": "ii", "iii_dwell": "iii"}
    for fam in ("i_handling", "ii_storage", "iii_dwell"):
        for k in range(len(S7["closed"]["sizes"]["20"]["contrasts"][fam])):
            rec = S7["closed"]["sizes"]["20"]["contrasts"][fam][k]
            cells = []
            for n in ("20", "30", "50"):
                for mode in ("raw", "closed", "pool"):
                    r = S7[mode]["sizes"][n]["contrasts"][fam][k]
                    cells.append(f"{r['mean']:+.2f}\\,{V[r['verdict']]}")
            lines.append(f"{fam_names[fam]} & {lab(rec['a'])} $\\to$ {lab(rec['b'])} & " + " & ".join(cells) + " \\\\")
    cells = []
    for n in ("20", "30", "50"):
        for mode in ("raw", "closed", "pool"):
            r = S7[mode]["sizes"][n]["contrasts"]["iv_interaction"]
            cells.append(f"{r['mean']:+.2f}\\,{V[r['verdict']]}")
    lines.append("iv & interaction (see text) & " + " & ".join(cells) + " \\\\")
    w("phase7_verdicts", "\n".join(lines))
    print("phase 7 verdict table written")

# ---------- dwell per transfer on the unbounded cells (the factorial-study paper, finding (ii); scripts/dwell_per_transfer.py)
if os.path.exists(f"{R}/phase7_dwell.json"):
    _dw = json.load(open(f"{R}/phase7_dwell.json"))
    _lab = {"yards_H1_S2_Winf": "$H_t{=}1$, $S_t{=}2$, $W_t{=}\\infty$", "yards_Hinf_Sinf_Winf": "$H_t{=}\\infty$, $S_t{=}\\infty$, $W_t{=}\\infty$"}
    rows = []
    for key in sorted(_dw, key=lambda k: (k.split("/")[1], int(k.split("/")[0]))):
        n, cell = key.split("/"); d = _dw[key]
        rows.append(f"{n} & {_lab[cell]} & {d['transfers']} & {d['median']:.0f} & {d['mean']:.0f} & {100*d['share_le_30']:.1f} & {100*d['share_le_120']:.0f} \\\\")
    w("phase7_dwell", "\n".join(rows))
