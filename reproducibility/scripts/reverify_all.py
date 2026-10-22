# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Re-verify every stored plan of the campaign with the current verifier (consistency check included).

Prints, per kind, the number of plans re-checked, with transfers, and the violations found, and writes
results/reverify_all.json.  Run after any change to the verifier.
"""
import glob, json, sys
from collections import Counter

sys.path.insert(0, "scripts")
from job import parse_setting, SETTINGS
from pdpt.solution import Solution
from pdpt.verifier import verify
from pdpt.instance import Instance


def instance_of(row):
    kind, args = row["kind"], row["argv"][1:]
    if kind == "port":
        from pdpt.portgen import generate
        return generate(row["n"], seed=row["seed"], **SETTINGS[row["setting"]])
    if kind == "port7":
        from pdpt.portgen import generate
        return generate(row["n"], seed=row["seed"], **parse_setting(row["setting"]))
    if kind == "lyuyu":
        from pdpt.converters import lyu_yu
        return lyu_yu(args[0])
    if kind == "sampaio":
        from pdpt.converters import sampaio
        return sampaio(args[0], name=row["instance"], integer_times=len(args) > 3 and args[3] == "int")[0]
    if kind == "tt14":
        from pdpt.thesis2014 import instance
        return instance(args[0], fleet_size=4, allow_transfer=args[1] == "1")
    if kind == "lilim":
        from pdpt.converters import li_lim
        return li_lim(args[0])
    if kind in ("ablation", "sens"):
        fam, ident = args[0], args[1]
        if fam in ("port30", "port50"):
            from pdpt.portgen import generate
            return generate(int(fam[4:]), seed=int(ident), n_yards=2, H=1, S=2)
        if fam == "lyuyu":
            from pdpt.converters import lyu_yu
            return lyu_yu(ident)
        if fam == "sampaio":
            from pdpt.converters import sampaio
            return sampaio(ident, name=row["instance"])[0]
    return None


def main():
    out, counts = {}, Counter()
    for f in sorted(glob.glob("results/jobs/*.json")):
        row = json.load(open(f))
        if "solution" not in row:
            continue
        try:
            inst = instance_of(row)
        except Exception as e:  # noqa
            counts[f"{row['kind']}:no-instance"] += 1
            continue
        if inst is None:
            counts[f"{row['kind']}:skipped"] += 1
            continue
        sol = Solution.from_dict(row["solution"])
        rep = verify(inst, sol)
        counts[f"{row['kind']}:checked"] += 1
        if row.get("metric") == "integer":
            counts["sampaio-integer:checked"] += 1
            if abs(rep.cost - row["cost"]) > 1e-6:
                counts["sampaio-integer:cost-mismatch"] += 1
        if rep.transfers:
            counts[f"{row['kind']}:with-transfers"] += 1
        if not rep.feasible:
            bad = [m for m in rep.violations if not m.startswith("fleet:") and "unassigned" not in m]
            if bad:
                counts[f"{row['kind']}:violations"] += 1
                out[f] = bad[:3]
    json.dump({"counts": dict(counts), "violations": out}, open("results/reverify_all.json", "w"), indent=1)
    for k in sorted(counts):
        print(k, counts[k])


if __name__ == "__main__":
    main()
