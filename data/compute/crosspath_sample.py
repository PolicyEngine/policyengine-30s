"""Part D diagnostic: why do the two national paths differ by ~0.24%?

national.py (policyengine.py) and national_raw_check.py (policyengine_us
Microsimulation directly) agree on CTC allowed, weights, households and child
poverty, but differ slightly on the income-tax change. This script runs both
paths on a uniform random subset of households (seed 20260924) with extra tax
variables and attributes the per-tax-unit differences.

Run: ../.venv/bin/python crosspath_sample.py [N_HOUSEHOLDS]   (default 6000)
Writes: checks/crosspath_sample.json
"""

from __future__ import annotations

import datetime
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
    write_json,
)

timer = Timer()
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from microdf import MicroDataFrame  # noqa: E402
from policyengine_us import Microsimulation  # noqa: E402

from policyengine.core import Parameter, ParameterValue, Policy, Simulation  # noqa: E402
from policyengine.tax_benefit_models.us import PolicyEngineUSDataset, USYearData, us_latest  # noqa: E402
from policyengine.tax_benefit_models.us.spm import resolve_spm_selection  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
CHECKS = DATA_DIR / "compute" / "checks"
VARS = [
    "income_tax",
    "income_tax_before_credits",
    "ctc",
    "ctc_value",
    "refundable_ctc",
    "ctc_limiting_tax_liability",
    "tax_unit_itemizes",
    "salt_deduction",
]

year_h5 = PE_DATA_DIR / "populace_us_2024_year_2026.h5"
full = PolicyEngineUSDataset(name="full", description="full", filepath=str(year_h5), year=YEAR)
all_hh = pd.DataFrame(full.data.household)["household_id"].astype(int).values
rng = np.random.default_rng(20260924)
hh_ids = sorted(rng.choice(all_hh, size=min(N, len(all_hh)), replace=False).tolist())
timer.lap("load")

# policyengine.py path
person = pd.DataFrame(full.data.person)
person = person[person["person_household_id"].isin(hh_ids)]
frames = {"person": person}
for ent in ("household", "marital_unit", "family", "spm_unit", "tax_unit"):
    df = pd.DataFrame(getattr(full.data, ent))
    frames[ent] = df[df[f"{ent}_id"].isin(set(person[f"person_{ent}_id"]))]
subset = PolicyEngineUSDataset(
    id="crosspath_subset",
    name="crosspath-subset",
    description="uniform random household subset",
    filepath=None,
    year=YEAR,
    data=USYearData(**{e: MicroDataFrame(f.reset_index(drop=True), weights=f"{e}_weight") for e, f in frames.items()}),
)
policy = Policy(
    name="CTC $3,000",
    parameter_values=[
        ParameterValue(
            parameter=Parameter(name=REFORM_PARAMETER, tax_benefit_model_version=us_latest, data_type=float),
            start_date=datetime.datetime(YEAR, 1, 1),
            end_date=datetime.datetime(YEAR, 12, 31),
            value=REFORM_VALUE,
        )
    ],
)
extra = {"tax_unit": VARS}
sb = Simulation(dataset=subset, tax_benefit_model_version=us_latest, extra_variables=extra)
sr = Simulation(dataset=subset, tax_benefit_model_version=us_latest, policy=policy, extra_variables=extra)
sb.run()
sr.run()
pe_b = pd.DataFrame(sb.output_dataset.data.tax_unit).set_index("tax_unit_id")
pe_r = pd.DataFrame(sr.output_dataset.data.tax_unit).set_index("tax_unit_id")
timer.lap("policyengine_py")

# raw path
bundle = bundle_us_dataset()
src = PE_DATA_DIR / bundle["path"]
raw_path = CHECKS / "crosspath_subset_2024.h5"
with pd.HDFStore(src, "r") as st:
    tp = st["_time_period"]
    rp = st["person"]
    rp = rp[rp["person_household_id"].isin(hh_ids)]
    raw_frames = {"person": rp}
    for ent in ("household", "marital_unit", "family", "spm_unit", "tax_unit"):
        df = st[ent]
        raw_frames[ent] = df[df[f"{ent}_id"].isin(set(rp[f"person_{ent}_id"]))]
with pd.HDFStore(raw_path, "w") as out:
    out.put("_time_period", tp, format="table")
    for ent, df in raw_frames.items():
        out.put(ent, df, format="table")
