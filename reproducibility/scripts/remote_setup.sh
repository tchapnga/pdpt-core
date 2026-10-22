#!/bin/bash
# One-shot setup on a fresh Ubuntu 24.04 machine, run from INSIDE a clone of the repository:
#   git clone https://github.com/<owner>/pdpt-core.git pdpt && cd pdpt && bash reproducibility/scripts/remote_setup.sh
set -eu
cd "$(dirname "$0")/../.."
sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv python3-pip git unzip > /dev/null
python3 -m venv .venv && . .venv/bin/activate
pip install -q -U pip && pip install -q -e . numba highspy ortools scipy pytest
cd reproducibility
mkdir -p ext
for z in ext_archives/*.zip; do d=ext/$(basename "$z" .zip); mkdir -p "$d"; unzip -q -o "$z" -d "$d"; done
cd ..
python3 -m pytest -q tests | tail -1
echo "setup done; start with:  cd reproducibility && nohup scripts/run_campaign.sh \$(nproc) > campaign.log 2>&1 &"
