# Running the computational campaign on a rented machine

Fresh Ubuntu 24.04, any number of cores (32 recommended), ~2 GB RAM per core for CP-SAT jobs.

```bash
# 1. as a normal user with sudo (only used for apt):
git clone https://github.com/<owner>/pdpt-core.git pdpt && cd pdpt && bash reproducibility/scripts/remote_setup.sh
cd reproducibility                 # every command below runs from this folder
# 2. start the campaign (phases 1 to 4; re-runnable; results pushed to git after each phase)
nohup scripts/run_campaign.sh $(nproc) > campaign.log 2>&1 &
# 3. watch
tail -f campaign.log            # or: ls results/jobs | wc -l
```

Jobs: 990 (phase 1) + 520 (phase 2) + 2,760 (phase 3) + 720 (phase 4) = 4,990. Budget: about 270 core-hours in total (phase 1 ≈ 25, phase 2 ≈ 100, phase 3 ≈ 85, phase 4 ≈ 60), i.e. ~17 h on 16 cores, ~9 h on 32.
Every job writes its own `results/jobs/<key>.json`; `scripts/collect.py` merges them and
`make_tables.py` regenerates the paper tables.  Instance archives in `ext_archives/` are the
Mendeley datasets of Lyu & Yu (2023, w925jygjct, CC BY 4.0) and Sampaio et al. (2020, pywzcgyzrv, CC BY 4.0).

## Convention updates during the campaign

The machine runs the campaign on `df2b8e2` and publishes results on the branch `campaign`; the fixes
below were found on the phase 1 results and are on `main`.  Job files carry a convention suffix
(`scripts/job.py: job_key`): `_sv` = one visit per transfer point and vehicle (Sampaio), `_sv2` = plus
the deadhead rule of Lyu & Yu's PDP-T (an unused vehicle pays its origin-to-destination trip).
`collect.py` drops job files whose stem is not the current key, except Sampaio runs without station
revisits (`tp_revisits == 0`), which are valid under the convention.

After phase 4: `git pull`, then rerun the phases; only the missing keys are computed (the Lyu & Yu
jobs: 3,180 jobs, about 85 CPU hours, 5.5 h on 16 cores; plus the Sampaio runs with revisits):

    scripts/run_campaign.sh 16 "1 2 3 4 5"

Phase 5 (sensitivity to the detour radius and the destroy range, 300 jobs, about 25 CPU hours) was added
after the campaign started; it runs with the other phases on the second pass.

## Phase 7 (pre-registered): factorial study of the yard parameters

Frozen before any phase-7 run, at the commit that introduces this section.

*Commit identifiers and times in this file refer to the development repository, whose history is available
to editors and reviewers on request; this public repository is a single snapshot of its final state.*
Search code: `pdpt/` unchanged since `5b29812`.  Everything below is computed on one machine, 600 s per run.

**Why.** The three yard settings of phases 1-2 confound the parameters (infinite -> (H=1, S=2) changes H and S;
(H=1, S=2) -> (H=1, S=1, W=60) changes S and W), so "storage room and dwell time, not handling throughput,
govern the value of a yard" is an interpretation.  Phase 7 measures it with one-factor contrasts, and tests
its "no effect" parts with equivalence tests rather than non-significance.

**Design.** PORT, n in {20, 30, 50}, days 0-19 (days 0-9 are the generator seeds of phases 1-2, recomputed).
Settings per day (37): `no_yard` (cold start), `no_yard_warm` (control: the no_yard plan re-optimised for the
same extra 600 s without yards), the 32 cells H in {1, inf} x S in {1, 2, 3, inf} x W in {30, 60, 120, inf},
the dwell cell (H=1, S=2, W=240), and two handling cells H=2 at (S=2, W=inf) and (S=inf, W=inf).  Every yard run and the control start from the
`no_yard` plan of the same day.  The grid stops at S=3 because the phase-1/2 runs use about three transfers per day for two yards, so
S=5 is expected to be indistinguishable from S=3; for W, a smoke test showed a dwell of 257 min with
unbounded yards, so W=240 is kept on the dwell axis.  Both expectations are **measured**, not assumed, by the
per-yard peaks recorded in every run (peak stored quantity, peak
simultaneous handling operations, longest dwell time; `yards` field of the job files).
CP-SAT certificates (1800 s) of the no-yard plans of days 10-19 at n=20 and 30.
Jobs: 7a = 60 no_yard + 20 CP-SAT; 7b = 3 x 20 x 36 = 2,160.  Pilot before the campaign:
`scripts/run_campaign.sh 16 "7a:1 7b:1"` (3 + 108 runs, day 0 only), to check keys, the warm-start guard, the
recorded peaks and the control; then `scripts/run_campaign.sh 16 "7a:20 7b:20"`.

