"""Parts B, C and the budget half of D: national 2026 microsimulation.

Interface: policyengine.py (latest release) with its release-bundle default
US dataset, via the documented canonical flow:

    datasets = pe.us.ensure_datasets(years=[2026], data_folder=...)
    baseline = Simulation(dataset=..., tax_benefit_model_version=pe.us.model)
    reform   = Simulation(..., policy=Policy(...))
    analysis = economic_impact_analysis(baseline, reform)

The bundle's dataset file is identified by sha256 against the release
manifest; to avoid re-downloading 827 MB we point ``data_folder`` at a
symlink to the byte-identical Hugging Face cache blob (policyengine.py
re-hashes it and only reuses it if the sha256 matches the manifest).

Run: ../.venv/bin/python national.py   (from this directory)
Writes: ../national.json and ../households_sample.json
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DATA_DIR,
    PE_DATA_DIR,
    REFORM_PARAMETER,
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
import pandas as pd  # noqa: E402

import policyengine as pe  # noqa: E402
from policyengine.core import Parameter, ParameterValue, Policy, Simulation  # noqa: E402
from policyengine.outputs.decile_analysis import _prepare_decile_analysis  # noqa: E402
from policyengine.outputs.poverty import (  # noqa: E402
    calculate_us_poverty_by_age,
)
from policyengine.tax_benefit_models.us import (  # noqa: E402
    economic_impact_analysis,
    ensure_datasets,
    us_latest,
)

timer.lap("imports")

SAMPLE_N = 12_000
SAMPLE_SEED = 20260924

# ------------------------------------------------------------ dataset
bundle = bundle_us_dataset()
source_h5 = PE_DATA_DIR / bundle["path"]
source_sha = sha256_file(source_h5)
assert source_sha == bundle["expected_sha256"], (source_sha, bundle["expected_sha256"])
timer.lap("hash_source_dataset")

datasets = ensure_datasets(years=[YEAR], data_folder=str(PE_DATA_DIR))
assert len(datasets) == 1, datasets.keys()
dataset_key, dataset = next(iter(datasets.items()))
year_h5 = Path(dataset.filepath)
year_sha = sha256_file(year_h5)
timer.lap("ensure_datasets_year_2026")

# Smoke-test mode only (never used for the published numbers): restrict to
# the first N households and write to compute/checks/test_*.json instead.
TEST_N = int(os.environ.get("PE30_TEST_HOUSEHOLDS", "0"))
OUT_NATIONAL = DATA_DIR / "national.json"
OUT_SAMPLE = DATA_DIR / "households_sample.json"
if TEST_N:
    from microdf import MicroDataFrame

    from policyengine.tax_benefit_models.us import PolicyEngineUSDataset, USYearData

    full = dataset.data
    person = pd.DataFrame(full.person)
    keep_hh = set(pd.DataFrame(full.household)["household_id"].iloc[:TEST_N])
    person = person[person["person_household_id"].isin(keep_hh)]
    frames = {"person": person}
    for ent in ("household", "marital_unit", "family", "spm_unit", "tax_unit"):
        df = pd.DataFrame(getattr(full, ent))
        frames[ent] = df[df[f"{ent}_id"].isin(set(person[f"person_{ent}_id"]))]
    dataset = PolicyEngineUSDataset(
        id="smoke_test",
        name="smoke-test",
        description="first N households (smoke test only)",
        filepath=None,
        year=YEAR,
        data=USYearData(**{e: MicroDataFrame(f.reset_index(drop=True), weights=f"{e}_weight") for e, f in frames.items()}),
    )
    OUT_NATIONAL = DATA_DIR / "compute" / "checks" / "test_national.json"
    OUT_SAMPLE = DATA_DIR / "compute" / "checks" / "test_households_sample.json"

# ------------------------------------------------------------ reform
reform_policy = Policy(
    name="CTC base amount $3,000 (2026)",
    parameter_values=[
        ParameterValue(
            parameter=Parameter(
                name=REFORM_PARAMETER,
                tax_benefit_model_version=us_latest,
                data_type=float,
            ),
            start_date=datetime.datetime(YEAR, 1, 1),
            end_date=datetime.datetime(YEAR, 12, 31),
            value=REFORM_VALUE,
        )
    ],
)

EXTRA = {
    "household": ["state_fips", "state_code_str", "household_income_decile"],
    "tax_unit": [
        "ctc_value",
        "refundable_ctc",
        "non_refundable_ctc",
        "income_tax_before_credits",
    ],
}

baseline = Simulation(dataset=dataset, tax_benefit_model_version=us_latest, extra_variables=EXTRA)
reform = Simulation(
    dataset=dataset,
    tax_benefit_model_version=us_latest,
    policy=reform_policy,
    extra_variables=EXTRA,
)

analysis = economic_impact_analysis(baseline, reform)
timer.lap("economic_impact_analysis")

child_pov_base = {p.poverty_type: p for p in calculate_us_poverty_by_age(baseline).outputs if p.filter_group == "child"}
child_pov_ref = {p.poverty_type: p for p in calculate_us_poverty_by_age(reform).outputs if p.filter_group == "child"}
timer.lap("child_poverty")

# ------------------------------------------------------------ raw arrays
bd, rd = baseline.output_dataset.data, reform.output_dataset.data


def f64(s) -> np.ndarray:
    return np.asarray(s, dtype=np.float64)


hh_b = pd.DataFrame(bd.household)
hh_r = pd.DataFrame(rd.household)
tu_b = pd.DataFrame(bd.tax_unit)
tu_r = pd.DataFrame(rd.tax_unit)
p_b = pd.DataFrame(bd.person)
assert (hh_b["household_id"].values == hh_r["household_id"].values).all()
assert (tu_b["tax_unit_id"].values == tu_r["tax_unit_id"].values).all()

hw = f64(hh_b["household_weight"])
tw = f64(tu_b["tax_unit_weight"])
total_households = float(hw.sum())

d_net = f64(hh_r["household_net_income"]) - f64(hh_b["household_net_income"])


def wsum_change(df_b, df_r, var, w):
    return float(np.sum((f64(df_r[var]) - f64(df_b[var])) * w))


budget = {
    "federal_income_tax_revenue_change": wsum_change(tu_b, tu_r, "income_tax", tw),
    "household_net_income_total_change": float(np.sum(d_net * hw)),
    "state_income_tax_revenue_change": wsum_change(tu_b, tu_r, "state_income_tax", tw),
    "employee_payroll_tax_change": wsum_change(tu_b, tu_r, "employee_payroll_tax", tw),
    "household_tax_change": wsum_change(hh_b, hh_r, "household_tax", hw),
    "household_benefits_change": wsum_change(hh_b, hh_r, "household_benefits", hw),
    "ctc_allowed_change": wsum_change(tu_b, tu_r, "ctc", tw),
    "ctc_value_change": wsum_change(tu_b, tu_r, "ctc_value", tw),
    "refundable_ctc_change": wsum_change(tu_b, tu_r, "refundable_ctc", tw),
    "non_refundable_ctc_change": wsum_change(tu_b, tu_r, "non_refundable_ctc", tw),
    "eitc_change": wsum_change(tu_b, tu_r, "eitc", tw),
    "ctc_allowed_baseline_total": float(np.sum(f64(tu_b["ctc"]) * tw)),
    "ctc_allowed_reform_total": float(np.sum(f64(tu_r["ctc"]) * tw)),
    "ctc_value_baseline_total": float(np.sum(f64(tu_b["ctc_value"]) * tw)),
    "ctc_value_reform_total": float(np.sum(f64(tu_r["ctc_value"]) * tw)),
    "federal_income_tax_baseline_total": float(np.sum(f64(tu_b["income_tax"]) * tw)),
    "federal_income_tax_reform_total": float(np.sum(f64(tu_r["income_tax"]) * tw)),
}
bi = analysis.budgetary_impact
budget["policyengine_py_budgetary_impact"] = {
    "federal": bi.federal,
    "state": bi.state,
    "unattributed": bi.unattributed,
    "total": bi.total,
    "sign_convention": "positive = government better off; negative = cost",
}
# Headline cost (positive number = cost to the federal government).
budget["federal_budget_cost_2026_usd"] = -budget["federal_income_tax_revenue_change"]

# Part D: second aggregation and the gap.
gap_value = -budget["federal_income_tax_revenue_change"] - budget["ctc_value_change"]
gap_allowed = -budget["federal_income_tax_revenue_change"] - budget["ctc_allowed_change"]
tu_d_tax = f64(tu_r["income_tax"]) - f64(tu_b["income_tax"])
tu_d_ctcv = f64(tu_r["ctc_value"]) - f64(tu_b["ctc_value"])
tu_d_ctc = f64(tu_r["ctc"]) - f64(tu_b["ctc"])
resid = -tu_d_tax - tu_d_ctcv
n_resid = int(np.sum(np.abs(resid) > 1))
w_resid = float(np.sum(tw[np.abs(resid) > 1]))
unrealized = tu_d_ctc - tu_d_ctcv
budget["second_aggregation_check"] = {
    "minus_federal_income_tax_change": -budget["federal_income_tax_revenue_change"],
    "sum_weighted_ctc_value_change": budget["ctc_value_change"],
    "sum_weighted_ctc_allowed_change": budget["ctc_allowed_change"],
    "gap_revenue_vs_ctc_value": gap_value,
    "gap_revenue_vs_ctc_allowed": gap_allowed,
    "gap_revenue_vs_ctc_value_share": gap_value / budget["ctc_value_change"] if budget["ctc_value_change"] else None,
    "tax_units_with_abs_residual_over_1usd": n_resid,
    "weighted_tax_units_with_abs_residual_over_1usd": w_resid,
    "weighted_ctc_allowed_but_not_realized_change": float(np.sum(unrealized * tw)),
    "tax_units_with_unrealized_ctc_increase_over_1usd": int(np.sum(unrealized > 1)),
    "weighted_tax_units_with_unrealized_ctc_increase_over_1usd": float(np.sum(tw[unrealized > 1])),
    "net_income_vs_federal_revenue_gap": budget["household_net_income_total_change"]
    + budget["federal_income_tax_revenue_change"],
}

# ------------------------------------------------------------ winners
gain = d_net > 1
share_households_gaining = float(hw[gain].sum() / total_households)
share_households_losing = float(hw[d_net < -1].sum() / total_households)

person_hh = p_b["household_id"].values
pw = f64(p_b["person_weight"])
hh_gain_map = pd.Series(gain, index=hh_b["household_id"].values)
person_in_gaining = hh_gain_map.reindex(person_hh).values.astype(bool)
share_people_in_gaining_households = float(pw[person_in_gaining].sum() / pw.sum())
# Same thing with household_weight x household_count_people (household-level).
hcount = f64(hh_b["household_count_people"])
share_people_alt = float((hw * hcount)[gain].sum() / (hw * hcount).sum())

# ------------------------------------------------------------ deciles
dec = []
for d in analysis.decile_impacts.outputs:
    dec.append(
        {
            "decile": d.decile,
            "average_change_household_net_income": d.absolute_change,
            "baseline_mean": d.baseline_mean,
            "reform_mean": d.reform_mean,
            "relative_change_percent": d.relative_change,
            "households_better_off_weighted": d.count_better_off,
            "households_worse_off_weighted": d.count_worse_off,
            "households_no_change_weighted": d.count_no_change,
        }
    )
prep = _prepare_decile_analysis(
    baseline,
    reform,
    income_variable="household_net_income",
    decile_variable=None,
    entity="household",
    quantiles=10,
)
pe_py_decile = np.asarray(prep.groups.fillna(-1).astype(int))
excluded_negative = float(hw[pe_py_decile == -1].sum())

# Alternative: policyengine-us household_income_decile variable.
pe_us_decile = np.asarray(hh_b["household_income_decile"]).astype(int)
dec_alt = []
for k in range(1, 11):
    m = pe_us_decile == k
    dec_alt.append({"decile": k, "average_change_household_net_income": float(np.sum(d_net[m] * hw[m]) / np.sum(hw[m]))})
decile_agreement = float(hw[pe_us_decile == pe_py_decile].sum() / total_households)

# ------------------------------------------------------------ poverty
def pov(collection, ptype):
    for p in collection.outputs:
        if p.poverty_type == ptype:
            return p
    raise KeyError(ptype)


poverty = {}
for ptype in ("spm", "spm_deep"):
    ab, ar = pov(analysis.baseline_poverty, ptype), pov(analysis.reform_poverty, ptype)
    cb, cr = child_pov_base[ptype], child_pov_ref[ptype]
    poverty[ptype] = {
        "all_people": {
            "rate_baseline": ab.rate,
            "rate_reform": ar.rate,
            "headcount_baseline": ab.headcount,
            "headcount_reform": ar.headcount,
            "population": ab.total_population,
            "people_lifted_out": ab.headcount - ar.headcount,
            "rate_change_pp": 100 * (ar.rate - ab.rate),
            "relative_change": (ar.rate - ab.rate) / ab.rate if ab.rate else None,
        },
        "children_under_18": {
            "rate_baseline": cb.rate,
            "rate_reform": cr.rate,
            "headcount_baseline": cb.headcount,
            "headcount_reform": cr.headcount,
            "population": cb.total_population,
            "children_lifted_out": cb.headcount - cr.headcount,
            "rate_change_pp": 100 * (cr.rate - cb.rate),
            "relative_change": (cr.rate - cb.rate) / cb.rate if cb.rate else None,
            "filter": "age <= 17 (policyengine.py AGE_GROUPS['child'])",
        },
    }

# Direct recomputation of child SPM poverty from person rows (check).
spm_b = pd.DataFrame(bd.spm_unit).set_index("spm_unit_id")["spm_unit_is_in_spm_poverty"]
spm_r = pd.DataFrame(rd.spm_unit).set_index("spm_unit_id")["spm_unit_is_in_spm_poverty"]
p_spm = p_b["spm_unit_id"].values
child = f64(p_b["age"]) < 18
pov_b_person = spm_b.reindex(p_spm).values.astype(bool)
pov_r_person = spm_r.reindex(p_spm).values.astype(bool)
direct_child = {
    "rate_baseline": float(pw[child & pov_b_person].sum() / pw[child].sum()),
    "rate_reform": float(pw[child & pov_r_person].sum() / pw[child].sum()),
    "children_lifted_out": float(pw[child & pov_b_person].sum() - pw[child & pov_r_person].sum()),
    "children_pushed_in": float(pw[child & ~pov_b_person & pov_r_person].sum()),
}

timer.lap("aggregates")

# ------------------------------------------------------------ Part C sample
n_children = (
    pd.Series(child.astype(int), index=p_b.index)
    .groupby(p_b["household_id"].values)
    .sum()
    .reindex(hh_b["household_id"].values)
    .fillna(0)
    .astype(int)
    .values
)
state_fips = np.asarray(hh_b["state_fips"]).astype(int)
state_code = np.asarray(hh_b["state_code_str"]).astype(str)
cd = np.asarray(hh_b["congressional_district_geoid"]).astype(int)
net_b = f64(hh_b["household_net_income"])

rng = np.random.default_rng(SAMPLE_SEED)
probs = hw / hw.sum()
idx = rng.choice(len(hw), size=SAMPLE_N, replace=True, p=probs)
dots_per = total_households / SAMPLE_N

columns = [
    "household_id",
    "state_fips",
    "state_code",
    "congressional_district_geoid",
    "household_net_income_baseline",
    "household_net_income_change",
    "children_under_18",
    "decile",
    "household_weight",
    "weight_share",
]
rows = []
hid = np.asarray(hh_b["household_id"]).astype(int)
for i in idx:
    rows.append(
        [
            int(hid[i]),
            int(state_fips[i]),
            str(state_code[i]),
            int(cd[i]) if cd[i] > 0 else None,
            round(float(net_b[i]), 2),
            round(float(d_net[i]), 2),
            int(n_children[i]),
            int(pe_py_decile[i]),
            round(float(hw[i]), 4),
            float(probs[i]),
        ]
    )
sample_meta_extra = {
    "sampling": (
        "numpy.random.default_rng(20260924).choice(n_households, size=12000, replace=True, "
        "p=household_weight / household_weight.sum()) over the baseline output household table"
    ),
    "n_draws": SAMPLE_N,
    "unique_households_drawn": int(len(np.unique(idx))),
    "total_weighted_households": total_households,
    "households_per_dot": dots_per,
    "columns_doc": {
        "household_id": "dataset household_id",
        "state_fips": "state FIPS (int)",
        "state_code": "two-letter state code (policyengine-us state_code_str)",
        "congressional_district_geoid": "SSDD integer (state FIPS * 100 + district); null if 0/missing",
        "household_net_income_baseline": "USD 2026, baseline",
        "household_net_income_change": "USD 2026, reform minus baseline",
        "children_under_18": "count of household members with age < 18",
        "decile": "policyengine.py household_net_income decile (1-10; -1 = negative baseline net income, excluded from deciles)",
        "household_weight": "survey weight (households represented by this record)",
        "weight_share": "household_weight / total weighted households = per-draw selection probability",
    },
    "sample_weighted_mean_check": {
        "share_gaining_in_sample": float(np.mean(d_net[idx] > 1)),
        "share_gaining_population": share_households_gaining,
    },
}
timer.lap("sample")

# ------------------------------------------------------------ outputs
versions = package_versions()
dataset_meta = {
    **bundle,
    "local_source_path": str(source_h5),
    "local_source_resolved_path": str(Path(os.path.realpath(source_h5))),
    "local_source_sha256": source_sha,
    "sha256_matches_manifest": source_sha == bundle["expected_sha256"],
    "year_2026_dataset_key": dataset_key,
    "year_2026_dataset_path": str(year_h5),
    "year_2026_dataset_sha256": year_sha,
    "year_2026_note": "Produced by policyengine.py create_datasets: every input variable of the bundle dataset computed for 2026 by policyengine-us (its uprating), weights mapped to all entities.",
    "n_households": int(len(hh_b)),
    "n_people": int(len(p_b)),
    "n_tax_units": int(len(tu_b)),
}
spm_meta = {
    "spm_config": baseline.spm_config,
}

national = {
    "meta": {
        "description": "National 2026 static microsimulation, baseline vs reform, PolicyEngine US via policyengine.py.",
        "reform": reform_description(),
        "interface": "policyengine.py Simulation + economic_impact_analysis (policyengine-us Microsimulation underneath)",
        "dataset": dataset_meta,
        "spm": spm_meta,
        "behavioral_responses": "none (static; no labor-supply elasticities set)",
        "versions": versions,
        "runtime": None,
        "script": "compute/national.py",
    },
    "budget": budget,
    "households_total_weighted": total_households,
    "people_total_weighted": float(pw.sum()),
    "winners": {
        "share_households_gaining_over_1usd": share_households_gaining,
        "share_households_losing_over_1usd": share_households_losing,
        "weighted_households_gaining_over_1usd": float(hw[gain].sum()),
        "share_people_in_gaining_households": share_people_in_gaining_households,
        "share_people_in_gaining_households_alt_hhweight_x_count": share_people_alt,
        "average_gain_among_gaining_households": float(np.sum(d_net[gain] * hw[gain]) / hw[gain].sum()),
        "average_change_all_households": float(np.sum(d_net * hw) / total_households),
    },
    "deciles": {
        "definition": (
            "policyengine.py calculate_decile_impacts (used by economic_impact_analysis): households ranked by "
            "baseline household_net_income with weights household_weight x household_count_people (so each decile "
            "holds ~10% of people); households with negative baseline net income get -1 and are excluded; "
            "average change = household-weighted mean of reform minus baseline household_net_income within decile."
        ),
        "weighted_households_excluded_negative_income": excluded_negative,
        "by_decile": dec,
        "alt_policyengine_us_household_income_decile": {
            "definition": "policyengine-us household_income_decile variable (MicroSeries.decile_rank on person-weighted household_net_income; negatives -1)",
            "by_decile": dec_alt,
            "household_weighted_share_same_decile_as_primary": decile_agreement,
        },
    },
    "poverty": poverty,
    "poverty_direct_recompute_children_spm": direct_child,
    "program_statistics": [
        {
            "program": p.program_name,
            "baseline_total": p.baseline_total,
            "reform_total": p.reform_total,
            "change": p.change,
        }
        for p in analysis.program_statistics.outputs
    ],
    "inequality": {
        "gini_baseline": analysis.baseline_inequality.gini,
        "gini_reform": analysis.reform_inequality.gini,
    },
}
national["meta"]["runtime"] = timer.summary()
write_json(OUT_NATIONAL, national)

sample = {
    "meta": {
        "description": "Weighted with-replacement sample of households for the dot-map visual.",
        "reform": reform_description(),
        "dataset": dataset_meta,
        "versions": versions,
        "runtime": national["meta"]["runtime"],
        "script": "compute/national.py",
        **sample_meta_extra,
    },
    "columns": columns,
    "rows": rows,
}
write_json(OUT_SAMPLE, sample, compact=True)

print("budget cost (federal income tax revenue change):", budget["federal_income_tax_revenue_change"])
print("net income total change:", budget["household_net_income_total_change"])
print("ctc_value change:", budget["ctc_value_change"], "ctc change:", budget["ctc_allowed_change"])
print("households:", total_households, "share gaining:", share_households_gaining, "people share:", share_people_in_gaining_households)
print("child spm:", poverty["spm"]["children_under_18"])
print("all spm:", poverty["spm"]["all_people"])
print("deciles:", [round(d["average_change_household_net_income"] or 0, 2) for d in dec])
print("runtime:", national["meta"]["runtime"])
