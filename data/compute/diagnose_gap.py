"""Part D diagnostic: why does -Δincome_tax differ from Δctc_value?

national.py found tax units where the reform's federal income tax change is
smaller than the change in ``ctc_value``. This script:

1. Reads the two output datasets that national.py's Simulation.ensure() saved
   in ../pe_data (baseline = the one with the lower weighted CTC total) and
   lists the tax units with |-Δincome_tax - Δctc_value| > $1 and their
   households.
2. Re-runs just those households through BOTH paths with extra variables:
   (a) policyengine.py Simulation on the year-2026 dataset subset;
   (b) policyengine_us.Microsimulation on a subset of the raw bundle .h5
       written to checks/residual_subset_2024.h5.
3. Writes checks/gap_diagnostic.json.

Run: ../.venv/bin/python diagnose_gap.py
"""

from __future__ import annotations

import datetime
import glob
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

from policyengine.core import Parameter, ParameterValue, Policy, Simulation  # noqa: E402
from policyengine.tax_benefit_models.us import (  # noqa: E402
    PolicyEngineUSDataset,
    USYearData,
    us_latest,
)
from policyengine.tax_benefit_models.us.spm import resolve_spm_selection  # noqa: E402

CHECKS = DATA_DIR / "compute" / "checks"
CHECKS.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 1. residual units
outs = sorted(glob.glob(str(PE_DATA_DIR / "*-spm-*.h5")))
assert len(outs) == 2, outs
tabs = []
for path in outs:
    with pd.HDFStore(path, "r") as st:
        tabs.append((path, st["tax_unit"], st["person"]))
tabs.sort(key=lambda t: float((t[1]["ctc"] * t[1]["tax_unit_weight"]).sum()))
(bpath, tb, pb), (rpath, tr, _) = tabs
assert (tb["tax_unit_id"].values == tr["tax_unit_id"].values).all()
w = tb["tax_unit_weight"].astype(float).values
d_tax = tr["income_tax"].astype(float).values - tb["income_tax"].astype(float).values
d_val = tr["ctc_value"].astype(float).values - tb["ctc_value"].astype(float).values
resid = -d_tax - d_val
flag = np.abs(resid) > 1
tu_ids = set(tb.loc[flag, "tax_unit_id"].astype(int))
hh_ids = sorted(set(pb.loc[pb["tax_unit_id"].isin(tu_ids), "household_id"].astype(int)))
timer.lap("residual_units")

VARS = [
    "income_tax",
    "income_tax_before_credits",
    "income_tax_capped_non_refundable_credits",
    "ctc",
    "ctc_value",
    "refundable_ctc",
    "ctc_limiting_tax_liability",
    "tax_unit_itemizes",
    "salt_deduction",
    "itemized_taxable_income_deductions",
    "standard_deduction",
    "taxable_income",
]

# ---------------------------------------------------------------- 2a. policyengine.py subset
year_h5 = PE_DATA_DIR / "populace_us_2024_year_2026.h5"
full = PolicyEngineUSDataset(name="full", description="full", filepath=str(year_h5), year=YEAR)
person = pd.DataFrame(full.data.person)
person = person[person["person_household_id"].isin(hh_ids)]
frames = {"person": person}
for ent in ("household", "marital_unit", "family", "spm_unit", "tax_unit"):
    df = pd.DataFrame(getattr(full.data, ent))
    frames[ent] = df[df[f"{ent}_id"].isin(set(person[f"person_{ent}_id"]))]
