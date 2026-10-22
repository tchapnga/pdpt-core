# pdpt-core

Optimisation engine for **pickup and delivery with transfers at capacitated transfer points** — relay yards,
micro-hubs and cross-docks whose storage slots, handling bays and dwell times are limited.

- **Model and instance format**: transfer points with storage capacity, handling bays, handling cost, transfer
  time and maximum storage time; heterogeneous fleets with load-type compatibility; asymmetric distance and
  time matrices; lexicographic or weighted objectives.
- **Search**: a large neighbourhood search whose operators act on transfers directly, with a max-plus
  insertion test evaluated in a compiled kernel.
- **Independent verifier**: every plan is re-checked (custody chains, loads, compatibility, consistency of the
  event graph, earliest-start schedule, windows, storage and handling-bay profiles, cost vector).
- **Exact models**: a MILP (HiGHS) and a constraint-programming model (OR-Tools CP-SAT) for certificates on
  small instances.
- **PORT generator**: container-drayage days with configurable relay yards.

## Install

Python 3.10 or later.

```
pip install -e .            # installs numpy, numba, highspy, ortools, scipy
pip install pytest && pytest
```

## Quick start

```
python examples/quickstart.py
```

```python
from pdpt.portgen import generate
from pdpt.lns import solve
from pdpt.verifier import verify

inst = generate(20, seed=0, S=2, H=1)          # 20 containers, two yards: 1 bay and 2 slots each
result = solve(inst, time_limit=20, seed=0)
report = verify(inst, result.solution)
print(report.feasible, report.vehicles_used, report.objective(inst))
```

Instances and solutions are JSON files (`Instance.load`, `Instance.save`, `Solution.load`, `Solution.save`);
`"inf"` means unconstrained. `pdpt.converters` reads the published benchmark formats (Li & Lim, Lyu & Yu,
Sampaio et al.).

## Repository layout

| Path | Content |
| --- | --- |
| `pdpt/` | the engine |
| `tests/` | unit and regression tests |
| `examples/` | a runnable quick start |
| `reproducibility/` | everything behind the two research papers: instances, campaign scripts, the 10,002 result files and the scripts that regenerate every table (see `reproducibility/README.md`) |

## Licence

pdpt-core is released under the **Apache License 2.0** (`LICENSE`): you may use, modify and redistribute it,
including in commercial products, provided that you keep the copyright and licence notices.

Copyright (C) 2026 The pdpt-core authors.
