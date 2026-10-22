# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Statistics for the computational study, from results/campaign_jobs.json.

* Paired Wilcoxon signed-rank tests, instance by instance:
    - PORT: each yard setting against no_yard (cost), per size
    - Sampaio: ours (best of seeds) against the shipped PDPTW solution, per class
    - Ablation: each variant against the full method, per family
* Dolan-More performance profiles on time-to-best for the ablation variants
  (pgfplots data in tables/profile_<family>.dat).
Writes tables/stats.tex (one row per test) and the .dat files.
"""
import json, os, re, statistics as st
from collections import defaultdict
from scipy.stats import wilcoxon

R, OUT = "results", "tables"
os.makedirs(OUT, exist_ok=True)
jobs = json.load(open(f"{R}/campaign_jobs.json")) if os.path.exists(f"{R}/campaign_jobs.json") else {}
rows = []


FAMILY = []          # (family, label, n, mean, wins, p) ; Holm-Bonferroni adjustment within each family
def wtest(label, a, b, family="misc"):
    """Paired test of b < a (one-sided); rows are rendered after the Holm adjustment per family."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 5:
        FAMILY.append((family, label, len(pairs), None, None, None)); return
    d = [100 * (y / x - 1) for x, y in pairs]
    try:
        p = wilcoxon([y - x for x, y in pairs], alternative="less").pvalue
    except ValueError:
        p = 1.0
    wins = sum(1 for x in d if x < -1e-9)
    FAMILY.append((family, label, len(pairs), st.mean(d), wins, p))


def render():
    out = []
    for fam in dict.fromkeys(f for f, *_ in FAMILY):
        tests = [t for t in FAMILY if t[0] == fam and t[5] is not None]
        m = len(tests)
        order = sorted(range(m), key=lambda i: tests[i][5])
        adj = [None] * m; running = 0.0
        for rank, i in enumerate(order):                 # Holm step-down
            running = max(running, min(1.0, (m - rank) * tests[i][5])); adj[i] = running
        k = 0
        for f, label, n, mean, wins, p in FAMILY:
            if f != fam: continue
            if p is None:
                out.append(f"{label} & {n} & {{--}} & -- & -- & --"); continue
            out.append(f"{label} & {n} & {mean:+.2f} & {wins}/{n} & {p:.3g} & {adj[k]:.3g}"); k += 1
    return out


# ---------------- PORT: yard settings vs no yard, best of seeds not needed (one run per seed/setting)
port = defaultdict(dict)
for r in jobs.get("port", []):
    port[(r["n"], r["seed"])][r["setting"]] = r["cost"]
for n in sorted({k[0] for k in port}):
    for s in ("yards_inf", "yards_H1_S2"):           # against the warm-start control (phase 6)
        a = [port[(n, d)].get("no_yard_warm") for d in range(10) if (n, d) in port]
        b = [port[(n, d)].get(s) for d in range(10) if (n, d) in port]
        if any(x is not None for x in a):
            LABS = {"yards_inf": "$S_t=H_t=\\infty$", "yards_H1_S2": "$H_t=1$, $S_t=2$"}
            wtest(f"PORT-{n}: yards {LABS[s]} vs no-yard control", a, b, "port")
    for s in ("yards_inf", "yards_H1_S2", "yards_H1_S1_W60"):
        a = [port[(n, d)].get("no_yard") for d in range(10) if (n, d) in port]
        b = [port[(n, d)].get(s) for d in range(10) if (n, d) in port]
        LABS = {"yards_inf": "$S_t=H_t=\\infty$", "yards_H1_S2": "$H_t=1$, $S_t=2$", "yards_H1_S1_W60": "$H_t=1$, $S_t=1$, $W_t=60$"}
        wtest(f"PORT-{n}: yards {LABS[s]} vs no yard", a, b, "port")
    # between settings: does tightening the yard cost, does removing its limits pay (one-sided, looser setting cheaper)
    for tight, loose in (("yards_H1_S1_W60", "yards_H1_S2"), ("yards_H1_S2", "yards_inf")):
        a = [port[(n, d)].get(tight) for d in range(10) if (n, d) in port]
        b = [port[(n, d)].get(loose) for d in range(10) if (n, d) in port]
        wtest(f"PORT-{n}: yards {LABS[loose]} vs {LABS[tight]}", a, b, "port")

# ---------------- Sampaio: ours vs RP solution, per class, best of seeds
sa = defaultdict(lambda: defaultdict(list))
for r in jobs.get("sampaio", []):
    if r.get("metric", "exact") != "integer":          # phase 8: the published metric
        continue
    m = re.match(r"SA(\d+)-(\dT)-(\d+)_(\w+)-(\d+)", r["instance"])
    # only the 50-request files ship a complete PDPTW solution (75/100: partial routes), so the paired
    # test against the shipped solution is restricted to n = 50
    if m and not r["unassigned"] and m.group(1) == "50":
        sa[f"SA{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"][m.group(5)].append((r["warm_cost"], r["cost"]))
for cls in sorted(sa):
    a = [v[0][0] for v in sa[cls].values()]
    b = [min(c for _, c in v) for v in sa[cls].values()]
    wtest(f"{cls}: ours vs RP", a, b, "sampaio")

# ---------------- Ablation: variant vs full, per family (mean over seeds per instance)
ab = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
for r in jobs.get("ablation", []):
    if not r["unassigned"]:
        ab[r["family"]][r["instance"]][r["variant"]].append(r["cost"])
for fam in sorted(ab):
    for v in ("no_transfer_ops", "no_phase1", "no_noise", "python_o1", "full_reprop"):
        a, b = [], []
        for inst, d in ab[fam].items():
            if "full" in d and v in d:
                a.append(st.mean(d["full"])); b.append(st.mean(d[v]))
        VLAB = {"no_transfer_ops": "no transfer ops", "no_phase1": "no phase 1", "no_noise": "no noise", "python_o1": "Python local test", "full_reprop": "full re-propagation"}
        wtest(f"{fam}: full vs {VLAB[v]}", b, a, "ablation")   # tests full < variant; negative = full (first-named) cheaper

rows = render()
open(f"{OUT}/stats.tex", "w").write(" \\\\\n".join(rows) + "\n")   # no trailing \\: main.tex adds it

# ---------------- performance profiles (Dolan-More) on cost, ablation variants
for fam in sorted(ab):
    VAR = ["full", "no_transfer_ops", "no_phase1", "no_noise", "python_o1", "full_reprop"]
    ratios = {v: [] for v in VAR}
    for inst, d in ab[fam].items():
        best = min(st.mean(c) for c in d.values())
        for v in VAR:
            if v in d:
                ratios[v].append(st.mean(d[v]) / best)
    taus = [1 + 0.002 * i for i in range(0, 101)]
    lines = ["tau " + " ".join(VAR)]
    for tau in taus:
        lines.append(f"{tau:.3f} " + " ".join(f"{(sum(1 for x in ratios[v] if x <= tau) / len(ratios[v])) if ratios[v] else 0:.3f}" for v in VAR))
    open(f"{OUT}/profile_{fam}.dat", "w").write("\n".join(lines) + "\n")
print(f"{len(rows)} tests written; profiles for {sorted(ab)}")
