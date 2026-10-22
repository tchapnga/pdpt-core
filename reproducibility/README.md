# Reproducibility

Everything needed to check and reproduce the computational results of the two research papers built on
pdpt-core: the instances, the campaign scripts, every result file and the scripts that regenerate every table.
All commands below run from this folder, after `pip install -e .` at the repository root.

| Path | Content |
| --- | --- |
| `instances/` | Li & Lim (2001) instances lc101, lr101, lrc101 |
| `ext_archives/` | the Mendeley datasets of Lyu & Yu (2023) and Sampaio et al. (2020), CC BY 4.0 |
| `scripts/` | campaign runner (`job.py`, `joblist.py`, `run_campaign.sh`), collection, re-verification and analysis scripts, including the pre-registered analysis of the factorial study (`analysis_phase7.py`) |
| `results/` | one JSON file per job (`results/jobs/`) and the merged campaign files |
| `make_tables.py`, `stats.py`, `make_fig_sensitivity.py` | regenerate every table and figure data file in `tables/` and `figures/` |
| `CAMPAIGN.md` | how the campaign was run, the convention changes and the pre-registered protocol |

## Regenerating the tables

```
mkdir -p ext && for z in ext_archives/*.zip; do d=ext/$(basename "$z" .zip); mkdir -p "$d"; unzip -q -o "$z" -d "$d"; done
python make_tables.py
python stats.py
```

Nothing in `tables/` or `figures/` is edited by hand.

## Running jobs

`python scripts/job.py <kind> <args...>` runs one job and writes `results/jobs/<key>.json` (the docstring of
`job.py` lists the job kinds). `scripts/joblist.py` and `scripts/run_campaign.sh` run whole phases in parallel,
and `scripts/collect.py` merges the job files. On a fresh Ubuntu machine, `bash scripts/remote_setup.sh`
installs everything. Results depend on the iterations a machine affords within a wall-clock budget, so a rerun
on different hardware reproduces the campaign values up to that effect.