spm_cfg = resolve_spm_selection()
rb = Microsimulation(dataset=str(raw_path), spm=spm_cfg)
rr = Microsimulation(
    dataset=str(raw_path),
    reform={REFORM_PARAMETER: {f"{REFORM_START}.{REFORM_STOP}": REFORM_VALUE}},
    spm=spm_cfg,
)


def raw_table(sim):
    ids = np.asarray(sim.calculate("tax_unit_id", YEAR).values).astype(int)
    data = {v: np.asarray(sim.calculate(v, YEAR).values).astype(float) for v in VARS}
    return pd.DataFrame(data, index=pd.Index(ids, name="tax_unit_id"))


raw_b = raw_table(rb)
raw_r = raw_table(rr)
raw_path.unlink()  # scratch copy only
timer.lap("raw")

ids = pe_b.index
raw_b = raw_b.loc[ids]
raw_r = raw_r.loc[ids]
w = pe_b["tax_unit_weight"].astype(float).values
f = lambda s: np.asarray(s, dtype=float)  # noqa: E731

d_tax_pe = f(pe_r["income_tax"]) - f(pe_b["income_tax"])
d_tax_raw = f(raw_r["income_tax"]) - f(raw_b["income_tax"])
diff = d_tax_pe - d_tax_raw
differs = np.abs(diff) > 1
lim_differs = (np.abs(f(pe_b["ctc_limiting_tax_liability"]) - f(raw_b["ctc_limiting_tax_liability"])) > 1) | (
    np.abs(f(pe_r["ctc_limiting_tax_liability"]) - f(raw_r["ctc_limiting_tax_liability"])) > 1
)
salt_pos = f(pe_b["salt_deduction"]) > 0
itemizes = f(pe_b["tax_unit_itemizes"]) > 0
lim_higher_pe = f(pe_b["ctc_limiting_tax_liability"]) - f(raw_b["ctc_limiting_tax_liability"])

summary = {
    "n_households": len(hh_ids),
    "n_tax_units": int(len(ids)),
    "max_abs_baseline_diff_by_variable": {
        v: float(np.max(np.abs(f(pe_b[v]) - f(raw_b[v])))) for v in VARS
    },
    "tax_units_where_d_income_tax_differs_over_1usd": int(differs.sum()),
    "of_which_ctc_limiting_tax_liability_differs": int((differs & lim_differs).sum()),
    "of_which_itemize_with_positive_salt": int((differs & itemizes & salt_pos).sum()),
    "tax_units_where_ctc_limiting_tax_liability_differs": int(lim_differs.sum()),
    "of_those_itemize_with_positive_salt": int((lim_differs & itemizes & salt_pos).sum()),
    "of_those_pepy_limiting_liability_higher": int((lim_differs & (lim_higher_pe > 0)).sum()),
    "weighted_d_income_tax_pepy": float(np.sum(d_tax_pe * w)),
    "weighted_d_income_tax_raw": float(np.sum(d_tax_raw * w)),
    "weighted_diff_all": float(np.sum(diff * w)),
    "weighted_diff_in_units_with_limiting_liability_difference": float(np.sum(diff[lim_differs] * w[lim_differs])),
    "weighted_d_ctc_value_pepy": float(np.sum((f(pe_r["ctc_value"]) - f(pe_b["ctc_value"])) * w)),
    "weighted_d_ctc_value_raw": float(np.sum((f(raw_r["ctc_value"]) - f(raw_b["ctc_value"])) * w)),
}
examples = []
for t in ids[differs][:15]:
    examples.append(
        {
            "tax_unit_id": int(t),
            **{f"pepy_b.{v}": float(pe_b.loc[t, v]) for v in VARS},
            **{f"raw_b.{v}": float(raw_b.loc[t, v]) for v in VARS},
            "pepy_r.income_tax": float(pe_r.loc[t, "income_tax"]),
            "raw_r.income_tax": float(raw_r.loc[t, "income_tax"]),
        }
    )
res = {
    "meta": {
        "description": "Cross-path diagnostic on a uniform random household subset.",
        "sampling": f"numpy.random.default_rng(20260924).choice(household_ids, size={N}, replace=False)",
        "versions": package_versions(),
        "runtime": timer.summary(),
        "script": "compute/crosspath_sample.py",
    },
    "summary": summary,
    "examples": examples,
}
write_json(CHECKS / "crosspath_sample.json", res)
for k, v in summary.items():
    print(k, v)
