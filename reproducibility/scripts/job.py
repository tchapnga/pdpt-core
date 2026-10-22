# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""One campaign job = one JSON file in results/jobs/.  Safe to run many in parallel.

usage: python3 scripts/job.py <kind> <args...>
  port   <n> <seed> <setting> <tl>          setting in no_yard | no_yard_warm | yards_inf | yards_H1_S2 | yards_H1_S1_W60
                                             (no_yard_warm and the yard settings warm-start from the no_yard job of the
                                             same seed; no_yard_warm is the control for the extra search time)
  port7  <n> <seed> <setting> <tl>          factorial study (phase 7): setting in no_yard | no_yard_warm | yards_H<h>_S<s>_W<w>
                                             with h, s, w integers or inf (e.g. yards_H1_S2_Winf); warm start from the
                                             port7 no_yard job of the same day, which must exist (the job fails otherwise);
                                             records per-yard peaks of storage, handling and dwell time
  cpsat  <n> <seed> <setting> <tl>          exact certificate / bound (CP-SAT, 1 worker)
  lyuyu  <file> <seed> <tl>                 Lyu & Yu instance (unused vehicle pays its o->e trip; void for PDPTW-T)
  sampaio <file> <seed> <tl> [int]          Sampaio instance, warm-started from the shipped PDPTW routes;
                                            "int": distances and times rounded up to the integer (published metric)
  tt14   <name> <transfer:0|1> <seed> <tl>
  lilim  <file> <seed> <tl>
  sens   <family> <id> <seed> <rho_mult> <dlo> <dhi> <tl>   sensitivity: radius = rho_mult x median direct length,
                                                  destroy range [dlo, dhi]; family as for ablation
  ablation <family> <id> <seed> <variant> <tl>   family: port30 | port50 (yards H1 S2, id = day), lyuyu (id = file), sampaio (id = file)
                                                  variant: full | no_transfer_ops | no_phase1 | no_noise | python_o1 | full_reprop
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pdpt.lns import solve
from pdpt.verifier import verify
from pdpt.solution import Solution

OUT = "results/jobs"
os.makedirs(OUT, exist_ok=True)
SETTINGS = {"no_yard": dict(n_yards=0), "no_yard_warm": dict(n_yards=0), "yards_inf": dict(n_yards=2),
            "yards_H1_S2": dict(n_yards=2, H=1, S=2), "yards_H1_S1_W60": dict(n_yards=2, H=1, S=1, W=60.0)}