subset = PolicyEngineUSDataset(
    id="residual_subset",
    name="residual-subset",
    description="households with -d_income_tax != d_ctc_value",
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
pb_sim = Simulation(dataset=subset, tax_benefit_model_version=us_latest, extra_variables=extra)
pr_sim = Simulation(dataset=subset, tax_benefit_model_version=us_latest, policy=policy, extra_variables=extra)
pb_sim.run()
pr_sim.run()
pe_b = pd.DataFrame(pb_sim.output_dataset.data.tax_unit).set_index("tax_unit_id")
pe_r = pd.DataFrame(pr_sim.output_dataset.data.tax_unit).set_index("tax_unit_id")
timer.lap("policyengine_py_subset")

# ---------------------------------------------------------------- 2b. raw subset
bundle = bundle_us_dataset()
src = PE_DATA_DIR / bundle["path"]
raw_path = CHECKS / "residual_subset_2024.h5"
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

from policyengine_us import Microsimulation  # noqa: E402

spm_cfg = resolve_spm_selection()
rb_sim = Microsimulation(dataset=str(raw_path), spm=spm_cfg)
rr_sim = Microsimulation(
    dataset=str(raw_path),
    reform={REFORM_PARAMETER: {f"{REFORM_START}.{REFORM_STOP}": REFORM_VALUE}},
    spm=spm_cfg,
)


def raw_table(sim):
    ids = np.asarray(sim.calculate("tax_unit_id", YEAR).values).astype(int)
    data = {v: np.asarray(sim.calculate(v, YEAR).values).astype(float) for v in VARS}
    return pd.DataFrame(data, index=pd.Index(ids, name="tax_unit_id"))


raw_b = raw_table(rb_sim)
raw_r = raw_table(rr_sim)
timer.lap("raw_subset")

# ---------------------------------------------------------------- 3. compare
flag_ids = sorted(tu_ids)
rows = []
for t in flag_ids:
    rec = {"tax_unit_id": int(t), "weight": float(tb.set_index("tax_unit_id").loc[t, "tax_unit_weight"])}
    for label, frame in (("pepy_b", pe_b), ("pepy_r", pe_r), ("raw_b", raw_b), ("raw_r", raw_r)):
        for v in VARS:
            rec[f"{label}.{v}"] = float(frame.loc[t, v])
    rows.append(rec)
df = pd.DataFrame(rows)


def share(mask):
    return float(mask.mean())


summary = {
    "n_flagged_tax_units": len(flag_ids),
    "weighted_flagged_tax_units": float(w[flag].sum()),
    "weighted_gap_usd": float(np.sum(resid * w)),
    "subset_households": len(hh_ids),
    "pepy_share_itemizing_baseline": share(df["pepy_b.tax_unit_itemizes"] > 0),
    "pepy_share_limiting_liability_exceeds_income_tax_before_credits_baseline": share(
        df["pepy_b.ctc_limiting_tax_liability"] > df["pepy_b.income_tax_before_credits"] - df["pepy_b.income_tax_capped_non_refundable_credits"] + df["pepy_b.ctc_value"] - df["pepy_b.refundable_ctc"] + 1
    ),
    "pepy_mean_limiting_minus_actual_before_credits": float(
        (df["pepy_b.ctc_limiting_tax_liability"] - df["pepy_b.income_tax_before_credits"]).mean()
    ),
    "pepy_weighted_minus_d_income_tax": float(np.sum(-(df["pepy_r.income_tax"] - df["pepy_b.income_tax"]) * df["weight"])),
    "pepy_weighted_d_ctc_value": float(np.sum((df["pepy_r.ctc_value"] - df["pepy_b.ctc_value"]) * df["weight"])),
    "raw_weighted_minus_d_income_tax": float(np.sum(-(df["raw_r.income_tax"] - df["raw_b.income_tax"]) * df["weight"])),
    "raw_weighted_d_ctc_value": float(np.sum((df["raw_r.ctc_value"] - df["raw_b.ctc_value"]) * df["weight"])),
    "raw_share_itemizing_baseline": share(df["raw_b.tax_unit_itemizes"] > 0),
    "raw_mean_limiting_minus_actual_before_credits": float(
        (df["raw_b.ctc_limiting_tax_liability"] - df["raw_b.income_tax_before_credits"]).mean()
    ),
    "max_abs_diff_between_paths": {
        v: float(np.max(np.abs(df[f"pepy_b.{v}"] - df[f"raw_b.{v}"]))) for v in VARS
    },
}
res = {
    "meta": {
        "description": "Diagnostic for the revenue-vs-ctc_value gap (Part D).",
        "baseline_output_file": bpath,
        "reform_output_file": rpath,
        "raw_subset_file": str(raw_path),
        "versions": package_versions(),
        "runtime": timer.summary(),
        "script": "compute/diagnose_gap.py",
    },
    "summary": summary,
    "tax_units": df.to_dict(orient="records"),
}
write_json(CHECKS / "gap_diagnostic.json", res)
print(pd.Series({k: v for k, v in summary.items() if k != "max_abs_diff_between_paths"}))
print(pd.Series(summary["max_abs_diff_between_paths"]))
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
show = ["tax_unit_id", "pepy_b.income_tax_before_credits", "pepy_b.ctc_limiting_tax_liability", "raw_b.ctc_limiting_tax_liability", "pepy_b.tax_unit_itemizes", "raw_b.tax_unit_itemizes", "pepy_b.salt_deduction", "pepy_b.income_tax", "raw_b.income_tax", "pepy_r.income_tax", "raw_r.income_tax"]
print(df[show].head(12))
