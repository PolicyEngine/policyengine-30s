"""Part D (extra): recompute the headline national numbers through a second path.

policyengine.py (national.py) first materializes a year-2026 dataset with
create_datasets and then runs its own Simulation wrapper. This script skips
policyengine.py's dataset and simulation layers entirely and runs
``policyengine_us.Microsimulation`` directly on the same bundle .h5 (verified
by sha256), baseline and reform, for period 2026. Only the SPM measurement
selection is resolved from the policyengine.py bundle (the country package
requires one).

Run: ../.venv/bin/python national_raw_check.py   (from this directory)
Writes: checks/national_raw_check.json (summarised into national.json by merge_checks.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DATA_DIR,
    PE_DATA_DIR,
    REFORM_PARAMETER,
    REFORM_START,
    REFORM_STOP,
    REFORM_VALUE,
    YEAR,
    Timer,
    bundle_us_dataset,
    package_versions,
    reform_description,
    sha256_file,
    write_json,
)

timer = Timer()
import numpy as np  # noqa: E402
from policyengine_us import Microsimulation  # noqa: E402

from policyengine.tax_benefit_models.us.spm import resolve_spm_selection  # noqa: E402

timer.lap("imports")

bundle = bundle_us_dataset()
path = PE_DATA_DIR / bundle["path"]
sha = sha256_file(path)
assert sha == bundle["expected_sha256"]
timer.lap("hash")

REFORM = {REFORM_PARAMETER: {f"{REFORM_START}.{REFORM_STOP}": REFORM_VALUE}}
spm_cfg = resolve_spm_selection()

base = Microsimulation(dataset=str(path), spm=spm_cfg)
ref = Microsimulation(dataset=str(path), reform=REFORM, spm=spm_cfg)
timer.lap("construct")


def arr(sim, var, map_to=None):
    return np.asarray(sim.calculate(var, YEAR, map_to=map_to).values, dtype=np.float64)


hw = arr(base, "household_weight")
tw = arr(base, "tax_unit_weight")
pw = arr(base, "person_weight")

out = {}
for var, w in (("income_tax", tw), ("ctc_value", tw), ("ctc", tw), ("state_income_tax", tw), ("household_net_income", hw)):
    b = arr(base, var)
    r = arr(ref, var)
    out[f"{var}_weighted_change"] = float(np.sum((r - b) * w))
    out[f"{var}_baseline_total"] = float(np.sum(b * w))
    if var == "household_net_income":
        d_net = r - b
timer.lap("aggregates")

age = arr(base, "age")
child = age < 18
pov_b = arr(base, "spm_unit_is_in_spm_poverty", map_to="person") > 0
pov_r = arr(ref, "spm_unit_is_in_spm_poverty", map_to="person") > 0
timer.lap("poverty")

hh_people = arr(base, "household_count_people")
res = {
    "meta": {
        "description": "Second-path national check: policyengine_us.Microsimulation directly on the bundle dataset.",
        "reform": reform_description(),
        "reform_dict_passed": REFORM,
        "dataset_path": str(path),
        "dataset_sha256": sha,
        "dataset_uri": bundle["default_dataset_uri"],
        "spm_config": spm_cfg,
        "versions": package_versions(),
        "runtime": None,
        "script": "compute/national_raw_check.py",
    },
    **out,
    "federal_budget_cost_2026_usd": -out["income_tax_weighted_change"],
    "households_total_weighted": float(hw.sum()),
    "people_total_weighted": float(pw.sum()),
    "share_households_gaining_over_1usd": float(hw[d_net > 1].sum() / hw.sum()),
    "share_people_in_gaining_households_hhweight_x_count": float((hw * hh_people)[d_net > 1].sum() / (hw * hh_people).sum()),
    "spm_child_rate_baseline": float(pw[child & pov_b].sum() / pw[child].sum()),
    "spm_child_rate_reform": float(pw[child & pov_r].sum() / pw[child].sum()),
    "spm_children_lifted_out": float(pw[child & pov_b].sum() - pw[child & pov_r].sum()),
    "spm_all_rate_baseline": float(pw[pov_b].sum() / pw.sum()),
    "spm_all_rate_reform": float(pw[pov_r].sum() / pw.sum()),
}
res["meta"]["runtime"] = timer.summary()
write_json(DATA_DIR / "compute" / "checks" / "national_raw_check.json", res)
for k, v in res.items():
    if k != "meta":
        print(k, v)
print(res["meta"]["runtime"])
