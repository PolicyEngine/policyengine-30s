"""The UK national run: the personal allowance at £15,000 across the enhanced FRS, 2026-27.

Interface: policyengine.py 6.2.0 with its certified UK dataset (enhanced_frs_2024_25,
policyengine-uk-data 1.56.16, uprated to 2026 by ensure_datasets with the installed
policyengine-uk, 2.102.3), the same flow as the US national run:

    baseline = Simulation(dataset=..., tax_benefit_model_version=uk_latest)
    reform   = Simulation(..., policy=Policy(personal allowance 15,000 from 2026-01-01))
    analysis = economic_impact_analysis(baseline, reform)

policyengine-uk labels fiscal year 2026-27 as 2026 and reads it at 2026-01-01, so the
reform starts there; a 2026-04-06 start silently leaves the run on current law. The run
asserts that the largest allowance the model applied moved from £12,570 to £15,000 and that
nobody's fell; allowances tapered above £100,000 of adjusted net income move by less or not at all.

The dataset is UK survey microdata (Family Resources Survey, UK Data Service End User
Licence). Only aggregates leave data/uk/private/: data/uk/national.json is committed; the
12,000 weighted draws behind the map's dots go to data/uk/private/households_sample.json,
which is git-ignored and never redistributed.

Run from the repo root (needs a Hugging Face token with access to
policyengine/policyengine-uk-data-private in HF_TOKEN):
  uv run --no-project --python 3.13 --with-requirements tools/uk/requirements.pe-6.2.0.lock.txt \\
      python tools/uk/national.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
UK = ROOT / "data" / "uk"
PRIVATE = UK / "private"
sys.path.insert(0, str(HERE))

from uk_family import PA_NEW, PA_PATH, YEAR, FISCAL_YEAR, versions  # noqa: E402

t0 = time.time()
laps = {}


def lap(name):
    laps[name] = round(time.time() - t0, 1)


import policyengine.tax_benefit_models.uk.datasets as ukds  # noqa: E402
from policyengine.core import Parameter, ParameterValue, Policy, Simulation  # noqa: E402
from policyengine.outputs.decile_analysis import _prepare_decile_analysis  # noqa: E402
from policyengine.outputs.poverty import UK_POVERTY_VARIABLES, calculate_uk_poverty_by_age  # noqa: E402
from policyengine.tax_benefit_models.uk import economic_impact_analysis, ensure_datasets, uk_latest  # noqa: E402

lap("imports")

SAMPLE_N = 12_000
SAMPLE_SEED = 20260925
NI = "NI"  # sample key for Northern Ireland households, which carry no constituency code

# ------------------------------------------------------------ dataset
manifest = ukds.get_release_manifest("uk")
MODEL = versions()["policyengine-uk"]
assert manifest.certification.certified_for_model_version == MODEL, (manifest.certification, MODEL)
# ensure_datasets reuses any uprated year file it finds, whichever install built it. Uprating runs
# policyengine.py's create_datasets on policyengine-uk's model, so a file left by other versions would
# carry their 2026 into this run. A stamp beside it names the builder and the file's sha256; the file
# is reused only when both match, so a file rewritten by anything else (an older checkout of this
# script, a direct create_datasets call) is rebuilt too. The stamp goes with the file it describes.
year_file = PRIVATE / f"enhanced_frs_2024_25_year_{YEAR}.h5"
stamp = year_file.with_suffix(".built_with.json")
BUILDER = {k: versions()[k] for k in ("policyengine", "policyengine-uk")}
sha_of = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
if not (year_file.exists() and stamp.exists() and json.loads(stamp.read_text()) == {**BUILDER, "sha256": sha_of(year_file)}):
    year_file.unlink(missing_ok=True)
    stamp.unlink(missing_ok=True)
datasets = ensure_datasets(years=[YEAR], data_folder=str(PRIVATE))
assert len(datasets) == 1, list(datasets)
dataset_key, dataset = next(iter(datasets.items()))
assert year_file.exists(), year_file
stamp.write_text(json.dumps({**BUILDER, "sha256": sha_of(year_file)}) + "\n")
source = PRIVATE / "enhanced_frs_2024_25.h5"
source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
EXPECTED_SHA = "e433e532b17bd8ce76030156285816e33d44e93edabd2204adbef71d19a68712"  # policyengine-uk-data 1.56.16
assert source_sha == EXPECTED_SHA == manifest.certified_data_artifact.sha256, (source_sha, manifest.certified_data_artifact)
lap("dataset")

# ------------------------------------------------------------ reform
reform_policy = Policy(
    name=f"Personal allowance £{PA_NEW:,} ({FISCAL_YEAR})",
    parameter_values=[
        ParameterValue(
            parameter=Parameter(name=PA_PATH, tax_benefit_model_version=uk_latest, data_type=float),
            start_date=dt.datetime(YEAR, 1, 1),
            end_date=dt.datetime(YEAR, 12, 31),
            value=float(PA_NEW),
        )
    ],
)
EXTRA = {
    "household": ["region", "hbai_household_net_income"],
    "person": ["personal_allowance", "adjusted_net_income", "income_tax", "national_insurance"],
    "benunit": ["universal_credit", "pension_credit", "housing_benefit"],
}
baseline = Simulation(dataset=dataset, tax_benefit_model_version=uk_latest, extra_variables=EXTRA)
reform = Simulation(dataset=dataset, tax_benefit_model_version=uk_latest, policy=reform_policy, extra_variables=EXTRA)
analysis = economic_impact_analysis(baseline, reform)
lap("economic_impact_analysis")
child_b = {p.poverty_type: p for p in calculate_uk_poverty_by_age(baseline).outputs if p.filter_group == "child"}
child_r = {p.poverty_type: p for p in calculate_uk_poverty_by_age(reform).outputs if p.filter_group == "child"}
lap("child_poverty")

bd, rd = baseline.output_dataset.data, reform.output_dataset.data
f64 = lambda s: np.asarray(s, dtype=np.float64)
hh_b, hh_r = pd.DataFrame(bd.household), pd.DataFrame(rd.household)
p_b, p_r = pd.DataFrame(bd.person), pd.DataFrame(rd.person)
bu_b, bu_r = pd.DataFrame(bd.benunit), pd.DataFrame(rd.benunit)
assert (hh_b["household_id"].values == hh_r["household_id"].values).all()
assert (p_b["person_id"].values == p_r["person_id"].values).all()

# the reform moved the allowance the model applied, and nothing else about who is who
pa_b, pa_r = f64(p_b["personal_allowance"]), f64(p_r["personal_allowance"])
assert pa_b.max() == 12_570 and pa_r.max() == PA_NEW, (pa_b.max(), pa_r.max())
assert np.all(pa_r >= pa_b - 1e-6), "someone's allowance fell"
# who has no allowance at all: the taper takes the whole £15,000 once adjusted net income (less
# grossed-up Gift Aid) reaches £100,000 + 2 x £15,000
no_pa = (pa_b == 0) & (pa_r == 0)
ani = f64(p_b["adjusted_net_income"])
allowance = {
    "records_with_no_allowance_in_either_run": int(no_pa.sum()),
    "weighted_people_with_no_allowance_in_either_run": float(f64(p_b["person_weight"])[no_pa].sum()),
    "lowest_adjusted_net_income_among_them": float(ani[no_pa].min()) if no_pa.any() else None,
    "records_whose_allowance_rose": int((pa_r > pa_b + 1e-6).sum()),
    "records_whose_allowance_rose_by_the_full_2430": int((np.abs(pa_r - pa_b - (PA_NEW - 12_570)) < 1e-6).sum()),
}
assert allowance["lowest_adjusted_net_income_among_them"] is None or allowance["lowest_adjusted_net_income_among_them"] >= 100_000 + 2 * PA_NEW

hw, pw, bw = f64(hh_b["household_weight"]), f64(p_b["person_weight"]), f64(bu_b["benunit_weight"])
total_households = float(hw.sum())
d_net = f64(hh_r["household_net_income"]) - f64(hh_b["household_net_income"])
wsum = lambda b, r, var, w: float(np.sum((f64(r[var]) - f64(b[var])) * w))

budget = {
    "income_tax_revenue_change": wsum(p_b, p_r, "income_tax", pw),
    "national_insurance_revenue_change": wsum(p_b, p_r, "national_insurance", pw),
    "universal_credit_change": wsum(bu_b, bu_r, "universal_credit", bw),
    # outside policyengine.py's UK programme list, so outside net cost; most of the identity gap
    "housing_benefit_change": wsum(bu_b, bu_r, "housing_benefit", bw),
    "household_net_income_total_change": float(np.sum(d_net * hw)),
    "income_tax_baseline_total": float(np.sum(f64(p_b["income_tax"]) * pw)),
    "income_tax_reform_total": float(np.sum(f64(p_r["income_tax"]) * pw)),
}
# differential: policyengine.py's own programme statistics against the sums above
prog = {o.program_name: {"baseline_total": o.baseline_total, "reform_total": o.reform_total, "change": o.change,
                         "is_tax": o.is_tax} for o in analysis.program_statistics.outputs}
budget["policyengine_py_program_statistics"] = prog
for name, mine in (("income_tax", budget["income_tax_revenue_change"]), ("universal_credit", budget["universal_credit_change"])):
    assert abs(prog[name]["change"] - mine) <= 1e-6 * max(1.0, abs(mine)) + 1.0, (name, prog[name]["change"], mine)
# headline cost: what the Exchequer loses, from policyengine.py's programme totals: taxes forgone less
# the benefits the higher net incomes withdraw (Universal Credit, Pension Credit). "tax_credits" overlaps
# with working_tax_credit and child_tax_credit, so it is left out of the sum (see UK_PROGRAMS)
taxes = sum(v["change"] for k, v in prog.items() if v["is_tax"])
benefits = sum(v["change"] for k, v in prog.items() if not v["is_tax"] and k != "tax_credits")
budget["net_cost_2026_27_gbp"] = benefits - taxes
budget["gross_income_tax_cost_2026_27_gbp"] = -budget["income_tax_revenue_change"]
budget["benefit_change_2026_27_gbp"] = benefits
# accounting identity: households gain what the Exchequer loses, up to programmes outside UK_PROGRAMS
gap = budget["household_net_income_total_change"] - budget["net_cost_2026_27_gbp"]
budget["identity_gap_gbp"] = gap
assert abs(gap) <= 0.005 * abs(budget["net_cost_2026_27_gbp"]), (gap, budget["net_cost_2026_27_gbp"])
lap("budget")

# ------------------------------------------------------------ winners
winners = {
    "share_households_gaining_over_1gbp": float(hw[d_net > 1].sum() / total_households),
    "share_households_losing_over_1gbp": float(hw[d_net < -1].sum() / total_households),
    "total_weighted_households": total_households,
}
# a few households lose: record who, and which programmes moved for them (observed, not assumed)
lose = d_net < -1
lose_ids = set(hh_b.loc[lose, "household_id"])
bu_lose = bu_b["benunit_id"].isin(set(p_b.loc[p_b["household_id"].isin(lose_ids), "benunit_id"]))
winners["losers"] = {
    "records": int(lose.sum()),
    "weighted_households": float(hw[lose].sum()),
    "largest_loss_gbp": float(-d_net[lose].min()) if lose.any() else 0.0,
    "change_among_losers_gbp": {
        "income_tax": float((f64(p_r["income_tax"]) - f64(p_b["income_tax"]))[p_b["household_id"].isin(lose_ids).to_numpy()].sum()),
        **{v: float((f64(bu_r[v]) - f64(bu_b[v]))[bu_lose.to_numpy()].sum()) for v in ("universal_credit", "pension_credit", "housing_benefit")},
    },
    "note": "unweighted sums over the losing records; their means-tested benefits fall by more than their tax cut",
}
assert winners["share_households_losing_over_1gbp"] < 0.005, winners

# ------------------------------------------------------------ deciles
dec = []
for d in analysis.decile_impacts.outputs:
    dec.append({
        "decile": d.decile,
        "average_change_household_net_income": d.absolute_change,
        "baseline_mean": d.baseline_mean,
        "reform_mean": d.reform_mean,
        "relative_change_percent": d.relative_change,
    })
dec.sort(key=lambda r: r["decile"])
assert [r["decile"] for r in dec] == list(range(1, 11)), [r["decile"] for r in dec]
prep = _prepare_decile_analysis(baseline, reform, income_variable="household_net_income", decile_variable=None,
                                entity="household", quantiles=10)
decile_of = np.asarray(prep.groups.fillna(-1).astype(int))
# differential: the groups themselves, rebuilt from the definition rather than taken from policyengine.py.
# Households ranked by baseline household net income, each weighted by household weight x its number of
# people (counted here from the person table); a household's rank is the weight at or below its income
# (ties share the rank) over the total; tenths by ceiling; negative incomes left out (-1).
inc_b = f64(hh_b["household_net_income"])
people = p_b.groupby("household_id").size().reindex(hh_b["household_id"].values).fillna(0).to_numpy()
w_eff = hw * people
vals, inv = np.unique(inc_b, return_inverse=True)
at_or_below = np.cumsum(np.bincount(inv, weights=w_eff))[inv] / w_eff.sum()
groups = np.clip(np.ceil(at_or_below * 10), 1, 10).astype(int)
groups[inc_b < 0] = -1
assert (groups == decile_of).all(), f"{int((groups != decile_of).sum())} households grouped differently"
decile_check = {
    "households_grouped_as_policyengine_py": int((groups == decile_of).sum()),
    "households_left_out_negative_income": int((groups == -1).sum()),
    "weighted_households_left_out": float(hw[groups == -1].sum()),
    "people_share_by_decile": [float(w_eff[groups == d].sum() / w_eff.sum()) for d in range(1, 11)],
}
# differential: the decile averages recomputed from the household rows, within those groups
for r in dec:
    m = groups == r["decile"]
    mine = float(np.sum(d_net[m] * hw[m]) / np.sum(hw[m]))
    assert abs(mine - r["average_change_household_net_income"]) < 0.01, (r, mine)

# ------------------------------------------------------------ poverty
poverty = {}
for ptype, var in UK_POVERTY_VARIABLES.items():
    k = ptype.value
    cb, cr = child_b[ptype], child_r[ptype]
    ab = next(p for p in analysis.baseline_poverty.outputs if p.poverty_type == ptype and not getattr(p, "filter_group", None))
    ar = next(p for p in analysis.reform_poverty.outputs if p.poverty_type == ptype and not getattr(p, "filter_group", None))
    poverty[k] = {
        "variable": var,
        "all_people": {"rate_baseline": ab.rate, "rate_reform": ar.rate, "headcount_baseline": ab.headcount,
                       "headcount_reform": ar.headcount, "people_lifted_out": ab.headcount - ar.headcount},
        "children_under_18": {"rate_baseline": cb.rate, "rate_reform": cr.rate, "headcount_baseline": cb.headcount,
                              "headcount_reform": cr.headcount, "children_lifted_out": cb.headcount - cr.headcount,
                              "filter": "age <= 17 (policyengine.py AGE_GROUPS['child'])"},
    }
lap("aggregates")

# ------------------------------------------------------------ the map's sample (private)
# constituency_code_oa is a dataset column (from output areas), not a model variable
codes_in = pd.DataFrame(dataset.data.household).set_index("household_id")["constituency_code_oa"].astype(str)
code = codes_in.reindex(hh_b["household_id"].values).fillna("").to_numpy()
region = hh_b["region"].astype(str).to_numpy()
no_code = code == ""
assert set(region[no_code]) <= {"NORTHERN_IRELAND"}, "a household outside Northern Ireland has no constituency"
rng = np.random.default_rng(SAMPLE_SEED)
probs = hw / total_households
idx = rng.choice(len(hw), size=SAMPLE_N, replace=True, p=probs)
rows = [[NI if no_code[i] else code[i], round(float(d_net[i]), 2), int(decile_of[i])] for i in idx]
PRIVATE.mkdir(parents=True, exist_ok=True)
(PRIVATE / "households_sample.json").write_text(json.dumps({
    "columns": ["constituency_code_or_NI", "household_net_income_change", "decile"],
    "rows": rows,
}, separators=(",", ":")))
sample_meta = {
    "sampling": f"numpy default_rng({SAMPLE_SEED}).choice(households, size={SAMPLE_N}, replace=True, p=household_weight / total)",
    "n_draws": SAMPLE_N,
    "unique_households_drawn": int(len(np.unique(idx))),
    "draws_in_northern_ireland": int(sum(no_code[idx])),
    "northern_ireland_note": ("the dataset carries constituency_code_oa for Great Britain only; Northern Ireland "
                              "households (all of the uncoded ones) are placed at random anywhere in Northern Ireland"),
    "northern_ireland_weight_share": float(hw[no_code].sum() / total_households),
    "stored": "data/uk/private/households_sample.json (git-ignored; record-level survey derivative, never committed)",
}
lap("sample")

# ------------------------------------------------------------ outputs
out = {
    "meta": {
        "description": f"Personal allowance £{PA_NEW:,} in {FISCAL_YEAR}, static, enhanced FRS 2024-25 uprated to 2026",
        "reform": {"parameter": PA_PATH, "value": PA_NEW, "start_date": f"{YEAR}-01-01", "end_date": f"{YEAR}-12-31",
                   "note": "policyengine-uk labels fiscal year 2026-27 as 2026 and reads it at 2026-01-01"},
        "behavioral_responses": "none (static; no labour-supply elasticities set)",
        "dataset": {"key": dataset_key, "source": "hf://policyengine/policyengine-uk-data-private/enhanced_frs_2024_25.h5@1.56.16",
                    "sha256": source_sha, "sha256_matches_installed_policyengine_py_manifest": True,
                    "certified_for_policyengine_uk": manifest.certification.certified_for_model_version,
                    "uprated_by_policyengine_uk": MODEL,
                    "households": int(len(hh_b)), "people": int(len(p_b))},
        "versions": {**versions(), "python": platform.python_version()},
        "runtime_seconds": laps,
        "script": "tools/uk/national.py",
        "licence_note": "aggregates only; the underlying FRS microdata stay in data/uk/private/",
    },
    "budget": budget,
    "winners": winners,
    "deciles": {"by_decile": dec, "definition": "policyengine.py household_net_income deciles (economic_impact_analysis)",
                "grouping_check": decile_check},
    "allowance": allowance,
    "poverty": poverty,
    "sample": sample_meta,
}
(UK / "national.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
print(json.dumps({"net_cost_bn": round(budget["net_cost_2026_27_gbp"] / 1e9, 2),
                  "gross_cost_bn": round(budget["gross_income_tax_cost_2026_27_gbp"] / 1e9, 2),
                  "share_gaining": round(winners["share_households_gaining_over_1gbp"], 4),
                  "children_lifted_out": {k: round(v["children_under_18"]["children_lifted_out"]) for k, v in poverty.items()},
                  "deciles": [round(r["average_change_household_net_income"]) for r in dec],
                  "laps": laps}, indent=1))
