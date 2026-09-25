#!/usr/bin/env bash
# Recreate the exact environment used for household.json / national.json /
# households_sample.json, then run every step. Run from anywhere.
set -euo pipefail
DATA="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DATA"

# 1. Python env (uv only). Python 3.13; exact pins in compute/requirements.lock.txt.
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r compute/requirements.lock.txt
#   (equivalent top-level request: uv pip install "policyengine[us]==6.1.1")

# 2. Dataset: the policyengine.py 6.1.1 bundle default US dataset,
#    hf://policyengine/populace-us/populace_us_2024.h5@populace-us-2024-spm-20260915
#    sha256 6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84.
#    If it is already in the Hugging Face cache, symlink the blob; otherwise
#    policyengine.py downloads it into pe_data/ (and verifies the sha256) itself.
mkdir -p pe_data
BLOB="$HOME/.cache/huggingface/hub/datasets--policyengine--populace-us/blobs/6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84"
if [ -f "$BLOB" ] && [ ! -e pe_data/populace_us_2024.h5 ]; then
  ln -s "$BLOB" pe_data/populace_us_2024.h5
fi

# 3. Compute.
cd compute
../.venv/bin/python household.py           # Part A + household half of D -> ../household.json
../.venv/bin/python national.py            # Parts B, C, budget half of D -> ../national.json, ../households_sample.json
../.venv/bin/python national_raw_check.py  # D: independent policyengine_us path -> checks/national_raw_check.json
../.venv/bin/python diagnose_gap.py        # D: explains -d(income_tax) vs d(ctc_value) gap -> checks/gap_diagnostic.json
                                           #    (reads the two output datasets national.py saved in ../pe_data)
../.venv/bin/python crosspath_sample.py 6000  # D: explains the small policyengine.py vs policyengine_us difference -> checks/crosspath_sample.json
../.venv/bin/python merge_checks.py        # folds checks, gap explanations and dataset note into ../national.json
