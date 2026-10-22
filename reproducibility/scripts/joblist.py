# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Print the job lines of a campaign phase (one per line, for `xargs -P`).

usage: python3 scripts/joblist.py <phase> [seeds=10]
phases (run in this order; each phase only depends on the previous ones):
  1  small sets: TT-14, Li & Lim, Lyu & Yu (1 seed on 3R/4R/5R, PDPT), PORT no_yard 20/30/50/100
  2  PORT yard settings (warm start from phase 1), Sampaio 50/75/100 (1 seed), CP-SAT certificates
  3  extra seeds: Lyu & Yu seeds 1-4, Sampaio seeds 1-4
  4  ablation: 6 solver variants x (10 PORT-30, 10 PORT-50, 10 LY PDPT-R20, 10 SA-50 180_long) x 3 seeds, 300 s
  5  sensitivity: radius x {0.5, 1, 2} and destroy range {15-40, 25-50, 35-60 %} (5 configurations
     sharing the baseline) x (10 PORT-30, 10 PORT-50) x 3 seeds, 300 s
  6  control for the warm start: PORT without yards, warm-started from the phase-1 plan with the same
     extra budget as the yard runs (40 jobs)
  8  Sampaio sets in the published metric (distances and times rounded up to the integer), 720 runs
  7a factorial study of the yard parameters, first half: PORT n in {20, 30, 50}, days 0..seeds-1 (20 in the
     campaign, 1 in the pilot), no_yard cold start 600 s, plus CP-SAT certificates of the new days at n=20, 30
  7b second half: the 36 other settings of the design (32 cells H x S x W, the W=240 cell, two H=2 cells and
     the control), warm-started from the 7a plan of the same day, 600 s
     (joblist.py 7b 20 -> 2,160 jobs; 7a 20 -> 60 + 20 jobs).  See CAMPAIGN.md, "Phase 7 (pre-registered)".
Jobs already finished (results/jobs/<key>.json exists) are skipped by job.py itself.
"""
import glob, sys
arg = sys.argv[1]
phase = int(arg.rstrip("ab")) if arg[0].isdigit() else int(arg)
sub = arg[len(str(phase)):]                      # "a" / "b" for the two halves of phase 7
seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 10
LY = "ext/lyuyu"
SA = "ext/sampaio"
PORT_TL = {20: 600, 30: 600, 50: 600, 100: 900}
out = []
if phase == 1:
    for i in range(1, 17):
        for tr in (0, 1):
            for s in range(seeds):
                out.append(f"tt14 E{i} {tr} {s} 10")
    for f in sorted(glob.glob("instances/l*101.txt")):
        for s in range(seeds):
            out.append(f"lilim {f} {s} 120")
    for f in sorted(glob.glob(f"{LY}/PDPTW-T/*/*.txt")):
        out.append(f"lyuyu {f} 0 60")
    for f in sorted(glob.glob(f"{LY}/PDP-T/*/*.txt")):
        out.append(f"lyuyu {f} 0 120")
    for n, tl in PORT_TL.items():
        for s in range(seeds):
            out.append(f"port {n} {s} no_yard {tl}")
elif phase == 2:
    for n, tl in PORT_TL.items():
        for s in range(seeds):
            for st in ("yards_inf", "yards_H1_S2", "yards_H1_S1_W60"):
                out.append(f"port {n} {s} {st} {tl}")
    for sub in ("5T_rpk", "4T_rpk"):
        for f in sorted(glob.glob(f"{SA}/50/50/json/50/50/json/{sub}/*/*.json")):
            out.append(f"sampaio {f} 0 300")
    for f in sorted(glob.glob(f"{SA}/75/75/json/*/*.json")):
        out.append(f"sampaio {f} 0 600")
    for f in sorted(glob.glob(f"{SA}/100/json/*/*.json")):
        out.append(f"sampaio {f} 0 900")
    for n in (20, 30):
        for s in range(seeds):
            for st in ("no_yard", "yards_inf"):
                out.append(f"cpsat {n} {s} {st} 1800")
elif phase == 3:
    for f in sorted(glob.glob(f"{LY}/PDPTW-T/*/*.txt")) + sorted(glob.glob(f"{LY}/PDP-T/*/*.txt")):
        for s in range(1, 5):
            out.append(f"lyuyu {f} {s} {60 if 'PDPTW' in f else 120}")
    for f in sorted(glob.glob(f"{SA}/50/50/json/50/50/json/5T_rpk/*/*.json")):
        for s in range(1, 5):
            out.append(f"sampaio {f} {s} 300")
elif phase == 4:
    VAR = ("full", "no_transfer_ops", "no_phase1", "no_noise", "python_o1", "full_reprop")
    fams = [("port30", [str(i) for i in range(10)]), ("port50", [str(i) for i in range(10)]),
            ("lyuyu", sorted(glob.glob(f"{LY}/PDP-T/PDPT-R20-K3-T3/*.txt"))[:10]),
            ("sampaio", sorted(glob.glob(f"{SA}/50/50/json/50/50/json/5T_rpk/180_long/*.json"))[:10])]
    for fam, ids in fams:
        for ident in ids:
            for v in VAR:
                for s in range(3):
                    out.append(f"ablation {fam} {ident} {s} {v} 300")
elif phase == 5:
    CONF = [(1.0, 0.25, 0.5), (0.5, 0.25, 0.5), (2.0, 0.25, 0.5), (1.0, 0.15, 0.4), (1.0, 0.35, 0.6)]
    for fam in ("port30", "port50"):
        for ident in range(10):
            for rho, lo, hi in CONF:
                for s in range(3):
                    out.append(f"sens {fam} {ident} {s} {rho} {lo} {hi} 300")
elif phase == 6:
    for n, tl in PORT_TL.items():
        for s in range(seeds):
            out.append(f"port {n} {s} no_yard_warm {tl}")
elif phase == 7:
    P7 = [20, 30, 50]
    inf = "inf"
    design = [f"yards_H{h}_S{s_}_W{w}" for h in (1, inf) for s_ in (1, 2, 3, inf) for w in (30, 60, 120, inf)]
    design += ["yards_H1_S2_W240", "yards_H2_S2_Winf", "yards_H2_Sinf_Winf", "no_yard_warm"]
    assert len(design) == 36
    if sub in ("", "a"):
        for n in P7:
            for d in range(seeds):
                out.append(f"port7 {n} {d} no_yard 600")
        for n in (20, 30):
            for d in range(10, seeds):                      # days 0-9 are certified in phase 2
                out.append(f"cpsat {n} {d} no_yard 1800")
    if sub in ("", "b"):
        for n in P7:
            for d in range(seeds):
                for st in design:
                    out.append(f"port7 {n} {d} {st} 600")
elif phase == 8:
    # Sampaio sets in the published metric (distances and times rounded up to the integer): the same
    # 720 runs as phases 2-3, warm-started from the shipped routes, with the "int" switch of job.py
    for sub in ("5T_rpk", "4T_rpk"):
        for f in sorted(glob.glob(f"{SA}/50/50/json/50/50/json/{sub}/*/*.json")):
            out.append(f"sampaio {f} 0 300 int")
    for f in sorted(glob.glob(f"{SA}/75/75/json/*/*.json")):
        out.append(f"sampaio {f} 0 600 int")
    for f in sorted(glob.glob(f"{SA}/100/json/*/*.json")):
        out.append(f"sampaio {f} 0 900 int")
    for f in sorted(glob.glob(f"{SA}/50/50/json/50/50/json/5T_rpk/*/*.json")):
        for s in range(1, 5):
            out.append(f"sampaio {f} {s} 300 int")
print("\n".join(out))
