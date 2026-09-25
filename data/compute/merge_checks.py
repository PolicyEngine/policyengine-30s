"""Fold the independent policyengine_us check into national.json (Part D).

Run after national.py and national_raw_check.py:
    ../.venv/bin/python merge_checks.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, write_json  # noqa: E402

nat_path = DATA_DIR / "national.json"
raw_path = DATA_DIR / "compute" / "checks" / "national_raw_check.json"
nat = json.loads(nat_path.read_text())
raw = json.loads(raw_path.read_text())

pairs = {
    "federal_budget_cost_2026_usd": (nat["budget"]["federal_budget_cost_2026_usd"], raw["federal_budget_cost_2026_usd"]),
    "household_net_income_total_change": (nat["budget"]["household_net_income_total_change"], raw["household_net_income_weighted_change"]),
    "ctc_value_change": (nat["budget"]["ctc_value_change"], raw["ctc_value_weighted_change"]),
    "ctc_allowed_change": (nat["budget"]["ctc_allowed_change"], raw["ctc_weighted_change"]),
    "state_income_tax_revenue_change": (nat["budget"]["state_income_tax_revenue_change"], raw["state_income_tax_weighted_change"]),
    "households_total_weighted": (nat["households_total_weighted"], raw["households_total_weighted"]),
    "people_total_weighted": (nat["people_total_weighted"], raw["people_total_weighted"]),
    "share_households_gaining_over_1usd": (nat["winners"]["share_households_gaining_over_1usd"], raw["share_households_gaining_over_1usd"]),
    "share_people_in_gaining_households_hhweight_x_count": (
        nat["winners"]["share_people_in_gaining_households_alt_hhweight_x_count"],
        raw["share_people_in_gaining_households_hhweight_x_count"],
    ),
    "spm_child_rate_baseline": (nat["poverty"]["spm"]["children_under_18"]["rate_baseline"], raw["spm_child_rate_baseline"]),
    "spm_child_rate_reform": (nat["poverty"]["spm"]["children_under_18"]["rate_reform"], raw["spm_child_rate_reform"]),
    "spm_children_lifted_out": (nat["poverty"]["spm"]["children_under_18"]["children_lifted_out"], raw["spm_children_lifted_out"]),
    "spm_all_rate_baseline": (nat["poverty"]["spm"]["all_people"]["rate_baseline"], raw["spm_all_rate_baseline"]),
    "spm_all_rate_reform": (nat["poverty"]["spm"]["all_people"]["rate_reform"], raw["spm_all_rate_reform"]),
}
comparison = {}
for k, (a, b) in pairs.items():
    comparison[k] = {
        "policyengine_py": a,
        "raw_policyengine_us": b,
        "abs_diff": b - a,
        "rel_diff": (b - a) / a if a else None,
    }

nat["second_path_check"] = {
    "description": (
        "Same reform and bundle dataset (same sha256) run through policyengine_us.Microsimulation directly "
        "(no policyengine.py create_datasets / Simulation layer). See compute/national_raw_check.py."
    ),
    "raw_meta": {k: raw["meta"][k] for k in ("dataset_sha256", "dataset_uri", "spm_config", "runtime", "script")},
    "comparison": comparison,
}
# ---- gap diagnostics (compute/diagnose_gap.py, compute/crosspath_sample.py)
import glob  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

gap = json.loads((DATA_DIR / "compute" / "checks" / "gap_diagnostic.json").read_text())
cross = json.loads((DATA_DIR / "compute" / "checks" / "crosspath_sample.json").read_text())
units = pd.DataFrame(gap["tax_units"])
lim_gt_actual = float(
    (units["pepy_b.ctc_limiting_tax_liability"] > units["pepy_b.income_tax_before_credits"] + 1).mean()
)
raw_lim_le_actual = float(
    (units["raw_b.ctc_limiting_tax_liability"] <= units["raw_b.income_tax_before_credits"] + 1).mean()
)

# State income tax change by state, from the saved baseline/reform outputs.
outs = sorted(glob.glob(str(DATA_DIR / "pe_data" / "*-spm-*.h5")))
tabs = []
for p in outs:
    with pd.HDFStore(p, "r") as st:
        tabs.append((st["tax_unit"], st["person"], st["household"]))
tabs.sort(key=lambda t: float((t[0]["ctc"] * t[0]["tax_unit_weight"]).sum()))
(tb, pb, hb), (tr, _, _) = tabs
d_state = (tr["state_income_tax"].astype(float) - tb["state_income_tax"].astype(float)) * tb["tax_unit_weight"].astype(float)
tu_hh = pb.drop_duplicates("tax_unit_id").set_index("tax_unit_id")["household_id"]
hh_state = hb.set_index("household_id")["state_code_str"]
states = hh_state.reindex(tu_hh.reindex(tb["tax_unit_id"]).values).values
by_state = pd.Series(d_state.values, index=states).groupby(level=0).sum()
by_state = by_state[by_state.abs() > 1].sort_values(ascending=False)

b = nat["budget"]
sac = b["second_aggregation_check"]
nat["budget"]["state_income_tax_change_by_state"] = {k: float(v) for k, v in by_state.items()}
nat["budget"]["gap_explanation"] = {
    "revenue_vs_ctc_value": (
        f"-Δfederal income tax = ${-b['federal_income_tax_revenue_change'] / 1e9:.3f}B vs Σ weighted Δctc_value = "
        f"${b['ctc_value_change'] / 1e9:.3f}B: gap -${-sac['gap_revenue_vs_ctc_value'] / 1e6:.1f}M "
        f"({100 * sac['gap_revenue_vs_ctc_value_share']:.2f}% of Δctc_value). All of it comes from "
        f"{sac['tax_units_with_abs_residual_over_1usd']} sample tax units "
        f"({sac['weighted_tax_units_with_abs_residual_over_1usd'] / 1e3:.0f}k weighted); every other tax unit has "
        f"-Δincome_tax = Δctc_value to within $1. {100 * gap['summary']['pepy_share_itemizing_baseline']:.1f}% of those units itemize. "
        f"For {100 * lim_gt_actual:.1f}% of them, ctc_limiting_tax_liability exceeds income_tax_before_credits "
        f"(mean of limiting minus actual pre-credit tax over all {sac['tax_units_with_abs_residual_over_1usd']} units: "
        f"+${gap['summary']['pepy_mean_limiting_minus_actual_before_credits']:,.0f}). policyengine-us computes that "
        "liability in a side branch with salt_deduction set to 0; its documentation says it excludes SALT to avoid "
        "circular dependencies. So ctc_value counts nonrefundable CTC these units cannot use, and their refundable CTC "
        "is computed against the higher no-SALT liability. Result: the revenue change is smaller than Δctc_value."
    ),
    "ctc_allowed_vs_value": (
        f"Σ weighted Δctc (credit allowed after phase-out, before the tax-liability limit) = ${b['ctc_allowed_change'] / 1e9:.3f}B, "
        f"of which ${sac['weighted_ctc_allowed_but_not_realized_change'] / 1e9:.3f}B is not realized (Δctc - Δctc_value) across "
        f"{sac['weighted_tax_units_with_unrealized_ctc_increase_over_1usd'] / 1e6:.2f}M weighted tax units. Those tax units lack enough "
        "income tax liability to use the higher nonrefundable credit, and their refundable portion is still capped at "
        "gov.irs.credits.ctc.refundable.individual_max per child and by the earned-income phase-in. The reform does not change either limit."
    ),
    "net_income_vs_federal_revenue": (
        f"Σ Δhousehold_net_income = ${b['household_net_income_total_change'] / 1e9:.3f}B is ${-sac['net_income_vs_federal_revenue_gap'] / 1e6:.1f}M "
        f"below the federal revenue loss because state income taxes rise on net by ${b['state_income_tax_revenue_change'] / 1e6:.1f}M. "
        "By state: "
        + ", ".join(f"{k} {v / 1e6:+.2f}M" for k, v in by_state.items())
        + ". This follows the policyengine-us formulas: Alabama (al_federal_income_tax_deduction), Oregon "
        "(or_federal_tax_liability_subtraction) and Missouri (mo_federal_income_tax_deduction) let filers deduct federal "
        "income tax, so a lower federal tax raises state tax. Oklahoma's child credit is based on the federal CTC "
        "(ok_federal_ctc), so it grows and state tax falls. Payroll tax and household_benefits do not change."
    ),
}
nat["second_path_check"]["explanation"] = (
    "The two paths agree exactly on households and people (weighted), CTC allowed (Σ weighted ctc) and child SPM poverty "
    "(to about 1e-9); all-person SPM rates differ by about 1e-4 relative. They differ on the federal income tax change by "
    f"{100 * comparison['federal_budget_cost_2026_usd']['rel_diff']:.2f}%. On the 128 flagged tax units "
    "(compute/diagnose_gap.py), the paths match on income_tax_before_credits, salt_deduction, tax_unit_itemizes and ctc. "
    "They differ only on ctc_limiting_tax_liability, and from it on refundable_ctc, ctc_value and income_tax. "
    f"In the policyengine.py path the limiting liability exceeds actual pre-credit tax for {100 * lim_gt_actual:.1f}% of those units. "
    f"In the direct policyengine_us path it is at or below actual pre-credit tax for {100 * raw_lim_le_actual:.1f}% of them. "
    f"In a uniform random subset of {cross['summary']['n_households']:,} households (compute/crosspath_sample.py), "
    f"every one of the {cross['summary']['tax_units_where_d_income_tax_differs_over_1usd']} tax units whose Δincome_tax differs "
    f"between paths also has a different ctc_limiting_tax_liability; {cross['summary']['of_which_itemize_with_positive_salt']} of them "
    "itemize with positive SALT. So the gap between paths is confined to how the no-SALT side branch evaluates for SALT "
    "itemizers under each construction path (itemization choice also differs for a few units). We did not trace the "
    "root cause inside policyengine-core's branch mechanics."
)
nat["second_path_check"]["diagnostics"] = {
    "flagged_units": {k: v for k, v in gap["summary"].items()},
    "flagged_units_share_pepy_limiting_gt_actual": lim_gt_actual,
    "flagged_units_share_raw_limiting_le_actual": raw_lim_le_actual,
    "crosspath_random_subset": cross["summary"],
    "files": ["compute/checks/gap_diagnostic.json", "compute/checks/crosspath_sample.json"],
}

nat["meta"]["dataset_selection_note"] = (
    "Dataset = the default US dataset of the latest released policyengine.py (6.1.1, PyPI 2026-09-22): "
    "manifest data_releases.us.default_dataset_uri = "
    "hf://policyengine/populace-us/populace_us_2024.h5@populace-us-2024-spm-20260915. "
    "Observed 2026-09-24: PolicyEngine/policyengine-api master (aac95d3) pins policyengine[models]==5.2.0 in "
    "pyproject.toml and uv.lock; the 5.2.0 bundle manifest's US default is "
    "populace_us_2024.h5@populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z. We did not trace the "
    "API's runtime-bundle/worker routing, so the live app's national run may use that older build; these numbers "
    "use the 6.1.1 default as the latest release."
)
write_json(nat_path, nat)
for k, v in comparison.items():
    print(f"{k:55s} {v['policyengine_py']:>22,.6f} {v['raw_policyengine_us']:>22,.6f} rel {v['rel_diff']}")

# Same dataset note on the dot-map sample.
sample_path = DATA_DIR / "households_sample.json"
sample = json.loads(sample_path.read_text())
sample["meta"]["dataset_selection_note"] = nat["meta"]["dataset_selection_note"]
write_json(sample_path, sample, compact=True)