def _versions():
    """Interpreter and solver versions, recorded in every result file."""
    out = {"python": sys.version.split()[0]}
    for mod in ("numba", "ortools", "highspy", "numpy"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", None) or __import__("importlib.metadata").metadata.version(mod)
        except Exception:
            out[mod] = None
    return out


def parse_setting(setting):
    """'no_yard' / 'no_yard_warm' -> no yards; 'yards_H<h>_S<s>_W<w>' -> two yards with those limits."""
    if setting in SETTINGS:
        return SETTINGS[setting]
    m = re.fullmatch(r"yards_H(\d+|inf)_S(\d+|inf)_W(\d+|inf)", setting)
    if not m:
        raise SystemExit(f"unknown setting {setting}")
    val = lambda x: float("inf") if x == "inf" else float(x)
    return dict(n_yards=2, H=val(m.group(1)), S=val(m.group(2)), W=val(m.group(3)))


def yard_profile(inst, sol, rep):
    """Per transfer point: transfers, peak stored quantity, peak simultaneous handling operations,
    longest dwell time (drop end to pick start), from the verifier's schedule."""
    from pdpt.solution import DROP, PICK
    out = {}
    for tpid in inst.transfer_points:
        drops, picks, ops = {}, {}, []
        for ri, route in enumerate(sol.routes):
            for vi, vis in enumerate(route.visits):
                if vis.transfer_point != tpid or vis.op not in (DROP, PICK):
                    continue
                _, st, en = rep.schedule.times[(ri, vi)]
                (drops if vis.op == DROP else picks)[vis.request] = (st, en)
                if en > st:
                    ops.append((st, +1)); ops.append((en, -1))
        events, dwell = [], 0.0
        for rid, (ds, de) in drops.items():
            if rid in picks:
                ps = picks[rid][0]; q = inst.requests[rid].quantity
                events.append((de, +q)); events.append((ps, -q)); dwell = max(dwell, ps - de)
        peak = cur = 0.0
        for _, dq in sorted(events, key=lambda e: (e[0], e[1])):
            cur += dq; peak = max(peak, cur)
        busy = pk = 0
        for _, d in sorted(ops, key=lambda e: (e[0], e[1])):
            busy += d; pk = max(pk, busy)
        out[tpid] = dict(transfers=len([r for r in drops if r in picks]), peak_storage=peak, peak_handling=pk, max_dwell=round(dwell, 2))
    return out


def key_of(argv):
    return "_".join(a.replace("/", "-").replace(".txt", "").replace(".json", "") for a in argv)


def job_key(argv):
    """File stem of a job; a suffix versions the benchmark conventions so that a convention change
    recomputes exactly the affected jobs (collect.py drops files whose stem is not the current key)."""
    key = key_of(argv)
    kind = argv[0]
    if kind == "sampaio":
        key += "_sv"                 # single visit per transfer point and vehicle
    if kind == "lyuyu" or (kind in ("ablation", "sens") and argv[1] == "lyuyu"):
        key += "_sv2"                # + deadhead trips of unused PDP-T vehicles (fixed_cost = -d(o,e))
    return key


def lns_row(inst, r, extra=None):
    rep = verify(inst, r.solution)
    row = dict(cost=round(rep.cost, 2), distance=round(rep.distance, 2), vehicles=rep.vehicles_used,
               transfers=rep.transfers, feasible=rep.feasible, unassigned=len(r.operator_stats["unassigned"]),
               it=r.iterations, t_best=round(r.history[-1][0], 2), violations=rep.violations[:3])
    if extra:
        row.update(extra)
    return row


def main(argv):
    kind, args = argv[0], argv[1:]
    key = job_key(argv)
    path = f"{OUT}/{key}.json"
    if os.path.exists(path):
        return
    t0 = time.time()
    if kind == "port":
        from pdpt.portgen import generate
        n, seed, setting, tl = int(args[0]), int(args[1]), args[2], float(args[3])
        inst = generate(n, seed=seed, **SETTINGS[setting])
        warm = None
        if setting != "no_yard":
            base = f"{OUT}/{key_of(['port', args[0], args[1], 'no_yard', args[3]])}.json"
            if os.path.exists(base):
                warm = Solution.from_dict(json.load(open(base))["solution"])
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed, warm_start=warm)
        row = lns_row(inst, r, dict(kind=kind, n=n, seed=seed, setting=setting, tl=tl, warm=warm is not None,
                                    solution=r.solution.to_dict()))
    elif kind == "port7":
        from pdpt.portgen import generate
        n, seed, setting, tl = int(args[0]), int(args[1]), args[2], float(args[3])
        inst = generate(n, seed=seed, **parse_setting(setting))
        warm = None
        if setting != "no_yard":
            base = f"{OUT}/{key_of(['port7', args[0], args[1], 'no_yard', args[3]])}.json"
            if not os.path.exists(base):
                raise SystemExit(f"port7: no_yard job of day {seed} must run first ({base} missing)")
            warm = Solution.from_dict(json.load(open(base))["solution"])
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed, warm_start=warm)
        rep = verify(inst, r.solution)
        row = lns_row(inst, r, dict(kind=kind, n=n, seed=seed, setting=setting, tl=tl, warm=warm is not None,
                                    yards=yard_profile(inst, r.solution, rep), solution=r.solution.to_dict()))
    elif kind == "cpsat":
        from pdpt.portgen import generate
        from pdpt.cpsat import solve as cps
        n, seed, setting, tl = int(args[0]), int(args[1]), args[2], float(args[3])
        inst = generate(n, seed=seed, **SETTINGS[setting])
        r = cps(inst, time_limit=tl, workers=1, scale=1)
        row = dict(kind=kind, n=n, seed=seed, setting=setting, tl=tl, status=r.status,
                   objective=r.objective, bound=round(r.bound, 1), time=round(r.time, 1),
                   cost=None if r.report is None else round(r.report.cost, 1),
                   vehicles=None if r.report is None else r.report.vehicles_used)
    elif kind == "lyuyu":
        from pdpt.converters import lyu_yu
        f, seed, tl = args[0], int(args[1]), float(args[2])
        inst = lyu_yu(f)
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed)
        row = lns_row(inst, r, dict(kind=kind, instance=inst.name, set="PDPT" if "PDP-T" in f else "PDPTW-T", seed=seed, tl=tl))
    elif kind == "sampaio":
        from pdpt.converters import sampaio
        f, seed, tl = args[0], int(args[1]), float(args[2])
        integer = len(args) > 3 and args[3] == "int"
        parts = f.split("/")
        size = "50" if "/50/" in f else ("75" if "/75/" in f else "100")
        sub = "4T" if "4T" in f else "5T"
        name = f"SA{size}-{sub}-{parts[-2]}-{parts[-1][:-5]}"
        inst, warm = sampaio(f, name=name, integer_times=integer)
        wrep = verify(inst, warm) if warm else None
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed, warm_start=warm)
        revisits = 0
        for rt in r.solution.routes:
            seen, prev = set(), None
            for v in rt.visits:
                tp = v.transfer_point
                if tp and tp != prev:
                    if tp in seen:
                        revisits += 1
                    seen.add(tp)
                prev = tp
        row = lns_row(inst, r, dict(kind=kind, instance=name, seed=seed, tl=tl, n=len(inst.requests),
                                    metric="integer" if integer else "exact",
                                    warm_cost=wrep and round(wrep.cost, 2), warm_vehicles=wrep and wrep.vehicles_used,
                                    tp_revisits=revisits, solution=r.solution.to_dict()))
    elif kind == "tt14":
        from pdpt.thesis2014 import instance
        name, tr, seed, tl = args[0], args[1] == "1", int(args[2]), float(args[3])
        inst = instance(name, fleet_size=4, allow_transfer=tr)
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed)
        row = lns_row(inst, r, dict(kind=kind, instance=name, transfer=tr, seed=seed, tl=tl))
    elif kind == "lilim":
        from pdpt.converters import li_lim
        f, seed, tl = args[0], int(args[1]), float(args[2])
        inst = li_lim(f)
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed)
        row = lns_row(inst, r, dict(kind=kind, instance=inst.name, seed=seed, tl=tl))
    elif kind in ("ablation", "sens"):
        if kind == "ablation":
            fam, ident, seed, variant, tl = args[0], args[1], int(args[2]), args[3], float(args[4])
            opts = dict(variant=variant)
        else:
            fam, ident, seed, rho_mult, dlo, dhi, tl = args[0], args[1], int(args[2]), float(args[3]), float(args[4]), float(args[5]), float(args[6])
            opts = dict(destroy_frac=(dlo, dhi))
        warm = None
        if fam in ("port30", "port50"):
            from pdpt.portgen import generate
            inst = generate(int(fam[4:]), seed=int(ident), n_yards=2, H=1, S=2)
        elif fam == "lyuyu":
            from pdpt.converters import lyu_yu
            inst = lyu_yu(ident)
        else:
            from pdpt.converters import sampaio
            inst, warm = sampaio(ident, name=f"SA-{ident.split('/')[-2]}-{ident.split('/')[-1][:-5]}")
        if kind == "sens":
            lens = sorted(inst.dist(rq.pickup, rq.delivery) for rq in inst.requests.values())
            opts["radius"] = rho_mult * lens[len(lens) // 2]
        r = solve(inst, time_limit=tl, max_iter=10**6, seed=seed, warm_start=warm, **opts)
        extra = dict(kind=kind, family=fam, instance=inst.name, seed=seed, tl=tl)
        extra.update(dict(variant=variant) if kind == "ablation" else dict(rho_mult=rho_mult, dlo=dlo, dhi=dhi))
        row = lns_row(inst, r, extra)
    else:
        raise SystemExit(f"unknown job kind {kind}")
    row["wall"] = round(time.time() - t0, 1)
    row["argv"] = argv
    row["versions"] = _versions()
    tmp = path + ".tmp"
    json.dump(row, open(tmp, "w"))
    os.replace(tmp, path)
    print(key, {k: v for k, v in row.items() if k not in ("solution", "argv")}, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