**Criteria.** Primary: relative cost change against the control of the same day, in % (Delta).
Secondary: trucks minus the control's.  Pairing is by day.  Runs with an unassigned request are excluded
(none expected; reported if any).

**Feasibility closure** (added after the pilot, commits `d353813` and `23c8adb`, before any campaign run; the
pilot is a test of the pipeline, not part of the campaign).  One search run per cell and day: the pilot showed
inversions between nested cells of 0.3-0.7 points (n=20: (H=inf, S=inf, W=inf) +0.00 but (H=1, S=inf, W=inf)
-0.73; n=30: S=1 -5.75 below S=2 -5.41; n=50: S=1 -2.34 below S=inf -2.20), larger than the TOST margin.  A
plan feasible under stricter limits is feasible under looser ones at the same cost, so these inversions are
search noise.  The *closed value* of a cell on a day is the cheapest plan, among its own and those of the
cells it dominates (H, S, W all <= its own, inf included), that the verifier accepts under the cell's own
limits; cost and trucks are then those of the retained plan.  The control is not a donor (a no-yard plan is
feasible under every cell; closing with it would make test (v) degenerate).  Closed values are monotone over
the grid by construction (checked by the script).  All tests below run on the closed values; the raw values
are reported alongside (`*_raw.tex`), and `results/phase7_closure.json` records every substitution.  The
saturation table uses the raw runs (the peaks describe what the search did under each cell).
Pilot measurements (day 0): peak stored quantity <= 2 and peak handling = 1 in every cell (so S=3 and
H=2 are unconstrained there, as expected); longest dwell 360 min (n=30) and 480 min (n=50) with W=inf;
W=120 leaves no transfer at n=50; control +0.00 % at the three sizes.

**Amendments recorded after the freeze (the text above is the frozen one, commit `9dccbae`, 18 October 2026 20:28:05 UTC).**
- *20 October 2026 (timeline).* Protocol committed 18:14:15 (`1784269`) and 18:41:38 (`21961a5`) on 18 October; pilot
  results committed 19:00:59 (`d353813`, 7a day 0) and 20:11:09 (`23c8adb`, 7b day 0); the closure amendment committed
  20:28:05 (`9dccbae`); days 1-19 (`7a:20 7b:20`, which skips the finished day-0 jobs) launched 20:32; phase 7a results
  committed 21:42:27 (`6db682c`; 60 runs of 600 s and 20 CP-SAT jobs, about 48,500 s of work on 16 cores), phase 7b
  results 19 October 19:13:25 (`57b3a6f`).
- *20 October 2026 (correction of the quoted range).* The three inversions quoted above span 0.14 to 0.73 points, not
  0.3-0.7; over all one-factor pairs of nested cells on day 0 there are 28 inversions, of 0.02 to 1.87 points (the
  largest at n=30, (H=1, S=inf, W=120) at -5.38 % against (H=inf, S=inf, W=120) at -3.51 %).
- *20 October 2026 (deviation).* The day-0 (pilot) runs were not repeated and are part of the analysed data, although
  the frozen text calls the pilot a test of the pipeline and not part of the campaign; the closure amendment was
  written after the day-0 results had been seen.  The whole analysis is therefore repeated on days 1-19
  (`P7_DAYS=1-19 P7_TAG=_d1 python3 scripts/analysis_phase7.py`, outputs `*_d1`): 4 of the 126 verdicts change, no
  headline finding does (the factorial-study paper, Section 6).

**Sensitivity analysis added after the campaign (not pre-registered).** The closure rule above gives a looser
cell more donors than a stricter one (the unbounded cell takes the best of 35 runs, a corner cell the best of
two), so a "stricter -> looser" contrast on closed values mixes the parameter's effect with a best-of-k
selection effect; the flaw was identified from the rule, after the campaign, during the review of v1.11.
`analysis_phase7.py` therefore also runs a *pool* closure (mode `pool` of `close()`): every yard run of the day
may donate to every cell if the verifier accepts the plan under the cell's limits, so all cells have the same
35 candidate donors.  Outputs: `phase7_*_pool.tex`, `results/phase7_closure_pool.json`, key `pool` of the summary.
The paper reports the pre-registered results as the protocol, the pool results as the sensitivity analysis,
and retains only the findings that hold on the raw values and under both closures.

