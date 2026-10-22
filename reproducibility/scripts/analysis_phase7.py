# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Pre-registered analysis of campaign phase 7 (factorial study of the yard parameters).

Protocol: CAMPAIGN.md, section "Phase 7 (pre-registered)".  This script is the analysis fixed before the
campaign; it reads results/campaign_jobs.json (kind "port7") and writes
  results/phase7_summary.json             every number used in the paper
  results/phase7_closure.json            feasibility closure: for every (size, day, cell) the plan retained and its origin
  tables/phase7_map_<n>.tex          cell map: each setting against the control (test v), closed values
  tables/phase7_contrasts.tex        families i-iv, with Holm and TOST, closed values
  tables/phase7_saturation_<n>.tex   observed peaks per cell (storage, handling, dwell), raw runs
  tables/phase7_*_raw.tex            the same map and contrast tables on the raw (unclosed) values
  tables/phase7_*_pool.tex           the same under the "pool" closure (sensitivity analysis, see close())
  results/phase7_closure_pool.json         its closure record

Primary criterion: relative cost change against the control of the same day, in % (Delta).
Secondary criterion: trucks (vehicles minus the control's).

Feasibility closure (pre-registered after the pilot, before any campaign run).  One search run per cell and
day: the pilot showed inversions of 0.02-1.87 points between cells nested on one factor (a stricter cell cheaper than a
looser one), which is search noise, since a plan feasible under the stricter limits is feasible under the
looser ones at the same cost.  The closed value of a cell on a day is the cheapest plan, among the plan of
the cell itself and the plans of the cells it dominates (H, S, W all <= its own, inf included), that the
verifier accepts under the cell's own limits; the control is not a donor (a no-yard plan is feasible under
every cell, and closing with it would make test (v) degenerate).  Closed values are monotone over the grid
by construction.  The main analysis uses the closed values; the raw values are reported alongside.
"""
import json, os, re, statistics as st
from collections import defaultdict
from scipy.stats import wilcoxon

R, OUT = "results", "tables"
# Sensitivity to the pilot day: P7_DAYS="1-19" restricts the analysis to those days and P7_TAG="_d1" suffixes every
# output (tables and JSON files), so that the main analysis on days 0-19 is untouched.
_days = os.environ.get("P7_DAYS")
DAYS = set(range(int(_days.split("-")[0]), int(_days.split("-")[1]) + 1)) if _days else None
TAG = os.environ.get("P7_TAG", "")
os.makedirs(OUT, exist_ok=True)
MARGIN = 0.5            # equivalence margin for TOST on the median paired difference, in points of relative cost (pre-registered)
ALPHA = 0.05
SIZES = (20, 30, 50)
INF = "inf"


def cell(h, s, w):
    return f"yards_H{h}_S{s}_W{w}"


def holm(ps):
    """Holm step-down adjusted p-values (None entries are passed through)."""
    idx = [i for i, p in enumerate(ps) if p is not None]
    m = len(idx)
    order = sorted(idx, key=lambda i: ps[i])
    adj = list(ps)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * ps[i]))
        adj[i] = running
    return adj


def wtwo(d):
    """Two-sided Wilcoxon signed-rank on paired differences d (None if fewer than 5 non-zero pairs)."""
    dd = [x for x in d if abs(x) > 1e-12]
    if len(d) < 5 or len(dd) < 1:
        return None
    try:
        return float(wilcoxon(d, alternative="two-sided").pvalue)
    except ValueError:
        return None


def wone(d):
    """One-sided: differences are negative (second plan cheaper)."""
    if len(d) < 5:
        return None
    try:
        return float(wilcoxon(d, alternative="less").pvalue)
    except ValueError:
        return None


def tost(d, margin=MARGIN):
    """Equivalence test on the paired differences: two one-sided Wilcoxon signed-rank tests (the location
    tested is the one the Wilcoxon test addresses, the median of the paired differences), p = max."""
    if len(d) < 5:
        return None
    try:
        p1 = wilcoxon([x + margin for x in d], alternative="greater").pvalue    # d > -margin
        p2 = wilcoxon([x - margin for x in d], alternative="less").pvalue       # d < +margin
    except ValueError:
        return None
    return float(max(p1, p2))


jobs = json.load(open(f"{R}/campaign_jobs.json")).get("port7", [])
rows = defaultdict(dict)            # (n, day) -> setting -> row
for r in jobs:
    if DAYS is None or r["seed"] in DAYS:
        rows[(r["n"], r["seed"])][r["setting"]] = r


def limits(setting):
    m = re.fullmatch(r"yards_H(\w+)_S(\w+)_W(\w+)", setting)
    v = lambda x: float("inf") if x == "inf" else float(x)
    return (v(m.group(1)), v(m.group(2)), v(m.group(3)))


def close(rows, mode="dominated"):
    """Feasibility closure (see module docstring).  Returns the closed rows (copies with cost/vehicles
    replaced) and the closure record.

    mode="dominated": the pre-registered rule -- donors are the cells the cell dominates (H, S, W all <=).
    mode="pool": sensitivity analysis added after the campaign (not pre-registered) -- every yard run of
    the day may donate its plan to every cell, if the verifier accepts the plan under the cell's own
    limits.  The pre-registered rule gives a looser cell more donors than a stricter one (the unbounded
    cell takes the best of 35 runs, a corner cell the best of two), so a "stricter -> looser" contrast
    mixes the parameter's effect with a best-of-k selection effect; the pool rule gives every cell the
    same donors, so a looser cell is cheaper only when the cheapest feasible plan of the day needs the
    looser limits.  Monotonicity over the grid holds in both modes (the set of accepted plans grows with
    the limits)."""
    import copy, sys
    sys.path.insert(0, "scripts")
    from job import parse_setting, job_key
    from pdpt.portgen import generate
    from pdpt.solution import Solution
    from pdpt.verifier import verify
    closed, record = copy.deepcopy(rows), {}
    for (n, day), S in sorted(rows.items()):
        cells = [s for s in S if s.startswith("yards_") and not S[s]["unassigned"]]
        lim = {s: limits(s) for s in cells}
        for s in cells:
            own = S[s]
            donors = sorted((S[d] for d in cells if d != s and (mode == "pool" or all(a <= b for a, b in zip(lim[d], lim[s])))
                             and S[d]["cost"] < own["cost"] - 1e-9), key=lambda r: r["cost"])
            if not donors:
                continue
            inst = generate(n, seed=day, **parse_setting(s))
            for d in donors:
                plan = json.load(open(f"{R}/jobs/{job_key(d['argv'])}.json"))["solution"]   # plans live in the job files
                rep = verify(inst, Solution.from_dict(plan))
                if rep.feasible:
                    closed[(n, day)][s]["cost"] = round(rep.cost, 2)
                    closed[(n, day)][s]["vehicles"] = rep.vehicles_used
                    record[f"{n}/{day}/{s}"] = dict(from_cell=d["setting"], raw_cost=own["cost"], closed_cost=round(rep.cost, 2),
                                                    raw_vehicles=own["vehicles"], closed_vehicles=rep.vehicles_used)
                    break
    for (n, day), S in closed.items():          # monotonicity over the grid, by construction; checked anyway
        cells = [s for s in S if s.startswith("yards_") and not S[s]["unassigned"]]
        for a in cells:
            for b in cells:
                if all(x <= y for x, y in zip(limits(a), limits(b))) and S[b]["cost"] > S[a]["cost"] + 1e-6:
                    raise AssertionError(f"closure not monotone: {n}/{day} {a} {S[a]['cost']} < {b} {S[b]['cost']}")
    return closed, record


def delta(n, setting):
    """Paired list over days of (Delta cost %, Delta trucks) of a setting against the control."""
    out = []
    for (nn, d), S in sorted(cur.items()):
        if nn != n or "no_yard_warm" not in S or setting not in S:
            continue
        c, x = S["no_yard_warm"], S[setting]
        if x["unassigned"] or c["unassigned"]:
            continue
        out.append((d, 100 * (x["cost"] / c["cost"] - 1), x["vehicles"] - c["vehicles"]))
    return out


def paired(n, a, b):
    """Day-paired differences Delta(b) - Delta(a) (cost points) and trucks(b) - trucks(a)."""
    A = {d: (dc, dv) for d, dc, dv in delta(n, a)}
    B = {d: (dc, dv) for d, dc, dv in delta(n, b)}
    days = sorted(set(A) & set(B))
    return [B[d][0] - A[d][0] for d in days], [B[d][1] - A[d][1] for d in days]


def analyse(suffix):
    summary = {"sizes": {}}
    contrast_lines = []
    for n in SIZES:
        if not any(nn == n for nn, _ in rows):
            continue
        S = {"map": {}, "contrasts": {}, "saturation": {}}
        # ---- (v) cell map: each setting against the control, one-sided, Holm within the size
        settings = sorted({s for (nn, _), ss in cur.items() if nn == n for s in ss if s not in ("no_yard", "no_yard_warm")}, key=limits)
        ps, info = [], []
        for s in settings:
            dl = delta(n, s)
            dc = [x[1] for x in dl]; dv = [x[2] for x in dl]
            p = wone(dc)
            ps.append(p)
            info.append((s, len(dl), st.mean(dc) if dc else None, sum(1 for x in dc if x < -1e-9), st.mean(dv) if dv else None))
        adj = holm(ps)
        map_lines = []
        for (s, k, m, wins, mv), p, ph in zip(info, ps, adj):
            S["map"][s] = dict(days=k, delta_cost=m, wins=wins, delta_trucks=mv, p=p, p_holm=ph)
            mm = re.fullmatch(r"yards_H(\w+)_S(\w+)_W(\w+)", s)
            lab = f"$H={mm.group(1)}$, $S={mm.group(2)}$, $W={mm.group(3)}$".replace("inf", r"\infty")
            sig = r"$^{*}$" if ph is not None and ph <= ALPHA else ""
            map_lines.append(f"{lab} & {k} & {m:+.2f}{sig} & {wins}/{k} & {mv:+.2f} & {'--' if p is None else f'{p:.2g}'} & {'--' if ph is None else f'{ph:.2g}'} \\\\")
        open(f"{OUT}/phase7_map_{n}{suffix}{TAG}.tex", "w").write("\n".join(map_lines) + "\n")

        # ---- families (i)-(iv): pre-registered contrasts
        fam = {
            "i_handling": [(cell(1, 2, INF), cell(INF, 2, INF)), (cell(2, 2, INF), cell(INF, 2, INF)), (cell(1, 2, INF), cell(2, 2, INF)),
                           (cell(1, INF, INF), cell(INF, INF, INF)), (cell(2, INF, INF), cell(INF, INF, INF)), (cell(1, INF, INF), cell(2, INF, INF))],
            "ii_storage": [(cell(1, 1, INF), cell(1, 2, INF)), (cell(1, 2, INF), cell(1, 3, INF)), (cell(1, 3, INF), cell(1, INF, INF))],
            "iii_dwell": [(cell(1, 2, 30), cell(1, 2, 60)), (cell(1, 2, 60), cell(1, 2, 120)), (cell(1, 2, 120), cell(1, 2, 240)), (cell(1, 2, 240), cell(1, 2, INF))],
        }
        for name, pairs in fam.items():
            ps, recs = [], []
            for a, b in pairs:
                dcost, dtr = paired(n, a, b)
                p = wtwo(dcost); q = tost(dcost)
                ps.append(p)
                recs.append(dict(a=a, b=b, days=len(dcost), mean=st.mean(dcost) if dcost else None,
                                 mean_trucks=st.mean(dtr) if dtr else None, p=p, p_tost=q))
            for rec, ph in zip(recs, holm(ps)):
                rec["p_holm"] = ph
                rec["verdict"] = ("different" if ph is not None and ph <= ALPHA else
                                  "equivalent" if rec["p_tost"] is not None and rec["p_tost"] <= ALPHA else "inconclusive")
            S["contrasts"][name] = recs
            for rec in recs:
                lab = lambda s: s.replace("yards_", "").replace("_", " ").replace("inf", r"$\infty$")
                fmt = lambda p: "--" if p is None else f"{p:.2g}"
                contrast_lines.append(f"{n} & {name.split('_')[0]} & {lab(rec['a'])} $\\to$ {lab(rec['b'])} & {rec['days']} & "
                                      f"{rec['mean']:+.2f} & {rec['mean_trucks']:+.2f} & {fmt(rec['p'])} & {fmt(rec['p_holm'])} & {fmt(rec['p_tost'])} & {rec['verdict']} \\\\")
        # (iv) interaction: difference of differences, H = 1
        A1 = dict(zip(*[[d for d, *_ in delta(n, cell(1, 1, INF))], [dc for _, dc, _ in delta(n, cell(1, 1, INF))]]))
        dod = []
        for d in sorted(A1):
            try:
                x = {s: next(dc for dd, dc, _ in delta(n, s) if dd == d) for s in (cell(1, 1, 60), cell(1, 1, INF), cell(1, INF, 60), cell(1, INF, INF))}
            except StopIteration:
                continue
            dod.append((x[cell(1, 1, 60)] - x[cell(1, 1, INF)]) - (x[cell(1, INF, 60)] - x[cell(1, INF, INF)]))
        p = wtwo(dod)
        S["contrasts"]["iv_interaction"] = dict(days=len(dod), mean=st.mean(dod) if dod else None, p=p,
                                                verdict="different" if p is not None and p <= ALPHA else "inconclusive")
        contrast_lines.append(f"{n} & iv & (W60 $-$ W$\\infty$) at S1 minus at S$\\infty$, H1 & {len(dod)} & "
                              f"{(st.mean(dod) if dod else 0):+.2f} & {{--}} & {'--' if p is None else f'{p:.2g}'} & -- & -- & {S['contrasts']['iv_interaction']['verdict']} \\\\")
        # ---- saturation: observed peaks per cell (mean over days and yards of the per-run maxima)
        sat_lines = []
        for s in settings:
            ys = [max(y["peak_storage"] for y in r["yards"].values()) for (nn, _), ss in cur.items() if nn == n and s in ss for r in [ss[s]] if r.get("yards")]
            yh = [max(y["peak_handling"] for y in r["yards"].values()) for (nn, _), ss in cur.items() if nn == n and s in ss for r in [ss[s]] if r.get("yards")]
            yw = [max(y["max_dwell"] for y in r["yards"].values()) for (nn, _), ss in cur.items() if nn == n and s in ss for r in [ss[s]] if r.get("yards")]
            tr = [r["transfers"] for (nn, _), ss in cur.items() if nn == n and s in ss for r in [ss[s]]]
            if ys:
                S["saturation"][s] = dict(peak_storage_mean=st.mean(ys), peak_storage_max=max(ys), peak_handling_max=max(yh),
                                          max_dwell_mean=st.mean(yw), max_dwell_max=max(yw), transfers_mean=st.mean(tr))
                sat_lines.append(f"{s.replace('_', ' ')} & {st.mean(tr):.1f} & {st.mean(ys):.2f} & {max(ys):.0f} & {max(yh)} & {st.mean(yw):.0f} & {max(yw):.0f} \\\\")
        open(f"{OUT}/phase7_saturation_{n}{TAG}.tex", "w").write("\n".join(sat_lines) + "\n")
        summary["sizes"][n] = S

    open(f"{OUT}/phase7_contrasts{suffix}{TAG}.tex", "w").write("\n".join(contrast_lines) + "\n")
    return summary


raw_rows = rows
closed_rows, closure = close(rows)
json.dump(closure, open(f"{R}/phase7_closure{TAG}.json", "w"), indent=1)
pool_rows, pool_closure = close(rows, mode="pool")              # sensitivity analysis (added after the campaign)
json.dump(pool_closure, open(f"{R}/phase7_closure_pool{TAG}.json", "w"), indent=1)
cur = closed_rows
main = analyse("")
cur = raw_rows
raw = analyse("_raw")
cur = pool_rows
pool = analyse("_pool")
stat = lambda c: dict(cells_closed=len(c), max_change_points=max([100 * (1 - v["closed_cost"] / v["raw_cost"]) for v in c.values()] or [0.0]))
summary = {"margin": MARGIN, "alpha": ALPHA, "closure": stat(closure), "closure_pool": stat(pool_closure),
           "closed": main, "raw": raw, "pool": pool}
json.dump(summary, open(f"{R}/phase7_summary{TAG}.json", "w"), indent=1)
print("phase 7:", {n: len(main["sizes"][n]["map"]) for n in main["sizes"]}, "cells;", len(closure), "cells closed, max",
      f"{summary['closure']['max_change_points']:.2f} points; pool closure:", len(pool_closure), "cells, max",
      f"{summary['closure_pool']['max_change_points']:.2f} points")
