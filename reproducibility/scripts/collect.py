# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Merge results/jobs/*.json into the per-campaign files read by make_tables.py."""
import glob, json, os
from collections import defaultdict
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from job import job_key
rows = []
for f in sorted(glob.glob("results/jobs/*.json")):
    r = json.load(open(f))
    stem = os.path.basename(f)[:-5]
    if stem != job_key(r["argv"]):
        continue                      # computed under a superseded convention or code version: not part of the campaign
    rows.append(r)
by = defaultdict(list)
for r in rows:
    by[r["kind"]].append(r)
out = {}
for kind, rs in by.items():
    out[kind] = [{k: v for k, v in r.items() if k != "solution"} for r in rs]
json.dump(out, open("results/campaign_jobs.json", "w"), indent=1)
print({k: len(v) for k, v in out.items()})