**Pre-registered tests** (`scripts/analysis_phase7.py`, written before the runs):
- (i) Handling: H=1 vs H=inf, H=2 vs H=inf, H=1 vs H=2, at (S=2, W=inf) and at (S=inf, W=inf).
- (ii) Storage, at (H=1, W=inf): S=1 vs 2, 2 vs 3, 3 vs inf.
- (iii) Dwell, at (H=1, S=2): W=30 vs 60, 60 vs 120, 120 vs 240, 240 vs inf.
- (iv) Interaction, at H=1: the single contrast [Delta(S=1, W=60) - Delta(S=1, W=inf)] minus
  [Delta(S=inf, W=60) - Delta(S=inf, W=inf)], paired by day.
- (v) Map: every cell against the control, one-sided (cell cheaper), Holm within each size (35 tests).
Families (i)-(iii) and (iv) use two-sided Wilcoxon signed-rank tests (direction not known a priori), Holm
within each family and size.  For every contrast of (i)-(iii) an equivalence test (TOST: two one-sided
Wilcoxon tests, p = max) on the median of the paired differences, with the margin **+-0.5 points of
relative cost** (about a tenth of the savings measured in phases 1-2), is reported; equivalence statements in
the paper are statements about that median.  Verdicts: *different* if the Holm-adjusted two-sided p <= 0.05;
*equivalent* if not different and the TOST p <= 0.05; *inconclusive* otherwise.  "No effect" is claimed in
the paper only for contrasts with the verdict *equivalent*.  Alpha = 0.05 throughout; with 20 days the
smallest attainable raw p is 2^-20.

**Reporting.** `results/phase7_summary.json` (closed and raw), `results/phase7_closure.json`, the cell maps (one table per size), the contrast table with
raw, Holm and TOST p-values, and the saturation table (observed peaks per cell).  The paper's Section 7.5,
abstract and conclusion are rewritten from these outputs; if the data contradict the current conclusion,
the paper states what the data show.


## Phase 8: Sampaio sets in the published metric (added 20 October 2026, before any run)

**Why.** The published RP costs of Sampaio et al. (2020), the base of their Tables 5-8, are the costs of the
shipped PDPTW routes with every distance rounded *up* to the integer (checked: equal to 0.1 on sixteen of
the eighteen 50-request classes, within 0.9 on the other two), and since speed is one their travel times are
rounded up too: every shipped plan is feasible under the rounded times.  Phases 2-3 ran the sets under exact
Euclidean distances and times; the plans they produced are infeasible under the rounded times (they use the
shift to the last minute), so the comparison reported in v1.18 and earlier is in a looser metric than theirs.

**Design.** The 720 runs of phases 2-3, warm-started from the shipped routes, with the converter option
`integer_times=True` (job argument `int`): seed 0 on the 360 instances (300 / 600 / 900 s for 50 / 75 / 100
requests) and seeds 1-4 on the 90 instances of the 5-station 50-request classes.  `python3 scripts/joblist.py 8`.
Rows carry `metric = "integer"`; `make_tables.py` and `stats.py` select the metric with
`SA_METRIC=integer` (default `exact`, the phase 2-3 rows, kept for the record).

**Criteria (pre-registered).** Table 7 of the paper is regenerated on the integer rows: the class mean of our
best of the seeds against the published RP cost, now in the same metric, next to their best and average of five.
The claim "below their best of five on k of 18 classes at n = 50" is restated with the k observed; the paired
tests against the shipped plans (same metric) are rerun as in phase 3.  No other table changes.  Expected: the
margins of v1.19 (1.3 to 10.3 points on the own-start base, 4T-300-long level) shrink by the rounding penalty
of plans with more stops, which the 20-second smoke test puts at one to three points; the 75/100-request
findings (worse than their best on 7 of 18 classes) are expected to hold or worsen.

**Result (20 October 2026, commit `d1b589c`, 720/720 runs, no unserved request, no infeasible plan).** At n = 50,
below their best of five on 17 of 18 classes and level on 5T-240-long (-28.5 against -28.5); margins: long 0.8-2.8
points, mixed 3.7-8.0, short 3.6-8.3; below their average of five on all 18.  Against the exact-metric runs our class
means moved by 0.1 to 6.2 points (median 3.9), more than the one-to-three-point expectation, the short
classes most (3.8-6.2): the rounding penalty of plans with many short arcs was under-estimated.  At n = 75/100 worse than their best on 10 of 18 classes (expected 7 or more): all six long
classes and four mixed, better on all six short.
